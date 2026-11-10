"""Flat geometry from a reviewed selection mask (docs/plans/2026-11-10-flat-geometry.md).

The reference outline is the exact pixel-cell outline: the union of the mask's pixel
squares, with each pixel (column x, row y) the cell [x, x + 1] x [y, y + 1]. It has no
half-pixel bias, unlike OpenCV centre tracing, which runs through pixel centres and
shrinks the outline by half a pixel (rule `vectorize.opencv.contour_offset_px`). Its
staircase edge is one pixel high. make_flat smooths the outline by default with
tdmg.smoothing.smooth_outline (rule flat.smooth.sigma_px), which uses the same pixel-cell
coordinates; smooth_px=0 keeps the exact outline.

The image-to-model transform is x_mm = (x_px - x0) * s and y_mm = (y1 - y_px) * s, where
x0 and y1 are the left and bottom edges of the outline's bounding box in pixels and
s = width_mm / (x1 - x0). Model +Y is image up, and the bounding box's lower-left corner
is at the origin.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
from importlib.metadata import version as package_version
from pathlib import Path

import manifold3d
import numpy as np
import shapely
import trimesh
from shapely import affinity
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

from tdmg import __version__
from tdmg._masks import binary_cells
from tdmg.checks import F1_CHECK_IDS, CheckResult, merge_exact, topology_checks, verdict
from tdmg.profiles import PrinterProfile, load_printer, printer_ids
from tdmg.records import (
    RecordError,
    canonical_json,
    check_output_dir,
    environment,
    png_bytes,
    record_text,
    write_outputs,
)
from tdmg.rules import load_rules
from tdmg.selection import RECORD_SCHEMA as SELECTION_SCHEMA
from tdmg.selection import SelectionError, load_mask, pixels_sha256, selection_identity
from tdmg.smoothing import METHOD as SMOOTHING_METHOD
from tdmg.smoothing import SmoothingError, smooth_outline

QUAD_SEGS = 8  # Buffer arcs per quarter circle. Chord error is r*(1-cos(pi/32)), about
               # 0.001 mm at r = 0.2 mm, far below a layer. An approximation setting.
HAUSDORFF_STEP_PX = 0.25  # Boundary sampling step for the measured change, in pixels.
                          # A measurement resolution, not a threshold: the caller passes
                          # HAUSDORFF_STEP_PX * scale_mm_per_px as clean's sample_step_mm.
DROPPED_LISTED = 10  # Display only: how many dropped-island areas the report lists.
THIN_LISTED = 5  # Display only: how many thin-region pieces the F3 measurement lists.
DISPLAY_DECIMALS = 3  # Display rounding of listed thin-region areas and centroids (mm).
# F2.target_width compares scale x mask width, both float64, with the requested width. The
# scale is width / mask width, so the product differs from width only by the rounding of one
# division and one multiplication, each at most 2^-53 (1.1e-16) relative: about 2.2e-16 in
# all. 1e-9 is a loose margin for this computed equality, not a physical tolerance.
WIDTH_RTOL = 1e-9
# Binary STL stores float32. Rounding to nearest moves a coordinate x by at most
# |x| * 2^-24; F2.export_matches_geometry allows twice that, 2^-23, relative to the largest
# expected coordinate. Not a physical tolerance either: storage rounding only.
STL_COORD_RTOL = 2.0 ** -23
HEX64 = re.compile(r"[0-9a-f]{64}")
THIN_RULE = "fdm.wall.min_thickness"
TRIANGLE_RULE = "slicer.orca.max_triangles_per_plate"
OPENING_RULE = "flat.sliver.opening_width"
ISLAND_RULE = "flat.island.min_square_side"
SMOOTH_RULE = "flat.smooth.sigma_px"
# flat-2 (2026-11-10): the outline is smoothed by default (smooth_px), and params.smoothing
# records it. flat-1 always used the exact pixel outline (smooth_px=0 here).
FLAT_ALGORITHM_VERSION = "flat-2"
RECORD_SCHEMA = "tdmg.flat/1"
# outline.png display colours only; these are not thresholds.
OUTLINE_KEPT = (128, 128, 128)        # grey: in the mask and in the final shape
OUTLINE_REMOVED = (220, 40, 40)       # red: in the mask, not in the final shape
OUTLINE_ADDED = (40, 90, 220)         # blue: outside the mask, in the final shape
OUTLINE_BACKGROUND = (255, 255, 255)  # white: in neither
REVIEW = ("Open outline.png: grey is in the mask and kept; red is in the mask but not in "
          f"the model, removed by smoothing ({SMOOTH_RULE}, when on) or by the cleaning "
          f"rules ({OPENING_RULE}, {ISLAND_RULE}); blue is outside the mask but in the "
          "model, added by smoothing. All three rules are untested hypotheses. Smoothing "
          "and cleaning both round convex corners. The verdict stays NOT CERTIFIED until "
          "F3 policy and slicer checks exist.")
# Every check the flat gate needs. F3 and F6 are UNKNOWN until their policy and slicer
# integration exist, so the verdict is NOT CERTIFIED for now.
FLAT_REQUIRED_CHECKS = F1_CHECK_IDS | {"F2.fits_build_volume", "F2.target_width",
                                       "F2.export_matches_geometry", "F3.thin_regions",
                                       "F4.body_count", "F5.triangles", "F6.slicer"}


class FlatError(ValueError):
    """The selection cannot be made into flat geometry as asked. Nothing is written."""


def _cells(mask: np.ndarray) -> np.ndarray:
    return binary_cells(mask, FlatError)


def mask_outline(mask: np.ndarray) -> shapely.Geometry:
    """Exact pixel-cell outline, in pixel units (x right, y down), as a union of row runs.

    The mask is bool, or integer with only 0 and 255 (255 is foreground). Collinear
    vertices left by the union are removed; the geometry is unchanged.
    """
    cells = _cells(mask)
    if not cells.any():
        raise FlatError("no printable foreground")
    padded = np.zeros((cells.shape[0], cells.shape[1] + 2), np.int8)
    padded[:, 1:-1] = cells
    edges = np.diff(padded, axis=1)
    ys, xs = np.nonzero(edges == 1)  # row-major, so the k-th start pairs with the k-th end
    _, xe = np.nonzero(edges == -1)
    boxes = shapely.box(xs, ys, xe, ys + 1)
    return shapely.simplify(shapely.union_all(boxes), 0)


def _number(name: str, value) -> float:
    """value as a float; bools, strings and other non-numbers raise FlatError."""
    if isinstance(value, bool):
        raise FlatError(f"{name} must be a number, got {value!r}")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise FlatError(f"{name} must be a number, got {value!r}") from None


def _require_positive(name: str, value: float) -> float:
    value = _number(name, value)
    if not math.isfinite(value) or value <= 0:
        raise FlatError(f"{name} must be a finite number above 0, got {value}")
    return value


def to_model(outline, width_mm: float) -> tuple[shapely.Geometry, dict]:
    """Scale to width_mm, flip Y, and put the bounding box's lower-left at the origin.

    The transform dict gives the scale and the bounding box of the outline in pixels
    (mask_width_px and mask_height_px are the outline's extents, not the image size; for a
    smoothed outline they are the smoothed extents).
    """
    width_mm = _require_positive("width_mm", width_mm)
    if outline.is_empty or outline.area <= 0:
        raise FlatError("no printable foreground")
    x0, y0, x1, y1 = (float(v) for v in outline.bounds)
    s = width_mm / (x1 - x0)
    transform = {"scale_mm_per_px": s, "x0_px": x0, "y1_px": y1,
                 "mask_width_px": x1 - x0, "mask_height_px": y1 - y0}
    return _apply_transform(outline, transform), transform


def _apply_transform(outline, transform: dict) -> shapely.Geometry:
    """outline (pixel units) in model mm, by a transform from to_model."""
    s, x0, y1 = transform["scale_mm_per_px"], transform["x0_px"], transform["y1_px"]
    return affinity.affine_transform(outline, [s, 0.0, 0.0, -s, -x0 * s, y1 * s])


def _require_non_negative(name: str, value: float) -> float:
    value = _number(name, value)
    if not math.isfinite(value) or value < 0:
        raise FlatError(f"{name} must be a finite number of at least 0, got {value}")
    return value


def _polygons(geom) -> tuple[list[Polygon], int]:
    """Polygons in geom, read recursively, and the count of non-polygonal parts skipped."""
    if geom.is_empty:
        return [], 0
    if isinstance(geom, Polygon):
        return [geom], 0
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        found, skipped = [], 0
        for sub in geom.geoms:
            polys, n = _polygons(sub)
            found.extend(polys)
            skipped += n
        return found, skipped
    return [], 1


def _order_key(part: Polygon) -> tuple:
    return (-part.area, part.bounds)


def _boundary_segments(geom) -> np.ndarray:
    """Every boundary segment of geom as LineStrings."""
    segments = []
    for line in shapely.get_parts(geom.boundary):
        xy = shapely.get_coordinates(line)
        segments.append(np.stack([xy[:-1], xy[1:]], axis=1))
    return shapely.linestrings(np.concatenate(segments))


def _directed_distance(source, target, step: float) -> float:
    """Largest distance from source's boundary, sampled at step, to the region target."""
    xy = shapely.get_coordinates(shapely.segmentize(source.boundary, step))
    shapely.prepare(target)
    # Samples in the target or on its boundary are at distance 0; only the rest need the tree.
    outside = xy[~shapely.intersects_xy(target, xy[:, 0], xy[:, 1])]
    if len(outside) == 0:
        return 0.0
    tree = shapely.STRtree(_boundary_segments(target))
    _, distances = tree.query_nearest(shapely.points(outside), return_distance=True)
    return float(distances.max())


def _sampled_hausdorff(a, b, step: float) -> float:
    """Sampled boundary-to-region distance between regions a and b, taken both ways.

    Each boundary is split into pieces no longer than step, and every vertex is a sample.
    A sample covered by the other REGION is at distance 0, else at its exact distance to
    the other region (its nearest boundary point). The result is the larger of the two
    directions. What it is and is not:
    - It is within step / 2 below the boundary-to-region value, the sup over boundary
      points of a of d(., b) and of b of d(., a): every boundary point is within step / 2
      of a sample, and d(., region) is 1-Lipschitz.
    - It is a lower bound of the two-sided region Hausdorff distance, since the samples
      are points of the regions. It does not see interior points: clean reports a derived
      upper bound for the region distance.
    - It is NOT the boundary-to-boundary distance. A change enclosed by the other region
      counts 0: a hole of a that b fills has its boundary inside b, so the hole is
      under-reported against how far the boundary moved.
    GEOS's plain hausdorff_distance looks only at vertices, so it misses a removed bar
    whose middle has no vertex. a and b must be non-empty; clean guarantees that.
    """
    return max(_directed_distance(a, b, step), _directed_distance(b, a, step))


def _hausdorff_upper_bound(boundary: float, step: float, radius: float,
                           largest_dropped_mm2: float) -> float:
    """Derived bound on the region Hausdorff distance between before and after cleaning.

    Derivation, for the exact opening by a disk of radius r, then the polygonal one:
    1. after -> before. after lies inside before, so this side is 0. The polygonal
       buffers can poke out of before by at most the chord error e (measured 0.0003 mm
       at a hair's root, under e = 0.00096 mm), and e is added below.
    2. before -> after, for a point x of before not in after, with d = d(x, boundary of
       before). If d >= r, the disk of radius r at x lies in before, so x is in the
       opening. So a point the opening removed has d < r. Otherwise x is in a dropped
       island D. If d >= r, every point within d - r of x survives the erosion, so D
       holds the disk of radius d around x, area(D) >= pi d^2 and d <= rho_D =
       sqrt(area(D) / pi). So d <= max(r, rho) with rho for the largest dropped island.
    3. d(., after) is 1-Lipschitz, so d(x, after) <= d + sup over the boundary of before
       of d(., after). That sup is at most the sampled value plus step / 2, because every
       boundary point is within step / 2 of a sample.
    4. Polygonal buffers: the erosion's polygon lies inside the true disk, so it erodes
       no more than the exact one, and point 2's "d >= r means kept" still holds. The
       dilation's polygon holds the disk of radius r - e, which shrinks the disk of
       point 2 by e: d <= rho + e. Adding e to the whole bound covers both cases.
    """
    rho = math.sqrt(largest_dropped_mm2 / math.pi)
    chord_error = radius * (1 - math.cos(math.pi / (4 * QUAD_SEGS)))
    return boundary + step / 2 + max(radius, rho) + chord_error


def clean(geom_mm, opening_mm: float, min_island_mm2: float,
          sample_step_mm: float) -> tuple[list[Polygon], dict]:
    """Open by opening_mm (round joins, QUAD_SEGS); split into polygons; drop small parts.

    The opening and the island limit come from the cleaning rules (hypotheses, untested
    on a printer). The opening removes features narrower than opening_mm and also rounds
    every convex corner to radius opening_mm / 2. opening_mm must be above 0: the opening
    is what separates parts that touch only at a corner.

    Measured at the boundary (Shapely 2.2.0, GEOS 3.14.1, QUAD_SEGS = 8): the erosion of a
    feature collapses to nothing unless it is wider than opening_mm by about 5e-5 of
    opening_mm. A 10 mm rectangle 0.40001 mm high is removed at opening 0.4 mm; one 0.4001
    mm high is kept. So features at, or within that margin above, the opening width are
    removed (tests/test_flat.py pins this).

    Returns the parts, largest first, and a report with a fixed key set:
    opening_mm, min_island_mm2, area_before_mm2, area_after_mm2, removed_area_mm2,
    boundary_hausdorff_mm, hausdorff_upper_bound_mm, hausdorff_sample_step_mm,
    dropped_islands {count, total_area_mm2, largest_mm2} for parts the opening left below
    min_island_mm2, vanished_parts {count, total_area_mm2} for input parts the opening
    erased entirely, and ignored_non_polygonal, the count of lines and points in the
    input, which have no printable area.

    boundary_hausdorff_mm is _sampled_hausdorff at sample_step_mm: the boundary-to-region
    distance (0 for samples inside the other region), both ways, within step / 2 of it; a
    lower bound of the two-sided region Hausdorff distance, and not the boundary-to-
    boundary distance (see _sampled_hausdorff).
    hausdorff_upper_bound_mm is a derived (not measured) bound on the true Hausdorff
    distance between the regions before and after cleaning:
        boundary_hausdorff_mm + step / 2 + max(r, rho) + e,
    with r = opening_mm / 2, rho = sqrt(largest dropped island area / pi) (0 if none)
    and e = r * (1 - cos(pi / (4 * QUAD_SEGS))), the buffer chord error. See
    _hausdorff_upper_bound for the derivation.
    """
    opening_mm = _require_positive("opening_mm", opening_mm)
    min_island_mm2 = _require_non_negative("min_island_mm2", min_island_mm2)
    sample_step_mm = _require_positive("sample_step_mm", sample_step_mm)
    if isinstance(geom_mm, (Polygon, MultiPolygon)) and geom_mm.is_valid:
        before, skipped = geom_mm, 0
    else:
        polys, skipped = _polygons(geom_mm)
        before = shapely.union_all(polys)
    radius = opening_mm / 2
    eroded = before.buffer(-radius, quad_segs=QUAD_SEGS)
    opened = eroded.buffer(radius, quad_segs=QUAD_SEGS)

    inputs = np.asarray(_polygons(before)[0], dtype=object)
    shapely.prepare(eroded)
    vanished = inputs[~shapely.intersects(eroded, inputs)] if len(inputs) else inputs
    candidates, _ = _polygons(opened)
    candidates.sort(key=_order_key)
    parts = [p for p in candidates if p.area >= min_island_mm2]
    dropped = sorted((float(p.area) for p in candidates if p.area < min_island_mm2),
                     reverse=True)
    area_before = float(before.area)
    area_after = float(sum(p.area for p in parts))
    if not parts:
        raise FlatError("nothing printable remains after cleaning (removed "
                        f"{area_before - area_after:.6g} mm^2 of {area_before:.6g} mm^2)")
    after = shapely.union_all(parts)
    boundary = _sampled_hausdorff(before, after, sample_step_mm)
    report = {"opening_mm": opening_mm, "min_island_mm2": min_island_mm2,
              "area_before_mm2": area_before, "area_after_mm2": area_after,
              "removed_area_mm2": area_before - area_after,
              "boundary_hausdorff_mm": boundary,
              "hausdorff_upper_bound_mm": _hausdorff_upper_bound(
                  boundary, sample_step_mm, radius, dropped[0] if dropped else 0.0),
              "hausdorff_sample_step_mm": sample_step_mm,
              "dropped_islands": {"count": len(dropped),
                                  "total_area_mm2": float(sum(dropped)),
                                  "largest_mm2": dropped[:DROPPED_LISTED]},
              "vanished_parts": {"count": len(vanished),
                                 "total_area_mm2": float(sum(p.area for p in vanished))},
              "ignored_non_polygonal": skipped}
    return parts, report


def extrude(parts: list[Polygon], thickness_mm: float) -> trimesh.Trimesh:
    """manifold3d extrusion of oriented rings (FillRule.Positive). Raises FlatError if empty.

    Exteriors are made counter-clockwise and holes clockwise, so under the Positive fill
    rule each hole subtracts and separate parts stay separate. The solid spans z = 0 to
    thickness_mm. Vertices come from manifold3d's float64 mesh.
    """
    thickness_mm = _require_positive("thickness_mm", thickness_mm)
    rings = []
    for part in parts:
        if part.is_empty:
            continue
        oriented = shapely.orient_polygons(part)
        for ring in (oriented.exterior, *oriented.interiors):
            rings.append(np.asarray(ring.coords, dtype=np.float64)[:-1])
    if not rings:
        raise FlatError("nothing to extrude")
    section = manifold3d.CrossSection(rings, manifold3d.FillRule.Positive)
    solid = manifold3d.Manifold.extrude(section, thickness_mm)
    status = solid.status()
    if status != manifold3d.Error.NoError:
        raise FlatError(f"extrusion failed: manifold3d status {status.name}")
    if solid.is_empty():
        raise FlatError("nothing to extrude")
    mesh = solid.to_mesh64()
    vertices = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    faces = np.asarray(mesh.tri_verts, dtype=np.int64)
    return trimesh.Trimesh(vertices, faces, process=False, validate=False)


# --- Gate checks F2-F6 for flat output (F1 is tdmg.checks.topology_checks) ------------


def thin_regions(parts: list[Polygon], min_width_mm: float) -> dict:
    """Where the solid is narrower than min_width_mm: union(parts) minus its opening.

    The opening (round joins, QUAD_SEGS) is by a disk of diameter min_width_mm, so what it
    removes is every region a disk of that width cannot reach. Convex corners always lose a
    sliver (r^2 (1 - pi/4) for a right angle, r = min_width_mm / 2), so every outline has
    some thin area. As in clean, the erosion collapses numerically for a feature within
    about 5e-5 of min_width_mm above it (measured: a 10 mm rectangle 0.90001 mm high is
    all thin at 0.9 mm, one 0.9001 mm high only at its corners), so such features count
    as thin. Returns min_width_mm, the total area, the number of pieces and the
    largest THIN_LISTED pieces by area, each with its area and centroid in model mm,
    rounded to DISPLAY_DECIMALS for display.
    """
    min_width_mm = _require_positive("min_width_mm", min_width_mm)
    union = shapely.union_all(parts)
    radius = min_width_mm / 2
    opened = union.buffer(-radius, quad_segs=QUAD_SEGS).buffer(radius, quad_segs=QUAD_SEGS)
    pieces, _ = _polygons(union.difference(opened))
    pieces.sort(key=_order_key)
    largest = [{"area_mm2": round(float(p.area), DISPLAY_DECIMALS),
                "centroid_mm": [round(float(p.centroid.x), DISPLAY_DECIMALS),
                                round(float(p.centroid.y), DISPLAY_DECIMALS)]}
               for p in pieces[:THIN_LISTED]]
    return {"min_width_mm": min_width_mm, "area_mm2": float(sum(p.area for p in pieces)),
            "pieces": len(pieces), "largest": largest}


def thin_region_check(parts: list[Polygon], rules: dict) -> CheckResult:
    """F3.thin_regions: always UNKNOWN for now, with the measurement.

    It measures the cleaned polygons, not the mesh. F2.export_matches_geometry ties the
    mesh to those polygons (bounds and volume), so the measurement applies to the export.
    """
    threshold = rules[THIN_RULE].default
    return CheckResult("F3.thin_regions", "UNKNOWN", thin_regions(parts, threshold),
                       threshold, THIN_RULE,
                       "tapered tips always appear; pass/fail policy pending research on "
                       "slicer handling of narrow features")


def _signed_volume(mesh: trimesh.Trimesh) -> float:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    tri = vertices[np.asarray(mesh.faces, dtype=np.int64)]
    return float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6)


def _extents(mesh: trimesh.Trimesh) -> list[float]:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    return [float(v) for v in vertices.max(axis=0) - vertices.min(axis=0)]


def build_volume_check(mesh: trimesh.Trimesh, printer: PrinterProfile) -> CheckResult:
    """F2.fits_build_volume: the mesh extents fit the printer's build volume, axis by axis.

    The printer profile, not the rules registry, is the source, so rule is None.
    """
    extents = _extents(mesh)
    volume = [float(v) for v in printer.build_volume_mm]
    ok = all(e <= v for e, v in zip(extents, volume, strict=True))
    return CheckResult("F2.fits_build_volume", "PASS" if ok else "FAIL", extents, volume,
                       None, f"threshold is build_volume_mm from printer profile {printer.id}; "
                             "axes as placed, no rotation tried")


def target_width_check(transform: dict, width_mm: float, mesh: trimesh.Trimesh) -> CheckResult:
    """F2.target_width: the scale maps the mask's bounding-box width to width_mm.

    It judges the scale only. The mesh width is reported, and F2.export_matches_geometry
    checks it against the cleaned outline.
    """
    scaled = transform["scale_mm_per_px"] * transform["mask_width_px"]
    ok = math.isclose(scaled, width_mm, rel_tol=WIDTH_RTOL, abs_tol=0.0)
    extents = _extents(mesh)
    size = " x ".join(f"{e:.6g}" for e in extents)
    return CheckResult("F2.target_width", "PASS" if ok else "FAIL",
                       {"scaled_mask_width_mm": scaled, "mesh_width_mm": extents[0]},
                       float(width_mm), None,
                       f"the mask's width is scaled to the requested width; final extents "
                       f"after cleaning are {size} mm, which can be smaller because cleaning "
                       "removes material; the mesh width is checked against the cleaned "
                       "outline by F2.export_matches_geometry")


def export_check(mesh: trimesh.Trimesh, parts: list[Polygon],
                 thickness_mm: float) -> CheckResult:
    """F2.export_matches_geometry: the mesh read back from the STL is the intended solid.

    Compares the mesh with the cleaned parts extruded to thickness_mm:
    - x and y bounds equal the parts' bounds, and the z range is [0, thickness_mm], each
      within coord_tol = STL_COORD_RTOL x the largest expected |coordinate|;
    - the volume equals area x thickness_mm within volume_tol. Moving every vertex by at
      most coord_tol per axis (sqrt(3) coord_tol in distance) changes the enclosed volume
      by at most about surface area x sqrt(3) coord_tol, to first order. The prism's
      surface area is 2 x area + perimeter x thickness; volume_tol doubles the product for
      the second-order terms.
    Both tolerances cover float32 storage only, so a scaled, shifted or reshaped export
    FAILs. The thresholds are derived, not rules, so rule is None.
    """
    region = shapely.union_all(parts)
    expected_xy = [float(v) for v in region.bounds]
    expected_z = [0.0, float(thickness_mm)]
    area = float(sum(p.area for p in parts))
    expected_volume = area * thickness_mm
    largest = max(max(abs(v) for v in expected_xy), thickness_mm)
    coord_tol = largest * STL_COORD_RTOL
    surface = 2 * area + float(region.length) * thickness_mm
    volume_tol = 2 * math.sqrt(3) * coord_tol * surface
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    xy = [float(low[0]), float(low[1]), float(high[0]), float(high[1])]
    z = [float(low[2]), float(high[2])]
    bound_error = max(abs(a - b) for a, b in zip(xy + z, expected_xy + expected_z,
                                                strict=True))
    volume = _signed_volume(mesh)
    volume_error = abs(volume - expected_volume)
    ok = bound_error <= coord_tol and volume_error <= volume_tol
    return CheckResult(
        "F2.export_matches_geometry", "PASS" if ok else "FAIL",
        {"xy_bounds_mm": xy, "z_range_mm": z, "volume_mm3": volume,
         "max_bound_error_mm": bound_error, "volume_error_mm3": volume_error},
        {"xy_bounds_mm": expected_xy, "z_range_mm": expected_z,
         "volume_mm3": expected_volume, "coord_tol_mm": coord_tol,
         "volume_tol_mm3": volume_tol},
        None, "tolerances cover float32 storage in the STL only (derived, not rules)")


def _body_count(mesh: trimesh.Trimesh) -> int:
    with np.errstate(all="ignore"):
        return len(mesh.split(only_watertight=False, repair=False))


def body_count_check(mesh: trimesh.Trimesh) -> CheckResult:
    """F4.body_count: PASS for one body; with more, UNKNOWN, since that is the user's call."""
    n = _body_count(mesh)
    if n == 1:
        return CheckResult("F4.body_count", "PASS", n, 1, None)
    return CheckResult("F4.body_count", "UNKNOWN", n, 1, None,
                       "separate pieces print loose; join them or accept")


def triangle_check(mesh: trimesh.Trimesh, rules: dict) -> CheckResult:
    """F5.triangles: the triangle count is within the slicer's per-plate limit."""
    limit = rules[TRIANGLE_RULE].default
    n = len(mesh.faces)
    return CheckResult("F5.triangles", "PASS" if n <= limit else "FAIL", n, limit,
                       TRIANGLE_RULE)


def slicer_check() -> CheckResult:
    """F6.slicer: UNKNOWN until a slicer is installed and wrapped."""
    return CheckResult("F6.slicer", "UNKNOWN", None, None, None, "no slicer integration yet")


def flat_checks(mesh: trimesh.Trimesh, parts: list[Polygon], transform: dict,
                width_mm: float, thickness_mm: float, printer: PrinterProfile,
                rules: dict) -> list[CheckResult]:
    """The F2-F6 checks, on an exactly merged mesh and the cleaned parts it came from."""
    return [build_volume_check(mesh, printer), target_width_check(transform, width_mm, mesh),
            export_check(mesh, parts, thickness_mm), thin_region_check(parts, rules),
            body_count_check(mesh), triangle_check(mesh, rules), slicer_check()]


# --- Run from a selection folder and write the outputs (S2-S4, S8) -------------------


def rasterise(parts: list[Polygon], transform: dict, shape: tuple[int, int]) -> np.ndarray:
    """H x W bool: the pixels of the mask's grid whose centres lie inside the parts.

    Pixel (col, row) is the cell [col, col + 1) x [row, row + 1) in pixel units; it counts
    as kept when its centre (col + 0.5, row + 0.5), mapped to model mm by to_model's
    transform, is inside a part (shapely's contains_xy, an exact point-in-polygon test),
    so no edge-fill convention is involved. A centre lies half a pixel from every cell
    edge, so a part bounded by pixel-cell edges rasterises to exactly its cells, and
    rounding in the inverse transform cannot move a centre across such an edge.
    """
    h, w = shape
    kept = np.zeros((h, w), bool)
    if not parts:
        return kept
    s, x0, y1 = transform["scale_mm_per_px"], transform["x0_px"], transform["y1_px"]
    region = shapely.union_all(parts)
    minx, miny, maxx, maxy = region.bounds
    # The region's bounding box in pixel columns and rows, widened by one pixel each way.
    c0 = max(math.floor(minx / s + x0) - 1, 0)
    c1 = min(math.ceil(maxx / s + x0) + 1, w)
    r0 = max(math.floor(y1 - maxy / s) - 1, 0)
    r1 = min(math.ceil(y1 - miny / s) + 1, h)
    if c0 >= c1 or r0 >= r1:
        return kept
    cols, rows = np.meshgrid(np.arange(c0, c1), np.arange(r0, r1))
    x_mm = (cols + 0.5 - x0) * s
    y_mm = (y1 - (rows + 0.5)) * s
    shapely.prepare(region)
    kept[r0:r1, c0:c1] = shapely.contains_xy(region, x_mm, y_mm)
    return kept


def _outline_image(mask: np.ndarray, kept: np.ndarray) -> np.ndarray:
    """H x W x 3: grey in mask and kept, red in mask only, blue kept only, the rest white."""
    image = np.empty((*mask.shape, 3), np.uint8)
    image[...] = OUTLINE_BACKGROUND
    image[mask & ~kept] = OUTLINE_REMOVED
    image[~mask & kept] = OUTLINE_ADDED
    image[mask & kept] = OUTLINE_KEPT
    return image


def _read_selection(selection_dir: Path) -> tuple[dict, np.ndarray]:
    """selection.json and the verified mask (bool, image-sized)."""
    record_path = selection_dir / "selection.json"
    if not record_path.is_file():
        raise FlatError(f"{record_path} not found; give a tdmg select output folder")
    try:
        record = json.loads(record_path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise FlatError(f"{record_path} is not valid JSON: {e}") from None
    if not isinstance(record, dict) or record.get("schema") != SELECTION_SCHEMA:
        raise FlatError(f"{record_path} is not a {SELECTION_SCHEMA} record")
    _check_provenance(record, record_path)
    w, h = record["input"]["width"], record["input"]["height"]
    expected = record["mask_pixels_sha256"]
    mask_path = selection_dir / "mask.png"
    if not mask_path.is_file():
        raise FlatError(f"{mask_path} not found")
    try:
        mask = load_mask(mask_path, (h, w))
    except SelectionError as e:
        raise FlatError(f"mask.png cannot be used: {e}") from None
    if pixels_sha256(mask) != expected:
        raise FlatError("mask.png does not match selection.json")
    return record, mask


def _check_provenance(record: dict, record_path: Path) -> None:
    """The fields that identify the selection are present, and selection_id matches them.

    The id is recomputed with selection.selection_identity, the definition write_selection
    uses, so an edited control, instruction or input hash with the old id is refused.
    """
    size = record.get("input")
    if not isinstance(size, dict):
        raise FlatError(f"{record_path} has no input block")
    if not all(type(size.get(k)) is int and size[k] > 0 for k in ("width", "height")):
        raise FlatError(f"{record_path} has no valid input width and height")
    interpretation = record.get("interpretation")
    fields = {"algorithm": isinstance(record.get("algorithm"), str),
              "controls": isinstance(record.get("controls"), dict),
              "input.pixels_sha256": _is_hex64(size.get("pixels_sha256")),
              "interpretation.text": isinstance(interpretation, dict)
              and "text" in interpretation
              and isinstance(interpretation["text"], (str, type(None))),
              "mask_pixels_sha256": _is_hex64(record.get("mask_pixels_sha256")),
              "selection_id": _is_hex64(record.get("selection_id"))}
    bad = [name for name, ok in fields.items() if not ok]
    if bad:
        raise FlatError(f"{record_path} is missing or has invalid: {', '.join(bad)}")
    try:
        recomputed = selection_identity(record["algorithm"], size["pixels_sha256"],
                                        record["controls"], interpretation["text"])
    except ValueError as e:          # NaN in the controls, or text UTF-8 cannot encode
        raise FlatError(f"selection.json is inconsistent: its identity cannot be "
                        f"recomputed ({e})") from None
    if recomputed != record["selection_id"]:
        raise FlatError("selection.json is inconsistent: selection_id does not match its "
                        "algorithm, input pixels, controls and instructions")


def _is_hex64(value) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _encode_stl(mesh: trimesh.Trimesh) -> bytes:
    """Binary STL bytes (float32 coordinates). The gate parses exactly these bytes."""
    return mesh.export(file_type="stl")


def _mesh_summary(mesh: trimesh.Trimesh) -> dict:
    return {"triangles": len(mesh.faces), "bodies": _body_count(mesh),
            "volume_mm3": _signed_volume(mesh), "extents_mm": _extents(mesh)}


def _flat_environment() -> dict:
    """records.environment() plus the geometry libraries the mesh bytes depend on."""
    return {**environment(), "shapely": shapely.__version__, "trimesh": trimesh.__version__,
            "manifold3d": package_version("manifold3d"),
            "contourpy": package_version("contourpy")}


def _smooth_value(smooth_px) -> float | None:
    """None (use the rule default), 0.0 (off), or a finite value above 0."""
    if smooth_px is None:
        return None
    value = _number("smooth_px", smooth_px)
    if not math.isfinite(value) or value < 0:
        raise FlatError(f"smooth_px must be 0 (off) or a finite number above 0, got {value}")
    return value


SMOOTHING_KEYS = ("applied", "sigma_px", "method", "area_change_px2", "removed_area_px2",
                  "added_area_px2", "hausdorff_lower_bound_px",
                  "hausdorff_sample_step_px", "parts_exact_cleaned", "parts_smoothed_cleaned",
                  "holes_exact_cleaned", "holes_smoothed_cleaned", "removed_regions",
                  "added_regions", "topology_changes")
TOPOLOGY_KINDS = ("disappeared", "appeared", "split", "merged", "holes_closed",
                  "holes_opened")
SMOOTHING_OFF = {"applied": False} | {key: None for key in SMOOTHING_KEYS[1:]}
SMOOTHING_ADVICE = ("; check outline.png, or use smooth_px 0 (--smooth-px 0) or a smaller "
                    "value")


def _smoothed(mask: np.ndarray, sigma: dict) -> shapely.Geometry:
    try:
        return smooth_outline(mask, sigma["value"])
    except SmoothingError as e:
        raise FlatError(f"smoothing failed: {e}") from None


def _regions(region, opening_mm: float, min_island_mm2: float) -> dict:
    """Pieces of region that survive the cleaning rules: open by opening_mm, keep >= island.

    The same opening (round joins, QUAD_SEGS) and island limit as clean. For information
    only: besides features that smoothing removed or added, the pieces include corner and
    tip rounding wherever smoothing moves the boundary by more than opening_mm over more
    than min_island_mm2 (at a coarse scale, every sharp corner).
    """
    radius = opening_mm / 2
    opened = region.buffer(-radius, quad_segs=QUAD_SEGS).buffer(radius, quad_segs=QUAD_SEGS)
    areas = sorted((float(p.area) for p in _polygons(opened)[0] if p.area >= min_island_mm2),
                   reverse=True)
    return {"count": len(areas), "total_area_mm2": float(sum(areas)),
            "largest_mm2": areas[:DROPPED_LISTED]}


def _holes(parts: list[Polygon]) -> int:
    return sum(len(p.interiors) for p in parts)


def _partners(parts: list[Polygon], others: list[Polygon]) -> list[list[int]]:
    """For each part, the indices of others it overlaps with positive area."""
    if not others:
        return [[] for _ in parts]
    tree = shapely.STRtree(others)
    found = []
    for part in parts:
        candidates = sorted(int(j) for j in tree.query(part, predicate="intersects"))
        found.append([j for j in candidates if part.intersection(others[j]).area > 0])
    return found


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _topology_changes(exact_parts: list[Polygon],
                      parts: list[Polygon]) -> tuple[dict, list[str]]:
    """Topology changes between the cleaned exact parts and the cleaned smoothed parts.

    Two parts correspond when they overlap with positive area (touching is not enough).
    - An exact part with no partner disappeared; with two or more, it split.
    - A smoothed part with no partner appeared; with two or more, it merged.
    - In a one-to-one pair, a difference in the number of holes (interior rings) counts as
      holes closed or opened, by the number of holes.
    Returns the counts by kind (TOPOLOGY_KINDS; parts, except holes_* count holes) and one
    warning per kind that occurred. No threshold is involved.
    Limitation: smoothing can remove a thin appendage attached to a part (a neck or tip
    narrower than about sigma) without changing the topology; that is not warned about.
    Check removed_regions and outline.png for it.
    """
    forward = _partners(exact_parts, parts)
    backward = _partners(parts, exact_parts)
    changes = dict.fromkeys(TOPOLOGY_KINDS, 0)
    warnings = []
    gone = [exact_parts[i] for i, js in enumerate(forward) if not js]
    new = [parts[j] for j, iis in enumerate(backward) if not iis]
    split = [js for js in forward if len(js) >= 2]
    merged = [iis for iis in backward if len(iis) >= 2]
    changes.update(disappeared=len(gone), appeared=len(new), split=len(split),
                   merged=len(merged))
    for found, verb in ((gone, "disappeared"), (new, "appeared")):
        if found:
            area = sum(p.area for p in found)
            warnings.append(f"{_plural(len(found), 'part')} {verb} with smoothing "
                            f"({area:.3g} mm^2 in all)")
    if split:
        warnings.append(f"smoothing split {_plural(len(split), 'part')} into "
                        f"{_plural(sum(len(js) for js in split), 'part')}")
    if merged:
        warnings.append(f"smoothing merged {_plural(sum(len(i) for i in merged), 'part')} "
                        f"into {_plural(len(merged), 'part')}")
    for i, js in enumerate(forward):
        if len(js) == 1 and len(backward[js[0]]) == 1:
            change = len(parts[js[0]].interiors) - len(exact_parts[i].interiors)
            if change < 0:
                changes["holes_closed"] -= change
            elif change > 0:
                changes["holes_opened"] += change
    for kind, verb in (("holes_closed", "closed"), ("holes_opened", "opened")):
        if changes[kind]:
            warnings.append(f"smoothing {verb} {_plural(changes[kind], 'hole')}")
    return changes, [w + SMOOTHING_ADVICE for w in warnings]


def _smoothing_report(exact, smooth, parts: list[Polygon], transform: dict, sigma: dict,
                      opening_mm: float, min_island_mm2: float) -> tuple[dict, list[str]]:
    """The record's smoothing section and warnings: what smoothing changed.

    exact and smooth are the outlines in pixel units; parts is the cleaned smoothed model.
    - area_change_px2 is the net area change; removed_area_px2 (exact minus smooth) and
      added_area_px2 (smooth minus exact) are the two directions, before cleaning.
    - The exact outline goes through the same transform and the same clean (opening,
      min_island, step) as the smoothed one. parts_*_cleaned and holes_*_cleaned count
      the parts and the holes (interior rings) each gives.
    - hausdorff_lower_bound_px is _sampled_hausdorff between the two cleaned regions,
      sampled at hausdorff_sample_step_px (HAUSDORFF_STEP_PX) and converted to pixels. It
      compares cleaned shapes, so specks that cleaning removes anyway do not dominate it.
      It is the boundary-to-region distance (0 for samples inside the other region),
      within step / 2 of it, and a lower bound of the two-sided region Hausdorff distance.
      It is NOT the boundary-to-boundary distance: a change enclosed by the other region,
      such as a hole that smoothing fills, is under-reported against how far the boundary
      moved. It is null if cleaning leaves nothing of the exact outline.
    - removed_regions and added_regions (_regions) are the pieces of (cleaned exact -
      cleaned smooth) and (cleaned smooth - cleaned exact) that survive the cleaning
      rules. They are information only and include corner and tip rounding.
    - topology_changes and the warnings come from part correspondence
      (_topology_changes): parts that disappeared, appeared, split or merged, and holes
      closed or opened in one-to-one pairs.
    """
    s = transform["scale_mm_per_px"]
    step_mm = HAUSDORFF_STEP_PX * s
    try:
        exact_parts, _ = clean(_apply_transform(exact, transform), opening_mm,
                               min_island_mm2, step_mm)
    except FlatError:                    # cleaning leaves nothing of the exact outline
        exact_parts = []
    exact_region = shapely.union_all(exact_parts)
    smooth_region = shapely.union_all(parts)
    hausdorff = (_sampled_hausdorff(exact_region, smooth_region, step_mm) / s
                 if exact_parts else None)
    section = {"applied": True, "sigma_px": sigma, "method": SMOOTHING_METHOD,
               "area_change_px2": float(smooth.area - exact.area),
               "removed_area_px2": float(exact.difference(smooth).area),
               "added_area_px2": float(smooth.difference(exact).area),
               "hausdorff_lower_bound_px": hausdorff,
               "hausdorff_sample_step_px": HAUSDORFF_STEP_PX,
               "parts_exact_cleaned": len(exact_parts), "parts_smoothed_cleaned": len(parts),
               "holes_exact_cleaned": _holes(exact_parts),
               "holes_smoothed_cleaned": _holes(parts),
               "removed_regions": _regions(exact_region.difference(smooth_region),
                                           opening_mm, min_island_mm2),
               "added_regions": _regions(smooth_region.difference(exact_region),
                                         opening_mm, min_island_mm2)}
    section["topology_changes"], warnings = _topology_changes(exact_parts, parts)
    return section, warnings


def make_flat(selection_dir, width_mm, thickness_mm, out_dir, printer="bambu-a1",
              smooth_px=None) -> dict:
    """Make model.stl, outline.png and flat.json from a tdmg select output folder.

    smooth_px is the Gaussian sigma, in image pixels, of tdmg.smoothing.smooth_outline:
    None takes the default of rule flat.smooth.sigma_px, 0 keeps the exact pixel outline,
    and any other value must be finite and above 0. The record's smoothing section
    measures what smoothing changed (see _smoothing_report). The record's warnings list
    says when smoothing changed the topology of the cleaned geometry: a part that
    disappeared, appeared, split or merged, or a hole closed or opened. A thin attached
    appendage that smoothing removes is not warned about (see _topology_changes). A
    warning is not a gate check and does not change the verdict.

    Everything is built, encoded and gated in memory first, so a refused input writes
    nothing. An I/O failure while writing (a full disk, a failed rename) can leave an
    incomplete folder without flat.json, which must not be used. A check that FAILs does
    not stop the write: the files and the verdict are written for review. The gate
    judges the STL bytes that are written: they are parsed back, merged
    exactly, and checked. flat_id is a SHA-256 of the canonical JSON of the algorithm,
    the mask's pixel hash and the parameters (with the printer id and the rules that set
    them); the environment is not part of it. flat_id identifies the geometry, so check
    thresholds (build volume, triangle limit, wall width) do not enter it; each check
    records its own threshold. The output file hashes are integrity hashes, valid within
    this environment only.
    """
    width_mm = _require_positive("width_mm", width_mm)
    thickness_mm = _require_positive("thickness_mm", thickness_mm)
    smooth_value = _smooth_value(smooth_px)
    selection, mask = _read_selection(Path(selection_dir))
    if printer not in printer_ids():
        raise FlatError(f"no printer profile {printer!r}; choose one of {printer_ids()}")
    profile = load_printer(printer)
    rules = load_rules()
    try:
        create_folder = check_output_dir(out_dir)
    except RecordError as e:
        raise FlatError(str(e)) from None

    opening = {"value": float(rules[OPENING_RULE].default), "rule": OPENING_RULE}
    side = float(rules[ISLAND_RULE].default)
    nozzle = float(profile.nozzle_diameter_mm)
    min_island = {"value": (side * nozzle) ** 2, "rules": [ISLAND_RULE],
                  "nozzle_diameter_mm": nozzle,
                  "formula": "(min_square_side x nozzle_diameter_mm)^2"}
    if smooth_value is None:
        sigma = {"value": float(rules[SMOOTH_RULE].default), "rule": SMOOTH_RULE}
    else:                              # an explicit value: no rule set it
        sigma = None if smooth_value == 0 else {"value": smooth_value, "rule": None}
    exact = mask_outline(mask)
    outline = exact if sigma is None else _smoothed(mask, sigma)
    model, transform = to_model(outline, width_mm)
    parts, cleaning = clean(model, opening["value"], min_island["value"],
                            HAUSDORFF_STEP_PX * transform["scale_mm_per_px"])
    if sigma is None:
        smoothing, warnings = dict(SMOOTHING_OFF), []
    else:
        smoothing, warnings = _smoothing_report(exact, outline, parts, transform, sigma,
                                                opening["value"], min_island["value"])
    stl = _encode_stl(extrude(parts, thickness_mm))
    kept = rasterise(parts, transform, mask.shape)
    files = {"model.stl": stl, "outline.png": png_bytes(_outline_image(mask, kept))}

    gated = merge_exact(trimesh.load(io.BytesIO(stl), file_type="stl", process=False))
    checks = topology_checks(gated) + flat_checks(gated, parts, transform, width_mm,
                                                  thickness_mm, profile, rules)
    params = {"width_mm": width_mm, "thickness_mm": thickness_mm, "printer": profile.id,
              "opening_mm": opening, "min_island_mm2": min_island,
              "smoothing": {"applied": False} if sigma is None else {"sigma_px": sigma}}
    identity = {"algorithm": FLAT_ALGORITHM_VERSION,
                "mask_pixels_sha256": selection["mask_pixels_sha256"],
                "params": params}
    record = {
        "schema": RECORD_SCHEMA, "tdmg_version": __version__,
        "algorithm": FLAT_ALGORITHM_VERSION,
        "flat_id": hashlib.sha256(canonical_json(identity)).hexdigest(),
        "selection": {"selection_id": selection["selection_id"],
                      "mask_pixels_sha256": selection["mask_pixels_sha256"]},
        "params": params, "smoothing": smoothing,
        "warnings": warnings, "transform": transform,
        "cleaning": cleaning,
        "mesh": _mesh_summary(gated),
        "checks": [c.as_dict() for c in checks],
        "verdict": verdict(checks, FLAT_REQUIRED_CHECKS),
        "outputs": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        "environment": _flat_environment(),
        "review": REVIEW,
    }
    try:
        data = record_text(record)
    except ValueError as e:
        raise FlatError(f"the record cannot be stored as strict JSON: {e}") from None
    try:
        write_outputs(out_dir, files, "flat.json", data, create_folder=create_folder)
    except RecordError as e:
        raise FlatError(str(e)) from None
    return record

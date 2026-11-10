"""Flat geometry from a reviewed selection mask (docs/plans/2026-11-10-flat-geometry.md).

The reference outline is the exact pixel-cell outline: the union of the mask's pixel
squares, with each pixel (column x, row y) the cell [x, x + 1] x [y, y + 1]. It has no
half-pixel bias, unlike OpenCV centre tracing, which runs through pixel centres and
shrinks the outline by half a pixel (rule `vectorize.opencv.contour_offset_px`). The
outline's staircase edge is one pixel high; this module does not smooth it.

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
from importlib.metadata import version as package_version
from pathlib import Path

import manifold3d
import numpy as np
import shapely
import trimesh
from shapely import affinity
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

from tdmg import __version__
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
from tdmg.selection import SelectionError, load_mask, pixels_sha256

QUAD_SEGS = 8  # Buffer arcs per quarter circle. Chord error is r*(1-cos(pi/32)), about
               # 0.001 mm at r = 0.2 mm, far below a layer. An approximation setting.
HAUSDORFF_STEP_PX = 0.25  # Boundary sampling step for the measured change, in pixels.
                          # A measurement resolution, not a threshold: the caller passes
                          # HAUSDORFF_STEP_PX * scale_mm_per_px as clean's sample_step_mm.
DROPPED_LISTED = 10  # Display only: how many dropped-island areas the report lists.
MASK_ON = 255  # Integer masks hold 0 and 255, as mask.png does (selection.load_mask).
THIN_LISTED = 5  # Display only: how many thin-region pieces the F3 measurement lists.
DISPLAY_DECIMALS = 3  # Display rounding of listed thin-region areas and centroids (mm).
WIDTH_RTOL = 1e-9  # F2.target_width float comparison only; the scale is exact up to rounding.
THIN_RULE = "fdm.wall.min_thickness"
TRIANGLE_RULE = "slicer.orca.max_triangles_per_plate"
OPENING_RULE = "flat.sliver.opening_width"
ISLAND_RULE = "flat.island.min_square_side"
FLAT_ALGORITHM_VERSION = "flat-1"
RECORD_SCHEMA = "tdmg.flat/1"
# outline.png display colours only; these are not thresholds.
OUTLINE_KEPT = (128, 128, 128)        # grey: printed
OUTLINE_REMOVED = (220, 40, 40)       # red: in the mask, removed by cleaning
OUTLINE_BACKGROUND = (255, 255, 255)  # white: not in the mask
REVIEW = ("Open outline.png: grey is kept, red was removed as unprintable. The verdict stays "
          "NOT CERTIFIED until F3 policy and slicer checks exist.")
# Every check the flat gate needs. F3 and F6 are UNKNOWN until their policy and slicer
# integration exist, so the verdict is NOT CERTIFIED for now.
FLAT_REQUIRED_CHECKS = F1_CHECK_IDS | {"F2.fits_build_volume", "F2.target_width",
                                       "F3.thin_regions", "F4.body_count", "F5.triangles",
                                       "F6.slicer"}


class FlatError(ValueError):
    """The selection cannot be made into flat geometry as asked. Nothing is written."""


def _cells(mask: np.ndarray) -> np.ndarray:
    mask = np.asarray(mask)
    if mask.ndim != 2:
        raise FlatError(f"mask must be two-dimensional, got shape {mask.shape}")
    if mask.dtype == np.bool_:
        return mask
    if np.issubdtype(mask.dtype, np.integer):
        if not np.isin(mask, (0, MASK_ON)).all():
            raise FlatError(f"an integer mask must hold only 0 and {MASK_ON}")
        return mask == MASK_ON
    raise FlatError(f"mask must be bool or integer (0 and {MASK_ON}), got {mask.dtype}")


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
    (mask_width_px and mask_height_px are the foreground's extents, not the image size).
    """
    width_mm = _require_positive("width_mm", width_mm)
    if outline.is_empty or outline.area <= 0:
        raise FlatError("no printable foreground")
    x0, y0, x1, y1 = (float(v) for v in outline.bounds)
    s = width_mm / (x1 - x0)
    model = affinity.affine_transform(outline, [s, 0.0, 0.0, -s, -x0 * s, y1 * s])
    transform = {"scale_mm_per_px": s, "x0_px": x0, "y1_px": y1,
                 "mask_width_px": x1 - x0, "mask_height_px": y1 - y0}
    return model, transform


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
    """Two-sided Hausdorff distance between regions a and b, sampled on both boundaries.

    Each boundary is split into pieces no longer than step, and every vertex is a sample.
    A sample covered by the other region is at distance 0, else at its exact distance to
    the other boundary. Samples are points of the boundaries and their distances are
    exact, so the result is a lower bound of the boundary-to-region Hausdorff distance
    and lies within step / 2 of it. It does not see interior points: clean reports a
    derived upper bound for the region distance. GEOS's plain hausdorff_distance looks
    only at vertices, so it misses a removed bar whose middle has no vertex. a and b
    must be non-empty; clean guarantees that.
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

    opening_mm must be above 0: the opening is what separates parts that touch only at a
    corner. Returns the parts, largest first, and a report with a fixed key set:
    opening_mm, min_island_mm2, area_before_mm2, area_after_mm2, removed_area_mm2,
    boundary_hausdorff_mm, hausdorff_upper_bound_mm, hausdorff_sample_step_mm,
    dropped_islands {count, total_area_mm2, largest_mm2} for parts the opening left below
    min_island_mm2, vanished_parts {count, total_area_mm2} for input parts the opening
    erased entirely, and ignored_non_polygonal, the count of lines and points in the
    input, which have no printable area.

    boundary_hausdorff_mm is the two-sided distance sampled on both boundaries at
    sample_step_mm: a lower bound of the boundary distance, accurate to step / 2.
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
    some thin area. Returns min_width_mm, the total area, the number of pieces and the
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
    """F3.thin_regions: always UNKNOWN for now, with the measurement."""
    threshold = rules[THIN_RULE].default
    return CheckResult("F3.thin_regions", "UNKNOWN", thin_regions(parts, threshold),
                       threshold, THIN_RULE,
                       "tapered tips always appear; pass/fail policy pending research on "
                       "slicer handling of narrow features")


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
    """F2.target_width: the scale maps the mask's bounding-box width to width_mm."""
    scaled = transform["scale_mm_per_px"] * transform["mask_width_px"]
    ok = math.isclose(scaled, width_mm, rel_tol=WIDTH_RTOL, abs_tol=0.0)
    size = " x ".join(f"{e:.6g}" for e in _extents(mesh))
    return CheckResult("F2.target_width", "PASS" if ok else "FAIL", scaled, float(width_mm),
                       None, f"the mask's width is scaled to the requested width; final "
                             f"extents after cleaning are {size} mm, which can be smaller "
                             "because cleaning removes material")


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
                width_mm: float, printer: PrinterProfile, rules: dict) -> list[CheckResult]:
    """The F2-F6 checks, on an exactly merged mesh and the cleaned parts it came from."""
    return [build_volume_check(mesh, printer), target_width_check(transform, width_mm, mesh),
            thin_region_check(parts, rules), body_count_check(mesh),
            triangle_check(mesh, rules), slicer_check()]


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
    """H x W x 3: kept pixels grey, mask pixels removed by cleaning red, the rest white."""
    image = np.empty((*mask.shape, 3), np.uint8)
    image[...] = OUTLINE_BACKGROUND
    image[mask & ~kept] = OUTLINE_REMOVED
    image[kept] = OUTLINE_KEPT
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
    size = record.get("input", {})
    w, h = (size.get(k) if isinstance(size, dict) else None for k in ("width", "height"))
    if not all(type(v) is int and v > 0 for v in (w, h)):
        raise FlatError(f"{record_path} has no valid input width and height")
    expected = record.get("mask_pixels_sha256")
    if not isinstance(expected, str) or not isinstance(record.get("selection_id"), str):
        raise FlatError(f"{record_path} has no mask_pixels_sha256 or selection_id")
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


def _mesh_summary(mesh: trimesh.Trimesh) -> dict:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    tri = vertices[faces]
    volume = float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6)
    return {"triangles": len(faces), "bodies": _body_count(mesh), "volume_mm3": volume,
            "extents_mm": _extents(mesh)}


def _flat_environment() -> dict:
    """records.environment() plus the geometry libraries the mesh bytes depend on."""
    return {**environment(), "shapely": shapely.__version__, "trimesh": trimesh.__version__,
            "manifold3d": package_version("manifold3d")}


def make_flat(selection_dir, width_mm, thickness_mm, out_dir, printer="bambu-a1") -> dict:
    """Make model.stl, outline.png and flat.json from a tdmg select output folder.

    Everything is built, encoded and gated in memory first, so a refused run writes
    nothing. The gate judges the STL bytes that are written: they are parsed back, merged
    exactly, and checked. flat_id is a SHA-256 of the canonical JSON of the algorithm,
    the mask's pixel hash and the parameters (with the printer id and the rules that set
    them); the environment is not part of it. flat_id identifies the geometry, so check
    thresholds (build volume, triangle limit, wall width) do not enter it; each check
    records its own threshold. The output file hashes are integrity hashes, valid within
    this environment only.
    """
    width_mm = _require_positive("width_mm", width_mm)
    thickness_mm = _require_positive("thickness_mm", thickness_mm)
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
    model, transform = to_model(mask_outline(mask), width_mm)
    parts, cleaning = clean(model, opening["value"], min_island["value"],
                            HAUSDORFF_STEP_PX * transform["scale_mm_per_px"])
    stl = extrude(parts, thickness_mm).export(file_type="stl")
    kept = rasterise(parts, transform, mask.shape)
    files = {"model.stl": stl, "outline.png": png_bytes(_outline_image(mask, kept))}

    gated = merge_exact(trimesh.load(io.BytesIO(stl), file_type="stl", process=False))
    checks = topology_checks(gated) + flat_checks(gated, parts, transform, width_mm, profile,
                                                  rules)
    params = {"width_mm": width_mm, "thickness_mm": thickness_mm, "printer": profile.id,
              "opening_mm": opening, "min_island_mm2": min_island}
    identity = {"algorithm": FLAT_ALGORITHM_VERSION,
                "mask_pixels_sha256": selection["mask_pixels_sha256"],
                "params": params}
    record = {
        "schema": RECORD_SCHEMA, "tdmg_version": __version__,
        "algorithm": FLAT_ALGORITHM_VERSION,
        "flat_id": hashlib.sha256(canonical_json(identity)).hexdigest(),
        "selection": {"selection_id": selection["selection_id"],
                      "mask_pixels_sha256": selection["mask_pixels_sha256"]},
        "params": params, "transform": transform, "cleaning": cleaning,
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

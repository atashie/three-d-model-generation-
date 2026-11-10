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

import math

import manifold3d
import numpy as np
import shapely
import trimesh
from shapely import affinity
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

QUAD_SEGS = 8  # Buffer arcs per quarter circle. Chord error is r*(1-cos(pi/32)), about
               # 0.001 mm at r = 0.2 mm, far below a layer. An approximation setting.
HAUSDORFF_STEP_PX = 0.25  # Boundary sampling step for the measured change, in pixels.
                          # A measurement resolution, not a threshold: the caller passes
                          # HAUSDORFF_STEP_PX * scale_mm_per_px as clean's sample_step_mm.
DROPPED_LISTED = 10  # Display only: how many dropped-island areas the report lists.
MASK_ON = 255  # Integer masks hold 0 and 255, as mask.png does (selection.load_mask).


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


def _require_positive(name: str, value: float) -> float:
    value = float(value)
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
    value = float(value)
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

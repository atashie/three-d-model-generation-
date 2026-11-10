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


class FlatError(ValueError):
    """The selection cannot be made into flat geometry as asked. Nothing is written."""


def mask_outline(mask: np.ndarray) -> shapely.Geometry:
    """Exact pixel-cell outline, in pixel units (x right, y down), as a union of row runs."""
    mask = np.asarray(mask)
    if mask.ndim != 2:
        raise FlatError(f"mask must be two-dimensional, got shape {mask.shape}")
    cells = mask.astype(bool)
    if not cells.any():
        raise FlatError("no printable foreground")
    boxes = []
    for y, row in enumerate(cells):
        edges = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
        starts = np.flatnonzero(edges == 1)
        ends = np.flatnonzero(edges == -1)
        boxes.extend(shapely.box(int(a), y, int(e), y + 1)
                     for a, e in zip(starts, ends, strict=True))
    return shapely.union_all(boxes)


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


def clean(geom_mm, opening_mm: float, min_island_mm2: float) -> tuple[list[Polygon], dict]:
    """Open by opening_mm (round joins, QUAD_SEGS); split into polygons; drop small parts.

    Returns the parts, largest first, and a report {opening_mm, min_island_mm2,
    area_before_mm2, area_after_mm2, removed_area_mm2, hausdorff_mm, dropped_islands}.
    Lines and points in the input are not printable area; if any appear they are
    skipped and counted as ignored_non_polygonal.
    """
    opening_mm = _require_non_negative("opening_mm", opening_mm)
    min_island_mm2 = _require_non_negative("min_island_mm2", min_island_mm2)
    polys, skipped = _polygons(geom_mm)
    before = shapely.union_all(polys)
    radius = opening_mm / 2
    opened = before.buffer(-radius, quad_segs=QUAD_SEGS).buffer(radius, quad_segs=QUAD_SEGS)
    candidates, _ = _polygons(opened)
    candidates.sort(key=_order_key)
    parts = [p for p in candidates if p.area >= min_island_mm2]
    dropped = sorted((float(p.area) for p in candidates if p.area < min_island_mm2),
                     reverse=True)
    after = shapely.union_all(parts)
    area_before = float(before.area)
    area_after = float(sum(p.area for p in parts))
    report = {"opening_mm": opening_mm, "min_island_mm2": min_island_mm2,
              "area_before_mm2": area_before, "area_after_mm2": area_after,
              "removed_area_mm2": area_before - area_after,
              "hausdorff_mm": (None if after.is_empty
                               else float(shapely.hausdorff_distance(before, after))),
              "dropped_islands": dropped}
    if skipped:
        report["ignored_non_polygonal"] = skipped
    if not parts:
        raise FlatError("nothing printable remains after cleaning (removed "
                        f"{report['removed_area_mm2']:.6g} mm^2 of "
                        f"{area_before:.6g} mm^2)")
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

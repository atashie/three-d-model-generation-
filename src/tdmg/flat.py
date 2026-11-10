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

import numpy as np
import shapely
from shapely import affinity

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

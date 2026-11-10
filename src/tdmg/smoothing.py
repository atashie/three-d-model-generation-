"""Smoothed outline of a binary mask: a Gaussian blur, then its 0.5 iso-contour.

Standalone: it needs only a mask and sigma, and does not depend on tdmg.flat. tdmg flat
calls it by default (docs/plans/2026-11-10-outline-smoothing.md; rule flat.smooth.sigma_px).

Method (METHOD):
1. The mask (bool, or integer 0/255) becomes a float32 field, 1 on the foreground, padded
   by PAD_PX zero pixels on every side.
2. OpenCV GaussianBlur with sigma_px in x and y and BORDER_CONSTANT (zero), so the
   foreground never reflects at the image border. The pad is blurred too, so it holds
   the blur's true values there. Every pad value is at most (1 - w_0) / 2 < 0.5 (w_0 is
   the kernel's centre weight), because every foreground pixel is at least one pixel away
   from it, so every contour closes inside the pad.
3. contourpy (serial algorithm, FillType.OuterOffset) traces the filled region between
   LEVEL = 0.5 and +inf, as polygons with their holes; they are unioned.
   - Level 0.5 is the midpoint between background and foreground. Across a long straight
     edge, the field at the two nearest pixel centres is (1 - w_0) / 2 and (1 + w_0) / 2,
     so the linear interpolation crosses 0.5 exactly on the cell edge: such an edge stays
     where it was. This is a property of a symmetric blur, not a tuned threshold.
4. The result is made valid only if it is not (_valid_polygonal).

Coordinates: the same pixel-cell convention as tdmg.flat.mask_outline, in pixel units,
x right and y down, with pixel (column c, row r) the cell [c, c + 1] x [r, r + 1].
contourpy puts padded array index i at a pixel centre; that is pixel i - PAD_PX, whose
centre is at i - PAD_PX + 0.5, so the outline is translated by 0.5 - PAD_PX in x and y.

Effects expected from the blur, on a scale of about sigma. tests/test_smoothing.py
measures specks, notches, corners and the staircase on synthetic masks; merging and
splitting are not measured there. tdmg flat records, per run, the area removed and added,
a sampled boundary distance, part and hole counts, and the regions removed or added:
- it removes boundary noise and specks smaller than about sigma, and fills small notches;
- it rounds real corners;
- it can merge parts closer than about sigma, or split parts joined by a neck thinner
  than about sigma;
- it removes the one-pixel staircase: a diagonal edge comes out straight.
"""

from __future__ import annotations

import math
import numbers

import contourpy
import cv2
import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

from tdmg._masks import binary_cells

LEVEL = 0.5   # midpoint between background (0) and foreground (1); see the docstring
PAD_PX = 1    # zero pad so every contour closes (one pixel suffices; see the docstring)
METHOD = ("Gaussian blur of the zero-extended binary mask (OpenCV GaussianBlur, "
          "BORDER_CONSTANT, sigma_px in x and y), then the filled 0.5 iso-contour "
          "(contourpy serial, FillType.OuterOffset) in pixel-cell coordinates")


class SmoothingError(ValueError):
    """The mask or sigma cannot be smoothed as asked."""


def _sigma(value) -> float:
    """value as a float: a real number (not a bool or a string), finite and above 0."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise SmoothingError(f"sigma_px must be a number, got {value!r}")
    sigma = float(value)
    if not math.isfinite(sigma) or sigma <= 0:
        raise SmoothingError(f"sigma_px must be a finite number above 0, got {sigma}")
    return sigma


def _polygon_parts(geom) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [] if geom.is_empty else [geom]
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        return [p for sub in geom.geoms for p in _polygon_parts(sub)]
    return []


def _valid_polygonal(geom) -> shapely.Geometry:
    """geom itself if valid; otherwise make_valid's polygonal parts, unioned.

    Lines and points that make_valid can return have no area and are dropped.
    """
    if geom.is_valid:
        return geom
    return shapely.union_all(_polygon_parts(shapely.make_valid(geom)))


def smooth_outline(mask: np.ndarray, sigma_px: float) -> shapely.Geometry:
    """The 0.5 iso-contour of the Gaussian-blurred mask, as a Polygon or MultiPolygon.

    See the module docstring for the method, the coordinate convention (that of
    tdmg.flat.mask_outline) and the effects. Raises SmoothingError for a bad sigma or
    mask, a mask with no foreground, or a foreground that the blur removes entirely.
    """
    sigma = _sigma(sigma_px)
    cells = binary_cells(mask, SmoothingError)
    if not cells.any():
        raise SmoothingError("no foreground to smooth")
    field = np.pad(cells.astype(np.float32), PAD_PX)
    field = cv2.GaussianBlur(field, (0, 0), sigma, sigmaY=sigma,
                             borderType=cv2.BORDER_CONSTANT)
    generator = contourpy.contour_generator(z=field, name="serial",
                                            fill_type=contourpy.FillType.OuterOffset)
    points, offsets = generator.filled(LEVEL, np.inf)
    polygons = []
    for xy, offset in zip(points, offsets, strict=True):
        rings = [xy[offset[i]:offset[i + 1]] for i in range(len(offset) - 1)]
        polygons.append(Polygon(rings[0], rings[1:]))
    geom = _valid_polygonal(shapely.union_all(polygons))
    if geom.is_empty or geom.area <= 0:
        raise SmoothingError(f"nothing remains after smoothing at sigma_px {sigma}: "
                             "every foreground feature is smaller than the blur")
    shift = 0.5 - PAD_PX
    return affinity.translate(geom, shift, shift)

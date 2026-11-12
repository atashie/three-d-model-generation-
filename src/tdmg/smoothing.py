"""Smoothed outline of a binary mask: a Gaussian blur, then its 0.5 iso-contour.

Standalone: it needs only a mask and sigma, and does not depend on tdmg.flat. tdmg flat
calls it by default (docs/plans/2026-11-10-outline-smoothing.md; rule flat.smooth.sigma_px).

smooth_labels (at the end of this module) is the multicolor counterpart for a color label
map (tdmg.color): the same Gaussian per color, then an argmax on a supersampled grid in
the same pixel-cell coordinates. Its docstring gives its method and coordinates.

Method (METHOD):
1. The mask (bool, or integer 0/255) becomes a float64 field, 1 on the foreground, padded
   by PAD_PX zero pixels on every side. float64, not float32 (changed 2026-11-11, flat-3):
   OpenCV's float32 blur gives last bits that depend on its code path (switching
   cv2.setUseOptimized changed the outline of all five owner selections); its float64
   blur gave the same bits both ways on every case measured on the Windows PC
   (research/reviews/2026-11-11-color-palette/, finding 5).
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
from dataclasses import dataclass

import contourpy
import cv2
import numpy as np
import shapely
from scipy import ndimage
from shapely import affinity
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

from tdmg._masks import binary_cells
from tdmg.color import OUTSIDE

LEVEL = 0.5   # midpoint between background (0) and foreground (1); see the docstring
PAD_PX = 1    # zero pad so every contour closes (one pixel suffices; see the docstring)
METHOD = ("Gaussian blur of the zero-extended binary mask (OpenCV GaussianBlur, float64, "
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
    field = np.pad(cells.astype(np.float64), PAD_PX)
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


# --- Color label maps (docs/plans/2026-11-11-color-palette.md, Decision 5, Task 5) -------

# The default supersample factor. A numerical choice, not a rule: it sets the size of the
# staircase left by the fine label map, 1/SUPERSAMPLE of an image pixel. Example: the
# owner's Roadie at 60 mm wide is about 0.100 mm/px (60 mm over its 599 px mask width), so
# 4 gives about 0.025 mm, far below a 0.4 mm bead. Memory and time grow with its square.
SUPERSAMPLE = 4

# Fine rows interpolated at a time. It bounds the working memory only: every fine pixel is
# computed from the same values by the same arithmetic whatever the band, so the result
# does not depend on it (tests/test_smooth_labels.py compares several band sizes).
_BAND_ROWS = 512

LABELS_METHOD = ("nearest-label fill of OUTSIDE (exact squared distance, lowest label on "
                 "ties), edge-replicated by one pixel; per color, the float64 indicator "
                 "blurred with OpenCV GaussianBlur (sigma_px in x and y, BORDER_REPLICATE); "
                 "bilinear samples at the fine pixel centres; argmax, lowest label on "
                 "ties. sigma 0: nearest upsample of the filled map")


def sigma_or_zero(value) -> float:
    """value as a float: a real number (not a bool or a string), finite and at least 0."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise SmoothingError(f"sigma_px must be a number, got {value!r}")
    sigma = float(value)
    if not math.isfinite(sigma) or sigma < 0:
        raise SmoothingError(f"sigma_px must be a finite number of at least 0, got {sigma}")
    return sigma


def check_supersample(value) -> int:
    """value as an int of at least 1 (not a bool), the fine map's supersample factor."""
    return _positive_int("supersample", value)


def _label_map(labels) -> np.ndarray:
    """labels as a new int32 (H, W) array; SmoothingError unless it is a valid label map."""
    a = np.asarray(labels)
    if a.ndim != 2:
        raise SmoothingError(f"labels must be two-dimensional, got shape {a.shape}")
    if a.dtype == np.bool_ or not np.issubdtype(a.dtype, np.integer):
        raise SmoothingError(f"labels must be an integer array, got {a.dtype}")
    if a.size == 0:
        raise SmoothingError(f"labels is empty (shape {a.shape})")
    if int(a.min()) < OUTSIDE:
        raise SmoothingError(f"labels must be {OUTSIDE} (OUTSIDE) or a palette index of "
                             f"at least 0, got {int(a.min())}")
    if int(a.max()) > np.iinfo(np.int32).max:
        raise SmoothingError(f"labels must fit in int32, got {int(a.max())}")
    if int(a.max()) == OUTSIDE:
        raise SmoothingError("labels has no labelled pixel (all OUTSIDE)")
    return a.astype(np.int32)


def _fill_outside(labels: np.ndarray) -> np.ndarray:
    """labels with every OUTSIDE pixel set to the label of its nearest labelled pixel.

    Nearest is by Euclidean distance between pixel centres. Ties are broken here, not by
    scipy, as in tdmg.color's thin step: per color, scipy.ndimage.distance_transform_edt
    (return_indices) gives a nearest pixel of that color, the squared distance to it is
    recomputed as an exact integer (it does not depend on which of several equally near
    pixels EDT returns), and the pixel takes the color at the least squared distance; on
    a tie, the lowest label.
    """
    out = labels == OUTSIDE
    if not out.any():
        return labels
    ty, tx = np.nonzero(out)
    best = np.full(len(ty), np.iinfo(np.int64).max, np.int64)
    best_c = np.full(len(ty), OUTSIDE, np.int32)
    for c in np.unique(labels[~out]):                    # ascending label
        iy, ix = ndimage.distance_transform_edt(labels != c, return_distances=False,
                                                return_indices=True)
        d2 = ((iy[ty, tx].astype(np.int64) - ty) ** 2
              + (ix[ty, tx].astype(np.int64) - tx) ** 2)
        closer = d2 < best                               # strict: the lowest label wins ties
        best = np.where(closer, d2, best)
        best_c = np.where(closer, c, best_c)
    filled = labels.copy()
    filled[ty, tx] = best_c
    return filled


def _linear_taps(n: int, s: int) -> tuple[np.ndarray, np.ndarray]:
    """For the n * s fine centres along an axis of n image pixels: the lower tap index
    into the one-pixel-padded axis (n + 2 samples) and the weight of the upper tap.

    Fine centre m is at image coordinate (m + 0.5) / s; padded sample p sits at the pixel
    centre p - 0.5. So the position in padded samples is u = (m + 0.5) / s + 0.5
    = (2m + 1 + s) / (2s), from 0.5 + 0.5/s to n + 0.5 - 0.5/s: always strictly between
    samples 0 and n + 1. The lower tap is floor(u) and the weight u - floor(u), both from
    exact integers (the weight is one division of integers, so correctly rounded).
    """
    num = 2 * np.arange(n * s, dtype=np.int64) + 1 + s
    lo = num // (2 * s)
    return lo, (num - lo * 2 * s) / (2 * s)


@dataclass(frozen=True, eq=False)
class SmoothedLabels:
    """The result of smooth_labels. eq=False: compared by identity (numpy arrays have no
    single truth value). The other fields are JSON-safe (int, float, str, tuple of int),
    for the colors record.

    fine: the fine label map (see smooth_labels), shape (H * s, W * s), in the smallest
      unsigned dtype that holds the largest input label (uint8 up to 255, uint16 up to
      65535, else uint32). Its numpy write flag is off: a read-only flag, not a deep
      guarantee (a caller can turn it back on).
    vanished: the input's labels (sorted ascending) that no fine pixel holds: colors the
      blur removed entirely (regions smaller than about sigma). Always () at sigma 0. It
      is reported, not hidden: the caller (the colors record) must say which colors are
      lost.
    supersample: s, as an int. sigma_px: the sigma used, as a float. method: LABELS_METHOD.
    """

    fine: np.ndarray
    vanished: tuple[int, ...]
    supersample: int
    sigma_px: float
    method: str


def smooth_labels(labels, sigma_px: float, supersample: int = SUPERSAMPLE,
                  *, _band_rows: int = _BAND_ROWS) -> SmoothedLabels:
    """A fine label map: the label map's regions smoothed by one Gaussian, without gaps.

    labels: (H, W) integer label map, OUTSIDE (-1, tdmg.color) outside the mask and
      palette indices 0..k-1 inside (such as clean_regions' result), with at least one
      labelled pixel. sigma_px: the Gaussian sigma in image pixels, finite and >= 0 (as
      tdmg.color_config.edge_sigma_px gives). supersample: an int >= 1 (bool refused).
      _band_rows: fine rows computed at a time, an int >= 1 (memory only; for tests).

    Returns a SmoothedLabels: fine, a new array of shape (H * s, W * s), s = supersample,
    with the read-only flag set, in the smallest unsigned dtype that holds the largest
    label (uint8 for a palette); vanished; and the settings. Every fine pixel holds
    exactly one label, one of the labels present in the input (never OUTSIDE). A color can
    disappear if the blur removes it; such colors are listed in vanished, never dropped
    silently. SmoothingError for any invalid argument.

    Two labels: label 0's fine region agrees with smooth_outline's polygon of the same
    mask within one fine pixel (1/s image px) along the boundary, for s <= 8 only. The
    bound is 0.707/s from the fine grid plus a measured gap of at most 0.020 image px
    between the bilinear level set and contourpy's chords, which does not shrink with s
    (tests/test_smooth_labels.py).

    Extent and coordinates: the fine map covers the image, no more. In the pixel-cell
    coordinates of tdmg.flat.mask_outline and smooth_outline (x right, y down, image pixel
    (column c, row r) the cell [c, c + 1] x [r, r + 1]), fine pixel (row i, column j) is
    the cell [j/s, (j + 1)/s] x [i/s, (i + 1)/s], with its centre at ((j + 0.5)/s,
    (i + 0.5)/s). So mask_outline(fine == c) scaled by 1/s about the origin is color c's
    region in the coordinates that smooth_outline returns and that tdmg.flat's to_model
    transform takes (x_mm = (x - x0) * scale, y_mm = (y1 - y) * scale).

    The fine map needs no pad, because smooth_outline's contour lies within the image box
    [0, W] x [0, H] up to float64 rounding (measured below). Proof: smooth_outline pads
    by one zero pixel. On the left, say, the pad's field is f(-1) = sum over the
    foreground (i >= 0, j) of w_{i+1} v_j and column 0's is f(0) = sum of
    w_i v_j (w, v: the normalised, symmetric 1-D weights in x and y). So f(-1) + f(0)
    <= sum_j v_j sum_{i>=0} (w_i + w_{i+1}) = 1, up to float64 rounding. Linear
    interpolation between the centres -0.5 and 0.5 then crosses 0.5 at x >= 0, and no
    crossing lies between two pad centres (each is below 0.5). So when step 2 clips this
    map to the R1 outline, it finds a label everywhere, except that float64 rounding of
    the field can put smooth_outline's contour very slightly outside the image box.
    Measured on the Windows PC (2026-11-11, flat-3) over full-image and border-touching
    random masks from 20 x 20 to 2000 x 1500 px, sigma 0.6 to 10: at most 2.5e-15 px
    (research/reviews/2026-11-11-color-palette/overshoot_f64.txt). With the earlier
    float32 field it was up to 1.9e-6 px. So step 2 MUST still intersect the R1 outline
    with the image box [0, W] x [0, H] before clipping this map to it.

    Method (LABELS_METHOD):
    1. Outside the mask: every OUTSIDE pixel takes the label of its nearest labelled pixel
       (Euclidean, exact integer squared distance, lowest label on ties; _fill_outside).
    2. sigma 0 (the exact preset): the filled map is upsampled by nearest neighbour, each
       pixel becoming an s x s block (np.repeat on both axes). No blur; steps 3-5 are
       skipped.
    3. The filled map is padded by one pixel by edge replication. For each label c, its
       indicator (float64, 1 where the label is c) is blurred with the call that
       smooth_outline makes: cv2.GaussianBlur, ksize (0, 0) (OpenCV derives the kernel
       from sigma), sigma_px in x and y, but BORDER_REPLICATE in place of BORDER_CONSTANT.
       Why the border differs: in smooth_outline everything beyond the image is
       background, so zero extension is the mask's own extension. Here the image's
       border pixels are labelled (step 1), and replication extends each label outwards,
       as the nearest fill would. The indicators then sum to 1 everywhere, so the fields
       do too, and for two labels label 0 wins where its field exceeds 0.5, the level
       smooth_outline uses. When label 0 is absent from the image border, its field is
       exactly smooth_outline's (replicating zeros is the zero extension).
    4. Each field is sampled at the fine pixel centres by bilinear interpolation between
       the four nearest padded pixel centres (_linear_taps gives the positions): first in
       y (between padded rows), then in x (between padded columns), in float64.
    5. Each fine pixel takes the label with the largest sample, the lowest label on ties.

    Cost: one exact EDT per color on H x W (only if there are OUTSIDE pixels), one blur
    per color of (H + 2) x (W + 2), and one interpolation per color of the H s x W s fine
    map, done in bands of _band_rows fine rows (a memory bound only; the result does not
    depend on it). Measured on the Windows PC (2026-11-11), a 2000 x 2000 map with 4
    colors inside a disc of radius 990 px, sigma 2.5, s 4 (an 8000 x 8000 fine map):
    4.9 s (best of 3) and a tracemalloc peak of 356 MiB. The earlier version (int32
    output, a full-size np.unique for vanished, git 9d66f8e) gave the same labels in
    5.4 s with a peak of 636 MiB. tracemalloc counts numpy and Python allocations only,
    not OpenCV's own buffers (the blur's), so the true peak is somewhat higher. The output
    itself is H s x W s bytes for uint8 (61 MiB here); the rest is the fill's EDT
    indices, the k coarse fields and a few float64 bands (_band_rows x W s x 8 bytes
    each).
    """
    sigma = sigma_or_zero(sigma_px)
    s = check_supersample(supersample)
    band_rows = _positive_int("_band_rows", _band_rows)
    filled = _fill_outside(_label_map(labels))
    h, w = filled.shape
    dtype = _fine_dtype(int(filled.max()))
    if sigma == 0:
        fine = np.repeat(np.repeat(filled.astype(dtype), s, axis=0), s, axis=1)
        return _result(fine, (), s, sigma)
    padded = np.pad(filled, 1, mode="edge")
    present = np.unique(filled)                          # ascending label
    fields = [cv2.GaussianBlur((padded == c).astype(np.float64), (0, 0), sigma,
                               sigmaY=sigma, borderType=cv2.BORDER_REPLICATE)
              for c in present]
    row_lo, row_t = _linear_taps(h, s)
    col_lo, col_t = _linear_taps(w, s)
    col_hi, col_u = col_lo + 1, 1 - col_t                # column taps and weights, once
    out = np.empty((h * s, w * s), dtype)
    as_label = present.astype(dtype)
    index_dtype = _fine_dtype(len(present) - 1)
    seen = np.zeros(len(present), bool)
    for start in range(0, h * s, band_rows):
        rows = slice(start, min(start + band_rows, h * s))
        lo, t = row_lo[rows], row_t[rows, None]
        u = 1 - t
        shape = (len(lo), w * s)
        best, v, tmp = np.empty(shape), np.empty(shape), np.empty(shape)
        best_i = np.zeros(shape, index_dtype)            # index into present
        for i, f in enumerate(fields):
            g = f[lo] * u + f[lo + 1] * t                # (band, W + 2), float64
            # v = g[:, col_lo] * col_u + g[:, col_hi] * col_t, with the same roundings
            np.take(g, col_lo, axis=1, out=v)
            np.multiply(v, col_u, out=v)
            np.take(g, col_hi, axis=1, out=tmp)
            np.multiply(tmp, col_t, out=tmp)
            np.add(v, tmp, out=v)
            if i == 0:
                best, v = v, best
            else:
                win = v > best                           # strict: the lowest label wins ties
                best_i[win] = i
                np.maximum(best, v, out=best)
        seen |= np.bincount(best_i.ravel(), minlength=len(present)) > 0
        np.take(as_label, best_i, out=out[rows])
    vanished = tuple(int(c) for c in present[~seen])
    return _result(out, vanished, s, sigma)


def _positive_int(name: str, value) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise SmoothingError(f"{name} must be an integer, got {value!r}")
    if int(value) < 1:
        raise SmoothingError(f"{name} must be at least 1, got {int(value)}")
    return int(value)


def _fine_dtype(top: int) -> type:
    """The smallest unsigned dtype that holds 0..top (labels fit in int32, so uint32 does)."""
    for dtype in (np.uint8, np.uint16, np.uint32):
        if top <= np.iinfo(dtype).max:
            return dtype
    raise SmoothingError(f"label {top} does not fit in uint32")


def _result(fine: np.ndarray, vanished: tuple, s: int, sigma: float) -> SmoothedLabels:
    fine.setflags(write=False)
    return SmoothedLabels(fine=fine, vanished=vanished, supersample=s, sigma_px=sigma,
                          method=LABELS_METHOD)

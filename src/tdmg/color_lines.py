"""Thin drawn lines that lie inside one other color: `thin_lines: widen`
(docs/plans/2026-11-19-widen-lines.md, Tasks 3-4; design
docs/plans/2026-11-19-widen-lines-design.md, part "The design", item 2). Pure functions on
tdmg.color's Quantized, with no I/O.

find_lines finds them on the extracted colors (before the outline step changes anything),
so each line is taken as drawn. In plain words:

1. The color view. Each pixel of an outline-family color counts as the non-family color
   nearest to that family color in CIELAB (squared distance; ties go to the lowest index).
   So the darker blur along the sides of a red line counts as red. (The outline drop
   gives each family pixel the spatially nearest color instead, which would give the blur
   to the neighbouring brown.)
2. Areas and lines. For each non-family color, in index order, each 4-connected piece of
   that color in the view is split in two: its areas, the pixels an opening of width
   2 x the line width keeps (tdmg.color.open_mask), and its lines, the rest. Each
   8-connected part of the lines is a candidate. Pieces and parts smaller than the island
   area are skipped.
3. A candidate is a line inside one color when all of these hold:
   - its ring (the candidate dilated by a 5 x 5 square, inside the image, less every
     pixel of its own color in the view) is mostly one other color, the host: the most
     common value of the ring (OUTSIDE counts as a value of its own; ties go to the
     lowest value) is not OUTSIDE, and its share of the ring is at least host_share;
   - its width is 2 x the 90th percentile, over the candidate's pixels, of the exact
     Euclidean distance (scipy.ndimage.distance_transform_edt) from each pixel centre to
     the nearest pixel centre outside the whole piece (the frame beyond the image counting
     as outside); its length is area / max(width, 1 px); its elongation, length /
     max(width, 1 px), is at least min_elongation.
4. Its ridge (centre line) is tdmg.color_outline.stroke_ridge of the candidate split into
   2 x 2 half pixels, as stroke_band does. Half pixel (r, c) covers rows r/2 to (r + 1)/2
   and columns c/2 to (c + 1)/2 of the image in cell coordinates (pixel i covers i to
   i + 1).

The function takes plain numbers and reads no rule. The caller passes:
- family: the outline family (color.outline.thin_share, tdmg.color_outline);
- limits: tdmg.color.Limits; only min_area_px (the island area, flat.island.min_square_side)
  is used here;
- width_px: the line width in pixels, line_width_mm (default color.lines.width) / mm_per_px;
- host_share: color.lines.host_share;
- min_elongation: color.lines.min_elongation.

The fixed parts of the method (2 x the width for the opening, the 5 x 5 ring, i.e. 2 px
around the candidate, and the 90th percentile) are part of the definition in the design and
of the rules' evidence (prototype research/verification/2026-11-19-widen-lines/
widen_try5.py), not separate thresholds. Connectivity is explicit: 4 for the pieces (as the
region cleanup), 8 for the candidates (as stroke_specks).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from tdmg.color import OUTSIDE, ColorError, Limits, Quantized, open_mask
from tdmg.color_outline import stroke_ridge

# The method's version, recorded in colors.json's methods.lines (Task 5).
LINES_METHOD = "inside-one-color-lines/1"
# The opening that separates areas from lines is this many line widths wide (design item 2).
BODY_WIDTHS = 2
# The ring is a dilation by a square this many pixels across: 2 px around the candidate.
RING_SQUARE_PX = 5
# The percentile of the distance transform taken as the candidate's half width.
WIDTH_PERCENTILE = 90

_FOUR = ndimage.generate_binary_structure(2, 1)
_EIGHT = ndimage.generate_binary_structure(2, 2)
_RING = np.ones((RING_SQUARE_PX, RING_SQUARE_PX), bool)
_RING_PAD = RING_SQUARE_PX // 2


@dataclass(frozen=True)
class Line:
    """One thin line inside one other color (find_lines).

    color: the extraction index of the line's color; host: that of the color it lies in.
    area_px: its pixel count (in the color view). width_px: 2 x the 90th percentile of the
    exact distance transform of its piece over its pixels. length_px: area_px / max(width_px,
    1). ridge: (row, col) of its ridge half pixels (2 x 2 per image pixel), sorted.
    """

    color: int
    host: int
    area_px: int
    width_px: float
    length_px: float
    ridge: tuple[tuple[int, int], ...]


def _positive(name: str, value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ColorError(f"{name} must be a number, got {value!r}")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ColorError(f"{name} must be a finite number above 0, got {value}")
    return value


def _check_family(family, k: int) -> tuple[int, ...]:
    if not isinstance(family, tuple) or any(
            isinstance(f, bool) or not isinstance(f, (int, np.integer)) for f in family):
        raise ColorError(f"family must be a tuple of palette indices, got {family!r}")
    fam = tuple(int(f) for f in family)
    if any(not 0 <= f < k for f in fam) or list(fam) != sorted(set(fam)):
        raise ColorError(f"family must be distinct indices below {k} in ascending order, "
                         f"got {family!r}")
    return fam


def color_view(q: Quantized, family: tuple[int, ...]) -> np.ndarray:
    """q.labels with each family color's pixels relabelled as the non-family color nearest
    to it in CIELAB (squared distance, ties to the lowest index). With no non-family color,
    or an empty family, the labels unchanged (a copy, int64)."""
    labels = np.asarray(q.labels).astype(np.int64)
    nonfam = [i for i in range(len(q.hex)) if i not in family]
    if not family or not nonfam:
        return labels
    lab = np.asarray(q.lab, np.float64)
    lut = np.arange(-1, len(q.hex))                 # lut[label + 1]; OUTSIDE stays
    for f in family:
        d2 = ((lab[nonfam] - lab[f]) ** 2).sum(axis=1)
        lut[f + 1] = nonfam[int(np.argmin(d2))]     # argmin: the first, the lowest index
    return lut[labels + 1]


def _box(sl, pad: int, shape) -> tuple[slice, slice]:
    return (slice(max(sl[0].start - pad, 0), min(sl[0].stop + pad, shape[0])),
            slice(max(sl[1].start - pad, 0), min(sl[1].stop + pad, shape[1])))


def find_lines(q: Quantized, family: tuple[int, ...], limits: Limits,
               width_px: float, host_share: float, min_elongation: float
               ) -> tuple[Line, ...]:
    """The thin lines inside one other color, sorted by (color, first ridge point). See the
    module docstring for the method and the rules the caller passes.

    q: the extracted colors. family: the outline family (ascending distinct indices).
    limits: its min_area_px is the island area. width_px, min_elongation: finite numbers
    above 0. host_share: a number above 0 and at most 1. Raises ColorError otherwise.

    Each piece is measured on its bounding box padded by 2 px (clipped to the image), which
    gives the same results as the whole image: the opening, the ring and the distances only
    reach that far, and the box's pad pixels are not in the piece.
    """
    if not isinstance(q, Quantized):
        raise ColorError(f"q must be a Quantized, got {type(q).__name__}")
    if not isinstance(limits, Limits):
        raise ColorError(f"limits must be a Limits, got {type(limits).__name__}")
    k = len(q.hex)
    fam = _check_family(family, k)
    width = _positive("width_px", width_px)
    share = _positive("host_share", host_share)
    if share > 1:
        raise ColorError(f"host_share must be at most 1, got {share}")
    elong = _positive("min_elongation", min_elongation)

    view = color_view(q, fam)
    shape = view.shape
    found: list[Line] = []
    for c in (i for i in range(k) if i not in fam):
        mine = view == c
        pieces, n = ndimage.label(mine, structure=_FOUR)   # numbered in row-major order
        if not n:
            continue
        areas = np.bincount(pieces.ravel(), minlength=n + 1)
        for li, sl in enumerate(ndimage.find_objects(pieces), start=1):
            if areas[li] < limits.min_area_px:
                continue
            box = _box(sl, _RING_PAD, shape)
            piece = pieces[box] == li
            thin = piece & ~open_mask(piece, BODY_WIDTHS * width)
            parts, m = ndimage.label(thin, structure=_EIGHT)
            if not m:
                continue
            part_areas = np.bincount(parts.ravel(), minlength=m + 1)
            edt = ndimage.distance_transform_edt(np.pad(piece, 1))[1:-1, 1:-1]
            for pj in range(1, m + 1):
                area = int(part_areas[pj])
                if area < limits.min_area_px:
                    continue
                part = parts == pj
                ring = ndimage.binary_dilation(part, structure=_RING) & ~mine[box]
                values = view[box][ring]
                if not values.size:
                    continue
                vals, counts = np.unique(values, return_counts=True)   # ascending values
                top = int(np.argmax(counts))                           # first: lowest value
                host = int(vals[top])
                if host == OUTSIDE or counts[top] / values.size < share:
                    continue
                w = 2.0 * float(np.percentile(edt[part], WIDTH_PERCENTILE))
                length = area / max(w, 1.0)
                if length / max(w, 1.0) < elong:
                    continue
                ry, rx = np.nonzero(stroke_ridge(np.repeat(np.repeat(part, 2, 0), 2, 1)))
                y0, x0 = 2 * box[0].start, 2 * box[1].start
                ridge = tuple(sorted(zip((ry + y0).tolist(), (rx + x0).tolist())))
                found.append(Line(color=c, host=host, area_px=area, width_px=w,
                                  length_px=length, ridge=ridge))
    found.sort(key=lambda ln: (ln.color, ln.ridge[0]))
    return tuple(found)

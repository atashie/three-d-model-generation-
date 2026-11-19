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
   - its ring (the candidate dilated by a 5 x 5 square, less every pixel of its own color
     in the view) is mostly one other color, the host: the most common value of the ring
     is not OUTSIDE, and its share of the ring is at least host_share. OUTSIDE counts as a
     value of its own, and the frame beyond the image counts as OUTSIDE (the view is
     padded with OUTSIDE by 2 px before the ring is taken), so a strip along the image's
     edge is not inside one color unless the share still holds with the frame counted.
     Ties go to the lowest value, so a tie with OUTSIDE (-1) is OUTSIDE. The share test
     is the exact integer comparison count >= host_share x ring size (float64 product);
   - its width is 2 x the 90th percentile (numpy's default, linear), over the candidate's
     pixels, of the Euclidean distance from each pixel centre to the nearest pixel centre
     outside the whole piece (the frame beyond the image counting as outside). The squared
     distances are exact integers (tdmg.color.d2_nearest, the convention of
     tdmg.color_outline), then square-rooted in float64. Its length is area / max(width,
     1 px); its elongation, length / max(width, 1 px) (float64), is at least
     min_elongation.
4. Its ridge (centre line) is tdmg.color_outline.stroke_ridge of the candidate split into
   2 x 2 half pixels, as stroke_band does. Half pixel (r, c) covers rows r/2 to (r + 1)/2
   and columns c/2 to (c + 1)/2 of the image in cell coordinates (pixel i covers i to
   i + 1).
5. The lines are returned sorted by (color, first ridge point). The order is total: the
   candidates of one color are disjoint sets of pixels, so their ridges, and their first
   ridge points, differ.

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

Work is cropped so that it grows with the sizes of the pieces and candidates, not with
their number times the image: the opening, the distances and the labelling of candidates
run once per piece on its bounding box padded by 2 px; the ring, the width and the ridge
run once per candidate on its own bounding box padded by 2 px. Each crop gives the same
result as the whole image (the pad holds the whole ring; beyond a box no pixel is in the
piece or candidate); tests/test_color_lines.py compares it with a plain whole-image form.

draw_lines (Task 4; design item 4) draws found lines on a smoothed fine label map, after
cleanup and smoothing: each line's ridge has its pieces joined (one found line, one
connected ridge) and is smoothed (RIDGE_SMOOTH_PX), then every fine pixel of the host
within half the drawn width of the smoothed ridge takes the line's color.
RIDGE_SMOOTH_PX (1.5 image px) is a method constant, not a print threshold: it is the size
of the beading it removes, the half-pixel staircase of a ridge that runs at an angle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

from tdmg.color import (
    FOUR_CONNECTED,
    OUTSIDE,
    ColorError,
    Limits,
    Quantized,
    d2_nearest,
    finite_positive,
    open_mask,
)
from tdmg.color_outline import stroke_ridge
from tdmg.smoothing import SmoothingError, check_supersample

# The method's version, recorded in colors.json's methods.lines (Task 5).
LINES_METHOD = "inside-one-color-lines/1"
# The opening that separates areas from lines is this many line widths wide (design item 2).
BODY_WIDTHS = 2
# The ring is a dilation by a square this many pixels across: 2 px around the candidate.
RING_SQUARE_PX = 5
# The percentile of the distances taken as the candidate's half width.
WIDTH_PERCENTILE = 90

# draw_lines moves each ridge point to the mean of the line's ridge points within this many
# image px (3 half pixels). A method constant, not a print threshold (module docstring).
RIDGE_SMOOTH_PX = 1.5
# draw_lines tests the discs of this many ridge points at a time (memory only).
_CHUNK = 1024
# The most ridge points within 3 half pixels of one (integer points with x^2 + y^2 <= 9),
# times 4: the largest denominator of a smoothed point (_smoothed, _disc_pixels).
_MAX_DEN = 4 * 29

_EIGHT = ndimage.generate_binary_structure(2, 2)
_RING = np.ones((RING_SQUARE_PX, RING_SQUARE_PX), bool)
_PAD = RING_SQUARE_PX // 2   # the ring's reach; every crop is padded by it


@dataclass(frozen=True)
class Line:
    """One thin line inside one other color (find_lines).

    color: the extraction index of the line's color; host: that of the color it lies in.
    area_px: its pixel count (in the color view). width_px: 2 x the 90th percentile of the
    exact distances to outside its piece, over its pixels. length_px: area_px /
    max(width_px, 1). ridge: (row, col) of its ridge half pixels (2 x 2 per image pixel),
    sorted.
    """

    color: int
    host: int
    area_px: int
    width_px: float
    length_px: float
    ridge: tuple[tuple[int, int], ...]


def _check_family(family, k: int) -> tuple[int, ...]:
    if not isinstance(family, tuple) or any(
            isinstance(f, bool) or not isinstance(f, (int, np.integer)) for f in family):
        raise ColorError(f"family must be a tuple of palette indices, got {family!r}")
    fam = tuple(int(f) for f in family)
    if any(not 0 <= f < k for f in fam) or list(fam) != sorted(set(fam)):
        raise ColorError(f"family must be distinct indices below {k} in ascending order, "
                         f"got {family!r}")
    return fam


def _color_view(q: Quantized, family: tuple[int, ...]) -> np.ndarray:
    """q.labels (int64 copy) with each family color's pixels relabelled as the non-family
    color nearest to it in CIELAB (squared distance, ties to the lowest index)."""
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


def _padded(sl: tuple[slice, slice]) -> tuple[slice, slice]:
    """A box (in the frame's coordinates) grown by _PAD on every side."""
    return (slice(sl[0].start - _PAD, sl[0].stop + _PAD),
            slice(sl[1].start - _PAD, sl[1].stop + _PAD))


def _host(values: np.ndarray, share: float) -> int | None:
    """The host of a ring's values, or None: the most common value (ties: the lowest), if
    it is not OUTSIDE and its count is at least share x the ring's size."""
    if not values.size:
        return None
    vals, counts = np.unique(values, return_counts=True)   # ascending values
    top = int(np.argmax(counts))                           # the first: the lowest value
    host = int(vals[top])
    if host == OUTSIDE or counts[top] < share * values.size:
        return None
    return host


def find_lines(q: Quantized, family: tuple[int, ...], limits: Limits,
               width_px: float, host_share: float, min_elongation: float
               ) -> tuple[Line, ...]:
    """The thin lines inside one other color, sorted by (color, first ridge point). See the
    module docstring for the method and the rules the caller passes.

    q: the extracted colors. family: the outline family (ascending distinct indices).
    limits: its min_area_px is the island area. width_px, min_elongation: finite numbers
    above 0. host_share: a number above 0 and at most 1. Raises ColorError otherwise.
    """
    if not isinstance(q, Quantized):
        raise ColorError(f"q must be a Quantized, got {type(q).__name__}")
    if not isinstance(limits, Limits):
        raise ColorError(f"limits must be a Limits, got {type(limits).__name__}")
    k = len(q.hex)
    fam = _check_family(family, k)
    width = finite_positive("width_px", width_px)
    share = finite_positive("host_share", host_share)
    if share > 1:
        raise ColorError(f"host_share must be at most 1, got {share}")
    elong = finite_positive("min_elongation", min_elongation)

    # Everything below is in the frame's coordinates: the image padded by _PAD, the frame
    # OUTSIDE in the view and in no piece, so no crop is ever clipped.
    view = np.pad(_color_view(q, fam), _PAD, constant_values=OUTSIDE)
    found: list[Line] = []
    for c in (i for i in range(k) if i not in fam):
        mine = view == c
        pieces, n = ndimage.label(mine, structure=FOUR_CONNECTED)   # row-major numbering
        if not n:
            continue
        areas = np.bincount(pieces.ravel(), minlength=n + 1)
        for li, sl in enumerate(ndimage.find_objects(pieces), start=1):
            if areas[li] < limits.min_area_px:
                continue
            box = _padded(sl)
            piece = pieces[box] == li
            thin = piece & ~open_mask(piece, BODY_WIDTHS * width)
            parts, m = ndimage.label(thin, structure=_EIGHT)
            if not m:
                continue
            part_areas = np.bincount(parts.ravel(), minlength=m + 1)
            # The exact squared distance to outside the piece, for its thin pixels (the
            # box's pad is outside the piece, so the box holds every nearest pixel).
            ty, tx = np.nonzero(thin)
            d2 = np.zeros(piece.shape, np.int64)
            d2[ty, tx] = d2_nearest(~piece, ty, tx)
            for pj, psl in enumerate(ndimage.find_objects(parts), start=1):
                area = int(part_areas[pj])
                if area < limits.min_area_px:
                    continue
                cbox = _padded(psl)                       # inside the piece's box
                part = parts[cbox] == pj
                gbox = (slice(box[0].start + cbox[0].start, box[0].start + cbox[0].stop),
                        slice(box[1].start + cbox[1].start, box[1].start + cbox[1].stop))
                ring = ndimage.binary_dilation(part, structure=_RING) & ~mine[gbox]
                host = _host(view[gbox][ring], share)
                if host is None:
                    continue
                d = np.sqrt(d2[cbox][part].astype(np.float64))
                w = 2.0 * float(np.percentile(d, WIDTH_PERCENTILE))
                length = area / max(w, 1.0)
                if length / max(w, 1.0) < elong:
                    continue
                ry, rx = np.nonzero(stroke_ridge(np.repeat(np.repeat(part, 2, 0), 2, 1)))
                y0, x0 = 2 * (gbox[0].start - _PAD), 2 * (gbox[1].start - _PAD)
                ridge = tuple(sorted(zip((ry + y0).tolist(), (rx + x0).tolist())))
                found.append(Line(color=c, host=host, area_px=area, width_px=w,
                                  length_px=length, ridge=ridge))
    found.sort(key=lambda ln: (ln.color, ln.ridge[0]))
    return tuple(found)


def _check_ridge(ridge, rows: int, cols: int) -> np.ndarray:
    """ridge as an (n, 2) int64 array of half-pixel (row, col), n >= 1, each row in
    0..rows - 1 and col in 0..cols - 1 (checked on the given integers, before the cast, so
    a large unsigned value cannot wrap)."""
    try:
        a = np.asarray(ridge)
    except (TypeError, ValueError) as exc:   # ragged sequences
        raise ColorError(f"ridge must be (row, col) pairs, got {ridge!r}") from exc
    if a.ndim != 2 or a.shape[1] != 2 or not a.shape[0]:
        raise ColorError(f"ridge must be a non-empty sequence of (row, col) pairs, "
                         f"got shape {a.shape}")
    if a.dtype == np.bool_ or not np.issubdtype(a.dtype, np.integer):
        raise ColorError(f"ridge must hold integers, got {a.dtype}")
    if int(a.min()) < 0:
        raise ColorError(f"ridge points must be at least 0, got {int(a.min())}")
    top_r, top_c = (int(v) for v in a.max(axis=0))
    if top_r >= rows or top_c >= cols:
        raise ColorError(f"ridge points must lie in the map's {rows} x {cols} half pixels, "
                         f"got row {top_r}, col {top_c}")
    return a.astype(np.int64)


def _check_label(name: str, value, dtype: np.dtype) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ColorError(f"{name} must be an integer label, got {value!r}")
    top = int(np.iinfo(dtype).max)
    if not 0 <= int(value) <= top:
        raise ColorError(f"{name} must be a label from 0 to {top} (the fine map's dtype "
                         f"{dtype}), got {int(value)}")
    return int(value)


def _segment(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The half pixels of the straight segment from a to b (int64 (row, col)), both ends
    included: max(|dr|, |dc|) + 1 points, a + round(t (b - a) / m) in exact integers
    (round half up)."""
    d = b - a
    m = int(np.abs(d).max())
    t = np.arange(m + 1, dtype=np.int64)[:, None]
    return a + (2 * t * d + m) // (2 * m)


def _piece_bridges(pts: np.ndarray, comp: np.ndarray, reach: int
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For each two pieces with points at most reach half pixels apart (exact integer
    test), their single shortest bridge: (d2, i, j) arrays (point indices i < j), the least
    (d2, i, j) of the pair, sorted by (d2, i, j)."""
    pairs = cKDTree(pts.astype(np.float64)).query_pairs(reach + 0.5, output_type="ndarray")
    if not len(pairs):
        pairs = np.zeros((0, 2), np.int64)
    i, j = np.minimum(pairs[:, 0], pairs[:, 1]), np.maximum(pairs[:, 0], pairs[:, 1])
    keep = comp[i] != comp[j]
    i, j = i[keep], j[keep]
    d2 = ((pts[i] - pts[j]) ** 2).sum(axis=1)                 # exact integers
    keep = d2 <= reach * reach
    i, j, d2 = i[keep], j[keep], d2[keep]
    ca, cb = np.minimum(comp[i], comp[j]), np.maximum(comp[i], comp[j])
    order = np.lexsort((j, i, d2, cb, ca))                    # per piece pair: least first
    ca, cb, d2, i, j = ca[order], cb[order], d2[order], i[order], j[order]
    first = np.ones(len(i), bool)
    first[1:] = (ca[1:] != ca[:-1]) | (cb[1:] != cb[:-1])
    d2, i, j = d2[first], i[first], j[first]
    order = np.lexsort((j, i, d2))
    return d2[order], i[order], j[order]


def _kruskal(comp: np.ndarray, n: int, d2: np.ndarray, i: np.ndarray, j: np.ndarray
             ) -> np.ndarray | None:
    """Which of the candidate bridges (sorted by (d2, i, j)) form the minimum spanning tree
    over the n pieces (a bool mask), or None when they do not join every piece."""
    parent = list(range(n + 1))                               # pieces are 1..n

    def root(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    tree = np.zeros(len(d2), bool)
    joined = 0
    for k in range(len(d2)):
        ra, rb = root(int(comp[i[k]])), root(int(comp[j[k]]))
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
            tree[k] = True
            joined += 1
            if joined == n - 1:
                return tree
    return None


def _bridged(pts: np.ndarray) -> np.ndarray:
    """The ridge with its pieces joined: sorted distinct int64 (row, col) half pixels.

    find_lines' ridge (local maxima of a discrete distance) is not always connected: along a
    curve it breaks into 8-connected pieces (on the half-pixel grid), with gaps of a few px
    that depend on the found line's shape, not on the drawn width. All the pieces come
    from one 8-connected found line, so every gap is an artifact of the discrete ridge and
    all of them are joined, with no distance limit.

    1. Each two pieces have one candidate bridge, their nearest points: the least exact
       integer squared distance, ties to the lowest (index, index) in the sorted ridge.
    2. The minimum spanning tree over the pieces (Kruskal over the candidates sorted by
       (squared distance, lower index, higher index), so ties are deterministic) joins
       them all. The candidates are those within a reach of 4 half pixels, doubled until
       they join every piece; the tree found is the one over all candidates (every edge
       it needs is within the final reach).
    3. A tree leaves one gap open in every closed loop (a ring drawn as a line would be
       cut or pinched there). So every other candidate no longer than the tree's longest
       bridge (squared distance at most its squared distance) is added too: only gaps no
       larger than one the tree already had to bridge. A loop whose closing gap is longer
       than every bridge of the tree stays open there.
    Each bridge adds the straight run of half pixels between its two points (_segment).
    Known small effect: on a tight hairpin a bridge may cross the waist between the two
    arms, where their discs already overlap.
    """
    pts = np.unique(pts, axis=0)                              # sorted rows, distinct
    local = pts - pts.min(axis=0)                             # the ridge's own box
    mark = np.zeros(tuple(local.max(axis=0) + 1), bool)
    mark[local[:, 0], local[:, 1]] = True
    comp_map, n = ndimage.label(mark, structure=_EIGHT)
    if n < 2:
        return pts
    comp = comp_map[local[:, 0], local[:, 1]]
    reach = 4
    while True:
        d2, i, j = _piece_bridges(pts, comp, reach)
        tree = _kruskal(comp, n, d2, i, j)
        if tree is not None:
            break
        reach *= 2
    use = d2 <= d2[tree].max()                                # the tree and loop closers
    added = [_segment(pts[a], pts[b]) for a, b in zip(i[use], j[use])]
    return np.unique(np.concatenate([pts, *added]), axis=0)


def _smoothed(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The smoothed ridge as exact fractions: (num_y, num_x, den), int64, one per point.

    Point k's smoothed position in cell coordinates is (num_y / den, num_x / den): the mean
    of the cell-coordinate centres ((r + 0.5) / 2, (c + 0.5) / 2) of the ridge points
    within RIDGE_SMOOTH_PX of it (itself included). With n such points and sums S_r, S_c of
    their half-pixel indices, the mean is ((2 S_r + n) / (4 n), (2 S_c + n) / (4 n)).
    Membership is decided on exact integer squared distances in half pixels: cKDTree finds
    the points of a slightly larger ball (indices sorted), so its float test never decides.
    """
    reach = 2 * RIDGE_SMOOTH_PX                               # 3.0 half pixels
    xy = pts.astype(np.float64)
    near_all = cKDTree(xy).query_ball_point(xy, reach + 0.5)
    num_y = np.empty(len(pts), np.int64)
    num_x = np.empty(len(pts), np.int64)
    den = np.empty(len(pts), np.int64)
    for k, near in enumerate(near_all):
        idx = np.array(sorted(near), np.int64)                # sorted for clarity only:
        # the sums below are exact integers, so their order does not matter
        d2 = ((pts[idx] - pts[k]) ** 2).sum(axis=1)           # exact integers
        idx = idx[d2 <= reach * reach]
        n = len(idx)
        num_y[k] = 2 * int(pts[idx, 0].sum()) + n
        num_x[k] = 2 * int(pts[idx, 1].sum()) + n
        den[k] = 4 * n
    return num_y, num_x, den


def _disc_pixels(num_y: np.ndarray, num_x: np.ndarray, den: np.ndarray, s: int,
                 radius: float, shape: tuple[int, int]) -> np.ndarray:
    """The flat indices, sorted and distinct, of the fine pixels whose centre is within
    radius (image px) of at least one point (num_y / den, num_x / den).

    Only a window around each point is tested: the fine pixels at most ceil(radius x s) + 1
    rows and columns from the fine pixel that holds the point. Fine pixel (i, j) has its
    centre at ((2i + 1) / (2s), (2j + 1) / (2s)), so with q = 2 s den its offset from the
    point is (a / q, b / q), a = (2i + 1) den - 2 s num_y and b = (2j + 1) den - 2 s num_x,
    exact integers. It is inside when a^2 + b^2 <= radius^2 x q^2: the left side is an
    exact integer, exact in float64 while it is below 2^53. A tested pixel's centre is at
    most radius + 3 px from the point in each axis and q <= 2 s _MAX_DEN, so
    a^2 + b^2 <= 2 (2 s _MAX_DEN (radius + 3))^2; draw_lines refuses a supersample and
    width for which that reaches 2^53 (s = 4 allows widths up to about 144000 px; s = 64,
    about 9000 px). The right side is float64,
    radius * radius then times q * q, IEEE-rounded the same way on every platform, so the
    test is deterministic.
    """
    h, w = shape
    reach = math.ceil(radius * s) + 1
    off = np.arange(-reach, reach + 1, dtype=np.int64)
    dy, dx = (a.ravel() for a in np.meshgrid(off, off, indexing="ij"))
    r2 = radius * radius
    found = []
    for start in range(0, len(den), _CHUNK):
        ny, nx, dn = (v[start:start + _CHUNK, None] for v in (num_y, num_x, den))
        i = (ny * s) // dn + dy
        j = (nx * s) // dn + dx
        a = (2 * i + 1) * dn - 2 * s * ny
        b = (2 * j + 1) * dn - 2 * s * nx
        q = (2 * s * dn).astype(np.float64)
        inside = (a * a + b * b).astype(np.float64) <= r2 * (q * q)
        inside &= (i >= 0) & (i < h) & (j >= 0) & (j < w)
        found.append(i[inside] * w + j[inside])
    return np.unique(np.concatenate(found))


def draw_lines(fine: np.ndarray, supersample: int, lines, width_px: float) -> np.ndarray:
    """The fine map with the lines drawn at width_px (design item 4).

    fine: a fine label map such as tdmg.smoothing.smooth_labels' fine (2-D, integer; image
    pixel (r, c) is split into supersample x supersample fine pixels, fine pixel (i, j)
    centred at ((i + 0.5) / s, (j + 0.5) / s) in cell coordinates). supersample: an int
    >= 1 (bool refused). lines: an iterable of (color_final, host_final, ridge): two labels
    in the fine map's numbering (after the merges' remap), each from 0 to the dtype's
    maximum, and a Line.ridge (half-pixel (row, col), half pixel (r, c) centred at
    ((r + 0.5) / 2, (c + 0.5) / 2); non-empty integers inside the map: rows 0 to
    2 x (fine rows / s) - 1, cols likewise). fine's shape must be a multiple of s (as
    smooth_labels' map is). width_px: the drawn width in image px, a finite number above
    0. Every argument is checked before anything is drawn; ColorError otherwise.

    For each line, in the given order:
    0. Its ridge's pieces are joined (_bridged): find_lines' ridge can break into pieces
       along a curve (gaps of up to 4.5 px on the test fixture, a 4 px red line of radius
       60 px, 6 px with its fringe), which would pinch or cut the drawn line. The pieces
       are joined by the shortest bridges that connect them all (a minimum spanning
       tree), with no distance limit, since they come from one connected found line.
       This is a step beyond the plan's two, found by testing (the arc in
       tests/test_color_lines.py drew in two pieces without it).
    1. Its ridge is smoothed: each point moves to the mean of the line's ridge points
       within RIDGE_SMOOTH_PX of it, itself included (each line on its own). This removes
       the half-pixel staircase of a ridge at an angle, which would bead the drawn edges.
       Near an end the mean lies inward, so the drawn line is a little shorter than with
       the raw ridge: on a straight ridge two half pixels thick (find_lines' ridge of a
       line an even number of px wide) the end point moves 9/14 px (0.64 px) along it,
       on one half pixel thick 0.75 px (tests/test_color_lines.py). The raw ridge starts
       about 1.5 px inside the found line's end and the drawn end cap reaches width_px / 2
       beyond the smoothed end, so the drawn line still reaches near the found line's end.
    2. Each fine pixel whose centre is within width_px / 2 of a smoothed point (the edge
       counts as within) and whose label is host_final at that moment becomes
       color_final. Only pixels holding host_final at that moment change, so a line never
       paints over a third color; lines are painted in the given order, and a later line
       may paint over an earlier line whose color is its host. Only the fine pixels near
       each point are tested.
    A line with color_final == host_final is skipped (nothing to draw; the caller records
    why).

    The smoothed points are exact fractions and the inclusion test compares an exact
    integer with one float64 product (_disc_pixels), so the result does not depend on the
    platform's float summation order. Returns a new array of fine's dtype and shape (not
    read-only, even if fine is); fine is never changed.
    """
    if not isinstance(fine, np.ndarray) or fine.ndim != 2 or not fine.size:
        raise ColorError(f"fine must be a non-empty 2-D array, got "
                         f"{getattr(fine, 'shape', type(fine).__name__)}")
    if fine.dtype == np.bool_ or not np.issubdtype(fine.dtype, np.integer):
        raise ColorError(f"fine must be an integer label map, got {fine.dtype}")
    try:
        s = check_supersample(supersample)
    except SmoothingError as exc:
        raise ColorError(str(exc)) from exc
    if fine.shape[0] % s or fine.shape[1] % s:
        raise ColorError(f"fine's shape {fine.shape} must be a multiple of the supersample "
                         f"{s}")
    radius = finite_positive("width_px", width_px) / 2
    if 2 * (2 * s * _MAX_DEN * (radius + 3)) ** 2 >= 2.0 ** 53:
        raise ColorError(f"width_px {width_px} is too large for exact tests at supersample "
                         f"{s}")
    rows, cols = 2 * (fine.shape[0] // s), 2 * (fine.shape[1] // s)
    todo = []
    for item in lines:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise ColorError(f"each line must be (color_final, host_final, ridge), "
                             f"got {item!r}")
        color = _check_label("color_final", item[0], fine.dtype)
        host = _check_label("host_final", item[1], fine.dtype)
        todo.append((color, host, _check_ridge(item[2], rows, cols)))
    out = np.array(fine, copy=True, order="C")
    flat = out.reshape(-1)                   # a view: out is C-contiguous
    for color, host, pts in todo:
        if color == host:
            continue
        idx = _disc_pixels(*_smoothed(_bridged(pts)), s, radius, out.shape)
        idx = idx[flat[idx] == host]
        flat[idx] = color
    return out

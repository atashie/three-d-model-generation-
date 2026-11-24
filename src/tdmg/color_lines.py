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
   2 x 2 half pixels, as stroke_band does, with its pieces joined (_bridged, with the
   candidate's half pixels as the mask that the extra bridges must stay inside). Half
   pixel (r, c) covers rows r/2 to (r + 1)/2 and columns c/2 to (c + 1)/2 of the image in
   cell coordinates (pixel i covers i to i + 1).
5. The lines are returned sorted by (color, first ridge point). The order is total: the
   candidates of one color are disjoint sets of pixels, so their ridges, and their first
   ridge points, differ.

The function takes plain numbers and reads no rule. The caller passes:
- family: the outline family (color.outline.thin_share, tdmg.color_outline);
- limits: tdmg.color.Limits; only min_area_px (the island area, flat.island.min_square_side)
  is used here;
- width_px: the line width in pixels, line_width_mm (default color.lines.width) / mm_per_px;
- host_share: color.lines.host_share;
- min_elongation: color.lines.min_elongation;
- closing: a Closing from closing_params(color.lines.loop_path_factor,
  color.lines.run_tolerance, color.lines.close_reach), for joining the ridge (_bridged).

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
cleanup and smoothing: each line's ridge (already joined by find_lines; a ridge given in
pieces is joined by a spanning tree) is smoothed (smooth_px, the rule
color.lines.ridge_smooth), then every fine pixel of the host within half the drawn width
of the smoothed ridge takes the line's color. paint_lines does the same and also returns
how many fine pixels each line changed (and, if asked, which line painted each pixel).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
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
LINES_METHOD = "inside-one-color-lines/2"
# The opening that separates areas from lines is this many line widths wide (design item 2).
BODY_WIDTHS = 2
# The ring is a dilation by a square this many pixels across: 2 px around the candidate.
RING_SQUARE_PX = 5
# The percentile of the distances taken as the candidate's half width.
WIDTH_PERCENTILE = 90

# draw_lines tests the discs of this many ridge points at a time (memory only).
_CHUNK = 1024
# _bridged computes the paths from this many ridge points at a time (memory only).
_PATH_CHUNK = 256

_EIGHT = ndimage.generate_binary_structure(2, 2)
_RING = np.ones((RING_SQUARE_PX, RING_SQUARE_PX), bool)
_PAD = RING_SQUARE_PX // 2   # the ring's reach; every crop is padded by it


@dataclass(frozen=True)
class Closing:
    """How _bridged closes a found line's loops (step 3), from three rules
    (closing_params): loop_path_factor (color.lines.loop_path_factor, a ratio),
    run_tolerance (color.lines.run_tolerance, in half pixels) and min_reach
    (color.lines.close_reach, in half pixels)."""

    loop_path_factor: float
    run_tolerance: int
    min_reach: int


def _half_pixels(name: str, value_px, minimum: int) -> int:
    """value_px (image px) as a whole number of half pixels, at least minimum."""
    if isinstance(value_px, bool) or not isinstance(value_px, (int, float, np.integer,
                                                               np.floating)):
        raise ColorError(f"{name} must be a number of px, got {value_px!r}")
    half = 2 * float(value_px)
    if not math.isfinite(half) or half != round(half) or half < minimum:
        raise ColorError(f"{name} must be a whole number of half pixels, at least "
                         f"{minimum / 2:g} px, got {value_px!r}")
    return round(half)


def closing_params(loop_path_factor, run_tolerance_px, close_reach_px) -> Closing:
    """A Closing from the three rules' values: the path factor a finite number above 0,
    the tolerance and the reach in image px, whole numbers of half pixels (the tolerance
    at least 0, the reach at least one half pixel). Raises ColorError otherwise."""
    return Closing(finite_positive("loop_path_factor", loop_path_factor),
                   _half_pixels("run_tolerance", run_tolerance_px, 0),
                   _half_pixels("close_reach", close_reach_px, 1))


@dataclass(frozen=True)
class Line:
    """One thin line inside one other color (find_lines).

    color: the extraction index of the line's color; host: that of the color it lies in.
    area_px: its pixel count (in the color view). width_px: 2 x the 90th percentile of the
    exact distances to outside its piece, over its pixels. length_px: area_px /
    max(width_px, 1). ridge: (row, col) of its ridge half pixels (2 x 2 per image pixel),
    sorted, its pieces joined (_bridged).
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
               width_px: float, host_share: float, min_elongation: float,
               closing: Closing) -> tuple[Line, ...]:
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
    if not isinstance(closing, Closing):
        raise ColorError(f"closing must be a Closing, got {type(closing).__name__}")

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
                halves = np.repeat(np.repeat(part, 2, 0), 2, 1)
                ry, rx = np.nonzero(stroke_ridge(halves))
                # Joined in the crop's half pixels, where halves is the candidate's mask.
                joined = _bridged(np.stack([ry, rx], axis=1).astype(np.int64), halves,
                                  closing)
                y0, x0 = 2 * (gbox[0].start - _PAD), 2 * (gbox[1].start - _PAD)
                ridge = tuple(zip((joined[:, 0] + y0).tolist(),
                                  (joined[:, 1] + x0).tolist()))      # sorted: unique
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


def _clear(pts: np.ndarray, comp: np.ndarray, a: int, b: int, tree: cKDTree) -> bool:
    """True when no ridge point of a third piece (not comp[a]'s, not comp[b]'s) lies in the
    closed disc whose diameter is the bridge a-b: (p - a) . (p - b) > 0 for every such p,
    in exact integers (cKDTree only gathers a slightly larger ball)."""
    pa, pb = pts[a], pts[b]
    mid = (pa + pb).astype(np.float64) / 2
    radius = math.sqrt(float(((pb - pa) ** 2).sum())) / 2
    near = np.array(sorted(tree.query_ball_point(mid, radius + 0.5)), np.int64)
    near = near[(comp[near] != comp[a]) & (comp[near] != comp[b])]
    dot = ((pts[near] - pa) * (pts[near] - pb)).sum(axis=1)
    return bool(np.all(dot > 0))


def _steps(pts: np.ndarray, a: int, b: int) -> int:
    """The bridge a-b's length in 8-connected half-pixel steps: max(|dr|, |dc|)."""
    return int(np.abs(pts[b] - pts[a]).max())


def _adjacent(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The ridge's 8-adjacent point pairs (i, j), i < j: its edges of weight 1."""
    pairs = cKDTree(pts.astype(np.float64)).query_pairs(1.5, output_type="ndarray")
    if not len(pairs):
        pairs = np.zeros((0, 2), np.int64)
    adj = np.abs(pts[pairs[:, 0]] - pts[pairs[:, 1]]).max(axis=1) == 1
    i, j = pairs[adj, 0], pairs[adj, 1]
    return np.minimum(i, j), np.maximum(i, j)


def _ridge_graph(pts: np.ndarray, bridges, adjacent=None) -> coo_matrix:
    """The ridge as a graph: an edge of weight 1 between 8-adjacent points (adjacent, or
    _adjacent(pts)), and one of weight _steps(a, b) for each bridge (a, b). Integer
    weights, so path lengths are exact."""
    n = len(pts)
    ai, aj = _adjacent(pts) if adjacent is None else adjacent
    rows, cols = list(ai), list(aj)
    weights = [1.0] * len(rows)
    for a, b in bridges:
        rows.append(a)
        cols.append(b)
        weights.append(float(_steps(pts, a, b)))
    return coo_matrix((weights, (rows, cols)), shape=(n, n)).tocsr()


def _local_paths(graph, pts: np.ndarray, kd: cKDTree, bridges, a: int, limit: float
                 ) -> tuple[np.ndarray, np.ndarray]:
    """The path lengths from a (inf beyond limit) to the ridge points within limit
    (Chebyshev) of a, as (those points, sorted; their lengths). graph: the ridge graph
    with the bridges known when it was built; bridges: the ones found since. The graph is
    cropped to those points: a path no longer than limit stays among them (a step or a
    bridge moves at most its length), so the lengths are the whole graph's."""
    near = np.array(sorted(kd.query_ball_point(pts[a], limit, p=np.inf)), np.int64)
    sub = graph[near][:, near]
    if bridges:
        inn = np.zeros(len(pts), bool)
        inn[near] = True
        extra = [(x, y) for x, y in bridges if inn[x] and inn[y]]
        if extra:
            ex = np.array(extra, np.int64)
            w = np.abs(pts[ex[:, 0]] - pts[ex[:, 1]]).max(axis=1).astype(np.float64)
            k = len(near)
            sub = sub + coo_matrix((w, (np.searchsorted(near, ex[:, 0]),
                                        np.searchsorted(near, ex[:, 1]))), shape=(k, k))
    d = dijkstra(sub, directed=False, indices=int(np.searchsorted(near, a)), limit=limit)
    return near, d


def _lengths(near: np.ndarray, d: np.ndarray, to: np.ndarray) -> np.ndarray:
    """The lengths to the points `to` in a _local_paths result (inf for a point not among
    its points)."""
    k = np.searchsorted(near, to)
    kc = np.minimum(k, len(near) - 1)
    return np.where((k < len(near)) & (near[kc] == to), d[kc], np.inf)


def _far(graph, pts: np.ndarray, i: np.ndarray, j: np.ndarray, steps: np.ndarray,
         limit: float, factor: float) -> np.ndarray:
    """For each pair (i, j) (sorted by i), whether its path is longer than
    factor x steps, vectorised per chunk of sources, on the graph cropped to
    the chunk's box grown by limit (as in _local_paths; j is within limit of i, so in
    the crop)."""
    far = np.zeros(len(i), bool)
    sources = np.unique(i)
    reach = math.floor(limit)
    for start in range(0, len(sources), _PATH_CHUNK):
        chunk = sources[start:start + _PATH_CHUNK]
        lo, hi = pts[chunk].min(axis=0) - reach, pts[chunk].max(axis=0) + reach
        sub = np.nonzero(((pts >= lo) & (pts <= hi)).all(axis=1))[0]
        d = dijkstra(graph[sub][:, sub], directed=False,
                     indices=np.searchsorted(sub, chunk), limit=limit)
        sel = np.arange(np.searchsorted(i, chunk[0], "left"),
                        np.searchsorted(i, chunk[-1], "right"))
        rows = np.searchsorted(chunk, i[sel])
        cols = np.searchsorted(sub, j[sel])
        far[sel] = d[rows, cols] > factor * steps[sel]
    return far


def _has_hole(inside: np.ndarray) -> bool:
    """Whether the mask (8-connected) encloses any pixel outside it: its complement,
    framed by one pixel and 4-connected, is in more than one piece."""
    rest = ~np.pad(inside, 1)
    return ndimage.label(rest, structure=FOUR_CONNECTED)[1] > 1


class _Topology:
    """The ridge's half pixels against the found line's mask (undilated), framed by one
    pixel: the mask's complement in its 4-connected components (the exterior, connected
    to the frame, and each hole). A closing bridge may separate two of those components
    from each other (it restores a hole the line has), but may never split one of them,
    the exterior or a hole, into two parts of the ridge's complement (Codex reviews of
    the fixes, 2026-11-19: an opening of one loop was closed when another loop of the
    same line had a hole; and an opening into a hole was closed inside that hole).
    Checked as a count: for each component of the mask's complement, the number of
    4-connected components of the ridge's complement that hold its pixels must not grow.
    Only its pixels beyond the run tolerance from the mask count (loose: the mask grown
    by it): a run may pass that close outside the line, so a pocket it cuts off there is
    its own rounding (the diamond loop in tests/test_color_lines.py), not an opening."""

    def __init__(self, inside: np.ndarray, loose: np.ndarray, pts: np.ndarray, segments):
        self.parts, self.n_parts = ndimage.label(~np.pad(inside, 1),
                                                 structure=FOUR_CONNECTED)
        self.counted = (self.parts > 0) & ~np.pad(loose, 1)
        self.ridge = np.zeros(self.parts.shape, bool)
        for seg in (pts, *segments):
            self.ridge[seg[:, 0] + 1, seg[:, 1] + 1] = True
        self.pieces = self._pieces(self.ridge)

    def _pieces(self, ridge: np.ndarray) -> np.ndarray:
        """For each component of the mask's complement (1..n), how many components of
        the ridge's complement hold its pixels."""
        lab, n = ndimage.label(~ridge, structure=FOUR_CONNECTED)
        on = self.counted & ~ridge
        pairs = np.unique(self.parts[on].astype(np.int64) * (n + 1) + lab[on])
        return np.bincount(pairs // (n + 1), minlength=self.n_parts + 1)

    def try_add(self, seg: np.ndarray) -> bool:
        """Add the run seg if it splits no component of the mask's complement; True when
        added."""
        ridge = self.ridge.copy()
        ridge[seg[:, 0] + 1, seg[:, 1] + 1] = True
        pieces = self._pieces(ridge)
        if (pieces > self.pieces).any():
            return False
        self.ridge, self.pieces = ridge, pieces
        return True


def _closing(pts: np.ndarray, comp: np.ndarray, inside: np.ndarray, tree_bridges,
             reach: int, closing: Closing) -> list:
    """The loop-closing bridges (a, b) of _bridged's step 3, in the order added."""
    if not _has_hole(inside):
        return []
    factor = closing.loop_path_factor
    loose = inside
    for _ in range(closing.run_tolerance):       # (binary_dilation's iterations=0 repeats)
        loose = ndimage.binary_dilation(loose, structure=_EIGHT)
    pairs = cKDTree(pts.astype(np.float64)).query_pairs(reach + 0.5, output_type="ndarray")
    if not len(pairs):
        return []
    i, j = np.minimum(pairs[:, 0], pairs[:, 1]), np.maximum(pairs[:, 0], pairs[:, 1])
    d2 = ((pts[i] - pts[j]) ** 2).sum(axis=1)                 # exact integers
    steps = np.abs(pts[i] - pts[j]).max(axis=1)
    keep = (d2 <= reach * reach) & (steps > 1)
    i, j, d2, steps = i[keep], j[keep], d2[keep], steps[keep]
    order = np.argsort(i, kind="stable")                      # by source, for _far
    i, j, d2, steps = i[order], j[order], d2[order], steps[order]
    limit = float(factor * reach)
    bridges = list(tree_bridges)
    graph = _ridge_graph(pts, bridges)
    # First filter: the path along the ridge (and the tree bridges) as it is.
    far = _far(graph, pts, i, j, steps, limit, factor)
    i, j, d2, steps = i[far], j[far], d2[far], steps[far]
    order = np.lexsort((j, i, d2))
    i, j, steps = i[order], j[order], steps[order]
    kd = cKDTree(pts.astype(np.float64))
    topology = _Topology(inside, loose, pts, [_segment(pts[a], pts[b]) for a, b in bridges])
    found: list = []
    cell = max(int(limit), 1)              # bucket side: every bound is at most limit
    bounds = factor * steps
    alive = np.ones(len(i), bool)
    # The candidates by their a's bucket (positions in order), for the upper bound below.
    by_cell: dict = {}
    for pos, key in enumerate(map(tuple, (pts[i] // cell).tolist())):
        by_cell.setdefault(key, []).append(pos)
    by_cell = {key: np.array(v, np.int64) for key, v in by_cell.items()}
    for t in range(len(i)):
        # alive[t] is exact: a candidate whose path is now within its bound has, on that
        # path, a last-found bridge k, and both parts of the path, a to k's first end x
        # and x to b, use only bridges found up to k; so the lengths measured from x when
        # k was found give at most the path's length, and that check (below, when k was
        # found) dropped the candidate. A candidate still alive has no such path.
        if not alive[t]:
            continue
        a, b = int(i[t]), int(j[t])
        seg = _segment(pts[a], pts[b])
        if (not loose[seg[:, 0], seg[:, 1]].all() or not _clear(pts, comp, a, b, kd)
                or not topology.try_add(seg)):
            continue
        found.append((a, b))
        # An upper bound for the later candidates: the path through this bridge's first
        # end, a; those it already puts within their bound close nothing (paths only
        # shorten from here on), so they are dropped now. Only a candidate whose a is
        # within limit of this a can have such a path: those in the 3 x 3 buckets around
        # this a's (never empty: this a's own bucket holds candidate t).
        near, d = _local_paths(graph, pts, kd, found, a, limit)
        ar, ac = int(pts[a, 0]) // cell, int(pts[a, 1]) // cell
        rest = np.concatenate([by_cell[key] for key in
                               ((ar + dr, ac + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1))
                               if key in by_cell])
        rest = rest[(rest > t) & alive[rest]]
        alive[rest] = ~(_lengths(near, d, i[rest]) + _lengths(near, d, j[rest])
                        <= bounds[rest])
    return found


def _bridged(pts: np.ndarray, inside: np.ndarray | None = None,
             closing: Closing | None = None) -> np.ndarray:
    """The ridge with its pieces joined and its loops closed: sorted distinct int64
    (row, col) half pixels.

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
       it needs is within the final reach). Every tree bridge is added.
    3. A tree leaves one gap open in every closed loop, and a ridge in one or two pieces
       can have a loop's gap inside one piece or a second gap between the same two pieces
       (a ring drawn as a line would be cut or pinched there; Codex review 2026-11-19,
       finding 1, and the spec review after it). So, given inside (a bool mask indexed by
       the ridge's own (row, col): find_lines passes the found line's half pixels) and
       closing (closing_params), the loop-closing bridges are added too (_closing), when
       the mask has a hole (_has_hole: otherwise there is no loop to keep). A candidate is
       any two ridge points (of any pieces, the same one included) at most the closing
       reach apart (exact squared distance; more than one half-pixel step apart), taken in
       (squared distance, lower index, higher index) order. It is added when all hold:
       - the path between its two points along the ridge, its bridges so far included
         (8-connected steps of 1, each bridge its length in steps), is more than
         closing.loop_path_factor times its own length in steps (color.lines.
         loop_path_factor): it does not shortcut a bend of the ridge. This alone does not
         tell a loop from a long U, whose path is unbounded against its chord: the next
         two tests do;
       - every half pixel of its straight run lies inside the mask grown by
         closing.run_tolerance half pixels (color.lines.run_tolerance): it follows the
         found line, never across the host;
       - no ridge point of a third piece lies in the closed disc on it as diameter
         (_clear): it joins two pieces that are neighbours along the line, not a chord
         past a piece between them;
       - it splits no component of the mask's complement (the exterior or a hole) into
         two parts of the ridge's complement (_Topology, on the undilated mask, counting
         the pixels beyond the run tolerance): it may restore a hole the line has, never
         close an opening of the line.
       Once a bridge is added, the later candidates' paths count it, so the other
       candidates across the same gap no longer close anything. (For speed each found
       bridge drops at once the later candidates it brings within their bound, from the
       lengths measured around it; the result is the whole-graph one,
       tests/test_color_lines.py.)
       On a net of lines the joined ridge can keep small extra holes at the crossings
       (5 to 19 half pixels on the test grid), inside the line, which the drawn width
       covers.
       The search is limited: the closing reach is twice the tree's final reach, and at
       least closing.min_reach half pixels (color.lines.close_reach); a loop whose gap is
       longer stays open there. With inside None (draw_lines, on a ridge that is not
       find_lines'), only the tree is added.
    Each bridge adds the straight run of half pixels between its two points (_segment).
    Known small effect: on a tight hairpin a tree bridge may cross the waist between the
    two arms, where their discs already overlap.
    """
    pts = np.unique(pts, axis=0)                              # sorted rows, distinct
    local = pts - pts.min(axis=0)                             # the ridge's own box
    mark = np.zeros(tuple(local.max(axis=0) + 1), bool)
    mark[local[:, 0], local[:, 1]] = True
    comp_map, n = ndimage.label(mark, structure=_EIGHT)
    comp = comp_map[local[:, 0], local[:, 1]]
    reach = 4
    tree_bridges: list = []
    if n >= 2:
        while True:
            d2, i, j = _piece_bridges(pts, comp, reach)
            tree = _kruskal(comp, n, d2, i, j)
            if tree is not None:
                break
            reach *= 2
        tree_bridges = list(zip(i[tree].tolist(), j[tree].tolist()))
    bridges = list(tree_bridges)
    if inside is not None:
        if not isinstance(closing, Closing):
            raise ColorError("closing (a Closing) is needed with inside")
        bridges += _closing(pts, comp, inside, tree_bridges,
                            max(2 * reach, closing.min_reach), closing)
    if not bridges:
        return pts
    added = [_segment(pts[a], pts[b]) for a, b in bridges]
    return np.unique(np.concatenate([pts, *added]), axis=0)


def _max_den(smooth_px: float) -> int:
    """The largest denominator of a smoothed point: 4 x the most ridge points within
    2 x smooth_px half pixels of one (the integer points (x, y) with x^2 + y^2 at most
    that squared; 29 for 1.5 px)."""
    r2 = math.floor((2 * smooth_px) ** 2)
    top = math.isqrt(r2)
    return 4 * sum(2 * math.isqrt(r2 - x * x) + 1 for x in range(-top, top + 1))


def _smoothed(pts: np.ndarray, smooth_px: float
              ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The smoothed ridge as exact fractions: (num_y, num_x, den), int64, one per point.

    Point k's smoothed position in cell coordinates is (num_y / den, num_x / den): the mean
    of the cell-coordinate centres ((r + 0.5) / 2, (c + 0.5) / 2) of the ridge points
    within smooth_px (image px) of it (itself included). With n such points and sums S_r, S_c of
    their half-pixel indices, the mean is ((2 S_r + n) / (4 n), (2 S_c + n) / (4 n)).
    Membership is decided on exact integer squared distances in half pixels: cKDTree finds
    the points of a slightly larger ball (indices sorted), so its float test never decides.
    """
    reach = 2 * smooth_px                                     # in half pixels
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
    most radius + 3 px from the point in each axis and q <= 2 s _max_den(smooth_px), so
    a^2 + b^2 <= 2 (2 s _max_den (radius + 3))^2; draw_lines refuses a supersample and
    width for which that reaches 2^53 (at smooth_px 1.5, s = 4 allows widths up to about
    144000 px; s = 64, about 9000 px). The right side is float64,
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


def centre_line(ridge, smooth_px: float) -> tuple[np.ndarray, np.ndarray]:
    """The centre line paint_lines draws one line around: (points, edges).

    points: (n, 2) float64 (row, col) in cell coordinates (image px), the smoothed points
    of paint_lines' steps 0 and 1 (_smoothed(_bridged(ridge)), num / den), around each of
    which it paints a disc. edges: (m, 2) int64 index pairs (i < j) of the joined ridge's
    8-adjacent half pixels (_adjacent), which join every point: the joined ridge is
    8-connected (its pieces are, and each bridge adds the 8-connected run _segment
    between two of its points). tdmg.colored_flat records them in model mm, and
    tdmg.color_gcode's F3.line_coverage samples the edges as straight segments.
    ridge: a non-empty sequence of non-negative half-pixel (row, col) integers;
    smooth_px: as paint_lines' (color.lines.ridge_smooth). ColorError otherwise."""
    top = np.iinfo(np.int64).max
    pts = _bridged(_check_ridge(ridge, top, top))
    num_y, num_x, den = _smoothed(pts, finite_positive("smooth_px", smooth_px))
    i, j = _adjacent(pts)
    return (np.column_stack([num_y / den, num_x / den]),
            np.column_stack([i, j]).astype(np.int64))


def draw_lines(fine: np.ndarray, supersample: int, lines, width_px: float, *,
               smooth_px: float) -> np.ndarray:
    """The fine map with the lines drawn at width_px: paint_lines' map."""
    return paint_lines(fine, supersample, lines, width_px, smooth_px=smooth_px)[0]


def paint_lines(fine: np.ndarray, supersample: int, lines, width_px: float, *,
                smooth_px: float, owners: bool = False):
    """The fine map with the lines drawn at width_px (design item 4), and how many fine
    pixels each line changed (in the given order; 0 for a line that changed none): (map,
    counts). With owners, also an int64 map of fine's shape giving, for each fine pixel,
    the index (in the given order) of the line that painted it last, or -1: (map, counts,
    owner). smooth_px: the ridge smoothing radius in image px (color.lines.ridge_smooth),
    a finite number above 0.

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
    0. Its ridge's pieces are joined (_bridged, tree only): find_lines' stroke ridge can
       break into pieces along a curve (gaps of up to 4.5 px on the test fixture, a 4 px
       red line of radius 60 px, 6 px with its fringe), which would pinch or cut the
       drawn line. find_lines already joins them (with the found line's mask, so closed
       loops stay closed), so its ridge is one piece and this step leaves it as it is; a
       ridge given in pieces is joined by the shortest bridges that connect them all (a
       minimum spanning tree), with no distance limit. This is a step beyond the plan's
       two, found by testing (the arc in tests/test_color_lines.py drew in two pieces
       without it).
    1. Its ridge is smoothed: each point moves to the mean of the line's ridge points
       within smooth_px of it, itself included (each line on its own). This removes
       the half-pixel staircase of a ridge at an angle, which would bead the drawn edges.
       Near an end the mean lies inward, so the drawn line is a little shorter than with
       the raw ridge: on a straight ridge two half pixels thick (find_lines' ridge of a
       line an even number of px wide) the end point moves 9/14 px (0.64 px) along it,
       on one half pixel thick 0.75 px (at smooth_px 1.5; tests/test_color_lines.py).
       The raw ridge starts about 1.5 px inside the found line's end and the drawn end
       cap reaches width_px / 2 beyond the smoothed end, so the drawn line still reaches
       near the found line's end.
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
    smooth = finite_positive("smooth_px", smooth_px)
    if 2 * (2 * s * _max_den(smooth) * (radius + 3)) ** 2 >= 2.0 ** 53:
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
    counts = []
    owner = np.full(out.size, -1, np.int64) if owners else None
    for k, (color, host, pts) in enumerate(todo):
        if color == host:
            counts.append(0)
            continue
        idx = _disc_pixels(*_smoothed(_bridged(pts), smooth), s, radius, out.shape)
        idx = idx[flat[idx] == host]
        flat[idx] = color
        if owner is not None:
            owner[idx] = k
        counts.append(len(idx))
    if owner is not None:
        return out, tuple(counts), owner.reshape(out.shape)
    return out, tuple(counts)

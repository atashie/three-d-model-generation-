"""tdmg.color_lines.find_lines and draw_lines: thin lines inside one other color
(docs/plans/2026-11-19-widen-lines.md, Tasks 3-4). Synthetic images built here."""

import math

import numpy as np
import pytest
from scipy import ndimage
from scipy.spatial import cKDTree

from tdmg.color import OUTSIDE, ColorError, Limits, from_labels, printable_limits_px
from tdmg.color_lines import (
    RIDGE_SMOOTH_PX,
    Line,
    _bridged,
    _segment,
    draw_lines,
    find_lines,
)
from tdmg.color_outline import stroke_ridge
from tdmg.profiles import load_printer
from tdmg.rules import load_rules
from tdmg.smoothing import smooth_labels

RULES = load_rules()
# 0.1 mm/px: opening 4 px, island area 64 px.
LIMITS = printable_limits_px(0.1, RULES, load_printer("bambu-a1"))
HOST_SHARE = RULES["color.lines.host_share"].default
MIN_ELONGATION = RULES["color.lines.min_elongation"].default

# Palette rows (the order given to from_labels; q.remap maps them to q's indices).
# In CIELAB, DARK is nearest RED and BLACK nearest BROWN (checked in test_palette_nearest).
RED, BROWN, DARK, GREEN, BLACK = 0, 1, 2, 3, 4
PALETTE = np.array([(200, 30, 30), (130, 85, 45), (140, 20, 25), (40, 150, 60), (15, 10, 10)],
                   np.uint8)


def quantized(rows: np.ndarray):
    """A Quantized from a map of palette rows (OUTSIDE allowed)."""
    return from_labels(rows, PALETTE, iterations=0, converged=True,
                       n_requested=len(PALETTE), n_distinct_colors=len(PALETTE))


def ix(q, row: int) -> int:
    return q.remap[row]


def run(q, family_rows=(), limits=LIMITS, width_px=4.0, host_share=HOST_SHARE,
        min_elongation=MIN_ELONGATION):
    family = tuple(sorted(ix(q, r) for r in family_rows))
    return find_lines(q, family, limits, width_px, host_share, min_elongation)


def ridge_centres(line: Line) -> np.ndarray:
    """The ridge half pixels' centres in pixel-index coordinates (pixel i's centre is i):
    half pixel r covers [r/2 - 1/2, r/2] of the pixel axis, so its centre is r/2 - 1/4."""
    return np.array(line.ridge, float) / 2 - 0.25


# --- The curved line: a 4 px red arc with a 1 px dark fringe each side, in brown ---------

ARC_C, ARC_R = (100.0, 100.0), 60.0
ARC_FROM, ARC_TO = math.radians(200), math.radians(340)   # the upper half, not closed


def arc_image(n: int = 200) -> np.ndarray:
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    d = np.hypot(yy - ARC_C[0], xx - ARC_C[1]) - ARC_R
    ang = np.mod(np.arctan2(yy - ARC_C[0], xx - ARC_C[1]), 2 * math.pi)
    on = (ang >= ARC_FROM) & (ang <= ARC_TO)
    rows = np.full((n, n), BROWN, np.int64)
    rows[on & (np.abs(d) < 3)] = DARK
    rows[on & (np.abs(d) < 2)] = RED
    return rows


def test_palette_nearest():
    """The fixtures' premise: DARK is nearest RED, BLACK nearest BROWN in CIELAB."""
    q = quantized(np.arange(5).repeat(320).reshape(40, 40))
    lab = np.asarray(q.lab)

    def nearest(row, among):
        d = [((lab[ix(q, row)] - lab[ix(q, a)]) ** 2).sum() for a in among]
        return among[int(np.argmin(d))]

    assert nearest(DARK, [RED, BROWN, GREEN]) == RED
    assert nearest(BLACK, [RED, BROWN, GREEN]) == BROWN


def test_curved_line_with_family_fringe():
    q = quantized(arc_image())
    lines = run(q, family_rows=(DARK,))
    assert len(lines) == 1
    (line,) = lines
    assert (line.color, line.host) == (ix(q, RED), ix(q, BROWN))
    # The view counts the fringe as red: the part is the arc with its fringe, 6 px wide.
    assert line.width_px == pytest.approx(6.0, abs=0.5)
    # Its length: the arc's centre line, 140 degrees of a 60 px radius (146.6 px).
    assert line.length_px == pytest.approx(ARC_R * (ARC_TO - ARC_FROM), rel=0.1)
    # Away from the two end caps, every ridge point is within 1 px of the drawn centre line.
    c = ridge_centres(line)
    d = np.hypot(c[:, 0] - ARC_C[0], c[:, 1] - ARC_C[1]) - ARC_R
    ang = np.mod(np.arctan2(c[:, 0] - ARC_C[0], c[:, 1] - ARC_C[1]), 2 * math.pi)
    cap = 4.0 / ARC_R                                    # 4 px of arc at each end
    mid = (ang >= ARC_FROM + cap) & (ang <= ARC_TO - cap)
    assert mid.sum() > 0.9 * len(c)
    assert np.abs(d[mid]).max() <= 1.0
    # At the caps the ridge runs to the corners, still inside the 6 px line's pixels.
    assert np.abs(d).max() <= 3.5
    assert list(line.ridge) == sorted(line.ridge)


def test_without_family_the_fringe_splits_the_ring():
    """With an empty family the view is q.labels: the 4 px red core alone is the candidate,
    and its 2 px ring is half the 1 px dark fringe and half brown, so it has no host. The
    color view is what makes the fringe part of the line."""
    assert run(quantized(arc_image())) == ()


def test_border_strip_between_wide_colors_is_not_a_line():
    rows = np.full((60, 80), BROWN, np.int64)
    rows[:, 40:] = GREEN
    rows[:, 39:41] = BLACK                               # family strip on the border
    q = quantized(rows)
    assert run(q, family_rows=(BLACK,)) == ()


def test_round_dot_is_not_a_line():
    """A disc 11 px across: area 97 px (above the 64 px island area), removed whole by the
    12 px opening (width_px 6), but its length is under 3 x its width."""
    yy, xx = np.mgrid[0:60, 0:60]
    rows = np.full((60, 60), BROWN, np.int64)
    dot = np.hypot(yy - 30, xx - 30) <= 5.5
    rows[dot] = RED
    assert dot.sum() >= LIMITS.min_area_px
    q = quantized(rows)
    assert run(q, width_px=6.0) == ()
    # Not the host share or the area: with no elongation limit to speak of, it is found.
    assert len(run(q, width_px=6.0, min_elongation=0.1)) == 1


def test_line_joined_to_wide_disc_finds_only_the_line():
    """The garnish case: a 4 px red line runs out of a red disc 40 px across."""
    yy, xx = np.mgrid[0:100, 0:140]
    rows = np.full((100, 140), BROWN, np.int64)
    disc = np.hypot(yy - 50, xx - 35) <= 20
    rows[disc] = RED
    rows[48:52, 50:120] = RED                            # 4 px wide, to column 119
    q = quantized(rows)
    lines = run(q)
    assert len(lines) == 1
    (line,) = lines
    assert (line.color, line.host) == (ix(q, RED), ix(q, BROWN))
    c = ridge_centres(line)
    assert np.hypot(c[:, 0] - 50, c[:, 1] - 35).min() > 18   # no ridge inside the disc
    assert c[:, 1].max() > 115
    assert 200 <= line.area_px <= 300                    # the ~66 px of line beyond the disc
    assert line.width_px == pytest.approx(4.0, abs=0.5)


def test_line_on_a_border_has_no_host():
    """A 4 px red line between brown (above) and green (below): its ring is half one color
    and half the other, below the host share."""
    rows = np.full((60, 100), BROWN, np.int64)
    rows[30:, :] = GREEN
    rows[28:32, 10:90] = RED
    q = quantized(rows)
    assert run(q) == ()
    rows[30:, :] = BROWN                                 # the control: one host
    q = quantized(rows)
    assert [(ln.color, ln.host) for ln in run(q)] == [(ix(q, RED), ix(q, BROWN))]


def test_line_touching_outside_has_no_host():
    """A line along the subject's edge: OUTSIDE is half its ring and is never a host."""
    rows = np.full((60, 100), OUTSIDE, np.int64)
    rows[:30, :] = BROWN
    rows[26:30, 10:90] = RED
    assert run(quantized(rows)) == ()


def test_straight_line_fixed_values():
    """A 4 x 160 px red line in brown: fixed expected values (computed with the first,
    uncropped implementation, 2a81caa). Width: the exact distances across are 1, 2, 2, 1,
    so the 90th percentile is 2 and the width 4. The ridge is the two middle half-pixel
    rows (303, 304) of the 8 half pixels across (300-307); it starts at half pixel 43,
    1.5 px in from the line's end at column 20, where the end cap's distances fall."""
    rows = np.full((200, 200), BROWN, np.int64)
    rows[150:154, 20:180] = RED
    q = quantized(rows)
    (line,) = run(q)
    assert (line.color, line.host, line.area_px) == (ix(q, RED), ix(q, BROWN), 640)
    assert line.width_px == 4.0
    assert line.length_px == 160.0
    assert line.ridge[0] == (303, 43)
    assert len(line.ridge) == 628
    assert {r for r, _ in line.ridge} == {303, 304}


def test_deterministic_and_sorted():
    rows = arc_image()
    rows[150:154, 20:180] = RED                           # a second, straight line
    q1, q2 = quantized(rows), quantized(rows.copy())
    a, b = run(q1, family_rows=(DARK,)), run(q2, family_rows=(DARK,))
    assert a == b
    assert len(a) == 2
    assert [(ln.color, ln.ridge[0]) for ln in a] == sorted((ln.color, ln.ridge[0]) for ln in a)


def test_turkey_like_at_real_scale():
    """A brown body with a black outline (family), two red lines with darker red sides
    (family), a red speck and a wide red area, at roadie-thanksgiving's numbers:
    min_width_px 4.79, min_area_px 91.6, width_px 4.91 (0.41 mm)."""
    mm_per_px = 0.4 / 4.79
    limits = Limits(min_width_px=4.79, min_area_px=91.6, mm_per_px=mm_per_px,
                    opening_width_mm=0.4, island_area_mm2=91.6 * mm_per_px ** 2,
                    nozzle_diameter_mm=0.4, opening_rule="flat.sliver.opening_width",
                    island_rule="flat.island.min_square_side")
    n = 180
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    rows = np.full((n, n), OUTSIDE, np.int64)
    body = np.hypot(yy - 90, xx - 90) <= 80
    rows[body] = BROWN
    rows[body & (np.hypot(yy - 90, xx - 90) > 77)] = BLACK      # 3 px outline at the edge
    # Line 1: a straight red line 3 px wide with 1 px dark sides, 60 px long.
    rows[59:64, 40:100] = DARK
    rows[60:63, 40:100] = RED
    # Line 2: a red arc 3 px wide with dark sides, radius 40 about (110, 90).
    d = np.hypot(yy - 110, xx - 90) - 40
    arc = (yy > 110) & body
    rows[arc & (np.abs(d) <= 2.5)] = DARK
    rows[arc & (np.abs(d) <= 1.5)] = RED
    # A red speck (3 x 3) and a wide red area 30 px across (the garnish), apart.
    rows[40:43, 120:123] = RED
    rows[(np.hypot(yy - 80, xx - 140) <= 15) & body] = RED
    q = quantized(rows)
    lines = run(q, family_rows=(DARK, BLACK), limits=limits, width_px=4.91)
    assert len(lines) == 2
    assert {(ln.color, ln.host) for ln in lines} == {(ix(q, RED), ix(q, BROWN))}
    for ln in lines:
        assert ln.width_px == pytest.approx(5.0, abs=1.0)
    # Sorted by first ridge point: the straight line (rows 59-63) comes before the arc.
    straight, curved = (ridge_centres(ln) for ln in lines)
    assert straight[:, 0].min() >= 59 and straight[:, 0].max() <= 63
    assert straight[:, 1].min() >= 40 and straight[:, 1].max() <= 100
    assert straight[:, 1].max() - straight[:, 1].min() > 50
    dc = np.hypot(curved[:, 0] - 110, curved[:, 1] - 90) - 40
    assert np.abs(dc).max() <= 2.5 and curved[:, 0].min() > 110
    assert curved[:, 1].max() - curved[:, 1].min() > 60
    for c in (straight, curved):                         # none in the speck or the garnish
        in_speck = (c[:, 0] >= 39) & (c[:, 0] <= 43) & (c[:, 1] >= 119) & (c[:, 1] <= 123)
        assert not in_speck.any()
        assert np.hypot(c[:, 0] - 80, c[:, 1] - 140).min() > 16


@pytest.mark.parametrize("kwargs, match", [
    ({"width_px": 0}, "width_px"),
    ({"width_px": float("nan")}, "width_px"),
    ({"width_px": True}, "width_px"),
    ({"host_share": 0}, "host_share"),
    ({"host_share": 1.5}, "host_share"),
    ({"host_share": True}, "host_share"),
    ({"min_elongation": -1}, "min_elongation"),
    ({"min_elongation": float("inf")}, "min_elongation"),
    ({"min_elongation": "3"}, "min_elongation"),
])
def test_bad_numbers_refused(kwargs, match):
    q = quantized(arc_image(40))
    args = {"width_px": 4.0, "host_share": 0.9, "min_elongation": 3.0, **kwargs}
    with pytest.raises(ColorError, match=match):
        find_lines(q, (), LIMITS, **args)


@pytest.mark.parametrize("family", [(9,), (1, 1), (True,), [0], (-1,), (1, 0)])
def test_bad_family_refused(family):
    q = quantized(arc_image(40))
    with pytest.raises(ColorError, match="family"):
        find_lines(q, family, LIMITS, 4.0, 0.9, 3.0)


def test_bad_q_and_limits_refused():
    q = quantized(arc_image(40))
    with pytest.raises(ColorError, match="Quantized"):
        find_lines(np.zeros((4, 4), int), (), LIMITS, 4.0, 0.9, 3.0)
    with pytest.raises(ColorError, match="Limits"):
        find_lines(q, (), {"min_area_px": 1}, 4.0, 0.9, 3.0)


def test_strip_along_the_image_edge_is_not_a_line():
    """The frame beyond the image counts as OUTSIDE: a strip on rows 0-3 of a brown image
    has half its ring beyond the image, so it is not inside one color."""
    rows = np.full((40, 100), BROWN, np.int64)
    rows[0:4, 10:90] = RED
    assert run(quantized(rows)) == ()
    rows[0:4] = BROWN                                    # the control: two rows in
    rows[2:6, 10:90] = RED
    assert len(run(quantized(rows))) == 1


def edge_line(sides) -> np.ndarray:
    """A 4 px red line on rows 2-5, columns 10-89, in brown; rows 0-1 above it OUTSIDE;
    beside its ends (rows 2-7, columns 0-9 and 90-99) `sides`. Its 2 px ring (columns
    8-91, rows 0-7, less the line): 168 px above (OUTSIDE), 24 px beside its ends
    (`sides`), 160 px below (brown), 352 px in all."""
    rows = np.full((30, 100), BROWN, np.int64)
    rows[0:2] = OUTSIDE
    rows[2:8, :10] = sides
    rows[2:8, 90:] = sides
    rows[2:6, 10:90] = RED
    return rows


def test_outside_most_common_is_never_a_host():
    """OUTSIDE is the most common ring value (192 of 352 px) but below the share; brown
    (160, 0.45) is above a share of 0.4. Still no line: the host is the most common value,
    and that is OUTSIDE. With brown beside the ends, brown is most common (184) and is the
    host."""
    q = quantized(edge_line(OUTSIDE))
    assert run(q, host_share=0.4) == ()
    q = quantized(edge_line(BROWN))
    assert [(ln.color, ln.host) for ln in run(q, host_share=0.4)] == [
        (ix(q, RED), ix(q, BROWN))]
    assert run(q, host_share=0.6) == ()                  # 184 / 352 = 0.52


def test_piece_below_the_island_area_is_skipped():
    rows = np.full((40, 100), BROWN, np.int64)
    rows[18:22, 10:25] = RED                             # 60 px, below 64
    assert run(quantized(rows), min_elongation=0.1) == ()
    rows[18:22, 10:26] = RED                             # 64 px: a line
    assert len(run(quantized(rows), min_elongation=0.1)) == 1


def test_candidate_with_no_other_color_in_its_ring_is_skipped(monkeypatch):
    """A ring with no pixel of another color (only reachable when the areas surround a
    candidate; forced here by an opening that keeps all but an inner 10 x 10 square)."""
    import tdmg.color_lines as cl

    def fake_open(mask, width_px):
        keep = np.asarray(mask, bool).copy()
        ys, xs = np.nonzero(keep)
        cy, cx = (ys.min() + ys.max()) // 2, (xs.min() + xs.max()) // 2
        keep[cy - 5:cy + 5, cx - 5:cx + 5] = False
        return keep

    rows = np.full((60, 60), BROWN, np.int64)
    rows[10:50, 10:50] = RED
    monkeypatch.setattr(cl, "open_mask", fake_open)
    assert run(quantized(rows), min_elongation=0.01) == ()


# --- The cropped computation equals a plain whole-image one -----------------------------

def reference_find_lines(q, family, limits, width_px, host_share, min_elongation):
    """The method of tdmg.color_lines written plainly on the whole image, with no crops."""
    from scipy import ndimage

    from tdmg.color import d2_nearest, open_mask
    from tdmg.color_outline import stroke_ridge

    labels = np.asarray(q.labels).astype(np.int64)
    lab = np.asarray(q.lab)
    nonfam = [i for i in range(len(q.hex)) if i not in family]
    view = labels.copy()
    for f in family:
        view[labels == f] = nonfam[int(np.argmin(((lab[nonfam] - lab[f]) ** 2).sum(1)))]
    framed = np.pad(view, 2, constant_values=OUTSIDE)
    out = []
    for c in nonfam:
        mine = view == c
        pieces, n = ndimage.label(mine, structure=ndimage.generate_binary_structure(2, 1))
        for li in range(1, n + 1):
            piece = pieces == li
            if piece.sum() < limits.min_area_px:
                continue
            thin = piece & ~open_mask(piece, 2 * width_px)
            parts, m = ndimage.label(thin, structure=ndimage.generate_binary_structure(2, 2))
            for pj in range(1, m + 1):
                part = parts == pj
                area = int(part.sum())
                if area < limits.min_area_px:
                    continue
                ring = ndimage.binary_dilation(np.pad(part, 2), structure=np.ones((5, 5), bool))
                values = framed[ring & (framed != c)]
                if not values.size:
                    continue
                vals, counts = np.unique(values, return_counts=True)
                host = int(vals[np.argmax(counts)])
                if host == OUTSIDE or counts.max() < host_share * values.size:
                    continue
                ty, tx = np.nonzero(part)
                d = np.sqrt(d2_nearest(~np.pad(piece, 1), ty + 1, tx + 1).astype(float))
                w = 2.0 * float(np.percentile(d, 90))
                length = area / max(w, 1.0)
                if length / max(w, 1.0) < min_elongation:
                    continue
                ry, rx = np.nonzero(stroke_ridge(np.repeat(np.repeat(part, 2, 0), 2, 1)))
                out.append(Line(c, host, area, w, length,
                                tuple(sorted(zip(ry.tolist(), rx.tolist())))))
    out.sort(key=lambda ln: (ln.color, ln.ridge[0]))
    return tuple(out)


def irregular_image(seed: int) -> np.ndarray:
    """Smoothed noise in four colors, with OUTSIDE at one side and random 3-5 px lines."""
    from scipy import ndimage

    rng = np.random.default_rng(seed)
    noise = ndimage.gaussian_filter(rng.standard_normal((120, 150)), 6)
    rows = np.digitize(noise, np.quantile(noise, [0.3, 0.6, 0.85])).astype(np.int64)
    rows = np.array([BROWN, GREEN, BLACK, DARK])[rows]
    rows[:, :8] = OUTSIDE
    for _ in range(12):
        y, x = int(rng.integers(0, 120)), int(rng.integers(0, 150))
        dy, dx = (int(v) for v in rng.integers(-60, 60, 2))
        w = int(rng.integers(3, 6))
        for t in np.linspace(0, 1, 200):
            yy, xx = int(y + dy * t) - w // 2, int(x + dx * t) - w // 2
            rows[max(yy, 0):max(yy + w, 0), max(xx, 0):max(xx + w, 0)] = RED
    return rows


CROP_CASES = [((), 0.6, 1.0), ((DARK,), 0.6, 1.0), ((BLACK,), 0.9, 3.0)]


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("family_rows, share, elong", CROP_CASES)
def test_cropped_equals_whole_image(seed, family_rows, share, elong):
    q = quantized(irregular_image(seed))
    family = tuple(sorted(ix(q, r) for r in family_rows))
    got = find_lines(q, family, LIMITS, 4.0, share, elong)
    assert got == reference_find_lines(q, family, LIMITS, 4.0, share, elong)


def test_cropped_equals_whole_image_finds_lines():
    """The comparison above is not vacuous: each case finds lines (seed 1: 5, 8 and 2)."""
    q = quantized(irregular_image(1))
    for family_rows, share, elong in CROP_CASES:
        family = tuple(sorted(ix(q, r) for r in family_rows))
        assert len(find_lines(q, family, LIMITS, 4.0, share, elong)) >= 2


def comb(n: int, teeth: int) -> np.ndarray:
    """A red comb in brown: a 40 px spine and 4 px teeth every 10 px, n - 100 px long."""
    rows = np.full((n, n), BROWN, np.int64)
    rows[20:60, 20:n - 20] = RED
    for x in 30 + 10 * np.arange(teeth):
        rows[60:n - 40, x:x + 4] = RED
    return rows


def test_comb_timing():
    """A coarse guard: a 1000 x 1000 comb with 96 teeth (the 96 red teeth and the 95 brown
    gaps between them are lines) took 32 s before the per-candidate crop on the Windows PC
    (2026-11-19). The limit is generous for slower runners."""
    import time

    q = quantized(comb(1000, 96))
    t0 = time.perf_counter()
    lines = run(q)
    elapsed = time.perf_counter() - t0
    assert len(lines) == 191
    assert elapsed < 10.0


def test_every_color_in_the_family_finds_nothing():
    q = quantized(arc_image())
    assert find_lines(q, tuple(range(len(q.hex))), LIMITS, 4.0, 0.9, 3.0) == ()


# --- draw_lines ----------------------------------------------------------------------------

S = 4                    # the fine map's supersample (tdmg.smoothing.SUPERSAMPLE)
DRAW_W = 4.9             # 0.41 mm at 0.0836 mm/px (roadie-thanksgiving)
HOST, INK, THIRD = 1, 2, 3


def straight_ridge(row0=100, col0=40, col1=360, rows=2):
    """A horizontal ridge `rows` half pixels thick, half-pixel columns col0..col1 - 1."""
    return tuple((r, c) for r in range(row0, row0 + rows) for c in range(col0, col1))


def ring_ridge(centre, radius, a0, a1, n_px, width=4.0):
    """find_lines' kind of ridge (stroke_ridge at half-pixel resolution) of an arc `width`
    px wide, angles a0..a1 (radians, atan2 of (y, x), y down), centre in cell coordinates."""
    r, c = np.mgrid[0:2 * n_px, 0:2 * n_px]
    y, x = (r + 0.5) / 2, (c + 0.5) / 2
    d = np.hypot(y - centre[0], x - centre[1]) - radius
    ang = np.mod(np.arctan2(y - centre[0], x - centre[1]), 2 * math.pi)
    mask = (np.abs(d) <= width / 2) & (ang >= a0) & (ang <= a1)
    ry, rx = np.nonzero(stroke_ridge(mask))
    return tuple(zip(ry.tolist(), rx.tolist()))


def width_along(fine, label, point, normal, s=S, reach=6.0, step=0.002):
    """The length (image px) of the run of `label` through `point` (cell coordinates) along
    `normal`, sampled every `step` px; each sample takes the fine pixel it falls in."""
    t = np.arange(-reach, reach + step / 2, step)
    y, x = point[0] + t * normal[0], point[1] + t * normal[1]
    on = fine[np.floor(y * s).astype(int), np.floor(x * s).astype(int)] == label
    mid = len(t) // 2
    assert on[mid], f"no {label} at {point}"
    lo, hi = mid, mid
    while lo > 0 and on[lo - 1]:
        lo -= 1
    while hi < len(t) - 1 and on[hi + 1]:
        hi += 1
    assert 0 < lo and hi < len(t) - 1, "the run reaches the sampling window's end"
    return (hi - lo + 1) * step


def test_draw_straight_band_width():
    fine = np.full((60 * S, 200 * S), HOST, np.uint8)
    out = draw_lines(fine, S, [(INK, HOST, straight_ridge())], DRAW_W)
    across = (out == INK).sum(axis=0)
    # Away from the ends (raw ridge: cell x 20.25..179.75), 3 px in from each.
    cols = np.arange(int(23.25 * S), int(176.75 * S))
    assert np.all(np.abs(across[cols] - DRAW_W * S) <= 1)
    # Centred on the ridge's middle, cell row 50.5: centres in 48.05..52.95, rows 192..211.
    rows = np.nonzero((out == INK).any(axis=1))[0]
    assert (rows.min(), rows.max()) == (192, 211)


def test_draw_ends_pulled_in_by_smoothing():
    """The end shortening the docstring states. The raw ridge (two half pixels thick) ends
    at cell x 20.25; the smoothed end point lies 9/14 px further in (the mean of the 7
    ridge points within 1.5 px: half-pixel columns 40-43 in its row, 40-42 in the other),
    so the first painted fine column is the first centre at or beyond
    20.25 + 9/14 - 4.9 / 2."""
    fine = np.full((60 * S, 200 * S), HOST, np.uint8)
    out = draw_lines(fine, S, [(INK, HOST, straight_ridge())], DRAW_W)
    cols = np.nonzero((out == INK).any(axis=0))[0]
    first = 20.25 + 9 / 14 - DRAW_W / 2
    assert cols.min() == math.ceil(first * S - 0.5)
    assert cols.max() == 200 * S - 1 - cols.min()                  # symmetric
    # One half pixel thick: the end moves 0.75 px (the mean of half-pixel columns 40-43).
    out1 = draw_lines(fine, S, [(INK, HOST, straight_ridge(rows=1))], DRAW_W)
    cols1 = np.nonzero((out1 == INK).any(axis=0))[0]
    assert cols1.min() == math.ceil((20.25 + 0.75 - DRAW_W / 2) * S - 0.5)
    assert RIDGE_SMOOTH_PX == 1.5


def test_draw_quarter_circle_width_along_normals():
    centre, radius = (10.0, 10.0), 30.0
    ridge = ring_ridge(centre, radius, 0.0, math.pi / 2, 50)
    fine = np.full((50 * S, 50 * S), HOST, np.uint8)
    out = draw_lines(fine, S, [(INK, HOST, ridge)], DRAW_W)
    widths = []
    for a in np.linspace(math.radians(10), math.radians(80), 20):
        u = (math.sin(a), math.cos(a))
        p = (centre[0] + radius * u[0], centre[1] + radius * u[1])
        widths.append(width_along(out, INK, p, u))
    assert np.all(np.abs(np.array(widths) - DRAW_W) <= 0.35), widths


def test_draw_never_paints_a_third_color():
    fine = np.full((60 * S, 200 * S), HOST, np.uint8)
    fine[:, 400:440] = THIRD                       # a stripe across the band
    out = draw_lines(fine, S, [(INK, HOST, straight_ridge())], DRAW_W)
    assert np.array_equal(out[:, 400:440], fine[:, 400:440])
    assert (out[:, 399] == INK).sum() == (out[:, 440] == INK).sum() > 0
    # A pixel of the line's own color in its band stays (painting it is a no-op).
    fine[200, 300] = INK
    assert draw_lines(fine, S, [(INK, HOST, straight_ridge())], DRAW_W)[200, 300] == INK


def test_draw_later_line_does_not_paint_an_earlier_one():
    fine = np.full((60 * S, 200 * S), HOST, np.uint8)
    a = (INK, HOST, straight_ridge())
    b = (THIRD, HOST, tuple((r, 200) for r in range(60, 140)))   # vertical, crossing a
    ab, ba = draw_lines(fine, S, [a, b], DRAW_W), draw_lines(fine, S, [b, a], DRAW_W)
    cross = (slice(195, 210), slice(400 - 4, 400 + 4))
    assert np.all(ab[cross] == INK) and np.all(ba[cross] == THIRD)


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16, np.int32, np.int64])
def test_draw_input_unchanged_dtype_kept(dtype):
    fine = np.full((60 * S, 200 * S), HOST, dtype)
    fine.setflags(write=False)                     # as smooth_labels returns it
    before = fine.copy()
    out = draw_lines(fine, S, [(INK, HOST, straight_ridge())], DRAW_W)
    assert np.array_equal(fine, before)
    assert out.dtype == fine.dtype and out.shape == fine.shape
    assert not np.shares_memory(out, fine)
    assert (out == INK).any()


def test_draw_color_equal_host_skipped_and_no_lines():
    fine = np.full((60 * S, 200 * S), HOST, np.uint8)
    assert np.array_equal(draw_lines(fine, S, [(HOST, HOST, straight_ridge())], DRAW_W),
                          fine)
    assert np.array_equal(draw_lines(fine, S, [], DRAW_W), fine)


def test_draw_ridge_beyond_the_map_is_clipped():
    fine = np.full((10 * S, 10 * S), HOST, np.uint8)
    out = draw_lines(fine, S, [(INK, HOST, ((0, 0), (0, 1), (100, 100)))], DRAW_W)
    assert out[0, 0] == INK and 0 < (out == INK).sum() < fine.size


def test_draw_deterministic_and_ridge_order_irrelevant():
    ridge = ring_ridge((10.0, 10.0), 30.0, 0.0, math.pi / 2, 50)
    fine = np.full((50 * S, 50 * S), HOST, np.uint8)
    a = draw_lines(fine, S, [(INK, HOST, ridge)], DRAW_W)
    b = draw_lines(fine, S, [(INK, HOST, tuple(reversed(ridge)))], DRAW_W)
    c = draw_lines(fine, S, [(INK, HOST, np.array(ridge))], DRAW_W)
    assert np.array_equal(a, b) and np.array_equal(a, c)


def test_draw_matches_a_plain_float_reference():
    """The exact-fraction implementation against a plain float form (cKDTree ball means,
    nearest smoothed point of every fine pixel centre): they may differ only on pixels
    whose distance is within 1e-9 px of the radius. Both start from the bridged ridge
    (the bridges are tested on their own below)."""
    ridge = np.array(ring_ridge((10.0, 10.0), 30.0, 0.0, math.pi / 2, 50))
    fine = np.full((50 * S, 50 * S), HOST, np.uint8)
    out = draw_lines(fine, S, [(INK, HOST, ridge)], DRAW_W)
    cell = (_bridged(ridge) + 0.5) / 2
    near = cKDTree(cell).query_ball_point(cell, RIDGE_SMOOTH_PX)
    smooth = np.array([cell[sorted(n)].mean(axis=0) for n in near])
    ii, jj = np.mgrid[0:fine.shape[0], 0:fine.shape[1]]
    cen = np.stack([((ii + 0.5) / S).ravel(), ((jj + 0.5) / S).ravel()], 1)
    d = cKDTree(smooth).query(cen)[0].reshape(fine.shape)
    differ = (d <= DRAW_W / 2) != (out == INK)
    assert np.all(np.abs(d[differ] - DRAW_W / 2) < 1e-9)


def test_draw_joins_every_piece_of_a_ridge():
    """find_lines' ridge can break into pieces along a curve (the arc fixture's ridge is 50
    8-connected pieces, with gaps up to 4.5 px). All pieces of one line are joined, with no
    distance limit: the band is whole and its width holds across a gap, whatever the gap
    or the drawn width."""
    fine = np.full((60 * S, 200 * S), HOST, np.uint8)
    ridge = straight_ridge()
    eight = np.ones((3, 3), bool)
    gap = tuple(p for p in ridge if not 190 <= p[1] < 198)        # 189 to 198: 4.5 px gap
    out = draw_lines(fine, S, [(INK, HOST, gap)], DRAW_W)
    assert ndimage.label(out == INK, structure=eight)[1] == 1
    across = (out == INK).sum(axis=0)
    assert np.all(np.abs(across[95 * S:100 * S] - DRAW_W * S) <= 1)
    # A 10.5 px gap, more than twice the drawn width, is joined too.
    far = tuple(p for p in ridge if not 190 <= p[1] < 211)
    assert ndimage.label(draw_lines(fine, S, [(INK, HOST, far)], DRAW_W) == INK,
                         structure=eight)[1] == 1
    # The arc fixture's ridge (find_lines) is in pieces; bridged, it is one.
    (line,) = run(quantized(arc_image()), family_rows=(DARK,))
    pieces = np.zeros((400, 400), bool)
    pieces[tuple(np.array(line.ridge).T)] = True
    assert ndimage.label(pieces, structure=eight)[1] == 50
    bridged = np.zeros((400, 400), bool)
    bridged[tuple(_bridged(np.array(line.ridge)).T)] = True
    assert ndimage.label(bridged, structure=eight)[1] == 1
    # Drawn much narrower than its gaps (2 px), the arc is still one piece.
    arc_fine = np.full((200 * S, 200 * S), HOST, np.uint8)
    thin = draw_lines(arc_fine, S, [(INK, HOST, line.ridge)], 2.0)
    assert ndimage.label(thin == INK, structure=eight)[1] == 1


def test_draw_two_lines_are_never_joined():
    """Two lines (two entries) are drawn on their own: their ridges are never bridged."""
    fine = np.full((60 * S, 200 * S), HOST, np.uint8)
    a = (INK, HOST, straight_ridge(col1=180))
    b = (INK, HOST, straight_ridge(col0=200))                     # 10 px further on
    out = draw_lines(fine, S, [a, b], 2.0)
    assert ndimage.label(out == INK, structure=np.ones((3, 3), bool))[1] == 2


def test_bridged_tie_break_deterministic():
    """Four pieces at a square's corners, four equally near bridges: the three with the
    lowest point indices win (0-1, 0-2, 1-3, not 2-3), whatever the input order."""
    pts = np.array([(0, 0), (0, 4), (4, 0), (4, 4)])
    a = _bridged(pts)
    assert np.array_equal(a, _bridged(pts[::-1]))
    want = [_segment(pts[0], pts[1]), _segment(pts[0], pts[2]), _segment(pts[1], pts[3])]
    assert np.array_equal(a, np.unique(np.concatenate(want), axis=0))
    assert not any((p == (4, 2)).all() for p in a)                # no 2-3 bridge


def test_bridge_segment_exact():
    seg = _segment(np.array([0, 0]), np.array([3, 7]))
    assert seg.tolist() == [[0, 0], [0, 1], [1, 2], [1, 3], [2, 4], [2, 5], [3, 6], [3, 7]]


_GOOD = np.ones((8, 8), np.uint8)


@pytest.mark.parametrize("args, match", [
    ((np.zeros((4, 4), bool), 4, [], 4.9), "integer"),
    ((np.zeros((4, 4), float), 4, [], 4.9), "integer"),
    ((np.zeros((4,), np.uint8), 4, [], 4.9), "2-D"),
    ((np.zeros((0, 4), np.uint8), 4, [], 4.9), "2-D"),
    (([[1, 1], [1, 1]], 4, [], 4.9), "2-D"),
    ((_GOOD, 0, [], 4.9), "supersample"),
    ((_GOOD, True, [], 4.9), "supersample"),
    ((_GOOD, 2.0, [], 4.9), "supersample"),
    ((_GOOD, 4, [], 0.0), "width_px"),
    ((_GOOD, 4, [], float("nan")), "width_px"),
    ((_GOOD, 4, [(2, 1)], 4.9), "each line"),
    ((_GOOD, 4, [(256, 1, ((0, 0),))], 4.9), "color_final"),
    ((_GOOD, 4, [(-1, 1, ((0, 0),))], 4.9), "color_final"),
    ((_GOOD, 4, [(2, True, ((0, 0),))], 4.9), "host_final"),
    ((_GOOD, 4, [(2, 1, ())], 4.9), "ridge"),
    ((_GOOD, 4, [(2, 1, ((0.5, 0),))], 4.9), "ridge"),
    ((_GOOD, 4, [(2, 1, ((-1, 0),))], 4.9), "ridge"),
    ((_GOOD, 4, [(2, 1, ((0, 0, 0),))], 4.9), "ridge"),
    ((_GOOD, 4, [(2, 1, ((0, 0), (1,)))], 4.9), "ridge"),
])
def test_draw_bad_arguments_refused(args, match):
    with pytest.raises(ColorError, match=match):
        draw_lines(*args)


def test_draw_checks_every_line_before_drawing():
    fine = np.full((8, 8), HOST, np.uint8)
    with pytest.raises(ColorError, match="ridge"):
        draw_lines(fine, 4, [(INK, HOST, ((0, 0),)), (INK, HOST, ())], 4.9)


def test_find_then_draw_after_cleanup_end_to_end():
    """find_lines on the arc image, the line removed from the labels as cleanup would,
    smooth_labels, then draw_lines with the found ridge: the drawn line is one 8-connected
    piece of the drawn width along its normals, reaching both ends, and nothing else
    changes."""
    rows = arc_image()
    rows[20:60, 150:190] = GREEN                   # another region, away from the arc
    q = quantized(rows)
    (line,) = run(q, family_rows=(DARK,))
    labels = np.asarray(q.labels).copy()
    red, brown, green = ix(q, RED), ix(q, BROWN), ix(q, GREEN)
    labels[(labels == red) | (labels == ix(q, DARK))] = brown     # as cleanup would
    fine = smooth_labels(labels, 2.5, S).fine
    assert not (fine == red).any()
    out = draw_lines(fine, S, [(line.color, line.host, line.ridge)], DRAW_W)
    drawn = out == red
    _, n = ndimage.label(drawn, structure=np.ones((3, 3), bool))
    assert n == 1
    assert np.array_equal(out[~drawn], fine[~drawn])
    assert np.array_equal(out == green, fine == green)
    centre = (ARC_C[0] + 0.5, ARC_C[1] + 0.5)      # pixel-index centre -> cell coordinates
    widths = []
    for a in np.linspace(ARC_FROM + 0.1, ARC_TO - 0.1, 20):    # 6 px of arc in from the ends
        u = (math.sin(a), math.cos(a))
        p = (centre[0] + ARC_R * u[0], centre[1] + ARC_R * u[1])
        widths.append(width_along(out, red, p, u))
    assert np.all(np.abs(np.array(widths) - DRAW_W) <= 0.35), widths
    # It reaches each end of the drawn arc to within 1 px of arc.
    ii, jj = np.nonzero(drawn)
    ang = np.mod(np.arctan2((ii + 0.5) / S - centre[0], (jj + 0.5) / S - centre[1]),
                 2 * math.pi)
    assert ang.min() <= ARC_FROM + 1.0 / ARC_R and ang.max() >= ARC_TO - 1.0 / ARC_R

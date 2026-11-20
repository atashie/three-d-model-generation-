"""tdmg.color_lines.find_lines and draw_lines: thin lines inside one other color
(docs/plans/2026-11-19-widen-lines.md, Tasks 3-4). Synthetic images built here."""

import dataclasses
import math

import numpy as np
import pytest
from scipy import ndimage
from scipy.spatial import cKDTree

from tdmg import color_lines
from tdmg.color import OUTSIDE, ColorError, Limits, from_labels, printable_limits_px
from tdmg.color_lines import (
    Closing,
    Line,
    _segment,
    closing_params,
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
# The ridge rules (rules/color.yaml): smoothing for draw_lines, and the loop closing.
RIDGE_SMOOTH_PX = RULES["color.lines.ridge_smooth"].default
CLOSING = closing_params(RULES["color.lines.loop_path_factor"].default,
                         RULES["color.lines.run_tolerance"].default,
                         RULES["color.lines.close_reach"].default)


def find_lines(q, family, limits, width_px, host_share, min_elongation, closing=CLOSING):
    """tdmg.color_lines.find_lines with the registry's closing rules."""
    return color_lines.find_lines(q, family, limits, width_px, host_share, min_elongation,
                                  closing)


def draw_lines(fine, supersample, lines, width_px, smooth_px=RIDGE_SMOOTH_PX):
    """tdmg.color_lines.draw_lines with the registry's ridge smoothing."""
    return color_lines.draw_lines(fine, supersample, lines, width_px, smooth_px=smooth_px)


def _bridged(pts, inside=None, closing=CLOSING):
    """tdmg.color_lines._bridged with the registry's closing rules (when given a mask)."""
    return color_lines._bridged(pts, inside, None if inside is None else closing)

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
    # 0.85: the ridge holds its bridges too (_bridged), 38 of 318 points in the caps.
    assert mid.sum() > 0.85 * len(c)
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
                halves = np.repeat(np.repeat(part, 2, 0), 2, 1)
                ry, rx = np.nonzero(stroke_ridge(halves))
                joined = _bridged(np.stack([ry, rx], axis=1), halves)
                out.append(Line(c, host, area, w, length,
                                tuple(sorted(map(tuple, joined.tolist())))))
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


def ring_ridge(centre, radius, a0, a1, n_px, width=4.0, joined=False):
    """find_lines' kind of stroke ridge (stroke_ridge at half-pixel resolution) of an arc
    `width` px wide, angles a0..a1 (radians, atan2 of (y, x), y down), centre in cell
    coordinates; joined: with its pieces joined as find_lines joins them (_bridged with
    the arc's half pixels as the mask)."""
    r, c = np.mgrid[0:2 * n_px, 0:2 * n_px]
    y, x = (r + 0.5) / 2, (c + 0.5) / 2
    d = np.hypot(y - centre[0], x - centre[1]) - radius
    ang = np.mod(np.arctan2(y - centre[0], x - centre[1]), 2 * math.pi)
    mask = (np.abs(d) <= width / 2) & (ang >= a0) & (ang <= a1)
    ry, rx = np.nonzero(stroke_ridge(mask))
    if joined:
        return tuple(map(tuple, _bridged(np.stack([ry, rx], axis=1), mask).tolist()))
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
    20.25 + 9/14 - 4.9 / 2. The 9/14 and 0.75 below follow from RIDGE_SMOOTH_PX = 1.5
    (asserted at the end); another radius gives other shifts."""
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
    b = (THIRD, HOST, tuple((r, 200) for r in range(60, 120)))   # vertical, crossing a
    ab, ba = draw_lines(fine, S, [a, b], DRAW_W), draw_lines(fine, S, [b, a], DRAW_W)
    cross = (slice(195, 210), slice(400 - 4, 400 + 4))
    assert np.all(ab[cross] == INK) and np.all(ba[cross] == THIRD)


def test_draw_later_line_paints_an_earlier_line_that_is_its_host():
    """Only pixels holding host_final at that moment change: a later line whose host is an
    earlier line's color paints over that line where they cross (order matters)."""
    fine = np.full((60 * S, 200 * S), HOST, np.uint8)
    a = (INK, HOST, straight_ridge())
    b = (THIRD, INK, tuple((r, 200) for r in range(60, 120)))    # host: a's color
    out = draw_lines(fine, S, [a, b], DRAW_W)
    cross = (slice(195, 210), slice(400 - 4, 400 + 4))
    assert np.all(out[cross] == THIRD)
    assert not (out[:150, 400] == THIRD).any()                    # only over a's band
    # The other order: b finds no INK yet and paints nothing.
    assert not (draw_lines(fine, S, [b, a], DRAW_W) == THIRD).any()


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


@pytest.mark.parametrize("ridge", [
    ((0, 0), (20, 0)),                      # row 20: one past the last half pixel (19)
    ((0, 0), (0, 20)),
    np.array([(0, 0), (2 ** 64 - 1, 0)], np.uint64),   # would wrap in int64
    np.array([(0, 0), (2 ** 63, 3)], np.uint64),
])
def test_draw_ridge_beyond_the_map_refused(ridge):
    fine = np.full((10 * S, 10 * S), HOST, np.uint8)
    with pytest.raises(ColorError, match="ridge"):
        draw_lines(fine, S, [(INK, HOST, ridge)], DRAW_W)


def test_draw_ridge_on_the_map_edges_is_clipped():
    """Ridge points on the first and last half-pixel rows and columns: the discs are
    clipped to the map, without error."""
    fine = np.full((10 * S, 10 * S), HOST, np.uint8)
    out = draw_lines(fine, S, [(INK, HOST, ((0, 0), (19, 19), (0, 19), (19, 0)))], DRAW_W)
    assert out[0, 0] == out[-1, -1] == out[0, -1] == out[-1, 0] == INK
    assert 0 < (out == INK).sum() < fine.size


def test_draw_shape_must_be_a_multiple_of_supersample():
    with pytest.raises(ColorError, match="multiple"):
        draw_lines(np.ones((10, 12), np.uint8), 4, [], DRAW_W)


def test_draw_width_too_large_for_exact_tests_refused():
    with pytest.raises(ColorError, match="too large"):
        draw_lines(np.ones((8, 8), np.uint8), 4, [], 2e5)
    draw_lines(np.ones((8, 8), np.uint8), 4, [], 1e5)              # within the bound


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
    # The arc fixture's stroke ridge is in pieces; find_lines' ridge (joined) is one.
    rows = arc_image()
    part = (rows == RED) | (rows == DARK)                # the candidate: the view's red
    raw = stroke_ridge(np.repeat(np.repeat(part, 2, 0), 2, 1))
    assert ndimage.label(raw, structure=eight)[1] > 1
    (line,) = run(quantized(rows), family_rows=(DARK,))
    joined = np.zeros((400, 400), bool)
    joined[tuple(np.array(line.ridge).T)] = True
    assert ndimage.label(joined, structure=eight)[1] == 1
    assert (raw & ~joined).sum() == 0                    # the stroke ridge is all kept
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
    """Two pieces, two equally short bridges: the one with the lowest point indices wins
    (row 0, not row 1), whatever the input order."""
    pts = np.array([(0, 0), (1, 0), (0, 3), (1, 3)])              # two vertical pieces
    a = _bridged(pts)
    assert np.array_equal(a, _bridged(pts[::-1]))
    assert np.array_equal(a, np.unique(np.concatenate([pts, [(0, 1), (0, 2)]]), axis=0))


FOUR = ndimage.generate_binary_structure(2, 1)
EIGHT = ndimage.generate_binary_structure(2, 2)


def closed_map(pts, shape):
    """The ridge as a bool map."""
    m = np.zeros(shape, bool)
    m[tuple(np.asarray(pts).T)] = True
    return m


def circle_ridge(r=40, n=100, gaps=()):
    """A one half pixel thick ridge on a circle of radius r half pixels about (n/2, n/2),
    without the points in the gaps (angle ranges in degrees), and its mask: the band
    within 3 half pixels of the circle (a ring with a hole)."""
    c = n / 2
    t = np.radians(np.arange(0, 360, 0.25))
    ang = np.degrees(t)
    keep = np.ones(len(t), bool)
    for a0, a1 in gaps:
        keep &= ~((ang >= a0) & (ang <= a1))
    pts = np.unique(np.rint(np.stack([c + r * np.sin(t[keep]), c + r * np.cos(t[keep])],
                                     axis=1)).astype(np.int64), axis=0)
    yy, xx = np.mgrid[0:n, 0:n]
    mask = np.abs(np.hypot(yy - c, xx - c) - r) <= 3
    return pts, mask


def closed(ridge, shape) -> bool:
    """Whether the ridge parts the map: the centre from the corner (4-connected)."""
    m = np.zeros(shape, bool)
    m[tuple(np.asarray(ridge).T)] = True
    parts = ndimage.label(~m, structure=FOUR)[0]
    return parts[shape[0] // 2, shape[1] // 2] != parts[0, 0]


@pytest.mark.parametrize("gaps", [((80, 90),), ((-1, 5), (175, 185))],
                         ids=["one gap, one piece", "two gaps, two pieces"])
def test_bridged_closes_a_ring_in_one_or_two_pieces(gaps):
    """Spec review of the Codex fixes: a ring whose ridge is one piece (a C) or two pieces
    has a gap the spanning tree never bridges; the closing bridges close it."""
    pts, mask = circle_ridge(gaps=gaps)
    n_pieces = ndimage.label(closed_map(pts, mask.shape), structure=EIGHT)[1]
    assert n_pieces == len(gaps)
    assert not closed(_bridged(pts), mask.shape)           # the tree alone
    assert closed(_bridged(pts, mask), mask.shape)


def test_bridged_does_not_close_a_u_whose_ends_the_line_does_not_join():
    """A U whose two tips are 16 half pixels apart across the host, in a line that also
    has a closed loop (so the mask has a hole and the closing step runs): the tips are
    far apart along the ridge, but the run between them leaves the line, so no bridge."""
    n = 200
    mask = np.zeros((n, n), bool)
    mask[40:151, 60:65] = mask[40:151, 76:81] = True          # the arms
    mask[146:151, 60:91] = True                               # the bottom, on to the loop
    mask[150:171, 90:111] = True
    mask[155:166, 95:106] = False                             # the loop's hole
    ridge = set()
    ridge |= {(r, 62) for r in range(42, 149)} | {(r, 78) for r in range(42, 149)}
    ridge |= {(148, c) for c in range(62, 93)}
    ridge |= ({(r, 92) for r in range(148, 169)} | {(r, 108) for r in range(152, 169)}
              | {(152, c) for c in range(92, 109)} | {(168, c) for c in range(92, 109)})
    pts = np.array(sorted(ridge), np.int64)
    assert np.array_equal(_bridged(pts, mask), pts)          # one piece, nothing added


def test_bridged_does_not_close_a_straight_line():
    """A straight ridge in two pieces, in a line whose mask also has a hole away from it
    (so the closing step runs): the tree joins the pieces, and nothing else is added."""
    pts = np.array(straight_ridge(row0=10, col0=10, col1=100))
    pts = pts[(pts[:, 1] < 50) | (pts[:, 1] > 53)]
    mask = np.zeros((30, 130), bool)
    mask[7:15, 8:102] = True
    mask[18:28, 110:120] = True
    mask[21:25, 113:117] = False                              # the hole
    assert np.array_equal(_bridged(pts, mask), _bridged(pts))
    assert ndimage.label(closed_map(_bridged(pts), mask.shape), structure=EIGHT)[1] == 1


def test_a_closing_bridge_past_a_third_piece_is_refused(monkeypatch):
    """_clear: a ring in one piece with a gap, and a third piece (one point) inside the
    gap, off the line toward the hole, which the tree joins to the ring. Every bridge
    across the gap has that point in the disc on it as diameter, and the runs to the point
    leave the (narrow) line, so the gap stays open; with _clear patched to pass, the long
    path makes the bridge a loop closer and it is added."""
    pts, _ = circle_ridge(gaps=((80, 90),))
    yy, xx = np.mgrid[0:100, 0:100]
    mask = np.abs(np.hypot(yy - 50, xx - 50) - 40) <= 1
    pts = np.unique(np.concatenate([pts, [(87, 53)]]), axis=0)
    assert not closed(_bridged(pts, mask), mask.shape)
    monkeypatch.setattr(color_lines, "_clear", lambda *args: True)
    assert closed(_bridged(pts, mask), mask.shape)


@pytest.mark.parametrize("radius", [20, 8])
@pytest.mark.parametrize("width_px", [1.5, 2.05])
def test_a_thin_ring_found_and_drawn_stays_closed(radius, width_px):
    """Spec review of the Codex fixes: a 2 px ring (half width 1 px) at width_px 1.5 and
    2.05 (0.41 mm at 0.2 mm/px). Two of its closing runs cut a corner of the line's
    staircase edge by a half pixel; with color.lines.run_tolerance they are taken."""
    n = 80
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    rows = np.full((n, n), BROWN, np.int64)
    rows[np.abs(np.hypot(yy - 40, xx - 40) - radius) < 1.0] = RED
    q = quantized(rows)
    (line,) = run(q, width_px=width_px, limits=dataclasses.replace(LIMITS, min_area_px=8))
    assert closed(line.ridge, (2 * n, 2 * n))
    fine = np.full((n * S, n * S), HOST, np.uint8)
    out = draw_lines(fine, S, [(INK, HOST, line.ridge)], width_px)
    parts = ndimage.label(out != INK, structure=FOUR)[0]
    assert parts[40 * S, 40 * S] != parts[0, 0]


def wavy_grid(n: int, spacing: int = 20) -> np.ndarray:
    """A net of wavy red lines 1.5 to 2.5 px wide, spacing px apart, on brown: one found
    line with many holes (the spec review's timing fixture)."""
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    w = 1.0 + 0.5 * np.cos(xx / 7 + yy / 5)
    on = ((np.abs(((yy + 3 * np.sin(xx / 15)) % spacing) - spacing / 2) < w)
          | (np.abs(((xx + 3 * np.sin(yy / 15)) % spacing) - spacing / 2) < w))
    rows = np.full((n, n), BROWN, np.int64)
    rows[on] = RED
    return rows


def _closing_whole_graph(pts, comp, inside, tree_bridges, reach, closing):
    """_closing written plainly: every candidate's path measured on the whole graph, with
    every bridge found so far, and the same run, disc and topology tests."""
    from scipy.sparse.csgraph import dijkstra

    if not color_lines._has_hole(inside):
        return []
    loose = inside
    for _ in range(closing.run_tolerance):
        loose = ndimage.binary_dilation(loose, structure=EIGHT)
    pairs = cKDTree(pts.astype(float)).query_pairs(reach + 0.5, output_type="ndarray")
    if not len(pairs):
        return []
    i, j = pairs.min(axis=1), pairs.max(axis=1)
    d2 = ((pts[i] - pts[j]) ** 2).sum(axis=1)
    steps = np.abs(pts[i] - pts[j]).max(axis=1)
    keep = (d2 <= reach * reach) & (steps > 1)
    order = np.lexsort((j[keep], i[keep], d2[keep]))
    i, j, steps = i[keep][order], j[keep][order], steps[keep][order]
    kd = cKDTree(pts.astype(float))
    found = []
    graph = color_lines._ridge_graph(pts, list(tree_bridges))
    topology = color_lines._Topology(inside, loose, pts,
                                     [_segment(pts[a], pts[b]) for a, b in tree_bridges])
    for a, b, m in zip(i.tolist(), j.tolist(), steps.tolist()):
        bound = closing.loop_path_factor * m
        if not dijkstra(graph, directed=False, indices=a, limit=bound)[b] > bound:
            continue
        seg = _segment(pts[a], pts[b])
        if (not loose[seg[:, 0], seg[:, 1]].all()
                or not color_lines._clear(pts, comp, a, b, kd) or not topology.try_add(seg)):
            continue
        found.append((a, b))
        graph = color_lines._ridge_graph(pts, list(tree_bridges) + found)
    return found


def _stroke(rows):
    """The view's red candidate of a fixture as find_lines takes it: its half pixels and
    their stroke ridge."""
    halves = np.repeat(np.repeat(rows == RED, 2, 0), 2, 1)
    ry, rx = np.nonzero(stroke_ridge(halves))
    return np.stack([ry, rx], axis=1).astype(np.int64), halves


def _ring_rows(n=80, radius=20.0, half=1.0, amp=0.0):
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    d = np.hypot(yy - n / 2, xx - n / 2) - radius
    rows = np.full((n, n), BROWN, np.int64)
    rows[np.abs(d) < half + amp * np.cos(np.arctan2(yy - n / 2, xx - n / 2) + 0.17)] = RED
    return rows


@pytest.mark.parametrize("fixture", [
    lambda: _stroke(wavy_grid(60)),
    lambda: _stroke(wavy_grid(100)),
    lambda: _stroke(_ring_rows()),
    lambda: _stroke(_ring_rows(radius=8.0)),
    lambda: _stroke(_ring_rows(n=120, radius=25.0, half=1.5, amp=0.5)),
    lambda: circle_ridge(gaps=((80, 90),)),
    lambda: circle_ridge(gaps=((-1, 5), (175, 185))),
    lambda: _stroke(wavy_grid(70, 10)),
], ids=["grid 60", "grid 100", "ring 20", "ring 8", "varying ring", "one gap", "two gaps",
        "dense grid"])
def test_closing_equals_the_whole_graph_form(fixture, monkeypatch):
    """_closing measures a path again only near a bridge found since, on a cropped graph;
    the result (the same bridges, in the same order) is the plain whole-graph form's."""
    pts, mask = fixture()
    fast = _bridged(pts, mask)
    monkeypatch.setattr(color_lines, "_closing", _closing_whole_graph)
    assert np.array_equal(fast, _bridged(pts, mask))


def test_grid_timing():
    """A coarse guard: a 200 x 200 px wavy grid of lines (one found line, many holes) took
    over 6 minutes when every candidate rebuilt the whole graph, and takes about 1 s now
    on the Windows PC (2026-11-19). Wall clock as test_comb_timing: the limit, 10 times
    that, is generous for slower runners and still fails on the old behaviour."""
    import time

    q = quantized(wavy_grid(200))
    t0 = time.perf_counter()
    lines = run(q, width_px=2.05)
    elapsed = time.perf_counter() - t0
    assert len(lines) == 1
    assert elapsed < 10.0


def test_an_open_loop_beside_a_closed_one_stays_open():
    """Codex review of the fixes, 2026-11-19, finding 1: two 1 px red rectangle outlines
    joined along a side, the upper one open (one pixel missing), the lower one closed, in
    one found line (41 mm wide: 0.41 mm/px, drawn at 1 px). The lower one has a hole, so
    loops are closed; the upper one's opening must stay open (its inside is the line's
    exterior), the lower one closed."""
    rows = np.full((100, 100), BROWN, np.int64)
    for r0, r1 in ((15, 45), (65, 85)):
        rows[[r0, r1], 20:61] = RED
        rows[r0:r1 + 1, [20, 60]] = RED
    rows[15, 40] = BROWN                                     # the opening
    rows[45:66, 20] = RED                                    # the join
    (line,) = run(quantized(rows), width_px=1.0,
                  limits=dataclasses.replace(LIMITS, min_area_px=8))
    out = draw_lines(np.full((100 * S, 100 * S), HOST, np.uint8), S,
                     [(INK, HOST, line.ridge)], 1.0)
    parts = ndimage.label(out != INK, structure=FOUR)[0]
    assert parts[30 * S, 40 * S] == parts[0, 0]              # upper: open to the outside
    assert parts[75 * S, 40 * S] != parts[0, 0]              # lower: closed


def _nested_rectangles(inner_open: bool) -> np.ndarray:
    """Codex review of the fixes (round 3), 2026-11-19: 1 px red rectangle outlines, the
    outer rows 10-90 x cols 10-90, the inner rows 30-70 x cols 30-70 (with (30, 50)
    missing when inner_open), joined along row 50, cols 10-30, on brown (45.1 mm wide:
    0.41 mm/px, drawn at 1 px)."""
    rows = np.full((110, 110), BROWN, np.int64)
    for a, b in ((10, 90), (30, 70)):
        rows[[a, b], a:b + 1] = RED
        rows[a:b + 1, [a, b]] = RED
    if inner_open:
        rows[30, 50] = BROWN
    rows[50, 10:31] = RED
    return rows


@pytest.mark.parametrize("inner_open", [True, False], ids=["inner open", "both closed"])
def test_a_bridge_never_splits_a_hole(inner_open):
    """The inner rectangle's opening leads into the outer one's hole: closing it would
    split that hole in two, so it stays open; the outer rectangle stays closed. With both
    closed, both stay closed."""
    (line,) = run(quantized(_nested_rectangles(inner_open)), width_px=1.0,
                  limits=dataclasses.replace(LIMITS, min_area_px=8))
    out = draw_lines(np.full((110 * S, 110 * S), HOST, np.uint8), S,
                     [(INK, HOST, line.ridge)], 1.0)
    parts = ndimage.label(out != INK, structure=FOUR)[0]
    inner, ring, outside = parts[50 * S, 50 * S], parts[20 * S, 50 * S], parts[0, 0]
    assert ring != outside                                   # the outer one is closed
    assert bool(inner == ring) is inner_open                 # the inner one as drawn


@pytest.mark.parametrize("args, match", [
    ((0, 0.5, 8), "loop_path_factor"),
    ((float("nan"), 0.5, 8), "loop_path_factor"),
    ((3, 0.3, 8), "run_tolerance"),
    ((3, -0.5, 8), "run_tolerance"),
    ((3, True, 8), "run_tolerance"),
    ((3, 0.5, 0), "close_reach"),
    ((3, 0.5, 8.25), "close_reach"),
])
def test_closing_params_refuses_bad_values(args, match):
    with pytest.raises(ColorError, match=match):
        closing_params(*args)


def test_closing_params_from_the_rules():
    assert CLOSING == Closing(loop_path_factor=3.0, run_tolerance=1, min_reach=16)
    with pytest.raises(ColorError, match="closing"):
        color_lines.find_lines(quantized(arc_image()), (), LIMITS, 4.0, 0.9, 3.0, None)


def test_a_closing_run_may_cut_a_corner_by_one_half_pixel(monkeypatch):
    """A one half pixel thin diamond loop (8-connected), its ridge the loop less the cells
    at one corner: every straight run across the gap passes inside the corner, one half
    pixel off the line. color.lines.run_tolerance (0.5 px, one half pixel) takes it; with
    0 the loop stays open."""
    n, c0, r = 80, 40, 30
    yy, xx = np.mgrid[0:n, 0:n]
    mask = np.abs(yy - c0) + np.abs(xx - c0) == r
    pts = np.argwhere(mask & (xx - c0 <= r - 2)).astype(np.int64)
    assert ndimage.label(closed_map(pts, mask.shape), structure=EIGHT)[1] == 1
    assert closed(_bridged(pts, mask), mask.shape)
    assert CLOSING.run_tolerance == 1
    strict = dataclasses.replace(CLOSING, run_tolerance=0)
    assert not closed(_bridged(pts, mask, strict), mask.shape)


def test_bridged_adds_no_chord_past_a_piece_between():
    """Three pieces along a bend, inside a mask with a hole (so the closing step runs):
    the bridge from the first to the third is not added: the path along the ridge is no
    longer than color.lines.loop_path_factor times it, and the middle piece lies in the
    disc on it."""
    pts = np.array([(0, 0), (2, 4), (0, 8)])
    want = [_segment(pts[0], pts[1]), _segment(pts[1], pts[2])]
    inside = np.ones((5, 11), bool)
    inside[3, 8] = False                                      # a hole
    assert np.array_equal(_bridged(pts, inside), np.unique(np.concatenate(want), axis=0))


def test_draw_full_ring_is_closed():
    """A full ring's ridge (80 pieces): a spanning tree alone leaves one gap; joined as
    find_lines joins it, the loop's closing bridge is added, so the drawn ring is closed
    (the rest of the map is two pieces, inside and outside), at the drawn width along 360
    normals, and still closed when drawn at 2 px."""
    centre, radius = (50.0, 50.0), 30.0
    ridge = ring_ridge(centre, radius, 0.0, 2 * math.pi, 100, joined=True)
    fine = np.full((100 * S, 100 * S), HOST, np.uint8)
    four = ndimage.generate_binary_structure(2, 1)
    for width in (DRAW_W, 2.0):
        out = draw_lines(fine, S, [(INK, HOST, ridge)], width)
        assert ndimage.label(out != INK, structure=four)[1] == 2, width
    out = draw_lines(fine, S, [(INK, HOST, ridge)], DRAW_W)
    widths = []
    for a in np.radians(np.arange(360) + 0.5):
        u = (math.sin(a), math.cos(a))
        p = (centre[0] + radius * u[0], centre[1] + radius * u[1])
        widths.append(width_along(out, INK, p, u))
    assert np.all(np.abs(np.array(widths) - DRAW_W) <= 0.35), (min(widths), max(widths))


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

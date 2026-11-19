"""tdmg.color_lines.find_lines: thin lines inside one other color
(docs/plans/2026-11-19-widen-lines.md, Task 3). Synthetic images built here."""

import math

import numpy as np
import pytest

from tdmg.color import OUTSIDE, ColorError, Limits, from_labels, printable_limits_px
from tdmg.color_lines import Line, find_lines
from tdmg.profiles import load_printer
from tdmg.rules import load_rules

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
    assert line.length_px == pytest.approx(line.area_px / line.width_px)
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
    """A disc 11 px across: area 95 px (above the 64 px island area), removed whole by the
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
        assert ln.length_px / ln.width_px >= MIN_ELONGATION


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


def test_every_color_in_the_family_finds_nothing():
    q = quantized(arc_image())
    assert find_lines(q, tuple(range(len(q.hex))), LIMITS, 4.0, 0.9, 3.0) == ()

"""tdmg.color_outline: outline detection, drop and keep, and the shade-pair flags
(docs/plans/2026-11-11-color-palette.md, Task 7c)."""

import copy
import math

import numpy as np
import pytest

from tdmg.color import (
    OUTSIDE,
    ColorError,
    from_labels,
    open_mask,
    printable_limits_px,
    srgb_to_lab,
)
from tdmg.color_outline import (
    KEEP_NO_EFFECT_NOTE,
    KEEP_RATIO_RULE,
    KEEP_WIDTH_RULE,
    OUTLINE_METHOD,
    STROKE_WIDTH_PERCENTILE,
    THIN_SHARE_RULE,
    ShadePair,
    detect_outline_family,
    handle_outlines,
    inscribed_width_px,
    keeps_wide_area,
    shade_pairs,
    stroke_band,
    stroke_ridge,
    stroke_specks,
    stroke_width_px,
    wide_core_components,
)
from tdmg.profiles import load_printer
from tdmg.rules import load_rules

RULES = load_rules()
A1 = load_printer("bambu-a1")
# 0.1 mm/px: the opening is 0.4 mm = 4 px (exactly 4.0 in float), the island area
# 0.64 mm2 = 64 px; a kept band of 0.6 mm (passed as width_mm in the band tests below,
# which were written for it) is 5.999... px in float (0.6 / 0.1), so W/2 and W round as for
# 6 px.
LIMITS = printable_limits_px(0.1, RULES, A1)
T = RULES[THIN_SHARE_RULE].default
RATIO = RULES[KEEP_RATIO_RULE].default

RED, WHITE, BLACK, DARKRED = (200, 30, 30), (240, 240, 240), (10, 10, 10), (110, 20, 20)
HEX = {"red": "#c81e1e", "white": "#f0f0f0", "black": "#0a0a0a", "darkred": "#6e1414"}
# The subject: rows 5..94, columns 5..114 (OUTSIDE around it). Red on the left (5..58),
# white on the right (61..114), a 2 px black line between them (59, 60) and a 2 px black
# ring inside the outer edge; a 1 px dark red fringe (column 58) on the red side of the
# middle line; a wide 12 x 12 black "pupil" inside the red.
TOP, BOTTOM, LEFT, RIGHT = 5, 95, 5, 115
PUPIL = (slice(40, 52), slice(25, 37))


def cartoon(fringe: bool = True) -> tuple[np.ndarray, np.ndarray]:
    rgb = np.zeros((100, 120, 3), np.uint8)
    mask = np.zeros((100, 120), bool)
    mask[TOP:BOTTOM, LEFT:RIGHT] = True
    rgb[TOP:BOTTOM, LEFT:59] = RED
    rgb[TOP:BOTTOM, 61:RIGHT] = WHITE
    rgb[TOP:BOTTOM, 59:61] = BLACK
    if fringe:
        rgb[TOP + 2:BOTTOM - 2, 58] = DARKRED
    ring = mask & ~np.pad(np.ones((BOTTOM - TOP - 4, RIGHT - LEFT - 4), bool),
                          ((TOP + 2, 100 - BOTTOM + 2), (LEFT + 2, 120 - RIGHT + 2)))
    rgb[ring] = BLACK
    rgb[PUPIL] = BLACK
    return rgb, mask


def as_quantized(rgb: np.ndarray, mask: np.ndarray):
    """Every distinct masked color is a palette color (from_labels orders them)."""
    colors, inverse = np.unique(rgb[mask], axis=0, return_inverse=True)
    labels = np.full(mask.shape, OUTSIDE, np.int64)
    labels[mask] = inverse.reshape(-1)
    return from_labels(labels, colors.astype(np.uint8), iterations=0, converged=True,
                       n_requested=len(colors), n_distinct_colors=len(colors))


@pytest.fixture
def q():
    return as_quantized(*cartoon())


def idx(q, name):
    return q.hex.index(HEX[name])


def run(q, outline_color="auto", outlines="drop", rules=RULES, limits=LIMITS, width_mm=None):
    return handle_outlines(q, outline_color=outline_color, outlines=outlines, limits=limits,
                           rules=rules, width_mm=width_mm)


# --- detection -----------------------------------------------------------------------------

def test_detection_finds_the_outline_family_by_thinness(q):
    family, thin = detect_outline_family(q, LIMITS, T)
    assert len(thin) == len(q.hex)
    for i in range(len(q.hex)):          # thinness is the share the color's opening removes
        m = q.labels == i
        assert thin[i] == 1.0 - open_mask(m, LIMITS.min_width_px)[m].sum() / m.sum()
    assert family == tuple(sorted((idx(q, "black"), idx(q, "darkred"))))
    assert thin[idx(q, "darkred")] == 1.0
    assert 0.38 < thin[idx(q, "black")] < 1.0           # the pupil is wide
    assert thin[idx(q, "red")] < 0.1 and thin[idx(q, "white")] < 0.1


def test_detection_threshold_is_strict(q):
    _, thin = detect_outline_family(q, LIMITS, T)
    b = idx(q, "black")
    family, _ = detect_outline_family(q, LIMITS, thin[b])        # thin > T, not >=
    assert b not in family
    with pytest.raises(ColorError, match="thin_share must be"):
        detect_outline_family(q, LIMITS, 1.5)


# --- drop ----------------------------------------------------------------------------------

def test_drop_removes_thin_strokes_and_keeps_the_wide_area_in_the_core_color(q):
    out, res = run(q)
    b, d = idx(q, "black"), idx(q, "darkred")
    assert res.family == tuple(sorted((b, d))) and res.core == b
    assert res.found_by == "auto" and res.method == OUTLINE_METHOD == "outline-thin-share/3"
    assert res.thresholds == ((THIN_SHARE_RULE, T), (KEEP_RATIO_RULE, RATIO))
    assert res.specks is None
    assert res.keep_width_mm is None and res.keep_width_px is None and res.band is None
    assert res.remap[d] is None and res.remap[b] is not None       # the core is kept
    assert set(out.hex) == {HEX["red"], HEX["white"], HEX["black"]}
    lab = out.labels
    core = out.hex.index(HEX["black"])
    # The core color is left only in the pupil (whose opening rounds its 4 corners off).
    ys, xs = np.nonzero(lab == core)
    assert ys.min() >= 40 and ys.max() <= 51 and xs.min() >= 25 and xs.max() <= 36
    assert (lab[42:50, 27:35] == core).all()
    assert (lab == core).sum() >= 144 - 4 * 3
    # Thin outline pixels took the nearest non-family color: red left, white right.
    red, white = out.hex.index(HEX["red"]), out.hex.index(HEX["white"])
    assert (lab[TOP:BOTTOM, LEFT:58] != white).all()
    row = lab[70, LEFT:RIGHT]
    assert set(row.tolist()) == {red, white}
    switch = np.flatnonzero(np.diff(row))
    # One switch, at a pixel edge within 1 px of the middle of the family's columns
    # (58..60, pixel edges 58 to 61).
    assert len(switch) == 1 and abs(LEFT + switch[0] + 1 - 59.5) <= 1
    assert (lab == OUTSIDE).sum() == (q.labels == OUTSIDE).sum()


def test_drop_uses_each_members_own_opening_not_the_union():
    # A 3 px black and a 3 px dark red stroke side by side: 6 px together (wider than the
    # 4 px opening), but each is thin on its own, so both are removed.
    rgb = np.zeros((60, 60, 3), np.uint8)
    rgb[:, :27] = RED
    rgb[:, 27:30] = BLACK
    rgb[:, 30:33] = DARKRED
    rgb[:, 33:] = WHITE
    qq = as_quantized(rgb, np.ones((60, 60), bool))
    out, res = run(qq)
    assert res.family == tuple(sorted((idx(qq, "black"), idx(qq, "darkred"))))
    assert set(out.hex) == {HEX["red"], HEX["white"]}
    assert res.remap[idx(qq, "black")] is None


def test_thin_pixels_tie_to_the_lowest_label():
    # A 1 px line between red and white: each line pixel is 1 px from both fills, a tie,
    # which goes to the lower palette index (as in the cleanup's thin step).
    rgb = np.zeros((40, 41, 3), np.uint8)
    rgb[:, :20] = RED
    rgb[:, 20] = BLACK
    rgb[:, 21:] = WHITE
    rgb[0:10, 0:10] = BLACK                    # a wide black area, so black stays
    qq = as_quantized(rgb, np.ones((40, 41), bool))
    out, res = run(qq, outline_color=[idx(qq, "black")])
    low = min(idx(qq, "red"), idx(qq, "white"))
    assert (out.labels[15:, 20] == out.hex.index(qq.hex[low])).all()
    assert res.remap[idx(qq, "black")] is not None


# --- keep: the drawing's own lines, redrawn at width W after the merges ---------------------

def test_keep_returns_the_band_of_the_drawn_lines_and_the_outer_edge(q):
    out, res = run(q, outlines="keep", width_mm=0.6)
    assert res.keep_width_mm == 0.6 and res.keep_width_px == 0.6 / LIMITS.mm_per_px
    # The width is a setting now (outline_width_mm), not a threshold.
    assert res.thresholds == ((THIN_SHARE_RULE, T), (KEEP_RATIO_RULE, RATIO))
    assert res.method == "outline-thin-share/3"
    # The pupil's four rounded-off corners (3 px each) are thin, so they are strokes, and
    # specks: they are not redrawn.
    assert res.specks == (4, 12)
    assert tuple(res.core_rgb) == BLACK and not res.band.flags.writeable
    # The band is returned, not painted: out is the drop's result.
    dropped, _ = run(q)
    assert np.array_equal(out.labels, dropped.labels)
    row = res.band[70]
    # Inside the outer edge: floor(W + 1/2) = 6 px from each side.
    assert row[LEFT:LEFT + 6].all() and not row[LEFT + 6]
    assert row[RIGHT - 6:RIGHT].all() and not row[RIGHT - 7]
    # The drawn line is columns 58 (fringe), 59, 60: its ridge is column 59, so the band is
    # 2 * floor((W - 1) / 2) + 1 = 5 px, columns 57..61, on every row of the straight line.
    for r in range(20, 35):
        assert np.flatnonzero(res.band[r, 20:100]).tolist() == list(range(37, 42))


def strokes_image(widths=(2,), n=40):
    """A vertical stroke of each width, 12 px apart, from column 30, in an n x 2n image."""
    s = np.zeros((n, n * 2), bool)
    x = 30
    starts = []
    for w in widths:
        s[:, x:x + w] = True
        starts.append(x)
        x += w + 12
    return s, starts


@pytest.mark.parametrize("stroke", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("w", [6.0, 5.99, 8.03])
def test_a_straight_drawn_stroke_becomes_a_band_of_about_w_centred_on_it(stroke, w):
    strokes, (x,) = strokes_image((stroke,))
    inside = np.ones(strokes.shape, bool)
    band = stroke_band(strokes, inside, w)
    lo, hi = 2 + int(w), strokes.shape[1] - 2 - int(w)     # away from the outer band
    cols = np.flatnonzero(band[20, lo:hi]) + lo
    assert cols.tolist() == list(range(cols[0], cols[-1] + 1))        # one run
    assert abs(len(cols) - w) <= 1
    # Centred on the drawn stroke (edges x .. x + stroke): within half a pixel.
    assert abs((cols[0] + cols[-1] + 1) / 2 - (x + stroke / 2)) <= 0.5
    assert (band[5:35, cols[0]:cols[-1] + 1]).all()                  # the same on every row


def test_the_ridge_is_the_centre_of_the_stroke():
    strokes, (x,) = strokes_image((3,))
    ridge = stroke_ridge(strokes)
    assert np.flatnonzero(ridge[20]).tolist() == [x + 1]
    strokes, (x,) = strokes_image((2,))
    assert np.flatnonzero(stroke_ridge(strokes)[20]).tolist() == [x, x + 1]
    assert not stroke_ridge(np.zeros((5, 5), bool)).any()


def test_a_t_junction_band_is_at_most_w_plus_2_wide():
    strokes = np.zeros((60, 60), bool)
    strokes[20:22, 5:55] = True               # the bar
    strokes[22:55, 30:32] = True              # the stem, meeting it
    w = 6.0
    band = stroke_band(strokes, np.ones(strokes.shape, bool), w)
    for r in range(24, 50):                   # across the stem, below the bar's band
        assert np.flatnonzero(band[r, 15:45]).size <= w + 2, r
    # At the junction itself: the widest disc inside the band (twice the distance
    # transform) is at most W + 2.
    from scipy import ndimage
    inner = band[8:52, 8:52]
    assert 2 * ndimage.distance_transform_edt(inner).max() <= w + 2


def test_keep_needs_a_band_wider_than_the_opening(q):
    rules = copy.deepcopy(RULES)
    rules[KEEP_WIDTH_RULE] = rules[KEEP_WIDTH_RULE].model_copy(update={"default": 0.4})
    with pytest.raises(ColorError, match="must be wider than"):
        run(q, outlines="keep", rules=rules)


def test_keep_without_a_family_has_no_effect(q):
    out, res = run(q, outline_color="none", outlines="keep")
    assert out is q and res.family == () and res.core is None and res.band is None
    assert res.notes == (KEEP_NO_EFFECT_NOTE,)
    assert res.keep_width_mm is None and res.thresholds == ()


# --- keep through plan_colors: lines kept, color borders and merges left alone -----------

GREEN, BLUE, DARKBLUE = (37, 86, 27), (84, 126, 157), (57, 82, 102)


def drawing():
    """Rows 5..74, columns 5..114. Left (5..54): two green regions, top and bottom, parted
    by a drawn 2 px black line (rows 39, 40), as Oddie's overlapping leaves. Right
    (57..114): blue above row 40 and dark blue (its shading) below, with no drawn line
    between them. Between left and right, a drawn 2 px black line (columns 55, 56)."""
    rgb = np.zeros((80, 120, 3), np.uint8)
    mask = np.zeros((80, 120), bool)
    mask[5:75, 5:115] = True
    rgb[5:75, 5:55] = GREEN
    rgb[39:41, 5:55] = BLACK
    rgb[5:75, 55:57] = BLACK
    rgb[5:40, 57:115] = BLUE
    rgb[40:75, 57:115] = DARKBLUE
    return rgb, mask


def draw_plan(**settings):
    from tdmg.color_plan import plan_colors
    s = {"colors": 4, "extract": 4, "edges": "exact", "base": "auto", "outlines": "keep",
         "outline_color": "auto", "merge": (), "outline_width_mm": 0.6, **settings}
    return plan_colors(*drawing(), s, LIMITS, RULES)


def test_keep_redraws_a_line_between_two_regions_of_one_color():
    p = draw_plan()
    black = p.extracted.hex.index("#0a0a0a")
    assert p.outline.family == (black,) and p.fate[black] == "final"
    core = p.cleaned.hex.index("#0a0a0a")
    lab = p.cleaned.labels
    # The leaf line (rows 39, 40; ridge both rows) is a band of 6 rows, 37..42, in black.
    for c in range(20, 40):
        assert np.flatnonzero(lab[20:60, c] == core).tolist() == list(range(17, 23)), c
    # Under drop the two greens fuse: no black is left there.
    d = draw_plan(outlines="drop")
    assert HEX["black"] not in d.cleaned.hex


def test_keep_draws_no_band_on_a_color_border_with_no_drawn_line():
    p = draw_plan()
    core = p.cleaned.hex.index("#0a0a0a")
    lab = p.cleaned.labels
    # Columns 70..100 (away from the drawn line and the outer band): no black across the
    # blue / dark blue border at row 40.
    assert not (lab[15:65, 70:100] == core).any()


def test_keep_after_a_merge_leaves_no_band_inside_the_merged_color():
    p0 = draw_plan()
    b, d = p0.extracted.hex.index("#547e9d"), p0.extracted.hex.index("#395266")
    p = draw_plan(merge=((d, b),))
    core = p.cleaned.hex.index("#0a0a0a")
    blue = p.cleaned.hex.index("#547e9d")
    lab = p.cleaned.labels
    # Inside the outer band and the line's band; cleanup may fill an inner corner pixel of
    # the band (rows 11 and 68, column 108), so the corners are left out.
    right = lab[12:68, 62:108]
    assert (right == blue).all()
    assert (lab[5:75, 55:57] == core).all()   # the drawn line is kept


def test_the_kept_band_survives_cleanup():
    p = draw_plan()
    core_b = p.banded.hex.index("#0a0a0a")
    core_c = p.cleaned.hex.index("#0a0a0a")
    before, after = p.banded.labels == core_b, p.cleaned.labels == core_c
    assert not (before & ~after).any()        # no band pixel is removed
    assert (after & ~before).sum() <= 20      # cleanup only fills a few inner corners


# --- explicit list and none ---------------------------------------------------------------

def test_an_explicit_list_is_the_family(q):
    d = idx(q, "darkred")
    out, res = run(q, outline_color=[d])
    assert res.family == (d,) and res.core == d and res.found_by == "config"
    assert res.thresholds == ((KEEP_RATIO_RULE, RATIO),)
    assert HEX["darkred"] not in out.hex and HEX["black"] in out.hex
    assert out.counts[out.hex.index(HEX["black"])] == (q.labels == idx(q, "black")).sum()


def test_none_changes_nothing(q):
    out, res = run(q, outline_color="none")
    assert out is q and res.family == () and res.found_by == "none"
    assert res.remap == tuple(range(len(q.hex))) and res.notes == ()
    assert len(res.thinness) == len(q.hex)        # still reported


@pytest.mark.parametrize("bad, message", [
    ([9], "outline_color 9 is not an index"), ([True], "outline_color"),
    ([1, 1], "more than once"), ([], "outline_color"), ("dark", "outline_color"),
])
def test_bad_outline_color_is_refused(q, bad, message):
    with pytest.raises(ColorError, match=message):
        run(q, outline_color=bad)


def test_every_color_in_the_family_is_refused(q):
    with pytest.raises(ColorError, match="every extracted color is in the outline family"):
        run(q, outline_color=list(range(len(q.hex))))


def test_a_bad_outlines_value_is_refused(q):
    with pytest.raises(ColorError, match="outlines must be drop or keep"):
        run(q, outline_color="none", outlines="hide")


# --- shade pairs -------------------------------------------------------------------------

def lab_of(*rgbs):
    return srgb_to_lab(np.array(rgbs, np.uint8)).tolist()


def test_two_tones_of_one_hue_are_flagged():
    lab = lab_of((72, 168, 53), (37, 86, 27), (240, 240, 240))        # light, dark green
    pairs = shade_pairs(lab, ["#48a835", "#25561b", "#f0f0f0"], [0, 1, 2], 5.5, 8.5)
    assert len(pairs) == 1
    p = pairs[0]
    assert isinstance(p, ShadePair) and (p.i, p.j) == (0, 1)
    assert (p.hex_i, p.hex_j) == ("#48a835", "#25561b")
    hue = [math.degrees(math.atan2(b, a)) % 360 for _, a, b in lab]
    assert p.dh_deg == pytest.approx(abs(hue[0] - hue[1])) and p.dh_deg < 5.5
    assert p.chroma_i == math.hypot(lab[0][1], lab[0][2])
    assert p.dl == lab[1][0] - lab[0][0]
    assert p.merge == (1, 0)                       # the later (smaller) one into the earlier


def test_low_chroma_and_far_hue_pairs_are_not_flagged():
    grey = lab_of((120, 120, 120), (200, 200, 200))                     # C* ~ 0
    assert shade_pairs(grey, ["#787878", "#c8c8c8"], [0, 1], 5.5, 8.5) == ()
    reds = lab_of((238, 96, 91), (161, 8, 4))                          # dh ~ 9.5
    assert shade_pairs(reds, ["#ee605b", "#a10804"], [0, 1], 5.5, 8.5) == ()


def test_shade_pairs_use_only_the_candidates_and_the_shortest_hue_way():
    lab = [[50.0, 20.0, -0.5], [40.0, 20.0, 0.5], [50.0, 20.0, -0.4]]   # hues 358.6, 1.4
    pairs = shade_pairs(lab, ["#a", "#b", "#c"], [0, 1], 5.5, 8.5)
    assert [(p.i, p.j) for p in pairs] == [(0, 1)]
    assert pairs[0].dh_deg == pytest.approx(2.86, abs=0.01)
    assert shade_pairs(lab, ["#a", "#b", "#c"], [1], 5.5, 8.5) == ()


# --- Task 7e-b: what survives drop, stroke specks under keep --------------------------------

def pupil_and_tip(fringe_block: bool = False):
    """100 x 120, all subject. Red left (0..57), a 4 px black line (58..61), white right
    (62..119). A 14 x 14 black pupil inside the red (rows 30..43, columns 15..28), and a
    6 x 6 black widening of the line on its red side (rows 70..75, columns 52..57), like a
    line's dark tip: with the line it is 6 x 10 px, wide for the 4 px opening. With
    fringe_block, a 1 px dark red fringe on the white side of the line (column 62) and an
    8 x 8 dark red block inside the white (rows 10..17, columns 90..97): a shading tone
    with a wide area."""
    rgb = np.zeros((100, 120, 3), np.uint8)
    rgb[:, :58] = RED
    rgb[:, 58:62] = BLACK
    rgb[:, 62:] = WHITE
    rgb[30:44, 15:29] = BLACK
    rgb[70:76, 52:58] = BLACK
    if fringe_block:
        rgb[:, 62] = DARKRED
        rgb[10:18, 90:98] = DARKRED
    return rgb, np.ones((100, 120), bool)


def test_stroke_width_is_the_p90_of_twice_the_ridge_distance():
    strokes, _ = strokes_image((4,))
    # A straight 4 px stroke: its two middle pixels are 2 px from the nearest non-stroke
    # centre, so it reads 4.
    assert stroke_width_px(strokes) == 4.0
    assert STROKE_WIDTH_PERCENTILE == 90
    assert stroke_width_px(np.zeros((5, 5), bool)) is None
    # A 1 px line of 9 px (ridge: all 9, each 2) and a 5 x 5 blob (ridge: its centre, 3 px
    # from outside, so 6): numpy's linear p90 of nine 2s and one 6 is 2 + 0.1 x 4 = 2.4.
    s = np.zeros((20, 40), bool)
    s[2, 2:11] = True
    s[10:15, 20:25] = True
    ridge = stroke_ridge(s)
    assert ridge[12, 22] and ridge[2].sum() == 9 and ridge.sum() == 10
    assert stroke_width_px(s) == pytest.approx(2.4)


def test_inscribed_width_counts_the_frame_and_reads_about_one_px_over():
    comp = np.zeros((30, 30), bool)
    comp[5:19, 5:19] = True                # 14 x 14: the middle pixels are 7 px from outside
    assert inscribed_width_px(comp) == 14.0
    comp = np.zeros((30, 30), bool)
    comp[0:5, 0:5] = True                  # at the image corner: the frame is outside
    assert inscribed_width_px(comp) == 6.0
    one = np.zeros((5, 5), bool)
    one[2, 2] = True
    assert inscribed_width_px(one) == 2.0


@pytest.mark.parametrize("ins, sw, ratio, kept", [
    (14.0, 4.0, 3.5, True),                # exactly ratio x stroke: kept (>=)
    (14.0, 4.0, 3.5000001, False),
    (8.0, 4.0, 2.0, True), (7.9, 4.0, 2.0, False),
    (1.0, 4.0, 0.0, True),                 # ratio 0 keeps every wide area
    (99.0, None, 2.0, False),              # no family stroke: nothing is kept
])
def test_the_ratio_rule_edges(ins, sw, ratio, kept):
    assert keeps_wide_area(ins, sw, ratio) is kept


def test_drop_keeps_the_pupil_but_not_a_lines_wide_tip():
    q = as_quantized(*pupil_and_tip())
    out, res = run(q)
    b = idx(q, "black")
    assert res.family == (b,) and res.core == b
    assert res.stroke_width_px == 4.0
    assert res.thresholds[-1] == (KEEP_RATIO_RULE, RATIO) and RATIO == 2.0
    pupil, tip = res.wide_components                      # largest first
    assert pupil.area_px > tip.area_px
    assert pupil.inscribed_px == 14.0 and pupil.kept
    assert abs(pupil.centroid[0] - 36.5) < 1 and abs(pupil.centroid[1] - 21.5) < 1
    assert tip.inscribed_px == 6.0 and not tip.kept      # 6 < 2 x 4
    core = out.hex.index(HEX["black"])
    red, white = out.hex.index(HEX["red"]), out.hex.index(HEX["white"])
    lab = out.labels
    assert (lab[32:42, 17:27] == core).all()             # the pupil stays
    assert (lab == core).sum() == pupil.area_px
    # The tip took the nearest non-family color: red, on its red side.
    assert (lab[70:76, 52:58] == red).all()
    assert set(np.unique(lab[60:90, 58:62]).tolist()) <= {red, white}


def test_drop_sends_a_shading_tones_wide_area_to_the_nearest_color_not_the_core():
    q = as_quantized(*pupil_and_tip(fringe_block=True))
    out, res = run(q)
    b, d = idx(q, "black"), idx(q, "darkred")
    assert res.family == tuple(sorted((b, d))) and res.core == b
    assert HEX["darkred"] not in out.hex
    white = out.hex.index(HEX["white"])
    assert (out.labels[10:18, 90:98] == white).all()     # not the core
    # The fringe widens the drawn line to 5 px (S reads 6), so the threshold is 12: the
    # pupil (14) is still kept, the tip (6) not; the core's components only.
    assert res.stroke_width_px == 6.0
    assert [(c.inscribed_px, c.kept) for c in res.wide_components] == [(14.0, True),
                                                                       (6.0, False)]


def test_with_no_family_stroke_no_wide_area_is_kept():
    # At 0.6 mm/px the opening is 0.67 px, so a 20 x 20 square has no thin pixel at all.
    limits = printable_limits_px(0.6, RULES, A1)
    rgb = np.zeros((60, 60, 3), np.uint8)
    rgb[:] = RED
    rgb[20:40, 20:40] = BLACK
    q = as_quantized(rgb, np.ones((60, 60), bool))
    out, res = run(q, outline_color=[idx(q, "black")], limits=limits)
    assert res.stroke_width_px is None
    assert [(c.area_px, c.kept) for c in res.wide_components] == [(400, False)]
    assert out.hex == (HEX["red"],) and res.remap[idx(q, "black")] is None


def test_wide_core_components_are_four_connected_and_ordered_by_size():
    m = np.zeros((20, 20), bool)
    m[2:6, 2:6] = True                           # 16 px, inscribed 4
    m[6:9, 6:9] = True                           # 9 px, inscribed 4; diagonal contact only
    m[12:18, 12:18] = True                       # 36 px, inscribed 6
    comps, keep = wide_core_components(m, 2.5, 2.0)            # threshold 5
    assert [(c.area_px, c.inscribed_px, c.kept) for c in comps] == [
        (36, 6.0, True), (16, 4.0, False), (9, 4.0, False)]
    assert keep.sum() == 36 and keep[12:18, 12:18].all()
    assert wide_core_components(np.zeros((4, 4), bool), 2.0, 2.0)[0] == ()


def test_wide_core_components_measure_each_on_its_own_box_with_the_frame_outside():
    # A component at the image corner: the frame beyond the image counts as outside, so a
    # 5 x 5 block there reads 6 (centre 3 px from outside), as it would in the open.
    m = np.zeros((30, 30), bool)
    m[0:5, 0:5] = True
    m[20:25, 20:25] = True
    comps, _ = wide_core_components(m, 1.0, 1.0)
    assert [(c.area_px, c.inscribed_px) for c in comps] == [(25, 6.0), (25, 6.0)]
    assert [c.centroid for c in comps] == [(2.0, 2.0), (22.0, 22.0)]


def test_stroke_specks_are_small_eight_connected_components():
    s = np.zeros((40, 40), bool)
    s[5, 5] = True
    s[6, 6] = True                               # diagonal: one speck of 2 px
    s[20, 0:39] = True                           # a 39 px line
    specks, n = stroke_specks(s, 39)
    assert specks[5, 5] and specks[6, 6] and not specks[20].any() and n == 1
    specks, n = stroke_specks(s, 40)                # strict: 39 < 40
    assert specks[20, 0:39].all() and n == 2
    specks, n = stroke_specks(np.zeros((4, 4), bool), 10)
    assert not specks.any() and n == 0


def test_keep_does_not_draw_stroke_specks():
    # The cartoon plus an isolated 2 x 2 black speck in the white, far from every line and
    # from the outer edge: below the island area (64 px at 0.1 mm/px), so it is not redrawn.
    rgb, mask = cartoon()
    rgb[70:72, 90:92] = BLACK
    q = as_quantized(rgb, mask)
    out, res = run(q, outlines="keep", width_mm=0.6)
    assert res.specks == (5, 16)                 # the speck and the pupil's four corners
    assert not res.band[66:76, 86:96].any()
    white = out.hex.index(HEX["white"])
    assert (out.labels[70:72, 90:92] == white).all()     # dropped like any thin pixel
    assert res.band[70, 59]                      # the drawn line is still redrawn
    assert "5 stroke speck(s)" in res.notes[-1]


def test_keep_takes_its_width_from_the_setting_and_refuses_one_at_the_opening(q):
    _, res = run(q, outlines="keep", width_mm=0.8)
    assert (res.keep_width_mm, res.keep_width_px) == (0.8, 0.8 / LIMITS.mm_per_px)
    _, res = run(q, outlines="keep")
    assert res.keep_width_mm == RULES[KEEP_WIDTH_RULE].default == 0.5
    for bad in (0.4, 0.3):
        with pytest.raises(ColorError, match="must be wider than flat.sliver.opening_width"):
            run(q, outlines="keep", width_mm=bad)
    for bad in (math.nan, math.inf, True, "0.5"):
        with pytest.raises(ColorError, match="outline_width_mm must be a finite number"):
            run(q, outlines="keep", width_mm=bad)
    _, res = run(q, width_mm=0.3)                # under drop the width is not used
    assert res.keep_width_mm is None and res.band is None


def test_a_negative_ratio_rule_is_refused(q):
    rules = copy.deepcopy(RULES)
    rules[KEEP_RATIO_RULE] = rules[KEEP_RATIO_RULE].model_copy(update={"default": -1.0})
    with pytest.raises(ColorError, match="must be 0 or more"):
        run(q, rules=rules)

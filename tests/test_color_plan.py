"""tdmg.color_plan.plan_colors: the pure color pipeline of tdmg colors
(docs/plans/2026-11-11-color-palette.md, Task 7b)."""

import numpy as np
import pytest

from tdmg.color import OUTSIDE, ColorError, Quantized, printable_limits_px
from tdmg.color_config import ColorConfigError
from tdmg.color_plan import FATES, ColorPlan, plan_colors
from tdmg.profiles import load_printer
from tdmg.rules import load_rules

RULES = load_rules()
A1 = load_printer("bambu-a1")
# 0.6 mm/px: opening 0.67 px, island 1.8 px^2, so the stripes survive cleanup.
LIMITS = printable_limits_px(0.6, RULES, A1)
SETTINGS = {"colors": 4, "extract": 5, "edges": "exact", "base": "auto", "outlines": "drop",
            "outline_color": "auto", "merge": ()}
STRIPES = [((200, 30, 30), 30), ((30, 30, 200), 25), ((30, 200, 30), 20),
           ((240, 240, 240), 15), ((20, 20, 20), 10)]


def stripes(speck: bool = False):
    rgb = np.zeros((60, 100, 3), np.uint8)
    x = 0
    for color, width in STRIPES:
        rgb[:, x:x + width] = color
        x += width
    mask = np.ones((60, 100), bool)
    if speck:                             # a one-pixel color that cleanup merges away
        rgb[30, 15] = (250, 140, 0)
    return rgb, mask


def plan(speck=False, **settings):
    return plan_colors(*stripes(speck), {**SETTINGS, **settings}, LIMITS, RULES)


def test_plain_plan_keeps_every_color_as_final():
    p = plan()
    assert isinstance(p, ColorPlan)
    assert isinstance(p.extracted, Quantized) and len(p.extracted.hex) == 5
    assert p.fate == ("final",) * 5
    assert p.final_index == (0, 1, 2, 3, 4)
    assert p.cleaned.hex == p.extracted.hex
    assert p.outline.family == () and p.merges == ()


def test_merges_compose_through_explicit_index_arrays():
    p = plan(merge=((4, 3), (0, 2)))
    # Extracted 0 (30 cols) goes into 2 (20 cols): 2 becomes the largest; 3 takes 4.
    assert p.fate == ("merged", "final", "final", "final", "merged")
    assert p.final_index == (None, 1, 0, 2, None)
    assert p.merges == ((4, 3), (0, 2))
    for i, f in enumerate(p.final_index):
        if f is not None:
            assert p.cleaned.hex[f] == p.extracted.hex[i]
    assert p.cleaned.counts == (50 * 60, 25 * 60, 25 * 60)


def test_a_color_cleanup_removes_has_fate_cleanup():
    p = plan(speck=True, extract=6)
    i = p.extracted.hex.index("#fa8c00")
    assert p.fate[i] == "cleanup" and p.final_index[i] is None
    assert "#fa8c00" in p.log.dropped_hex
    assert sorted(f for f in p.final_index if f is not None) == list(range(len(p.cleaned.hex)))


def test_every_fate_is_known():
    assert set(FATES) == {"final", "merged", "outline", "cleanup"}
    assert set(plan(merge=((4, 3),)).fate) <= set(FATES)


def test_explicit_outline_indices_are_checked_against_the_real_extraction_first():
    # The image has 5 colors although extract is 8: index 6 is refused as an index, before
    # the outline step (which would refuse a list as not implemented yet).
    with pytest.raises(ColorConfigError, match="outline_color 6 is not an extraction index: "
                                               "the extraction has 5 colors"):
        plan(extract=8, outline_color=(6,))
    with pytest.raises(ColorError, match="not implemented yet"):
        plan(extract=8, outline_color=(4,))


def test_merge_beyond_the_real_extraction_is_refused():
    with pytest.raises(ColorConfigError, match=r"merge \[6, 0\]: 6 is not an extraction"):
        plan(extract=8, merge=((6, 0),))


def test_plan_colors_is_pure_and_repeatable():
    rgb, mask = stripes()
    before = rgb.copy()
    a = plan_colors(rgb, mask, SETTINGS, LIMITS, RULES)
    b = plan_colors(rgb, mask, SETTINGS, LIMITS, RULES)
    assert (rgb == before).all()
    assert np.array_equal(a.cleaned.labels, b.cleaned.labels) and a.fate == b.fate
    assert (a.cleaned.labels != OUTSIDE).all()

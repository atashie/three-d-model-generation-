"""tdmg.color_plan.plan_colors: the pure color pipeline of tdmg colors
(docs/plans/2026-11-11-color-palette.md, Tasks 7b and 7c)."""

import numpy as np
import pytest

import tdmg.color_plan
from tdmg.color import (
    OUTLINE_METHOD,
    OUTSIDE,
    ColorError,
    OutlineResult,
    Quantized,
    from_labels,
    printable_limits_px,
)
from tdmg.color_config import ColorConfigError
from tdmg.color_plan import FATES, ColorPlan, _translate, plan_colors, shade_candidates
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
    # the outline step reads it.
    with pytest.raises(ColorConfigError, match="outline_color 6 is not an extraction index: "
                                               "the extraction has 5 colors"):
        plan(extract=8, outline_color=(6,))
    p = plan(extract=8, outline_color=(4,))       # the black stripe, named by the owner
    assert p.outline.family == (4,) and p.outline.found_by == "config"
    assert p.outline.core == 4 and p.fate[4] == "final"      # a wide stripe: kept as core


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


# --- Task 7c: fates through the outline step, merges into the core, shade pairs ----------

def _fake_outline(family, core, removed, recolor=None):
    """A handle_outlines that removes the extraction indices `removed` (their pixels go to
    color 0) and reports the given family and core; recolor: {index: rgb} changes palette
    colors, to break the hex cross-check."""
    def fake(q, **_):
        labels = np.array(q.labels, np.int64)
        for i in removed:
            labels[q.labels == i] = 0
        rgb = np.array(q.rgb)
        for i, c in (recolor or {}).items():
            rgb[i] = c
        out = from_labels(labels, rgb, iterations=q.iterations, converged=q.converged,
                          n_requested=q.n_requested, n_distinct_colors=q.n_distinct_colors)
        return out, OutlineResult(family=family, core=core, thinness=(0.0,) * len(q.hex),
                                  found_by="auto", method=OUTLINE_METHOD, remap=out.remap,
                                  thresholds=(), keep_width_mm=None, keep_width_px=None,
                                  notes=())
    return fake


def test_fates_follow_the_composed_remap_for_a_kept_core(monkeypatch):
    monkeypatch.setattr(tdmg.color_plan, "handle_outlines", _fake_outline((3, 4), 3, (4,)))
    p = plan()
    assert p.fate == ("final", "final", "final", "final", "outline")
    assert p.final_index[3] is not None
    assert p.cleaned.hex[p.final_index[3]] == p.extracted.hex[3]
    assert p.final_index[4] is None


def test_a_removed_color_outside_the_family_is_a_bug(monkeypatch):
    monkeypatch.setattr(tdmg.color_plan, "handle_outlines", _fake_outline((3,), 3, (2,)))
    with pytest.raises(ColorError, match="extracted color 2 was removed by the outline "
                                         "handling but is not in the outline family"):
        plan()


def test_a_final_color_with_no_extracted_source_is_a_bug(monkeypatch):
    monkeypatch.setattr(tdmg.color_plan, "handle_outlines",
                        _fake_outline((), None, (), recolor={1: (1, 2, 3)}))
    with pytest.raises(ColorError, match=r"final color \d \(#010203\) is not the final index "
                                         "of an extracted color"):
        plan()


def test_translate_refuses_a_merge_the_outline_step_removed():
    with pytest.raises(ColorError, match=r"merge \[0, 3\]: the outline handling removed "
                                         "color 3"):
        _translate([(0, 3)], (0, 1, 2, None))
    assert _translate([(2, 0)], (1, 0, 2, None)) == [(2, 1)]


# 0.1 mm/px, as in tests/test_color_outline.py's cartoon (opening 4 px, kept band 6 px).
LIMITS_01 = printable_limits_px(0.1, RULES, A1)


def cartoon_plan(rgb_mask=None, **settings):
    from test_color_outline import cartoon
    return plan_colors(*(rgb_mask or cartoon()), {**SETTINGS, "extract": 4, **settings},
                       LIMITS_01, RULES)


def _ix(p, name):
    from test_color_outline import HEX
    return p.extracted.hex.index(HEX[name])


def test_cartoon_plan_drops_the_outline_family_and_keeps_the_core():
    p = cartoon_plan()
    b, d = _ix(p, "black"), _ix(p, "darkred")
    assert p.outline.family == tuple(sorted((b, d))) and p.outline.core == b
    assert p.fate[d] == "outline" and p.fate[b] == "final"
    assert len(p.cleaned.hex) == 3


def test_a_merge_into_the_core_is_allowed_and_from_a_member_refused():
    p0 = cartoon_plan()
    b, d, w, r = (_ix(p0, n) for n in ("black", "darkred", "white", "red"))
    p = cartoon_plan(merge=((w, b),))
    assert p.fate[w] == "merged" and p.fate[b] == "final"
    assert len(p.cleaned.hex) == 2
    with pytest.raises(ColorConfigError, match=f"color {b} is in the outline family, which"):
        cartoon_plan(merge=((b, r),))
    with pytest.raises(ColorConfigError, match=f"color {d} is in the outline family but is "
                                               "not its core"):
        cartoon_plan(merge=((r, d),))


def test_a_merge_into_a_core_left_with_no_pixel_is_refused():
    # Without the pupil, the core keeps no wide area and is removed.
    from test_color_outline import PUPIL, RED, cartoon
    rgb, mask = cartoon()
    rgb[PUPIL] = RED
    p = cartoon_plan((rgb, mask))
    b, w = _ix(p, "black"), _ix(p, "white")
    assert p.outline.core == b and p.fate[b] == "outline"
    with pytest.raises(ColorConfigError, match=rf"merge \[{w}, {b}\]: color {b}, the outline "
                                               "core, has no pixel left"):
        cartoon_plan((rgb, mask), merge=((w, b),))


def test_shade_pairs_are_flagged_never_applied():
    rgb = np.zeros((60, 100, 3), np.uint8)
    rgb[:, :40] = (37, 86, 27)          # dark green
    rgb[:, 40:70] = (72, 168, 53)       # light green: the same hue
    rgb[:, 70:] = (240, 240, 240)
    mask = np.ones((60, 100), bool)
    p = plan_colors(rgb, mask, {**SETTINGS, "extract": 3}, LIMITS, RULES)
    assert [(s.i, s.j) for s in p.shade_pairs] == [(0, 1)]
    assert p.shade_pairs[0].merge == (1, 0)
    assert len(p.cleaned.hex) == 3                         # flagged only
    assert p.shade_rules == (("color.shade.max_hue_diff_deg", 5.5),
                             ("color.shade.min_chroma", 8.5))
    # Once the owner merges them, the pair is no longer flagged.
    p = plan_colors(rgb, mask, {**SETTINGS, "extract": 3, "merge": ((1, 0),)}, LIMITS, RULES)
    assert p.shade_pairs == () and len(p.cleaned.hex) == 2


def test_shade_candidates_leave_out_removed_merged_and_core_colors():
    assert shade_candidates(5, (0, None, 1, 2, 3), 3, ((4, 0),)) == [0, 2]

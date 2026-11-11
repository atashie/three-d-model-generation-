"""tdmg.color: the owner's merges, index tracking (Quantized.remap) and the outline step
(docs/plans/2026-11-11-color-palette.md, Task 7b)."""

import numpy as np
import pytest

from tdmg.color import (
    OUTSIDE,
    ColorError,
    apply_merges,
    clean_regions,
    from_labels,
    merge_problem,
    quantize,
)
from tdmg.color_outline import (
    KEEP_NO_EFFECT_NOTE,
    OUTLINE_METHOD,
    OutlineResult,
    handle_outlines,
)

# Five flat colors with distinct areas, so the extraction order is known: 0 is the largest.
COLORS = [(200, 30, 30), (30, 30, 200), (30, 200, 30), (240, 240, 240), (20, 20, 20)]
AREAS = [500, 400, 300, 200, 100]


def five_colors() -> tuple[np.ndarray, np.ndarray]:
    flat = np.concatenate([np.full((n, 3), c, np.uint8) for c, n in zip(COLORS, AREAS)])
    rgb = np.zeros((1, 1600, 3), np.uint8)
    rgb[0, :1500] = flat
    mask = np.zeros((1, 1600), bool)
    mask[0, :1500] = True
    return rgb, mask


@pytest.fixture
def q5():
    q = quantize(*five_colors(), 5)
    assert q.counts == tuple(AREAS)               # order: largest first
    return q


def test_apply_merges_moves_pixels_and_shrinks_the_palette(q5):
    m = apply_merges(q5, [(4, 0), (3, 2)])
    assert len(m.hex) == 3
    # 0 gets 4's pixels (500 + 100), 2 gets 3's (300 + 200); 1 keeps 400. Re-sorted.
    assert m.hex == (q5.hex[0], q5.hex[2], q5.hex[1])
    assert m.counts == (600, 500, 400) and sum(m.shares) == pytest.approx(1.0)
    assert m.remap == (0, 2, 1, None, None)
    # Every pixel of a merged color now has its into color; the others are unchanged.
    for a, b in ((4, 0), (3, 2)):
        assert (m.labels[q5.labels == a] == m.remap[b]).all()
    for i in (0, 1, 2):
        assert (m.labels[q5.labels == i] == m.remap[i]).all()
    assert (m.labels == OUTSIDE).sum() == (q5.labels == OUTSIDE).sum() == 100
    assert m.dropped == q5.dropped + 2            # merged-away colors count as dropped
    assert (m.iterations, m.converged, m.n_requested, m.n_distinct_colors) == (
        q5.iterations, q5.converged, q5.n_requested, q5.n_distinct_colors)
    assert not m.labels.flags.writeable


def test_apply_merges_resorts_by_the_new_areas(q5):
    # 2 (300 px) takes 0's 500: it becomes the largest color, index 0.
    m = apply_merges(q5, [(0, 2)])
    assert m.hex[0] == q5.hex[2] and m.counts[0] == 800
    assert m.remap == (None, 1, 0, 2, 3)


def test_apply_merges_keeps_the_into_color_unchanged(q5):
    m = apply_merges(q5, [(1, 0)])
    i = m.remap[0]
    assert m.hex[i] == q5.hex[0] and (m.rgb[i] == q5.rgb[0]).all()
    assert (m.lab[i] == q5.lab[0]).all()


def test_apply_merges_does_not_depend_on_pair_order(q5):
    a = apply_merges(q5, [(4, 0), (3, 1), (2, 0)])
    b = apply_merges(q5, [(2, 0), (3, 1), (4, 0)])
    assert a.hex == b.hex and np.array_equal(a.labels, b.labels)


def test_two_colors_into_one(q5):
    m = apply_merges(q5, [(3, 2), (4, 2)])
    assert m.counts == (600, 500, 400)
    assert m.remap == (1, 2, 0, None, None)


def test_no_merges_leaves_the_labels(q5):
    m = apply_merges(q5, [])
    assert m is not q5
    assert m.hex == q5.hex and np.array_equal(m.labels, q5.labels) and m.dropped == q5.dropped


@pytest.mark.parametrize("merges, message", [
    ([(1, 1)], "merges a color into itself"),
    ([(3, 1), (3, 2)], "merged more than once"),
    ([(3, 1), (1, 0)], "no chains"),
    ([(5, 0)], "indices must be 0 to 4"),
    ([(0, -1)], "indices must be 0 to 4"),
    ([(True, 0)], "pair of color indices"),
    ([(1.0, 0)], "pair of color indices"),
    ([(1, 0, 2)], "pair of color indices"),
    ([3], "pair of color indices"),
])
def test_bad_merges_are_refused(q5, merges, message):
    with pytest.raises(ColorError, match=message):
        apply_merges(q5, merges)


def test_apply_merges_refuses_a_non_quantized():
    with pytest.raises(ColorError, match="Quantized"):
        apply_merges(np.zeros((2, 2)), [])


def test_merge_problem():
    assert merge_problem([]) is None
    assert merge_problem([(3, 0), (4, 0)]) is None
    assert "itself" in merge_problem([(0, 0)])
    assert "more than once" in merge_problem([(1, 0), (1, 2)])
    assert "no chains" in merge_problem([(2, 1), (1, 0)])


def test_from_labels_records_the_old_to_new_index_array():
    labels = np.array([[2, 2, 2, 0, OUTSIDE, 1, 1]])
    rgb = np.array([[10, 10, 10], [200, 0, 0], [0, 0, 200], [5, 5, 5]], np.uint8)
    q = from_labels(labels, rgb, iterations=0, converged=True, n_requested=4,
                    n_distinct_colors=4)
    # Ordered by count: old 2 (3 px) -> 0, old 1 (2 px) -> 1, old 0 (1 px) -> 2; 3 unused.
    assert q.remap == (2, 1, 0, None)
    assert q.hex == ("#0000c8", "#c80000", "#0a0a0a") and q.dropped == 1


def test_remap_is_by_index_not_by_color():
    # Two palette entries with the same color are still told apart by index.
    labels = np.array([[0, 1, 1]])
    rgb = np.array([[1, 2, 3], [1, 2, 3]], np.uint8)
    q = from_labels(labels, rgb, iterations=0, converged=True, n_requested=2,
                    n_distinct_colors=1)
    assert q.remap == (1, 0)


def test_quantize_remap_has_one_entry_per_rounded_centroid(q5):
    assert sorted(i for i in q5.remap if i is not None) == list(range(5))


def test_clean_regions_remap_follows_its_palette(q5):
    from tdmg.color import Limits
    limits = Limits(min_width_px=0.5, min_area_px=150.0, mm_per_px=0.1, opening_width_mm=0.05,
                    island_area_mm2=1.5, nozzle_diameter_mm=0.4,
                    opening_rule="flat.sliver.opening_width",
                    island_rule="flat.island.min_square_side")
    cleaned, log = clean_regions(q5, limits)
    for i, j in enumerate(cleaned.remap):
        if j is None:
            assert q5.hex[i] in log.dropped_hex
        else:
            assert cleaned.hex[j] == q5.hex[i]


# --- the outline step on five 1-pixel-tall stripes (tests/test_color_outline.py has the
# --- detection, drop and keep cases) --------------------------------------------------

def _limits():
    from tdmg.color import printable_limits_px
    from tdmg.profiles import load_printer
    from tdmg.rules import load_rules
    return printable_limits_px(0.1, load_rules(), load_printer("bambu-a1")), load_rules()


@pytest.mark.parametrize("outlines", ["drop", "keep"])
def test_outline_none_does_nothing(q5, outlines):
    limits, rules = _limits()
    out, res = handle_outlines(q5, outline_color="none", outlines=outlines, limits=limits,
                               rules=rules)
    assert out is q5
    notes = (KEEP_NO_EFFECT_NOTE,) if outlines == "keep" else ()
    assert (res.family, res.core, res.found_by, res.method, res.remap, res.notes) == (
        (), None, "none", OUTLINE_METHOD, (0, 1, 2, 3, 4), notes)
    assert isinstance(res, OutlineResult) and len(res.thinness) == 5


def test_a_bad_outlines_value_is_refused(q5):
    limits, rules = _limits()
    with pytest.raises(ColorError, match="outlines must be drop or keep"):
        handle_outlines(q5, outline_color="none", outlines="hide", limits=limits, rules=rules)

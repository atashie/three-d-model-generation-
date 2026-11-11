"""tdmg.color: the owner's merges, index matching and the outline seam
(docs/plans/2026-11-11-color-palette.md, Task 7b)."""

import numpy as np
import pytest

from tdmg.color import (
    OUTLINE_METHOD,
    OUTLINE_PLACEHOLDER_NOTE,
    OUTSIDE,
    ColorError,
    OutlineResult,
    apply_merges,
    from_labels,
    handle_outlines,
    index_map,
    merge_problem,
    quantize,
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
    assert index_map(q5, m) == (0, 2, 1, None, None)
    # Every pixel of a merged color now has its into color; the others are unchanged.
    for a, b in ((4, 0), (3, 2)):
        assert (m.labels[q5.labels == a] == index_map(q5, m)[b]).all()
    for i in (0, 1, 2):
        assert (m.labels[q5.labels == i] == index_map(q5, m)[i]).all()
    assert (m.labels == OUTSIDE).sum() == (q5.labels == OUTSIDE).sum() == 100
    assert m.dropped == q5.dropped + 2            # merged-away colors count as dropped
    assert (m.iterations, m.converged, m.n_requested, m.n_distinct_colors) == (
        q5.iterations, q5.converged, q5.n_requested, q5.n_distinct_colors)
    assert not m.labels.flags.writeable


def test_apply_merges_resorts_by_the_new_areas(q5):
    # 2 (300 px) takes 0's 500: it becomes the largest color, index 0.
    m = apply_merges(q5, [(0, 2)])
    assert m.hex[0] == q5.hex[2] and m.counts[0] == 800
    assert index_map(q5, m) == (None, 1, 0, 2, 3)


def test_apply_merges_keeps_the_into_color_unchanged(q5):
    m = apply_merges(q5, [(1, 0)])
    i = index_map(q5, m)[0]
    assert m.hex[i] == q5.hex[0] and (m.rgb[i] == q5.rgb[0]).all()
    assert (m.lab[i] == q5.lab[0]).all()


def test_apply_merges_does_not_depend_on_pair_order(q5):
    a = apply_merges(q5, [(4, 0), (3, 1), (2, 0)])
    b = apply_merges(q5, [(2, 0), (3, 1), (4, 0)])
    assert a.hex == b.hex and np.array_equal(a.labels, b.labels)


def test_two_colors_into_one(q5):
    m = apply_merges(q5, [(3, 2), (4, 2)])
    assert m.counts == (600, 500, 400)
    assert index_map(q5, m) == (1, 2, 0, None, None)


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


def test_index_map_matches_by_color(q5):
    same = from_labels(q5.labels, q5.rgb, iterations=0, converged=True, n_requested=5,
                       n_distinct_colors=5)
    assert index_map(q5, same) == (0, 1, 2, 3, 4)
    m = apply_merges(q5, [(0, 4)])                # 4 becomes the largest
    assert index_map(q5, m) == (None, 1, 2, 3, 0)


def test_index_map_refuses_a_palette_with_a_repeated_color():
    labels = np.array([[0, 1]])
    rgb = np.array([[1, 2, 3], [1, 2, 3]], np.uint8)
    q = from_labels(labels, rgb, iterations=0, converged=True, n_requested=2,
                    n_distinct_colors=1)
    with pytest.raises(ColorError, match="a color twice"):
        index_map(q, q)


# --- the outline seam (Task 7c fills it in) ---------------------------------------------

@pytest.mark.parametrize("outlines", ["drop", "keep"])
def test_outline_none_does_nothing(q5, outlines):
    out, res = handle_outlines(q5, outline_color="none", outlines=outlines)
    assert out is q5
    assert res == OutlineResult(family=(), found_by="none", method=OUTLINE_METHOD, note=None)


@pytest.mark.parametrize("outlines", ["drop", "keep"])
def test_outline_auto_is_a_placeholder_that_finds_nothing(q5, outlines):
    out, res = handle_outlines(q5, outline_color="auto", outlines=outlines)
    assert out is q5 and res.family == () and res.found_by == "auto"
    assert res.method == OUTLINE_METHOD == "outline-not-implemented/0"
    assert res.note == OUTLINE_PLACEHOLDER_NOTE and "not implemented" in res.note


def test_an_explicit_outline_list_is_refused_until_task_7c(q5):
    with pytest.raises(ColorError, match="not implemented yet"):
        handle_outlines(q5, outline_color=[4], outlines="drop")


def test_a_bad_outlines_value_is_refused(q5):
    with pytest.raises(ColorError, match="outlines must be drop or keep"):
        handle_outlines(q5, outline_color="none", outlines="hide")

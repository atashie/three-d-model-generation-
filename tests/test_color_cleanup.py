"""Tests for tdmg.color.clean_regions and printable_limits_px
(docs/plans/2026-11-11-color-palette.md, Decision 4 and Task 4).

The label maps are built here. The limits always come from the rules and the printer
profile through printable_limits_px; `limits_for(w)` picks the mm_per_px that makes the
opening width w pixels, and every geometry asserts the precondition it relies on (a piece
below or above the island area, a shape the opening leaves unchanged), so a
change of rule values fails loudly instead of silently testing something else.
"""

import hashlib
import math
import time

import numpy as np
import pytest
from scipy import ndimage
from test_color import _owner_selection, research_rows  # noqa: F401  (a fixture)

from tdmg import color
from tdmg.color import (
    OUTSIDE,
    CleanupLog,
    ColorError,
    Limits,
    clean_regions,
    from_labels,
    printable_limits_px,
    quantize,
)
from tdmg.profiles import load_printer
from tdmg.rules import load_rules

RULES = load_rules()
PRINTER = load_printer("bambu-a1")
OPENING_MM = float(RULES["flat.sliver.opening_width"].default)
ISLAND_MM2 = (float(RULES["flat.island.min_square_side"].default)
              * PRINTER.nozzle_diameter_mm) ** 2

B, C, A = (40, 120, 200), (230, 200, 40), (200, 30, 30)  # display colors only
FOUR = ndimage.generate_binary_structure(2, 1)


def limits_for(width_px: float) -> Limits:
    """Limits whose opening width is width_px pixels (the island area follows the rules)."""
    return printable_limits_px(OPENING_MM / width_px, RULES, PRINTER)


def make_q(labels, rgb):
    labels = np.asarray(labels, np.int32)
    return from_labels(labels, np.array(rgb, np.uint8), iterations=0, converged=True,
                       n_requested=len(rgb), n_distinct_colors=len(rgb))


def hex_map(q) -> np.ndarray:
    """Each pixel's hex color, '' outside."""
    pal = np.array(list(q.hex) + [""], dtype=object)
    return pal[np.where(q.labels == OUTSIDE, len(q.hex), q.labels)]


def hexes(rgb) -> str:
    return "#" + "".join(f"{v:02x}" for v in rgb)


def index_of(q, rgb) -> int:
    return q.hex.index(hexes(rgb))


# --- limits ---------------------------------------------------------------------------------


def test_printable_limits_from_rules_and_profile():
    mpp = 0.07
    lim = printable_limits_px(mpp, RULES, PRINTER)
    assert lim.min_width_px == pytest.approx(OPENING_MM / mpp, rel=1e-15)
    assert lim.min_area_px == pytest.approx(ISLAND_MM2 / mpp ** 2, rel=1e-15)
    assert lim.mm_per_px == mpp
    assert lim.opening_rule == "flat.sliver.opening_width"
    assert lim.island_rule == "flat.island.min_square_side"
    assert lim.nozzle_diameter_mm == PRINTER.nozzle_diameter_mm
    assert lim.opening_width_mm == OPENING_MM
    assert lim.island_area_mm2 == pytest.approx(ISLAND_MM2, rel=1e-15)


def test_rule_ids_match_flat():
    from tdmg import flat
    assert color.OPENING_RULE == flat.OPENING_RULE
    assert color.ISLAND_RULE == flat.ISLAND_RULE


@pytest.mark.parametrize("bad", [0, 0.0, -0.1, math.nan, math.inf, -math.inf, True, "0.1",
                                 None])
def test_printable_limits_refuses_bad_scale(bad):
    with pytest.raises(ColorError):
        printable_limits_px(bad, RULES, PRINTER)


def test_limits_refuse_bad_values():
    with pytest.raises(ColorError):
        Limits(min_width_px=0.0, min_area_px=1.0, mm_per_px=1.0, opening_width_mm=0.4,
               island_area_mm2=0.64, nozzle_diameter_mm=0.4,
               opening_rule="flat.sliver.opening_width", island_rule="flat.island.min_square_side")
    with pytest.raises(ColorError):
        Limits(min_width_px=1.0, min_area_px=math.nan, mm_per_px=1.0, opening_width_mm=0.4,
               island_area_mm2=0.64, nozzle_diameter_mm=0.4,
               opening_rule="flat.sliver.opening_width", island_rule="flat.island.min_square_side")


# --- the opening (R1's buffer(-w/2).buffer(+w/2) on the union of pixel squares) ----------

WIDTHS = [0.9, 1.9, 2.5, 3.2, 3.993, 4.0, 5.353, 6.0]


def strip_widths(w):
    """(n removed, n kept): a straight strip of n px is removed iff n <= w."""
    lo, hi = math.floor(w), math.ceil(w)
    removed = [n for n in {lo, hi} if 1 <= n <= w]
    kept = [n for n in {lo, hi, lo + 1} if n > w]
    return removed, kept


@pytest.mark.parametrize("w", WIDTHS)
@pytest.mark.parametrize("vertical", [False, True])
def test_axis_aligned_strip_is_removed_iff_not_wider_than_w(w, vertical):
    removed, kept = strip_widths(w)
    assert removed or w < 1
    assert kept
    for n in removed + kept:
        mask = np.zeros((40, 80), bool)
        mask[12:12 + n, 4:76] = True           # a 72 px long strip, n px wide
        got = color.open_mask(mask.T if vertical else mask, w)
        got = got.T if vertical else got
        assert not (got & ~mask).any()
        if n in removed:
            assert not got.any(), (w, n)
        else:
            # away from the strip's two ends, every pixel across the width is kept
            assert got[12:12 + n, 4 + math.ceil(w):76 - math.ceil(w)].all(), (w, n)


def _f_exact(mask, pts):
    """Distance from each point (x, y) to the complement of the union of the mask's pixel
    squares (pixel (i, j) is [j, j+1] x [i, i+1]; beyond the image is outside)."""
    pad = np.pad(mask, 1, constant_values=False)
    oi, oj = np.nonzero(~pad)
    x0, y0 = oj - 1.0, oi - 1.0
    dx = np.maximum(np.maximum(x0[None] - pts[:, :1], 0), pts[:, :1] - (x0[None] + 1))
    dy = np.maximum(np.maximum(y0[None] - pts[:, 1:], 0), pts[:, 1:] - (y0[None] + 1))
    return np.sqrt(dx ** 2 + dy ** 2).min(axis=1)


DELTA = math.sqrt(2) / 4   # the covering radius of the half-pixel lattice


def reference_sets(mask, w, step=1 / 8):
    """Brute force. O(m): pixels whose centre is within r - m of some point c, on a grid
    of spacing `step`, with distance to the complement > r + m (r = w / 2). Returns
    (O(0), O(DELTA)). The half-pixel lattice is on the grid, so O(0) bounds the method
    from above exactly; O(DELTA) on the grid is a subset of the continuous O(DELTA)."""
    h, wd = mask.shape
    r = w / 2
    gx = np.arange(0, wd / step + 1) * step
    gy = np.arange(0, h / step + 1) * step
    pts = np.stack(np.meshgrid(gx, gy, indexing="xy"), -1).reshape(-1, 2)
    f = _f_exact(mask, pts)
    cy, cx = np.nonzero(mask)
    out = []
    for m in (0.0, DELTA + 1e-9):
        good = pts[f > r + m]
        o = np.zeros(mask.shape, bool)
        if len(good):
            for y, x in zip(cy, cx):
                d2 = (good[:, 0] - (x + 0.5)) ** 2 + (good[:, 1] - (y + 0.5)) ** 2
                o[y, x] = (d2 <= (r - m) ** 2).any() if r - m >= 0 else False
        out.append(o)
    return out


@pytest.mark.parametrize("w", [1.9, 2.5, 3.993, 4.0, 5.353])
def test_45_degree_band_within_the_stated_bound(w):
    """The band |col - row| <= k of pixels, a staircase at 45 degrees: the result lies
    between O(sqrt(2)/4) and O(0) (see open_mask), so it errs only toward removal, by
    at most the stated margin."""
    ii, jj = np.mgrid[0:24, 0:24]
    for k in range(5):
        mask = np.abs(jj - ii) <= k
        got = color.open_mask(mask, w)
        o0, od = reference_sets(mask, w)
        assert not (got & ~o0).any(), (w, k)
        assert not (od & ~got).any(), (w, k)


@pytest.mark.parametrize("seed", range(6))
def test_opening_errs_only_toward_removal_within_the_stated_bound(seed):
    """The same sandwich on random blobs."""
    rng = np.random.default_rng(seed)
    mask = ndimage.binary_opening(rng.random((14, 14)) < 0.65, structure=FOUR)
    w = float(rng.choice([1.7, 2.5, 3.2, 4.0]))
    got = color.open_mask(mask, w)
    o0, od = reference_sets(mask, w)
    assert not (got & ~o0).any()
    assert not (od & ~got).any()


# --- thin parts -----------------------------------------------------------------------------


def test_one_pixel_line_is_reassigned_to_the_surrounding_color():
    lab = np.zeros((30, 30), np.int32)
    lab[15, :] = 1
    q = make_q(lab, [B, A])
    out, log = clean_regions(q, limits_for(4.0))
    assert out.hex == (hexes(B),)
    assert (out.labels == 0).all()
    assert log.thin_pixels_reassigned == log.pixels_changed == 30 and log.pieces_merged == 0
    assert log.moved == ((hexes(A), hexes(B), 30),)
    assert log.dropped_hex == (q.hex[index_of(q, A)],)
    assert out.dropped == 1


def test_thin_spur_returns_to_its_own_color_when_that_is_nearest():
    """A 1-px spur of B into the outside, with C far away across the outside: the spur is
    thin, its nearest non-thin pixel is B's own, so it stays B (intended)."""
    mask = np.zeros((30, 80), bool)
    mask[5:25, 5:25] = True                      # B square
    mask[15, 25:35] = True                       # the spur, 10 px long
    mask[5:25, 55:75] = True                     # C square, 20 px beyond the spur's tip
    lab = np.where(mask, 0, OUTSIDE).astype(np.int32)
    lab[5:25, 55:75] = 1
    q = make_q(lab, [B, C])
    out, log = clean_regions(q, limits_for(4.0))
    np.testing.assert_array_equal(out.labels, q.labels)
    assert log.pixels_changed == 0 and log.thin_pixels_left >= 10


def test_no_non_thin_pixel_leaves_labels_and_reports():
    mask = np.zeros((10, 40), bool)
    mask[5, 2:38] = True
    lab = np.where(mask, 0, OUTSIDE).astype(np.int32)
    lab[5, 20:38] = 1
    q = make_q(lab, [B, C])
    out, log = clean_regions(q, limits_for(4.0))
    assert log.no_core
    assert log.thin_pixels_reassigned == 0
    # Both pieces (18 px) are below the island area. B's has the lower flat index, so it
    # goes first, into C, its only color neighbour; the joined piece then has none and is kept.
    assert log.pieces_merged == 1
    assert out.hex == (hexes(C),)
    assert log.kept_pieces == 1 and log.kept_area_px == 36


# --- small pieces ---------------------------------------------------------------------------


def test_speck_below_island_area_is_merged_into_the_color_around_it():
    lab = np.zeros((40, 40), np.int32)
    lab[18:21, 18:21] = 1                       # 3 x 3
    lim = limits_for(1.9)
    assert 9 < lim.min_area_px                                # 9 is small ...
    np.testing.assert_array_equal(color.open_mask(lab == 1, lim.min_width_px), lab == 1)
    out, log = clean_regions(make_q(lab, [B, A]), lim)
    assert (out.labels == 0).all() and len(out.hex) == 1
    assert log.pieces_merged == 1 and log.thin_pixels_reassigned == 0
    assert log.moved == ((hexes(A), hexes(B), 9),)


def assert_nothing_thin(lab, lim):
    """Precondition: every color is unchanged by the opening, so only merges act."""
    for c in np.unique(lab[lab != OUTSIDE]):
        np.testing.assert_array_equal(color.open_mask(lab == c, lim.min_width_px), lab == c)


@pytest.mark.parametrize("c0,c1,want", [(18, 20, B), (19, 21, C)])
def test_speck_on_two_colors_goes_to_the_longer_boundary(c0, c1, want):
    lab = np.zeros((30, 40), np.int32)
    lab[:, 20:] = 1                              # B left, C right
    lab[10:13, c0:c1 + 1] = 2                    # 3 x 3 speck of A on the boundary
    lim = limits_for(1.9)
    assert lim.min_area_px > 9
    q = make_q(lab, [B, C, A])
    out, log = clean_regions(q, lim)
    assert set(hex_map(out)[10:13, c0:c1 + 1].ravel()) == {hexes(want)}
    assert log.pieces_merged == 1


@pytest.mark.parametrize("split", [21, 19])
def test_speck_on_equal_boundaries_goes_to_the_lowest_palette_index(split):
    """A 3 x 2 speck straddling the B|C line shares 5 edges with each; the larger color
    (palette index 0) takes it: B when the line is at column 21, C when it is at 19."""
    lab = np.ones((30, 40), np.int32)
    lab[:, :split] = 0
    lab[10:13, split - 1:split + 1] = 2          # cols split-1 (B side) and split (C side)
    q = make_q(lab, [B, C, A])
    lim = limits_for(1.9)
    assert lim.min_area_px > 6
    winner = hexes(B) if split == 21 else hexes(C)
    assert q.hex[0] == winner
    out, log = clean_regions(q, lim)
    assert set(hex_map(out)[10:13, split - 1:split + 1].ravel()) == {winner}
    assert log.pieces_merged == 1


def test_two_adjacent_small_pieces_do_not_swap():
    """A (rows 10-11) touches only C; C (rows 12-13) touches A on 6 edges and B on 3.
    Merged at once they would swap colors. One at a time (A first: same area, lower flat
    index), A joins C, and the joined piece is no longer small."""
    mask = np.zeros((20, 20), bool)
    mask[10:14, 10:16] = True
    mask[14:20, 10:13] = True
    lab = np.where(mask, 0, OUTSIDE).astype(np.int32)
    lab[10:12, 10:16] = 2
    lab[12:14, 10:16] = 1
    lim = limits_for(1.9)
    assert 12 < lim.min_area_px < 18
    assert_nothing_thin(lab, lim)
    q = make_q(lab, [B, C, A])
    out, log = clean_regions(q, lim)
    assert (hex_map(out)[10:14, 10:16] == hexes(C)).all()
    assert (hex_map(out)[14:20, 10:13] == hexes(B)).all()
    assert log.pieces_merged == 1
    assert log.moved == ((hexes(A), hexes(C), 12),)


def test_cascading_merges_reach_a_fixed_point_and_count_passes():
    """A 1-px line inside the outside: A (1 px) touches only C (2 px); joined they are 3 px,
    still small, and join B (8 px)."""
    mask = np.zeros((20, 30), bool)
    mask[10, 10:21] = True
    lab = np.where(mask, 0, OUTSIDE).astype(np.int32)
    lab[10, 10] = 2
    lab[10, 11:13] = 1
    lim = limits_for(0.9)
    assert 3 < lim.min_area_px < 8
    assert_nothing_thin(lab, lim)
    out, log = clean_regions(make_q(lab, [B, C, A]), lim)
    assert (out.labels[mask] == 0).all()
    assert log.pieces_merged == 2                # A into C (its only neighbour), then C into B
    assert log.passes == 2 and not log.cap_hit   # one pass that changed, one that did not
    assert sorted(log.dropped_hex) == sorted([hexes(A), hexes(C)])


def test_pass_cap_is_recorded(monkeypatch):
    lab = np.zeros((30, 30), np.int32)
    lab[10:13, 10:13] = 1
    monkeypatch.setattr(color, "MAX_CLEAN_PASSES", 1)
    _, log = clean_regions(make_q(lab, [B, C]), limits_for(1.9))
    assert log.passes == 1 and log.cap_hit


def test_regions_above_both_limits_are_untouched():
    """Three full-width stripes, 13 to 14 px tall: no convex corner meets another color
    (the stripes' corners are at the image edge, nearer their own non-thin pixels)."""
    lab = np.zeros((40, 60), np.int32)
    lab[13:27] = 2
    lab[27:] = 1
    lim = limits_for(4.0)
    assert 13 > lim.min_width_px and 13 * 60 > lim.min_area_px
    q = make_q(lab, [B, C, A])
    out, log = clean_regions(q, lim)
    np.testing.assert_array_equal(out.labels, q.labels)
    assert out.hex == q.hex
    assert log.pixels_changed == 0 and log.moved == () and log.pieces_merged == 0
    assert log.passes == 1


def test_convex_corners_at_another_color_are_rounded_symmetrically():
    """A block of A inside B loses the corner pixels a disk of the opening width cannot
    reach and whose nearest non-thin pixel is B's (the same corner rounding as R1's
    opening). The tie rule (own color, then lowest index) does not depend on EDT's choice,
    so the four corners lose the same pixels."""
    lab = np.zeros((40, 40), np.int32)
    lab[10:30, 12:28] = 1                        # 20 x 16 block, centred
    q = make_q(lab, [B, A])
    out, log = clean_regions(q, limits_for(4.0))
    got = out.labels
    assert log.pixels_changed > 0 and not log.cap_hit and log.passes <= 3
    changed = got != q.labels
    np.testing.assert_array_equal(changed, changed[::-1, :])
    np.testing.assert_array_equal(changed, changed[:, ::-1])
    assert changed[10:12, 12:14].any() and not changed[13:27, 14:26].any()
    assert int(changed.sum()) == 4 * int(changed[10:20, 12:20].sum())


def test_thresholds_scale_with_mm_per_px():
    lab = np.zeros((30, 30), np.int32)
    lab[10:13, 10:13] = 1                        # 3 x 3
    q = make_q(lab, [B, A])
    fine, coarse = limits_for(1.9), limits_for(1.0)
    assert fine.min_area_px > 9 > coarse.min_area_px
    assert fine.mm_per_px < coarse.mm_per_px
    out_f, _ = clean_regions(q, fine)
    out_c, log_c = clean_regions(q, coarse)
    assert len(out_f.hex) == 1
    np.testing.assert_array_equal(out_c.labels, q.labels)
    assert log_c.pixels_changed == 0


def test_isolated_small_piece_is_kept_and_reported():
    mask = np.zeros((30, 40), bool)
    mask[2:28, 2:20] = True                      # big B region
    mask[10:13, 30:33] = True                    # 3 x 3 A island, only OUTSIDE around it
    lab = np.where(mask, 0, OUTSIDE).astype(np.int32)
    lab[10:13, 30:33] = 1
    lim = limits_for(1.9)
    assert lim.min_area_px > 9
    q = make_q(lab, [B, A])
    out, log = clean_regions(q, lim)
    np.testing.assert_array_equal(out.labels, q.labels)
    assert log.kept_pieces == 1 and log.kept_area_px == 9
    assert log.pieces_merged == 0


def noisy_labels(seed=0, shape=(60, 80), k=4):
    rng = np.random.default_rng(seed)
    coarse = rng.integers(0, k, size=(shape[0] // 4, shape[1] // 4))
    lab = np.kron(coarse, np.ones((4, 4), int))
    specks = rng.random(shape) < 0.03
    lab = np.where(specks, rng.integers(0, k, size=shape), lab).astype(np.int32)
    mask = np.ones(shape, bool)
    mask[:5, :] = mask[:, :3] = False
    return np.where(mask, lab, OUTSIDE)


PAL4 = [B, C, A, (20, 160, 60)]


def test_log_counts_equal_label_changes():
    q = make_q(noisy_labels(), PAL4)
    out, log = clean_regions(q, limits_for(4.0))
    before, after = hex_map(q), hex_map(out)
    changed = before != after
    assert changed.any() and log.pieces_merged > 0 and log.thin_pixels_reassigned > 0
    assert log.pixels_changed == int(changed.sum()) == sum(n for _, _, n in log.moved)
    pairs = {}
    for f, t in zip(before[changed], after[changed]):
        pairs[(f, t)] = pairs.get((f, t), 0) + 1
    assert {(f, t): n for f, t, n in log.moved} == pairs
    assert (before == "").tolist() == (after == "").tolist()    # OUTSIDE never changes
    assert set(out.hex) <= set(q.hex)
    np.testing.assert_array_equal(out.rgb, np.array(
        [q.rgb[q.hex.index(h)] for h in out.hex]))
    assert out.dropped == q.dropped + len(log.dropped_hex)
    assert out.n_requested == q.n_requested and out.iterations == q.iterations
    assert not log.cap_hit and log.passes >= 2
    assert isinstance(log, CleanupLog)


def test_cleanup_is_deterministic():
    q = make_q(noisy_labels(seed=3), PAL4)
    a, la = clean_regions(q, limits_for(4.0))
    b, lb = clean_regions(q, limits_for(4.0))
    np.testing.assert_array_equal(a.labels, b.labels)
    assert a.hex == b.hex and la == lb


def assert_fixed_point_without_small_pieces(out, lim):
    """What clean_regions guarantees: no piece with a color neighbour below the island
    area, and a further pass (thin step, then merge step) leaves the labels as they are.
    It does not claim that no pixel is thin: residual opening losses (corners, staircase
    edges, pixels the merge step returns) are reported in thin_pixels_left and
    thin_returned."""
    lab = out.labels
    for c in range(len(out.hex)):
        pieces, n = ndimage.label(lab == c, structure=FOUR)
        if n == 0:
            continue
        areas = np.bincount(pieces.ravel())[1:]
        for p in np.flatnonzero(areas < lim.min_area_px) + 1:
            region = pieces == p
            ring = ndimage.binary_dilation(region, structure=FOUR) & ~region
            neigh = lab[ring]
            assert not ((neigh != OUTSIDE) & (neigh != c)).any(), (c, p, areas[p - 1])
    again = lab.astype(np.int32).copy()
    color._thin_step(again, lim)
    color._merge_step(again, lim.min_area_px, len(out.hex))
    np.testing.assert_array_equal(again, lab)


def test_synthetic_result_is_a_fixed_point_without_small_pieces():
    q = make_q(noisy_labels(seed=7), PAL4)
    lim = limits_for(4.0)
    out, _ = clean_regions(q, lim)
    assert_fixed_point_without_small_pieces(out, lim)


def test_bad_input_is_refused():
    q = make_q(noisy_labels(), PAL4)
    with pytest.raises(ColorError):
        clean_regions(q, 0.1)
    with pytest.raises(ColorError):
        clean_regions("q", limits_for(4.0))


# --- the owner's images ---------------------------------------------------------------------

@pytest.mark.parametrize("name", ["roadie-tol30", "oddie"])
def test_owner_images_fixed_point_without_small_pieces(name, research_rows):  # noqa: F811 (the fixture)
    rgb, mask = _owner_selection(name, research_rows)
    cols = np.flatnonzero(mask.any(0))
    mm_per_px = 60.0 / (cols.max() - cols.min() + 1)
    lim = printable_limits_px(mm_per_px, RULES, PRINTER)
    q = quantize(rgb, mask, 4)
    t0 = time.perf_counter()
    out, log = clean_regions(q, lim)
    dt = time.perf_counter() - t0
    assert set(out.hex) <= set(q.hex)
    assert not log.cap_hit
    assert ((out.labels == OUTSIDE) == ~mask).all()
    assert_fixed_point_without_small_pieces(out, lim)
    print(f"\n{name}: mm_per_px {mm_per_px:.6f}, min_width_px {lim.min_width_px:.3f}, "
          f"min_area_px {lim.min_area_px:.2f}; passes {log.passes}, cap_hit {log.cap_hit}, "
          f"thin reassigned {log.thin_pixels_reassigned}, thin left {log.thin_pixels_left}, returned {log.thin_returned}, "
          f"pieces merged {log.pieces_merged}, pixels changed {log.pixels_changed} of "
          f"{int(mask.sum())}, dropped {log.dropped_hex}, kept pieces {log.kept_pieces} "
          f"({log.kept_area_px} px), no_core {log.no_core}; moved {log.moved}; "
          f"palette {q.hex} shares {[f'{s:.1%}' for s in q.shares]} -> {out.hex} shares {[f'{s:.1%}' for s in out.shares]}; "
          f"time {dt:.2f} s; labels sha256 "
          f"{hashlib.sha256(out.labels.tobytes()).hexdigest()[:16]}")

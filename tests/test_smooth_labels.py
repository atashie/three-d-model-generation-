"""Tests for tdmg.smoothing.smooth_labels (docs/plans/2026-11-11-color-palette.md, Task 5).

Notation as in tests/test_smoothing.py: s is the supersample factor, so a fine pixel is
1/s image pixels wide. Fine pixel (row i, column j) is the cell [j/s, (j+1)/s] x
[i/s, (i+1)/s] in the pixel-cell coordinates of tdmg.flat.mask_outline and
smooth_outline, so `fine_region` below (mask_outline of the fine map, scaled by 1/s)
is in the same coordinates as smooth_outline.
"""

import hashlib
import math
import time
import tracemalloc

import cv2
import numpy as np
import pytest
import shapely
from shapely import affinity
from test_smoothing import SIGMA, disc, roadie_mask, square

from tdmg.color import OUTSIDE, clean_regions, printable_limits_px, quantize
from tdmg.color_config import edge_sigma_px
from tdmg.flat import mask_outline
from tdmg.profiles import load_printer
from tdmg.rules import load_rules
from tdmg.smoothing import (
    SUPERSAMPLE,
    SmoothedLabels,
    SmoothingError,
    smooth_labels,
    smooth_outline,
)


def fine_map(*args, **kwargs) -> np.ndarray:
    """smooth_labels' fine map; the tests of its vanished colors call it directly."""
    return smooth_labels(*args, **kwargs).fine


def fine_region(fine: np.ndarray, label: int, s: int):
    """The pixel-cell outline of the fine pixels holding label, in image pixel units."""
    return affinity.scale(mask_outline(fine == label), 1 / s, 1 / s, origin=(0, 0))


def boundary_hausdorff(a, b, step: float) -> float:
    """Two-sided distance between the BOUNDARIES of a and b, sampled every step.

    Each boundary is split into pieces no longer than step; every vertex is a sample and
    its exact distance to the other boundary is taken. The result is within step / 2
    below the true boundary Hausdorff distance (distance to a set is 1-Lipschitz).
    """
    def directed(x, y):
        xy = shapely.get_coordinates(shapely.segmentize(x.boundary, step))
        return float(shapely.distance(shapely.points(xy), y.boundary).max())
    return max(directed(a, b), directed(b, a))


def brute_fill(labels: np.ndarray) -> np.ndarray:
    """Every OUTSIDE pixel takes the label at the least squared distance, lowest on ties."""
    out = labels.copy()
    ly, lx = np.nonzero(labels != OUTSIDE)
    lab = labels[ly, lx]
    for y, x in zip(*np.nonzero(labels == OUTSIDE), strict=True):
        d2 = (ly - y) ** 2 + (lx - x) ** 2
        out[y, x] = lab[d2 == d2.min()].min()
    return out


def kron(labels: np.ndarray, s: int) -> np.ndarray:
    return np.kron(labels, np.ones((s, s), labels.dtype))


# --- shape, coverage and the exact (sigma 0) case --------------------------------------


@pytest.mark.parametrize("s", [1, 2, 3, 4])
@pytest.mark.parametrize("sigma", [0.0, 1.0, SIGMA])
def test_output_shape_dtype_and_every_fine_pixel_labelled(s, sigma):
    labels = np.full((30, 41), OUTSIDE, np.int32)
    labels[5:25, 5:20] = 0
    labels[5:25, 20:36] = 1
    labels[12:18, 14:26] = 2
    fine = fine_map(labels, sigma, s)
    assert fine.shape == (30 * s, 41 * s)
    assert fine.dtype == np.int32
    assert set(np.unique(fine).tolist()) == {0, 1, 2}     # no OUTSIDE, nothing else


@pytest.mark.parametrize("s", [1, 2, 4, 5])
def test_sigma_zero_is_a_pure_nearest_upsample(s):
    rng = np.random.default_rng(3)
    labels = rng.integers(0, 4, (23, 31)).astype(np.int32)
    fine = fine_map(labels, 0, s)
    assert np.array_equal(fine, kron(labels, s))
    assert np.array_equal(fine, np.repeat(np.repeat(labels, s, axis=0), s, axis=1))


def test_sigma_zero_keeps_the_pixel_cell_outlines():
    # The coordinate mapping: each color's fine region, scaled by 1/s, is exactly the
    # pixel-cell outline of that color in the image (the convention of tdmg.flat).
    labels = np.zeros((20, 20), np.int32)
    labels[3:9, 4:15] = 1
    labels[11:17, 2:7] = 2
    for s in (1, 3, 4):
        fine = fine_map(labels, 0.0, s)
        for c in (0, 1, 2):
            assert fine_region(fine, c, s).equals(mask_outline(labels == c))


def test_a_single_color_fills_everything():
    labels = np.full((15, 15), OUTSIDE, np.int32)
    labels[7, 7] = 2
    for sigma in (0.0, SIGMA):
        assert (fine_map(labels, sigma, 3) == 2).all()


# --- the two-label case against smooth_outline ----------------------------------------


def outline_field(mask: np.ndarray) -> np.ndarray:
    """smooth_outline's blurred field at the image pixel centres (its padded field's
    interior), computed with the same call smooth_outline makes."""
    field = np.pad(mask.astype(np.float32), 1)
    field = cv2.GaussianBlur(field, (0, 0), SIGMA, sigmaY=SIGMA,
                             borderType=cv2.BORDER_CONSTANT)
    return field[1:-1, 1:-1]


def two_label_masks():
    mask_ring = disc(40, 60, 120) & ~disc(20, 60, 120)
    r, c = np.indices((120, 120))
    diag = (c < r) & (r < 100) & (c > 15)          # a staircase diagonal and two corners
    return {"square": square(), "disc": disc(45, 60, 120), "ring": mask_ring,
            "diagonal": diag, "roadie_like": roadie_mask()}


@pytest.mark.parametrize("name", list(two_label_masks()))
def test_two_labels_at_supersample_1_are_smooth_outlines_field_above_half(name):
    # At s = 1 the fine pixel centres are the image pixel centres, where no interpolation
    # happens. Label 0's field is then smooth_outline's field: the masks are zero on the
    # image border, so edge replication gives the same zero extension that BORDER_CONSTANT
    # and the zero pad give. Label 1's field is the blur of 1 - mask, which is 1 - f up to
    # float32 rounding, so label 0 wins exactly where f > 0.5, away from |f - 0.5| < 1e-6.
    mask = two_label_masks()[name]
    assert not (mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any())
    fine = fine_map(np.where(mask, 0, 1).astype(np.int32), SIGMA, 1)
    f = outline_field(mask)
    clear = np.abs(f - 0.5) > 1e-6
    assert np.array_equal((fine == 0)[clear], (f > 0.5)[clear])


# Measured on the Windows PC on 2026-11-11 (boundary_hausdorff, step 0.01 px, sigma 2.5),
# in image px, per mask (square, disc, ring, diagonal, roadie_like):
#   s = 1: 0.551 0.653 0.674 0.553 0.700   (largest 0.700 / s)
#   s = 2: 0.346 0.346 0.341 0.355 0.349   (0.710 / s)
#   s = 4: 0.164 0.172 0.171 0.178 0.190   (0.761 / s)
#   s = 8: 0.098 0.086 0.087 0.108 0.104   (0.867 / s)
# The excess over the 0.707 / s fine-pixel bound is at most 0.020 px at every s: the gap
# between the bilinear level set and contourpy's chords, which is fixed in image px and does
# not shrink with s. So the one-fine-pixel tolerance holds for s <= 8 only (at s = 16 it
# would need 0.044 + 0.020 > 1/16); the default SUPERSAMPLE is 4.
@pytest.mark.parametrize("s", [1, 2, 4, 8])
@pytest.mark.parametrize("name", list(two_label_masks()))
def test_two_labels_match_smooth_outline_within_one_fine_pixel(name, s):
    # What is compared: the boundary of label 0's fine region (fine_region, image pixel
    # units) and the boundary of smooth_outline(mask) (the same units), by the two-sided
    # sampled boundary distance. Tolerance 1 / s (one fine pixel), derived:
    # - A fine boundary edge separates two fine centres 1/s apart, one with the
    #   interpolated field above 0.5 and one below, so the 0.5 level set of the bilinear
    #   field crosses the segment between them. Every point of the edge is within
    #   sqrt((1/2s)^2 + (1/2s)^2) = 0.707 / s of that crossing.
    # - The bilinear field and contourpy's iso-line share the crossings on the grid lines
    #   between image pixel centres (both interpolate linearly along them); inside a cell
    #   contourpy joins them with a chord, the bilinear level set is a hyperbola through
    #   them. That gap is not bounded here a priori; it is measured (above, at most
    #   0.020 px), and the margin from 0.707 / s to 1 / s covers it and the sampling error
    #   (below step / 2 = 0.005 px) for s <= 8.
    mask = two_label_masks()[name]
    fine = fine_map(np.where(mask, 0, 1).astype(np.int32), SIGMA, s)
    d = boundary_hausdorff(fine_region(fine, 0, s), smooth_outline(mask, SIGMA), 0.01)
    assert d <= 1 / s


def test_a_straight_edge_on_the_image_border_stays_put():
    # A half plane that runs into the image border. Edge replication extends both labels
    # straight out of the image, so the field is the half plane's at every row, and the
    # edge stays on the cell edge x = 20 (at fine column 20 s), as smooth_outline keeps a
    # straight edge.
    s = 4
    labels = np.where(np.indices((40, 50))[1] < 20, 0, 1).astype(np.int32)
    fine = fine_map(labels, SIGMA, s)
    assert (fine[:, :20 * s] == 0).all() and (fine[:, 20 * s:] == 1).all()


# Measured on the Windows PC on 2026-11-11: the worst overshoot of smooth_outline's bounds
# beyond [0, W] x [0, H], over full-image masks and random masks with foreground on two
# borders, at sizes 20 x 20 to 2000 x 1500 (sigma 0.6 to 10, where 8 sigma fits):
#   sigma 0.6: 4.5e-8, 1.0: 0, 1.5: 5.6e-8, 2.5: 5.6e-7, 4.0: 4.5e-7, 6.0: 9.0e-7,
#   10.0: 1.9e-6 px; at most 2.2e-7 * sigma px.
# Why it grows with sigma: a float32 error df in the field moves the 0.5 crossing by
# df / slope, and the slope across an edge is about w_0 = 1 / (sigma sqrt(2 pi)) per px.
# The allowance, 1e-6 * max(sigma, 1) px, is about 4.5 times the worst ratio measured.
def overshoot_allowance(sigma: float) -> float:
    return 1e-6 * max(sigma, 1.0)


def overshoot(mask: np.ndarray, sigma: float) -> float:
    h, w = mask.shape
    minx, miny, maxx, maxy = smooth_outline(mask, sigma).bounds
    return max(-minx, -miny, maxx - w, maxy - h)


@pytest.mark.parametrize("seed", range(12))
def test_smooth_outline_stays_inside_the_image(seed):
    # Why the fine map needs no pad: smooth_outline's contour lies within [0, W] x [0, H]
    # (smooth_labels' docstring gives the proof), so the fine map covers every point that
    # step 2 can clip to, even for foreground on the image border. The proof holds up to
    # float32 rounding of the blurred field (see the measurement above), which is why
    # step 2 must intersect the R1 outline with the image box.
    rng = np.random.default_rng(seed)
    h, w = int(rng.integers(20, 40)), int(rng.integers(20, 40))
    mask = rng.random((h, w)) < 0.6
    mask[:, :3] = True                                    # foreground on the border
    sigma = float(rng.choice([0.6, 1.0, 2.5]))
    assert overshoot(mask, sigma) <= overshoot_allowance(sigma)


@pytest.mark.parametrize("shape, sigma", [((40, 60), 2.5), ((40, 60), 6.0),
                                          ((300, 500), 10.0), ((101, 77), 4.0)])
def test_full_image_masks_overshoot_only_by_rounding(shape, sigma):
    assert overshoot(np.ones(shape, bool), sigma) <= overshoot_allowance(sigma)


# --- junctions, OUTSIDE fill and ties --------------------------------------------------


def test_a_three_color_junction():
    # Three 120-degree sectors of a disc meet at its centre, with OUTSIDE around it.
    n, s = 80, 4
    r, c = np.indices((n, n))
    ang = np.mod(np.arctan2(r + 0.5 - 40, c + 0.5 - 40), 2 * np.pi)
    labels = (ang // (2 * np.pi / 3)).astype(np.int32)
    labels[(c + 0.5 - 40) ** 2 + (r + 0.5 - 40) ** 2 > 30 ** 2] = OUTSIDE
    fine = fine_map(labels, SIGMA, s)
    assert fine.shape == (n * s, n * s) and fine.min() >= 0 and fine.max() <= 2
    # All three colors reach within 2 px of the junction, and a point 20 px out on each
    # sector's bisector (20 sin 60 = 17.3 px from the other sectors, beyond the 10 px
    # kernel radius plus the 1 px interpolation reach) keeps its color.
    fr, fc = np.indices(fine.shape)
    near = (fc + 0.5 - 40 * s) ** 2 + (fr + 0.5 - 40 * s) ** 2 < (2 * s) ** 2
    assert set(np.unique(fine[near]).tolist()) == {0, 1, 2}
    for k, a in enumerate((np.pi / 3, np.pi, 5 * np.pi / 3)):
        y, x = 40 + 20 * math.sin(a), 40 + 20 * math.cos(a)
        assert fine[int(y * s), int(x * s)] == k


def test_outside_fill_matches_brute_force_nearest():
    rng = np.random.default_rng(7)
    labels = rng.integers(0, 3, (25, 33)).astype(np.int32)
    labels[rng.random(labels.shape) < 0.85] = OUTSIDE
    fine = fine_map(labels, 0.0, 2)
    assert np.array_equal(fine, kron(brute_fill(labels), 2))


@pytest.mark.parametrize("row, want", [
    ([0, OUTSIDE, 1], 0),            # equidistant: the lowest label
    ([1, OUTSIDE, 0], 0),            # the lowest label, not the first one met
    ([2, OUTSIDE, 1], 1),
    ([2, OUTSIDE, OUTSIDE, 1], None),  # no tie: each OUTSIDE pixel has one nearest
])
def test_outside_ties_go_to_the_lowest_label(row, want):
    labels = np.array([row], np.int32)
    fine = fine_map(labels, 0.0, 1)
    if want is None:
        assert fine.tolist() == [[2, 2, 1, 1]]
    else:
        assert fine[0, 1] == want


def test_outside_ties_at_equal_squared_distance_in_different_directions():
    # The OUTSIDE pixel (2, 2) is at squared distance 5 from (0, 1) and from (1, 0)
    # (offsets (2, 1) and (1, 2)), with labels 3 and 1, and nothing nearer: it takes 1.
    labels = np.full((3, 3), OUTSIDE, np.int32)
    labels[0, 1] = 3
    labels[1, 0] = 1
    assert fine_map(labels, 0.0, 1)[2, 2] == 1
    assert np.array_equal(fine_map(labels, 0.0, 1), brute_fill(labels))


def test_outside_fill_with_blur_keeps_the_nearest_color_away_from_other_colors():
    # The blur's support: OpenCV's float kernel has radius round(4 sigma) = 10 px at
    # sigma 2.5, and the bilinear step reads image pixel centres within 1 px of a fine
    # centre. So where every filled pixel within (radius + 1) px in x and y (the kernel is
    # separable, so its support is a square) holds one color, every other field is 0 and
    # the fine pixel takes that color.
    labels = np.full((60, 80), OUTSIDE, np.int32)
    labels[20:40, 10:30] = 0
    labels[20:40, 50:70] = 1
    s = 4
    fine = fine_map(labels, SIGMA, s)
    filled = brute_fill(labels)
    reach = round(4 * SIGMA) + 1
    lo = cv2.erode((filled == 0).astype(np.uint8), np.ones((2 * reach + 1,) * 2, np.uint8),
                   borderType=cv2.BORDER_REPLICATE).astype(bool)
    hi = cv2.erode((filled == 1).astype(np.uint8), np.ones((2 * reach + 1,) * 2, np.uint8),
                   borderType=cv2.BORDER_REPLICATE).astype(bool)
    outside = kron((labels == OUTSIDE).astype(np.int32), s).astype(bool)
    assert (fine[kron(lo.astype(np.int32), s).astype(bool) & outside] == 0).all()
    assert (fine[kron(hi.astype(np.int32), s).astype(bool) & outside] == 1).all()
    assert lo.sum() > 100 and hi.sum() > 100


def test_input_is_not_modified_and_labels_are_a_subset():
    labels = np.full((20, 20), OUTSIDE, np.int32)
    labels[5:15, 2:9] = 5
    labels[5:15, 11:18] = 2
    before = labels.copy()
    fine = fine_map(labels, SIGMA, 2)
    assert np.array_equal(labels, before)
    assert set(np.unique(fine).tolist()) == {2, 5}


# --- colors the blur removes ---------------------------------------------------------


def test_colors_the_blur_removes_are_reported():
    # A lone pixel of 1 and a 2 x 2 block of 2 in a field of 0: at sigma 2.5 neither field
    # reaches the field of 0 anywhere, so both vanish, and smooth_labels says so.
    labels = np.zeros((40, 40), np.int32)
    labels[20, 20] = 1
    labels[10:12, 10:12] = 2
    out = smooth_labels(labels, SIGMA, 4)
    assert isinstance(out, SmoothedLabels)
    assert out.vanished == (1, 2)
    assert (out.fine == 0).all()
    # Exact edges keep every color.
    assert smooth_labels(labels, 0.0, 4).vanished == ()


def test_no_color_vanishes_from_large_regions():
    labels = np.full((30, 41), OUTSIDE, np.int32)
    labels[5:25, 5:20] = 0
    labels[5:25, 20:36] = 3
    out = smooth_labels(labels, SIGMA, 2)
    assert out.vanished == ()
    assert set(np.unique(out.fine).tolist()) == {0, 3}


def test_the_result_is_frozen_and_read_only():
    out = smooth_labels(np.zeros((4, 4), np.int32), 1.0, 2)
    with pytest.raises(AttributeError):
        out.vanished = (1,)
    with pytest.raises(ValueError):
        out.fine[0, 0] = 1


# --- determinism ---------------------------------------------------------------------


def test_repeat_calls_are_identical_and_dtype_independent():
    rng = np.random.default_rng(11)
    labels = rng.integers(-1, 4, (40, 50)).astype(np.int32)
    first = fine_map(labels, SIGMA, 4)
    assert np.array_equal(fine_map(labels, SIGMA, 4), first)
    assert np.array_equal(fine_map(labels.astype(np.int64), SIGMA, 4), first)
    assert np.array_equal(fine_map(labels, SIGMA, np.int64(4)), first)


def test_the_band_size_does_not_change_the_result():
    rng = np.random.default_rng(5)
    labels = rng.integers(-1, 3, (37, 29)).astype(np.int32)
    whole = fine_map(labels, SIGMA, 4)
    for band in (1, 7, 64):
        assert np.array_equal(fine_map(labels, SIGMA, 4, _band_rows=band), whole)


def test_supersample_default_is_the_module_constant():
    labels = np.zeros((5, 6), np.int32)
    assert fine_map(labels, 1.0).shape == (5 * SUPERSAMPLE, 6 * SUPERSAMPLE)
    assert SUPERSAMPLE == 4


# --- refusals --------------------------------------------------------------------------


@pytest.mark.parametrize("labels, message", [
    (np.zeros((4, 4), np.float64), "integer"),
    (np.zeros((4, 4), bool), "integer"),
    (np.zeros((4, 4, 1), np.int32), "two-dimensional"),
    (np.zeros(4, np.int32), "two-dimensional"),
    (np.zeros((0, 4), np.int32), "empty"),
    (np.full((3, 3), -2, np.int32), "-1"),
    (np.full((3, 3), OUTSIDE, np.int32), "no labelled pixel"),
    (np.full((3, 3), 2 ** 40, np.int64), "int32"),
])
def test_bad_labels_raise(labels, message):
    with pytest.raises(SmoothingError, match=message):
        fine_map(labels, 1.0, 2)


def test_a_nested_list_of_ints_is_accepted():
    assert fine_map([[0, 1], [1, 0]], 0.0, 1).tolist() == [[0, 1], [1, 0]]


@pytest.mark.parametrize("sigma", [-1.0, float("nan"), float("inf"), True, "2.5", None])
def test_bad_sigma_raises(sigma):
    with pytest.raises(SmoothingError, match="sigma_px"):
        fine_map(np.zeros((4, 4), np.int32), sigma, 2)


@pytest.mark.parametrize("s", [0, -1, 2.0, True, "4", None])
def test_bad_supersample_raises(s):
    with pytest.raises(SmoothingError, match="supersample"):
        fine_map(np.zeros((4, 4), np.int32), 1.0, s)


# --- the owner's images ---------------------------------------------------------------

RULES = load_rules()
PRINTER = load_printer("bambu-a1")

# Measured on the Windows PC on 2026-11-11 (numpy, scipy and OpenCV from uv.lock). The
# hashes are asserted on every platform on purpose: they are how cross-platform parity is
# checked. A hash failure on another machine (the M5 Mac has not run this yet) means that
# parity must be investigated (library builds, float rounding), not that the code is wrong.
# Share changes, fine map (inside the mask) minus cleaned map, in percentage points:
#   roadie-tol30 (#ed0707 #ededed #eeef0a #5c271b): +0.281 +0.205 +0.059 -0.545
#   oddie        (#234c1a #4c708b #48a835 #dc4f47): +0.005 +0.020 -0.004 -0.020
# The largest change is Roadie's dark outline color, whose lines are a few pixels wide:
# the blur rounds and thins them (smooth_outline's known effect on features below about
# sigma). The tolerance, 1 percentage point, is a sanity margin about twice the largest
# measured change; the hashes pin the exact output.
OWNER_SHARES_TOL = 0.01
OWNER_FINE_SHA = {"roadie-tol30": "b10f4e03e0ffde1c", "oddie": "c0c1daf8b9b6bdca"}


@pytest.mark.parametrize("name", ["roadie-tol30", "oddie"])
def test_owner_images_smooth_preset(name, owner_selection):
    rgb, mask = owner_selection(name)
    cols = np.flatnonzero(mask.any(0))
    mm_per_px = 60.0 / (cols.max() - cols.min() + 1)
    cleaned, _ = clean_regions(quantize(rgb, mask, 4),
                               printable_limits_px(mm_per_px, RULES, PRINTER))
    sigma, rule = edge_sigma_px("smooth", RULES)
    s = SUPERSAMPLE
    tracemalloc.start()
    t0 = time.perf_counter()
    # tracemalloc counts numpy and Python allocations only, not OpenCV's own buffers.
    result = smooth_labels(cleaned.labels, sigma, s)
    fine = result.fine
    dt = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    k = len(cleaned.hex)
    assert fine.shape == (mask.shape[0] * s, mask.shape[1] * s)
    assert fine.min() >= 0 and fine.max() < k
    assert result.vanished == ()
    # Shares over the fine pixels whose image pixel is in the mask, against the cleaned
    # map's shares (its labelled pixels).
    inside = np.repeat(np.repeat(mask, s, axis=0), s, axis=1)
    fine_shares = np.bincount(fine[inside], minlength=k) / inside.sum()
    diff = fine_shares - np.array(cleaned.shares)
    digest = hashlib.sha256(np.ascontiguousarray(fine).tobytes()).hexdigest()[:16]
    print(f"\n{name}: mm_per_px {mm_per_px:.6f}, sigma {sigma} ({rule}), s {s}, "
          f"fine {fine.shape}, {cleaned.hex}, cleaned shares "
          f"{[f'{v:.4%}' for v in cleaned.shares]}, fine shares "
          f"{[f'{v:.4%}' for v in fine_shares]}, change (points) "
          f"{[f'{100 * v:+.4f}' for v in diff]}; time {dt:.2f} s; tracemalloc peak "
          f"{peak / 2 ** 20:.1f} MiB (numpy/Python only); vanished {result.vanished}; fine sha256 {digest}")
    assert np.abs(diff).max() <= OWNER_SHARES_TOL
    assert digest == OWNER_FINE_SHA[name]

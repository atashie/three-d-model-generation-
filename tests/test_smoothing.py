"""Tests for tdmg.smoothing (docs/plans/2026-11-10-outline-smoothing.md, Task 2).

Each expectation is derived from the geometry of a Gaussian blur, not read off the output.
Notation: w_k is the normalised 1-D kernel weight at offset k pixels. OpenCV samples the
Gaussian at integer offsets within +-4 sigma for float images and normalises the samples,
so w_k = exp(-k^2 / (2 sigma^2)) / sum, which `kernel` reproduces.
"""

import hashlib
import math
import os
import subprocess
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pytest
import shapely
from selection_fixtures import RED, WHITE, roadie_like
from shapely import affinity

from tdmg.flat import _sampled_hausdorff as sampled_hausdorff
from tdmg.flat import mask_outline
from tdmg.smoothing import METHOD, SmoothingError, _valid_polygonal, smooth_outline

SIGMA = 2.5


def kernel(sigma: float = SIGMA) -> dict[int, float]:
    radius = round(4 * sigma)
    ks = np.arange(-radius, radius + 1)
    w = np.exp(-ks.astype(float) ** 2 / (2 * sigma ** 2))
    return dict(zip(ks.tolist(), (w / w.sum()).tolist(), strict=True))


def square(shape=(100, 100), rows=(20, 80), cols=(20, 80)) -> np.ndarray:
    mask = np.zeros(shape, bool)
    mask[rows[0]:rows[1], cols[0]:cols[1]] = True
    return mask


def crossings(geom, y: float) -> list[float]:
    """x of every boundary crossing of the horizontal line at y, sorted."""
    hit = geom.boundary.intersection(shapely.LineString([(-1e3, y), (1e3, y)]))
    return sorted(float(x) for x in shapely.get_coordinates(hit)[:, 0])


def roadie_mask() -> np.ndarray:
    img = roadie_like()
    rgb = img[..., :3]
    return (img[..., 3] == 255) & ((rgb == RED).all(axis=2) | (rgb == WHITE).all(axis=2))


# --- straight edges and corners --------------------------------------------------------


def test_straight_edges_stay_where_they_were_at_the_midpoints():
    # Across an edge at x = 20 the blurred field at the pixel centres on either side is
    # f(19) = sum_{k>=1} w_k = (1 - w_0) / 2 and f(20) = sum_{k>=0} w_k = (1 + w_0) / 2:
    # they sum to 1, so linear interpolation puts the 0.5 crossing exactly halfway between
    # the centres 19.5 and 20.5, at the cell edge 20. The midpoints are 30 px (12 sigma)
    # from every corner, so the other edges add nothing measurable.
    g = smooth_outline(square(), SIGMA)
    assert g.is_valid and isinstance(g, shapely.Polygon)
    for edge, found in zip((20.0, 80.0), crossings(g, 50.0), strict=True):
        assert abs(found - edge) < 1e-3
    swapped = affinity.affine_transform(g, [0, 1, 1, 0, 0, 0])    # y <-> x
    for edge, found in zip((20.0, 80.0), crossings(swapped, 50.0), strict=True):
        assert abs(found - edge) < 1e-3


def test_corners_are_rounded_and_lose_the_predicted_area():
    # Near a corner the blurred unit quadrant is Phi(x/s) Phi(y/s) for a continuous
    # Gaussian, so the 0.5 contour inside the corner is y = s Phi^-1(0.5 / Phi(x/s)).
    # Outside the quadrant one factor is below 0.5, so nothing is added. The area lost at
    # one corner is s^2 * integral_0^inf Phi^-1(0.5 / Phi(t)) dt (about 0.865 s^2). The
    # sampled kernel and the linear interpolation between pixel centres differ from the
    # continuous case; 5% covers that (the chords cut inside the convex curve).
    nd = NormalDist()
    ts = np.linspace(0.0, 12.0, 120001)
    ys = [nd.inv_cdf(min(0.5 / nd.cdf(t), 1 - 1e-15)) for t in ts]
    per_corner = SIGMA ** 2 * float(np.trapezoid(np.maximum(ys, 0.0), ts))
    g = smooth_outline(square(), SIGMA)
    loss = 60 * 60 - g.area
    assert loss == pytest.approx(4 * per_corner, rel=0.05)
    # The corner moves in along the diagonal to where Phi(t)^2 = 0.5, t = 0.545 sigma.
    t = nd.inv_cdf(math.sqrt(0.5)) * SIGMA
    corner = shapely.Point(20.0, 20.0)
    assert g.boundary.distance(corner) == pytest.approx(math.sqrt(2) * t, rel=0.05)


# --- noise: specks and notches -------------------------------------------------------


def test_a_speck_next_to_a_body_is_removed():
    # A lone pixel blurs to at most w_0^2 (about 0.025 at sigma 2.5) at any pixel centre.
    # The box checked (x 89-92) is interpolated from the centres of columns 88-92, at least
    # 9 columns from the body's last column 79, so the body adds at most sum_{k>=9} w_k
    # there. Both together stay below 0.5, so no 0.5 contour enters the box.
    w = kernel()
    assert w[0] ** 2 + sum(v for k, v in w.items() if k >= 9) < 0.5
    mask = square()
    mask[50, 90] = True
    g = smooth_outline(mask, SIGMA)
    assert isinstance(g, shapely.Polygon)
    assert not g.intersects(shapely.box(89.0, 49.0, 92.0, 52.0))


def test_a_one_pixel_notch_is_filled():
    # A notch one pixel wide and four deep (column 50, rows 20-23) in the top edge of the
    # square. At the centre of notch row r the body gives sum_{k >= 20 - r} w_k (the
    # columns cover more than the kernel), and the missing column takes away at most
    # w_0 * sum of the row weights <= w_0. For r >= 21 the bound is above 0.5, so those
    # centres are inside the smoothed outline. Row 20 is not claimed: its bound is not.
    w = kernel()
    mask = square()
    mask[20:24, 50] = False
    g = smooth_outline(mask, SIGMA)
    assert isinstance(g, shapely.Polygon) and not g.interiors
    for r in (21, 22, 23):
        bound = sum(v for k, v in w.items() if k >= 20 - r) - w[0]
        assert bound > 0.5
        assert g.contains(shapely.Point(50.5, r + 0.5))


# --- staircases ------------------------------------------------------------------------


def test_a_diagonal_staircase_becomes_a_straight_line():
    # mask[r, c] = c < r. The map (c, r) -> (r, c + 1) takes the mask onto its complement,
    # and the isotropic blur commutes with it, so f(T p) = 1 - f(p). The pixel centres
    # (k, k) and (k, k + 1) are such a pair, so the 0.5 crossing on the grid edge between
    # them is at its midpoint. The mask is also invariant under the translation (1, 1), so
    # the field is too, and this holds at every k along the diagonal: every contour vertex
    # on the edge lies on the line y = x + 0.5 (pixel-cell coordinates). In a window
    # 80 px wide, away from the triangle's corners, the smoothed
    # boundary is that line, sqrt(2) * 80 long; the exact pixel outline is a staircase of
    # 80 + 80, about 41% longer.
    n = 200
    r, c = np.indices((n, n))
    mask = c < r
    window = shapely.box(60.0, 0.0, 140.0, 160.0)
    euclid = math.sqrt(2) * 80
    smooth = smooth_outline(mask, SIGMA).boundary.intersection(window)
    exact = mask_outline(mask).boundary.intersection(window)
    assert smooth.length == pytest.approx(euclid, rel=0.02)
    assert exact.length / euclid == pytest.approx(math.sqrt(2), rel=0.02)
    xy = shapely.get_coordinates(smooth)
    assert np.abs(xy[:, 1] - xy[:, 0] - 0.5).max() < 1e-3


# --- topology and coordinates --------------------------------------------------------


def disc(radius: float, centre: int, size: int) -> np.ndarray:
    # Pixel (c, r) is in the disc when its centre (c + 0.5, r + 0.5) is within radius of
    # (centre, centre), so the mask is symmetric about that point in pixel-cell coordinates.
    r, c = np.indices((size, size))
    return (c + 0.5 - centre) ** 2 + (r + 0.5 - centre) ** 2 <= radius ** 2


def test_a_ring_keeps_its_hole():
    # Outer radius 40, inner 20: the ring is 20 px (8 sigma) wide, so the blur cannot close
    # it. The hole's boundary moves towards its centre by about sigma^2 / (2 * 20) = 0.16 px,
    # a 1.6% loss of hole area; 5% is a loose margin over that.
    mask = disc(40, 60, 120) & ~disc(20, 60, 120)
    g = smooth_outline(mask, SIGMA)
    assert isinstance(g, shapely.Polygon) and len(g.interiors) == 1
    hole = shapely.Polygon(g.interiors[0])
    assert hole.contains(shapely.Point(60, 60))
    assert hole.area == pytest.approx(int(disc(20, 60, 120).sum()), rel=0.05)


def test_smooth_and_exact_outlines_agree_on_a_disc():
    # Every point of the exact pixel outline lies on an edge between a cell whose centre is
    # inside the circle and one whose centre is outside, so within sqrt(2)/2 of the circle.
    # The 0.5 contour of a blurred disc lies inside it by about sigma^2 / (2R) = 0.05 px.
    # So the two agree within 1 px. A half-pixel shift of the smooth outline breaks this,
    # and by symmetry the smooth outline's centroid is the disc's centre.
    mask = disc(60, 80, 160)
    exact = mask_outline(mask)
    smooth = smooth_outline(mask, SIGMA)
    assert sampled_hausdorff(exact, smooth, 0.25) < 1.0
    assert smooth.centroid.distance(shapely.Point(80, 80)) < 1e-3
    shifted = affinity.translate(smooth, 0.5, 0.5)
    assert sampled_hausdorff(exact, shifted, 0.25) > 1.0


def test_foreground_touching_the_image_border_gives_a_closed_valid_polygon():
    # The mask is zero-extended (BORDER_CONSTANT) and padded by one pixel before the blur,
    # so the field at the pad is the blur's true value there: at most (1 - w_0) / 2 < 0.5
    # (every foreground cell is at least one column or row away). The contour closes inside
    # the pad, and an edge on the image border stays on it, as an interior edge does.
    mask = square((50, 50), (0, 30), (0, 30))
    g = smooth_outline(mask, SIGMA)
    assert g.is_valid and isinstance(g, shapely.Polygon) and g.exterior.is_closed
    left, right = crossings(g, 15.0)
    assert abs(left - 0.0) < 1e-3 and abs(right - 30.0) < 1e-3
    top, bottom = crossings(affinity.affine_transform(g, [0, 1, 1, 0, 0, 0]), 15.0)
    assert abs(top - 0.0) < 1e-3 and abs(bottom - 30.0) < 1e-3
    full = smooth_outline(np.ones((20, 30), bool), SIGMA)
    assert full.is_valid and isinstance(full, shapely.Polygon)
    assert full.bounds == pytest.approx((0.0, 0.0, 30.0, 20.0), abs=1e-3)


@pytest.mark.parametrize("seed", range(20))
def test_random_masks_give_valid_polygonal_output(seed):
    rng = np.random.default_rng(seed)
    mask = rng.random((30, 37)) < 0.5
    mask[10:20, 10:25] = True              # one body large enough to survive any sigma used
    g = smooth_outline(mask, float(rng.choice([0.6, 1.0, 1.5, 2.5])))
    assert g.is_valid and isinstance(g, (shapely.Polygon, shapely.MultiPolygon))
    assert g.area > 0


def test_invalid_contours_are_repaired_into_polygons():
    # contourpy did not give invalid rings on 3000 random masks, but a ring touching itself
    # is possible in principle (a grid value exactly at 0.5); _valid_polygonal repairs it.
    bowtie = shapely.Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])
    assert not bowtie.is_valid
    fixed = _valid_polygonal(bowtie)
    assert fixed.is_valid and isinstance(fixed, shapely.MultiPolygon)
    assert fixed.area == pytest.approx(2.0)
    ok = shapely.box(0, 0, 1, 1)
    assert _valid_polygonal(ok) is ok


def test_integer_masks_use_0_and_255():
    mask = square()
    assert smooth_outline(mask.astype(np.uint8) * 255, SIGMA).equals(
        smooth_outline(mask, SIGMA))


def test_method_names_the_steps():
    assert "Gaussian" in METHOD and "0.5" in METHOD and "contourpy" in METHOD


# --- determinism -------------------------------------------------------------------------


def test_repeat_calls_are_identical():
    mask = roadie_mask()
    first = shapely.to_wkb(smooth_outline(mask, SIGMA))
    assert shapely.to_wkb(smooth_outline(mask, SIGMA)) == first


CHILD = """
import hashlib, sys
import numpy as np, shapely
sys.path.insert(0, sys.argv[1])
from test_smoothing import roadie_mask
from tdmg.smoothing import smooth_outline
print(hashlib.sha256(shapely.to_wkb(smooth_outline(roadie_mask(), 2.5))).hexdigest())
"""


def test_two_fresh_processes_give_identical_outlines():
    tests_dir = str(Path(__file__).parent)
    outputs = []
    for hash_seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        done = subprocess.run([sys.executable, "-c", CHILD, tests_dir], env=env,
                              capture_output=True, text=True, check=True, timeout=300)
        outputs.append(done.stdout.split())
    assert len(outputs[0]) == 1 and len(outputs[0][0]) == 64
    assert outputs[0] == outputs[1]
    here = hashlib.sha256(shapely.to_wkb(smooth_outline(roadie_mask(), SIGMA))).hexdigest()
    assert outputs[0] == [here]


# --- errors ----------------------------------------------------------------------------


@pytest.mark.parametrize("sigma", [0.0, -1.0, float("nan"), float("inf"), -float("inf"),
                                   True, "2.5", None])
def test_bad_sigma_raises(sigma):
    with pytest.raises(SmoothingError, match="sigma_px"):
        smooth_outline(square(), sigma)


@pytest.mark.parametrize("mask, message", [
    (np.ones((3, 3), np.float64), "bool or integer"),
    (np.full((4, 4), 1, np.uint8), "0 and 255"),
    (np.ones((3, 3, 3), bool), "two-dimensional"),
])
def test_bad_masks_raise(mask, message):
    with pytest.raises(SmoothingError, match=message):
        smooth_outline(mask, SIGMA)


def test_all_background_raises():
    with pytest.raises(SmoothingError, match="no foreground"):
        smooth_outline(np.zeros((10, 10), bool), SIGMA)


def test_foreground_that_smooths_away_raises():
    mask = np.zeros((20, 20), bool)
    mask[10, 10] = True                    # a lone pixel: at most w_0^2 < 0.5 after blurring
    with pytest.raises(SmoothingError, match="nothing remains"):
        smooth_outline(mask, SIGMA)


def test_smoothing_error_is_a_value_error():
    assert issubclass(SmoothingError, ValueError)

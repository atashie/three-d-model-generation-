import math

import numpy as np
import pytest
import shapely

from tdmg.flat import FlatError, mask_outline, to_model


def polygons(geom) -> list:
    return list(getattr(geom, "geoms", [geom]))


@pytest.mark.parametrize("seed", range(5))
def test_outline_area_equals_pixel_count(seed):
    mask = np.random.default_rng(seed).random((40, 57)) < 0.45
    outline = mask_outline(mask)
    assert outline.is_valid
    assert outline.area == int(mask.sum())


def test_outline_of_uint8_mask_matches_bool():
    mask = np.zeros((6, 7), np.uint8)
    mask[1:4, 2:6] = 255
    assert mask_outline(mask).equals(mask_outline(mask > 0))
    assert mask_outline(mask).bounds == (2.0, 1.0, 6.0, 4.0)


def test_hole_inside_a_hole_gives_ring_and_separate_island():
    mask = np.zeros((11, 11), bool)
    mask[0:11, 0:11] = True
    mask[2:9, 2:9] = False   # hole in the ring
    mask[4:7, 4:7] = True    # island inside the hole
    parts = sorted(polygons(mask_outline(mask)), key=lambda p: -p.area)
    assert len(parts) == 2
    ring, island = parts
    assert len(ring.interiors) == 1
    assert len(island.interiors) == 0
    assert ring.area == 121 - 49
    assert island.area == 9
    assert island.within(shapely.Polygon(ring.interiors[0]))


def test_l_glyph_keeps_its_foot_at_model_bottom_right():
    # Image rows go down. Upright stem on the left, foot along the bottom to the right.
    mask = np.zeros((20, 30), bool)
    mask[2:18, 3:7] = True     # stem
    mask[14:18, 3:27] = True   # foot at image bottom, extending right
    model, transform = to_model(mask_outline(mask), 48.0)
    s = transform["scale_mm_per_px"]
    assert s == pytest.approx(2.0)
    minx, miny, maxx, maxy = model.bounds
    assert (minx, miny) == (0.0, 0.0)
    # The foot's far end (image x 26, rows 14-17) is at low y and high x in the model.
    foot_tip = shapely.box(maxx - s, 0.0, maxx, 4 * s)
    assert model.contains(foot_tip.buffer(-1e-9))
    # Above the foot, the right of the model is empty; the stem sits at low x.
    assert not model.intersects(shapely.box(maxx - s, 5 * s, maxx, maxy).buffer(-1e-9))
    assert model.contains(shapely.box(0.0, maxy - s, 4 * s, maxy).buffer(-1e-9))


def test_transform_maps_corners_and_reports_plain_numbers():
    mask = np.zeros((10, 12), bool)
    mask[3:7, 2:10] = True
    model, transform = to_model(mask_outline(mask), 16.0)
    assert transform == {"scale_mm_per_px": 2.0, "x0_px": 2.0, "y1_px": 7.0,
                         "mask_width_px": 8.0, "mask_height_px": 4.0}
    assert all(type(v) is float for v in transform.values())
    assert model.bounds == (0.0, 0.0, 16.0, 8.0)


@pytest.mark.parametrize("width", [0.37, 1.0, 60.0, 123.456789])
def test_scaled_width_equals_requested_width(width):
    mask = np.random.default_rng(7).random((31, 43)) < 0.5
    model, _ = to_model(mask_outline(mask), width)
    minx, miny, maxx, _ = model.bounds
    assert abs((maxx - minx) - width) < 1e-9
    assert abs(minx) < 1e-9 and abs(miny) < 1e-9


def test_empty_mask_raises():
    with pytest.raises(FlatError, match="^no printable foreground$"):
        mask_outline(np.zeros((5, 5), bool))


def test_mask_must_be_two_dimensional():
    with pytest.raises(FlatError):
        mask_outline(np.ones((3, 3, 3), bool))


@pytest.mark.parametrize("width", [0.0, -1.0, math.inf, -math.inf, math.nan])
def test_bad_width_raises(width):
    outline = mask_outline(np.ones((2, 2), bool))
    with pytest.raises(FlatError, match="width"):
        to_model(outline, width)


def test_to_model_refuses_empty_outline():
    with pytest.raises(FlatError, match="^no printable foreground$"):
        to_model(shapely.Polygon(), 10.0)

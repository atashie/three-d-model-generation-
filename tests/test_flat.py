import json
import math

import numpy as np
import pytest
import shapely

from tdmg.flat import QUAD_SEGS, FlatError, clean, mask_outline, to_model


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


# --- Task 4: cleaning ---------------------------------------------------------------

OPENING = 0.4
MIN_ISLAND = 0.64  # (2.0 x 0.4 mm)^2, the rule defaults with the A1 nozzle


def coords(part) -> set:
    return {tuple(c) for ring in [part.exterior, *part.interiors] for c in ring.coords}


def test_squares_touching_at_a_corner_become_two_parts_without_shared_coordinates():
    touching = shapely.union_all([shapely.box(0, 0, 5, 5), shapely.box(5, 5, 10, 10)])
    assert isinstance(touching, shapely.MultiPolygon)
    parts, report = clean(touching, OPENING, MIN_ISLAND)
    assert len(parts) == 2
    assert all(isinstance(p, shapely.Polygon) and p.is_valid for p in parts)
    assert not coords(parts[0]) & coords(parts[1])
    assert parts[0].distance(parts[1]) > 0
    assert report["dropped_islands"] == []


def test_thin_hair_is_removed():
    square = shapely.box(0, 0, 5, 5)
    hair = shapely.box(5, 2.4, 9, 2.6)  # 0.2 mm wide, 4 mm long
    parts, report = clean(shapely.union_all([square, hair]), OPENING, MIN_ISLAND)
    assert len(parts) == 1
    # Opening keeps a stub at the hair's root: the eroded square bulges to where the
    # root corners are r = 0.2 away, x = 5 - sqrt(0.2^2 - 0.1^2), and regrows by r.
    # The polygonal arcs can erode less than a true circle, by at most the chord error.
    chord_error = 0.2 * (1 - math.cos(math.pi / (4 * QUAD_SEGS)))
    assert parts[0].bounds[2] <= 5.0 - math.sqrt(0.2**2 - 0.1**2) + 0.2 + chord_error
    # An exact opening never adds area. The polygonal one can poke past the root's inner
    # corners (measured: 0.0003 mm, 1e-5 mm^2), but only by up to the chord error.
    assert shapely.union_all([square, hair]).buffer(chord_error).contains(parts[0])
    assert report["removed_area_mm2"] > 0
    assert report["removed_area_mm2"] >= hair.area - 1e-9
    assert report["area_before_mm2"] == pytest.approx(square.area + hair.area)
    assert report["area_after_mm2"] == pytest.approx(parts[0].area)
    # The farthest removed points are the hair's tip corners.
    tip = max(parts[0].distance(shapely.Point(9, y)) for y in (2.4, 2.6))
    assert 3.9 < tip < 4.0
    assert report["hausdorff_mm"] == pytest.approx(tip, abs=1e-9)


def test_specks_below_min_island_are_dropped_and_reported():
    body = shapely.box(0, 0, 5, 5)
    speck = shapely.box(10, 0, 10.7, 0.7)     # 0.49 mm^2: survives opening, below 0.64
    island = shapely.box(10, 3, 11, 4)        # 1 mm^2 before opening
    parts, report = clean(shapely.union_all([body, speck, island]), OPENING, MIN_ISLAND)
    assert len(parts) == 2
    assert parts[0].area > parts[1].area
    assert parts[1].within(island)
    assert len(report["dropped_islands"]) == 1
    assert 0 < report["dropped_islands"][0] < MIN_ISLAND
    assert report["dropped_islands"][0] == pytest.approx(speck.buffer(-0.2).buffer(
        0.2, quad_segs=QUAD_SEGS).area)


def test_dropped_islands_are_listed_largest_first():
    specks = [shapely.box(10 * i, 20, 10 * i + side, 20 + side)
              for i, side in enumerate([0.5, 0.7, 0.6])]
    geom = shapely.union_all([shapely.box(0, 0, 5, 5), *specks])
    _, report = clean(geom, OPENING, MIN_ISLAND)
    assert len(report["dropped_islands"]) == 3
    assert report["dropped_islands"] == sorted(report["dropped_islands"], reverse=True)


def test_report_numbers_are_plain_floats_or_none():
    geom = shapely.union_all([shapely.box(0, 0, 5, 5), shapely.box(10, 0, 10.7, 0.7)])
    _, report = clean(geom, OPENING, MIN_ISLAND)
    assert set(report) == {"opening_mm", "min_island_mm2", "area_before_mm2",
                           "area_after_mm2", "removed_area_mm2", "hausdorff_mm",
                           "dropped_islands"}
    for key, value in report.items():
        if key == "dropped_islands":
            assert value and all(type(v) is float for v in value)
        else:
            assert type(value) is float, key
    json.dumps(report, allow_nan=False)


def test_parts_are_ordered_by_area_then_bounds():
    # Two equal squares: the tie is broken by bounds, whatever the input order.
    a, b, big = shapely.box(20, 0, 23, 3), shapely.box(0, 10, 3, 13), shapely.box(0, 0, 8, 8)
    for order in ([a, b, big], [big, b, a], [b, big, a]):
        parts, _ = clean(shapely.MultiPolygon(order), OPENING, MIN_ISLAND)
        assert [p.bounds for p in parts] == [
            pytest.approx(big.bounds), pytest.approx(b.bounds), pytest.approx(a.bounds)]
    first = clean(shapely.MultiPolygon([a, b, big]), OPENING, MIN_ISLAND)
    again = clean(shapely.MultiPolygon([a, b, big]), OPENING, MIN_ISLAND)
    assert [p.wkb for p in first[0]] == [p.wkb for p in again[0]]
    assert first[1] == again[1]


def test_geometry_collection_is_read_recursively_and_lines_are_counted():
    nested = shapely.GeometryCollection([
        shapely.MultiPolygon([shapely.box(0, 0, 5, 5)]),
        shapely.GeometryCollection([shapely.box(10, 0, 15, 5), shapely.LineString([(0, 9),
                                                                                   (9, 9)])]),
        shapely.Point(20, 20)])
    parts, report = clean(nested, OPENING, MIN_ISLAND)
    assert len(parts) == 2
    assert report["ignored_non_polygonal"] == 2


def test_nothing_left_raises_with_removed_area():
    with pytest.raises(FlatError, match=r"nothing printable remains after cleaning.*0\.25"):
        clean(shapely.box(0, 0, 0.5, 0.5).buffer(0), 2.0, MIN_ISLAND)


@pytest.mark.parametrize("opening, island", [(-0.1, 0.64), (math.nan, 0.64), (0.4, -1.0),
                                             (0.4, math.inf)])
def test_bad_cleaning_parameters_raise(opening, island):
    with pytest.raises(FlatError):
        clean(shapely.box(0, 0, 5, 5), opening, island)

import io
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import shapely
import trimesh
from hypothesis import given, settings
from hypothesis import strategies as st
from selection_fixtures import RED, WHITE, roadie_like

from tdmg.checks import F1_CHECK_IDS, CheckResult, merge_exact, topology_checks, verdict
from tdmg.flat import (
    DROPPED_LISTED,
    FLAT_REQUIRED_CHECKS,
    HAUSDORFF_STEP_PX,
    QUAD_SEGS,
    THIN_LISTED,
    FlatError,
    body_count_check,
    build_volume_check,
    clean,
    extrude,
    flat_checks,
    mask_outline,
    slicer_check,
    target_width_check,
    thin_region_check,
    thin_regions,
    to_model,
    triangle_check,
)
from tdmg.flat import _sampled_hausdorff as sampled_hausdorff
from tdmg.profiles import load_printer
from tdmg.rules import load_rules


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
STEP = 0.01        # Hausdorff sampling step for hand-made geometry, in mm
REPORT_KEYS = {"opening_mm", "min_island_mm2", "area_before_mm2", "area_after_mm2",
               "removed_area_mm2", "boundary_hausdorff_mm", "hausdorff_upper_bound_mm",
               "hausdorff_sample_step_mm",
               "dropped_islands", "vanished_parts", "ignored_non_polygonal"}


def run_clean(geom, opening=OPENING, island=MIN_ISLAND, step=STEP):
    return clean(geom, opening, island, step)


def coords(part) -> set:
    return {tuple(c) for ring in [part.exterior, *part.interiors] for c in ring.coords}


def test_squares_touching_at_a_corner_become_two_parts_without_shared_coordinates():
    touching = shapely.union_all([shapely.box(0, 0, 5, 5), shapely.box(5, 5, 10, 10)])
    assert isinstance(touching, shapely.MultiPolygon)
    parts, report = run_clean(touching)
    assert len(parts) == 2
    assert all(isinstance(p, shapely.Polygon) and p.is_valid for p in parts)
    assert not coords(parts[0]) & coords(parts[1])
    assert parts[0].distance(parts[1]) > 0
    assert report["dropped_islands"] == {"count": 0, "total_area_mm2": 0.0, "largest_mm2": []}


def test_thin_hair_is_removed():
    square = shapely.box(0, 0, 5, 5)
    hair = shapely.box(5, 2.4, 9, 2.6)  # 0.2 mm wide, 4 mm long
    parts, report = run_clean(shapely.union_all([square, hair]))
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
    # The farthest removed points are the hair's tip corners, which are sample points.
    tip = max(parts[0].distance(shapely.Point(9, y)) for y in (2.4, 2.6))
    assert 3.9 < tip < 4.0
    assert report["boundary_hausdorff_mm"] == pytest.approx(tip, abs=1e-9)


def bridged_blobs() -> np.ndarray:
    """Two 40 px squares joined by a 1 x 30 px bar."""
    mask = np.zeros((60, 130), bool)
    mask[10:50, 10:50] = True
    mask[10:50, 80:120] = True
    mask[30, 50:80] = True
    return mask


def test_hausdorff_sees_a_removed_bar_between_vertices():
    outline = mask_outline(bridged_blobs())
    before, transform = to_model(outline, 11.0)  # 110 px wide: 0.1 mm per pixel
    step = HAUSDORFF_STEP_PX * transform["scale_mm_per_px"]
    parts, report = clean(before, OPENING, MIN_ISLAND, step)
    after = shapely.union_all(parts)
    assert len(parts) == 2
    assert shapely.hausdorff_distance(before, after) < 0.2  # GEOS checks vertices only
    dense = shapely.hausdorff_distance(before, after, densify=0.002)
    assert dense > 1.4  # the bar's middle is 1.5 mm from either square
    assert report["hausdorff_sample_step_mm"] == step
    assert report["boundary_hausdorff_mm"] <= dense + 1e-9
    assert report["boundary_hausdorff_mm"] == pytest.approx(dense, abs=step)
    assert report["boundary_hausdorff_mm"] == pytest.approx(1.5, abs=step)
    assert report["hausdorff_upper_bound_mm"] >= dense


def test_sampled_hausdorff_is_symmetric_and_zero_for_equal_regions():
    a, b = shapely.box(0, 0, 4, 4), shapely.box(0, 0, 4, 6)
    assert sampled_hausdorff(a, a, 0.1) == 0.0
    assert sampled_hausdorff(a, b, 0.1) == sampled_hausdorff(b, a, 0.1) == 2.0


def test_upper_bound_covers_a_dropped_island_far_inside_a_hole():
    # Reviewer's counterexample: the farthest removed point is the island's centre, which
    # no boundary sample sees. Boundary value about 9.6, true value about 10.
    centre = shapely.Point(15, 15)
    frame = shapely.box(0, 0, 30, 30).difference(centre.buffer(10, quad_segs=64))
    island = centre.buffer(0.4, quad_segs=64)            # 0.503 mm^2 < MIN_ISLAND
    parts, report = run_clean(shapely.union_all([frame, island]))
    assert len(parts) == 1
    assert report["dropped_islands"]["count"] == 1
    assert report["dropped_islands"]["largest_mm2"][0] == pytest.approx(0.503, abs=0.002)
    true_at_centre = parts[0].distance(centre)
    assert true_at_centre == pytest.approx(9.999, abs=0.002)
    assert report["boundary_hausdorff_mm"] == pytest.approx(9.599, abs=0.002)
    assert report["boundary_hausdorff_mm"] <= true_at_centre
    assert report["hausdorff_upper_bound_mm"] >= true_at_centre


def test_upper_bound_formula():
    square = shapely.box(0, 0, 5, 5)
    hair = shapely.box(5, 2.4, 9, 2.6)
    _, report = run_clean(shapely.union_all([square, hair]))
    chord_error = 0.2 * (1 - math.cos(math.pi / (4 * QUAD_SEGS)))
    assert report["hausdorff_upper_bound_mm"] == pytest.approx(
        report["boundary_hausdorff_mm"] + STEP / 2 + 0.2 + chord_error, abs=1e-12)


def test_specks_below_min_island_are_dropped_and_reported():
    body = shapely.box(0, 0, 5, 5)
    speck = shapely.box(10, 0, 10.7, 0.7)     # 0.49 mm^2: survives opening, below 0.64
    island = shapely.box(10, 3, 11, 4)        # 1 mm^2 before opening
    parts, report = run_clean(shapely.union_all([body, speck, island]))
    assert len(parts) == 2
    assert parts[0].area > parts[1].area
    assert parts[1].within(island)
    expected = speck.buffer(-0.2).buffer(0.2, quad_segs=QUAD_SEGS).area
    dropped = report["dropped_islands"]
    assert dropped["count"] == 1
    assert dropped["largest_mm2"] == [pytest.approx(expected)]
    assert dropped["total_area_mm2"] == pytest.approx(expected)
    assert 0 < expected < MIN_ISLAND
    assert report["vanished_parts"] == {"count": 0, "total_area_mm2": 0.0}


def test_dropped_islands_count_all_and_list_the_largest_first():
    sides = [0.5, 0.7, 0.6, 0.45, 0.55, 0.65, 0.5, 0.6, 0.7, 0.5, 0.62, 0.48]
    specks = [shapely.box(10 * i, 20, 10 * i + side, 20 + side) for i, side in enumerate(sides)]
    _, report = run_clean(shapely.union_all([shapely.box(0, 0, 5, 5), *specks]))
    dropped = report["dropped_islands"]
    opened = [s.buffer(-0.2).buffer(0.2, quad_segs=QUAD_SEGS).area for s in specks]
    assert dropped["count"] == len(sides) > DROPPED_LISTED
    assert dropped["total_area_mm2"] == pytest.approx(sum(opened))
    assert dropped["largest_mm2"] == pytest.approx(sorted(opened, reverse=True)[:DROPPED_LISTED])
    assert len(dropped["largest_mm2"]) == DROPPED_LISTED


def test_parts_erased_by_the_opening_are_reported_as_vanished():
    mask = np.zeros((100, 100), bool)
    mask[10:50, 10:50] = True                  # 4 x 4 mm body at 0.1 mm per pixel
    specks = [(y, x) for y in range(60, 100, 4) for x in range(60, 100, 8)]
    for y, x in specks:
        mask[y, x] = True                      # 0.1 mm specks vanish in a 0.4 mm opening
    mask[99, 0] = mask[0, 99] = True           # two more; they set the width to 100 px
    model, transform = to_model(mask_outline(mask), 10.0)
    assert transform["scale_mm_per_px"] == pytest.approx(0.1)
    parts, report = clean(model, OPENING, MIN_ISLAND, 0.025)
    assert len(parts) == 1
    assert report["vanished_parts"]["count"] == len(specks) + 2
    assert report["vanished_parts"]["total_area_mm2"] == pytest.approx(
        (len(specks) + 2) * 0.01)
    assert report["dropped_islands"]["count"] == 0


def test_report_has_a_fixed_key_set_and_plain_types():
    for geom in (shapely.box(0, 0, 5, 5),
                 shapely.union_all([shapely.box(0, 0, 5, 5), shapely.box(10, 0, 10.7, 0.7)])):
        _, report = run_clean(geom)
        assert set(report) == REPORT_KEYS
        assert set(report["dropped_islands"]) == {"count", "total_area_mm2", "largest_mm2"}
        assert set(report["vanished_parts"]) == {"count", "total_area_mm2"}
        for key in REPORT_KEYS - {"dropped_islands", "vanished_parts", "ignored_non_polygonal"}:
            assert type(report[key]) is float, key
        assert type(report["ignored_non_polygonal"]) is int
        for group in ("dropped_islands", "vanished_parts"):
            assert type(report[group]["count"]) is int
            assert type(report[group]["total_area_mm2"]) is float
        assert all(type(v) is float for v in report["dropped_islands"]["largest_mm2"])
        json.dumps(report, allow_nan=False)
        assert report["ignored_non_polygonal"] == 0


def test_parts_are_ordered_by_area_then_bounds():
    # Two equal squares: the tie is broken by bounds, whatever the input order.
    a, b, big = shapely.box(20, 0, 23, 3), shapely.box(0, 10, 3, 13), shapely.box(0, 0, 8, 8)
    for order in ([a, b, big], [big, b, a], [b, big, a]):
        parts, _ = run_clean(shapely.MultiPolygon(order))
        assert [p.bounds for p in parts] == [
            pytest.approx(big.bounds), pytest.approx(b.bounds), pytest.approx(a.bounds)]
    first = run_clean(shapely.MultiPolygon([a, b, big]))
    again = run_clean(shapely.MultiPolygon([a, b, big]))
    assert [p.wkb for p in first[0]] == [p.wkb for p in again[0]]
    assert first[1] == again[1]


def test_invalid_input_is_unioned_first():
    overlapping = shapely.MultiPolygon([shapely.box(0, 0, 5, 5), shapely.box(3, 0, 8, 5)])
    assert not overlapping.is_valid
    parts, report = run_clean(overlapping)
    assert len(parts) == 1
    assert report["area_before_mm2"] == pytest.approx(40.0)


def test_geometry_collection_is_read_recursively_and_lines_are_counted():
    nested = shapely.GeometryCollection([
        shapely.MultiPolygon([shapely.box(0, 0, 5, 5)]),
        shapely.GeometryCollection([shapely.box(10, 0, 15, 5), shapely.LineString([(0, 9),
                                                                                   (9, 9)])]),
        shapely.Point(20, 20)])
    parts, report = run_clean(nested)
    assert len(parts) == 2
    assert report["ignored_non_polygonal"] == 2


def test_nothing_left_raises_with_removed_area():
    with pytest.raises(FlatError, match=r"nothing printable remains after cleaning.*0\.25"):
        run_clean(shapely.box(0, 0, 0.5, 0.5).buffer(0), opening=2.0)


@pytest.mark.parametrize("opening, island, step", [
    (0.0, 0.64, STEP), (-0.1, 0.64, STEP), (math.nan, 0.64, STEP), (0.4, -1.0, STEP),
    (0.4, math.inf, STEP), (0.4, 0.64, 0.0), (0.4, 0.64, -1.0), (0.4, 0.64, math.nan)])
def test_bad_cleaning_parameters_raise(opening, island, step):
    with pytest.raises(FlatError):
        clean(shapely.box(0, 0, 5, 5), opening, island, step)


# --- Task 5: extrusion --------------------------------------------------------------


def statuses(mesh) -> dict[str, str]:
    return {r.id: r.status for r in topology_checks(merge_exact(mesh))}


def bodies(mesh) -> list:
    return mesh.split(only_watertight=False, repair=False)


@settings(max_examples=60, deadline=None)
@given(x=st.floats(-50, 50), y=st.floats(-50, 50), w=st.floats(1, 80), h=st.floats(1, 80),
       fx=st.floats(0.1, 0.8), fy=st.floats(0.1, 0.8), fw=st.floats(0.05, 0.8),
       fh=st.floats(0.05, 0.8), thickness=st.floats(0.2, 10))
def test_rectangle_with_hole_volume_and_topology(x, y, w, h, fx, fy, fw, fh, thickness):
    hx, hy = x + fx * w, y + fy * h
    hw, hh = min(fw, 0.95 - fx) * w, min(fh, 0.95 - fy) * h
    shell = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    hole = [(hx, hy), (hx + hw, hy), (hx + hw, hy + hh), (hx, hy + hh)]
    part = shapely.Polygon(shell, [hole])
    assert part.is_valid
    mesh = extrude([part], thickness)
    assert mesh.vertices.dtype == np.float64
    expected = part.area * thickness
    assert abs(mesh.volume - expected) <= 1e-6 * expected
    assert set(statuses(mesh).values()) == {"PASS"}


def test_hole_orientation_does_not_matter():
    shell = [(0, 0), (0, 10), (10, 10), (10, 0)]       # clockwise exterior
    hole = [(2, 2), (8, 2), (8, 8), (2, 8)]            # counter-clockwise hole
    mesh = extrude([shapely.Polygon(shell, [hole])], 2.0)
    assert mesh.volume == pytest.approx((100 - 36) * 2.0, rel=1e-12)
    assert set(statuses(mesh).values()) == {"PASS"}


def test_two_parts_give_two_bodies():
    parts = [shapely.box(0, 0, 5, 5), shapely.box(7, 0, 9, 3)]
    mesh = extrude(parts, 1.5)
    found = bodies(mesh)
    assert len(found) == 2
    assert sorted(b.volume for b in found) == pytest.approx([6 * 1.5, 25 * 1.5])
    assert set(statuses(mesh).values()) == {"PASS"}


def test_extrusion_spans_zero_to_thickness():
    mesh = extrude([shapely.box(1, 2, 4, 6)], 3.0)
    assert mesh.bounds.tolist() == [[1.0, 2.0, 0.0], [4.0, 6.0, 3.0]]


def test_repeated_extrusion_is_identical():
    parts, _ = clean(shapely.union_all([shapely.box(0, 0, 5, 5), shapely.Point(8, 2).buffer(
        1.5)]), OPENING, MIN_ISLAND, STEP)
    first, second = extrude(parts, 2.0), extrude(parts, 2.0)
    assert np.array_equal(first.vertices, second.vertices)
    assert np.array_equal(first.faces, second.faces)


def test_empty_parts_raise():
    with pytest.raises(FlatError):
        extrude([], 2.0)
    with pytest.raises(FlatError):
        extrude([shapely.Polygon()], 2.0)


@pytest.mark.parametrize("thickness", [0.0, -1.0, math.inf, math.nan])
def test_bad_thickness_raises(thickness):
    with pytest.raises(FlatError, match="thickness"):
        extrude([shapely.box(0, 0, 1, 1)], thickness)


def bird_mask() -> np.ndarray:
    img = roadie_like()
    rgb, opaque = img[..., :3], img[..., 3] == 255
    return opaque & ((rgb == RED).all(axis=2) | (rgb == WHITE).all(axis=2))


def test_full_chain_on_a_bird_like_mask_passes_f1_after_stl_round_trip():
    mask = bird_mask()
    outline = mask_outline(mask)
    assert outline.area == int(mask.sum())
    model, transform = to_model(outline, 60.0)
    assert transform["scale_mm_per_px"] == 60.0 / transform["mask_width_px"]
    step = HAUSDORFF_STEP_PX * transform["scale_mm_per_px"]
    parts, report = clean(model, OPENING, MIN_ISLAND, step)
    assert report["removed_area_mm2"] > 0          # the 1 px ring cannot survive opening
    mesh = extrude(parts, 3.0)
    assert set(statuses(mesh).values()) == {"PASS"}
    assert mesh.volume == pytest.approx(report["area_after_mm2"] * 3.0, rel=1e-9)
    assert len(bodies(mesh)) == len(parts) >= 3      # body and two separate shoes
    written = trimesh.load(io.BytesIO(mesh.export(file_type="stl")), file_type="stl",
                           process=False)
    assert set(statuses(written).values()) == {"PASS"}


# --- Review fixes: mask input, outline simplification, determinism ------------------


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16, np.int32])
def test_integer_masks_use_0_and_255(dtype):
    mask = np.zeros((6, 7), dtype)
    mask[1:4, 2:6] = 255
    assert mask_outline(mask).equals(mask_outline(mask == 255))


@pytest.mark.parametrize("values", [(0, 1), (0, 128), (0, 254)])
def test_integer_masks_with_other_values_raise(values):
    mask = np.full((4, 4), values[0], np.uint8)
    mask[1:3, 1:3] = values[1]
    with pytest.raises(FlatError, match="0 and 255"):
        mask_outline(mask)


@pytest.mark.parametrize("mask", [np.ones((3, 3), np.float64), np.full((3, 3), np.nan),
                                  np.ones((3, 3), np.float32)])
def test_float_masks_raise(mask):
    with pytest.raises(FlatError, match="bool or integer"):
        mask_outline(mask)


def raw_union(mask: np.ndarray):
    boxes = []
    for y, row in enumerate(mask):
        edges = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
        boxes += [shapely.box(a, y, e, y + 1)
                  for a, e in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1),
                                  strict=True)]
    return shapely.union_all(boxes)


def collinear_vertices(geom) -> int:
    count = 0
    for part in polygons(geom):
        for ring in (part.exterior, *part.interiors):
            xy = np.asarray(ring.coords)[:-1]
            a, b, c = xy, np.roll(xy, -1, axis=0), np.roll(xy, -2, axis=0)
            cross = (b - a)[:, 0] * (c - b)[:, 1] - (b - a)[:, 1] * (c - b)[:, 0]
            count += int(np.count_nonzero(cross == 0))
    return count


@pytest.mark.parametrize("seed", range(5))
def test_outline_drops_collinear_vertices_and_keeps_the_geometry(seed):
    mask = np.random.default_rng(seed).random((40, 57)) < 0.45
    mask[5:30, 5:40] = True  # long straight runs give collinear vertices in the union
    outline, union = mask_outline(mask), raw_union(mask)
    assert collinear_vertices(union) > 0
    assert collinear_vertices(outline) == 0
    assert outline.is_valid
    assert outline.area == union.area == int(mask.sum())
    assert outline.symmetric_difference(union).area == 0
    assert shapely.get_num_coordinates(outline) < shapely.get_num_coordinates(union)


def test_square_mask_outline_has_four_corners():
    mask = np.zeros((10, 10), bool)
    mask[1:9, 2:7] = True
    outline = mask_outline(mask)
    assert isinstance(outline, shapely.Polygon)
    assert len(outline.exterior.coords) == 5


CHILD = """
import hashlib, json, sys
import numpy as np
sys.path.insert(0, sys.argv[1])
from selection_fixtures import RED, WHITE, roadie_like
from tdmg.flat import HAUSDORFF_STEP_PX, clean, extrude, mask_outline, to_model
img = roadie_like()
rgb = img[..., :3]
mask = (img[..., 3] == 255) & ((rgb == RED).all(axis=2) | (rgb == WHITE).all(axis=2))
model, transform = to_model(mask_outline(mask), 60.0)
parts, report = clean(model, 0.4, 0.64, HAUSDORFF_STEP_PX * transform["scale_mm_per_px"])
mesh = extrude(parts, 3.0)
arrays = np.ascontiguousarray(mesh.vertices).tobytes() + np.ascontiguousarray(
    mesh.faces).tobytes()
record = json.dumps([transform, report], sort_keys=True, allow_nan=False).encode()
print(hashlib.sha256(arrays).hexdigest(), hashlib.sha256(record).hexdigest())
"""


def test_two_fresh_processes_give_identical_mesh_and_report():
    tests_dir = str(Path(__file__).parent)
    outputs = []
    for hash_seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        done = subprocess.run([sys.executable, "-c", CHILD, tests_dir], env=env,
                              capture_output=True, text=True, check=True, timeout=300)
        outputs.append(done.stdout.split())
    assert len(outputs[0]) == 2
    assert outputs[0] == outputs[1]


# --- Task 6: thin regions and the F2-F6 checks ------------------------------------


def a1():
    return load_printer("bambu-a1")


def with_default(rule_id: str, value) -> dict:
    """The rules registry with one rule's default replaced, for testing a check's FAIL path."""
    rules = load_rules()
    rules[rule_id] = rules[rule_id].model_copy(update={"default": value})
    return rules


def by_id(results) -> dict:
    return {r.id: r for r in results}


def test_thin_regions_find_a_thin_strip_and_report_its_centroid():
    # A 10 x 10 mm square with a 0.5 x 6 mm strip on its right: the strip is below 0.9 mm.
    square = shapely.box(0, 0, 10, 10)
    strip = shapely.box(10, 2, 16, 2.5)
    found = thin_regions([shapely.union_all([square, strip])], 0.9)
    assert found["min_width_mm"] == 0.9
    biggest = found["largest"][0]
    assert biggest["area_mm2"] == pytest.approx(3.0, abs=0.1)
    assert biggest["centroid_mm"] == pytest.approx([13.0, 2.25], abs=0.05)
    assert found["area_mm2"] >= biggest["area_mm2"]
    assert found["pieces"] >= 1
    assert len(found["largest"]) <= THIN_LISTED
    json.dumps(found, allow_nan=False)


def test_thin_regions_of_a_wide_square_are_only_its_corners():
    # Opening rounds convex corners. With a true circle each loses r^2 (1 - pi/4), r = 0.45
    # mm. The buffer's quarter arc is QUAD_SEGS chords inscribed in the circle, whose area is
    # QUAD_SEGS * r^2 sin(pi / (2 QUAD_SEGS)) / 2, so each corner loses slightly more.
    found = thin_regions([shapely.box(0, 0, 10, 10)], 0.9)
    r = 0.45
    corner = r ** 2 * (1 - QUAD_SEGS * math.sin(math.pi / (2 * QUAD_SEGS)) / 2)
    assert corner > r ** 2 * (1 - math.pi / 4)
    assert found["area_mm2"] == pytest.approx(4 * corner, rel=1e-6)
    assert found["pieces"] == 4
    assert all(e["area_mm2"] == pytest.approx(corner, abs=1e-3) for e in found["largest"])


def test_thin_regions_list_at_most_the_largest_five_largest_first():
    strips = [shapely.box(3 * i, 0, 3 * i + 0.5, 1 + i) for i in range(7)]
    found = thin_regions(strips, 0.9)
    areas = [e["area_mm2"] for e in found["largest"]]
    assert len(areas) == THIN_LISTED == 5
    assert areas == sorted(areas, reverse=True)
    assert areas[0] == pytest.approx(0.5 * 7, rel=1e-6)
    assert found["pieces"] == 7


def test_f3_thin_regions_is_unknown_with_the_measurement():
    parts = [shapely.union_all([shapely.box(0, 0, 10, 10), shapely.box(10, 2, 16, 2.5)])]
    check = thin_region_check(parts, load_rules())
    assert check.id == "F3.thin_regions"
    assert check.status == "UNKNOWN"
    assert check.rule == "fdm.wall.min_thickness"
    assert check.threshold == load_rules()["fdm.wall.min_thickness"].default == 0.9
    assert check.measured == thin_regions(parts, 0.9)
    assert check.note == ("tapered tips always appear; pass/fail policy pending research on "
                          "slicer handling of narrow features")


def test_f2_fits_build_volume_passes_and_fails():
    small = extrude([shapely.box(0, 0, 60, 40)], 3.0)
    check = build_volume_check(merge_exact(small), a1())
    assert check.status == "PASS"
    assert check.measured == [60.0, 40.0, 3.0]
    assert check.threshold == [256.0, 256.0, 256.0]
    assert check.rule is None
    assert "bambu-a1" in check.note and "build_volume_mm" in check.note
    wide = extrude([shapely.box(0, 0, 300, 40)], 3.0)
    assert build_volume_check(merge_exact(wide), a1()).status == "FAIL"


def test_f2_fits_build_volume_checks_every_axis():
    tall = raw_box(10.0, 10.0, 257.0)
    assert build_volume_check(tall, a1()).status == "FAIL"
    exact = raw_box(256.0, 256.0, 256.0)
    assert build_volume_check(exact, a1()).status == "PASS"


def raw_box(x: float, y: float, z: float) -> trimesh.Trimesh:
    box = trimesh.creation.box(extents=(x, y, z))
    return trimesh.Trimesh(box.vertices, box.faces, process=False)


def test_f2_target_width_passes_and_reports_final_extents():
    mask = np.zeros((10, 20), bool)
    mask[2:8, 3:13] = True
    model, transform = to_model(mask_outline(mask), 40.0)
    mesh = merge_exact(extrude(polygons(model), 2.0))
    check = target_width_check(transform, 40.0, mesh)
    assert check.status == "PASS"
    assert check.measured == pytest.approx(40.0, rel=1e-12)
    assert check.threshold == 40.0
    assert check.rule is None
    assert "40 x 24 x 2 mm" in check.note
    assert "cleaning removes material" in check.note


def test_f2_target_width_fails_on_a_wrong_scale():
    mask = np.zeros((10, 20), bool)
    mask[2:8, 3:13] = True
    model, transform = to_model(mask_outline(mask), 40.0)
    mesh = merge_exact(extrude(polygons(model), 2.0))
    assert target_width_check(transform, 41.0, mesh).status == "FAIL"
    off = {**transform, "scale_mm_per_px": transform["scale_mm_per_px"] * (1 + 1e-6)}
    assert target_width_check(off, 40.0, mesh).status == "FAIL"


def test_f4_body_count_pass_for_one_and_unknown_for_more():
    one = body_count_check(merge_exact(extrude([shapely.box(0, 0, 5, 5)], 1.0)))
    assert (one.id, one.status, one.measured, one.threshold) == ("F4.body_count", "PASS", 1, 1)
    two = body_count_check(merge_exact(extrude(
        [shapely.box(0, 0, 5, 5), shapely.box(7, 0, 9, 3)], 1.0)))
    assert (two.status, two.measured) == ("UNKNOWN", 2)
    assert two.note == "separate pieces print loose; join them or accept"


def test_f5_triangles_pass_and_fail_with_a_tiny_limit():
    mesh = merge_exact(extrude([shapely.box(0, 0, 5, 5)], 1.0))
    check = triangle_check(mesh, load_rules())
    assert check.status == "PASS"
    assert check.measured == len(mesh.faces)
    assert check.rule == "slicer.orca.max_triangles_per_plate"
    assert check.threshold == 1_000_000
    tiny = triangle_check(mesh, with_default("slicer.orca.max_triangles_per_plate", 4))
    assert (tiny.status, tiny.threshold) == ("FAIL", 4)
    at_limit = with_default("slicer.orca.max_triangles_per_plate", len(mesh.faces))
    assert triangle_check(mesh, at_limit).status == "PASS"


def test_f6_slicer_is_always_unknown():
    check = slicer_check()
    assert (check.id, check.status, check.note) == ("F6.slicer", "UNKNOWN",
                                                   "no slicer integration yet")


def test_required_checks_are_f1_to_f6():
    assert FLAT_REQUIRED_CHECKS == F1_CHECK_IDS | {
        "F2.fits_build_volume", "F2.target_width", "F3.thin_regions", "F4.body_count",
        "F5.triangles", "F6.slicer"}
    assert {r.id for r in topology_checks(merge_exact(extrude([shapely.box(0, 0, 1, 1)],
                                                              1.0)))} == F1_CHECK_IDS


def test_verdict_is_not_certified_even_for_a_perfect_part():
    mask = np.zeros((10, 20), bool)
    mask[2:8, 3:13] = True
    model, transform = to_model(mask_outline(mask), 40.0)
    parts = polygons(model)
    mesh = merge_exact(extrude(parts, 2.0))
    results = topology_checks(mesh) + flat_checks(mesh, parts, transform, 40.0, a1(),
                                                  load_rules())
    found = by_id(results)
    assert set(found) == FLAT_REQUIRED_CHECKS
    assert len(results) == len(found)
    unknown = {i for i, r in found.items() if r.status != "PASS"}
    assert unknown == {"F3.thin_regions", "F6.slicer"}
    assert verdict(results, FLAT_REQUIRED_CHECKS) == "NOT CERTIFIED"
    # Only the two pending checks hold it back.
    passed = [r if r.status == "PASS" else CheckResult(r.id, "PASS", r.measured, r.threshold,
                                                       r.rule) for r in results]
    assert verdict(passed, FLAT_REQUIRED_CHECKS) == "PRINTABLE"

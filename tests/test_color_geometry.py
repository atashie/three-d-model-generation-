import itertools
import json
import math
import subprocess
import sys

import numpy as np
import pytest
import shapely
from shapely import affinity
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

from tdmg import color_geometry
from tdmg.color_geometry import (
    STATUSES,
    ColorGeometryError,
    ColorRegions,
    color_regions,
    fine_regions_px,
)
from tdmg.flat import QUAD_SEGS, apply_transform, mask_outline, thin_regions, to_model

# Thin-part width for synthetic maps at 1 mm per pixel. A test input, not a rule.
THIN = 0.5


def image_box(width_px, height_px, width_mm=None):
    """S and the transform for the whole image box; width_mm defaults to 1 mm per px."""
    return to_model(shapely.box(0, 0, width_px, height_px),
                    width_px if width_mm is None else width_mm)


def regions(fine, *, s=1, silhouette=None, transform=None, n_colors=None, base_index=0,
            thin_width_mm=THIN):
    fine = np.asarray(fine, dtype=np.uint8)
    full, t = image_box(fine.shape[1] / s, fine.shape[0] / s)
    return color_regions(
        fine, s, t if transform is None else transform,
        full if silhouette is None else silhouette,
        n_colors=int(fine.max()) + 1 if n_colors is None else n_colors,
        base_index=base_index, thin_width_mm=thin_width_mm)


def pieces(result: ColorRegions) -> list[Polygon]:
    return [p for polys in result.inlays.values() for p in polys] + list(result.base_top)


def entry(result, index):
    (found,) = [e for e in result.report["colors"] if e["index"] == index]
    return found


def clipped_region(fine, s, transform, silhouette, c):
    return shapely.intersection(apply_transform(fine_regions_px(fine, s)[c], transform),
                                silhouette)


# --- partitions ----------------------------------------------------------------------


def test_two_flat_colors_give_exact_halves():
    fine = np.zeros((4, 4), np.uint8)
    fine[:, 2:] = 1
    result = regions(fine)
    right, left = shapely.box(2, 0, 4, 4), shapely.box(0, 0, 2, 4)
    (inlay,) = result.inlays[1]
    (base,) = result.base_top
    assert inlay.area == right.area and shapely.symmetric_difference(inlay, right).area == 0
    assert base.area == left.area and shapely.symmetric_difference(base, left).area == 0
    assert shapely.intersection(inlay, base).area == 0.0
    assert 0 not in result.inlays
    assert entry(result, 1) == {"index": 1, "status": "inlay", "area_mm2": 8.0, "parts": 1,
                                "thin": thin_regions([inlay], THIN)}
    assert result.report["base"] == {"index": 0, "present_in_fine": True, "area_mm2": 8.0}
    assert result.warnings == []


def assert_partition(result, silhouette):
    parts = pieces(result)
    for a, b in itertools.combinations(parts, 2):
        assert shapely.intersection(a, b).area == 0.0
    union = shapely.union_all(parts)
    assert shapely.symmetric_difference(union, silhouette).area < 1e-9


def test_three_color_t_junction_partitions_s():
    fine = np.zeros((8, 8), np.uint8)
    fine[4:, :4] = 1
    fine[4:, 4:] = 2
    result = regions(fine)
    assert sorted(result.inlays) == [1, 2]
    assert_partition(result, image_box(8, 8)[0])


def test_four_color_checker_corner_partitions_s():
    fine = np.kron(np.array([[0, 1], [2, 3]]), np.ones((4, 4))).astype(np.uint8)
    result = regions(fine, base_index=1)
    assert sorted(result.inlays) == [0, 2, 3]
    assert result.report["base"]["index"] == 1
    assert [e["index"] for e in result.report["colors"]] == [0, 2, 3]
    assert_partition(result, image_box(8, 8)[0])


def test_partition_at_supersample_two_and_a_real_scale():
    fine = np.zeros((12, 16), np.uint8)
    fine[3:9, 2:7] = 1
    fine[5:12, 8:14] = 2
    full, transform = image_box(8, 6, width_mm=37.3)
    silhouette = shapely.Point(18, 14).buffer(12, quad_segs=QUAD_SEGS).intersection(full)
    result = color_regions(fine, 2, transform, silhouette, n_colors=3, base_index=0,
                           thin_width_mm=0.4)
    assert_partition(result, silhouette)
    assert math.isclose(result.report["silhouette_area_mm2"], silhouette.area)


def test_inlays_are_the_clipped_fine_regions():
    fine = np.kron(np.array([[0, 1, 2], [2, 3, 1]]), np.ones((5, 5))).astype(np.uint8)
    full, transform = image_box(15, 10, width_mm=41.9)
    silhouette = shapely.Point(20, 14).buffer(13, quad_segs=QUAD_SEGS).intersection(full)
    result = color_regions(fine, 1, transform, silhouette, n_colors=4, base_index=2,
                           thin_width_mm=0.4)
    for c in (0, 1, 3):
        own = clipped_region(fine, 1, transform, silhouette, c)
        assert shapely.symmetric_difference(shapely.union_all(result.inlays[c]), own).area \
            == 0.0
        assert entry(result, c)["area_mm2"] == pytest.approx(own.area, rel=1e-12)


# --- thin parts are kept and reported --------------------------------------------------------


def outline_strip_case():
    fine = np.zeros((10, 20), np.uint8)
    fine[0, 0:8] = 1        # top row: model y 9..10, x 0..8
    fine[4:10, 10:20] = 1   # block: model y 0..6, x 10..20
    silhouette = shapely.box(0.8, 0.8, 19.2, 9.2)
    return fine, silhouette


def test_strip_along_the_outline_is_kept_and_reported_thin():
    fine, silhouette = outline_strip_case()
    result = regions(fine, silhouette=silhouette)
    strip = shapely.box(0.8, 9.0, 8.0, 9.2)        # 0.2 mm wide, below THIN
    block = shapely.box(10.0, 0.8, 19.2, 6.0)
    r = THIN / 2
    opened_block = block.buffer(-r, quad_segs=QUAD_SEGS).buffer(r, quad_segs=QUAD_SEGS)
    report = entry(result, 1)
    assert report["status"] == "inlay" and report["parts"] == 2
    assert math.isclose(report["area_mm2"], strip.area + block.area, rel_tol=1e-12)
    kept_block, kept_strip = result.inlays[1]
    assert shapely.symmetric_difference(kept_block, block).area == 0.0
    assert shapely.symmetric_difference(kept_strip, strip).area == 0.0
    corner_loss = block.area - opened_block.area
    assert abs(report["thin"]["area_mm2"] - (strip.area + corner_loss)) < 1e-6
    assert report["thin"] == thin_regions(result.inlays[1], THIN)
    assert shapely.intersection(strip, shapely.union_all(result.base_top)).area == 0.0
    assert result.warnings == []
    assert_partition(result, silhouette)


def test_thin_line_color_is_an_inlay_reported_thin():
    fine = np.zeros((10, 10), np.uint8)
    fine[:, 4] = 1
    result = regions(fine, thin_width_mm=1.5)
    report = entry(result, 1)
    assert report["status"] == "inlay" and report["parts"] == 1
    assert report["area_mm2"] == 10.0
    assert math.isclose(report["thin"]["area_mm2"], 10.0, rel_tol=1e-12)
    assert result.warnings == []
    assert result.report["base_thin"] == thin_regions(result.base_top, 1.5)
    assert math.isclose(result.report["base"]["area_mm2"], 90.0, rel_tol=1e-12)


def test_speck_is_kept():
    fine = np.zeros((10, 10), np.uint8)
    fine[3:6, 3:6] = 1
    result = regions(fine, thin_width_mm=1.0)
    report = entry(result, 1)
    assert report["status"] == "inlay" and report["parts"] == 1
    assert report["area_mm2"] == 9.0
    (base,) = result.base_top
    assert len(base.interiors) == 1


# --- statuses and warnings ------------------------------------------------------------------


def test_color_outside_the_silhouette():
    fine = np.zeros((10, 10), np.uint8)
    fine[0, :] = 2       # model y 9..10
    fine[5:, :] = 1
    silhouette = shapely.box(0, 0, 10, 8)
    result = regions(fine, silhouette=silhouette)
    report = entry(result, 2)
    assert report == {"index": 2, "status": "outside_silhouette", "area_mm2": 0.0,
                      "parts": 0, "thin": thin_regions([], THIN)}
    assert 2 not in result.inlays and 1 in result.inlays
    (warning,) = result.warnings
    assert warning.startswith("color 2: outside_silhouette:")
    assert warning.endswith("; 2 filaments remain")


def test_color_sharing_only_an_edge_with_s_is_outside():
    fine = np.zeros((10, 10), np.uint8)
    fine[:, 0:2] = 1                         # model x 0..2
    silhouette = shapely.box(2, 0, 10, 10)
    region = apply_transform(fine_regions_px(fine, 1)[1], image_box(10, 10)[1])
    assert shapely.intersection(region, silhouette).geom_type == "LineString"
    result = regions(fine, silhouette=silhouette)
    assert entry(result, 1)["status"] == "outside_silhouette"
    assert entry(result, 1)["area_mm2"] == 0.0
    assert 1 not in result.inlays


def test_overlap_plus_touching_edge_keeps_only_the_polygon():
    fine = np.zeros((10, 10), np.uint8)
    fine[0:5, 0:2] = 1                       # model x 0..2, y 5..10: touches S at x = 2
    fine[5:10, 5:8] = 1                      # model x 5..8, y 0..5: inside S
    silhouette = shapely.box(2, 0, 10, 10)
    region = apply_transform(fine_regions_px(fine, 1)[1], image_box(10, 10)[1])
    raw = shapely.intersection(region, silhouette)
    assert isinstance(raw, GeometryCollection)
    assert {g.geom_type for g in raw.geoms} == {"Polygon", "LineString"}
    result = regions(fine, silhouette=silhouette)
    (inlay,) = result.inlays[1]
    assert inlay.area == 15.0
    assert entry(result, 1)["parts"] == 1 and entry(result, 1)["area_mm2"] == 15.0
    assert_partition(result, silhouette)


def test_absent_palette_index_vanished_in_fine():
    fine = np.zeros((6, 6), np.uint8)
    fine[:, 3:] = 1
    result = regions(fine, n_colors=4)
    assert [e["index"] for e in result.report["colors"]] == [1, 2, 3]
    for index in (2, 3):
        assert entry(result, index) == {"index": index, "status": "vanished_in_fine",
                                        "area_mm2": 0.0, "parts": 0,
                                        "thin": thin_regions([], THIN)}
    assert [w.split(":")[0] for w in result.warnings] == ["color 2", "color 3"]
    assert all(w.endswith("; 2 filaments remain") for w in result.warnings)


def test_warnings_give_the_filament_count_left():
    fine = np.kron(np.array([[0, 1], [2, 2]]), np.ones((5, 5))).astype(np.uint8)
    fine[0, 0] = 3
    silhouette = shapely.box(0, 0, 10, 9)    # leaves out row 0, so color 3 is outside
    result = regions(fine, n_colors=5, silhouette=silhouette)
    assert sorted(result.inlays) == [1, 2]
    assert [w.split(":")[:2] for w in result.warnings] == [
        ["color 3", " outside_silhouette"], ["color 4", " vanished_in_fine"]]
    assert all(w.endswith("; 3 filaments remain") for w in result.warnings)


def test_single_filament_wording():
    result = regions(np.zeros((5, 5), np.uint8), n_colors=2)
    (warning,) = result.warnings
    assert warning.endswith("; 1 filament remains")


def test_absent_base_is_recorded_and_warned():
    fine = np.zeros((6, 6), np.uint8) + 1
    fine[:, 3:] = 2
    result = regions(fine, n_colors=3, base_index=0)
    assert result.report["base"] == {"index": 0, "present_in_fine": False, "area_mm2": 0.0}
    assert result.base_top == []
    (warning,) = result.warnings
    assert warning.startswith("base color 0: not in the fine label map")
    assert warning.endswith("; 3 filaments remain")


def test_base_color_is_not_vectorized(monkeypatch):
    fine = np.kron(np.array([[0, 1], [2, 0]]), np.ones((4, 4))).astype(np.uint8)
    seen = []
    real = color_geometry.mask_outline

    def spy(mask):
        seen.append(np.asarray(mask).copy())
        return real(mask)

    monkeypatch.setattr(color_geometry, "mask_outline", spy)
    result = regions(fine, base_index=0)
    assert len(seen) == 2
    assert not any(np.array_equal(m, fine == 0) for m in seen)
    assert result.report["base"]["present_in_fine"] is True


# --- containment, report form, determinism -------------------------------------------------


# Containment tolerance for S with oblique edges: a few ulps of GEOS's float64
# intersection arithmetic. Measured worst with the current code (Shapely 2.2.0, GEOS
# 3.14.1, 2026-11-12 spec re-review): the "circle" case, vertices about
# 0.28 * eps * max|coordinate| off S, with a difference area of 0; "supersample" 0.03 eps.
ULPS = 4


def containment_case(case):
    if case == "strip":
        fine, silhouette = outline_strip_case()
        return fine, 1, image_box(20, 10)[1], silhouette
    if case == "checker":
        fine = np.kron(np.array([[0, 1], [2, 3]]), np.ones((5, 5))).astype(np.uint8)
        full, transform = image_box(10, 10, width_mm=23.7)
        return fine, 1, transform, full.buffer(-1.3, quad_segs=QUAD_SEGS)
    if case == "supersample":
        fine = np.zeros((12, 16), np.uint8)
        fine[3:9, 2:7] = 1
        fine[5:12, 8:14] = 2
        full, transform = image_box(8, 6, width_mm=37.3)
        return fine, 2, transform, shapely.Point(18, 14).buffer(
            12, quad_segs=QUAD_SEGS).intersection(full)
    fine = np.kron(np.array([[0, 1, 2], [2, 3, 1]]), np.ones((5, 5))).astype(np.uint8)
    full, transform = image_box(15, 10, width_mm=41.9)
    return fine, 1, transform, shapely.Point(20, 14).buffer(
        13, quad_segs=QUAD_SEGS).intersection(full)


def inlays_and_clipped(case):
    fine, s, transform, silhouette = containment_case(case)
    result = color_regions(fine, s, transform, silhouette, n_colors=int(fine.max()) + 1,
                           base_index=0, thin_width_mm=0.4)
    assert result.inlays
    for c, polys in result.inlays.items():
        own = clipped_region(fine, s, transform, silhouette, c)
        for p in polys:
            assert isinstance(p, Polygon) and p.is_valid
            yield p, silhouette, own


@pytest.mark.parametrize("case", ["strip", "checker"])
def test_axis_aligned_inlays_lie_exactly_within_s_and_their_clipped_region(case):
    for p, silhouette, own in inlays_and_clipped(case):
        assert shapely.difference(p, silhouette).area == 0.0
        assert shapely.difference(p, own).area == 0.0


@pytest.mark.parametrize("case", ["strip", "checker", "supersample", "circle"])
def test_inlays_lie_within_s_and_their_clipped_region_to_float64_rounding(case):
    eps = np.finfo(float).eps
    for p, silhouette, own in inlays_and_clipped(case):
        xy = shapely.get_coordinates(p)
        dist = ULPS * eps * float(np.abs(xy).max())
        vertices = shapely.points(xy)
        for region in (silhouette, own):
            assert float(shapely.distance(region, vertices).max()) <= dist
            assert shapely.difference(p, region).area <= p.length * dist


@pytest.mark.parametrize("case", ["strip", "checker", "supersample", "circle"])
def test_base_top_is_the_base_colors_own_region_in_s(case):
    fine, s, transform, silhouette = containment_case(case)
    result = color_regions(fine, s, transform, silhouette, n_colors=int(fine.max()) + 1,
                           base_index=0, thin_width_mm=0.4)
    # Built independently of fine_regions_px: the base label's scaled pixel-cell outline.
    own_px = affinity.scale(mask_outline(fine == 0), 1 / s, 1 / s, origin=(0, 0))
    own = shapely.intersection(apply_transform(own_px, transform), silhouette)
    difference = shapely.symmetric_difference(shapely.union_all(result.base_top), own).area
    if case in ("strip", "checker"):
        assert difference == 0.0
    else:
        dist = ULPS * np.finfo(float).eps * float(np.abs(shapely.get_coordinates(own)).max())
        assert difference <= own.length * dist


def test_report_form_and_json_safety():
    fine, silhouette = outline_strip_case()
    fine = fine.copy()
    fine[8:, 0:3] = 2
    result = regions(fine, silhouette=silhouette, n_colors=4)
    report = result.report
    assert set(report) == {"colors", "base", "base_thin", "silhouette_area_mm2"}
    for e in report["colors"]:
        assert set(e) == {"index", "status", "area_mm2", "parts", "thin"}
        assert e["status"] in STATUSES
        assert type(e["area_mm2"]) is float
        for key in ("index", "parts"):
            assert type(e[key]) is int
        assert set(e["thin"]) == {"min_width_mm", "area_mm2", "pieces", "largest"}
    assert set(report["base"]) == {"index", "present_in_fine", "area_mm2"}
    assert type(report["base"]["index"]) is int and type(report["base"]["area_mm2"]) is float
    assert json.loads(json.dumps(report, allow_nan=False)) == report
    assert all(type(k) is int for k in result.inlays)
    assert math.isclose(report["base"]["area_mm2"],
                        sum(p.area for p in result.base_top), rel_tol=1e-12)
    inlay_area = sum(e["area_mm2"] for e in report["colors"])
    assert math.isclose(inlay_area + report["base"]["area_mm2"],
                        report["silhouette_area_mm2"], rel_tol=1e-12)
    for polys in [*result.inlays.values(), result.base_top]:
        keys = [(-p.area, p.bounds) for p in polys]
        assert keys == sorted(keys)


def test_no_inlay_left_gives_s_as_base_top():
    fine = np.zeros((5, 5), np.uint8)
    result = regions(fine, n_colors=2)
    assert result.inlays == {}
    (base,) = result.base_top
    assert base.area == 25.0
    assert entry(result, 1)["status"] == "vanished_in_fine"


def test_multipolygon_silhouette():
    fine = np.zeros((10, 10), np.uint8)
    fine[:, 5:] = 1
    silhouette = MultiPolygon([shapely.box(0, 0, 4, 10), shapely.box(6, 0, 10, 10)])
    result = regions(fine, silhouette=silhouette)
    assert_partition(result, silhouette)


CONSTRUCTION = """
import json
import numpy as np
import shapely
from tdmg.color_geometry import color_regions
from tdmg.flat import QUAD_SEGS, to_model
fine = np.kron(np.array([[0, 1, 2], [2, 3, 1]]), np.ones((5, 5))).astype(np.uint8)
full, transform = to_model(shapely.box(0, 0, 15, 10), 41.9)
silhouette = shapely.Point(20, 14).buffer(13, quad_segs=QUAD_SEGS).intersection(full)
result = color_regions(fine, 1, transform, silhouette, n_colors=4, base_index=2,
                       thin_width_mm=0.4)
lines = [f"{c} {p.wkb_hex}" for c, ps in result.inlays.items() for p in ps]
lines += [f"base {p.wkb_hex}" for p in result.base_top]
lines += [json.dumps(result.report, sort_keys=True), json.dumps(result.warnings)]
"""


def construct() -> list[str]:
    namespace = {}
    exec(CONSTRUCTION, namespace)  # noqa: S102 - our own fixed text, also run in a subprocess
    return namespace["lines"]


def test_repeat_runs_are_identical_in_process_and_across_processes():
    first = construct()
    assert construct() == first
    other = subprocess.run(
        [sys.executable, "-c", CONSTRUCTION + "print('\\n'.join(lines))"],
        capture_output=True, text=True, check=True, timeout=60)
    assert other.stdout.splitlines() == first


# --- refusals ------------------------------------------------------------------------------


def good_args():
    fine = np.zeros((4, 4), np.uint8)
    fine[:, 2:] = 1
    full, transform = image_box(4, 4)
    return {"fine": fine, "supersample": 1, "transform": transform, "silhouette": full,
            "n_colors": 2, "base_index": 0, "thin_width_mm": 0.5}


def call(**changes):
    args = {**good_args(), **changes}
    return color_regions(args.pop("fine"), args.pop("supersample"), args.pop("transform"),
                         args.pop("silhouette"), **args)


def test_good_args_run():
    assert call().report["colors"][0]["status"] == "inlay"


@pytest.mark.parametrize(("changes", "name"), [
    ({"supersample": True}, "supersample"),
    ({"supersample": 0}, "supersample"),
    ({"supersample": 1.0}, "supersample"),
    ({"fine": np.zeros((2, 2, 2), np.uint8)}, "fine"),
    ({"fine": np.zeros((4, 4), np.float64)}, "fine"),
    ({"fine": np.zeros((4, 4), bool)}, "fine"),
    ({"fine": np.zeros((0, 4), np.uint8)}, "fine"),
    ({"fine": np.full((4, 4), -1, np.int8)}, "fine"),
    ({"fine": np.full((4, 4), 2, np.uint8)}, "n_colors"),
    ({"n_colors": 0}, "n_colors"),
    ({"n_colors": True}, "n_colors"),
    ({"n_colors": 2.0}, "n_colors"),
    ({"base_index": 2}, "base_index"),
    ({"base_index": -1}, "base_index"),
    ({"base_index": False}, "base_index"),
    ({"thin_width_mm": 0}, "thin_width_mm"),
    ({"thin_width_mm": -0.4}, "thin_width_mm"),
    ({"thin_width_mm": math.nan}, "thin_width_mm"),
    ({"thin_width_mm": math.inf}, "thin_width_mm"),
    ({"thin_width_mm": True}, "thin_width_mm"),
    ({"thin_width_mm": "0.4"}, "thin_width_mm"),
    ({"silhouette": Polygon()}, "silhouette"),
    ({"silhouette": shapely.LineString([(0, 0), (1, 1)])}, "silhouette"),
    ({"silhouette": shapely.box(0, 0, 0, 4)}, "silhouette"),
    ({"silhouette": Polygon([(0, 0), (4, 4), (4, 0), (0, 4)])}, "silhouette"),
    ({"transform": {"scale_mm_per_px": 0.0, "x0_px": 0.0, "y1_px": 4.0}}, "transform"),
    ({"transform": {"x0_px": 0.0, "y1_px": 4.0}}, "transform"),
    ({"transform": {"scale_mm_per_px": 1.0, "x0_px": False, "y1_px": 4.0}}, "transform"),
])
def test_refusals(changes, name):
    with pytest.raises(ColorGeometryError, match=name):
        call(**changes)


def test_transform_accepts_any_real_number():
    plain = call()
    numpy_ints = call(transform={"scale_mm_per_px": np.int64(1), "x0_px": np.int32(0),
                                 "y1_px": np.int64(4)})
    assert [p.wkb for p in numpy_ints.inlays[1]] == [p.wkb for p in plain.inlays[1]]


# --- fine_regions_px --------------------------------------------------------------------------


def test_fine_regions_px_halves_mask_outline_at_supersample_two():
    fine = np.array([[0, 0, 1, 1],
                     [0, 2, 2, 1],
                     [0, 2, 2, 1],
                     [3, 3, 1, 1]], np.uint8)
    found = fine_regions_px(fine, 2)
    assert list(found) == [0, 1, 2, 3]
    assert all(type(k) is int for k in found)
    for c, geom in found.items():
        expected = shapely.get_coordinates(mask_outline(fine == c)) / 2
        np.testing.assert_array_equal(shapely.get_coordinates(geom), expected)


def test_fine_regions_px_skips_absent_labels_and_takes_signed_ints():
    fine = np.array([[0, 5], [5, 5]], np.int16)
    found = fine_regions_px(fine, 1)
    assert list(found) == [0, 5]
    assert found[5].area == 3.0


def test_fine_regions_px_vectorizes_only_the_labels_asked_for():
    fine = np.array([[0, 1], [2, 3]], np.uint8)
    found = fine_regions_px(fine, 1, labels=[3, 1, 7])
    assert list(found) == [1, 3]
    assert all(type(k) is int for k in found)
    assert fine_regions_px(fine, 1, labels=[]) == {}


@pytest.mark.parametrize(("fine", "s", "labels", "name"), [
    (np.zeros((2, 2), bool), 1, None, "fine"),
    (np.zeros((2, 2), np.float32), 1, None, "fine"),
    (np.zeros(4, np.uint8), 1, None, "fine"),
    (np.zeros((2, 2), np.uint8), True, None, "supersample"),
    (np.zeros((2, 2), np.uint8), 0, None, "supersample"),
    (np.zeros((2, 2), np.uint8), 1, [True], "labels"),
    (np.zeros((2, 2), np.uint8), 1, [0.0], "labels"),
    (np.zeros((2, 2), np.uint8), 1, [-1], "labels"),
])
def test_fine_regions_px_refusals(fine, s, labels, name):
    with pytest.raises(ColorGeometryError, match=name):
        fine_regions_px(fine, s, labels=labels)

import hashlib
import io
import json
import shutil

import numpy as np
import pytest
import shapely
import trimesh
from PIL import Image
from selection_fixtures import BIRD_SEED, DISC_SEED, roadie_like
from shapely import affinity

import tdmg.flat
from tdmg.checks import F1_CHECK_IDS, merge_exact, topology_checks
from tdmg.flat import (
    FLAT_ALGORITHM_VERSION,
    FLAT_REQUIRED_CHECKS,
    HAUSDORFF_STEP_PX,
    OUTLINE_ADDED,
    OUTLINE_BACKGROUND,
    OUTLINE_KEPT,
    OUTLINE_REMOVED,
    RECORD_SCHEMA,
    FlatError,
    clean,
    extrude,
    make_flat,
    mask_outline,
    rasterise,
    to_model,
)
from tdmg.flat import _sampled_hausdorff as sampled_hausdorff
from tdmg.records import canonical_json, record_text
from tdmg.rules import load_rules
from tdmg.selection import Intake, SelectionSpec, pixels_sha256, select_subject, write_selection
from tdmg.smoothing import METHOD, smooth_outline

SPEC = SelectionSpec(instructions="Use only the bird.", remove_at=(DISC_SEED,),
                     keep_at=(BIRD_SEED,))
FILES = ("model.stl", "outline.png", "flat.json")
# flat-1 (exact pixel outline) was 07270f3d5a676e08e221ecec991ed14fd02f9eda2eba8586d87ea17623c402e0.
# Re-pinned for flat-2 (2026-11-10): smoothing on by default, and params.smoothing added.
GOLDEN_FLAT_ID = "1d64c015d890492208b46c0e0ab6f6f6fbb45c3d20e7d19f1177b048028c2c6d"
SMOOTHING_KEYS = {"applied", "sigma_px", "method", "area_change_px2", "removed_area_px2",
                  "added_area_px2", "boundary_hausdorff_lower_bound_px",
                  "hausdorff_sample_step_px", "parts_exact_cleaned", "parts_smoothed_cleaned",
                  "lost_features", "added_features"}
FEATURE_KEYS = {"count", "total_area_mm2", "largest_mm2"}
# sha256 of model.stl for roadie_like at 60 x 3 mm, computed with flat-1 (commit b987845,
# from git archive) on 2026-11-10. The off path (smooth_px=0) must still give these bytes.
FLAT1_STL_SHA256 = "da1a172548660a8384fe26d4217f0352dc0cac4f0b2a3aaf4351e6fe786baf94"


def write_roadie_selection(folder):
    rgba = roadie_like()
    intake = Intake(rgba, "f" * 64, pixels_sha256(rgba), False, "x.png")
    write_selection(intake, select_subject(intake, SPEC), folder)
    return folder


@pytest.fixture(scope="module")
def selection_dir(tmp_path_factory):
    return write_roadie_selection(tmp_path_factory.mktemp("sel") / "roadie")


@pytest.fixture(scope="module")
def run(selection_dir, tmp_path_factory):
    out = tmp_path_factory.mktemp("flat") / "out"
    return make_flat(selection_dir, 60.0, 3.0, out), out


@pytest.fixture(scope="module")
def run_off(selection_dir, tmp_path_factory):
    out = tmp_path_factory.mktemp("flat") / "off"
    return make_flat(selection_dir, 60.0, 3.0, out, smooth_px=0), out


def by_id(record) -> dict:
    return {c["id"]: c for c in record["checks"]}


def png(path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im).copy()


def test_roadie_run_gives_one_body_and_passes_f1(run):
    record, _ = run
    checks = by_id(record)
    assert set(checks) == FLAT_REQUIRED_CHECKS
    assert {checks[i]["status"] for i in F1_CHECK_IDS} == {"PASS"}
    # roadie_like's bird keeps its shoes: at tolerance 30 the dark outline joins them to
    # the legs, so the selection is one 8-connected piece, and at 60 mm (0.71 mm per pixel)
    # the 0.4 mm opening does not cut the 3-pixel legs. Measured: one body, nothing dropped.
    assert record["mesh"]["bodies"] == 1
    assert checks["F4.body_count"]["status"] == "PASS"
    assert record["cleaning"]["dropped_islands"]["count"] == 0
    for i in ("F2.fits_build_volume", "F2.target_width", "F2.export_matches_geometry",
              "F5.triangles"):
        assert checks[i]["status"] == "PASS"
    assert checks["F3.thin_regions"]["status"] == "UNKNOWN"
    assert checks["F6.slicer"]["status"] == "UNKNOWN"
    assert record["verdict"] == "NOT CERTIFIED"


def test_roadie_record_contents(run, selection_dir):
    record, _ = run
    selection = json.loads((selection_dir / "selection.json").read_bytes())
    assert record["schema"] == RECORD_SCHEMA == "tdmg.flat/1"
    assert record["algorithm"] == FLAT_ALGORITHM_VERSION == "flat-2"
    assert record["selection"] == {"selection_id": selection["selection_id"],
                                   "mask_pixels_sha256": selection["mask_pixels_sha256"]}
    params = record["params"]
    assert (params["width_mm"], params["thickness_mm"], params["printer"]) == (60.0, 3.0,
                                                                               "bambu-a1")
    assert params["opening_mm"] == {"value": 0.4, "rule": "flat.sliver.opening_width"}
    island = params["min_island_mm2"]
    assert island["value"] == pytest.approx((2.0 * 0.4) ** 2, rel=1e-15)
    assert island["rules"] == ["flat.island.min_square_side"]
    assert island["nozzle_diameter_mm"] == 0.4
    assert record["cleaning"]["opening_mm"] == 0.4
    assert record["cleaning"]["min_island_mm2"] == island["value"]
    assert record["transform"]["scale_mm_per_px"] * record["transform"]["mask_width_px"] == \
        pytest.approx(60.0, rel=1e-12)
    mesh = record["mesh"]
    assert mesh["extents_mm"][2] == pytest.approx(3.0, rel=1e-12)
    assert mesh["extents_mm"][0] <= 60.0
    # The mesh is read back from the STL, which stores float32 coordinates (relative
    # rounding 2^-24, about 6e-8), so the volume matches area x thickness to about 1e-7.
    assert mesh["volume_mm3"] == pytest.approx(record["cleaning"]["area_after_mm2"] * 3.0,
                                               rel=1e-6)
    assert set(record["outputs"]) == {"model.stl", "outline.png"}
    assert {"python", "numpy", "opencv", "shapely", "trimesh", "manifold3d",
            "contourpy"} <= set(record["environment"])
    assert params["smoothing"] == {"sigma_px": {"value": 2.5, "rule": "flat.smooth.sigma_px"}}
    assert record["review"] == (
        "Open outline.png: grey is in the mask and kept; red is in the mask but not in the "
        "model, removed by smoothing (flat.smooth.sigma_px, when on) or by the cleaning "
        "rules (flat.sliver.opening_width, flat.island.min_square_side); blue is outside "
        "the mask but in the model, added by smoothing. All three rules are untested "
        "hypotheses. Smoothing and cleaning both round convex corners. The verdict stays "
        "NOT CERTIFIED until F3 policy and slicer checks exist.")


def test_roadie_files_exist_and_record_is_canonical_with_lf(run):
    record, out = run
    assert sorted(p.name for p in out.iterdir()) == sorted(FILES)
    data = (out / "flat.json").read_bytes()
    assert b"\r" not in data
    assert data == record_text(record)
    assert json.loads(data) == record
    for name, digest in record["outputs"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == digest


def test_stl_on_disk_is_the_gated_bytes(run):
    record, out = run
    stl = (out / "model.stl").read_bytes()
    assert hashlib.sha256(stl).hexdigest() == record["outputs"]["model.stl"]
    mesh = merge_exact(trimesh.load(io.BytesIO(stl), file_type="stl", process=False))
    regated = [c.as_dict() for c in topology_checks(mesh)]
    assert regated == [c for c in record["checks"] if c["id"].startswith("F1.")]
    assert len(mesh.faces) == record["mesh"]["triangles"]


def test_record_is_strict_json(run):
    record, out = run
    json.dumps(record, allow_nan=False)

    def refuse(name):
        raise AssertionError(f"non-finite constant {name} in flat.json")

    json.loads((out / "flat.json").read_bytes(), parse_constant=refuse)


def colours(image) -> tuple[np.ndarray, ...]:
    return tuple((image == c).all(axis=2) for c in (OUTLINE_KEPT, OUTLINE_REMOVED,
                                                     OUTLINE_ADDED, OUTLINE_BACKGROUND))


def test_outline_png_colours_without_smoothing(run_off, selection_dir):
    record, out = run_off
    image = png(out / "outline.png")
    mask = png(selection_dir / "mask.png") == 255
    assert image.shape == (*mask.shape, 3)
    grey, red, blue, white = colours(image)
    assert (grey | red | white).all()
    assert OUTLINE_KEPT == (128, 128, 128) and OUTLINE_REMOVED == (220, 40, 40)
    assert OUTLINE_ADDED == (40, 90, 220) and OUTLINE_BACKGROUND == (255, 255, 255)
    assert not blue.any()                    # without smoothing, cleaning only removes
    assert not (grey & ~mask).any()
    assert np.array_equal(red, mask & ~grey)
    # The 0.4 mm opening at 0.71 mm per pixel rounds convex pixel corners by under half a
    # pixel, so no pixel centre is lost and nothing shows red, though area was removed.
    # Measured: grey is exactly the mask.
    assert np.array_equal(grey, mask)
    assert not red.any()
    assert record["cleaning"]["removed_area_mm2"] > 0


def test_outline_png_colours_with_smoothing(run, selection_dir):
    _, out = run
    image = png(out / "outline.png")
    mask = png(selection_dir / "mask.png") == 255
    grey, red, blue, white = colours(image)
    assert (grey | red | blue | white).all()
    kept = grey | blue
    assert np.array_equal(grey, mask & kept)
    assert np.array_equal(red, mask & ~kept)
    assert np.array_equal(blue, ~mask & kept)
    assert np.array_equal(white, ~mask & ~kept)


def test_outline_png_shows_removed_hair_in_red(tmp_path):
    rgba = np.zeros((40, 60, 4), np.uint8)
    rgba[5:35, 5:35] = (230, 20, 20, 255)     # a 30 px square
    rgba[19, 35:55] = (230, 20, 20, 255)      # a 1 px hair, 0.2 mm wide at 6 mm / 30 px
    intake = Intake(rgba, "f" * 64, pixels_sha256(rgba), False, "x.png")
    spec = SelectionSpec(instructions="", keep_at=((10, 10),))
    write_selection(intake, select_subject(intake, spec), tmp_path / "sel")
    record = make_flat(tmp_path / "sel", 10.0, 2.0, tmp_path / "out")
    image = png(tmp_path / "out" / "outline.png")
    red = (image == OUTLINE_REMOVED).all(axis=2)
    grey = (image == OUTLINE_KEPT).all(axis=2)
    assert red[19, 36:55].all()               # the hair, away from its root
    assert grey[6:34, 6:34].all()             # the square's inside
    assert record["cleaning"]["removed_area_mm2"] > 0


@pytest.mark.parametrize("width_mm", [10.0, 7.3, 123.456])
def test_rasterise_returns_a_kept_square_exactly(width_mm):
    mask = np.zeros((12, 17), bool)
    mask[3:9, 4:13] = True
    model, transform = to_model(mask_outline(mask), width_mm)
    assert np.array_equal(rasterise([model], transform, mask.shape), mask)


def test_rasterise_returns_an_l_shape_and_a_hole_exactly():
    mask = np.zeros((20, 30), bool)
    mask[2:18, 3:7] = True
    mask[14:18, 3:27] = True
    mask[2:12, 15:25] = True
    mask[5:8, 18:21] = False
    model, transform = to_model(mask_outline(mask), 33.3)
    parts = list(getattr(model, "geoms", [model]))
    assert np.array_equal(rasterise(parts, transform, mask.shape), mask)


def test_tampered_mask_is_refused_and_nothing_written(selection_dir, tmp_path):
    copy = tmp_path / "sel"
    shutil.copytree(selection_dir, copy)
    mask = png(copy / "mask.png")
    mask[0, 0] = 255 - mask[0, 0]
    Image.fromarray(mask).save(copy / "mask.png")
    with pytest.raises(FlatError, match="mask.png does not match selection.json"):
        make_flat(copy, 60.0, 3.0, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_invalid_mask_file_is_a_flat_error(selection_dir, tmp_path):
    copy = tmp_path / "sel"
    shutil.copytree(selection_dir, copy)
    Image.fromarray(np.full((5, 5), 255, np.uint8)).save(copy / "mask.png")
    with pytest.raises(FlatError, match="mask.png cannot be used"):
        make_flat(copy, 60.0, 3.0, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_missing_selection_json_is_refused_and_nothing_written(selection_dir, tmp_path):
    copy = tmp_path / "sel"
    shutil.copytree(selection_dir, copy)
    (copy / "selection.json").unlink()
    with pytest.raises(FlatError, match="selection.json"):
        make_flat(copy, 60.0, 3.0, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_unparsable_selection_json_is_refused(selection_dir, tmp_path):
    copy = tmp_path / "sel"
    shutil.copytree(selection_dir, copy)
    (copy / "selection.json").write_bytes(b"{not json")
    with pytest.raises(FlatError, match="not valid JSON"):
        make_flat(copy, 60.0, 3.0, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("width, thickness", [(0.0, 3.0), (-1.0, 3.0), (float("inf"), 3.0),
                                              (float("nan"), 3.0), (60.0, 0.0),
                                              (60.0, float("nan")), (True, 3.0),
                                              ("abc", 3.0), (None, 3.0), (60.0, True),
                                              (60.0, "abc"), (60.0, None)])
def test_bad_size_is_refused_and_nothing_written(selection_dir, tmp_path, width, thickness):
    with pytest.raises(FlatError, match="width_mm|thickness_mm"):
        make_flat(selection_dir, width, thickness, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_unknown_printer_is_refused(selection_dir, tmp_path):
    with pytest.raises(FlatError, match="printer"):
        make_flat(selection_dir, 60.0, 3.0, tmp_path / "out", printer="../nope")
    assert not (tmp_path / "out").exists()


def test_non_empty_output_folder_is_refused(selection_dir, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "other.txt").write_bytes(b"x")
    with pytest.raises(FlatError, match="not empty"):
        make_flat(selection_dir, 60.0, 3.0, out)
    assert sorted(p.name for p in out.iterdir()) == ["other.txt"]


def test_repeat_runs_are_byte_identical_and_thickness_changes_the_id(run, selection_dir,
                                                                      tmp_path):
    first, out1 = run
    second = make_flat(selection_dir, 60.0, 3.0, tmp_path / "again")
    assert second["flat_id"] == first["flat_id"]
    for name in FILES:
        assert (tmp_path / "again" / name).read_bytes() == (out1 / name).read_bytes()
    thinner = make_flat(selection_dir, 60.0, 2.0, tmp_path / "thin")
    assert thinner["flat_id"] != first["flat_id"]
    assert thinner["selection"] == first["selection"]


def test_golden_flat_id(run):
    # Pinned for roadie_like at 60 x 3 mm on bambu-a1. If a deliberate change to the flat
    # algorithm or its parameters moves this, bump FLAT_ALGORITHM_VERSION and re-pin.
    # The second assertion tells the two causes apart: if it holds but the pin fails, the
    # inputs (fixture, rules, profile) changed; if it fails, the identity's definition did.
    record, _ = run
    identity = {"algorithm": record["algorithm"],
                "mask_pixels_sha256": record["selection"]["mask_pixels_sha256"],
                "params": record["params"]}
    assert record["flat_id"] == hashlib.sha256(canonical_json(identity)).hexdigest()
    assert record["flat_id"] == GOLDEN_FLAT_ID


def tiny_triangle_limit(monkeypatch, limit=4):
    rules = load_rules()
    rule_id = "slicer.orca.max_triangles_per_plate"
    rules[rule_id] = rules[rule_id].model_copy(update={"default": limit})
    # make_flat calls load_rules through tdmg.flat's module-level import, so patching
    # the name in tdmg.flat changes the rules it sees (tdmg.rules is untouched).
    monkeypatch.setattr("tdmg.flat.load_rules", lambda: rules)


def test_a_gate_fail_still_writes_every_file_with_the_verdict(selection_dir, tmp_path,
                                                               monkeypatch):
    tiny_triangle_limit(monkeypatch)
    out = tmp_path / "out"
    record = make_flat(selection_dir, 60.0, 3.0, out)
    f5 = by_id(record)["F5.triangles"]
    assert (f5["status"], f5["threshold"]) == ("FAIL", 4)
    assert record["verdict"] == "NOT CERTIFIED"
    assert sorted(p.name for p in out.iterdir()) == sorted(FILES)
    assert json.loads((out / "flat.json").read_bytes()) == record


def scaled_stl(monkeypatch, factor=0.1):
    """Make make_flat export a mesh scaled by factor, as a broken encoder would."""
    encode = tdmg.flat._encode_stl

    def broken(mesh):
        return encode(trimesh.Trimesh(np.asarray(mesh.vertices) * factor, mesh.faces,
                                      process=False))

    monkeypatch.setattr(tdmg.flat, "_encode_stl", broken)


def test_an_export_that_differs_from_the_geometry_fails_the_gate(selection_dir, tmp_path,
                                                                  monkeypatch, run):
    scaled_stl(monkeypatch)
    record = make_flat(selection_dir, 60.0, 3.0, tmp_path / "out")
    checks = by_id(record)
    assert checks["F2.export_matches_geometry"]["status"] == "FAIL"
    assert {checks[i]["status"] for i in F1_CHECK_IDS} == {"PASS"}
    assert checks["F2.target_width"]["status"] == "PASS"     # the scale itself was right
    # 0.1 x the width of the same run's correct mesh. Smoothing and cleaning can leave the
    # cleaned mesh slightly narrower than 60 mm (the opening rounds the smoothed extremes),
    # so the reference is the correct mesh's width, not 60 mm.
    correct_width = run[0]["mesh"]["extents_mm"][0]
    assert checks["F2.target_width"]["measured"]["mesh_width_mm"] == pytest.approx(
        0.1 * correct_width, rel=1e-6)
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == sorted(FILES)


def edited_selection(selection_dir, tmp_path, change):
    copy = tmp_path / "sel"
    shutil.copytree(selection_dir, copy)
    record = json.loads((copy / "selection.json").read_bytes())
    change(record)
    (copy / "selection.json").write_bytes(record_text(record))
    return copy


def _set(path, value):
    def change(record):
        *parents, last = path
        target = record
        for key in parents:
            target = target[key]
        if value is DELETE:
            del target[last]
        else:
            target[last] = value
    return change


DELETE = object()


@pytest.mark.parametrize("path, value, message", [
    (("selection_id",), "", "selection_id"),
    (("selection_id",), "0" * 63 + "g", "selection_id"),
    (("interpretation", "text"), "Use the disc too.", "inconsistent"),
    (("controls", "color_tolerance", "value"), 31.0, "inconsistent"),
    (("controls",), DELETE, "controls"),
    (("algorithm",), DELETE, "algorithm"),
    (("algorithm",), "selection-0", "inconsistent"),
    (("input", "pixels_sha256"), DELETE, "pixels_sha256"),
    (("input", "pixels_sha256"), "f" * 64, "inconsistent"),
    (("schema",), "tdmg.selection/0", "tdmg.selection/1"),
    (("interpretation",), DELETE, "interpretation"),
])
def test_selection_provenance_is_verified(selection_dir, tmp_path, path, value, message):
    copy = edited_selection(selection_dir, tmp_path, _set(path, value))
    with pytest.raises(FlatError, match=message):
        make_flat(copy, 60.0, 3.0, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_an_inconsistent_selection_names_the_problem(selection_dir, tmp_path):
    copy = edited_selection(selection_dir, tmp_path,
                            _set(("interpretation", "text"), "Use the disc too."))
    with pytest.raises(FlatError, match="^selection.json is inconsistent: "):
        make_flat(copy, 60.0, 3.0, tmp_path / "out")


# --- smoothing (docs/plans/2026-11-10-outline-smoothing.md, Task 3) ---------------------


def test_default_run_smooths_with_the_rule_and_records_it(run):
    record, _ = run
    smoothing = record["smoothing"]
    assert set(smoothing) == SMOOTHING_KEYS
    assert smoothing["applied"] is True
    assert smoothing["sigma_px"] == {"value": 2.5, "rule": "flat.smooth.sigma_px"}
    assert smoothing["method"] == METHOD
    for key in ("area_change_px2", "removed_area_px2", "added_area_px2",
                "boundary_hausdorff_lower_bound_px"):
        assert isinstance(smoothing[key], float)
    assert smoothing["boundary_hausdorff_lower_bound_px"] > 0
    assert smoothing["hausdorff_sample_step_px"] == HAUSDORFF_STEP_PX
    assert smoothing["removed_area_px2"] > 0 and smoothing["added_area_px2"] > 0
    assert smoothing["area_change_px2"] == pytest.approx(
        smoothing["added_area_px2"] - smoothing["removed_area_px2"], abs=1e-9)
    counts = (smoothing["parts_exact_cleaned"], smoothing["parts_smoothed_cleaned"])
    assert counts == (1, 1) and all(type(n) is int for n in counts)
    # roadie_like at 60 mm is 0.718 mm per pixel, so sigma 2.5 px is 1.8 mm, and smoothing
    # moves the boundary at tips and concave corners by more than the 0.4 mm opening over
    # more than min_island (0.64 mm^2). Measured: 4 lost pieces of 1.22 mm^2 (the ends of
    # the two shoe ellipses, in mirror pairs) and 6 added pieces of 1.5-2.2 mm^2 (the
    # concave corners where the legs meet the body and the shoes). The rule cannot tell
    # this rounding from a lost feature, so roadie_like warns.
    lost, added = smoothing["lost_features"], smoothing["added_features"]
    assert set(lost) == set(added) == FEATURE_KEYS
    assert (lost["count"], added["count"]) == (4, 6)
    assert all(a >= 0.64 for a in lost["largest_mm2"] + added["largest_mm2"])
    assert len(record["warnings"]) == 2
    assert record["warnings"][0].startswith("smoothing removed 4 features that cleaning ")
    assert record["warnings"][1].startswith("smoothing added 6 features that cleaning ")


def test_smoothing_measurements_match_a_direct_computation(run, selection_dir):
    record, _ = run
    mask = png(selection_dir / "mask.png") == 255
    exact, smooth = mask_outline(mask), smooth_outline(mask, 2.5)
    smoothing = record["smoothing"]
    assert smoothing["area_change_px2"] == smooth.area - exact.area
    assert smoothing["removed_area_px2"] == exact.difference(smooth).area
    assert smoothing["added_area_px2"] == smooth.difference(exact).area
    t = record["transform"]
    assert t["mask_width_px"] == smooth.bounds[2] - smooth.bounds[0]
    # Both outlines go through the same transform and the same cleaning; the distance is
    # between the cleaned regions, in mm, divided by the scale.
    s = t["scale_mm_per_px"]
    matrix = [s, 0.0, 0.0, -s, -t["x0_px"] * s, t["y1_px"] * s]
    step = HAUSDORFF_STEP_PX * s
    cleaned = [shapely.union_all(clean(affinity.affine_transform(g, matrix), 0.4,
                                       (2.0 * 0.4) ** 2, step)[0]) for g in (exact, smooth)]
    assert smoothing["boundary_hausdorff_lower_bound_px"] == sampled_hausdorff(
        *cleaned, step) / s


def test_off_run_records_a_fixed_shape(run_off):
    record, _ = run_off
    assert record["smoothing"] == {"applied": False} | {
        key: None for key in SMOOTHING_KEYS - {"applied"}}
    assert set(record["smoothing"]) == SMOOTHING_KEYS
    assert record["warnings"] == []
    assert record["params"]["smoothing"] == {"applied": False}


def test_explicit_sigma_is_recorded_without_a_rule(selection_dir, tmp_path, run):
    record = make_flat(selection_dir, 60.0, 3.0, tmp_path / "out", smooth_px=1.5)
    assert record["smoothing"]["applied"] is True
    assert record["smoothing"]["sigma_px"] == {"value": 1.5, "rule": None}
    assert record["params"]["smoothing"] == {"sigma_px": {"value": 1.5, "rule": None}}
    assert record["flat_id"] != run[0]["flat_id"]


def test_ids_differ_between_on_and_off(run, run_off):
    assert run[0]["flat_id"] != run_off[0]["flat_id"]
    assert run[0]["selection"] == run_off[0]["selection"]


def test_off_reproduces_the_exact_outline_path(run_off, selection_dir):
    # The flat-1 path, built directly: exact outline, transform, cleaning, extrusion.
    record, out = run_off
    mask = png(selection_dir / "mask.png") == 255
    model, transform = to_model(mask_outline(mask), 60.0)
    parts, cleaning = clean(model, 0.4, (2.0 * 0.4) ** 2,
                            HAUSDORFF_STEP_PX * transform["scale_mm_per_px"])
    stl = tdmg.flat._encode_stl(extrude(parts, 3.0))
    assert (out / "model.stl").read_bytes() == stl
    assert hashlib.sha256(stl).hexdigest() == FLAT1_STL_SHA256
    assert record["outputs"]["model.stl"] == FLAT1_STL_SHA256
    assert record["transform"] == transform
    assert record["cleaning"] == json.loads(record_text({"c": cleaning}))["c"]


def side_length(stl: bytes, thickness: float) -> float:
    """The outline's perimeter, from the STL: the area of the vertical faces / thickness."""
    mesh = trimesh.load(io.BytesIO(stl), file_type="stl", process=False)
    vertical = np.abs(mesh.face_normals[:, 2]) < 1e-6
    return float(mesh.area_faces[vertical].sum()) / thickness


def test_smoothing_shortens_the_roadie_perimeter_and_passes_the_gate(run, run_off):
    on, out_on = run
    off, out_off = run_off
    smooth = side_length((out_on / "model.stl").read_bytes(), 3.0)
    exact = side_length((out_off / "model.stl").read_bytes(), 3.0)
    assert smooth < exact
    for record in (on, off):
        checks = by_id(record)
        assert {checks[i]["status"] for i in F1_CHECK_IDS} == {"PASS"}
        assert checks["F2.export_matches_geometry"]["status"] == "PASS"


def notched_selection(folder):
    # A 30 px square (rows and columns 5-34) with a notch one pixel wide and four deep
    # (column 20, rows 5-8) in its top edge. tests/test_smoothing.py derives that at sigma
    # 2.5 px the centres of the notch pixels at rows 6-8 lie inside the smoothed outline.
    rgba = np.zeros((40, 60, 4), np.uint8)
    rgba[5:35, 5:35] = (230, 20, 20, 255)
    rgba[5:9, 20] = 0
    intake = Intake(rgba, "f" * 64, pixels_sha256(rgba), False, "x.png")
    write_selection(intake, select_subject(intake, SelectionSpec(instructions="",
                                                                 keep_at=((10, 10),))),
                    folder)
    return folder


def test_outline_png_shows_area_added_by_smoothing_in_blue(tmp_path):
    sel = notched_selection(tmp_path / "sel")
    record = make_flat(sel, 10.0, 2.0, tmp_path / "out")
    image = png(tmp_path / "out" / "outline.png")
    mask = png(sel / "mask.png") == 255
    assert not mask[5:9, 20].any()
    blue = colours(image)[2]
    assert blue[6:9, 20].all()
    assert not (blue & mask).any()
    assert record["smoothing"]["applied"] is True
    off = make_flat(sel, 10.0, 2.0, tmp_path / "off", smooth_px=0)
    assert not colours(png(tmp_path / "off" / "outline.png"))[2].any()
    assert off["smoothing"]["applied"] is False


@pytest.mark.parametrize("smooth_px", [-1.0, float("nan"), float("inf"), -float("inf"), True,
                                       False, "abc"])
def test_bad_smooth_px_is_refused_and_nothing_written(selection_dir, tmp_path, smooth_px):
    with pytest.raises(FlatError, match="smooth_px"):
        make_flat(selection_dir, 60.0, 3.0, tmp_path / "out", smooth_px=smooth_px)
    assert not (tmp_path / "out").exists()


def test_smoothing_that_removes_everything_is_a_flat_error(tmp_path):
    rgba = np.zeros((20, 20, 4), np.uint8)
    rgba[10, 10] = (230, 20, 20, 255)          # a lone pixel: blurred peak w_0^2 < 0.5
    intake = Intake(rgba, "f" * 64, pixels_sha256(rgba), False, "x.png")
    write_selection(intake, select_subject(intake, SelectionSpec(instructions="",
                                                                 keep_at=((10, 10),))),
                    tmp_path / "sel")
    with pytest.raises(FlatError, match="smoothing"):
        make_flat(tmp_path / "sel", 10.0, 2.0, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def body_and_stroke_selection(folder):
    # A square body 40 px wide (columns 10-49) and, separately below it, a stroke
    # 3 px high and 30 px long. At width 20 mm the 40 px wide outline gives 0.5 mm per
    # pixel, so the stroke is 1.5 mm wide: wider than the 0.4 mm opening, and its 22.5 mm^2
    # area is above min_island (0.64 mm^2), so cleaning alone keeps it. At sigma 2.5 px the
    # stroke blurs to at most w_-1 + w_0 + w_1 (about 0.45) < 0.5 (tests/test_smoothing.py
    # notation), so smoothing removes it.
    rgba = np.zeros((70, 60, 4), np.uint8)
    rgba[10:50, 10:50] = (230, 20, 20, 255)
    rgba[60:63, 15:45] = (230, 20, 20, 255)
    intake = Intake(rgba, "f" * 64, pixels_sha256(rgba), False, "x.png")
    spec = SelectionSpec(instructions="", keep_at=((20, 20), (20, 61)))
    write_selection(intake, select_subject(intake, spec), folder)
    return folder


def test_a_feature_lost_to_smoothing_is_warned_about(tmp_path):
    sel = body_and_stroke_selection(tmp_path / "sel")
    record = make_flat(sel, 20.0, 2.0, tmp_path / "out")
    assert record["transform"]["scale_mm_per_px"] == pytest.approx(0.5, rel=1e-3)
    smoothing = record["smoothing"]
    assert (smoothing["parts_exact_cleaned"], smoothing["parts_smoothed_cleaned"]) == (2, 1)
    lost = smoothing["lost_features"]
    assert set(lost) == FEATURE_KEYS
    # The largest piece is the stroke: 30 x 3 px = 22.5 mm^2, a little less after the
    # opening rounds its ends. The other four are the square's corners. Each loses at most
    # the continuous-Gaussian corner area, 0.865 sigma^2 = 5.4 px^2 = 1.35 mm^2 at 0.25
    # mm^2 per px^2 (tests/test_smoothing.py), and the four are equal by symmetry. At this
    # scale a corner piece is wider than the opening and above min_island, so the rule
    # counts corner rounding as a lost feature too.
    assert lost["count"] == 5
    stroke, *corners = lost["largest_mm2"]
    assert 20.0 < stroke <= 22.5
    assert all(0.64 <= c < 1.35 for c in corners)
    assert max(corners) == pytest.approx(min(corners), rel=1e-6)
    assert lost["total_area_mm2"] == pytest.approx(stroke + sum(corners), rel=1e-12)
    assert smoothing["added_features"]["count"] == 0
    assert len(record["warnings"]) == 1
    assert record["warnings"][0].startswith("smoothing removed 5 features that cleaning alone "
                                            "would keep")
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == sorted(FILES)
    off = make_flat(sel, 20.0, 2.0, tmp_path / "off", smooth_px=0)
    assert off["warnings"] == [] and off["smoothing"]["lost_features"] is None

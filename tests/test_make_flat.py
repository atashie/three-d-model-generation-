import hashlib
import io
import json
import shutil

import numpy as np
import pytest
import trimesh
from PIL import Image
from selection_fixtures import BIRD_SEED, DISC_SEED, roadie_like

from tdmg.checks import F1_CHECK_IDS, merge_exact, topology_checks
from tdmg.flat import (
    FLAT_ALGORITHM_VERSION,
    FLAT_REQUIRED_CHECKS,
    OUTLINE_BACKGROUND,
    OUTLINE_KEPT,
    OUTLINE_REMOVED,
    RECORD_SCHEMA,
    FlatError,
    make_flat,
    mask_outline,
    rasterise,
    to_model,
)
from tdmg.records import canonical_json, record_text
from tdmg.rules import load_rules
from tdmg.selection import Intake, SelectionSpec, pixels_sha256, select_subject, write_selection

SPEC = SelectionSpec(instructions="Use only the bird.", remove_at=(DISC_SEED,),
                     keep_at=(BIRD_SEED,))
FILES = ("model.stl", "outline.png", "flat.json")
GOLDEN_FLAT_ID = "07270f3d5a676e08e221ecec991ed14fd02f9eda2eba8586d87ea17623c402e0"


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
    for i in ("F2.fits_build_volume", "F2.target_width", "F5.triangles"):
        assert checks[i]["status"] == "PASS"
    assert checks["F3.thin_regions"]["status"] == "UNKNOWN"
    assert checks["F6.slicer"]["status"] == "UNKNOWN"
    assert record["verdict"] == "NOT CERTIFIED"


def test_roadie_record_contents(run, selection_dir):
    record, _ = run
    selection = json.loads((selection_dir / "selection.json").read_bytes())
    assert record["schema"] == RECORD_SCHEMA == "tdmg.flat/1"
    assert record["algorithm"] == FLAT_ALGORITHM_VERSION == "flat-1"
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
    assert {"python", "numpy", "shapely", "trimesh", "manifold3d"} <= set(record["environment"])
    assert record["review"] == (
        "Open outline.png: grey is kept, red was removed as unprintable. The verdict stays "
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


def test_outline_png_colours(run, selection_dir):
    record, out = run
    image = png(out / "outline.png")
    mask = png(selection_dir / "mask.png") == 255
    assert image.shape == (*mask.shape, 3)
    grey = (image == OUTLINE_KEPT).all(axis=2)
    red = (image == OUTLINE_REMOVED).all(axis=2)
    white = (image == OUTLINE_BACKGROUND).all(axis=2)
    assert (grey | red | white).all()
    assert OUTLINE_KEPT == (128, 128, 128) and OUTLINE_REMOVED == (220, 40, 40)
    assert OUTLINE_BACKGROUND == (255, 255, 255)
    assert not (grey & ~mask).any()          # cleaning only removes material
    assert np.array_equal(red, mask & ~grey)
    # The 0.4 mm opening at 0.71 mm per pixel rounds convex pixel corners by under half a
    # pixel, so no pixel centre is lost and nothing shows red, though area was removed.
    # Measured: grey is exactly the mask.
    assert np.array_equal(grey, mask)
    assert not red.any()
    assert record["cleaning"]["removed_area_mm2"] > 0


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

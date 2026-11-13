"""tdmg slice on a tdmg flat --colors folder: tdmg.color_slicing.make_color_slice
(docs/plans/2026-11-13-color-slicing.md, Decisions 5 to 7 and Task 6).

The fake OrcaSlicer and PrusaSlicer are tests/test_slice.py's (fixtures fake and prusa):
the fake OrcaSlicer's default G-code has no layers, so the color checks are UNKNOWN and
these tests cover the wiring, the record, the refusals and the CLI. The real slicers run in
the tests marked slicer.
"""

import copy
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import pytest
import test_slice
from test_colored_flat import write_plan, write_sel
from typer.testing import CliRunner

import tdmg.color_slicing as cs
from tdmg.checks import CheckResult
from tdmg.cli import app
from tdmg.color_gcode import required_check_ids
from tdmg.colored_flat import make_colored_flat
from tdmg.orca_input import turn_over
from tdmg.records import canonical_json
from tdmg.slicer import SlicerError
from tdmg.slicing import SLICE_REQUIRED_CHECKS, make_slice

# tests/test_slice.py's fixtures: the fake OrcaSlicer and the fake PrusaSlicer.
fake = test_slice.fake
prusa = test_slice.prusa
runner = CliRunner(env={"NO_COLOR": "1", "FORCE_COLOR": None, "COLUMNS": "200"})
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    text = ANSI.sub("", text)
    text = "".join(" " if 0x2500 <= ord(c) <= 0x257F else c for c in text)
    return " ".join(text.split())


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def colored(tmp_path_factory):
    """A tdmg flat --colors folder with a glue version (the roadie-like test plan)."""
    root = tmp_path_factory.mktemp("colored")
    sel = write_sel(root / "sel")
    assert write_plan(sel, root / "colors")["ready"] is True
    rec = make_colored_flat(sel, root / "colors", root / "out", thickness_mm=3.0)
    assert rec["glue"]["built"] is True
    return root / "out"


@pytest.fixture
def folder(colored, tmp_path):
    """A copy of the colored folder that a test may change."""
    out = tmp_path / "colored"
    shutil.copytree(colored, out)
    return out


@pytest.fixture
def orca(fake):
    """The fake OrcaSlicer, reporting each model's own layer count (the glue pieces are
    thinner than the base)."""
    return lambda **kw: fake(layers="auto", **kw)


def _run(colored_dir, out, root, **kw):
    return cs.make_color_slice(colored_dir, out, root, **kw)


def _record(colored_dir):
    return json.loads((Path(colored_dir) / "colored.json").read_bytes())


# --- The record ------------------------------------------------------------------------

def test_record_and_files_with_the_fake(colored, orca, tmp_path):
    args = tmp_path / "args.json"
    root = orca(args_file=str(args))
    out = tmp_path / "slice"
    rec = _run(colored, out, root)
    src = _record(colored)
    assert (rec["schema"], rec["algorithm"]) == ("tdmg.colorslice/1", "colorslice-1")
    assert re.fullmatch(r"[0-9a-f]{64}", rec["colorslice_id"])
    assert rec["links"]["colorflat_id"] == src["colorflat_id"]
    assert rec["links"]["colored_record_sha256"] == _sha((colored / "colored.json").read_bytes())
    assert rec["links"]["model_3mf_sha256"] == src["outputs"]["model.3mf"]
    ams = [b for b in src["bodies"] if b["route"] == "ams"]
    n = len(ams)
    # The filament map: the shells in model_3mf order, filament = position + 1.
    assert [(f["filament"], f["body"], f["index"], f["hex"]) for f in rec["filament_map"]] == [
        (i + 1, name, next(b["index"] for b in ams if b["name"] == name),
         next(b["hex"] for b in ams if b["name"] == name))
        for i, name in enumerate(src["model_3mf"]["shells"])]
    # Derived filament profiles: the pinned one with only filament_colour set.
    pinned = json.loads((root / "profiles-flat" / "filament.json").read_bytes())
    for f, row in zip(rec["filaments"]["profiles"], rec["filament_map"], strict=True):
        data = (out / f["file"]).read_bytes()
        assert _sha(data) == f["sha256"] == rec["outputs"][f["file"]]
        parsed = json.loads(data)
        assert parsed == {**pinned, "filament_colour": [row["hex"].upper()]}
        assert f["differs_from_pinned_in"] == ["filament_colour"]
    # The command: the 3MF input and one filament per color, joined by ";".
    runs = [json.loads(line) for line in args.read_text().splitlines()]
    colour_runs = [r for r in runs if Path(r["argv"][0]).name == "orca-input.3mf"]
    assert len(colour_runs) == 2 and len(runs) == 2 + len(rec["glue"]["plates"])
    seen = colour_runs[1]                     # face down
    assert Path(seen["argv"][0]).name == "orca-input.3mf"
    assert seen["argv"][3] == "--load-filaments"
    assert [Path(p).name for p in seen["argv"][4].split(";")] == [
        f"filament-{i + 1}.json" for i in range(n)]
    assert [json.loads(t)["filament_colour"] for t in seen["filaments"]] == [
        [f["hex"].upper()] for f in rec["filament_map"]]
    assert rec["command"][:2] == ["<orca-slicer.exe>", "<orca-input.3mf>"]
    assert rec["command"][5] == ";".join(f"<filament-{i + 1}.json>" for i in range(n))
    # Both faces, each with its input, G-code, statistics and checks.
    for face, folder in (("up", "face-up"), ("down", "face-down")):
        f = rec["faces"][face]
        assert f["folder"] == folder
        orca = (out / folder / "orca-input.3mf").read_bytes()
        assert _sha(orca) == f["orca_input"]["sha256"]
        assert (out / folder / "plate_1.gcode").is_file()     # nothing FAILed
        assert (out / folder / "plate_1.statistics.json").is_file()
        ids = [c["id"] for c in f["checks"]]
        assert "F2.orca_input_matches_bodies" in ids and "F6.slicer" not in ids
        by = {c["id"]: c["status"] for c in f["checks"]}
        assert by["F2.orca_input_matches_bodies"] == "PASS"
        assert by["F6.slicer_exit"] == by["F6.gcode_present"] == "PASS"
        assert by["F6.color_changes"] == "UNKNOWN"      # the fake G-code has no layers
        assert set(f["required_checks"]) >= required_check_ids(n) | {
            "F2.orca_input_matches_bodies", "F6.slicer_exit", "F6.gcode_present",
            "F6.layer_count", "F6.single_object", "F6.portability",
            "F2.export_3mf_matches_bodies", "F4.color_partition"}
        assert not set(f["required_checks"]) & {"F6.slicer", "F3.thin_regions",
                                                "F4.glue_fit", "F4.glue_partition"}
        assert f["verdict"] == "NOT CERTIFIED"
        assert f["certification"].startswith("NOT CERTIFIED: F6.color_changes UNKNOWN")
        assert f["filament_map"] == rec["filament_map"]
    up, down = (out / "face-up/orca-input.3mf").read_bytes(), \
        (out / "face-down/orca-input.3mf").read_bytes()
    assert up != down
    # Glue plates: R1 records, with R1's required set; the two flat-only checks missing.
    glue = [b for b in src["bodies"] if b["route"] == "glue"]
    assert sorted(rec["glue"]["plates"]) == sorted(b["file"][:-4] for b in glue)
    report = src["glue"]["report"]
    for name, plate in rec["glue"]["plates"].items():
        row = next(b for b in glue if b["file"] == f"{name}.stl")
        assert plate["algorithm"] == "slice-5"
        assert plate["required_checks"] == sorted(SLICE_REQUIRED_CHECKS - {"F2.target_width"})
        assert "F2.target_width" in plate["not_applicable"]
        assert "missing" not in plate["certification"]
        body = next(c for c in plate["checks"] if c["id"] == "F4.body_count")
        want = 1 if row["role"] == "base" else next(
            c["pieces"] for c in report["colors"] if c["index"] == row["index"])
        assert (body["status"], body["measured"], body["threshold"]) == ("PASS", want, want)
        assert (out / name / "plate_1.gcode").is_file()
        assert plate["gcode"]["file"] == f"{name}/plate_1.gcode"
    assert any(c["pieces"] > 1 for c in report["colors"])      # the test covers several
    assert rec["portability"]["configured"] is False
    assert rec["portability"]["check"]["status"] == "UNKNOWN"
    assert rec["model_3mf"]["check"]["status"] == "PASS"
    names = {str(p.relative_to(out)).replace("\\", "/") for p in out.rglob("*")
             if p.is_file()}
    assert names == {*rec["outputs"], "slice.json"}
    assert json.loads((out / "slice.json").read_bytes()) == rec


def _comparable(rec):
    """The record without what differs between two runs: the environment and the fake's
    timestamped G-code bytes (the normalised hash stays)."""
    rec = copy.deepcopy(rec)
    del rec["environment"]
    rec["outputs"] = {k: v for k, v in rec["outputs"].items() if "plate_1.gcode" not in k}
    for section in [*rec["faces"].values(), *rec["glue"]["plates"].values()]:
        if section["gcode"]:
            del section["gcode"]["sha256"]
        section["outputs"] = None
    return rec


def test_repeat_runs_give_the_same_record(colored, orca, tmp_path):
    root = orca()
    a = _run(colored, tmp_path / "a", root)
    b = _run(colored, tmp_path / "b", root)
    assert a["colorslice_id"] == b["colorslice_id"]
    assert _comparable(a) == _comparable(b)
    for face in ("face-up", "face-down"):
        assert ((tmp_path / "a" / face / "orca-input.3mf").read_bytes()
                == (tmp_path / "b" / face / "orca-input.3mf").read_bytes())


def test_the_id_is_the_hash_of_its_inputs(colored, orca, tmp_path):
    root = orca()
    rec = _run(colored, tmp_path / "a", root)
    identity = {
        "algorithm": "colorslice-1", "colorflat_id": rec["links"]["colorflat_id"],
        "colored_record_sha256": rec["links"]["colored_record_sha256"],
        "faces": {f: {"orca_input_sha256": rec["faces"][f]["orca_input"]["sha256"]}
                  for f in ("up", "down")},
        "slicer": {"version": rec["slicer"]["version"],
                   "exe_sha256": rec["slicer"]["exe_sha256"],
                   "libraries": rec["slicer"]["libraries"],
                   "app_tree_sha256": rec["slicer"]["app_tree_sha256"],
                   "app_tree_verified": True},
        "profiles": {k: v["sha256"] for k, v in rec["slicer"]["profiles"].items()},
        "filaments": [f["sha256"] for f in rec["filaments"]["profiles"]],
        "command": rec["command"],
        "f3": {"tolerance": {"rule": "acceptance.dimension.tolerance", "value_mm": 0.2},
               "elefant_foot_compensation_mm": 0.075},
        "portability": None,
        "glue_plates": {k: p["slice_id"] for k, p in rec["glue"]["plates"].items()}}
    assert rec["colorslice_id"] == _sha(canonical_json(identity))
    # Skipping the tree check changes the id, as in R1.
    skipped = _run(colored, tmp_path / "b", root, check_tree=False)
    assert skipped["colorslice_id"] != rec["colorslice_id"]
    assert skipped["faces"]["up"]["certification"].startswith(
        "NOT CERTIFIED: app tree not verified (--skip-tree-check)")


def test_the_face_down_input_is_the_turned_bodies(colored, orca, tmp_path):
    _run(colored, tmp_path / "a", orca())
    src = _record(colored)
    shells = cs.ams_shells(src, {n: (colored / n).read_bytes() for n in src["outputs"]})
    from tdmg.orca_input import write_orca_input
    assert (tmp_path / "a/face-up/orca-input.3mf").read_bytes() == write_orca_input(shells)
    assert ((tmp_path / "a/face-down/orca-input.3mf").read_bytes()
            == write_orca_input(turn_over(shells)))


# --- Refusals: nothing written ------------------------------------------------------------

def _refused(folder, tmp_path, root, message):
    out = tmp_path / "out"
    with pytest.raises(SlicerError, match=message):
        _run(folder, out, root)
    assert not out.exists()


def test_a_folder_without_colored_json_is_refused(tmp_path, orca):
    (tmp_path / "empty").mkdir()
    _refused(tmp_path / "empty", tmp_path, orca(), "colored.json is missing")


def _edit(folder, change):
    rec = _record(folder)
    change(rec)
    (folder / "colored.json").write_text(json.dumps(rec), encoding="utf-8")


@pytest.mark.parametrize(("change", "message"), [
    (lambda r: r.update(schema="tdmg.flat/1"), "schema is 'tdmg.flat/1'"),
    (lambda r: r.update(algorithm="colorflat-2"), "algorithm is 'colorflat-2'"),
    (lambda r: r["identity"]["params"].update(thickness_mm=4.0),
     "colorflat_id does not match its identity"),
    (lambda r: r.update(required_checks=r["required_checks"][1:]), "required_checks"),
    (lambda r: r["outputs"].update({"model.3mf": "0" * 64}), "model.3mf has sha256"),
    (lambda r: r["bodies"][0].update(file="nothing.stl"), "a body row is not valid"),
    (lambda r: r["model_3mf"].update(shells=r["model_3mf"]["shells"][::-1]),
     "palette.json does not describe"),
    (lambda r: r["bodies"][0]["checks"][0].update(status="MAYBE"), "has status 'MAYBE'"),
])
def test_a_tampered_record_is_refused(folder, tmp_path, orca, change, message):
    _edit(folder, change)
    _refused(folder, tmp_path, orca(), message)


def test_a_changed_stl_is_refused(folder, tmp_path, orca):
    stl = folder / "ams-base.stl"
    stl.write_bytes(stl.read_bytes()[:-1] + b"\x01")
    _refused(folder, tmp_path, orca(), "ams-base.stl has sha256 .* does not match")


@pytest.mark.parametrize("name", ["ams-base.stl", "glue-base.stl", "palette.json"])
def test_a_missing_output_is_refused(folder, tmp_path, orca, name):
    (folder / name).unlink()
    _refused(folder, tmp_path, orca(), f"{name} is missing")


def test_a_non_empty_output_folder_is_refused(colored, tmp_path, orca):
    out = tmp_path / "out"
    out.mkdir()
    (out / "x").write_text("x")
    with pytest.raises(SlicerError, match="not empty"):
        _run(colored, out, orca())


def test_make_slice_still_refuses_a_colored_folder(colored, tmp_path, orca):
    with pytest.raises(SlicerError, match="make_color_slice"):
        make_slice(colored, tmp_path / "out", orca())
    assert not (tmp_path / "out").exists()


# --- The colored record's own checks: carried, as R1 carries flat.json's ------------------

def test_a_failed_inherited_check_is_carried_and_quarantines(folder, tmp_path,
                                                             orca):
    def fail(r):
        r["assembly"]["ams"][0]["status"] = "FAIL"          # F4.color_partition
    _edit(folder, fail)
    out = tmp_path / "out"
    rec = _run(folder, out, orca())
    for face in ("up", "down"):
        f = rec["faces"][face]
        assert "F4.color_partition FAIL" in f["certification"]
        assert f["gcode"]["quarantined"] is True
        assert f["gcode"]["file"] == f"{f['folder']}/plate_1.gcode.failed"
        assert (out / f["folder"] / "plate_1.gcode.failed").is_file()
        assert not (out / f["folder"] / "plate_1.gcode").exists()
    # The glue plates carry their own checks, not the AMS assembly's.
    assert all("F4.color_partition" not in p["certification"]
               for p in rec["glue"]["plates"].values())


# --- Verdicts ------------------------------------------------------------------------------

def _all_pass(monkeypatch):
    """Make the color checks and F6.portability PASS (the fakes cannot produce them)."""
    real = cs.color_slice_checks

    def passing(gcode, shells, setup, statistics=None, not_measured=None):
        checks, record = real(gcode, shells, setup, statistics, not_measured)
        req = required_check_ids(len(list(shells)))
        return [CheckResult(c.id, "PASS", c.measured, c.threshold, c.rule, c.note)
                if c.id in req else c for c in checks], record
    monkeypatch.setattr(cs, "color_slice_checks", passing)
    monkeypatch.setattr(cs, "_portability", lambda *a, **kw: (
        CheckResult("F6.portability", "PASS", None, None, None, "test"),
        {"configured": False, "reason": "test", "gcode": None}, None, None))


def test_printable_when_every_required_check_passes(colored, orca, tmp_path,
                                                    monkeypatch):
    _all_pass(monkeypatch)
    rec = _run(colored, tmp_path / "a", orca())
    for face in ("up", "down"):
        f = rec["faces"][face]
        assert f["certification"] == "PRINTABLE", f["certification"]
        assert f["certification_note"] == cs.COLOR_PRINTABLE_MEANING
        assert f["gcode"]["quarantined"] is False
    assert rec["verdicts"]["face-up"] == "PRINTABLE"


def test_cli_printable_says_to_print_from_model_3mf(colored, orca, tmp_path,
                                                    monkeypatch):
    _all_pass(monkeypatch)
    r = runner.invoke(app, ["slice", str(colored), "--out", str(tmp_path / "s"),
                            "--slicer-dir", str(orca())])
    assert r.exit_code == 0, r.output
    lines = r.stdout.splitlines()
    assert "face-up: PRINTABLE" in lines and "face-down: PRINTABLE" in lines
    assert cs.COLOR_PRINT_THIS in lines
    assert cs.COLOR_PRINT_THIS.startswith("to print: open model.3mf in Bambu Studio")
    assert "plate_1.gcode are for checking only" in cs.COLOR_PRINT_THIS
    assert not any(line.startswith("print ") for line in lines)


# --- The CLI ------------------------------------------------------------------------------

def test_cli_output_for_a_colored_folder(colored, orca, tmp_path):
    out = tmp_path / "s"
    r = runner.invoke(app, ["slice", str(colored), "--out", str(out), "--slicer-dir",
                            str(orca())])
    assert r.exit_code == 0, r.output            # no check FAILed (UNKNOWN ones only)
    rec = json.loads((out / "slice.json").read_bytes())
    lines = r.stdout.splitlines()
    assert lines[0] == f"face-up: {rec['faces']['up']['certification']}"
    assert lines[1] == ("  ? color changes, flush ?, prime tower ?, time ? (slicer "
                        "estimates)")
    assert lines[2] == f"face-down: {rec['faces']['down']['certification']}"
    filament = ", ".join(
        f"filament {f['filament']}: "
        + ("base" if f["role"] == "base" else f"color {f['index']}") + f" {f['hex']}"
        for f in rec["filament_map"])
    assert filament in lines and filament.startswith("filament 1: base #")
    for name, plate in rec["glue"]["plates"].items():
        assert f"{name} (glue plate, sliced as an R1 part): {plate['certification']}" in lines
    assert any(line.startswith("portability: UNKNOWN - PrusaSlicer is not configured")
               for line in lines)
    assert ("no face is PRINTABLE: do not print yet; model.3mf is the file to print from "
            "once a face is, with the filaments above") in lines
    assert cs.COLOR_PRINT_THIS not in lines
    assert f"colorslice_id {rec['colorslice_id']}" in lines
    assert f"wrote {out / 'slice.json'}" in lines
    assert f"wrote {out / 'face-up' / 'plate_1.gcode'}" in lines


def test_cli_exit_1_and_refusal_exit_2(folder, orca, tmp_path):
    def fail(r):
        r["assembly"]["ams"][0]["status"] = "FAIL"
    _edit(folder, fail)
    r = runner.invoke(app, ["slice", str(folder), "--out", str(tmp_path / "a"),
                            "--slicer-dir", str(orca())])
    assert r.exit_code == 1, r.output
    assert cs.COLOR_DO_NOT_PRINT in r.stdout.splitlines()
    (folder / "ams-base.stl").unlink()
    r = runner.invoke(app, ["slice", str(folder), "--out", str(tmp_path / "b"),
                            "--slicer-dir", str(orca())])
    assert r.exit_code == 2
    assert "ams-base.stl is missing" in _plain(r.stderr)
    assert not (tmp_path / "b").exists()


# --- PrusaSlicer on model.3mf (fake) ---------------------------------------------------------

def _expected_parts(colored):
    return sum(b["bodies"] for b in _record(colored)["bodies"] if b["route"] == "ams")


def test_portability_reads_model_3mf_and_records_the_volume_as_information(
        colored, orca, prusa, tmp_path):
    out = tmp_path / "a"
    volume = 1234.5
    rec = _run(colored, out, orca(), prusaslicer_dir=prusa(
        info={"number_of_parts": _expected_parts(colored), "volume": f"{volume:.6f}"}))
    port = rec["portability"]
    check = port["check"]
    assert check["status"] == "PASS", check          # a volume far off does not FAIL it
    assert "information" in check["note"] and "No derivation" in check["note"]
    assert "model.3mf" in check["note"]
    palette = sum(b["volume_mm3"] for b in _record(colored)["bodies"] if b["route"] == "ams")
    assert check["measured"]["volume_mm3"] == volume
    assert check["measured"]["palette_volume_mm3"] == pytest.approx(palette)
    assert check["measured"]["volume_difference_mm3"] == pytest.approx(volume - palette)
    assert check["threshold"]["volume_tol_mm3"] is None
    assert port["commands"]["info"] == ["<prusa-slicer-console.exe>", "--info", "<model.3mf>"]
    assert port["expected"]["volume_judged"] is False
    assert port["gcode"]["file"] == "prusaslicer.portability-only.gcode.txt"
    assert (out / "prusaslicer.portability-only.gcode.txt").is_file()
    for face in ("up", "down"):
        assert "F6.portability" not in rec["faces"][face]["certification"]


def test_portability_fails_on_the_wrong_part_count(colored, orca, prusa,
                                                   tmp_path):
    out = tmp_path / "a"
    rec = _run(colored, out, orca(), prusaslicer_dir=prusa())     # the fake says 1 part
    check = rec["portability"]["check"]
    assert check["status"] == "FAIL"
    assert "number_of_parts 1, not the" in check["note"]
    assert "of the AMS bodies of colored.json" in check["note"]
    assert (out / "prusaslicer.portability-only.gcode.txt.failed").is_file()
    for face in ("up", "down"):
        assert rec["faces"][face]["gcode"]["quarantined"] is True


# --- The real slicers ------------------------------------------------------------------------

@pytest.mark.slicer
@pytest.mark.skipif(not (os.environ.get("TDMG_ORCASLICER_DIR")
                         and os.environ.get("TDMG_PRUSASLICER_DIR")),
                    reason="TDMG_ORCASLICER_DIR and TDMG_PRUSASLICER_DIR are not both set "
                           "to verified installs")
def test_the_test_plan_slices_with_the_real_slicers(colored, tmp_path):
    rec = cs.make_color_slice(colored, tmp_path / "s")
    n = len(rec["filament_map"])
    for face in ("up", "down"):
        by = {c["id"]: c["status"] for c in rec["faces"][face]["checks"]}
        for cid in ("F2.orca_input_matches_bodies", "F6.slicer_exit", "F6.gcode_present",
                    "F6.layer_count", "F6.single_object", "F6.color_changes",
                    "F6.tool_placement", "F6.filaments_used"):
            assert by[cid] == "PASS", (face, cid, rec["faces"][face]["certification"])
        assert rec["faces"][face]["summary"]["changes"] is not None
        assert len([c for c in by if c.startswith("F3.") and ".T" in c]) == 3 * n
    port = rec["portability"]["check"]
    assert port["status"] == "PASS", port
    assert "volume_difference_mm3" in port["measured"]
    for plate in rec["glue"]["plates"].values():
        by = {c["id"]: c["status"] for c in plate["checks"]}
        assert by["F6.slicer_exit"] == "PASS" and by["F6.layer_count"] == "PASS"
        assert by["F4.body_count"] == "PASS"


def test_a_glue_plate_with_the_wrong_body_count_fails_it(folder, tmp_path, orca):
    def more(r):
        r["glue"]["report"]["colors"][0]["pieces"] += 1
    _edit(folder, more)
    with pytest.raises(SlicerError, match="glue report"):
        _run(folder, tmp_path / "a", orca())       # colors and pieces disagree: refused
    assert not (tmp_path / "a").exists()


def test_the_body_count_check_compares_the_stl_with_the_report():
    import trimesh
    two = trimesh.util.concatenate([trimesh.creation.box((1, 1, 1)),
                                    trimesh.creation.box((1, 1, 1)).apply_translation(
                                        (3, 0, 0))])
    data = two.export(file_type="stl")
    assert cs.glue_body_count_check(data, 2).status == "PASS"
    bad = cs.glue_body_count_check(data, 3)
    assert (bad.status, bad.measured, bad.threshold) == ("FAIL", 2, 3)


# --- A PRINTABLE glue plate -----------------------------------------------------------------

def _f3_pass(monkeypatch):
    """R1's F3 checks PASS (the fake G-code cannot be measured)."""
    import tdmg.slicing
    from tdmg.printed import F3_SLICE_CHECK_IDS

    def passing(gcode, stl, setup, not_measured=None):
        return ([CheckResult(cid, "PASS", None, None, None, "test") for cid in F3_SLICE_CHECK_IDS],
                {"measured": False, "layer_count": None})
    monkeypatch.setattr(tdmg.slicing, "f3_checks", passing)


def test_a_printable_glue_plate_names_its_own_stl(colored, orca, prusa, tmp_path,
                                                  monkeypatch):
    from tdmg.portability import portability_meaning
    from tdmg.slicing import PRINTABLE_MEANING, printable_meaning
    _f3_pass(monkeypatch)
    out = tmp_path / "s"
    r = runner.invoke(app, ["slice", str(colored), "--out", str(out), "--slicer-dir",
                            str(orca()), "--prusaslicer-dir", str(prusa())])
    rec = json.loads((out / "slice.json").read_bytes())
    base = rec["glue"]["plates"]["glue-base"]     # one body, so the fake's 1 part is right
    assert base["certification"] == "PRINTABLE", base["certification"]
    assert base["certification_note"] == printable_meaning("glue-base.stl")
    assert "glue-base.stl" in base["certification_note"]
    assert "model.stl" not in base["certification_note"]
    port = next(c for c in base["checks"] if c["id"] == "F6.portability")
    assert portability_meaning("glue-base.stl") in port["note"]
    assert "model.stl" not in port["note"]
    # R1's texts are unchanged.
    assert printable_meaning() == PRINTABLE_MEANING and "model.stl" in PRINTABLE_MEANING
    lines = r.stdout.splitlines()
    assert ("glue-base: slice glue-base.stl in Bambu Studio to print; its plate_1.gcode is "
            "for checking only") in lines
    printable = {n for n, p in rec["glue"]["plates"].items() if p["verdict"] == "PRINTABLE"}
    assert sum("in Bambu Studio to print; its plate_1.gcode" in line for line in lines) \
        == len(printable)

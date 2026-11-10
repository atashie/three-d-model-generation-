"""tdmg slice and make_slice, with the fake slicer (docs/plans/2026-11-10-slicer-check.md).

The fake install has a pin made for it (tdmg.slicing.load_pin is replaced), and the
command is [sys.executable, tests/fake_orca.py] (tdmg.slicing.slicer_command is replaced).
The fake reads its behaviour from $TDMG_FAKE_ORCA_CONTROL. The integration test at the
end runs the real slicer when TDMG_ORCASLICER_DIR points at a verified install.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import sys

import numpy as np
import pytest
import trimesh
from test_make_flat import write_roadie_selection
from test_selection import _intake
from typer.testing import CliRunner

import tdmg.flat
import tdmg.slicing
from tdmg.cli import app
from tdmg.flat import flat_identity, make_flat
from tdmg.paths import REPO_ROOT
from tdmg.records import canonical_json
from tdmg.rules import load_rules
from tdmg.selection import SelectionSpec, select_subject, write_selection
from tdmg.slicer import Slicer, SlicerError, load_pin, platform_key
from tdmg.slicing import (
    RECORD_SCHEMA,
    SLICE_ALGORITHM_VERSION,
    SLICE_REQUIRED_EXTRA,
    allowed_layer_counts,
    make_slice,
    slicer_command,
    stl_z_range,
)

FAKE = REPO_ROOT / "tests" / "fake_orca.py"
PIN = load_pin()
# The two process keys make_slice reads, with the A1 values (see tests/test_slicer.py).
PROCESS = {"layer_height": "0.2", "initial_layer_print_height": "0.2"}
FILES = {"machine.json": b"{}", "process.json": json.dumps(PROCESS).encode(),
         "filament.json": b"{}"}
APP = {"orca-slicer.exe": b"exe", "OrcaSlicer.dll": b"dll", "resources/x.txt": b"x"}
F6_IDS = ["F6.slicer_exit", "F6.gcode_present", "F6.layer_count", "F6.single_object",
          "F6.portability"]
RECORD_KEYS = {"schema", "tdmg_version", "algorithm", "slice_id", "links", "params", "slicer",
               "command", "exit", "stats", "checks", "verdict", "certification", "gcode",
               "stderr_tail", "log_written", "outputs", "environment", "review"}
runner = CliRunner(env={"NO_COLOR": "1", "FORCE_COLOR": None, "COLUMNS": "200"})
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tree(app: dict[str, bytes]) -> str:
    lines = sorted(f"{rel}\t{_sha(d)}" for rel, d in app.items())
    return _sha("".join(x + "\n" for x in lines).encode())


@pytest.fixture(scope="module")
def flat_dir(tmp_path_factory):
    sel = write_roadie_selection(tmp_path_factory.mktemp("sel") / "roadie")
    out = tmp_path_factory.mktemp("flat") / "out"
    make_flat(sel, 60.0, 3.0, out)
    return out


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """A fake install and its pin; returns a function that sets the fake's behaviour."""
    root = tmp_path / "orca"
    for rel, data in APP.items():
        (root / "app" / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / "app" / rel).write_bytes(data)
    (root / "profiles-flat").mkdir()
    for name, data in FILES.items():
        (root / "profiles-flat" / name).write_bytes(data)
    flat = {k: p.model_copy(update={"sha256": _sha(FILES[p.file])})
            for k, p in PIN.profiles.flat.items()}
    pin = PIN.model_copy(update={
        "exe": PIN.exe.model_copy(update={"sha256": _sha(APP["orca-slicer.exe"])}),
        "libraries": [PIN.libraries[0].model_copy(
            update={"sha256": _sha(APP["OrcaSlicer.dll"])})],
        "app_tree": PIN.app_tree.model_copy(update={"files": len(APP), "sha256": _tree(APP)}),
        "profiles": PIN.profiles.model_copy(update={"flat": flat})})
    monkeypatch.setattr(tdmg.slicing, "load_pin", lambda: pin)
    monkeypatch.setattr(tdmg.slicing, "slicer_command", lambda slicer: [sys.executable,
                                                                         str(FAKE)])
    monkeypatch.delenv("TDMG_ORCASLICER_DIR", raising=False)
    control = tmp_path / "control.json"
    monkeypatch.setenv("TDMG_FAKE_ORCA_CONTROL", str(control))

    def behave(**kwargs):
        # The roadie flat is 3 mm thick: 15 layers at 0.2/0.2 mm.
        control.write_bytes(json.dumps({"layers": 15, **kwargs}).encode())
        return root
    behave.pin = pin
    behave.root = root
    return behave


def by_id(record):
    return {c["id"]: c for c in record["checks"]}


# --- The record ---------------------------------------------------------------------

def test_record_contents(flat_dir, fake, tmp_path):
    root = fake()
    out = tmp_path / "slice"
    record = make_slice(flat_dir, out, root)
    flat = json.loads((flat_dir / "flat.json").read_bytes())
    assert set(record) == RECORD_KEYS
    assert (record["schema"], record["algorithm"]) == (RECORD_SCHEMA, SLICE_ALGORITHM_VERSION)
    assert record["schema"] == "tdmg.slice/1" and record["algorithm"] == "slice-1"
    assert record["links"] == {"flat_id": flat["flat_id"],
                               "flat_record_sha256": _sha((flat_dir / "flat.json").read_bytes()),
                               "model_stl_sha256": flat["outputs"]["model.stl"],
                               "selection_id": flat["selection"]["selection_id"]}
    z = stl_z_range((flat_dir / "model.stl").read_bytes())
    assert z == (0.0, 3.0)                         # 3.0 is exact in float32
    assert record["params"] == {"timeout_s": {"value": 300, "rule": "slicer.orca.timeout_s"},
                                "thickness_mm": 3.0,
                                "stl_z_mm": {"min": 0.0, "max": 3.0, "extent": 3.0},
                                "expected_layer_counts": [15]}
    pin = fake.pin
    assert record["slicer"] == {
        "name": "OrcaSlicer", "version": "2.5.0", "pin": "orcaslicer-2.5.0",
        "exe_sha256": pin.exe.sha256,
        "libraries": {"app/OrcaSlicer.dll": pin.libraries[0].sha256},
        "app_tree_sha256": pin.app_tree.sha256,
        "app_tree_verified": True,
        "profiles": {k: {"name": p.preset, "file": p.file, "sha256": p.sha256}
                     for k, p in pin.profiles.flat.items()},
        "platform": platform_key()}
    # Placeholders only: no path from this machine.
    assert record["command"] == [
        "<orca-slicer.exe>", "<model.stl>", "--load-settings",
        "<machine.json>;<process.json>", "--load-filaments", "<filament.json>", "--slice",
        "0", "--outputdir", "<outdir>", "--export-statistics", "--logfile", "<slicer.log>"]
    assert record["exit"]["signed"] == 0 and record["exit"]["name"] == "CLI_SUCCESS"
    assert record["exit"]["timed_out"] is False
    assert record["stats"]["layer_count"] == 15
    ids = [c["id"] for c in record["checks"]]
    assert "F6.slicer" not in ids and ids[-5:] == F6_IDS
    assert ids[:-5] == [c["id"] for c in flat["checks"] if c["id"] != "F6.slicer"]
    assert {c["id"]: c["status"] for c in record["checks"][-5:]} == {
        "F6.slicer_exit": "PASS", "F6.gcode_present": "PASS", "F6.layer_count": "PASS",
        "F6.single_object": "PASS", "F6.portability": "UNKNOWN"}
    assert record["verdict"] == "NOT CERTIFIED"
    # The reason is derived from the required checks that are not PASS, in check order.
    assert record["certification"] == ("NOT CERTIFIED: F3.thin_regions UNKNOWN, "
                                        "F6.portability UNKNOWN")
    assert record["environment"]["platform"] == platform.platform()
    assert record["log_written"] is False
    files = sorted(p.name for p in out.iterdir())
    assert files == ["plate_1.gcode", "plate_1.statistics.json", "slice.json"]
    assert record["outputs"] == {n: _sha((out / n).read_bytes()) for n in files
                                 if n != "slice.json"}
    assert record["gcode"]["sha256"] == record["outputs"]["plate_1.gcode"]
    assert record["gcode"]["normalised_lines"] == 1
    assert (record["gcode"]["file"], record["gcode"]["quarantined"]) == ("plate_1.gcode", False)
    assert json.loads((out / "slice.json").read_bytes()) == record
    assert str(tmp_path) not in (out / "slice.json").read_text(encoding="utf-8")


def test_slice_id_is_the_hash_of_its_identity(flat_dir, fake, tmp_path):
    record = make_slice(flat_dir, tmp_path / "slice", fake())
    pin = fake.pin
    identity = {"algorithm": "slice-1", "flat_id": record["links"]["flat_id"],
                "model_stl_sha256": record["links"]["model_stl_sha256"],
                "slicer": {"version": "2.5.0", "exe_sha256": pin.exe.sha256,
                           "libraries": {"app/OrcaSlicer.dll": pin.libraries[0].sha256},
                           "app_tree_sha256": pin.app_tree.sha256,
                           "app_tree_verified": True},
                "profiles": {k: p.sha256 for k, p in pin.profiles.flat.items()},
                "flat_record_sha256": record["links"]["flat_record_sha256"],
                "command": record["command"]}
    assert record["slice_id"] == _sha(canonical_json(identity))


def _box_stl(height):
    return trimesh.creation.box((20, 20, height)).apply_translation(
        (10, 10, height / 2)).export(file_type="stl")


def test_layer_counts_come_from_the_stl_as_stored():
    # Two thicknesses either side of 100.1 mm (q = 499.5 at 0.2/0.2 mm) are stored as the
    # same float32 STL, so they must get the same allowed set, with both neighbours.
    a, b = _box_stl(100.099999), _box_stl(100.100001)
    assert a == b
    assert allowed_layer_counts(a, PROCESS) == allowed_layer_counts(b, PROCESS) == {500, 501}
    assert allowed_layer_counts(_box_stl(3.0), PROCESS) == {15}
    assert allowed_layer_counts(_box_stl(3.05), PROCESS) == {15}
    assert allowed_layer_counts(_box_stl(1.1), PROCESS) == {5, 6}


def test_flat_identity_is_the_definition_make_flat_uses(flat_dir):
    flat = json.loads((flat_dir / "flat.json").read_bytes())
    assert flat_identity(flat["algorithm"], flat["selection"]["mask_pixels_sha256"],
                         flat["params"]) == flat["flat_id"]


def test_a_different_flat_record_gives_a_different_slice_id(flat_dir, fake, tmp_path):
    root = fake()
    a = make_slice(flat_dir, tmp_path / "a", root)
    copy = _copy_flat(flat_dir, tmp_path)
    record = json.loads((copy / "flat.json").read_bytes())
    record["review"] = record["review"] + " (edited)"        # not part of flat_id
    (copy / "flat.json").write_bytes(json.dumps(record).encode())
    b = make_slice(copy, tmp_path / "b", root)
    assert a["links"]["flat_id"] == b["links"]["flat_id"]
    assert a["links"]["flat_record_sha256"] != b["links"]["flat_record_sha256"]
    assert a["slice_id"] != b["slice_id"]


def test_slicer_command_is_the_verified_exe(tmp_path):
    exe = tmp_path / "app" / "orca-slicer.exe"
    slicer = Slicer(tmp_path, exe, {}, {}, PIN)
    assert slicer_command(slicer) == [str(exe)]


def test_repeat_runs_differ_only_in_the_timestamp(flat_dir, fake, tmp_path):
    root = fake()
    a = make_slice(flat_dir, tmp_path / "a", root)
    b = make_slice(flat_dir, tmp_path / "b", root, timeout_s=120)
    # The fake writes the time to the microsecond, so the raw G-code differs.
    assert a["gcode"]["sha256"] != b["gcode"]["sha256"]
    assert a["gcode"]["normalised_sha256"] == b["gcode"]["normalised_sha256"]
    # The timeout does not change the output, so it is not part of the id.
    assert b["params"]["timeout_s"] == {"value": 120.0, "rule": None}
    assert a["slice_id"] == b["slice_id"]


def test_a_timeout_is_recorded(flat_dir, fake, tmp_path):
    out = tmp_path / "slice"
    record = make_slice(flat_dir, out, fake(sleep=30), timeout_s=0.5)
    checks = by_id(record)
    assert record["exit"]["timed_out"] is True and record["exit"]["raw"] is None
    assert checks["F6.slicer_exit"]["status"] == "FAIL"
    # An explicit timeout: no rule set it, so the check names none.
    assert checks["F6.slicer_exit"]["rule"] is None
    assert checks["F6.slicer_exit"]["threshold"] == 0.5
    assert "F6.slicer_exit FAIL" in record["certification"]


def test_the_default_timeout_check_names_the_rule(flat_dir, fake, tmp_path, monkeypatch):
    rules = load_rules()
    short = rules["slicer.orca.timeout_s"].model_copy(update={"default": 0.5})
    monkeypatch.setattr(tdmg.slicing, "load_rules", lambda: {**rules,
                                                             "slicer.orca.timeout_s": short})
    record = make_slice(flat_dir, tmp_path / "slice", fake(sleep=30))
    assert by_id(record)["F6.slicer_exit"]["rule"] == "slicer.orca.timeout_s"


def test_the_log_is_copied_when_the_slicer_writes_one(flat_dir, fake, tmp_path):
    out = tmp_path / "slice"
    record = make_slice(flat_dir, out, fake(log=True))
    assert record["log_written"] is True
    # The fake writes it in text mode, so Windows gives CRLF; the bytes are copied as is.
    assert (out / "slicer.log").read_bytes().replace(b"\r\n", b"\n") == b"fake log\n"
    assert "slicer.log" in record["outputs"]


def test_a_failed_slice_writes_the_record_and_fails(flat_dir, fake, tmp_path):
    out = tmp_path / "slice"
    record = make_slice(flat_dir, out, fake(exit=-50, gcode=False, stats=False,
                                            stderr="plate 1: No object is fully inside"))
    checks = by_id(record)
    assert checks["F6.slicer_exit"]["status"] == "FAIL"
    assert record["exit"]["name"] == "CLI_NO_SUITABLE_OBJECTS"
    assert record["stats"] is None and record["gcode"] is None
    assert record["stderr_tail"].endswith("No object is fully inside")
    assert record["certification"].startswith("NOT CERTIFIED: F3.thin_regions UNKNOWN, "
                                              "F6.slicer_exit FAIL, F6.gcode_present FAIL")
    # Like the real slicer, the fake writes a log when it fails.
    assert record["log_written"] is True
    assert sorted(p.name for p in out.iterdir()) == ["slice.json", "slicer.log"]


def test_gcode_from_a_failed_slice_is_renamed(flat_dir, fake, tmp_path):
    out = tmp_path / "slice"
    record = make_slice(flat_dir, out, fake(exit=-100))
    assert by_id(record)["F6.slicer_exit"]["status"] == "FAIL"
    names = sorted(p.name for p in out.iterdir())
    assert "plate_1.gcode" not in names and "plate_1.gcode.failed" in names
    assert record["gcode"]["file"] == "plate_1.gcode.failed"
    assert record["gcode"]["quarantined"] is True
    assert record["gcode"]["sha256"] == record["outputs"]["plate_1.gcode.failed"]


def test_a_truncated_print_with_exit_0_is_quarantined(flat_dir, fake, tmp_path):
    out = tmp_path / "slice"
    record = make_slice(flat_dir, out, fake(layers=2))
    assert by_id(record)["F6.slicer_exit"]["status"] == "PASS"
    assert by_id(record)["F6.layer_count"]["status"] == "FAIL"
    names = sorted(p.name for p in out.iterdir())
    assert names == ["plate_1.gcode.failed", "plate_1.statistics.json", "slice.json"]
    assert (record["gcode"]["file"], record["gcode"]["quarantined"]) == (
        "plate_1.gcode.failed", True)


def _two_body_flat(tmp_path):
    rgba = np.zeros((60, 100, 4), np.uint8)
    rgba[10:50, 5:45] = (230, 20, 20, 255)
    rgba[10:50, 55:95] = (230, 20, 20, 255)
    intake = _intake(rgba)
    sel = tmp_path / "sel2"
    write_selection(intake, select_subject(intake, SelectionSpec()), sel)
    out = tmp_path / "flat2"
    make_flat(sel, 60.0, 3.0, out)
    return out


def test_several_bodies_are_named_in_the_reason(fake, tmp_path):
    flat2 = _two_body_flat(tmp_path)
    record = make_slice(flat2, tmp_path / "slice", fake())
    assert by_id(record)["F4.body_count"]["status"] == "UNKNOWN"
    assert "F4.body_count UNKNOWN" in record["certification"]


# --- Refusals: nothing written -----------------------------------------------------------

def _copy_flat(flat_dir, tmp_path):
    copy = tmp_path / "flat"
    shutil.copytree(flat_dir, copy)
    return copy


def test_a_model_changed_after_flat_is_refused(flat_dir, fake, tmp_path):
    copy = _copy_flat(flat_dir, tmp_path)
    (copy / "model.stl").write_bytes((copy / "model.stl").read_bytes()[:-50])
    with pytest.raises(SlicerError, match="model.stl.*does not match flat.json"):
        make_slice(copy, tmp_path / "slice", fake())
    assert not (tmp_path / "slice").exists()


def _set_check(check_id, **fields):
    def change(record):
        for c in record["checks"]:
            if c["id"] == check_id:
                c.update(fields)
    return change


@pytest.mark.parametrize(("change", "message"), [
    (lambda r: r.update(schema="tdmg.flat/0"), "schema"),
    (lambda r: r.pop("flat_id"), "flat_id"),
    (lambda r: r.update(flat_id="ab" * 31), "flat_id"),
    (lambda r: r["selection"].pop("selection_id"), "selection_id"),
    (lambda r: r["selection"].update(selection_id="x" * 64), "selection_id"),
    (lambda r: r["params"].pop("thickness_mm"), "thickness_mm"),
    (lambda r: r["params"].update(thickness_mm=True), "thickness_mm"),
    (lambda r: r["params"].update(thickness_mm="3"), "thickness_mm"),
    # The reviewer's Experiment A: F3 forged to PASS and the thickness edited.
    (lambda r: (_set_check("F3.thin_regions", status="PASS")(r),
                r["params"].update(thickness_mm=2.0)), "flat.json is inconsistent"),
    (lambda r: r["params"].update(width_mm=61.0), "flat.json is inconsistent"),
    (lambda r: r.update(checks=["F1.finite PASS"]), "check"),
    (_set_check("F1.finite", status="OK"), "status"),
    (_set_check("F1.finite", extra=1), "check"),
])
def test_a_bad_flat_record_is_refused(flat_dir, fake, tmp_path, change, message):
    copy = _copy_flat(flat_dir, tmp_path)
    record = json.loads((copy / "flat.json").read_bytes())
    change(record)
    (copy / "flat.json").write_bytes(json.dumps(record).encode())
    with pytest.raises(SlicerError, match=message):
        make_slice(copy, tmp_path / "slice", fake())
    assert not (tmp_path / "slice").exists()


def test_a_missing_flat_record_is_refused(fake, tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(SlicerError, match="flat.json"):
        make_slice(tmp_path / "empty", tmp_path / "slice", fake())


def test_a_non_empty_output_folder_is_refused_before_slicing(flat_dir, fake, tmp_path):
    out = tmp_path / "slice"
    out.mkdir()
    (out / "x").write_bytes(b"")
    ran = tmp_path / "ran.txt"
    with pytest.raises(SlicerError, match="not empty"):
        make_slice(flat_dir, out, fake(cwd_file=str(ran)))
    assert not ran.exists()                              # the slicer never started


def test_a_profile_changed_after_locate_is_refused(flat_dir, fake, tmp_path, monkeypatch):
    root = fake()
    real_locate = tdmg.slicing.locate

    def locate_then_change(slicer_dir, pin, full_tree=True):
        found = real_locate(slicer_dir, pin, full_tree)
        (root / "profiles-flat" / "process.json").write_bytes(b'{"layer_height": "0.1"}')
        return found
    monkeypatch.setattr(tdmg.slicing, "locate", locate_then_change)
    with pytest.raises(SlicerError, match="process.json.*does not match the pin"):
        make_slice(flat_dir, tmp_path / "slice", root)
    assert not (tmp_path / "slice").exists()


def test_a_changed_install_is_refused(flat_dir, fake, tmp_path):
    root = fake()
    (root / "app" / "OrcaSlicer.dll").write_bytes(b"patched")
    with pytest.raises(SlicerError, match="OrcaSlicer.dll.*does not match the pin"):
        make_slice(flat_dir, tmp_path / "slice", root)
    assert not (tmp_path / "slice").exists()


@pytest.mark.parametrize("change", ["changed", "added"])
def test_the_whole_app_tree_is_checked_unless_skipped(flat_dir, fake, tmp_path, change):
    root = fake()
    good = make_slice(flat_dir, tmp_path / "good", root)
    if change == "changed":           # an auxiliary file: not checked by name, only in the tree
        (root / "app" / "resources" / "x.txt").write_bytes(b"changed")
    else:
        (root / "app" / "extra.dll").write_bytes(b"new")
    with pytest.raises(SlicerError, match="app tree.*does not match the pin"):
        make_slice(flat_dir, tmp_path / "refused", root)
    assert not (tmp_path / "refused").exists()
    skipped = make_slice(flat_dir, tmp_path / "skipped", root, check_tree=False)
    assert skipped["slicer"]["app_tree_verified"] is False
    assert good["slicer"]["app_tree_verified"] is True
    # The flag is part of slice_id: an unverified tree is a different claim.
    assert skipped["slice_id"] != good["slice_id"]


def test_cli_skip_tree_check(flat_dir, fake, tmp_path):
    root = fake()
    (root / "app" / "extra.dll").write_bytes(b"new")
    r = _slice(flat_dir, tmp_path / "a", "--slicer-dir", str(root))
    assert r.exit_code == 2 and "app tree" in r.stderr
    r = _slice(flat_dir, tmp_path / "b", "--slicer-dir", str(root), "--skip-tree-check")
    assert r.exit_code == 0, r.output
    assert "app tree not verified (--skip-tree-check)" in r.stdout
    assert json.loads((tmp_path / "b" / "slice.json").read_bytes())[
        "slicer"]["app_tree_verified"] is False


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_a_bad_timeout_is_refused(flat_dir, fake, tmp_path, value):
    with pytest.raises(SlicerError, match="timeout_s"):
        make_slice(flat_dir, tmp_path / "slice", fake(), timeout_s=value)


# --- The command line -------------------------------------------------------------------

def _plain(text: str) -> str:
    return " ".join(ANSI.sub("", text).split())


def _slice(flat_dir, out, *extra):
    return runner.invoke(app, ["slice", str(flat_dir), "--out", str(out), *extra])


def test_cli_exit_0_prints_the_summary(flat_dir, fake, tmp_path):
    out = tmp_path / "slice"
    r = _slice(flat_dir, out, "--slicer-dir", str(fake()))
    assert r.exit_code == 0, r.output
    record = json.loads((out / "slice.json").read_bytes())
    text = r.stdout
    assert text.startswith("NOT CERTIFIED: F3.thin_regions UNKNOWN, F6.portability UNKNOWN\n")
    assert "do not print" not in text
    assert "slicer exit 0 (CLI_SUCCESS)" in text
    assert "15 layers, 766.1 s, 3.727 g (slicer estimates)" in text
    assert "  F6.portability UNKNOWN: second slicer (PrusaSlicer) not run" in text
    assert "F6.layer_count" not in text            # PASS checks are not listed
    assert f"slice_id {record['slice_id']}" in text
    assert f"wrote {out / 'slice.json'}" in text


def test_cli_exit_1_on_a_truncated_print(flat_dir, fake, tmp_path):
    out = tmp_path / "slice"
    r = _slice(flat_dir, out, "--slicer-dir", str(fake(layers=2)))
    assert r.exit_code == 1, r.output
    assert "F6.layer_count FAIL - measured 2; threshold [15]" in r.stdout
    assert ("a check FAILed: do not print this G-code; it is kept as plate_1.gcode.failed"
            in r.stdout)
    assert (out / "slice.json").is_file() and not (out / "plate_1.gcode").exists()


def test_cli_exit_1_when_a_flat_check_failed(fake, tmp_path, monkeypatch):
    rules = load_rules()
    tiny = rules["slicer.orca.max_triangles_per_plate"].model_copy(update={"default": 4})
    monkeypatch.setattr(tdmg.flat, "load_rules",
                        lambda: {**rules, "slicer.orca.max_triangles_per_plate": tiny})
    sel = write_roadie_selection(tmp_path / "sel")
    make_flat(sel, 60.0, 3.0, tmp_path / "flat")
    out = tmp_path / "slice"
    r = _slice(tmp_path / "flat", out, "--slicer-dir", str(fake()))
    assert r.exit_code == 1, r.output
    assert "F5.triangles FAIL" in r.stdout
    assert "a check FAILed: do not print this G-code" in r.stdout
    # The slicer itself succeeded; the inherited FAIL still quarantines the G-code.
    assert sorted(p.name for p in out.iterdir()) == [
        "plate_1.gcode.failed", "plate_1.statistics.json", "slice.json"]
    assert json.loads((out / "slice.json").read_bytes())["gcode"]["quarantined"] is True


def test_cli_timeout_option(flat_dir, fake, tmp_path):
    out = tmp_path / "slice"
    r = _slice(flat_dir, out, "--slicer-dir", str(fake(sleep=30)), "--timeout-s", "0.5")
    assert r.exit_code == 1, r.output
    assert "F6.slicer_exit FAIL" in r.stdout and "0.5 s timeout" in r.stdout


def test_cli_exit_2_without_a_slicer_folder(flat_dir, fake, tmp_path):
    fake()
    out = tmp_path / "slice"
    r = _slice(flat_dir, out)
    assert r.exit_code == 2, r.output
    err = _plain(r.stderr)
    assert "--slicer-dir" in err and "TDMG_ORCASLICER_DIR" in err
    assert "scripts/setup_orcaslicer.py" in err
    assert not out.exists()


def test_cli_exit_2_for_a_missing_slicer_folder(flat_dir, fake, tmp_path):
    fake()
    r = _slice(flat_dir, tmp_path / "slice", "--slicer-dir", str(tmp_path / "nowhere"))
    assert r.exit_code == 2 and "setup_orcaslicer.py" in r.stderr
    assert not (tmp_path / "slice").exists()


def test_cli_exit_2_for_a_tampered_model(flat_dir, fake, tmp_path):
    copy = _copy_flat(flat_dir, tmp_path)
    (copy / "model.stl").write_bytes(b"solid nothing\nendsolid nothing\n")
    r = _slice(copy, tmp_path / "slice", "--slicer-dir", str(fake()))
    assert r.exit_code == 2 and "does not match flat.json" in r.stderr
    assert "Traceback" not in r.output
    assert not (tmp_path / "slice").exists()


def test_cli_help_documents_the_exit_codes():
    narrow = CliRunner(env={"NO_COLOR": "1", "FORCE_COLOR": None, "COLUMNS": "80"})
    text = _plain(narrow.invoke(app, ["slice", "--help"]).output)
    for phrase in ("0 files written, and no check FAILed", "1 files written, and at least one",
                   "2 input or setup error", "Exit 0 does not mean the part is certified"):
        assert phrase in text


def test_the_required_checks_are_the_f6_checks():
    assert SLICE_REQUIRED_EXTRA == frozenset(F6_IDS)


# --- Integration: the real slicer -------------------------------------------------------

@pytest.mark.slicer
@pytest.mark.skipif(not os.environ.get("TDMG_ORCASLICER_DIR"),
                    reason="TDMG_ORCASLICER_DIR is not set to a verified OrcaSlicer install")
def test_roadie_slices_with_the_real_slicer(tmp_path):
    from test_cli import _selection

    sel = _selection(tmp_path)
    flat_out = tmp_path / "flat"
    r = runner.invoke(app, ["flat", str(sel), "--width-mm", "60", "--thickness-mm", "3",
                            "--out", str(flat_out)])
    assert r.exit_code == 0, r.output
    out = tmp_path / "slice"
    r = _slice(flat_out, out)
    assert r.exit_code == 0, r.output
    record = json.loads((out / "slice.json").read_bytes())
    status = {c["id"]: c["status"] for c in record["checks"] if c["id"].startswith("F6.")}
    assert status == {"F6.slicer_exit": "PASS", "F6.gcode_present": "PASS",
                      "F6.layer_count": "PASS", "F6.single_object": "PASS",
                      "F6.portability": "UNKNOWN"}
    assert record["stats"]["layer_count"] == 15
    assert record["slicer"]["exe_sha256"] == PIN.exe.sha256
    assert record["slicer"]["app_tree_verified"] is True

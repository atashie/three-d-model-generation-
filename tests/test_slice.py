"""tdmg slice and make_slice, with the fake slicer (docs/plans/2026-11-10-slicer-check.md).

The fake install has a pin made for it (tdmg.slicing.load_pin is replaced), and the
command is [sys.executable, tests/fake_orca.py] (tdmg.slicing.slicer_command is replaced).
The fake reads its behaviour from $TDMG_FAKE_ORCA_CONTROL. The fake PrusaSlicer
(tests/fake_prusa.py, fixture prusa) works the same way, with $TDMG_FAKE_PRUSA_CONTROL.
The integration tests at the end run the real slicers when TDMG_ORCASLICER_DIR (and
TDMG_PRUSASLICER_DIR) point at verified installs.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
import shapely
import trimesh
from gcode_fixtures import gcode, layer, solid
from shapely import affinity
from test_make_flat import write_roadie_selection
from test_selection import _intake
from typer.testing import CliRunner

import tdmg.flat
import tdmg.printed
import tdmg.slicing
from tdmg.cli import app
from tdmg.flat import flat_identity, make_flat
from tdmg.paths import REPO_ROOT
from tdmg.portability import PORTABILITY_MEANING, PRUSA_GCODE_NOTE, load_prusa_pin
from tdmg.printed import model_section
from tdmg.records import canonical_json
from tdmg.rules import load_rules
from tdmg.selection import SelectionSpec, select_subject, write_selection
from tdmg.slicer import OUTPUT_TAIL_CHARS, Slicer, SlicerError, load_pin, platform_key
from tdmg.slicing import (
    DO_NOT_PRINT,
    PRINT_THIS,
    PRINTABLE_MEANING,
    RECORD_SCHEMA,
    SLICE_ALGORITHM_VERSION,
    SLICE_REQUIRED_CHECKS,
    SLICE_REQUIRED_EXTRA,
    allowed_layer_counts,
    make_slice,
    slicer_command,
    stl_z_range,
)

FAKE = REPO_ROOT / "tests" / "fake_orca.py"
PIN = load_pin()
# The three process keys make_slice reads, with the A1 values (see tests/test_slicer.py
# and research/verification/2026-11-10-thin-walls/slicer-settings.txt).
PROCESS = {"layer_height": "0.2", "initial_layer_print_height": "0.2",
           "elefant_foot_compensation": "0.075"}
# The filament keys make_slice reads: the A1 PLA Basic values (profiles-flat/filament.json).
FILAMENT = {"filament_diameter": ["1.75"], "filament_flow_ratio": ["0.98"]}
# The machine keys make_slice reads: the A1's plate, height and nozzle
# (profiles-flat/machine.json).
MACHINE = {"printable_area": ["0x0", "256x0", "256x256", "0x256"], "printable_height": "256",
           "nozzle_diameter": ["0.4"]}
FILES = {"machine.json": json.dumps(MACHINE).encode(),
         "process.json": json.dumps(PROCESS).encode(),
         "filament.json": json.dumps(FILAMENT).encode()}
APP = {"orca-slicer.exe": b"exe", "OrcaSlicer.dll": b"dll", "resources/x.txt": b"x"}
F6_IDS = ["F6.slicer_exit", "F6.gcode_present", "F6.layer_count", "F6.single_object",
          "F6.portability"]
F3_IDS = ["F3.printed_connectivity", "F3.edge_coverage", "F3.edge_overprint"]
RECORD_KEYS = {"schema", "tdmg_version", "algorithm", "slice_id", "links", "params", "slicer",
               "command", "exit", "stats", "checks", "verdict", "certification", "gcode",
               "stderr_tail", "log_written", "outputs", "environment", "review",
               "printed", "certification_note", "portability"}
NOT_CONFIGURED = ("PrusaSlicer is not configured: pass --prusaslicer-dir DIR or set "
                  "TDMG_PRUSASLICER_DIR; install it with `uv run python "
                  "scripts/setup_prusaslicer.py --dest DIR`")
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
    monkeypatch.delenv("TDMG_PRUSASLICER_DIR", raising=False)   # tests opt in (fixture prusa)
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
    assert record["schema"] == "tdmg.slice/1" and record["algorithm"] == "slice-5"
    assert record["links"] == {"flat_id": flat["flat_id"],
                               "flat_record_sha256": _sha((flat_dir / "flat.json").read_bytes()),
                               "model_stl_sha256": flat["outputs"]["model.stl"],
                               "selection_id": flat["selection"]["selection_id"]}
    z = stl_z_range((flat_dir / "model.stl").read_bytes())
    assert z == (0.0, 3.0)                         # 3.0 is exact in float32
    assert record["params"] == {"timeout_s": {"value": 300, "rule": "slicer.orca.timeout_s"},
                                "prusaslicer_timeout_s": {"value": 300,
                                                          "rule": "slicer.prusa.timeout_s"},
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
    assert "F6.slicer" not in ids and ids[-5:] == F6_IDS and ids[-8:-5] == F3_IDS
    assert ids[:-8] == [c["id"] for c in flat["checks"] if c["id"] != "F6.slicer"]
    assert {c["id"]: c["status"] for c in record["checks"][-5:]} == {
        "F6.slicer_exit": "PASS", "F6.gcode_present": "PASS", "F6.layer_count": "PASS",
        "F6.single_object": "PASS", "F6.portability": "UNKNOWN"}
    assert record["verdict"] == "NOT CERTIFIED"
    assert by_id(record)["F6.portability"]["note"] == NOT_CONFIGURED
    assert record["certification_note"] is None
    assert record["portability"]["configured"] is False
    assert record["portability"]["slicer"] is None and record["portability"]["gcode"] is None
    # The reason is derived from the required checks that are not PASS, in check order.
    # The fake's default G-code has no layer comments, so the F3 checks cannot measure it.
    assert record["certification"] == ("NOT CERTIFIED: F3.printed_connectivity UNKNOWN, "
                                        "F3.edge_coverage UNKNOWN, F3.edge_overprint UNKNOWN, "
                                        "F6.portability UNKNOWN")
    assert "no Z_HEIGHT" in by_id(record)["F3.edge_coverage"]["note"]
    assert record["printed"]["measured"] is False
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
    identity = {"algorithm": "slice-5", "flat_id": record["links"]["flat_id"],
                "model_stl_sha256": record["links"]["model_stl_sha256"],
                "slicer": {"version": "2.5.0", "exe_sha256": pin.exe.sha256,
                           "libraries": {"app/OrcaSlicer.dll": pin.libraries[0].sha256},
                           "app_tree_sha256": pin.app_tree.sha256,
                           "app_tree_verified": True},
                "profiles": {k: p.sha256 for k, p in pin.profiles.flat.items()},
                "flat_record_sha256": record["links"]["flat_record_sha256"],
                "command": record["command"],
                "f3": {"tolerance": {"rule": "acceptance.dimension.tolerance", "value_mm": 0.2},
                       "elefant_foot_compensation_mm": 0.075},
                "portability": None}           # PrusaSlicer not configured
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
    assert record["certification"].startswith(
        "NOT CERTIFIED: F3.printed_connectivity UNKNOWN, F3.edge_coverage UNKNOWN, "
        "F3.edge_overprint UNKNOWN, F6.slicer_exit FAIL, F6.gcode_present FAIL")
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


# --- F3 from the printed footprint (tdmg.printed) -----------------------------------------

PLATE_CENTRE = (128.0, 128.0)       # the A1 plate's centre, from MACHINE


@pytest.fixture(scope="module")
def square_flat(tmp_path_factory):
    """A 20 mm square (corners rounded by smoothing), 3 mm thick: 15 layers."""
    rgba = np.zeros((60, 60, 4), np.uint8)
    rgba[10:50, 10:50] = (230, 20, 20, 255)
    intake = _intake(rgba)
    sel = tmp_path_factory.mktemp("square") / "sel"
    write_selection(intake, select_subject(intake, SelectionSpec()), sel)
    out = tmp_path_factory.mktemp("square-flat") / "flat"
    make_flat(sel, 20.0, 3.0, out)
    return out


def _bed_section(flat_dir):
    """The model's section where the slicer puts it: its bounding box on the plate centre."""
    section = model_section((flat_dir / "model.stl").read_bytes(), 0.1)
    x0, y0, x1, y1 = section.bounds
    return affinity.translate(section, PLATE_CENTRE[0] - (x0 + x1) / 2,
                              PLATE_CENTRE[1] - (y0 + y1) / 2)


def _square_gcode(flat_dir, first=None, upper=None):
    """15 layers of walls and fill covering first (layer 1) and upper (layers 2-15); both
    are the model's section on the bed unless given."""
    bed = _bed_section(flat_dir)
    first = bed if first is None else first
    upper = bed if upper is None else upper
    return gcode([layer(0.2 * (i + 1), solid(first if i == 0 else upper)) for i in range(15)])


def test_a_covered_square_passes_both_f3_checks(square_flat, fake, tmp_path):
    out = tmp_path / "slice"
    record = make_slice(square_flat, out, fake(gcode_text=_square_gcode(square_flat)))
    checks = by_id(record)
    assert checks["F3.printed_connectivity"]["status"] == "PASS"
    coverage = checks["F3.edge_coverage"]
    assert coverage["status"] == "PASS"
    assert coverage["rule"] == "acceptance.dimension.tolerance"
    # The allowance: the tolerance, plus elefant_foot_compensation on the first layer.
    assert coverage["threshold"] == {"first_layer_mm": pytest.approx(0.275),
                                     "other_layers_mm": 0.2}
    # A square looks the same at every quarter turn, so any turn may be found (the turn is
    # tested on an L shape in tests/test_printed.py).
    assert coverage["measured"]["angle_deg"] in (0, 90, 180, 270)
    assert coverage["measured"]["max_gap_mm"] < 0.2
    assert "strength is not judged" in coverage["note"].lower()
    assert "bead model" in checks["F3.printed_connectivity"]["note"].lower()
    # Only the second slicer blocks certification now.
    assert record["certification"] == "NOT CERTIFIED: F6.portability UNKNOWN"
    assert record["verdict"] == "NOT CERTIFIED"
    thin = checks["F3.thin_regions"]
    assert thin["status"] == "UNKNOWN" and "information only" in thin["note"]
    printed = record["printed"]
    assert printed["measured"] is True and printed["reason"] is None
    assert [lay["z"] for lay in printed["layers"]] == pytest.approx(
        [0.2 * (i + 1) for i in range(15)])
    assert all(lay["parts"] == [1, 1] and lay["holes"] == [0, 0] for lay in printed["layers"])
    assert set(printed["layers"][0]) == {"z", "max_gap_mm", "parts", "holes", "unmatched",
                                         "max_over_mm"}
    assert checks["F3.edge_overprint"]["status"] == "PASS"
    assert all(lay["unmatched"] == 0 for lay in printed["layers"])
    assert printed["alignment"]["plate_centre_mm"] == list(PLATE_CENTRE)
    assert printed["alignment"]["angle_deg"] == coverage["measured"]["angle_deg"]
    assert len(printed["alignment"]["scores"]) == 4
    assert printed["allowance_mm"] == {"first_layer": pytest.approx(0.275),
                                       "other_layers": 0.2, "elefant_foot_compensation": 0.075}
    assert (record["gcode"]["file"], record["gcode"]["quarantined"]) == ("plate_1.gcode", False)
    assert json.loads((out / "slice.json").read_bytes()) == record


def _to_bed(record, point):
    """A model point in bed mm, by the record's alignment."""
    a = record["printed"]["alignment"]
    moved = affinity.translate(affinity.rotate(shapely.Point(point), a["angle_deg"],
                                               origin=tuple(a["model_bbox_centre_mm"])),
                               *a["shift_mm"])
    return [moved.x, moved.y]


def _split(flat_dir):
    bed = _bed_section(flat_dir)
    x0, y0, x1, y1 = bed.bounds
    cx = (x0 + x1) / 2
    return cx, bed.difference(shapely.box(cx - 0.5, y0 - 1, cx + 0.5, y1 + 1))


def test_a_split_print_fails_connectivity_and_is_quarantined(square_flat, fake, tmp_path):
    cx, split = _split(square_flat)
    out = tmp_path / "slice"
    record = make_slice(square_flat, out,
                        fake(gcode_text=_square_gcode(square_flat, upper=split)))
    c = by_id(record)["F3.printed_connectivity"]
    assert c["status"] == "FAIL"
    m = c["measured"]
    assert (m["layers"], m["layers_mismatched"], m["first_z"]) == (15, 14, pytest.approx(0.4))
    assert (m["parts_model"], m["parts_printed"], m["holes_model"], m["holes_printed"]) == (
        1, 2, 0, 0)
    assert [(u["what"], u["overlaps"]) for u in m["unmatched"]] == [("model part", 2)]
    assert _to_bed(record, m["largest_gap_at_model_mm"])[0] == pytest.approx(cx, abs=0.5)
    assert "model part overlapping 2 at model" in c["note"]
    assert "z = 0.4 mm" in c["note"] and "2 printed part(s)" in c["note"]
    assert "F3.printed_connectivity FAIL" in record["certification"]
    assert sorted(p.name for p in out.iterdir()) == [
        "plate_1.gcode.failed", "plate_1.statistics.json", "slice.json"]
    assert record["gcode"]["quarantined"] is True


def test_cli_exit_1_on_an_f3_fail(square_flat, fake, tmp_path):
    _, split = _split(square_flat)
    out = tmp_path / "slice"
    r = _slice(square_flat, out, "--slicer-dir",
               str(fake(gcode_text=_square_gcode(square_flat, upper=split))))
    assert r.exit_code == 1, r.output
    assert "F3.printed_connectivity FAIL - measured" in r.stdout
    assert "do not print this G-code" in r.stdout
    assert not (out / "plate_1.gcode").exists()


def test_an_unprinted_corner_fails_coverage_only(square_flat, fake, tmp_path):
    bed = _bed_section(square_flat)
    _, _, x1, y1 = bed.bounds
    clipped = bed.difference(shapely.box(x1 - 2, y1 - 2, x1 + 1, y1 + 1))
    record = make_slice(square_flat, tmp_path / "slice",
                        fake(gcode_text=_square_gcode(square_flat, upper=clipped)))
    checks = by_id(record)
    assert checks["F3.printed_connectivity"]["status"] == "PASS"   # still one part
    c = checks["F3.edge_coverage"]
    assert c["status"] == "FAIL"
    m = c["measured"]
    assert m["max_gap_mm"] > 1 and m["layers_over"] == 14
    assert m["worst_z"] > 0.3                    # one of the 14 identical upper layers
    assert m["at_bed_mm"][0] > x1 - 2 and m["at_bed_mm"][1] > y1 - 2
    # The model point is the bed point under the recorded alignment.
    assert _to_bed(record, m["at_model_mm"]) == pytest.approx(m["at_bed_mm"], abs=1e-9)
    assert record["gcode"]["quarantined"] is True


@pytest.mark.parametrize(("where", "gap", "status"), [
    # Inside 0.2 + 0.075 mm on the first layer with the 0.025 mm sampling bound added.
    ("first", 0.24, "PASS"),
    ("first", 0.30, "FAIL"),
    ("upper", 0.25, "FAIL"),     # above the first layer the allowance is 0.2 mm
])
def test_the_first_layer_is_allowed_the_elephant_foot(square_flat, fake, tmp_path, where, gap,
                                                      status):
    shrunk = _bed_section(square_flat).buffer(-gap)
    text = (_square_gcode(square_flat, first=shrunk) if where == "first"
            else _square_gcode(square_flat, upper=shrunk))
    record = make_slice(square_flat, tmp_path / "slice", fake(gcode_text=text))
    c = by_id(record)["F3.edge_coverage"]
    assert c["status"] == status
    m = c["measured"]
    if where == "first":
        assert m["worst_z"] == pytest.approx(0.2)
    else:
        assert m["worst_z"] > 0.3                # one of the 14 identical upper layers
    assert m["max_gap_mm"] == pytest.approx(gap, abs=0.01)
    assert m["allowance_mm"] == pytest.approx(0.275 if where == "first" else 0.2)
    assert by_id(record)["F3.printed_connectivity"]["status"] == "PASS"


def test_unsupported_gcode_leaves_f3_unknown(square_flat, fake, tmp_path):
    text = _square_gcode(square_flat).replace("M83", "M82")
    record = make_slice(square_flat, tmp_path / "slice", fake(gcode_text=text))
    for cid in F3_IDS:
        check = by_id(record)[cid]
        assert check["status"] == "UNKNOWN" and "absolute extrusion" in check["note"]
    assert record["printed"]["measured"] is False
    assert "absolute extrusion" in record["printed"]["reason"]
    assert record["certification"] == ("NOT CERTIFIED: F3.printed_connectivity UNKNOWN, "
                                       "F3.edge_coverage UNKNOWN, F3.edge_overprint UNKNOWN, "
                                       "F6.portability UNKNOWN")
    assert record["gcode"]["quarantined"] is False          # UNKNOWN is not a FAIL


def test_f3_is_not_measured_after_a_failed_slice(square_flat, fake, tmp_path):
    record = make_slice(square_flat, tmp_path / "slice",
                        fake(exit=-100, gcode_text=_square_gcode(square_flat)))
    for cid in F3_IDS:
        check = by_id(record)[cid]
        assert check["status"] == "UNKNOWN" and "the slicer failed" in check["note"]


def test_the_printed_analysis_is_not_part_of_slice_id(square_flat, fake, tmp_path):
    a = make_slice(square_flat, tmp_path / "a", fake(gcode_text=_square_gcode(square_flat)))
    b = make_slice(square_flat, tmp_path / "b", fake())
    assert by_id(a)["F3.edge_coverage"]["status"] != by_id(b)["F3.edge_coverage"]["status"]
    assert a["slice_id"] == b["slice_id"]          # an output, not part of the request


def _with_profile(fake, monkeypatch, kind: str, data: bytes) -> None:
    """Replace one of the fake install's profiles, and its hash in the fake pin."""
    (fake.root / "profiles-flat" / f"{kind}.json").write_bytes(data)
    flat = dict(fake.pin.profiles.flat)
    flat[kind] = flat[kind].model_copy(update={"sha256": _sha(data)})
    pin = fake.pin.model_copy(update={"profiles": fake.pin.profiles.model_copy(
        update={"flat": flat})})
    monkeypatch.setattr(tdmg.slicing, "load_pin", lambda: pin)


@pytest.mark.parametrize("value", [None, "-0.1", "nan", "abc"])
def test_a_bad_elefant_foot_compensation_is_refused(flat_dir, fake, tmp_path, monkeypatch,
                                                     value):
    root = fake()
    process = {k: v for k, v in PROCESS.items() if k != "elefant_foot_compensation"}
    if value is not None:
        process["elefant_foot_compensation"] = value
    _with_profile(fake, monkeypatch, "process", json.dumps(process).encode())
    with pytest.raises(SlicerError, match="elefant_foot_compensation"):
        make_slice(flat_dir, tmp_path / "slice", root)
    assert not (tmp_path / "slice").exists()


@pytest.mark.parametrize("data", [b"{}", b"[]", b"not json",
                                  json.dumps({"printable_area": ["0x0"]}).encode()])
def test_a_machine_profile_without_a_plate_is_refused(flat_dir, fake, tmp_path, monkeypatch,
                                                      data):
    root = fake()
    _with_profile(fake, monkeypatch, "machine", data)
    with pytest.raises(SlicerError, match="plate"):
        make_slice(flat_dir, tmp_path / "slice", root)
    assert not (tmp_path / "slice").exists()


def test_an_analysis_error_is_unknown_and_the_outputs_are_written(square_flat, fake, tmp_path,
                                                                  monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(tdmg.printed, "analyse", broken)
    out = tmp_path / "slice"
    record = make_slice(square_flat, out, fake(gcode_text=_square_gcode(square_flat)))
    for cid in F3_IDS:
        check = by_id(record)[cid]
        assert check["status"] == "UNKNOWN"
        assert "analysis error: RuntimeError: boom" in check["note"]
    assert sorted(p.name for p in out.iterdir()) == [
        "plate_1.gcode", "plate_1.statistics.json", "slice.json"]


def test_the_tolerance_used_is_part_of_slice_id(flat_dir, fake, tmp_path, monkeypatch):
    root = fake()
    a = make_slice(flat_dir, tmp_path / "a", root)
    rules = load_rules()
    wider = rules["acceptance.dimension.tolerance"].model_copy(update={"default": 0.3})
    monkeypatch.setattr(tdmg.slicing, "load_rules",
                        lambda: {**rules, "acceptance.dimension.tolerance": wider})
    b = make_slice(flat_dir, tmp_path / "b", root)
    assert a["slice_id"] != b["slice_id"]


def test_a_g_code_cut_short_fails_coverage_and_the_layer_count(square_flat, fake, tmp_path):
    # Codex item 2: the G-code stops after 2 of the model's 15 layers, while the statistics
    # still say 15. F3 reconciles the G-code with the model, and F6 with the statistics.
    bed = _bed_section(square_flat)
    text = gcode([layer(0.2 * (i + 1), solid(bed)) for i in range(2)])
    record = make_slice(square_flat, tmp_path / "slice", fake(gcode_text=text))
    checks = by_id(record)
    assert checks["F3.edge_coverage"]["status"] == "FAIL"
    assert "the G-code has 2 layers, not one of [15]" in checks["F3.edge_coverage"]["note"]
    assert checks["F6.layer_count"]["status"] == "FAIL"
    assert checks["F6.layer_count"]["measured"] == {"statistics": 15, "gcode": 2}
    assert record["gcode"]["quarantined"] is True


@pytest.mark.parametrize("filament", [{}, {"filament_diameter": ["1.75"]},
                                      {"filament_diameter": ["0"],
                                       "filament_flow_ratio": ["0.98"]},
                                      {"filament_diameter": ["x"],
                                       "filament_flow_ratio": ["0.98"]}])
def test_a_filament_profile_without_its_flow_is_refused(flat_dir, fake, tmp_path,
                                                        monkeypatch, filament):
    root = fake()
    _with_profile(fake, monkeypatch, "filament", json.dumps(filament).encode())
    with pytest.raises(SlicerError, match="filament"):
        make_slice(flat_dir, tmp_path / "slice", root)
    assert not (tmp_path / "slice").exists()


def test_the_required_checks_swap_thin_regions_for_the_printed_checks():
    assert set(F3_IDS) <= SLICE_REQUIRED_CHECKS
    assert "F3.thin_regions" not in SLICE_REQUIRED_CHECKS
    assert "F3.thin_regions" in tdmg.flat.FLAT_REQUIRED_CHECKS      # flat is unchanged
    assert SLICE_REQUIRED_CHECKS == (tdmg.flat.FLAT_REQUIRED_CHECKS
                                     - {"F6.slicer", "F3.thin_regions"}
                                     | set(F3_IDS) | SLICE_REQUIRED_EXTRA)


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
    assert text.startswith("NOT CERTIFIED: F3.printed_connectivity UNKNOWN, "
                           "F3.edge_coverage UNKNOWN, F3.edge_overprint UNKNOWN, "
                           "F6.portability UNKNOWN\n")
    assert "do not print" not in text
    assert "slicer exit 0 (CLI_SUCCESS)" in text
    assert "15 layers, 766.1 s, 3.727 g (slicer estimates)" in text
    assert f"  F6.portability UNKNOWN: {NOT_CONFIGURED}" in text
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
    for phrase in ("0 files written, and no required check FAILed",
                   "1 files written, and a required check FAILed",
                   "2 input or setup error", "Exit 0 does not mean the part is certified"):
        assert phrase in text


def test_the_required_checks_are_the_f6_checks():
    assert SLICE_REQUIRED_EXTRA == frozenset(F6_IDS)


# --- Integration: the real slicer -------------------------------------------------------

@pytest.mark.slicer
@pytest.mark.skipif(not os.environ.get("TDMG_ORCASLICER_DIR"),
                    reason="TDMG_ORCASLICER_DIR is not set to a verified OrcaSlicer install")
def test_roadie_slices_with_the_real_slicer(tmp_path, monkeypatch):
    from test_cli import _selection

    # OrcaSlicer alone: test_roadie_is_portable_with_the_real_prusaslicer adds PrusaSlicer.
    monkeypatch.delenv("TDMG_PRUSASLICER_DIR", raising=False)

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
    checks = by_id(record)
    f3 = [checks["F3.printed_connectivity"], checks["F3.edge_coverage"],
          checks["F3.edge_overprint"]]
    assert [c["status"] for c in f3] == ["PASS"] * 3, f3
    assert record["printed"]["measured"] is True and len(record["printed"]["layers"]) == 15
    assert record["gcode"]["quarantined"] is False
    assert record["slicer"]["app_tree_verified"] is True
    # The start G-code is the A1 template's, from the pinned flat profile (plan
    # 2026-11-13-color-slicing, Task 1): its first line, and the AMS load (M620 S...).
    machine = json.loads((Path(os.environ["TDMG_ORCASLICER_DIR"]) / PIN.profiles.folder
                          / PIN.profiles.flat["machine"].file).read_text(encoding="utf-8"))
    template = machine["machine_start_gcode"].splitlines()
    assert any(line.startswith("M620 S") for line in template)
    lines = (out / "plate_1.gcode").read_text(encoding="utf-8").splitlines()
    start = lines[:next(i for i, line in enumerate(lines) if line == "; CHANGE_LAYER")]
    assert template[0] in start
    assert any(line.startswith("M620 S") for line in start)


# --- F6.portability with the fake PrusaSlicer ---------------------------------------------

FAKE_PRUSA = REPO_ROOT / "tests" / "fake_prusa.py"
PRUSA_FILE = "prusaslicer.portability-only.gcode.txt"     # generic G-code, never printed
PRUSA_PIN = load_prusa_pin()
PRUSA_TOP = "PrusaSlicer-2.9.7/"
PRUSA_APP = {PRUSA_TOP + "prusa-slicer-console.exe": b"pexe",
             PRUSA_TOP + "PrusaSlicer.dll": b"pdll", PRUSA_TOP + "resources/y.txt": b"y"}
PRUSA_SETTINGS = {
    "--bed-shape": {"value": "0x0,256x0,256x256,0x256", "profile": "machine",
                    "key": "printable_area"},
    "--max-print-height": {"value": "256", "profile": "machine", "key": "printable_height"},
    "--nozzle-diameter": {"value": "0.4", "profile": "machine", "key": "nozzle_diameter"},
    "--layer-height": {"value": "0.2", "profile": "process", "key": "layer_height"},
    "--first-layer-height": {"value": "0.2", "profile": "process",
                             "key": "initial_layer_print_height"},
    "--filament-diameter": {"value": "1.75", "profile": "filament", "key": "filament_diameter"}}
PRUSA_GCODE_COMMAND = ["<prusa-slicer-console.exe>", "--export-gcode", "<model.stl>", "-o",
                       "<prusaslicer.portability-only.gcode.txt>", "--bed-shape",
                       "0x0,256x0,256x256,0x256",
                       "--max-print-height", "256", "--nozzle-diameter", "0.4",
                       "--layer-height", "0.2", "--first-layer-height", "0.2",
                       "--filament-diameter", "1.75"]


@pytest.fixture
def prusa(tmp_path, monkeypatch):
    """A fake PrusaSlicer install and its pin; returns a function that sets its behaviour."""
    root = tmp_path / "prusa"
    for rel, data in PRUSA_APP.items():
        (root / "app" / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / "app" / rel).write_bytes(data)
    pin = PRUSA_PIN.model_copy(update={
        "exe": PRUSA_PIN.exe.model_copy(update={
            "sha256": _sha(PRUSA_APP[PRUSA_TOP + "prusa-slicer-console.exe"])}),
        "libraries": [PRUSA_PIN.libraries[0].model_copy(update={
            "sha256": _sha(PRUSA_APP[PRUSA_TOP + "PrusaSlicer.dll"])})],
        "app_tree": PRUSA_PIN.app_tree.model_copy(update={"files": len(PRUSA_APP),
                                                          "sha256": _tree(PRUSA_APP)})})
    monkeypatch.setattr(tdmg.slicing, "load_prusa_pin", lambda: pin)
    monkeypatch.setattr(tdmg.slicing, "prusa_command",
                        lambda found: [sys.executable, str(FAKE_PRUSA)])
    control = tmp_path / "prusa-control.json"
    monkeypatch.setenv("TDMG_FAKE_PRUSA_CONTROL", str(control))

    def behave(**kwargs):
        control.write_bytes(json.dumps(kwargs).encode())
        return root
    behave.pin = pin
    behave.root = root
    return behave


def _prusa_identity(pin, verified=True):
    return {"version": "2.9.7", "exe_sha256": pin.exe.sha256,
            "libraries": {"app/PrusaSlicer-2.9.7/PrusaSlicer.dll": pin.libraries[0].sha256},
            "app_tree_sha256": pin.app_tree.sha256, "app_tree_verified": verified}


def test_portability_passes_with_the_fake(flat_dir, fake, prusa, tmp_path):
    out = tmp_path / "slice"
    record = make_slice(flat_dir, out, fake(), prusaslicer_dir=prusa())
    check = by_id(record)["F6.portability"]
    assert check["status"] == "PASS", check
    assert "generic G-code" in check["note"] and "not for the A1" in check["note"]
    # What it shows for STL, and what it does not: both slicers read STL with admesh.
    assert PORTABILITY_MEANING in check["note"]
    assert PORTABILITY_MEANING == (
        "a second slicer (PrusaSlicer 2.9.7) accepts model.stl as modelled (its admesh read "
        "agrees with tdmg's trimesh read: parts, facets, sizes, volume) and slices its full "
        "height, with extrusion on every layer, given the A1 bed, nozzle, layer and filament "
        "settings (its other settings are PrusaSlicer's defaults)")
    assert "share the admesh STL reader" in check["note"]
    assert "3MF output must re-run portability" in check["note"]
    mesh = json.loads((flat_dir / "flat.json").read_bytes())["mesh"]
    port = record["portability"]
    assert port["configured"] is True and port["reason"] is None
    assert port["slicer"] == {"name": "PrusaSlicer", "pin": "prusaslicer-2.9.7",
                              **_prusa_identity(prusa.pin)}
    assert port["settings"] == PRUSA_SETTINGS
    assert port["commands"] == {"info": ["<prusa-slicer-console.exe>", "--info", "<model.stl>"],
                                "gcode": PRUSA_GCODE_COMMAND}
    info = port["info"]
    assert (info["returncode"], info["timed_out"]) == (0, False)
    parsed = info["parsed"]
    assert (parsed["facets"], parsed["parts"], parsed["manifold"]) == (mesh["triangles"], 1,
                                                                       True)
    assert parsed["size_mm"] == pytest.approx(mesh["extents_mm"], abs=1e-6)
    assert parsed["volume_mm3"] == pytest.approx(mesh["volume_mm3"], abs=1e-6)
    assert port["expected"] == {"parts": mesh["bodies"], "facets": mesh["triangles"],
                                "size_mm": mesh["extents_mm"], "volume_mm3": mesh["volume_mm3"],
                                "layer_counts": [15]}
    tolerances = port["tolerances"]
    assert 0 < tolerances["size_mm"] < 1e-4 and 0 < tolerances["volume_mm3"] < 0.01 * 2300
    assert 0 < tolerances["z_mm"] < 1e-4
    gcode_part = port["gcode"]
    assert (gcode_part["returncode"], gcode_part["timed_out"]) == (0, False)
    assert (gcode_part["layers"], gcode_part["last_z_mm"]) == (15, 3.0)
    assert gcode_part["expected_top_mm"] == pytest.approx(3.0)
    assert (gcode_part["file"], gcode_part["quarantined"]) == (PRUSA_FILE, False)
    assert gcode_part["sha256"] == record["outputs"]["prusaslicer.portability-only.gcode.txt"]
    assert gcode_part["normalised_lines"] == 1
    assert "not for the A1" in port["note"] and "never print" in port["note"]
    assert sorted(p.name for p in out.iterdir()) == [
        "plate_1.gcode", "plate_1.statistics.json", PRUSA_FILE, "slice.json"]
    # Only F3 (the fake OrcaSlicer G-code has no layers) blocks certification now.
    assert record["certification"] == ("NOT CERTIFIED: F3.printed_connectivity UNKNOWN, "
                                       "F3.edge_coverage UNKNOWN, F3.edge_overprint UNKNOWN")
    assert json.loads((out / "slice.json").read_bytes()) == record
    text = (out / "slice.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    # PrusaSlicer prints the G-code's full path; the record keeps it as a placeholder only.
    assert "tdmg-slice-" not in text
    assert gcode_part["stdout_tail"].strip() == ("Slicing result exported to "
                                                 f"<work>{os.sep}gcode{os.sep}{PRUSA_FILE}")


@pytest.mark.parametrize(("control", "reason"), [
    ({"info": {"manifold": "no", "open_edges": 3}}, "not manifold (open_edges 3)"),
    ({"info": {"facets_reversed": 2}}, "repaired the mesh on import (facets_reversed 2)"),
    ({"info": {"number_of_parts": 2}}, "number_of_parts 2, not the 1 bod"),
    ({"info": {"number_of_facets": 12}}, "number_of_facets 12, not the"),
    ({"info": {"size_x": "59.000000"}}, "size_x 59 mm"),
    ({"info": {"size_z": "3.001000"}}, "size_z 3.001 mm"),
    ({"info": {"volume": "2200.000000"}}, "volume 2200 mm3"),
    ({"info": {"volume": None}}, "cannot read --info"),
    ({"info_stdout": "garbage\n"}, "cannot read --info"),
    ({"info_exit": 1, "stderr": "model.stl: Loading of a model file failed."},
     "--info exited 1: model.stl: Loading of a model file failed."),
    ({"gcode": False, "stdout": "All objects are outside of the print volume."},
     "--export-gcode exited 0 but wrote no G-code"),
    ({"gcode_exit": 1}, "--export-gcode exited 1"),
    ({"layers": 10}, "10 layers, not one of [15]"),
    ({"last_z": "2.8"}, "its ;Z: at layer 15 of 15 is 2.8 mm, not 3 mm"),
    # The plan: an open_edges line at all, even 0, is a FAIL.
    ({"info": {"open_edges": 0}}, "not manifold (open_edges 0)"),
    ({"gcode_empty": True}, "--export-gcode wrote an empty G-code"),
    # An uneven Z sequence with the right count and top, and a missing ;Z: line.
    ({"z": {"5": "1.1"}}, "its ;Z: at layer 5 of 15 is 1.1 mm, not 1 mm"),
    ({"z": {"7": None}}, "the G-code has 14 ;Z: lines for 15 layers"),
    # Codex review 2026-11-11, finding 1: markers alone must not pass.
    ({"truncate": True}, "does not end with '; prusaslicer_config = end': it is incomplete"),
    ({"no_extrusion": [15]}, "layer 15 of 15 has no extruding move"),
    ({"no_extrusion": list(range(1, 16))}, "layer 1 of 15 has no extruding move"),
    ({"move_z": {"9": "2.000"}}, "layer 9 of 15 extrudes at Z 2 mm, not at its 1.8 mm"),
    ({"move_z": {"3": "0.6015"}}, "more than the 3 decimals")])
def test_portability_fails_and_names_the_first_failed_condition(flat_dir, fake, prusa,
                                                                 tmp_path, control, reason):
    out = tmp_path / "slice"
    record = make_slice(flat_dir, out, fake(), prusaslicer_dir=prusa(**control))
    check = by_id(record)["F6.portability"]
    assert check["status"] == "FAIL"
    assert reason in check["note"], check["note"]
    assert "F6.portability FAIL" in record["certification"]
    names = {p.name for p in out.iterdir()}
    # A FAIL quarantines both G-codes, under the same rule as the main one.
    assert "plate_1.gcode" not in names and "prusaslicer.portability-only.gcode.txt" not in names
    assert "plate_1.gcode.failed" in names
    if record["portability"]["gcode"]["file"] is not None:
        assert "prusaslicer.portability-only.gcode.txt.failed" in names
        assert record["portability"]["gcode"]["quarantined"] is True


def test_an_open_mesh_from_the_research_record_fails(flat_dir, fake, prusa, tmp_path):
    # results.txt: the open cube reads "manifold = no; open_edges = 3" and slices to 10 of
    # 100 layers with exit 0. Here both happen; --info is named first.
    record = make_slice(flat_dir, tmp_path / "slice", fake(),
                        prusaslicer_dir=prusa(info={"manifold": "no", "open_edges": 3},
                                              layers=2))
    check = by_id(record)["F6.portability"]
    assert check["status"] == "FAIL" and "not manifold" in check["note"]
    assert record["portability"]["gcode"]["layers"] == 2
    assert record["portability"]["info"]["parsed"]["open_edges"] == 3


def test_a_slow_prusaslicer_is_stopped(flat_dir, fake, prusa, tmp_path):
    record = make_slice(flat_dir, tmp_path / "slice", fake(), timeout_s=4,
                        prusaslicer_dir=prusa(sleep=30))
    check = by_id(record)["F6.portability"]
    assert check["status"] == "FAIL" and "--info was stopped after the 4 s timeout" in check[
        "note"]
    assert record["portability"]["info"]["timed_out"] is True
    assert record["portability"]["gcode"]["timed_out"] is True
    # An explicit --timeout-s names no rule, for either slicer.
    assert check["rule"] is None
    assert record["params"]["prusaslicer_timeout_s"] == {"value": 4.0, "rule": None}


def test_prusaslicer_runs_use_their_own_timeout_rule(flat_dir, fake, prusa, tmp_path,
                                                     monkeypatch):
    rules = load_rules()
    short = rules["slicer.prusa.timeout_s"].model_copy(update={"default": 0.5})
    monkeypatch.setattr(tdmg.slicing, "load_rules",
                        lambda: {**rules, "slicer.prusa.timeout_s": short})
    record = make_slice(flat_dir, tmp_path / "slice", fake(), prusaslicer_dir=prusa(sleep=30))
    checks = by_id(record)
    assert checks["F6.slicer_exit"]["status"] == "PASS"          # OrcaSlicer keeps 300 s
    assert checks["F6.portability"]["status"] == "FAIL"
    assert "--info was stopped after the 0.5 s timeout" in checks["F6.portability"]["note"]
    assert checks["F6.portability"]["rule"] == "slicer.prusa.timeout_s"
    assert record["params"]["prusaslicer_timeout_s"] == {"value": 0.5,
                                                         "rule": "slicer.prusa.timeout_s"}


def test_paths_are_hidden_before_the_output_is_cut(flat_dir, fake, prusa, tmp_path):
    # The fake writes its working folder's path, then enough text that the kept tail
    # starts inside that path. Hiding paths after cutting would leave part of it.
    pad = OUTPUT_TAIL_CHARS - 40
    record = make_slice(flat_dir, tmp_path / "slice", fake(),
                        prusaslicer_dir=prusa(stderr_cwd_pad=pad))
    tail = record["portability"]["info"]["stderr_tail"]
    assert tail.endswith("y" * pad) and "<work>" in tail
    text = (tmp_path / "slice" / "slice.json").read_text(encoding="utf-8")
    assert "tdmg-slice-" not in text and str(prusa.root) not in text


def test_portability_is_part_of_slice_id(flat_dir, fake, prusa, tmp_path):
    root = fake()
    record = make_slice(flat_dir, tmp_path / "a", root, prusaslicer_dir=prusa())
    pin = fake.pin
    identity = {"algorithm": "slice-5", "flat_id": record["links"]["flat_id"],
                "model_stl_sha256": record["links"]["model_stl_sha256"],
                "slicer": {"version": "2.5.0", "exe_sha256": pin.exe.sha256,
                           "libraries": {"app/OrcaSlicer.dll": pin.libraries[0].sha256},
                           "app_tree_sha256": pin.app_tree.sha256,
                           "app_tree_verified": True},
                "profiles": {k: p.sha256 for k, p in pin.profiles.flat.items()},
                "flat_record_sha256": record["links"]["flat_record_sha256"],
                "command": record["command"],
                "f3": {"tolerance": {"rule": "acceptance.dimension.tolerance", "value_mm": 0.2},
                       "elefant_foot_compensation_mm": 0.075},
                "portability": {"slicer": _prusa_identity(prusa.pin),
                                "settings": {k: v["value"] for k, v in PRUSA_SETTINGS.items()},
                                "commands": record["portability"]["commands"]}}
    assert record["slice_id"] == _sha(canonical_json(identity))
    without = make_slice(flat_dir, tmp_path / "b", root)
    assert without["slice_id"] != record["slice_id"]
    # --skip-tree-check covers both slicers, and changes the id.
    skipped = make_slice(flat_dir, tmp_path / "c", root, prusaslicer_dir=prusa.root,
                         check_tree=False)
    assert skipped["portability"]["slicer"]["app_tree_verified"] is False
    assert skipped["slicer"]["app_tree_verified"] is False
    assert skipped["slice_id"] != record["slice_id"]


def test_a_changed_prusaslicer_install_is_refused(flat_dir, fake, prusa, tmp_path):
    root = fake()
    (prusa().joinpath("app", PRUSA_TOP, "extra.dll")).write_bytes(b"new")
    with pytest.raises(SlicerError, match="app tree.*does not match the pin.*"
                                          "setup_prusaslicer.py"):
        make_slice(flat_dir, tmp_path / "slice", root, prusaslicer_dir=prusa.root)
    assert not (tmp_path / "slice").exists()
    r = _slice(flat_dir, tmp_path / "cli", "--slicer-dir", str(root), "--prusaslicer-dir",
               str(prusa.root))
    assert r.exit_code == 2 and "app tree" in r.stderr
    assert not (tmp_path / "cli").exists()
    # The exe and the library are checked even with --skip-tree-check.
    (prusa.root / "app" / PRUSA_TOP / "PrusaSlicer.dll").write_bytes(b"patched")
    with pytest.raises(SlicerError, match="PrusaSlicer.dll.*does not match the pin"):
        make_slice(flat_dir, tmp_path / "slice", root, prusaslicer_dir=prusa.root,
                   check_tree=False)


def test_a_missing_prusaslicer_folder_is_refused(flat_dir, fake, prusa, tmp_path, monkeypatch):
    prusa()
    monkeypatch.setenv("TDMG_PRUSASLICER_DIR", str(tmp_path / "nowhere"))
    with pytest.raises(SlicerError, match="not a folder"):
        make_slice(flat_dir, tmp_path / "slice", fake())
    assert not (tmp_path / "slice").exists()


def test_a_missing_setting_is_refused_only_when_prusaslicer_runs(flat_dir, fake, prusa,
                                                                  tmp_path, monkeypatch):
    root = fake()
    machine = {k: v for k, v in MACHINE.items() if k != "printable_height"}
    _with_profile(fake, monkeypatch, "machine", json.dumps(machine).encode())
    with pytest.raises(SlicerError, match="printable_height.*--max-print-height"):
        make_slice(flat_dir, tmp_path / "slice", root, prusaslicer_dir=prusa())
    assert not (tmp_path / "slice").exists()
    record = make_slice(flat_dir, tmp_path / "slice", root)       # not configured: unused
    assert by_id(record)["F6.portability"]["status"] == "UNKNOWN"


def test_the_environment_variable_configures_prusaslicer(flat_dir, fake, prusa, tmp_path,
                                                          monkeypatch):
    monkeypatch.setenv("TDMG_PRUSASLICER_DIR", str(prusa()))
    record = make_slice(flat_dir, tmp_path / "slice", fake())
    assert by_id(record)["F6.portability"]["status"] == "PASS"


def test_printable_when_every_required_check_passes(square_flat, fake, prusa, tmp_path):
    out = tmp_path / "slice"
    record = make_slice(square_flat, out, fake(gcode_text=_square_gcode(square_flat)),
                        prusaslicer_dir=prusa())
    assert record["verdict"] == "PRINTABLE"
    assert record["certification"] == "PRINTABLE"
    note = record["certification_note"]
    assert note == PRINTABLE_MEANING
    assert PORTABILITY_MEANING in note and "share the admesh STL reader" in note
    assert "independent" not in note
    for phrase in ("every required gate check passed", "pinned slicers", "A1 profile",
                   "acceptance.dimension.tolerance", "still a hypothesis",
                   "no calibration print", "strength is not judged"):
        assert phrase in note, phrase
    assert (record["gcode"]["file"], record["gcode"]["quarantined"]) == ("plate_1.gcode", False)
    assert record["portability"]["gcode"]["file"] == "prusaslicer.portability-only.gcode.txt"


def test_cli_printable(square_flat, fake, prusa, tmp_path):
    out = tmp_path / "slice"
    r = _slice(square_flat, out, "--slicer-dir", str(fake(gcode_text=_square_gcode(
        square_flat))), "--prusaslicer-dir", str(prusa()))
    assert r.exit_code == 0, r.output
    lines = r.stdout.splitlines()
    assert lines[0] == "PRINTABLE"
    assert lines[1] == PRINTABLE_MEANING
    portability = next(line for line in lines if line.startswith("portability:"))
    assert portability.startswith("portability: PrusaSlicer 2.9.7 PASS - 1 part, ")
    assert "15 layers" in portability
    assert PRUSA_GCODE_NOTE in r.stdout
    assert PRINT_THIS in lines
    # Until the pinned A1 profile carries the A1's own G-code (docs/plans/
    # 2026-11-13-color-slicing.md, Decision 1), the message must not say to print it.
    assert PRINT_THIS.startswith("slice model.stl in Bambu Studio to print")
    assert "plate_1.gcode is for checking only" in PRINT_THIS
    assert ("tdmg's G-code is not yet printed or compared with Bambu Studio's own slice"
            in PRINT_THIS)
    assert "incomplete" not in PRINT_THIS         # the profile was fixed on 2026-11-13
    assert "prusaslicer.portability-only.gcode.txt is not for printing" in PRINT_THIS
    assert not any(line.startswith("print plate_1.gcode") for line in lines)
    assert (f"wrote {out / PRUSA_FILE} (portability evidence only; not for printing)"
            in lines)
    assert f"wrote {out / 'plate_1.gcode'}" in lines


def test_skip_tree_check_caps_the_certification(square_flat, fake, prusa, tmp_path):
    root = fake(gcode_text=_square_gcode(square_flat))
    record = make_slice(square_flat, tmp_path / "a", root, prusaslicer_dir=prusa(),
                        check_tree=False)
    assert all(c["status"] == "PASS" for c in record["checks"]
               if c["id"] in SLICE_REQUIRED_CHECKS)
    assert record["certification"] == "NOT CERTIFIED: app tree not verified (--skip-tree-check)"
    assert record["verdict"] == "NOT CERTIFIED"
    assert record["certification_note"] is None
    # Other reasons follow it.
    failed = make_slice(square_flat, tmp_path / "b", root, prusaslicer_dir=prusa(layers=10),
                        check_tree=False)
    assert failed["certification"] == ("NOT CERTIFIED: app tree not verified "
                                       "(--skip-tree-check), F6.portability FAIL")
    # The exit code is unchanged: 0 unless a check FAILed.
    r = _slice(square_flat, tmp_path / "c", "--slicer-dir", str(root), "--prusaslicer-dir",
               str(prusa()), "--skip-tree-check")
    assert r.exit_code == 0, r.output
    lines = r.stdout.splitlines()
    assert lines[0] == "NOT CERTIFIED: app tree not verified (--skip-tree-check)"
    assert not any(line.startswith("print plate_1.gcode") for line in lines)


def test_cli_portability_line_when_not_configured_or_failed(flat_dir, fake, prusa, tmp_path):
    r = _slice(flat_dir, tmp_path / "a", "--slicer-dir", str(fake()))
    assert r.exit_code == 0, r.output
    assert f"portability: UNKNOWN - {NOT_CONFIGURED}" in r.stdout
    r = _slice(flat_dir, tmp_path / "b", "--slicer-dir", str(fake()), "--prusaslicer-dir",
               str(prusa(layers=10)))
    assert r.exit_code == 1, r.output
    assert "portability: PrusaSlicer 2.9.7 FAIL - " in r.stdout
    assert "F6.portability FAIL" in r.stdout
    assert "prusaslicer.portability-only.gcode.txt.failed" in r.stdout
    assert (DO_NOT_PRINT + " (and PrusaSlicer's as "
            "prusaslicer.portability-only.gcode.txt.failed)") in r.stdout
    # Outside the bed PrusaSlicer writes no G-code, so the message does not name one.
    r = _slice(flat_dir, tmp_path / "c", "--slicer-dir", str(fake()), "--prusaslicer-dir",
               str(prusa(gcode=False)))
    assert r.exit_code == 1, r.output
    assert DO_NOT_PRINT in r.stdout and "PrusaSlicer's as" not in r.stdout


def test_cli_help_documents_the_prusaslicer_option():
    text = _plain(runner.invoke(app, ["slice", "--help"]).output)
    assert "--prusaslicer-dir" in text and "TDMG_PRUSASLICER_DIR" in text
    assert "setup_prusaslicer.py" in text


@pytest.mark.slicer
@pytest.mark.skipif(not (os.environ.get("TDMG_ORCASLICER_DIR")
                         and os.environ.get("TDMG_PRUSASLICER_DIR")),
                    reason="TDMG_ORCASLICER_DIR and TDMG_PRUSASLICER_DIR are not both set to "
                           "verified installs")
def test_roadie_is_portable_with_the_real_prusaslicer(tmp_path):
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
    check = by_id(record)["F6.portability"]
    assert check["status"] == "PASS", check
    port = record["portability"]
    assert port["slicer"]["exe_sha256"] == PRUSA_PIN.exe.sha256
    assert port["slicer"]["app_tree_verified"] is True
    assert port["gcode"]["layers"] == 15 and port["gcode"]["last_z_mm"] == 3.0
    assert port["info"]["parsed"]["manifold"] is True
    assert (out / "prusaslicer.portability-only.gcode.txt").is_file()


def test_the_thin_regions_note_says_information_only_once():
    from tdmg.slicing import THIN_REGIONS_NOTE, _thin_regions_note
    current = "tapered tips always appear; information only: tdmg slice judges thin features"
    assert _thin_regions_note(current) == current
    stale = "tapered tips always appear; pass/fail policy pending research"
    assert _thin_regions_note(stale) == f"{stale}; {THIN_REGIONS_NOTE}"
    assert _thin_regions_note(None) == THIN_REGIONS_NOTE
    assert _thin_regions_note("") == THIN_REGIONS_NOTE

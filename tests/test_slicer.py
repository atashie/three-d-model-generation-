"""The OrcaSlicer pin and wrapper (docs/plans/2026-11-10-slicer-check.md)."""

import ast
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tdmg.paths import REPO_ROOT
from tdmg.slicer import (
    GCODE_NAME,
    KILL_WAIT_S,
    OUTPUT_TAIL_CHARS,
    PIN_ID,
    STATS_NAME,
    SlicerError,
    app_tree_sha256,
    decode_exit,
    expected_layer_counts,
    f6_checks,
    gcode_hashes,
    load_pin,
    locate,
    parse_statistics,
    platform_key,
    run_slicer,
    slicer_args,
    verify_install,
)

RECORD = REPO_ROOT / "research" / "verification" / "2026-11-10-orcaslicer-windows"
# The profile hashes since the include fix (2026-11-13); the install and app hashes, and
# the chains, are still the 2026-11-10 record's.
PROFILE_RECORD = REPO_ROOT / "research" / "verification" / "2026-11-13-a1-profile-include"
PIN = load_pin()


def _hash_lines(name: str, record=RECORD) -> dict[str, str]:
    """`<sha256> *<path>` lines (sha256sum's binary-mode output) as {path: sha256}."""
    out = {}
    for line in (record / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, path = line.split(" *", 1)
            out[path] = digest
    return out


def test_pin_loads_by_id():
    assert PIN.id == PIN_ID == "orcaslicer-2.5.0"
    assert (PIN.version, PIN.tag, PIN.release.platform) == ("2.5.0", "v2.5.0", "windows-x64")
    assert PIN.release.asset == "OrcaSlicer_Windows_V2.5.0_x64_portable.zip"
    assert PIN.release.url.endswith("/v2.5.0/" + PIN.release.asset)


def test_pin_hashes_equal_the_research_record():
    install = _hash_lines("install-hashes.txt")
    assert PIN.release.sha256 == install["download/" + PIN.release.asset]
    assert PIN.exe.sha256 == install[PIN.exe.path]
    flattened = _hash_lines("flattened-hashes.txt", PROFILE_RECORD)
    assert {p.file: p.sha256 for p in PIN.profiles.flat.values()} == flattened
    manifest = json.loads((PROFILE_RECORD / "source-manifest.json").read_text(encoding="utf-8"))
    assert manifest["tag"] == PIN.tag
    assert PIN.profiles.upstream_sha256 == manifest["files_sha256"]
    # The 2026-11-10 record is kept as it was: only the machine profile and the manifest
    # changed, and the new manifest adds the five A1 templates to the old one's files.
    old_flat = _hash_lines("flattened-hashes.txt")
    assert {f: h for f, h in flattened.items() if f != "machine.json"} == {
        f: h for f, h in old_flat.items() if f != "machine.json"}
    assert flattened["machine.json"] != old_flat["machine.json"]
    old_manifest = json.loads((RECORD / "source-manifest.json").read_text(encoding="utf-8"))
    added = set(manifest["files_sha256"]) - set(old_manifest["files_sha256"])
    assert {k: v for k, v in manifest["files_sha256"].items() if k not in added} == (
        old_manifest["files_sha256"])
    assert sorted(added) == sorted(
        f"machine/{name}.json" for name in PIN.profiles.flat["machine"].includes)


def test_pin_includes_equal_the_research_record():
    # flatten-output.txt: "<leaf> chain: ... keys N", then "  includes: [...]" (a Python list).
    lines = (PROFILE_RECORD / "flatten-output.txt").read_text(encoding="utf-8").splitlines()
    found = {}
    for i, line in enumerate(lines):
        if " chain: " in line:
            found[line.split(" chain: ")[0]] = ast.literal_eval(
                lines[i + 1].removeprefix("  includes: "))
    assert {p.preset: p.includes for p in PIN.profiles.flat.values()} == found
    assert found["Bambu Lab A1 0.4 nozzle"] == [
        f"Bambu Lab A1 0.4 nozzle template {key}" for key in (
            "machine_start_gcode", "machine_end_gcode", "time_lapse_gcode",
            "change_filament_gcode", "layer_change_gcode")]


def test_pin_app_tree_and_library_equal_the_research_record():
    # app-tree.txt: "<folder>: files N, tree sha256 H, T s" then "  <file>  <sha256>" lines.
    lines = (RECORD / "app-tree.txt").read_text(encoding="utf-8").splitlines()
    head = lines[0].split(": files ", 1)[1].split(", ")
    assert PIN.app_tree.files == int(head[0])
    assert PIN.app_tree.sha256 == head[1].removeprefix("tree sha256 ")
    files = dict(line.split() for line in lines[1:3])
    assert files["orca-slicer.exe"] == PIN.exe.sha256
    assert [(lib.path, lib.sha256) for lib in PIN.libraries] == [
        ("app/OrcaSlicer.dll", files["OrcaSlicer.dll"])]
    # Both folders hashed (the install and a fresh extraction) gave the same tree.
    assert {ln.split(", ")[1] for ln in lines if ": files " in ln} == {
        "tree sha256 " + PIN.app_tree.sha256}


def test_app_tree_sha256_follows_its_definition(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "b.txt").write_bytes(b"b")
    (tmp_path / "sub" / "a.txt").write_bytes(b"a")
    lines = sorted([f"b.txt\t{hashlib.sha256(b'b').hexdigest()}",
                    f"sub/a.txt\t{hashlib.sha256(b'a').hexdigest()}"])
    want = hashlib.sha256("".join(x + "\n" for x in lines).encode()).hexdigest()
    assert app_tree_sha256(tmp_path) == (2, want)


def test_pin_chains_equal_the_research_record():
    # flatten.txt is the research script's output: "<leaf> chain: a <- b <- leaf keys N".
    lines = (RECORD / "flatten.txt").read_text(encoding="utf-8").splitlines()
    chains = {}
    for line in lines:
        leaf, rest = line.split(" chain: ")
        chains[leaf] = rest.rsplit(" keys ", 1)[0].split(" <- ")
    assert {p.preset: p.chain for p in PIN.profiles.flat.values()} == chains
    assert {k: p.file for k, p in PIN.profiles.flat.items()} == {
        "machine": "machine.json", "process": "process.json", "filament": "filament.json"}


def test_pin_exit_codes():
    codes = PIN.exit_codes
    # Utils.hpp v2.5.0: 0, -1..-25, -50..-69 and -100..-102.
    assert sorted(codes) == sorted([0, *range(-25, 0), *range(-69, -49), -100, -101, -102])
    assert all(name.startswith("CLI_") for name in codes.values())
    assert codes[0] == "CLI_SUCCESS"
    # Codes the research record observed, and the ones CLAUDE.md names.
    assert codes[-50] == "CLI_NO_SUITABLE_OBJECTS"
    assert codes[-6] == "CLI_DATA_FILE_ERROR"
    assert codes[-3] == "CLI_FILE_NOTFOUND"
    assert codes[-51] == "CLI_VALIDATE_ERROR"
    assert codes[-59] == "CLI_TRIANGLE_COUNT_EXCEEDS_LIMIT"


def test_pin_decoding_rules_and_their_sources():
    win, posix = PIN.decoding["windows"], PIN.decoding["posix"]
    assert (win.rule, win.status) == ("unsigned32", "measured")
    assert (posix.rule, posix.status) == ("low8", "assumed")
    readme = (RECORD / "README.md").read_text(encoding="utf-8")
    assert "Windows exit codes are not truncated." in readme
    claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "reaching a parent as the low 8 bits" in claude
    assert "not been re-measured with OrcaSlicer 2.5.0" in claude


APP = {"orca-slicer.exe": b"exe", "OrcaSlicer.dll": b"dll", "resources/x.txt": b"x"}


def _fake_install(tmp_path, pin, exe=b"exe", profiles=None, app=None):
    profiles = profiles or {"machine.json": b"m", "process.json": b"p", "filament.json": b"f"}
    app = {**APP, "orca-slicer.exe": exe, **(app or {})}
    for rel, data in app.items():
        path = tmp_path / "app" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (tmp_path / pin.profiles.folder).mkdir()
    for name, data in profiles.items():
        (tmp_path / pin.profiles.folder / name).write_bytes(data)
    return tmp_path


def _tree(app: dict[str, bytes]) -> str:
    """The tree hash, computed here from its definition (not with tdmg.slicer)."""
    lines = sorted(f"{rel}\t{hashlib.sha256(d).hexdigest()}" for rel, d in app.items())
    return hashlib.sha256("".join(x + "\n" for x in lines).encode()).hexdigest()


def _pin_for(exe: bytes, files: dict[str, bytes], app=None):
    app = {**APP, "orca-slicer.exe": exe, **(app or {})}
    flat = {k: p.model_copy(update={"sha256": hashlib.sha256(files[p.file]).hexdigest()})
            for k, p in PIN.profiles.flat.items()}
    lib = PIN.libraries[0].model_copy(update={"sha256": hashlib.sha256(app["OrcaSlicer.dll"])
                                              .hexdigest()})
    return PIN.model_copy(update={
        "exe": PIN.exe.model_copy(update={"sha256": hashlib.sha256(exe).hexdigest()}),
        "libraries": [lib],
        "app_tree": PIN.app_tree.model_copy(update={"files": len(app), "sha256": _tree(app)}),
        "profiles": PIN.profiles.model_copy(update={"flat": flat})})


FILES = {"machine.json": b"m", "process.json": b"p", "filament.json": b"f"}


def test_verify_install_accepts_matching_hashes(tmp_path):
    pin = _pin_for(b"exe", FILES)
    found = verify_install(_fake_install(tmp_path, pin), pin)
    assert found["exe_sha256"] == pin.exe.sha256
    assert found["profiles"]["process"] == {"name": "0.20mm Standard @BBL A1",
                                            "file": "process.json",
                                            "sha256": pin.profiles.flat["process"].sha256}


def test_verify_install_checks_the_library_every_time(tmp_path):
    pin = _pin_for(b"exe", FILES)
    folder = _fake_install(tmp_path, pin, app={"OrcaSlicer.dll": b"patched"})
    with pytest.raises(SlicerError, match="OrcaSlicer.dll.*does not match the pin"):
        verify_install(folder, pin)


def test_verify_install_full_tree(tmp_path):
    pin = _pin_for(b"exe", FILES)
    found = verify_install(_fake_install(tmp_path, pin), pin, full_tree=True)
    assert found["app_tree"] == {"files": 3, "sha256": pin.app_tree.sha256}
    assert found["libraries"] == {"app/OrcaSlicer.dll": pin.libraries[0].sha256}


@pytest.mark.parametrize("change", [{"resources/x.txt": b"changed"}, {"extra.dll": b"new"}])
def test_verify_install_full_tree_refuses_any_other_change(tmp_path, change):
    pin = _pin_for(b"exe", FILES)
    folder = _fake_install(tmp_path, pin, app=change)
    assert verify_install(folder, pin)["exe_sha256"] == pin.exe.sha256   # quick check passes
    with pytest.raises(SlicerError, match="app tree.*does not match the pin"):
        verify_install(folder, pin, full_tree=True)


def test_verify_install_refuses_a_changed_exe(tmp_path):
    pin = _pin_for(b"exe", FILES)
    with pytest.raises(SlicerError, match="orca-slicer.exe.*does not match the pin"):
        verify_install(_fake_install(tmp_path, pin, exe=b"other"), pin)


def test_verify_install_refuses_a_changed_profile(tmp_path):
    pin = _pin_for(b"exe", FILES)
    changed = {**FILES, "process.json": b"p2"}
    with pytest.raises(SlicerError, match="process.json.*does not match the pin"):
        verify_install(_fake_install(tmp_path, pin, profiles=changed), pin)


def test_verify_install_refuses_a_missing_file(tmp_path):
    pin = _pin_for(b"exe", FILES)
    folder = _fake_install(tmp_path, pin)
    (folder / pin.profiles.folder / "filament.json").unlink()
    with pytest.raises(SlicerError, match="filament.json.*missing"):
        verify_install(folder, pin)


# --- Locating the slicer ----------------------------------------------------------------

def test_locate_needs_a_folder(monkeypatch):
    monkeypatch.delenv("TDMG_ORCASLICER_DIR", raising=False)
    with pytest.raises(SlicerError, match="--slicer-dir.*TDMG_ORCASLICER_DIR.*setup_orcaslicer"):
        locate(None)


def test_locate_from_the_argument_or_the_environment(tmp_path, monkeypatch):
    pin = _pin_for(b"exe", FILES)
    folder = _fake_install(tmp_path, pin)
    monkeypatch.delenv("TDMG_ORCASLICER_DIR", raising=False)
    found = locate(folder, pin)
    assert found.exe == folder / "app" / "orca-slicer.exe"
    assert found.profiles == {k: folder / "profiles-flat" / f"{k}.json"
                              for k in ("machine", "process", "filament")}
    assert found.verified["exe_sha256"] == pin.exe.sha256
    monkeypatch.setenv("TDMG_ORCASLICER_DIR", str(folder))
    assert locate(None, pin) == found


def test_locate_refuses_a_hash_mismatch(tmp_path, monkeypatch):
    pin = _pin_for(b"exe", FILES)
    folder = _fake_install(tmp_path, pin, exe=b"a different build")
    monkeypatch.setenv("TDMG_ORCASLICER_DIR", str(folder))
    with pytest.raises(SlicerError, match="does not match the pin"):
        locate(None, pin)


def test_locate_refuses_a_folder_that_does_not_exist(tmp_path):
    with pytest.raises(SlicerError, match="not a folder"):
        locate(tmp_path / "nowhere")


# --- Exit codes -------------------------------------------------------------------------

def test_decode_exit_windows_is_unsigned_32_bit():
    # The three nonzero codes measured on Windows (research record, results.txt).
    for raw, signed, name in ((4294967246, -50, "CLI_NO_SUITABLE_OBJECTS"),
                              (4294967290, -6, "CLI_DATA_FILE_ERROR"),
                              (4294967293, -3, "CLI_FILE_NOTFOUND"), (0, 0, "CLI_SUCCESS")):
        got = decode_exit(raw, "windows")
        assert (got["raw"], got["signed"], got["name"]) == (raw, signed, name)
        assert got["decoding"] == {"platform": "windows", "rule": "unsigned32",
                                   "status": "measured",
                                   "source": PIN.decoding["windows"].source}


def test_decode_exit_posix_is_low_8_bits_and_assumed():
    # CLAUDE.md (M5 notes): -50 -> 206, -51 -> 205, -59 -> 197.
    for raw, signed, name in ((206, -50, "CLI_NO_SUITABLE_OBJECTS"),
                              (205, -51, "CLI_VALIDATE_ERROR"),
                              (197, -59, "CLI_TRIANGLE_COUNT_EXCEEDS_LIMIT")):
        got = decode_exit(raw, "posix")
        assert (got["raw"], got["signed"], got["name"]) == (raw, signed, name)
        assert (got["decoding"]["rule"], got["decoding"]["status"]) == ("low8", "assumed")


def test_decode_exit_unknown_codes_signals_and_bad_values():
    assert decode_exit(2**32 - 30, "windows") == {
        "raw": 2**32 - 30, "signed": -30, "name": None,
        "decoding": decode_exit(0, "windows")["decoding"]}
    assert decode_exit(2**32 - 100, "windows")["name"] == "CLI_SLICING_ERROR"
    killed = decode_exit(-9, "posix")
    assert (killed["signed"], killed["name"]) == (None, "killed by signal 9")
    for raw, plat in ((2**32, "windows"), (-1, "windows"), (256, "posix")):
        with pytest.raises(SlicerError, match="out of range"):
            decode_exit(raw, plat)
    with pytest.raises(SlicerError, match="platform"):
        decode_exit(0, "amiga")
    assert platform_key() == ("windows" if sys.platform == "win32" else "posix")


# --- Layers and statistics ----------------------------------------------------------------

# The two keys and their values in the flattened A1 process profile
# (artifacts/tools/orcaslicer-2.5.0/profiles-flat/process.json, read 2026-11-10):
# "layer_height": "0.2", "initial_layer_print_height": "0.2". Hard-coded because CI does
# not have the file; test_expected_layer_counts_with_the_local_profile reads it.
A1_PROCESS = {"layer_height": "0.2", "initial_layer_print_height": "0.2"}
LOCAL_PROCESS = (REPO_ROOT / "artifacts" / "tools" / "orcaslicer-2.5.0" / "profiles-flat"
                 / "process.json")


def test_expected_layer_counts_for_the_a1_profile():
    # The 20 mm cube sliced into 100 layers and the 3 mm models into 15 (research record).
    assert expected_layer_counts(20, A1_PROCESS) == {100}
    assert expected_layer_counts(3, A1_PROCESS) == {15}
    assert expected_layer_counts(0.2, A1_PROCESS) == {1}
    assert expected_layer_counts(
        3, {"layer_height": "0.1", "initial_layer_print_height": "0.3"}) == {28}


@pytest.mark.parametrize(("t", "allowed"), [
    # README addendum item 3: at exactly half a layer the slicer chose 6, 10, 2, 15, 2.
    (1.1, {5, 6}), (2.1, {10, 11}), (0.3, {1, 2}), (3.1, {15, 16}), (0.5, {2, 3}),
    # Away from a half layer it matched the nearest count.
    (3.0, {15}), (3.05, {15}), (3.15, {16})])
def test_expected_layer_counts_accept_either_neighbour_at_half_a_layer(t, allowed):
    assert expected_layer_counts(t, A1_PROCESS) == allowed


@pytest.mark.skipif(not LOCAL_PROCESS.is_file(), reason="no local OrcaSlicer install")
def test_expected_layer_counts_with_the_local_profile():
    process = json.loads(LOCAL_PROCESS.read_text(encoding="utf-8"))
    assert {k: process[k] for k in A1_PROCESS} == A1_PROCESS
    assert expected_layer_counts(20, process) == {100}


def test_expected_layer_counts_refuse_bad_input():
    with pytest.raises(SlicerError, match="layer_height"):
        expected_layer_counts(3, {"initial_layer_print_height": "0.2"})
    with pytest.raises(SlicerError, match="positive"):
        expected_layer_counts(3, {"layer_height": "0", "initial_layer_print_height": "0.2"})
    with pytest.raises(SlicerError, match="thinner than the first layer"):
        expected_layer_counts(0.1, A1_PROCESS)


def _stats(path, layers=100, objects=1, units=None):
    data = {"generator": "OrcaSlicer 2.5.0",
            "units": units or {"time": "s", "length": "mm", "volume": "mm3", "weight": "g"},
            "summary": {"time": 766.104, "layer_count": layers, "volume": 2957.692,
                        "weight": 3.7267},
            "objects": [{"name": f"o{i}"} for i in range(objects)]}
    path.write_bytes(json.dumps(data).encode())
    return path


def test_parse_statistics(tmp_path):
    got = parse_statistics(_stats(tmp_path / STATS_NAME, objects=2))
    assert got == {"generator": "OrcaSlicer 2.5.0", "layer_count": 100, "time_s": 766.104,
                   "volume_mm3": 2957.692, "weight_g": 3.7267, "objects": ["o0", "o1"]}


def test_parse_statistics_refuses_other_units_or_a_bad_file(tmp_path):
    with pytest.raises(SlicerError, match="units"):
        parse_statistics(_stats(tmp_path / "a.json", units={"time": "min"}))
    (tmp_path / "b.json").write_bytes(b"{not json")
    with pytest.raises(SlicerError, match="b.json"):
        parse_statistics(tmp_path / "b.json")
    units = {"time": "s", "length": "mm", "volume": "mm3", "weight": "g"}
    (tmp_path / "c.json").write_bytes(json.dumps({"units": units, "summary": {}}).encode())
    with pytest.raises(SlicerError, match="layer_count"):
        parse_statistics(tmp_path / "c.json")


# --- Running the (fake) slicer --------------------------------------------------------

FAKE = [sys.executable, str(REPO_ROOT / "tests" / "fake_orca.py")]


def _setup_run(tmp_path, **control):
    for kind in ("machine", "process", "filament"):
        (tmp_path / f"{kind}.json").write_bytes(b"{}")
    profiles = {k: tmp_path / f"{k}.json" for k in ("machine", "process", "filament")}
    stl = tmp_path / "model.stl"
    stl.write_bytes(b"solid x\nendsolid x\n")
    (tmp_path / "model.fake.json").write_bytes(json.dumps(control).encode())
    work = tmp_path / "work"
    work.mkdir()
    return stl, profiles, work


def _run(tmp_path, timeout=60, expected=frozenset({100}), **control):
    stl, profiles, work = _setup_run(tmp_path, **control)
    run = run_slicer(FAKE, stl, profiles, work, timeout)
    return run, f6_checks(run, expected)


def _by_id(checks):
    return {c.id: c for c in checks}


def test_slicer_args_are_the_measured_form():
    p = {k: Path(f"/p/{k}.json") for k in ("machine", "process", "filament")}
    assert slicer_args(Path("/m.stl"), p, Path("/w/out"), Path("/w/slicer.log")) == [
        str(Path("/m.stl")), "--load-settings",
        f"{p['machine']};{p['process']}", "--load-filaments", str(p["filament"]),
        "--slice", "0", "--outputdir", str(Path("/w/out")), "--export-statistics",
        "--logfile", str(Path("/w/slicer.log"))]


def test_success_passes_every_measured_f6_check(tmp_path):
    run, (checks, stats) = _run(tmp_path)
    assert run.returncode == 0 and not run.timed_out
    assert run.args[:len(FAKE)] == FAKE
    assert sorted(p.name for p in run.out_dir.iterdir()) == [GCODE_NAME, STATS_NAME]
    status = {c.id: c.status for c in checks}
    # F6.portability is measured with PrusaSlicer by tdmg.portability, not here.
    assert status == {"F6.slicer_exit": "PASS", "F6.gcode_present": "PASS",
                      "F6.layer_count": "PASS", "F6.single_object": "PASS"}
    by = _by_id(checks)
    assert by["F6.layer_count"].measured == 100 and by["F6.layer_count"].threshold == [100]
    assert by["F6.slicer_exit"].measured["name"] == "CLI_SUCCESS"
    assert stats["layer_count"] == 100 and stats["objects"] == ["m0"]


def test_a_nonzero_exit_is_decoded_on_this_platform(tmp_path):
    run, (checks, stats) = _run(tmp_path, exit=-50, gcode=False, stats=False, log=True)
    # sys.exit(-50) reaches the parent as the platform's encoding of -50.
    assert run.returncode == (2**32 - 50 if platform_key() == "windows" else 206)
    by = _by_id(checks)
    assert by["F6.slicer_exit"].status == "FAIL"
    assert by["F6.slicer_exit"].measured["signed"] == -50
    assert "CLI_NO_SUITABLE_OBJECTS" in by["F6.slicer_exit"].note
    assert by["F6.gcode_present"].status == "FAIL"
    # Nothing to measure after a failed slice: not a second failure, just unknown.
    assert by["F6.layer_count"].status == "UNKNOWN"
    assert by["F6.single_object"].status == "UNKNOWN"
    assert stats is None and run.log_path.is_file()


def test_missing_gcode_fails(tmp_path):
    _, (checks, _) = _run(tmp_path, gcode=False)
    by = _by_id(checks)
    assert by["F6.slicer_exit"].status == "PASS"
    assert by["F6.gcode_present"].status == "FAIL"
    assert by["F6.gcode_present"].measured == {"file": GCODE_NAME, "bytes": None}


def test_missing_statistics_after_a_clean_exit_fail(tmp_path):
    _, (checks, stats) = _run(tmp_path, stats=False)
    by = _by_id(checks)
    assert by["F6.layer_count"].status == "FAIL" and by["F6.single_object"].status == "FAIL"
    assert "statistics" in by["F6.layer_count"].note and stats is None


def test_a_truncated_print_fails_the_layer_count(tmp_path):
    # The open-mesh cube: exit 0, both files, but 10 layers instead of 100.
    _, (checks, _) = _run(tmp_path, layers=10)
    by = _by_id(checks)
    assert by["F6.slicer_exit"].status == "PASS"
    assert by["F6.layer_count"].status == "FAIL"
    assert (by["F6.layer_count"].measured, by["F6.layer_count"].threshold) == (10, [100])
    assert "height" in by["F6.layer_count"].note and "F1" in by["F6.layer_count"].note


@pytest.mark.parametrize("layers", [5, 6])
def test_either_half_layer_neighbour_passes(tmp_path, layers):
    _, (checks, _) = _run(tmp_path, expected={5, 6}, layers=layers)
    by = _by_id(checks)
    assert by["F6.layer_count"].status == "PASS"
    assert by["F6.layer_count"].threshold == [5, 6]


def test_a_count_outside_the_allowed_set_fails(tmp_path):
    _, (checks, _) = _run(tmp_path, expected={5, 6}, layers=7)
    assert _by_id(checks)["F6.layer_count"].status == "FAIL"


def test_two_objects_fail_single_object(tmp_path):
    _, (checks, _) = _run(tmp_path, objects=2)
    by = _by_id(checks)
    assert by["F6.single_object"].status == "FAIL"
    assert by["F6.single_object"].measured == 2


def test_a_slow_slicer_is_stopped_at_the_timeout(tmp_path):
    run, (checks, stats) = _run(tmp_path, timeout=0.5, sleep=30)
    assert run.timed_out and run.returncode is None
    by = _by_id(checks)
    assert by["F6.slicer_exit"].status == "FAIL"
    assert by["F6.slicer_exit"].rule == "slicer.orca.timeout_s"
    assert "0.5 s" in by["F6.slicer_exit"].note
    assert by["F6.layer_count"].status == "UNKNOWN" and stats is None


def test_the_timeout_kills_the_whole_process_tree(tmp_path):
    # The fake starts a child that keeps the output pipes open for 30 s. Killing only the
    # fake leaves run_slicer waiting on those pipes until KILL_WAIT_S (measured 10.5 s on
    # Windows, 2026-11-10); killing the tree returned in 0.6 s.
    start = time.perf_counter()
    run, _ = _run(tmp_path, timeout=0.5, sleep=30, grandchild=30)
    assert run.timed_out
    assert time.perf_counter() - start < KILL_WAIT_S / 2


def test_run_slicer_runs_in_the_work_folder(tmp_path):
    record = tmp_path / "cwd.txt"
    run, _ = _run(tmp_path, cwd_file=str(record))
    assert Path(record.read_text()) == run.out_dir.parent


def test_run_slicer_keeps_only_the_end_of_long_output(tmp_path):
    run, _ = _run(tmp_path, stderr="x" * (OUTPUT_TAIL_CHARS * 2) + "END")
    assert len(run.stderr) == OUTPUT_TAIL_CHARS and run.stderr.endswith("END")


def test_run_slicer_needs_an_absolute_program(tmp_path):
    stl, profiles, work = _setup_run(tmp_path)
    with pytest.raises(SlicerError, match="absolute"):
        run_slicer(["orca-slicer.exe"], stl, profiles, work, 10)


def test_the_fake_refuses_another_argument_form(tmp_path):
    # The fake checks the form, so the tests above prove run_slicer used the measured one.
    stl, _, _ = _setup_run(tmp_path)
    r = subprocess.run([*FAKE, str(stl), "--slice", "0"], check=False)
    assert decode_exit(r.returncode, platform_key())["signed"] == -2


def test_run_slicer_refuses_a_missing_program(tmp_path):
    stl, profiles, work = _setup_run(tmp_path)
    with pytest.raises(SlicerError, match="cannot start"):
        run_slicer([str(tmp_path / "no-such.exe")], stl, profiles, work, 10)


def test_run_slicer_refuses_a_semicolon_in_a_settings_path(tmp_path):
    stl, profiles, work = _setup_run(tmp_path)
    odd = tmp_path / "a;b"
    odd.mkdir()
    (odd / "process.json").write_bytes(b"{}")
    with pytest.raises(SlicerError, match="contains ';'"):
        run_slicer(FAKE, stl, {**profiles, "process": odd / "process.json"}, work, 10)
    assert not (work / "out").exists()


def test_run_slicer_needs_an_empty_work_folder(tmp_path):
    stl, profiles, work = _setup_run(tmp_path)
    (work / "stale").write_bytes(b"")
    with pytest.raises(SlicerError, match="empty"):
        run_slicer(FAKE, stl, profiles, work, 10)


# --- G-code hash ------------------------------------------------------------------------

START, END = b"; HEADER_BLOCK_START\n", b"; HEADER_BLOCK_END\n"


def test_gcode_hash_ignores_only_the_generated_line():
    a = START + b"; generated by OrcaSlicer 2.5.0 on 2026-11-10 at 12:46:23\n" + END + b"G28\n"
    b = START + b"; generated by OrcaSlicer 2.5.0 on 2026-11-11 at 08:00:00\n" + END + b"G28\n"
    ha, hb = gcode_hashes(a), gcode_hashes(b)
    assert ha["sha256"] != hb["sha256"]
    assert ha["normalised_sha256"] == hb["normalised_sha256"]
    assert ha["normalised_lines"] == 1
    assert ha["normalised_sha256"] == hashlib.sha256(START + b"\n" + END + b"G28\n").hexdigest()
    # Any other change still changes the normalised hash.
    c = a.replace(b"G28", b"G29")
    assert gcode_hashes(c)["normalised_sha256"] != ha["normalised_sha256"]
    # Only the first such line in the header block is blanked; outside it nothing is.
    twice = a + b"; generated by X at Y\n"
    assert gcode_hashes(twice)["normalised_lines"] == 1
    assert gcode_hashes(twice)["normalised_sha256"] != ha["normalised_sha256"]
    for plain in (b"G28\n", b"; generated by X at Y\nG28\n",
                  START + END + b"; generated by X at Y\n",
                  START + b"; generated by X at Y\n"):   # no block, outside it, or unclosed
        got = gcode_hashes(plain)
        assert got["normalised_lines"] == 0 and got["normalised_sha256"] == got["sha256"]


def test_gcode_hash_keeps_crlf_line_ends():
    a = b"; HEADER_BLOCK_START\r\n; generated by O on d at t\r\n; HEADER_BLOCK_END\r\nG28\r\n"
    assert gcode_hashes(a)["normalised_sha256"] == hashlib.sha256(
        b"; HEADER_BLOCK_START\r\n\r\n; HEADER_BLOCK_END\r\nG28\r\n").hexdigest()


def test_pin_include_defaults_are_the_quoted_printconfig_defaults():
    # source-excerpts.txt quotes each default from PrintConfig.cpp at v2.5.0, as
    # 'src/libslic3r/PrintConfig.cpp:<line>: def->set_default_value(new
    # ConfigOptionString("<C string>"));   (<key>, <line of its add>)'.
    text = (PROFILE_RECORD / "source-excerpts.txt").read_text(encoding="utf-8")
    quoted = {}
    for m in re.finditer(r'^src/libslic3r/PrintConfig\.cpp:\d+: def->set_default_value\(new '
                         r'ConfigOptionString\((?:"(.*)")?\)\);   \((\w+),', text, re.MULTILINE):
        quoted[m.group(2)] = (m.group(1) or "").replace("\\n", "\n")
    assert sorted(quoted) == sorted(
        k.removeprefix("Bambu Lab A1 0.4 nozzle template ")
        for k in PIN.profiles.flat["machine"].includes)
    assert PIN.profiles.include_defaults_sha256 == {
        k: hashlib.sha256(v.encode()).hexdigest() for k, v in quoted.items()}

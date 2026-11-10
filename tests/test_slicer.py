"""The OrcaSlicer pin and wrapper (docs/plans/2026-11-10-slicer-check.md)."""

import hashlib
import json

import pytest

from tdmg.paths import REPO_ROOT
from tdmg.slicer import PIN_ID, SlicerError, load_pin, verify_install

RECORD = REPO_ROOT / "research" / "verification" / "2026-11-10-orcaslicer-windows"
PIN = load_pin()


def _hash_lines(name: str) -> dict[str, str]:
    """`<sha256> *<path>` lines (sha256sum's binary-mode output) as {path: sha256}."""
    out = {}
    for line in (RECORD / name).read_text(encoding="utf-8").splitlines():
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
    flattened = _hash_lines("flattened-hashes.txt")
    assert {p.file: p.sha256 for p in PIN.profiles.flat.values()} == flattened
    manifest = json.loads((RECORD / "source-manifest.json").read_text(encoding="utf-8"))
    assert manifest["tag"] == PIN.tag
    assert PIN.profiles.upstream_sha256 == manifest["files_sha256"]


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
    assert "exit codes reach a parent as the low 8 bits" in claude


def _fake_install(tmp_path, pin, exe=b"exe", profiles=None):
    profiles = profiles or {"machine.json": b"m", "process.json": b"p", "filament.json": b"f"}
    (tmp_path / "app").mkdir()
    (tmp_path / pin.exe.path).write_bytes(exe)
    (tmp_path / pin.profiles.folder).mkdir()
    for name, data in profiles.items():
        (tmp_path / pin.profiles.folder / name).write_bytes(data)
    return tmp_path


def _pin_for(exe: bytes, files: dict[str, bytes]):
    flat = {k: p.model_copy(update={"sha256": hashlib.sha256(files[p.file]).hexdigest()})
            for k, p in PIN.profiles.flat.items()}
    return PIN.model_copy(update={
        "exe": PIN.exe.model_copy(update={"sha256": hashlib.sha256(exe).hexdigest()}),
        "profiles": PIN.profiles.model_copy(update={"flat": flat})})


FILES = {"machine.json": b"m", "process.json": b"p", "filament.json": b"f"}


def test_verify_install_accepts_matching_hashes(tmp_path):
    pin = _pin_for(b"exe", FILES)
    found = verify_install(_fake_install(tmp_path, pin), pin)
    assert found["exe_sha256"] == pin.exe.sha256
    assert found["profiles"]["process"] == {"name": "0.20mm Standard @BBL A1",
                                            "file": "process.json",
                                            "sha256": pin.profiles.flat["process"].sha256}


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

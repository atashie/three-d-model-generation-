"""scripts/setup_orcaslicer.py, offline: every download is replaced by local bytes."""

import hashlib
import importlib.util
import io
import json
import zipfile

import pytest

from tdmg.paths import REPO_ROOT
from tdmg.slicer import load_pin

_spec = importlib.util.spec_from_file_location(
    "setup_orcaslicer", REPO_ROOT / "scripts" / "setup_orcaslicer.py")
setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup)

PIN = load_pin()
EXE = b"not really an exe"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def _pin_with(release_sha=None, exe_sha=None, flat=None, upstream=None):
    profiles = PIN.profiles
    if flat is not None or upstream is not None:
        profiles = profiles.model_copy(update={k: v for k, v in
                                               (("flat", flat), ("upstream_sha256", upstream))
                                               if v is not None})
    return PIN.model_copy(update={
        "release": PIN.release.model_copy(update={"sha256": release_sha or PIN.release.sha256}),
        "exe": PIN.exe.model_copy(update={"sha256": exe_sha or PIN.exe.sha256}),
        "profiles": profiles})


# --- Installing the app from the release zip ------------------------------------------

def _fake_download(data: bytes, calls: list):
    def download(url, path):
        calls.append(url)
        path.write_bytes(data)
    return download


def test_install_app_verifies_and_extracts(tmp_path, monkeypatch):
    archive = _zip({"orca-slicer.exe": EXE, "resources/x.txt": b"x"})
    pin = _pin_with(release_sha=_sha(archive), exe_sha=_sha(EXE))
    calls = []
    monkeypatch.setattr(setup, "download", _fake_download(archive, calls))
    setup.install_app(tmp_path, pin)
    assert calls == [pin.release.url]
    assert (tmp_path / "app" / "orca-slicer.exe").read_bytes() == EXE
    assert (tmp_path / "app" / "resources" / "x.txt").read_bytes() == b"x"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["app", "download"]


def test_install_app_refuses_a_wrong_zip_hash(tmp_path, monkeypatch):
    archive = _zip({"orca-slicer.exe": EXE})
    pin = _pin_with(release_sha=_sha(b"something else"), exe_sha=_sha(EXE))
    monkeypatch.setattr(setup, "download", _fake_download(archive, []))
    with pytest.raises(setup.SetupError, match="OrcaSlicer_Windows_V2.5.0_x64_portable.zip.*"
                                               "does not match the pin"):
        setup.install_app(tmp_path, pin)
    assert not (tmp_path / "app").exists()
    assert not (tmp_path / "download" / pin.release.asset).exists()   # not kept as verified


def test_install_app_refuses_a_wrong_exe_hash_and_leaves_no_app(tmp_path, monkeypatch):
    archive = _zip({"orca-slicer.exe": b"tampered"})
    pin = _pin_with(release_sha=_sha(archive), exe_sha=_sha(EXE))
    monkeypatch.setattr(setup, "download", _fake_download(archive, []))
    with pytest.raises(setup.SetupError, match="orca-slicer.exe.*does not match the pin"):
        setup.install_app(tmp_path, pin)
    assert not (tmp_path / "app").exists()
    assert [p.name for p in tmp_path.iterdir()] == ["download"]   # no extraction leftovers


def test_install_app_refuses_a_non_empty_app_folder_before_downloading(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "old.txt").write_bytes(b"old")
    calls = []
    monkeypatch.setattr(setup, "download", _fake_download(b"", calls))
    with pytest.raises(setup.SetupError, match="not empty"):
        setup.install_app(tmp_path, PIN)
    assert calls == []


def test_install_app_uses_a_local_zip_after_checking_it(tmp_path, monkeypatch):
    archive = _zip({"orca-slicer.exe": EXE})
    local = tmp_path / "local.zip"
    local.write_bytes(archive)
    dest = tmp_path / "dest"
    dest.mkdir()
    calls = []
    monkeypatch.setattr(setup, "download", _fake_download(b"", calls))
    setup.install_app(dest, _pin_with(release_sha=_sha(archive), exe_sha=_sha(EXE)),
                      zip_path=local)
    assert calls == []
    assert (dest / "app" / "orca-slicer.exe").read_bytes() == EXE
    with pytest.raises(setup.SetupError, match="local.zip.*does not match the pin"):
        setup.install_app(tmp_path / "other", _pin_with(release_sha=_sha(b"x")),
                          zip_path=local)


# --- Flattening the profile chains ------------------------------------------------------

def _upstream():
    """A tiny vendor: one chain per kind, two files each, with the research merge applied."""
    files = {
        "machine/base_m.json": {"name": "base_m", "a": "1", "b": "1", "from": "system",
                                "instantiation": "false"},
        "machine/M.json": {"name": "M", "inherits": "base_m", "b": "2", "setting_id": "X",
                           "description": "d"},
        "process/base_p.json": {"name": "base_p", "layer_height": "0.1"},
        "process/P.json": {"name": "P", "inherits": "base_p", "layer_height": "0.2"},
        "filament/base_f.json": {"name": "base_f", "t": ["200"]},
        "filament/F.json": {"name": "F", "inherits": "base_f", "from": "system"},
    }
    raw = {path: json.dumps(cfg).encode() for path, cfg in files.items()}
    index = {"machine_list": [{"name": "base_m", "sub_path": "machine/base_m.json"},
                              {"name": "M", "sub_path": "machine/M.json"}],
             "process_list": [{"name": "base_p", "sub_path": "process/base_p.json"},
                              {"name": "P", "sub_path": "process/P.json"}],
             "filament_list": [{"name": "base_f", "sub_path": "filament/base_f.json"},
                               {"name": "F", "sub_path": "filament/F.json"}]}
    # Expected outputs, written by hand: child overrides parent, the dropped keys go,
    # name is the leaf and from is "User"; indent 1, sorted keys, CRLF line ends.
    expected = {"machine.json": {"name": "M", "a": "1", "b": "2", "from": "User"},
                "process.json": {"name": "P", "layer_height": "0.2", "from": "User"},
                "filament.json": {"name": "F", "t": ["200"], "from": "User"}}
    expected = {k: json.dumps(v, indent=1, sort_keys=True).replace("\n", "\r\n").encode()
                for k, v in expected.items()}
    return raw, index, expected


def _fake_fetch(raw: dict, index: dict, served: list):
    base = PIN.profiles.source_base + PIN.profiles.vendor

    def fetch(url):
        served.append(url)
        if url == base + ".json":
            return json.dumps(index).encode()
        for path, data in raw.items():
            if url == base + "/" + path:
                return data
        raise AssertionError(f"unexpected url {url}")
    return fetch


def _flat_pin(raw, expected, **override):
    chains = {"machine": ["base_m", "M"], "process": ["base_p", "P"],
              "filament": ["base_f", "F"]}
    flat = {k: p.model_copy(update={"preset": chains[k][-1], "chain": chains[k],
                                    "sha256": _sha(expected[p.file])})
            for k, p in PIN.profiles.flat.items()}
    upstream = {path: _sha(data) for path, data in raw.items()}
    upstream.update(override.get("upstream", {}))
    for kind, sha in override.get("flat", {}).items():
        flat[kind] = flat[kind].model_copy(update={"sha256": sha})
    return _pin_with(flat=flat, upstream=upstream)


def test_flatten_merges_chains_into_the_pinned_bytes(monkeypatch):
    raw, index, expected = _upstream()
    served = []
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, served))
    out = setup.flatten(_flat_pin(raw, expected))
    assert {k: out[k] for k in expected} == expected
    manifest = json.loads(out["source-manifest.json"])
    assert manifest == {"tag": PIN.tag, "files_sha256": {p: _sha(d) for p, d in raw.items()}}
    assert all(u.startswith(PIN.profiles.source_base) for u in served)


def test_flatten_refuses_a_changed_upstream_file(monkeypatch):
    raw, index, expected = _upstream()
    pin = _flat_pin(raw, expected)
    raw["process/base_p.json"] = json.dumps({"name": "base_p", "layer_height": "0.3"}).encode()
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="process/base_p.json.*does not match the pin"):
        setup.flatten(pin)


def test_flatten_refuses_an_output_that_differs_from_the_pin(monkeypatch):
    raw, index, expected = _upstream()
    pin = _flat_pin(raw, expected, flat={"filament": _sha(b"other")})
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="filament.json.*does not match the pin"):
        setup.flatten(pin)


def test_flatten_refuses_a_file_the_pin_does_not_list(monkeypatch):
    raw, index, expected = _upstream()
    pin = _flat_pin(raw, expected)
    upstream = dict(pin.profiles.upstream_sha256)
    del upstream["machine/base_m.json"]
    pin = _pin_with(flat=pin.profiles.flat, upstream=upstream)
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="machine/base_m.json.*not in the pin"):
        setup.flatten(pin)


def test_flatten_refuses_when_a_pinned_file_is_not_used(monkeypatch):
    raw, index, expected = _upstream()
    pin = _flat_pin(raw, expected, upstream={"process/unused.json": _sha(b"u")})
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="process/unused.json"):
        setup.flatten(pin)


def test_flatten_refuses_a_different_chain(monkeypatch):
    raw, index, expected = _upstream()
    pin = _flat_pin(raw, expected)
    flat = dict(pin.profiles.flat)
    flat["machine"] = flat["machine"].model_copy(update={"chain": ["other", "M"]})
    pin = _pin_with(flat=flat, upstream=pin.profiles.upstream_sha256)
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="chain"):
        setup.flatten(pin)


def test_write_profiles_refuses_a_non_empty_folder(tmp_path):
    (tmp_path / "profiles-flat").mkdir()
    (tmp_path / "profiles-flat" / "old.json").write_bytes(b"{}")
    with pytest.raises(setup.SetupError, match="not empty"):
        setup.write_profiles(tmp_path, PIN, {"machine.json": b"{}"})


# --- Platform and command line --------------------------------------------------------

def test_only_windows_x64_is_supported():
    setup.check_platform("Windows", "AMD64")
    for system, machine in (("Linux", "x86_64"), ("Darwin", "arm64"), ("Windows", "ARM64")):
        with pytest.raises(setup.SetupError, match="Windows x64 only"):
            setup.check_platform(system, machine)


def test_main_exits_2_on_another_platform_without_writing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(setup.platform, "system", lambda: "Linux")
    dest = tmp_path / "orca"
    assert setup.main(["--dest", str(dest)]) == 2
    assert "Windows x64 only" in capsys.readouterr().err
    assert not dest.exists()


def test_main_verify_only_reports_a_mismatch(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "orca-slicer.exe").write_bytes(b"not the pinned exe")
    assert setup.main(["--verify-only", str(tmp_path)]) == 2
    assert "does not match the pin" in capsys.readouterr().err

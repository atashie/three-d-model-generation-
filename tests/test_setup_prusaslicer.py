"""scripts/setup_prusaslicer.py, offline: the download is replaced by a fake zip."""

import hashlib
import importlib.util
import io
import zipfile

import pytest

from tdmg.paths import REPO_ROOT
from tdmg.portability import load_prusa_pin

_spec = importlib.util.spec_from_file_location(
    "setup_prusaslicer", REPO_ROOT / "scripts" / "setup_prusaslicer.py")
setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup)

PIN = load_prusa_pin()
TOP = "PrusaSlicer-2.9.7/"          # the zip's one top-level folder (research record)
MEMBERS = {TOP + "prusa-slicer-console.exe": b"not really an exe",
           TOP + "PrusaSlicer.dll": b"dll", TOP + "resources/x.txt": b"x"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def _pin_with(release_sha, app=MEMBERS):
    """PIN with its hashes replaced: app is the extracted tree the pin should expect."""
    lines = sorted(f"{rel}\t{_sha(d)}" for rel, d in app.items())
    tree = _sha("".join(x + "\n" for x in lines).encode())
    return PIN.model_copy(update={
        "release": PIN.release.model_copy(update={"sha256": release_sha}),
        "exe": PIN.exe.model_copy(update={"sha256": _sha(app[TOP + "prusa-slicer-console.exe"])}),
        "libraries": [PIN.libraries[0].model_copy(update={
            "sha256": _sha(app[TOP + "PrusaSlicer.dll"])})],
        "app_tree": PIN.app_tree.model_copy(update={"files": len(app), "sha256": tree})})


def _fake_download(data: bytes, calls: list):
    def download(url, path):
        calls.append(url)
        path.write_bytes(data)
    return download


def test_setup_downloads_checks_and_extracts(tmp_path, monkeypatch, capsys):
    archive = _zip(MEMBERS)
    pin = _pin_with(_sha(archive))
    calls = []
    monkeypatch.setattr(setup, "check_platform", lambda: None)
    monkeypatch.setattr(setup, "load_prusa_pin", lambda: pin)
    monkeypatch.setattr(setup, "download", _fake_download(archive, calls))
    dest = tmp_path / "prusa"
    found = setup.setup(dest)
    assert calls == [pin.release.url]
    assert found["exe_sha256"] == pin.exe.sha256
    assert found["app_tree"] == {"files": 3, "sha256": pin.app_tree.sha256}
    assert (dest / pin.exe.path).read_bytes() == MEMBERS[TOP + "prusa-slicer-console.exe"]
    assert sorted(p.name for p in dest.iterdir()) == ["app", "download"]
    # --verify-only checks the whole tree, so one extra file is refused.
    assert setup.main(["--verify-only", str(dest)]) == 0
    (dest / "app" / "PrusaSlicer-2.9.7" / "added.txt").write_bytes(b"+")
    assert setup.main(["--verify-only", str(dest)]) == 2
    assert "app tree" in capsys.readouterr().err


def test_setup_uses_a_local_zip_after_checking_it(tmp_path, monkeypatch):
    archive = _zip(MEMBERS)
    local = tmp_path / "local.zip"
    local.write_bytes(archive)
    calls = []
    monkeypatch.setattr(setup, "check_platform", lambda: None)
    monkeypatch.setattr(setup, "download", _fake_download(b"", calls))
    monkeypatch.setattr(setup, "load_prusa_pin", lambda: _pin_with(_sha(archive)))
    setup.setup(tmp_path / "a", local)
    assert calls == []
    monkeypatch.setattr(setup, "load_prusa_pin", lambda: _pin_with(_sha(b"x")))
    with pytest.raises(setup.SetupError, match="local.zip.*does not match the pin"):
        setup.setup(tmp_path / "b", local)
    assert not (tmp_path / "b" / "app").exists()


@pytest.mark.parametrize(("change", "what"), [
    ({TOP + "prusa-slicer-console.exe": b"tampered"}, "prusa-slicer-console.exe"),
    ({TOP + "PrusaSlicer.dll": b"tampered"}, "PrusaSlicer.dll"),
    ({TOP + "resources/x.txt": b"tampered"}, "app tree"),
    ({TOP + "resources/extra.txt": b"new"}, "app tree")])
def test_setup_refuses_any_changed_file_and_leaves_no_app(tmp_path, monkeypatch, change, what):
    archive = _zip({**MEMBERS, **change})
    monkeypatch.setattr(setup, "check_platform", lambda: None)
    monkeypatch.setattr(setup, "load_prusa_pin", lambda: _pin_with(_sha(archive)))
    monkeypatch.setattr(setup, "download", _fake_download(archive, []))
    dest = tmp_path / "prusa"
    with pytest.raises(setup.SetupError, match=f"{what}.*does not match the pin"):
        setup.setup(dest)
    assert sorted(p.name for p in dest.iterdir()) == ["download"]   # no app, no leftovers


def test_setup_refuses_a_wrong_download_and_keeps_nothing(tmp_path, monkeypatch):
    archive = _zip(MEMBERS)
    monkeypatch.setattr(setup, "check_platform", lambda: None)
    monkeypatch.setattr(setup, "load_prusa_pin", lambda: _pin_with(_sha(b"other")))
    monkeypatch.setattr(setup, "download", _fake_download(archive, []))
    dest = tmp_path / "prusa"
    with pytest.raises(setup.SetupError, match="PrusaSlicer-2.9.7.zip.*does not match the pin"):
        setup.setup(dest)
    assert list((dest / "download").iterdir()) == []


def test_setup_refuses_a_non_empty_app_folder_before_downloading(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "old.txt").write_bytes(b"old")
    calls = []
    monkeypatch.setattr(setup, "check_platform", lambda: None)
    monkeypatch.setattr(setup, "download", _fake_download(b"", calls))
    with pytest.raises(setup.SetupError, match="not empty"):
        setup.setup(tmp_path)
    assert calls == []


def test_main_exits_2_on_another_platform_without_writing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(setup.platform, "system", lambda: "Linux")
    dest = tmp_path / "prusa"
    assert setup.main(["--dest", str(dest)]) == 2
    assert "Windows x64 only" in capsys.readouterr().err
    assert not dest.exists()


def test_main_verify_only_reports_a_mismatch(tmp_path, capsys):
    exe = tmp_path / PIN.exe.path
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"not the pinned exe")
    assert setup.main(["--verify-only", str(tmp_path)]) == 2
    assert "does not match the pin" in capsys.readouterr().err


def test_the_setup_helpers_are_shared_with_orcaslicer():
    orca_spec = importlib.util.spec_from_file_location(
        "setup_orcaslicer", REPO_ROOT / "scripts" / "setup_orcaslicer.py")
    orca = importlib.util.module_from_spec(orca_spec)
    orca_spec.loader.exec_module(orca)
    assert orca.SetupError is setup.SetupError
    assert orca.SetupError is setup._slicer_setup.SetupError

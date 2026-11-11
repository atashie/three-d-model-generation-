"""The PrusaSlicer pin, its verification and locate (docs/plans/2026-11-11-portability-check.md).

The pin's values come from research/verification/2026-11-11-prusaslicer-windows/; the
tests check them against that record where it has them.
"""

import hashlib
import os

import pytest

from tdmg.paths import REPO_ROOT
from tdmg.portability import (
    PRUSA_ENV_VAR,
    PRUSA_PIN_ID,
    PrusaPin,
    load_prusa_pin,
    locate_prusaslicer,
    verify_prusa_install,
)
from tdmg.slicer import SlicerError

RECORD = REPO_ROOT / "research" / "verification" / "2026-11-11-prusaslicer-windows"
PIN = load_prusa_pin()
EXE = "app/PrusaSlicer-2.9.7/prusa-slicer-console.exe"
DLL = "app/PrusaSlicer-2.9.7/PrusaSlicer.dll"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_lines(name: str) -> dict[str, str]:
    """`<sha256> *<path>` lines (sha256sum's binary-mode output) as {path: sha256}."""
    out = {}
    for line in (RECORD / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, path = line.split(" *", 1)
            out[path] = digest
    return out


# --- The pin -------------------------------------------------------------------------

def test_pin_loads_by_id():
    assert PIN.id == PRUSA_PIN_ID == "prusaslicer-2.9.7"
    assert (PIN.name, PIN.version, PIN.tag) == ("PrusaSlicer", "2.9.7", "version_2.9.7")
    assert PIN.release.platform == "windows-x64"
    assert PIN.release.asset == "PrusaSlicer-2.9.7.zip"
    assert PIN.release.url == ("https://github.com/prusa3d/PrusaSlicer/releases/download/"
                               "version_2.9.7/PrusaSlicer-2.9.7.zip")
    assert PIN.exe.path == EXE
    assert [lib.path for lib in PIN.libraries] == [DLL]
    assert PIN.app_tree.folder == "app"
    assert PIN.record == "research/verification/2026-11-11-prusaslicer-windows/README.md"
    assert (REPO_ROOT / PIN.record).is_file()


def test_pin_hashes_equal_the_research_record():
    install = _hash_lines("install-hashes.txt")
    assert PIN.release.sha256 == install["download/" + PIN.release.asset]
    assert PIN.release.sha256 == ("5d4f395aeb6c344b300e0e1be37a0e1931622b642c3c3085eb19cd"
                                  "ae211bc008")
    assert PIN.exe.sha256 == install[PIN.exe.path]
    # The README gives the zip digest GitHub publishes, too.
    assert PIN.release.sha256 in (RECORD / "README.md").read_text(encoding="utf-8")


def test_pin_decoding_is_the_measured_one():
    win = PIN.decoding["windows"]
    assert (win.error_exit, win.status) == (1, "measured")
    readme = (RECORD / "README.md").read_text(encoding="utf-8")
    assert "PrusaSlicer reports errors with exit code 1" in readme
    assert "An exit code of 0 is not success." in readme
    assert win.source.startswith(PIN.record)


def test_pin_refuses_an_exe_outside_the_app_folder():
    data = PIN.model_dump()
    data["exe"]["path"] = "elsewhere/prusa-slicer-console.exe"
    with pytest.raises(ValueError, match="inside app/"):
        PrusaPin.model_validate(data)


# --- Verifying and locating an install --------------------------------------------------

APP = {"PrusaSlicer-2.9.7/prusa-slicer-console.exe": b"exe",
       "PrusaSlicer-2.9.7/PrusaSlicer.dll": b"dll",
       "PrusaSlicer-2.9.7/resources/x.txt": b"x"}


def _tree(app: dict[str, bytes]) -> str:
    """The tree hash, computed here from its definition (not with tdmg.slicer)."""
    lines = sorted(f"{rel}\t{_sha(d)}" for rel, d in app.items())
    return _sha("".join(x + "\n" for x in lines).encode())


def fake_prusa_pin(app=None) -> PrusaPin:
    app = app or APP
    return PIN.model_copy(update={
        "exe": PIN.exe.model_copy(update={
            "sha256": _sha(app["PrusaSlicer-2.9.7/prusa-slicer-console.exe"])}),
        "libraries": [PIN.libraries[0].model_copy(update={
            "sha256": _sha(app["PrusaSlicer-2.9.7/PrusaSlicer.dll"])})],
        "app_tree": PIN.app_tree.model_copy(update={"files": len(app), "sha256": _tree(app)})})


def fake_prusa_install(root, app=None):
    for rel, data in (app or APP).items():
        path = root / "app" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def test_verify_accepts_matching_hashes(tmp_path):
    pin = fake_prusa_pin()
    found = verify_prusa_install(fake_prusa_install(tmp_path), pin, full_tree=True)
    assert found == {"exe_sha256": pin.exe.sha256,
                     "libraries": {DLL: pin.libraries[0].sha256},
                     "app_tree": {"files": 3, "sha256": pin.app_tree.sha256}}
    assert "app_tree" not in verify_prusa_install(tmp_path, pin)


@pytest.mark.parametrize(("change", "what"), [
    ({"PrusaSlicer-2.9.7/prusa-slicer-console.exe": b"other"}, "prusa-slicer-console.exe"),
    ({"PrusaSlicer-2.9.7/PrusaSlicer.dll": b"patched"}, "PrusaSlicer.dll")])
def test_verify_refuses_a_changed_exe_or_library(tmp_path, change, what):
    pin = fake_prusa_pin()
    fake_prusa_install(tmp_path, {**APP, **change})
    with pytest.raises(SlicerError, match=f"{what}.*does not match the pin.*"
                                          "setup_prusaslicer.py"):
        verify_prusa_install(tmp_path, pin)


@pytest.mark.parametrize("change", [{"PrusaSlicer-2.9.7/resources/x.txt": b"changed"},
                                    {"PrusaSlicer-2.9.7/extra.dll": b"new"}])
def test_verify_full_tree_refuses_any_other_change(tmp_path, change):
    pin = fake_prusa_pin()
    fake_prusa_install(tmp_path, {**APP, **change})
    assert verify_prusa_install(tmp_path, pin)["exe_sha256"] == pin.exe.sha256
    with pytest.raises(SlicerError, match="app tree.*does not match the pin"):
        verify_prusa_install(tmp_path, pin, full_tree=True)


def test_verify_refuses_a_missing_exe(tmp_path):
    with pytest.raises(SlicerError, match="prusa-slicer-console.exe is missing.*"
                                          "setup_prusaslicer.py"):
        verify_prusa_install(tmp_path, fake_prusa_pin())


def test_locate_is_none_when_not_configured(monkeypatch):
    monkeypatch.delenv(PRUSA_ENV_VAR, raising=False)
    assert locate_prusaslicer(None, fake_prusa_pin()) is None


def test_locate_from_the_argument_or_the_environment(tmp_path, monkeypatch):
    pin = fake_prusa_pin()
    root = fake_prusa_install(tmp_path / "prusa")
    monkeypatch.delenv(PRUSA_ENV_VAR, raising=False)
    found = locate_prusaslicer(root, pin)
    assert found.exe == root.resolve() / EXE
    assert found.verified["app_tree"] == {"files": 3, "sha256": pin.app_tree.sha256}
    assert found.pin == pin
    monkeypatch.setenv(PRUSA_ENV_VAR, str(root))
    assert locate_prusaslicer(None, pin) == found
    quick = locate_prusaslicer(None, pin, full_tree=False)
    assert "app_tree" not in quick.verified


def test_locate_refuses_a_folder_that_does_not_exist_or_does_not_match(tmp_path):
    pin = fake_prusa_pin()
    with pytest.raises(SlicerError, match="not a folder.*setup_prusaslicer.py"):
        locate_prusaslicer(tmp_path / "nowhere", pin)
    root = fake_prusa_install(tmp_path / "prusa",
                              {**APP, "PrusaSlicer-2.9.7/PrusaSlicer.dll": b"patched"})
    with pytest.raises(SlicerError, match="PrusaSlicer.dll.*does not match the pin"):
        locate_prusaslicer(root, pin)


@pytest.mark.slicer
@pytest.mark.skipif(not os.environ.get(PRUSA_ENV_VAR),
                    reason="TDMG_PRUSASLICER_DIR is not set to a verified PrusaSlicer install")
def test_the_real_install_matches_the_pin():
    found = locate_prusaslicer(None)
    assert found.verified["exe_sha256"] == PIN.exe.sha256
    assert found.verified["app_tree"] == {"files": PIN.app_tree.files,
                                          "sha256": PIN.app_tree.sha256}

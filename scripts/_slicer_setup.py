"""Helpers shared by scripts/setup_orcaslicer.py and scripts/setup_prusaslicer.py.

Each script downloads one pinned Windows x64 release zip (or takes --zip), checks its
SHA-256, extracts it into a fresh DIR/app/ and checks the exe, the pinned libraries and
the whole app tree against its pin file before moving it into place. A pin is any object
with release, exe, libraries and app_tree (tdmg.slicer.SlicerPin, tdmg.portability.PrusaPin).

Imported as a sibling module: Python puts scripts/ on sys.path when a script in it runs,
and pyproject.toml adds it for pytest.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from tdmg.slicer import app_tree_sha256, sha256_file

HTTP_TIMEOUT_S = 60   # per network read; a stalled connection fails instead of hanging
_CHUNK = 1 << 20


class SetupError(Exception):
    """The install was refused; nothing that failed a check is left in place."""


def fetch(url: str, user_agent: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        return resp.read()


def download(url: str, path: Path, user_agent: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp, open(path, "xb") as f:
        shutil.copyfileobj(resp, f, _CHUNK)


def check_hash(what: str, actual: str, expected: str) -> None:
    if actual != expected:
        raise SetupError(f"{what} has sha256 {actual}, which does not match the pin ({expected})")


def check_platform(system: str, machine: str) -> None:
    if system != "Windows" or machine.upper() not in ("AMD64", "X86_64"):
        raise SetupError(f"this script supports Windows x64 only (found {system} {machine}); "
                         "the pinned asset is the Windows x64 portable zip")


def require_empty(folder: Path) -> None:
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        raise SetupError(f"{folder} is not empty; choose a new --dest or remove it")


def install_app(dest: Path, pin, zip_path: Path | None,
                download: Callable[[str, Path], None]) -> None:
    """Get the release zip, check it, extract it into dest/app and check the exe, the
    libraries and the whole app tree. download(url, path) fetches the zip when needed."""
    app = dest / "app"
    require_empty(app)
    if zip_path is None:
        (dest / "download").mkdir(parents=True, exist_ok=True)
        zip_path = dest / "download" / pin.release.asset
        if not zip_path.exists():
            partial = zip_path.with_name(zip_path.name + ".partial")
            partial.unlink(missing_ok=True)
            download(pin.release.url, partial)
            try:
                check_hash(str(zip_path), sha256_file(partial), pin.release.sha256)
            except SetupError:
                partial.unlink()
                raise
            os.replace(partial, zip_path)
        elif sha256_file(zip_path) != pin.release.sha256:
            raise SetupError(f"the cached download {zip_path} does not match the pin "
                             f"({pin.release.sha256}); delete {zip_path} and run again")
    check_hash(str(zip_path), sha256_file(zip_path), pin.release.sha256)

    tmp = Path(tempfile.mkdtemp(dir=dest, prefix=".app-"))
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)   # extractall drops absolute paths and ".." components
        for pinned in (pin.exe, *pin.libraries):
            rel = Path(pinned.path).relative_to(pin.app_tree.folder)
            if not (tmp / rel).is_file():
                raise SetupError(f"the zip has no {rel}")
            check_hash(str(rel), sha256_file(tmp / rel), pinned.sha256)
        files, tree = app_tree_sha256(tmp)
        if (files, tree) != (pin.app_tree.files, pin.app_tree.sha256):
            raise SetupError(f"the extracted app tree ({files} files, sha256 {tree}) does not "
                             f"match the pin ({pin.app_tree.files} files, "
                             f"{pin.app_tree.sha256})")
        if app.exists():
            app.rmdir()         # empty, checked above
        os.replace(tmp, app)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

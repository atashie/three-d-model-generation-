"""The ignore rules for jobs and the print library (restructure design, sections 1 and 5).

The repository is public, so a source image or a non-public printable file must never be
staged by an ordinary `git add`. These tests ask git itself, so they skip outside a checkout.
"""

import shutil
import subprocess

import pytest

from tdmg.paths import REPO_ROOT

IGNORED = [
    "jobs/roadie-drop/job.yaml",
    "jobs/roadie-drop/source/roadie.png",
    "prints/roadie/source/roadie.png",
    "prints/roadie/source/mask.png",
    "prints/roadie/private/model.3mf",
    "prints/.staging-roadie/card.md",
]
TRACKED = [
    "prints/roadie/card.md",
    "prints/roadie/job.yaml",
    "prints/roadie/provenance.json",
    "prints/roadie/COMPLETE",
    "prints/roadie/files/model.3mf",
    "prints/roadie/files/palette.json",
]


def _in_checkout() -> bool:
    if shutil.which("git") is None:
        return False
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=REPO_ROOT, check=False,
                       capture_output=True, text=True)
    return r.returncode == 0


pytestmark = pytest.mark.skipif(not _in_checkout(), reason="not in a git checkout")


def _ignored(path: str) -> bool:
    r = subprocess.run(["git", "check-ignore", "--no-index", "-q", path],
                       cwd=REPO_ROOT, check=False)
    assert r.returncode in (0, 1), f"git check-ignore failed for {path}"
    return r.returncode == 0


@pytest.mark.parametrize("path", IGNORED)
def test_private_and_working_paths_are_ignored(path):
    assert _ignored(path)


@pytest.mark.parametrize("path", TRACKED)
def test_library_card_config_and_public_files_are_not_ignored(path):
    assert not _ignored(path)


@pytest.mark.parametrize("path", TRACKED)
def test_library_files_have_no_line_ending_conversion(path):
    # COMPLETE lists each file's SHA-256; with core.autocrlf=true (Git for Windows' default)
    # a text checkout would add CR bytes and `tdmg library check` would call the entry
    # damaged (seen in a fresh clone on the PC, 2026-11-17).
    r = subprocess.run(["git", "check-attr", "text", "--", path], cwd=REPO_ROOT,
                       check=True, capture_output=True, text=True)
    assert r.stdout.strip().endswith(": text: unset"), r.stdout

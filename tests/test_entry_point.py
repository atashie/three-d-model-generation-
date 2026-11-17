"""The tdmg console entry point passes the owner's words through verbatim.

Click (typer's copy) expands every argument on Windows by default: expanduser,
expandvars and glob, so '$HOME', '%USERNAME%', '~ x' and '*.png' reached tdmg rewritten
even inside shell single quotes (measured on the PC, 2026-11-17, in the Task 12 quality
review). `tdmg.cli.main` turns that off; `[project.scripts]` and `python -m tdmg.cli`
both use it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from PIL import Image

import tdmg.cli
from tdmg.jobs import load_job
from tdmg.paths import REPO_ROOT

# Each would be rewritten by the expansion: env vars (both forms), a leading tilde, a glob
# that matches a file in the working folder; and a leading slash (Git Bash's path
# conversion, which tdmg cannot undo: the skill sets MSYS_NO_PATHCONV=1).
WORDS = {"prompt": "~ tilde", "generator": "$HOME", "settings": "%USERNAME%",
         "references": "*.png", "chosen": "/yes", "edits": "it’s ${HOME} ~/x"}
FLAGS = {"prompt": "--prompt", "generator": "--generator", "settings": "--settings",
         "references": "--references", "chosen": "--chosen", "edits": "--edits"}


def _args(tmp_path: Path) -> list[str]:
    image = tmp_path / "img.png"
    Image.new("RGBA", (20, 10), (200, 30, 30, 255)).save(image)
    args = ["job", "new", "t1", "--class", "flat-icon", "--image", str(image),
            "--origin", "generated", "--jobs-dir", str(tmp_path / "jobs"),
            "--prints-dir", str(tmp_path / "prints")]
    for key, flag in FLAGS.items():
        args += [flag, WORDS[key]]
    return args


def _stored(tmp_path: Path) -> dict:
    source = load_job(tmp_path / "jobs" / "t1")["source"]
    return {key: source[key] for key in WORDS}


def test_pyproject_script_is_main():
    meta = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert meta["project"]["scripts"]["tdmg"] == "tdmg.cli:main"


def test_main_turns_windows_expansion_off(monkeypatch):
    seen = {}

    def fake_app(*args, **kw):
        seen.update(kw)

    monkeypatch.setattr(tdmg.cli, "app", fake_app)
    tdmg.cli.main()
    assert seen.get("windows_expand_args") is False


def test_main_keeps_the_words_verbatim(tmp_path, monkeypatch):
    """Through main() with sys.argv, as the console script calls it. On Windows this is
    where the expansion would happen; elsewhere it checks main() runs the CLI."""
    monkeypatch.chdir(tmp_path)               # so "*.png" would match img.png
    monkeypatch.setattr(sys, "argv", ["tdmg", *_args(tmp_path)])
    with pytest.raises(SystemExit) as e:
        tdmg.cli.main()
    assert e.value.code in (0, None)
    assert _stored(tmp_path) == WORDS


@pytest.mark.skipif(os.name != "nt", reason="the expansion is Windows-only")
def test_installed_script_keeps_the_words_verbatim(tmp_path):
    script = Path(sys.executable).parent / "tdmg.exe"
    if not script.exists():
        pytest.skip(f"no installed tdmg script beside {sys.executable}")
    proc = subprocess.run([str(script), *_args(tmp_path)], cwd=tmp_path, check=False,
                          capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "NO_COLOR": "1"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _stored(tmp_path) == WORDS


def test_module_run_keeps_the_words_verbatim(tmp_path):
    """python -m tdmg.cli (CI's wheel check and scripts/repeat_runs.py use it)."""
    proc = subprocess.run([sys.executable, "-m", "tdmg.cli", *_args(tmp_path)],
                          cwd=tmp_path, check=False, capture_output=True, text=True,
                          encoding="utf-8", env={**os.environ, "NO_COLOR": "1"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _stored(tmp_path) == WORDS

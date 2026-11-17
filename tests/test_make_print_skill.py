"""The make-print skill's commands exist in the CLI (restructure Task 12).

Every `tdmg ...` line inside a code block of .claude/skills/make-print/SKILL.md is parsed;
each subcommand and each --flag must exist in the typer app's click command tree, so the
skill cannot drift from the CLI. job set keys must be real stage parameters, and the
commands whose slice key depends on PrusaSlicer all give the same slicer folders.
"""

from __future__ import annotations

import re
import shlex

import pytest
import typer

from tdmg import jobs
from tdmg.cli import app
from tdmg.paths import REPO_ROOT

SKILL = REPO_ROOT / ".claude" / "skills" / "make-print" / "SKILL.md"
ORCA = "artifacts/tools/orcaslicer-2.5.0"
PRUSA = "artifacts/tools/prusaslicer-2.9.7"
# Commands that read the slice stage's key (PrusaSlicer configured or not) and those that
# run the slicer.
NEEDS_PRUSA = {("job", "run"), ("job", "status"), ("job", "confirm"), ("finish",)}
NEEDS_ORCA = {("job", "run"), ("finish",)}


def _code_lines(text: str) -> list[str]:
    """The lines inside fenced code blocks, with backslash continuations joined."""
    out, inside, pending = [], False, ""
    for line in text.splitlines():
        if line.strip().startswith("```"):
            inside = not inside
            continue
        if not inside:
            continue
        if line.rstrip().endswith("\\"):
            pending += line.rstrip()[:-1] + " "
            continue
        out.append(pending + line)
        pending = ""
    return out


def _tdmg_commands(text: str) -> list[list[str]]:
    """The arguments after `tdmg` of every tdmg command line in a code block."""
    commands = []
    for line in _code_lines(text):
        tokens = shlex.split(line, comments=True)
        if "tdmg" in tokens:
            commands.append(tokens[tokens.index("tdmg") + 1:])
    return commands


def _is_group(cmd) -> bool:
    # typer 0.28 carries its own copy of click (typer._click), so test by shape, not class.
    return isinstance(getattr(cmd, "commands", None), dict)


def _resolve(args: list[str]) -> tuple[tuple[str, ...], object, list[str]]:
    """Walk the click tree: (subcommand path, the command, the remaining arguments)."""
    cmd = typer.main.get_command(app)
    path: list[str] = []
    rest = list(args)
    while _is_group(cmd) and rest and not rest[0].startswith("-"):
        sub = cmd.commands.get(rest[0])
        assert sub is not None, f"tdmg {' '.join(path)}: no subcommand {rest[0]!r}"
        path.append(rest.pop(0))
        cmd = sub
    return tuple(path), cmd, rest


def _flags(cmd) -> set[str]:
    names = {"--help"}
    for p in cmd.params:
        if p.param_type_name == "option":
            names.update(o for o in (*p.opts, *p.secondary_opts) if o.startswith("--"))
    return names


def _option_value(rest: list[str], flag: str) -> str | None:
    for i, tok in enumerate(rest):
        if tok == flag and i + 1 < len(rest):
            return rest[i + 1]
        if tok.startswith(flag + "="):
            return tok.split("=", 1)[1]
    return None


COMMANDS = _tdmg_commands(SKILL.read_text(encoding="utf-8"))


def test_the_skill_has_its_commands():
    paths = {_resolve(args)[0] for args in COMMANDS}
    for needed in [("job", "new"), ("job", "set"), ("job", "run"), ("job", "status"),
                   ("job", "confirm"), ("finish",), ("library", "check"), ("strip",)]:
        assert needed in paths, f"the skill has no tdmg {' '.join(needed)} command"


def test_the_skill_has_frontmatter():
    text = SKILL.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "SKILL.md starts with YAML frontmatter"
    assert re.search(r"^name: make-print$", m.group(1), re.MULTILINE)
    assert re.search(r"^description: Use when ", m.group(1), re.MULTILINE)


@pytest.mark.parametrize("args", COMMANDS, ids=[" ".join(a)[:60] for a in COMMANDS])
def test_command_and_flags_exist(args):
    path, cmd, rest = _resolve(args)
    assert not _is_group(cmd) or "--help" in rest, (
        f"tdmg {' '.join(path)} is a group, not a command")
    known = _flags(cmd)
    for tok in rest:
        if tok.startswith("--"):
            flag = tok.split("=", 1)[0]
            assert flag in known, f"tdmg {' '.join(path)} has no option {flag}"


@pytest.mark.parametrize("args", COMMANDS, ids=[" ".join(a)[:60] for a in COMMANDS])
def test_job_set_keys_are_stage_parameters(args):
    path, _, rest = _resolve(args)
    if path != ("job", "set"):
        return
    pairs = [tok for tok in rest[1:] if not tok.startswith("--")]
    assert pairs, "job set without STAGE.KEY=VALUE"
    for pair in pairs:
        key = pair.split("=", 1)[0]
        stage, _, name = key.partition(".")
        assert stage in jobs.STAGE_FIELDS, f"{key}: no stage {stage!r}"
        assert name in jobs.STAGE_FIELDS[stage], f"{key}: stage {stage} has no {name!r}"


@pytest.mark.parametrize("args", COMMANDS, ids=[" ".join(a)[:60] for a in COMMANDS])
def test_slicer_folders_are_the_same_everywhere(args):
    path, _, rest = _resolve(args)
    if path in NEEDS_PRUSA:
        assert _option_value(rest, "--prusaslicer-dir") == PRUSA, (
            f"tdmg {' '.join(path)} must give --prusaslicer-dir {PRUSA}")
    if path in NEEDS_ORCA or _option_value(rest, "--slicer-dir") is not None:
        assert _option_value(rest, "--slicer-dir") == ORCA, (
            f"tdmg {' '.join(path)} must give --slicer-dir {ORCA}")


def test_pinned_slicer_folders_match_the_setup_scripts():
    """The folders named in the skill are the ones CLAUDE.md's verify commands check."""
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert f"setup_orcaslicer.py --verify-only {ORCA}" in text
    assert f"setup_prusaslicer.py --verify-only {PRUSA}" in text

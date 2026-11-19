"""The make-print skill's commands exist in the CLI (restructure Task 12).

Every `tdmg ...` line inside a code block of .claude/skills/make-print/SKILL.md is parsed;
each subcommand and each --flag must exist in the typer app's click command tree, so the
skill cannot drift from the CLI. job set keys (and every STAGE.KEY the text names) must
be real stage parameters, each job set line must be accepted by a temporary job, flag
values must be ones the CLI takes (or an upper-case placeholder), the commands that carry
the owner's words start with MSYS_NO_PATHCONV=1 and quote them in single quotes, and the
commands whose slice key depends on PrusaSlicer all give the same slicer folders.
"""

from __future__ import annotations

import re
import shlex

import pytest
import typer
from PIL import Image

from tdmg import jobs
from tdmg.cli import app
from tdmg.job_runner import set_parameters
from tdmg.paths import REPO_ROOT
from tdmg.recipes import CLASSES, RECIPES

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


def _set_args(rest: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """(STAGE.KEY=VALUE assignments, (STAGE.KEY, WORDS) of --text) of a job set line's
    arguments after the job name; other --flags (and their values) are left out."""
    pairs, texts, i = [], [], 0
    while i < len(rest):
        tok = rest[i]
        if tok == "--text":
            texts.append((rest[i + 1], rest[i + 2]))
            i += 3
        elif tok.startswith("--"):
            i += 1 if "=" in tok else 2
        else:
            pairs.append(tok)
            i += 1
    return pairs, texts


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
    pairs, texts = _set_args(rest[1:])
    assert pairs or texts, "job set without STAGE.KEY=VALUE or --text STAGE.KEY WORDS"
    for key in [p.split("=", 1)[0] for p in pairs] + [t for t, _ in texts]:
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


# --- values, words and job set lines ---------------------------------------------------

PLACEHOLDER = re.compile(r"^[A-Z][A-Z_]*$")
VALUES = {
    "--class": set(CLASSES),
    "--origin": set(jobs.ORIGINS),
    "--subject": set(jobs.SUBJECTS),
    "--face": set(jobs.CONFIRM_FACES),
    "--route": {route.name for r in RECIPES for route in r.routes},
    "--public": {"yes", "no"},
}
WORD_FLAGS = ("--owner-said", "--purge-owner-said", "--prompt", "--generator",
              "--generator-version", "--settings", "--references", "--chosen", "--edits")
# A rule id such as flat.sliver.opening_width has a third part; a stage key has two.
STAGE_KEY = re.compile(r"\b(" + "|".join(jobs.STAGE_FIELDS) + r")\.([a-z_]+)\b(?!\.\w)")
FILE_SUFFIXES = {"json", "png", "yaml", "md", "stl", "3mf", "gcode"}


@pytest.mark.parametrize("args", COMMANDS, ids=[" ".join(a)[:60] for a in COMMANDS])
def test_flag_values_are_ones_the_cli_takes(args):
    _, _, rest = _resolve(args)
    for flag, allowed in VALUES.items():
        value = _option_value(rest, flag)
        if value is not None:
            assert value in allowed or PLACEHOLDER.match(value), (
                f"{flag} {value!r}: not one of {sorted(allowed)} or a placeholder")


def _raw_tdmg_lines(text: str) -> list[str]:
    return [line.strip() for line in _code_lines(text) if " tdmg " in f" {line} "]


@pytest.mark.parametrize("line", _raw_tdmg_lines(SKILL.read_text(encoding="utf-8")))
def test_owner_words_are_single_quoted_without_path_conversion(line):
    """Git Bash turns a leading / into a Windows path unless MSYS_NO_PATHCONV=1, and only
    single quotes keep $, ` and ! from the shell."""
    carries = (any(f" {flag} " in line for flag in WORD_FLAGS)
               or "select.instructions" in line)
    if not carries:
        return
    assert line.startswith("MSYS_NO_PATHCONV=1 "), line
    for flag in WORD_FLAGS:
        if f" {flag} " in line:
            assert f" {flag} '" in line, f"{flag} words are not in single quotes: {line}"
    if " --text " in line:
        assert re.search(r" --text [a-z_]+\.[a-z_]+ '", line), (
            f"--text words are not in single quotes: {line}")


def test_owner_words_in_job_set_use_text():
    """select.instructions holds the owner's words: given with --text (stored as they
    are), never as STAGE.KEY=VALUE, which reads YAML (a backslash escape, a colon)."""
    lines = [line for line in _raw_tdmg_lines(SKILL.read_text(encoding="utf-8"))
             if "select.instructions" in line]
    assert lines, "the skill does not record select.instructions"
    for line in lines:
        assert "--text select.instructions '" in line and "select.instructions=" not in line


def test_every_stage_key_named_in_the_skill_exists():
    text = SKILL.read_text(encoding="utf-8")
    named = {(m.group(1), m.group(2)) for m in STAGE_KEY.finditer(text)
             if m.group(2) not in FILE_SUFFIXES}
    assert named, "the skill names no stage parameters"
    for stage, key in sorted(named):
        assert key in jobs.STAGE_FIELDS[stage], f"{stage}.{key} is not a stage parameter"


def _set_lines() -> list[list[str]]:
    return [args for args in COMMANDS if _resolve(args)[0] == ("job", "set")]


@pytest.mark.parametrize("args", _set_lines(), ids=[" ".join(a)[:60] for a in _set_lines()])
def test_job_set_lines_are_accepted(args, tmp_path):
    """Apply the line's assignments to a new job of the recipe they belong to, so every
    value parses and passes the stage's checks (a placeholder path becomes a real file)."""
    _, _, rest = _resolve(args)
    pairs, texts = _set_args(rest[1:])
    image = tmp_path / "img.png"
    Image.new("RGBA", (20, 10), (200, 30, 30, 255)).save(image)
    colors = not any(p.startswith("flat.") for p in pairs)
    jobs.new_job(tmp_path / "jobs", "t1", "flat-icon", image, colors=colors,
                 prints_dir=tmp_path / "prints")
    mask = tmp_path / "mask.png"
    Image.new("L", (20, 10), 255).save(mask)
    pairs = [f"select.mask={mask}" if p.startswith("select.mask=") else p for p in pairs]
    job, _ = set_parameters(tmp_path / "jobs" / "t1", pairs, texts)
    for target, words in texts:
        stage, key = target.split(".")
        assert job["stages"][stage][key] == words

"""The print library, `prints/<name>/`, and `tdmg finish` (restructure plan Task 9; design
docs/plans/2026-11-16-restructure-design.md section 5, with its amendments, and the plan's
dated notes to Task 9).

**A library entry** (`prints/NAME/`), once finished:

    card.md          what to print and how, for people (tracked)
    job.yaml         the job's spec, byte for byte as it was in jobs/NAME/ (tracked)
    provenance.json  code, environment, rules, profiles, algorithms, checks, verdicts and the
                     owner's confirmations, verbatim (tracked)
    source/          the source image and its mask, if any (git-ignored)
    files/ or        the confirmed route's printable files (Route.required_files): files/
    private/         when the owner says the design may be public (tracked), else private/
                     (git-ignored)
    purge.json       the purge record: the owner's words, the date and every file of
                     jobs/NAME with its SHA-256 (tracked)
    COMPLETE         the SHA-256 of every other file of the entry, written last (tracked)

A folder without COMPLETE is not a finished entry.

**Where the purge record goes, and why COMPLETE comes last.** The purge record is its own
file, purge.json, written after the publish and before COMPLETE; COMPLETE then lists it
with every other file, and only then is jobs/NAME deleted. So COMPLETE is last and correct,
and provenance.json stays byte for byte the file that was staged and checked before the
publish: writing the purge record into provenance.json after COMPLETE would make COMPLETE's
hash of it wrong, and writing COMPLETE again would break "written last". purge.json says
what will be deleted (it is written before the deletion); finish checks afterwards that the
folder is gone.

**The steps** (finish):
1. Names and paths: NAME is a job name (tdmg.jobs.check_name); the job is exactly
   JOBS_DIR/NAME, a folder with job.yaml; no component of the job folder, PRINTS_DIR, the
   staging folder PRINTS_DIR/.staging-NAME or the entry PRINTS_DIR/NAME is a symlink or a
   junction; the job and the library folders are disjoint after resolving; PRINTS_DIR/NAME
   is absent (unless resuming). The job's lock (tdmg.job_runner.job_lock) is held for the
   whole finish.
2. State: the source files match job.yaml; every stage is done and current (job_status,
   with the same Machine as job run); one print confirmation is chosen (choose_print) and
   it is current; the git tree of the code checkout is clean outside the jobs and prints
   folders, since the commit pins the code (git_state). Outside a git checkout, refused.
3. Stage PRINTS_DIR/.staging-NAME/: job.yaml, source/ (the image and the mask job.yaml
   names), the printable files of the confirmed route (in files/ or private/),
   provenance.json and card.md. Each file is read once, checked against its hash
   (job.yaml's source hashes, the confirmation's covers) and written from those bytes.
4. Rebuild: job.yaml and source/ from the staging folder are copied into a scratch folder
   (tempfile) as a fresh job and run with tdmg.job_runner.run_job and the same Machine.
   Every file of every stage folder is compared with the job's (compare_jobs: byte for
   byte, except the measured volatile parts), and the rebuilt slice record's identity,
   verdicts and printable-file hashes with the confirming entry's (so a hand-edited
   verdict is caught). On any difference the staging folder is removed, nothing is
   deleted, and finish stops (RebuildDiffers; exit 1).
5. Public: the owner's answer (--public yes|no, required) is in the card and
   provenance.json, and decides files/ or private/.
6. Publish: the staging folder is renamed to PRINTS_DIR/NAME; then purge.json; then
   COMPLETE.
7. Purge: needs the owner's words (--purge-owner-said, verbatim, not blank; dated with
   today's local date, as confirmations are). Every file and folder under jobs/NAME is
   listed with its SHA-256 (a link inside it is refused) into purge.json; COMPLETE is
   written and checked again (every hash); then exactly jobs/NAME is deleted
   (shutil.rmtree, refusing to follow links) and checked to be gone.

**Dry run** (dry_run): steps 1 to 4, including the rebuild; then it says what 5 to 7 would
do and removes the staging folder (and PRINTS_DIR, if it made it). Nothing else changes.
The purge words are not needed. It is refused while an earlier finish is unfinished.

**Resume.** Running finish again after an interruption looks at what is on disk:
- a staging folder (and no entry): the earlier run stopped before the publish. The
  staging folder holds only copies of the job's files and what finish wrote, so it is
  removed and steps 3 and 4 run again;
- PRINTS_DIR/NAME without COMPLETE: the publish happened (the rename comes only after
  the rebuild passed). It is never redone. Steps 1 and 2 run again; the entry's
  provenance.json must name the same confirmation, the same public answer and the same
  stage-record hashes as the job has now, and its job.yaml, source and printable files
  must equal the job's byte for byte. Then purge.json (replaced if an earlier run wrote
  one: the words of the run that deletes are recorded), COMPLETE and the purge;
- PRINTS_DIR/NAME with COMPLETE while jobs/NAME still exists: the purge was interrupted.
  COMPLETE must verify (verify_complete), and every file left in jobs/NAME must be in
  purge.json with the same SHA-256; then the deletion is finished. purge.json is kept as
  it is (COMPLETE covers it);
- COMPLETE and no jobs/NAME: already finished; COMPLETE is verified and reported.
Anything else (a staging folder beside an entry, an entry or staging folder whose job is
gone, an entry of another job) is refused with nothing changed. jobs/NAME is deleted only
when PRINTS_DIR/NAME has COMPLETE and every hash in it matches.

**The rebuild comparison** (compare_jobs). The evidence is
research/verification/2026-11-16-repeatability/README.md: two runs of the same inputs
differ only in the slicers' timestamp line of each G-code and in slice.json's hashes of
those G-code files. So:
- a G-code file (GCODE_TIMESTAMPS: plate_1.gcode, PrusaSlicer's
  prusaslicer.portability-only.gcode.txt, and their .failed forms) may differ in its
  timestamp line only (OrcaSlicer: line 2; PrusaSlicer: line 1), and only when that line
  matches the measured pattern in both files (re.fullmatch, line end removed); every other
  line byte for byte and the same number of lines (the README's "G-code allowance");
- slice.json may differ only at VOLATILE_FIELDS (the README's table of fields, with
  <plate> a glue plate name), and only where both values are SHA-256 strings; the
  README's "inferred, not measured" forms (plate_1.gcode.failed at the top level,
  face-up/plate_1.gcode.failed, a top-level PrusaSlicer .failed G-code) are not in it;
- every other file byte for byte, and the same set of files in every stage folder.
state.json and .lock are not compared: state.json holds slice.json's SHA-256 (the plan's
note to Task 9), and .lock is the lock.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from tdmg import __version__, confirmations, jobs, paths
from tdmg.color_slicing import PRINT_FACE
from tdmg.job_runner import (
    DONE,
    LOCK_FILE,
    STAGE_RECORDS,
    ConfirmationStatus,
    Machine,
    job_lock,
    job_status,
    rules_sha256,
    run_job,
    stage_algorithms,
    stage_profiles,
)
from tdmg.jobs import JOB_FILE, SOURCE_DIR, JobError, check_name, load_job, parse_job
from tdmg.portability import PRUSA_FAILED_GCODE_NAME, PRUSA_GCODE_NAME
from tdmg.recipes import GLUE_FILE, recipe
from tdmg.records import RecordError, record_text, replace_file, write_outputs
from tdmg.rules import load_rules
from tdmg.slicing import FAILED_GCODE_NAME, GCODE_NAME, PRINT_THIS

CARD_FILE = "card.md"
PROVENANCE_FILE = "provenance.json"
PURGE_FILE = "purge.json"
COMPLETE_FILE = "COMPLETE"
PUBLIC_DIR = "files"             # tracked: the owner said the design may be public
PRIVATE_DIR = "private"          # git-ignored (.gitignore prints/*/private/)
STAGING_PREFIX = ".staging-"     # git-ignored (.gitignore prints/.staging-*/)
PROVENANCE_SCHEMA = "tdmg.provenance/1"
PURGE_SCHEMA = "tdmg.purge/1"
COMPLETE_SCHEMA = "tdmg.complete/1"
REPEATABILITY = "research/verification/2026-11-16-repeatability/README.md"
# Temporary names tdmg.records.replace_file uses in the entry (".<stem>-XXXX.tmp"); a crash
# can leave one behind, and the resume removes it.
LEFTOVER_TMP = re.compile(r"\.(COMPLETE|purge)-[^/]*\.tmp")
# The installed distributions provenance.json names, with their versions (None when not
# installed): pyproject.toml's runtime dependencies.
KEY_LIBRARIES = ("numpy", "scipy", "trimesh", "networkx", "lxml", "manifold3d", "lib3mf",
                 "shapely", "opencv-python-headless", "build123d", "vtracer", "pillow",
                 "pydantic", "typer", "pyyaml", "contourpy")

# --- the rebuild comparison (module docstring; REPEATABILITY) ---------------------------------

# The G-code timestamp lines, by file name: (line number from 1, the measured pattern). The
# README's "G-code allowance" table; the same patterns as scripts/repeat_runs.py.
_ORCA_STAMP = (2, re.compile(
    r"; generated by OrcaSlicer 2\.5\.0 on \d{4}-\d{2}-\d{2} at \d{2}:\d{2}:\d{2}"))
_PRUSA_STAMP = (1, re.compile(
    r"; generated by PrusaSlicer 2\.9\.7 on \d{4}-\d{2}-\d{2} at \d{2}:\d{2}:\d{2} UTC"))
GCODE_TIMESTAMPS = {GCODE_NAME: _ORCA_STAMP, FAILED_GCODE_NAME: _ORCA_STAMP,
                    PRUSA_GCODE_NAME: _PRUSA_STAMP, PRUSA_FAILED_GCODE_NAME: _PRUSA_STAMP}
# slice.json's fields that may differ between two runs: the README's "Fields that differ
# between two runs" table (slice.json rows), as key paths; "<plate>" is a glue plate's name
# (tdmg.recipes.GLUE_FILE without ".stl"). Nothing else may differ.
PLATE = "<plate>"
VOLATILE_FIELDS: tuple[tuple[str, ...], ...] = (
    ("gcode", "sha256"),
    ("portability", "gcode", "sha256"),
    ("faces", "up", "gcode", "sha256"),
    ("faces", "down", "gcode", "sha256"),
    ("glue", "plates", PLATE, "gcode", "sha256"),
    ("glue", "plates", PLATE, "portability", "gcode", "sha256"),
    ("outputs", "plate_1.gcode"),
    ("outputs", "prusaslicer.portability-only.gcode.txt"),
    ("outputs", "face-up/plate_1.gcode"),
    ("outputs", "face-down/plate_1.gcode"),
    ("outputs", "face-down/plate_1.gcode.failed"),
    ("outputs", f"{PLATE}/plate_1.gcode"),
    ("outputs", f"{PLATE}/plate_1.gcode.failed"),
    ("outputs", f"{PLATE}/prusaslicer.portability-only.gcode.txt"),
    ("outputs", f"{PLATE}/prusaslicer.portability-only.gcode.txt.failed"),
)
_PLATE_PATTERN = GLUE_FILE.removesuffix(r"\.stl")
_VOLATILE = tuple(tuple(re.compile(re.escape(k).replace(re.escape(PLATE), _PLATE_PATTERN))
                        for k in path) for path in VOLATILE_FIELDS)
SLICE_RECORD = STAGE_RECORDS["slice"]
MAX_SHOWN = 12                   # differing JSON paths shown per file


class LibraryError(ValueError):
    """finish refuses, or cannot go on; what it changed is said in the message. Nothing
    of the job is deleted."""


class RebuildDiffers(LibraryError):
    """The rebuild does not match the job; `differences` lists the files and fields."""

    def __init__(self, differences: list[str]):
        self.differences = differences
        super().__init__("the rebuild does not match the job: " + "; ".join(differences))


def _p(path) -> str:
    """A path for a message, ASCII-safe."""
    text = str(path)
    return text if text.isascii() else ascii(text)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hex(v) -> bool:
    return isinstance(v, str) and jobs.HEX64.fullmatch(v) is not None


def _words(text: str) -> str:
    return json.dumps(text, ensure_ascii=True)


# --- folders -----------------------------------------------------------------------------------

def default_prints_dir() -> Path:
    """The checkout's prints/ folder; outside a source checkout, --prints-dir is needed."""
    if paths.REPO_ROOT is None:
        raise LibraryError("tdmg is not running from a source checkout, so there is no "
                           "default prints folder; give --prints-dir")
    return paths.REPO_ROOT / "prints"


def code_checkout() -> Path | None:
    """The source checkout whose git commit pins the code (None from a wheel)."""
    return paths.REPO_ROOT


def _no_links(path: Path, what: str) -> None:
    """Refuse a path any existing component of which is a symlink or a junction."""
    p = Path(os.path.abspath(path))
    for q in (p, *p.parents):
        if q.is_symlink() or q.is_junction():
            raise LibraryError(f"{what} {_p(p)}: {_p(q)} is a link (symlink or junction); "
                               "finish works only on plain folders")


def _inside(a: Path, b: Path) -> bool:
    return a == b or b in a.parents


def _walk(root: Path) -> tuple[list[str], list[str]]:
    """(files, folders) under root, as sorted POSIX paths relative to it, without following
    links; LibraryError on a link or anything that is not a plain file or folder."""
    files, folders = [], []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        for name in sorted(dirnames + filenames):
            path = here / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink() or path.is_junction():
                raise LibraryError(f"{_p(path)} is a link (symlink or junction); finish "
                                   "does not follow links, so it stops here")
            if path.is_dir():
                folders.append(rel)
            elif path.is_file():
                files.append(rel)
            else:
                raise LibraryError(f"{_p(path)} is not a plain file or folder")
    return sorted(files), sorted(folders)


def _hashes(root: Path, files: list[str]) -> dict[str, str]:
    return {rel: _sha((root / rel).read_bytes()) for rel in files}


# --- step 2: state ------------------------------------------------------------------------------

@dataclass(frozen=True)
class Git:
    commit: str
    uv_lock_sha256: str


def _git(top: Path, *args: str) -> bytes:
    try:
        done = subprocess.run(["git", "-C", str(top), *args], capture_output=True,
                              check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise LibraryError(f"cannot run git ({e}); finish needs git: the commit pins the "
                           "code") from None
    if done.returncode != 0:
        err = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise LibraryError(f"git {' '.join(args)} failed in {_p(top)}"
                           + (f": {_p(err[-1])}" if err else ""))
    return done.stdout


def git_state(repo: Path | None, jobs_dir: Path, prints_dir: Path) -> Git:
    """The commit and uv.lock's SHA-256 of the code checkout, after checking that
    `git status --porcelain` shows nothing outside the jobs and prints folders."""
    if repo is None:
        raise LibraryError("tdmg is not running from a git checkout, so no commit pins the "
                           "code; run finish from the source checkout")
    if not (Path(repo) / ".git").exists():
        raise LibraryError(f"{_p(repo)} is not a git checkout (no .git); the commit pins the "
                           "code, so finish needs one")
    top = Path(_git(Path(repo), "rev-parse", "--show-toplevel").decode("utf-8").strip())
    out = _git(top, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    skip = []
    for folder in (jobs_dir, prints_dir):
        try:
            skip.append(Path(folder).resolve().relative_to(top.resolve()).as_posix())
        except ValueError:
            pass                        # outside the checkout: git does not list it
    entries = out.split(b"\0")
    dirty, i = [], 0
    while i < len(entries):
        entry = entries[i].decode("utf-8", "replace")
        i += 1
        if not entry:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            i += 1                      # a rename or copy: the source path follows
        if any(path == s or path.startswith(s + "/") for s in skip):
            continue
        dirty.append(path)
    if dirty:
        shown = ", ".join(_p(d) for d in dirty[:5]) + (" ..." if len(dirty) > 5 else "")
        raise LibraryError(f"the git tree is not clean ({len(dirty)} change(s) outside the "
                           f"jobs and prints folders: {shown}); commit or remove them first, "
                           "so the commit pins the code that made the print")
    commit = _git(top, "rev-parse", "HEAD").decode("ascii").strip()
    lock = top / "uv.lock"
    if not lock.is_file():
        raise LibraryError(f"{_p(top)} has no uv.lock; the library records its SHA-256")
    return Git(commit, _sha(lock.read_bytes()))


def choose_print(status, number: int | None) -> ConfirmationStatus:
    """The print confirmation finish uses (the plan's note to Task 9): --confirmation N
    when given (it must be a current print entry); else the one current print entry, or
    the latest of several that share route and face. Several current entries that differ
    in route or face need --confirmation."""
    prints = [c for c in status.confirmations if c.entry["subject"] == "print"]
    current = [c for c in prints if c.current and not c.stages_stale]
    if number is not None:
        found = [c for c in status.confirmations if c.number == number]
        if not found:
            raise LibraryError(f"--confirmation {number}: job {status.name} has no "
                               f"confirmation {number} (tdmg job status lists them)")
        c = found[0]
        if c.entry["subject"] != "print":
            raise LibraryError(f"--confirmation {number} is a {c.entry['subject']} "
                               "confirmation, not a print confirmation")
        if c not in current:
            why = c.problem or "a stage it rests on is not done"
            raise LibraryError(f"confirmation {number} is stale ({why}); ask the owner to "
                               "confirm the print again (tdmg job confirm)")
        return c
    if not current:
        stale = [c for c in prints if c not in current]
        why = ("; ".join(f"confirmation {c.number} is stale ({c.problem})" for c in stale)
               if stale else "there is none")
        raise LibraryError(f"no current print confirmation: {why}. The owner confirms the "
                           "print they made: tdmg job confirm --subject print")
    kinds = {(c.entry["route"], c.entry["face"]) for c in current}
    if len(kinds) > 1:
        listed = ", ".join(f"{c.number} ({confirmations.describe(c.entry)})" for c in current)
        raise LibraryError(f"several current print confirmations differ in route or face "
                           f"({listed}); give --confirmation N for the one to finish")
    return max(current, key=lambda c: c.number)


@dataclass
class State:
    folder: Path
    job: dict
    job_bytes: bytes
    status: object
    chosen: ConfirmationStatus
    current_prints: list[ConfirmationStatus]
    records: dict[str, bytes]            # stage -> its record's bytes
    git: Git


def check_state(folder: Path, machine: Machine, number: int | None, repo: Path | None,
                jobs_dir: Path, prints_dir: Path) -> State:
    """Step 2 (module docstring)."""
    job_bytes = (folder / JOB_FILE).read_bytes()
    try:
        job = load_job(folder)
        if parse_job(job_bytes) != job:
            raise JobError(f"{JOB_FILE} changed while it was read; try again")
        jobs.check_source(folder, job)
    except JobError as e:
        raise LibraryError(str(e)) from None
    status = job_status(folder, machine, job=job)
    for s in status.stages:
        if s.state != DONE:
            raise LibraryError(f"stage {s.stage} is {s.state}" + (f" ({s.note})" if s.note
                               else "") + "; finish needs every stage done and current (tdmg "
                               "job run, with the same --prusaslicer-dir)")
    chosen = choose_print(status, number)
    current = [c for c in status.confirmations if c.entry["subject"] == "print"
               and c.current and not c.stages_stale]
    records = {s: (folder / s / STAGE_RECORDS[s]).read_bytes()
               for s in recipe(job["recipe"]).stages}
    git = git_state(repo, jobs_dir, prints_dir)
    return State(folder, job, job_bytes, status, chosen, current, records, git)


# --- step 3: what is staged --------------------------------------------------------------------

def _printable(state: State) -> dict[str, tuple[str, bytes]]:
    """{library name: (job path, bytes)} of the confirmed route's printable files, each
    read once and checked against the confirmation's covers."""
    entry = state.chosen.entry
    out = {}
    for rel, digest in entry["covers"].items():
        data = (state.folder / rel).read_bytes()
        if _sha(data) != digest:
            raise LibraryError(f"{rel} changed since it was confirmed; ask the owner to "
                               "confirm the print again")
        out[rel.partition("/")[2]] = (rel, data)
    return out


def payload(state: State, public: bool) -> dict[str, bytes]:
    """The entry's copied files: job.yaml, source/ (image and mask) and the printable
    files in files/ or private/, each checked against its hash."""
    job = state.job
    files = {JOB_FILE: state.job_bytes}
    for src in [job["source"]] + ([job["source"]["mask"]] if job["source"]["mask"] else []):
        data = (state.folder / src["file"]).read_bytes()
        if _sha(data) != src["sha256"]:
            raise LibraryError(f"source file {src['file']} changed while it was read")
        files[src["file"]] = data
    folder = PUBLIC_DIR if public else PRIVATE_DIR
    for name, (_, data) in _printable(state).items():
        files[f"{folder}/{name}"] = data
    return files


def _json(data: bytes) -> dict:
    return json.loads(data)


def _walk_json(obj, path=()):
    """Every (key path, dict) in a JSON value, depth first."""
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from _walk_json(v, (*path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_json(v, (*path, i))


def json_path(path) -> str:
    """'$.faces.down.verdict', '$.outputs["plate_1.gcode"]', '$.checks[3]' (the README's
    notation: a key holding . / [ ] or " is written in brackets as a JSON string)."""
    out = "$"
    for k in path:
        if isinstance(k, int):
            out += f"[{k}]"
        elif re.fullmatch(r"[A-Za-z0-9_-]+", k):
            out += f".{k}"
        else:
            out += f"[{json.dumps(k, ensure_ascii=True)}]"
    return out


def check_results(record: dict) -> list[dict]:
    """Every check result in a record (a dict with "id" and "status"): where it is, its id,
    status, rule and threshold."""
    return [{"path": json_path(p), "id": d["id"], "status": d["status"],
             "rule": d.get("rule"), "threshold": d.get("threshold")}
            for p, d in _walk_json(record) if "id" in d and "status" in d]


def verdicts_in(record: dict) -> list[dict]:
    """Every verdict and certification in a record, with where it is."""
    out = []
    for p, d in _walk_json(record):
        for key in ("verdict", "certification"):
            if key in d and (d[key] is None or isinstance(d[key], str)):
                out.append({"path": json_path((*p, key)), "value": d[key]})
        if isinstance(d.get("verdicts"), dict):
            out.append({"path": json_path((*p, "verdicts")), "value": d["verdicts"]})
    return out


def rules_used(records: dict[str, dict]) -> dict[str, dict]:
    """The rules the stage records name ("rule": id, or "rules": [ids] in a formula), each
    with its registry entry, the values the records hold beside a single "rule" ("value":
    the rule's value as used) and the thresholds of checks that name it ("threshold": what
    the check derived from it, not the rule's own value). A formula's "value" is the
    formula's result, so it is not taken as a rule value."""
    registry = load_rules()
    seen: dict[str, dict[str, list]] = {}

    def add(rid, key, value):
        if rid in registry:
            bucket = seen.setdefault(rid, {"values": [], "thresholds": []})[key]
            if value is not None and value not in bucket:
                bucket.append(value)
    for rec in records.values():
        for _, d in _walk_json(rec):
            if isinstance(d.get("rule"), str):
                add(d["rule"], "values", d.get("value"))
                add(d["rule"], "thresholds", d.get("threshold"))
            if isinstance(d.get("rules"), list):
                for rid in d["rules"]:
                    if isinstance(rid, str):
                        add(rid, "values", None)
    out = {}

    def ordered(values):
        return sorted(values, key=lambda v: json.dumps(v, sort_keys=True))
    for rid in sorted(seen):
        r = registry[rid]
        out[rid] = {"values_in_records": ordered(seen[rid]["values"]),
                    "check_thresholds": ordered(seen[rid]["thresholds"]),
                    "default": r.default, "unit": r.unit,
                    "range": None if r.range is None else list(r.range), "kind": r.kind,
                    "provenance": r.best_provenance, "validation": r.best_validation,
                    "summary": r.summary}
    return out


def _libraries() -> dict[str, str | None]:
    out = {}
    for dist in KEY_LIBRARIES:
        try:
            out[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            out[dist] = None
    return out


def provenance(state: State, public: bool, machine: Machine, today: str) -> dict:
    """provenance.json's content (module docstring)."""
    job = state.job
    rid = job["recipe"]
    entry = state.chosen.entry
    recs = {s: _json(b) for s, b in state.records.items()}
    folder = PUBLIC_DIR if public else PRIVATE_DIR
    printable = {f"{folder}/{name}": _sha(data)
                 for name, (_, data) in _printable(state).items()}
    slice_rec = recs["slice"]
    stages = {}
    for s in recipe(rid).stages:
        rec = recs[s]
        stages[s] = {"record": f"{s}/{STAGE_RECORDS[s]}",
                     "record_sha256": _sha(state.records[s]),
                     "algorithm": rec.get("algorithm"),
                     "algorithms_expected": stage_algorithms(job, s),
                     "tdmg_version": rec.get("tdmg_version"),
                     "verdicts": verdicts_in(rec), "checks": check_results(rec)}
    return {
        "schema": PROVENANCE_SCHEMA,
        "name": job["name"], "class": job["class"], "recipe": rid,
        "route": entry["route"], "face": entry["face"],
        "public": public, "printable_folder": folder, "printable_files": printable,
        "source": copy.deepcopy(job["source"]),
        "code": {"git_commit": state.git.commit, "uv_lock_sha256": state.git.uv_lock_sha256,
                 "tdmg_version": __version__},
        "environment": {"python": platform.python_version(),
                        "implementation": platform.python_implementation(),
                        "platform": platform.platform(), "machine": platform.machine(),
                        "libraries": _libraries()},
        "rules_sha256": rules_sha256(), "rules": rules_used(recs),
        "profiles": {s: p for s in recipe(rid).stages
                     if (p := stage_profiles(job, s, machine))},
        "slicers": {"orcaslicer": slice_rec.get("slicer"),
                    "prusaslicer": (slice_rec.get("portability") or {}).get("slicer")},
        "stages": stages,
        "confirmation": {"number": state.chosen.number, "entry": copy.deepcopy(entry)},
        "print_confirmations": [{"number": c.number, "entry": copy.deepcopy(c.entry)}
                                for c in state.current_prints],
        "rebuild": {"proof": "before the publish, the job was rebuilt in a scratch folder "
                             "from job.yaml and source/ only, at this commit, and every "
                             "stage folder compared with the job's",
                    "allowed": {"gcode_timestamp_lines": {
                                    name: {"line": line, "pattern": pat.pattern}
                                    for name, (line, pat) in GCODE_TIMESTAMPS.items()},
                                "slice_json_fields": [json_path(f) for f in VOLATILE_FIELDS]},
                    "evidence": REPEATABILITY},
        "purge_record": PURGE_FILE,
        "finished": today,
    }


# --- step 3: the card ---------------------------------------------------------------------------

def _quote(text: str) -> list[str]:
    return [f"> {line}" if line else ">" for line in text.split("\n")]


def _route_sections(route: str, face: str | None, slice_rec: dict) -> list[tuple[str, dict]]:
    """(name, slice record section) of what was confirmed: single, the record; ams, the
    face; glue, each plate."""
    if route == "single":
        return [("model.stl", slice_rec)]
    if route == "ams":
        return [(f"face {face}", slice_rec["faces"][face])]
    return [(name, p) for name, p in slice_rec["glue"]["plates"].items()]


def _unknown_checks(section: dict) -> list[str]:
    return sorted({c["id"] for c in check_results(section) if c["status"] == "UNKNOWN"})


def card(state: State, public: bool, today: str) -> str:
    """card.md: what to print and how, in plain English (module docstring)."""
    job, entry = state.job, state.chosen.entry
    rid, route, face = job["recipe"], entry["route"], entry["face"]
    r = recipe(rid)
    recs = {s: _json(b) for s, b in state.records.items()}
    slice_rec = recs["slice"]
    stage = jobs.print_stage(rid)
    made = recs[stage]
    folder = PUBLIC_DIR if public else PRIVATE_DIR
    printable = _printable(state)
    L = [f"# {job['name']}", "",
         (f"A finished print in the tdmg library: recipe {rid} ({r.name}), class "
         f"{job['class']}. Finished on {today} by `tdmg finish`."), "",
         "## What to print", ""]
    L.append(f"Route **{route}**" + (f", face **{face}**" if face else "") +
             ". Files (in `" + folder + "/`):")
    L.append("")
    for name, (_, data) in printable.items():
        L.append(f"- `{folder}/{name}` (SHA-256 `{_sha(data)}`)")
    L.append("")
    if route == "single":
        L.append("How: " + PRINT_THIS + ". The G-code files are not in the library.")
    elif route == "ams":
        L.append("How: " + PRINT_FACE[(face,)] + ". The G-code files are not in the "
                 "library.")
        if state.chosen.chosen_face:            # tdmg's choice, when the owner's differs
            L += ["", f"Printed face {face}; tdmg chose {state.chosen.chosen_face}."]
    else:
        L.append("How: a glue print needs every plate. For each plate: slice it in Bambu "
                 "Studio to print; tdmg's G-code is for checking only and is not in the "
                 "library. Then glue each color's pieces into the base's pockets.")
    others = [x.name for x in r.routes if x.name != route]
    L += ["", f"Only the {route} route was confirmed by the owner; "
          + (f"the recipe's other routes ({', '.join(others)}) are not in this entry."
             if others else "the recipe has no other route.")]
    # Filaments
    L += ["", "## Filaments", ""]
    if route == "single":
        L.append("One filament, any color: the model is a single body.")
    elif route == "ams":
        palette = _json(printable["palette.json"][1])
        fmap = {f.get("body"): f.get("filament") for f in slice_rec.get("filament_map", [])}
        L += [("From `palette.json` (shell order in `model.3mf`), with the filament numbers "
              "tdmg sliced with:"), "",
              "| Shell | Role | Color | Body | Filament |", "|---|---|---|---|---|"]
        for s in palette["shells"]:
            L.append(f"| {s['shell']} | {s['role']} | `{s['hex']}` | {s['body']} | "
                     f"{fmap.get(s['body'], '?')} |")
    else:
        L += ["| Plate | Color |", "|---|---|"]
        hexes = {b["file"]: b.get("hex") for b in made.get("bodies", [])}
        for name in printable:
            L.append(f"| `{name}` | `{hexes.get(name, '?')}` |")
    # Size
    L += ["", "## Size", ""]
    params = {s: job["stages"][s] for s in r.stages}
    width = (params.get("flat") or params.get("colors") or {}).get("width_mm")
    thick = (params.get("flat") or params.get("colored_flat") or {}).get("thickness_mm")
    L.append(f"Width {width} mm (the subject's width), thickness {thick} mm (job.yaml).")
    if route == "single":
        ext = (made.get("mesh") or {}).get("extents_mm")
        if ext:
            L.append(f"The model's extents: {_mm(ext)} (flat.json).")
    else:
        for b in made.get("bodies", []):
            if b.get("route") == route and (route == "glue" or b.get("role") == "base") \
                    and b.get("extents_mm"):
                L.append(f"`{b['file']}` extents: {_mm(b['extents_mm'])} (colored.json).")
    # Layer settings
    L += ["", "## Layer settings", ""]
    prof = (slice_rec.get("slicer") or {}).get("profiles") or {}
    names = ", ".join(f"{k} \"{v.get('name')}\"" for k, v in sorted(prof.items()))
    L.append(f"tdmg sliced it with the pinned {slice_rec.get('slicer', {}).get('pin')} "
             f"profiles ({names}). Use the same printer, process and filament profiles in "
             "Bambu Studio.")
    for label, section in _route_sections(route, face, slice_rec):
        n = (section.get("stats") or {}).get("layer_count")
        L.append(f"- {label}: {n} layers")
    # Verdict
    L += ["", "## Historical verdict", "",
          (f"At commit `{state.git.commit}`, under the rules then in force (rules SHA-256 "
          f"`{rules_sha256()}`). `tdmg library verify` re-runs it under today's code; it "
          "never rewrites this."), ""]
    for label, section in _route_sections(route, face, slice_rec):
        verdict, cert = section.get("verdict"), section.get("certification") or ""
        why = cert.removeprefix(str(verdict)).lstrip(": ")
        L.append(f"- {label}: **{verdict}**" + (f": {why}" if why else ""))
    note = next((s.get("certification_note") for _, s in
                 _route_sections(route, face, slice_rec) if s.get("certification_note")),
                None)
    if note:
        L += ["", note]
    if entry["accept_not_certified"]:
        L += ["", ("The owner printed (or chose to print) a file tdmg did not certify "
              "(--accept-not-certified).")]
    warnings = _warnings(recs, route, face, slice_rec)
    if warnings:
        L += ["", "Warnings:", ""] + [f"- {w}" for w in warnings]
    # What was not checked
    L += ["", "## What was not checked", ""]
    unknown = sorted({i for _, s in _route_sections(route, face, slice_rec)
                      for i in _unknown_checks(s)})
    if unknown:
        L.append("Checks that could not be measured (UNKNOWN): " + ", ".join(unknown) + ".")
        L.append("")
    used = rules_used(recs)
    open_rules = {k: v for k, v in used.items() if v["validation"] != "calibrated"}
    if open_rules:
        L.append("Rules this print used that have not been calibrated on our printer (each "
                 "with its kind and validation, from rules/):")
        L.append("")
        for rid_, v in open_rules.items():
            L.append(f"- `{rid_}` = {_values(v)} {v['unit']}: {v['kind']}, {v['validation']}")
    L.append("")
    L.append("Strength is not judged, and no dimension has been measured with calipers.")
    # Confirmation
    L += ["", "## The owner's confirmation", "",
          (f"Confirmation {state.chosen.number} ({confirmations.describe(entry)}), given on "
          f"{entry['date']} at job revision {entry['revision']}, in the owner's words:"), ""]
    L += _quote(entry["owner_said"])
    L += ["", (f"All {len(state.current_prints)} current print confirmation(s) are copied "
          "verbatim into provenance.json.")]
    # Public
    L += ["", "## Public", ""]
    if public:
        L.append("The owner said the design may be public: the printable files are in "
                 "`files/`, tracked in git.")
    else:
        L.append("The owner said the design is not public: the printable files are in "
                 "`private/`, which git ignores; they exist only on this disk and its "
                 "copies.")
    # Source
    src = job["source"]
    L += ["", "## Source", "",
          f"- `{src['file']}`, SHA-256 `{src['sha256']}`; origin: {src['origin']}"]
    if src["mask"]:
        L.append(f"- mask `{src['mask']['file']}`, SHA-256 `{src['mask']['sha256']}`")
    for k in jobs.GENERATED_FIELDS:
        if k in src:
            L.append(f"- {k}: {src[k]}")
    L.append("- `source/` is git-ignored: it exists only on this disk and its copies.")
    L += ["", ("See `provenance.json` for the code, environment, rules, profiles, checks and "
          "confirmations, and `purge.json` for the job's files that were deleted."), ""]
    return "\n".join(L)


def _mm(ext) -> str:
    return " x ".join(f"{float(x):.2f}" for x in ext) + " mm"


def _values(v: dict) -> str:
    """The rule's value as the records used it; its rules/ default when the records name
    the rule without its value."""
    if v["values_in_records"]:
        return ", ".join(json.dumps(x, sort_keys=True) for x in v["values_in_records"])
    return f"{json.dumps(v['default'])} (rules/ default)"


def _warnings(recs: dict, route: str, face: str | None, slice_rec: dict) -> list[str]:
    out = []
    sel = recs.get("select", {})
    out += [_text(w) for w in (sel.get("result") or {}).get("warnings", [])]
    stage = "flat" if "flat" in recs else "colored_flat"
    out += [_text(w) for w in recs[stage].get("warnings", [])]
    if route == "ams":
        out += [_text(w) for w in slice_rec["faces"][face].get("warnings", [])]
    return [w for w in out if w]


def _text(w) -> str:
    if isinstance(w, str):
        return w
    if isinstance(w, dict) and isinstance(w.get("text"), str):
        return w["text"]
    return json.dumps(w, sort_keys=True)


# --- step 4: the rebuild and its comparison ---------------------------------------------------

def _gcode_difference(name: str, a: bytes, b: bytes) -> str | None:
    """Why two G-code files differ beyond the timestamp allowance, or None."""
    line_no, pattern = GCODE_TIMESTAMPS[name]
    la, lb = a.split(b"\n"), b.split(b"\n")
    if len(la) != len(lb):
        return f"{len(la)} lines against {len(lb)}"
    diff = [i for i, (x, y) in enumerate(zip(la, lb)) if x != y]
    other = [i for i in diff if i != line_no - 1]
    if other:
        return f"line {other[0] + 1} differs (only line {line_no}, the timestamp, may)"
    if diff:
        for f in (la, lb):
            text = f[line_no - 1].rstrip(b"\r").decode("utf-8", "replace")
            if pattern.fullmatch(text) is None:
                return (f"line {line_no} differs and is not the measured timestamp line "
                        f"({text[:80]!a})")
    return None


def _volatile(path: tuple) -> bool:
    return any(len(path) == len(pat) and all(isinstance(k, str) and m.fullmatch(k)
                                             for k, m in zip(path, pat))
               for pat in _VOLATILE)


_MASK = "<volatile: G-code hash>"


def _masked(obj, path=()):
    """A copy with each volatile field that holds a SHA-256 replaced by _MASK."""
    if isinstance(obj, dict):
        return {k: (_MASK if _volatile((*path, k)) and _hex(v) else _masked(v, (*path, k)))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_masked(v, (*path, i)) for i, v in enumerate(obj)]
    return obj


def json_differences(a, b, path=()) -> list[str]:
    """The JSON paths where two values differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(json_path((*path, k)) + (" missing in the rebuild" if k not in b
                                                    else " only in the rebuild"))
            else:
                out += json_differences(a[k], b[k], (*path, k))
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += json_differences(x, y, (*path, i))
        return out
    if a == b and type(a) is type(b):
        return []
    return [json_path(path)]


def _shown(paths: list[str]) -> str:
    more = f" and {len(paths) - MAX_SHOWN} more" if len(paths) > MAX_SHOWN else ""
    return ", ".join(paths[:MAX_SHOWN]) + more


def _json_or_none(data: bytes):
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None


def compare_file(stage: str, rel: str, a: bytes, b: bytes) -> str | None:
    """Why the job's file (a) and the rebuild's (b) differ beyond the measured allowance
    (module docstring), or None."""
    name = rel.rpartition("/")[2]
    where = f"{stage}/{rel}"
    if a == b:
        return None
    if stage == "slice" and name in GCODE_TIMESTAMPS:
        why = _gcode_difference(name, a, b)
        return None if why is None else f"{where}: {why}"
    ja, jb = _json_or_none(a), _json_or_none(b)
    if stage == "slice" and rel == SLICE_RECORD and isinstance(ja, dict) \
            and isinstance(jb, dict):
        # Byte for byte except the volatile values: both files must be tdmg's own record
        # text, so equal content means equal bytes.
        diff = json_differences(_masked(ja), _masked(jb))
        form = record_text(ja) == a and record_text(jb) == b
        if diff:
            return (f"{where}: fields differ: {_shown(diff)}"
                    + ("" if form else " (and it is not in tdmg's record form)"))
        return None if form else f"{where}: differs and is not in tdmg's record form"
    if ja is not None and jb is not None:
        diff = json_differences(ja, jb)
        if diff:
            return f"{where}: fields differ: {_shown(diff)}"
        return f"{where}: the same JSON content in different bytes"
    return f"{where}: bytes differ"


def compare_jobs(job_dir: Path, rebuilt: Path, stages: tuple[str, ...]) -> list[str]:
    """Every difference between the job's stage folders and the rebuild's (module
    docstring)."""
    out = []
    for stage in stages:
        a_files, _ = _walk(job_dir / stage)
        b_files, _ = _walk(rebuilt / stage)
        for rel in sorted(set(a_files) - set(b_files)):
            out.append(f"{stage}/{rel}: missing in the rebuild")
        for rel in sorted(set(b_files) - set(a_files)):
            out.append(f"{stage}/{rel}: only in the rebuild")
        for rel in sorted(set(a_files) & set(b_files)):
            why = compare_file(stage, rel, (job_dir / stage / rel).read_bytes(),
                               (rebuilt / stage / rel).read_bytes())
            if why:
                out.append(why)
    return out


def rebuild(staging: Path, state: State, machine: Machine, say) -> list[str]:
    """Step 4: run the staged job.yaml and source/ in a scratch folder; the differences."""
    job, entry = state.job, state.chosen.entry
    with tempfile.TemporaryDirectory(prefix="tdmg-rebuild-",
                                     ignore_cleanup_errors=True) as tmp:
        scratch = Path(tmp) / job["name"]
        scratch.mkdir()
        shutil.copy2(staging / JOB_FILE, scratch / JOB_FILE)
        shutil.copytree(staging / SOURCE_DIR, scratch / SOURCE_DIR)
        say(f"4. rebuilding in a scratch folder ({_p(scratch)}) from job.yaml and "
            "source/ only ...")
        try:
            events, status = run_job(scratch, machine)
        except JobError as e:
            return [f"the rebuild was refused: {e}"]
        out = [f"rebuild: stage {ev.stage} failed: {ev.message}" for ev in events
               if ev.action == "failed"]
        out += [f"rebuild: stage {s.stage} is {s.state}" + (f" ({s.note})" if s.note
                                                            else "")
                for s in status.stages if s.state != DONE]
        if out:
            return out
        out = compare_jobs(state.folder, scratch, recipe(job["recipe"]).stages)
        try:
            cover = confirmations.print_cover(scratch, load_job(scratch), entry["route"],
                                              entry["face"])
        except JobError as e:
            return [*out, f"the rebuild's printable files cannot be bound: {e}"]
        if cover.slice_id != entry["slice_id"]:
            out.append(f"the rebuilt slice record's identity {cover.slice_id} is not the "
                       f"confirmed one ({entry['slice_id']})")
        if cover.verdicts != entry["verdicts"]:
            out.append(f"the rebuilt verdicts {cover.verdicts} are not the confirmed ones "
                       f"({entry['verdicts']})")
        if cover.covers != entry["covers"]:
            out.append("the rebuilt printable files are not the confirmed ones")
        return out


# --- COMPLETE, purge.json ----------------------------------------------------------------------

def complete_bytes(entry: Path) -> bytes:
    files, _ = _walk(entry)
    files = [f for f in files if f != COMPLETE_FILE]
    return record_text({"schema": COMPLETE_SCHEMA, "files": _hashes(entry, files)})


def verify_complete(entry: Path) -> list[str]:
    """Why prints/NAME is not a verified finished entry ([] when it is): COMPLETE present
    and in form, the same set of files, and every SHA-256 matching."""
    path = entry / COMPLETE_FILE
    if not path.is_file():
        return [f"{_p(entry)} has no {COMPLETE_FILE}"]
    data = _json_or_none(path.read_bytes())
    if not (isinstance(data, dict) and data.get("schema") == COMPLETE_SCHEMA
            and isinstance(data.get("files"), dict)
            and all(_hex(v) for v in data["files"].values())):
        return [f"{COMPLETE_FILE} is not a {COMPLETE_SCHEMA} file"]
    try:
        files, _ = _walk(entry)
    except LibraryError as e:
        return [str(e)]
    files = [f for f in files if f != COMPLETE_FILE]
    out = [f"{rel}: not listed in {COMPLETE_FILE}" for rel in files if rel not in data["files"]]
    out += [f"{rel}: listed in {COMPLETE_FILE} but missing" for rel in data["files"]
            if rel not in files]
    out += [f"{rel}: its SHA-256 is not the one {COMPLETE_FILE} lists"
            for rel in files if rel in data["files"]
            and _sha((entry / rel).read_bytes()) != data["files"][rel]]
    return out


def job_listing(folder: Path) -> tuple[dict[str, str], list[str]]:
    """({file: SHA-256}, folders) of everything under jobs/NAME except finish's own lock
    file; a link anywhere inside is refused."""
    files, folders = _walk(folder)
    files = [f for f in files if f != LOCK_FILE]
    return _hashes(folder, files), folders


def purge_record(name: str, words: str, day: str, listing: tuple[dict, list]) -> bytes:
    files, folders = listing
    return record_text({"schema": PURGE_SCHEMA, "name": name, "owner_said": words,
                        "date": day,
                        "deleted": f"the job folder {name} (jobs/{name}) and everything in it",
                        "files": files, "folders": folders,
                        "not_listed": [LOCK_FILE + " (finish's own lock)"]})


def _onexc(func, path, exc):
    """shutil.rmtree's error handler: never follow a link; retry a read-only file once
    after making it writable; anything else stops the deletion."""
    p = Path(path)
    if p.is_symlink() or p.is_junction():
        raise LibraryError(f"{_p(p)} is a link; the purge does not follow links") from exc
    if isinstance(exc, PermissionError) and p.exists():
        os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
        func(path)
        return
    raise exc


def delete_job(folder: Path) -> None:
    """Delete exactly the job folder; LibraryError when anything is left."""
    _no_links(folder, "job")
    _walk(folder)                       # refuses a link anywhere inside
    try:
        shutil.rmtree(folder, onexc=_onexc)
    except OSError as e:
        raise LibraryError(f"the purge stopped ({e.strerror or e}: {_p(e.filename or '')}); "
                           "prints/ holds the finished entry; run finish again to finish "
                           "the purge") from None
    if folder.exists() or folder.is_symlink():
        raise LibraryError(f"{_p(folder)} is still there after the purge; run finish again")


# --- finish ---------------------------------------------------------------------------------------

def _today(today: datetime.date | None) -> str:
    return (datetime.date.today() if today is None else today).isoformat()


def finish(name: str, *, public: bool | None, purge_owner_said: str | None,
           confirmation: int | None = None, dry_run: bool = False,
           machine: Machine | None = None, jobs_dir: Path | None = None,
           prints_dir: Path | None = None, repo: Path | None = None,
           say: Callable[[str], None] = print, today: datetime.date | None = None) -> None:
    """tdmg finish (module docstring). Raises LibraryError on a refusal (nothing of the job
    is deleted) and RebuildDiffers when the rebuild does not match."""
    machine = Machine() if machine is None else machine
    try:
        name = check_name(name)
    except JobError as e:
        raise LibraryError(str(e)) from None
    if public is None:
        raise LibraryError("--public yes|no is required: ask the owner whether the design "
                           "may be public (yes: files/, tracked in git; no: private/, "
                           "git-ignored)")
    if purge_owner_said is not None or not dry_run:
        problem = jobs.owner_words_problem(purge_owner_said) if purge_owner_said is not None \
            else "is required: the owner's own words giving permission to delete the job"
        if problem:
            raise LibraryError(f"--purge-owner-said {problem}")
    if confirmation is not None and confirmation < 1:
        raise LibraryError(f"--confirmation {confirmation}: confirmations are numbered "
                           "from 1 (tdmg job status)")
    day = _today(today)
    try:
        jobs_dir = Path(os.path.abspath(jobs.default_jobs_dir() if jobs_dir is None
                                        else jobs_dir))
    except JobError as e:
        raise LibraryError(str(e)) from None
    prints_dir = Path(os.path.abspath(default_prints_dir() if prints_dir is None
                                      else prints_dir))
    repo = code_checkout() if repo is None else Path(repo)
    folder = jobs_dir / name
    staging = prints_dir / f"{STAGING_PREFIX}{name}"
    entry = prints_dir / name
    # Step 1: names and paths.
    _no_links(folder, "job")
    _no_links(prints_dir, "prints folder")
    _no_links(staging, "staging folder")
    _no_links(entry, "library entry")
    rj, rp = folder.resolve(), prints_dir.resolve()
    if _inside(rj, rp) or _inside(rp, rj):
        raise LibraryError(f"the job {_p(folder)} and the prints folder {_p(prints_dir)} "
                           "overlap; they must be separate folders")
    if rj != jobs_dir.resolve() / name:
        raise LibraryError(f"the job must be exactly {_p(jobs_dir / name)}")
    has_job = folder.is_dir()
    has_staging, has_entry = staging.exists(), entry.exists()
    complete = (entry / COMPLETE_FILE).is_file()
    if dry_run and (has_staging or has_entry):
        raise LibraryError("an earlier finish of this job is unfinished (a staging folder or "
                           f"{_p(entry)} exists); run finish without --dry-run to resume it")
    if not has_job:
        if folder.exists():
            raise LibraryError(f"{_p(folder)} is not a folder")
        if has_entry and complete and not has_staging:
            problems = verify_complete(entry)
            if problems:
                raise LibraryError(f"{_p(entry)} does not verify: {'; '.join(problems)}")
            say(f"job {name} is already finished: {_p(entry)} is complete and verifies, and "
                "the job is gone")
            return
        if has_entry or has_staging:
            raise LibraryError(f"there is no job {name} in {_p(jobs_dir)}, but "
                               f"{_p(entry if has_entry else staging)} is not a finished "
                               "entry; nothing was changed: look at it by hand")
        raise LibraryError(f"no job {name} in {_p(jobs_dir)}")
    if not (folder / JOB_FILE).is_file() and not (has_entry and complete):
        raise LibraryError(f"{_p(folder)} has no {JOB_FILE}: not a job")
    if has_staging and has_entry:
        raise LibraryError(f"both {_p(staging)} and {_p(entry)} exist; nothing was changed: "
                           "look at them by hand")
    for path, what in ((staging, "staging folder"), (entry, "library entry")):
        if path.exists() and not path.is_dir():
            raise LibraryError(f"the {what} {_p(path)} is not a folder")
    _walk(folder)                       # a link anywhere inside the job: refused now
    for path in (staging, entry):
        if path.is_dir():
            _walk(path)
    try:
        jobs.check_not_linked(folder)
        lock = job_lock(folder)
        lock.__enter__()
    except JobError as e:
        raise LibraryError(str(e)) from None
    try:
        say(f"1. names and paths: job {_p(folder)}, library entry {_p(entry)}")
        if has_entry and complete:
            _resume_purge(folder, entry, name, say)
        elif has_entry:
            _resume_publish(folder, entry, name, public, purge_owner_said, confirmation,
                            machine, jobs_dir, prints_dir, repo, day, say)
        else:
            if has_staging:
                _remove_staging(staging)
                say(f"   removed {_p(staging)}, left by an interrupted finish; staging again")
            _fresh(folder, staging, entry, prints_dir, name, public, purge_owner_said,
                   confirmation, dry_run, machine, jobs_dir, repo, day, say)
    finally:
        lock.__exit__(None, None, None)


def _remove_staging(staging: Path) -> None:
    _no_links(staging, "staging folder")
    _walk(staging)
    shutil.rmtree(staging, onexc=_onexc)


def _describe(c: ConfirmationStatus) -> str:
    e = c.entry
    return (f"confirmation {c.number}: {confirmations.describe(e)}, {e['date']}, "
            f"{_words(e['owner_said'])}")


def _fresh(folder, staging, entry, prints_dir, name, public, words, number, dry_run,
           machine, jobs_dir, repo, day, say) -> None:
    state = check_state(folder, machine, number, repo, jobs_dir, prints_dir)
    say(f"2. state: every stage done and current; {_describe(state.chosen)}; git tree "
        f"clean at {state.git.commit}")
    made_prints = not prints_dir.exists()
    try:
        files = payload(state, public)
        files[CARD_FILE] = card(state, public, day).encode("utf-8")
        prov = record_text(provenance(state, public, machine, day))
        try:
            write_outputs(staging, files, PROVENANCE_FILE, prov, create_folder=True,
                          subfolders=True)
        except RecordError as e:
            raise LibraryError(str(e)) from None
        say(f"3. staged {_p(staging)}: {len(files) + 1} files")
        differences = rebuild(staging, state, machine, say)
        if differences:
            raise RebuildDiffers(differences)
        say("   the rebuild matches: every file byte for byte, except the G-code "
            "timestamp lines and slice.json's hashes of those G-code files "
            f"({REPEATABILITY})")
    except Exception:
        if staging.exists():
            _remove_staging(staging)
        if made_prints and prints_dir.is_dir() and not any(prints_dir.iterdir()):
            prints_dir.rmdir()
        raise
    folder_name = PUBLIC_DIR if public else PRIVATE_DIR
    if dry_run:
        _remove_staging(staging)
        if made_prints and prints_dir.is_dir() and not any(prints_dir.iterdir()):
            prints_dir.rmdir()
        listing = job_listing(folder)
        say("dry run: nothing was changed; the staging folder is removed. A real run would:")
        say(f"5. public: {'yes' if public else 'no'}: the printable files in {folder_name}/"
            + (" (tracked in git)" if public else " (git-ignored)"))
        say(f"6. publish: rename the staging folder to {_p(entry)}, write {PURGE_FILE}, then "
            f"{COMPLETE_FILE}")
        say(f"7. purge: delete {_p(folder)} ({len(listing[0])} files, {len(listing[1])} "
            "folders), with --purge-owner-said")
        return
    say(f"5. public: {'yes' if public else 'no'}: printable files in {folder_name}/")
    os.rename(staging, entry)
    say(f"6. published {_p(entry)}")
    _purge(folder, entry, name, words, day, say)


def _purge(folder: Path, entry: Path, name: str, words: str, day: str, say,
           *, write_record: bool = True) -> None:
    if write_record:
        listing = job_listing(folder)
        replace_file(entry, PURGE_FILE, purge_record(name, words, day, listing))
        replace_file(entry, COMPLETE_FILE, complete_bytes(entry))
        say(f"   wrote {PURGE_FILE} ({len(listing[0])} files of the job listed) and "
            f"{COMPLETE_FILE}")
    problems = verify_complete(entry)
    if problems:
        raise LibraryError(f"{_p(entry)} does not verify ({'; '.join(problems)}); the job "
                           "is not deleted")
    delete_job(folder)
    say(f"7. purged {_p(folder)}: the owner said {_words(_purge_words(entry))}")


def _purge_words(entry: Path) -> str:
    return _json((entry / PURGE_FILE).read_bytes())["owner_said"]


def _same_job(folder: Path, entry: Path) -> None:
    mine, theirs = folder / JOB_FILE, entry / JOB_FILE
    if mine.is_file() and theirs.is_file() and mine.read_bytes() == theirs.read_bytes():
        return
    if not mine.is_file() and theirs.is_file():
        return                          # a purge stopped part way; purge.json decides
    raise LibraryError(f"{_p(entry)} already exists and is not this job's print (its "
                       f"{JOB_FILE} differs); choose another job name, or look at it by "
                       "hand. Nothing was changed")


def _resume_publish(folder, entry, name, public, words, number, machine, jobs_dir,
                    prints_dir, repo, day, say) -> None:
    """prints/NAME without COMPLETE (module docstring, Resume)."""
    _same_job(folder, entry)
    state = check_state(folder, machine, number, repo, jobs_dir, prints_dir)
    say(f"2. state: every stage done and current; {_describe(state.chosen)}; git tree "
        f"clean at {state.git.commit}")
    prov = _json_or_none((entry / PROVENANCE_FILE).read_bytes()) \
        if (entry / PROVENANCE_FILE).is_file() else None
    if not (isinstance(prov, dict) and prov.get("schema") == PROVENANCE_SCHEMA
            and prov.get("name") == name):
        raise LibraryError(f"{_p(entry)} has no {PROVENANCE_SCHEMA} {PROVENANCE_FILE} for job "
                           f"{name}; nothing was changed: look at it by hand")
    if prov.get("public") != public:
        raise LibraryError(f"{_p(entry)} was published with --public "
                           f"{'yes' if prov.get('public') else 'no'}; run finish again with "
                           "that answer (a publish is never redone)")
    if prov.get("confirmation") != {"number": state.chosen.number,
                                    "entry": state.chosen.entry}:
        raise LibraryError(f"{_p(entry)} was published for confirmation "
                           f"{(prov.get('confirmation') or {}).get('number')}, not "
                           f"{state.chosen.number}; give --confirmation for it")
    hashes = {s: _sha(b) for s, b in state.records.items()}
    if {s: v.get("record_sha256") for s, v in (prov.get("stages") or {}).items()} != hashes:
        raise LibraryError("the job's stage records changed since the publish; nothing was "
                           "changed: look at it by hand")
    expected = payload(state, public)
    for leftover in [p for p in entry.iterdir() if LEFTOVER_TMP.fullmatch(p.name)]:
        leftover.unlink()
        say(f"   removed {leftover.name}, left by an interrupted write")
    files, _ = _walk(entry)
    allowed = set(expected) | {CARD_FILE, PROVENANCE_FILE, PURGE_FILE}
    extra = [f for f in files if f not in allowed]
    missing = [f for f in [*expected, CARD_FILE, PROVENANCE_FILE] if f not in files]
    differ = [f for f in expected if f in files and (entry / f).read_bytes() != expected[f]]
    if extra or missing or differ:
        raise LibraryError(f"{_p(entry)} is not what finish published (extra: {extra}, "
                           f"missing: {missing}, different: {differ}); nothing was changed")
    say(f"6. {_p(entry)} was published by an earlier run (not redone); it matches the job")
    _purge(folder, entry, name, words, day, say)


def _resume_purge(folder: Path, entry: Path, name: str, say) -> None:
    """COMPLETE with the job still present (module docstring, Resume)."""
    _same_job(folder, entry)
    problems = verify_complete(entry)
    if problems:
        raise LibraryError(f"{_p(entry)} has {COMPLETE_FILE} but does not verify "
                           f"({'; '.join(problems)}); the job is not deleted")
    record = _json_or_none((entry / PURGE_FILE).read_bytes()) \
        if (entry / PURGE_FILE).is_file() else None
    if not (isinstance(record, dict) and record.get("schema") == PURGE_SCHEMA
            and record.get("name") == name and isinstance(record.get("files"), dict)):
        raise LibraryError(f"{_p(entry)} has no {PURGE_SCHEMA} {PURGE_FILE} for job {name}; "
                           "the job is not deleted")
    left, _ = job_listing(folder)
    strange = [rel for rel, digest in left.items() if record["files"].get(rel) != digest]
    if strange:
        raise LibraryError(f"{_p(folder)} holds files that {PURGE_FILE} does not list with "
                           f"these hashes ({', '.join(strange[:5])}); the job is not deleted")
    say(f"6. {_p(entry)} is complete and verifies; finishing the interrupted purge")
    _purge(folder, entry, name, record["owner_said"], record["date"], say,
           write_record=False)


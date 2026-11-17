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
    STAGED           the SHA-256 of every staged file, written after the rebuild passed and
                     before the publish (tracked)
    purge.json       the purge record: the owner's words, the date and every file and
                     folder of jobs/NAME, files with their SHA-256 (tracked)
    COMPLETE         the SHA-256 of every other file of the entry, written last (tracked)

A folder without COMPLETE is not a finished entry.

**Where the purge record goes, and why COMPLETE comes last.** The purge record is its own
file, purge.json, written after the publish and before COMPLETE; COMPLETE then lists it
with every other file, and only then is jobs/NAME deleted. So COMPLETE is last and correct,
and provenance.json stays byte for byte the file that was staged and checked before the
publish: writing the purge record into provenance.json after COMPLETE would make COMPLETE's
hash of it wrong, and writing COMPLETE again would break "written last". purge.json says
what will be deleted (it is written before the deletion); finish checks afterwards that the
folder is gone. COMPLETE certifies only itself, so before deleting anything finish also
checks the entry against purge.json (entry_problems).

**The steps** (finish):
1. Names and paths: NAME is a job name (tdmg.jobs.check_name); the job is exactly
   JOBS_DIR/NAME, a folder with job.yaml; no component of the job folder, PRINTS_DIR, the
   staging folder PRINTS_DIR/.staging-NAME or the entry PRINTS_DIR/NAME is a symlink or a
   junction; the job and the library folders are disjoint after resolving; PRINTS_DIR/NAME
   is absent (unless resuming). No folder inside the job may be a link or unreadable
   (_walk). The job's lock (_Lock: the same .lock file as tdmg.job_runner.job_lock) is
   taken before the entry's state is read and held for the whole finish; it moves with
   the job folder to its tombstone.
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
6. Publish: STAGED is written into the staging folder, which is renamed to
   PRINTS_DIR/NAME; then purge.json; then COMPLETE.
7. Purge: needs the owner's words (--purge-owner-said, verbatim, not blank; dated with
   today's local date, as confirmations are). Every file and folder under jobs/NAME is
   listed (files with their SHA-256) into purge.json, with the jobs folder; COMPLETE is
   written. Before anything is deleted: COMPLETE verifies (every hash) and the entry is
   this job's (entry_problems: provenance.json, the printable files, each stage record's
   hash, job.yaml and source against purge.json). Then purge_job renames jobs/NAME to its
   tombstone JOBS_DIR/.purging-NAME (on Windows this fails at once when a program holds a
   file in it open), checks that the tombstone holds exactly what purge.json lists (a
   file added after the listing: it is renamed back and finish refuses), and deletes it
   (shutil.rmtree, refusing to follow links), checking it is gone. Files the library does
   not keep and that are not stage outputs, job.yaml, state.json or source/ (not_kept) are
   named first.

**Dry run** (dry_run): steps 1 to 4, including the rebuild; then it says what 5 to 7 would
do (naming the not_kept files) and removes the staging folder (and PRINTS_DIR, if it made
it). Nothing else changes. The purge words are not needed. It is refused while an earlier
finish is unfinished.

**Resume.** Running finish again after an interruption looks at what is on disk:
- a staging folder (and no entry): the earlier run stopped before the publish. The
  staging folder holds only copies of the job's files and what finish wrote, so it is
  removed and steps 3 and 4 run again;
- PRINTS_DIR/NAME without COMPLETE: the publish happened (the rename comes only after
  the rebuild passed). It is never redone. Steps 1 and 2 run again; every file of the
  entry must be the one STAGED lists (staged_problems: so an edited card or provenance is
  refused); provenance.json must name the same confirmation, the same public answer and
  the same stage-record hashes as the job has now, and its job.yaml, source and printable
  files must equal the job's byte for byte. Then purge.json (replaced if an earlier run
  wrote one: the words of the run that deletes are recorded), COMPLETE and the purge;
- PRINTS_DIR/NAME with COMPLETE while jobs/NAME still exists: the run stopped after
  COMPLETE and before the rename to the tombstone, so jobs/NAME must hold exactly what
  purge.json lists (a job made again under the same name does not); the entry is checked
  as in step 7, then the purge runs. purge.json is kept as it is (COMPLETE covers it), and
  finish says so when this run's --public or purge words differ;
- the tombstone JOBS_DIR/.purging-NAME with a finished entry: the deletion stopped part
  way. The entry is checked as in step 7, every file left must be in purge.json with the
  same SHA-256, and the rest is deleted;
- COMPLETE and neither jobs/NAME nor a tombstone: already finished; COMPLETE is verified
  and reported.
Anything else (a staging folder beside an entry, an entry or staging folder whose job is
gone, an entry of another job, a job beside its tombstone) is refused with nothing
changed. Nothing of the job is deleted unless PRINTS_DIR/NAME has COMPLETE, every hash in
it matches, and the entry is this job's.

**Known limit.** A file written into JOBS_DIR/.purging-NAME after purge_job's re-walk
and before the deletion is deleted without being listed. Nothing else knows that path (no
job has the name while the tombstone exists, and tdmg job new refuses the name), so only a
program that already had the folder open, or that is given the tombstone's path, could do
it.

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
- every other file byte for byte, and the same set of files in every stage folder;
- each masked G-code hash, in the job's slice.json and the rebuild's, must be the SHA-256
  of the G-code file it names in the same folder (gcode_binding_problems).
state.json and .lock are not compared: state.json holds slice.json's SHA-256 (the plan's
note to Task 9), and .lock is the lock.

**tdmg library check [NAME]** (check_library, check_entry; plan Task 10). Every folder of
PRINTS_DIR (or NAME and its staging folder) is one of:
- ok: COMPLETE in form; every file it lists present with that SHA-256, none missing, no
  unlisted file and no folder that holds no listed file; STAGED lists the same files
  (but STAGED and purge.json) with the same SHA-256s, so a COMPLETE written again over an
  edited file is caught; entry_problems against purge.json; job.yaml's source hashes are
  COMPLETE's and provenance.json's source is job.yaml's. A LOCAL_ONLY folder (source/,
  private/: git-ignored) missing entirely is "unavailable", not damage: a clone has
  neither. A file missing from one that is present is damage (a partial copy);
- incomplete: no COMPLETE, a leftover .staging-NAME, or a verified entry whose job (or its
  tombstone) is still in the jobs folder (library_jobs_dir, or --jobs-dir): what an
  interrupted finish leaves; the remedy is to run tdmg finish NAME again;
- damaged: anything else wrong, including a folder whose name is not a job name, and a
  file or folder that cannot be read (check goes on with the other entries). A file an
  operating system adds (OS_FILES: .DS_Store, Thumbs.db, desktop.ini; AppleDouble ._*
  files) is damage too, strictly, but the message says what it is and that deleting it is
  safe. Plain files beside the entries are not looked at. Each folder is reported by its
  name on disk, so prints/Roadie is "Roadie" even when asked for roadie on a
  case-insensitive file system; messages of the helpers finish shares say check's words.
Exit codes (tdmg.cli): 0 when every entry is ok; 1 when one is incomplete or damaged; 2
when it cannot check. "Source unavailable" alone exits 0: it is the normal state of every
clone (git does not carry source/ or private/), so making it a failure would make check
fail on every machine but one and teach people to ignore exit 1. It is printed as a note
on each entry and counted in the summary, and verify refuses without the source.
--require-private makes it exit 1, for checking a copy of prints/ that should hold them.
The threat model is finish's: check catches damage and accidental or tool edits, not an
adversary; an edit with STAGED, COMPLETE (and the records they bind) all written again to
agree passes check, and only git's history of the tracked files, or verify's run against
provenance.json, would show it.

**tdmg library verify NAME** (verify, compare_with_provenance; plan Task 10). The entry
must check ok and have its source. Its job.yaml and source/ are copied into a scratch
folder made in tempfile's folder (refused when that is inside the library or the jobs
folder) and run with run_job and the given Machine; nothing is written into the library.
Compared with provenance.json (which holds stage-record hashes and extracted checks and
verdicts, not the records), over the historical and the current stages: each stage done;
each stage record's SHA-256, but slice.json's, for which provenance.json holds
slice_digests (written by finish): the SHA-256 of slice.json with the VOLATILE_FIELDS
masked, and of each G-code file with its timestamp line blanked (the rebuild's
allowance), each masked hash bound to its file (gcode_binding_problems); each record's
algorithm, verdicts (verdicts_in) and checks (check_results: status, rule, threshold, by
path and id); from the confirmation, the slice identity, the confirmed printable files'
SHA-256s (byte for byte; so private/ need not be on this machine) and their verdicts. Not
compared, and said so (NOT_COMPARED): the stages' other files, the allowed timestamp lines
and G-code hash fields, and the checks' measured values. uv.lock is hashed as git's blob
at HEAD (uv_lock_sha256, in finish too), so line ends do not count. what_changed lists
the causes outside the outputs: code commit
(and uncommitted changes), tdmg version, uv.lock, Python, platform, key libraries,
rules_sha256 and each used rule's default, unit and range, algorithm ids and profiles.
Whether PrusaSlicer was configured is read from provenance.json (the slice profiles hold
its pin exactly when it was: prusaslicer_then) and said, with a note when this run
differs. Before the run, the pinned slicers are looked up as the slice stage does
(_check_slicers); one that cannot be used on this machine is the environment, not the
code: CannotVerify, exit 2, as are a missing entry, one that does not check, and a missing
source. A stage that then fails (run_job's failed event) is a difference, exit 1, like
any other; none exit 0. Its words come from the exception class the event carries
(RunEvent.error): an OSError or a SlicerError (a crash, a timeout, a changed install;
MACHINE_ERRORS) is "failed (possibly the environment)", any other "refused by the current
code" (its input is no longer accepted). The current slice.json must also be in tdmg's
record form, as in the rebuild, so the same content in other bytes is a difference.
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

import tdmg.slicing
from tdmg import __version__, confirmations, jobs, paths
from tdmg.color_slicing import PRINT_FACE
from tdmg.job_runner import (
    DONE,
    LOCK_FILE,
    STAGE_RECORDS,
    STATE_FILE,
    ConfirmationStatus,
    Machine,
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
from tdmg.slicer import SlicerError
from tdmg.slicing import FAILED_GCODE_NAME, GCODE_NAME, PRINT_THIS

CARD_FILE = "card.md"
PROVENANCE_FILE = "provenance.json"
PURGE_FILE = "purge.json"
COMPLETE_FILE = "COMPLETE"
STAGED_FILE = "STAGED"
PUBLIC_DIR = "files"             # tracked: the owner said the design may be public
PRIVATE_DIR = "private"          # git-ignored (.gitignore prints/*/private/)
STAGING_PREFIX = ".staging-"     # git-ignored (.gitignore prints/.staging-*/)
PROVENANCE_SCHEMA = "tdmg.provenance/1"
PURGE_SCHEMA = "tdmg.purge/1"
COMPLETE_SCHEMA = "tdmg.complete/1"
STAGED_SCHEMA = "tdmg.staged/1"
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
# Tracked files allowed inside a --jobs-dir or --prints-dir that is inside the checkout.
TREE_SKIP = ("jobs/", "prints/")
MAX_SHOWN = 12                   # differing JSON paths shown per file


class LibraryError(ValueError):
    """finish refuses, or cannot go on; what it changed is said in the message. Before
    step 7's deletion nothing of the job is deleted; a deletion that stops part way leaves
    the rest in the job's tombstone, and the next run finishes it."""


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


# Windows' classic path limits for programs without long-path support: MAX_PATH, 260
# characters with the final NUL, and 248 for a folder (MAX_PATH less room for an 8.3 file
# name). A folder path of 248 or more cannot be read into (measured 2026-11-17 on the PC:
# os.walk failed on a 256-character folder with "The system cannot find the path
# specified"; tests/test_finish.py::test_a_path_too_long_stops_the_listing).
WINDOWS_FOLDER_LIMIT = 248


def _unreadable(path, e: OSError) -> LibraryError:
    """A LibraryError for a file or folder finish cannot read, saying so plainly."""
    where = str(e.filename or path)
    text = f"cannot read {_p(where)} ({e.strerror or e})" + _long_hint(where)
    return LibraryError(text + "; finish stops, and nothing of the job is deleted")


def _long_hint(where) -> str:
    """The Windows path-limit hint, when the path is at or over the folder limit."""
    where = str(where)
    if os.name == "nt" and len(where) >= WINDOWS_FOLDER_LIMIT:
        return (f"; the path is {len(where)} characters long, at or over Windows' "
                f"{WINDOWS_FOLDER_LIMIT}-character limit for a folder (260 for a file) in "
                "programs without long-path support; move the job to a shorter path")
    return ""


def _walk(root: Path) -> tuple[list[str], list[str]]:
    """(files, folders) under root, as sorted POSIX paths relative to it, without following
    links; LibraryError on a link, anything that is not a plain file or folder, and any
    folder that cannot be read (os.walk would otherwise skip it silently)."""
    files, folders = [], []

    def stop(e: OSError):
        raise _unreadable(root, e)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=stop):
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
                raise LibraryError(f"{_p(path)} is not a plain file or folder (or cannot be "
                                   f"read){_long_hint(path)}; finish stops, and nothing of "
                                   "the job is deleted")
    return sorted(files), sorted(folders)


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as e:
        raise _unreadable(path, e) from None


def _hashes(root: Path, files: list[str]) -> dict[str, str]:
    return {rel: _sha(_read(root / rel)) for rel in files}


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
    skip = []
    for folder in (jobs_dir, prints_dir):
        try:
            rel = Path(folder).resolve().relative_to(top.resolve()).as_posix()
        except ValueError:
            continue                    # outside the checkout: git does not list it
        # A jobs or prints folder that holds tracked code would hide changes to it.
        tracked = [t for t in _git(top, "ls-files", "-z", "--", rel or ".").decode(
            "utf-8", "replace").split("\0") if t and not t.startswith(TREE_SKIP)]
        if tracked or rel in ("", "."):
            raise LibraryError(f"the folder {_p(folder)} holds files git tracks (for example "
                               f"{_p((tracked or ['the whole checkout'])[0])}); give --jobs-dir "
                               "and --prints-dir folders that hold no tracked files except "
                               "under jobs/ and prints/")
        skip.append(rel)
    out = _git(top, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = out.split(b"\0")
    dirty, i = [], 0
    while i < len(entries):
        entry = entries[i].decode("utf-8", "replace")
        i += 1
        if not entry:
            continue
        code, paths_ = entry[:2], [entry[3:]]
        if "R" in code or "C" in code:  # a rename or copy (staged or not): the source follows
            paths_.append(entries[i].decode("utf-8", "replace") if i < len(entries) else "")
            i += 1
        # Every path the entry names must be inside a skipped folder.
        if all(any(p == s or p.startswith(s + "/") for s in skip) for p in paths_):
            continue
        dirty += [p for p in paths_ if p]
    if dirty:
        shown = ", ".join(_p(d) for d in dirty[:5]) + (" ..." if len(dirty) > 5 else "")
        raise LibraryError(f"the git tree is not clean ({len(dirty)} change(s) outside the "
                           f"jobs and prints folders: {shown}); commit or remove them first, "
                           "so the commit pins the code that made the print")
    commit = _git(top, "rev-parse", "HEAD").decode("ascii").strip()
    lock = top / "uv.lock"
    if not lock.is_file():
        raise LibraryError(f"{_p(top)} has no uv.lock; the library records its SHA-256")
    return Git(commit, uv_lock_sha256(top))


def uv_lock_sha256(top: Path) -> str:
    """The SHA-256 of uv.lock as git holds it at HEAD (git cat-file blob: no line-end
    conversion), so the same commit gives the same hash on Windows and macOS."""
    return _sha(_git(top, "cat-file", "blob", "HEAD:uv.lock"))


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
        if s == "slice":
            stages[s].update(slice_digests(state.folder / s, state.records[s]))
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
    """The owner's words, verbatim, as an indented code block: Markdown shows it as it is,
    with nothing in it read as formatting."""
    return [f"    {line}" for line in text.split("\n")]


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
             f"profiles ({names}). Whether Bambu Studio's own profiles of these names hold "
             "the same settings has not been checked.")
    settings = (slice_rec.get("portability") or {}).get("settings") or {}
    heights = [(label, settings[flag]["value"]) for label, flag in
               (("layer height", "--layer-height"),
                ("first layer height", "--first-layer-height"))
               if isinstance(settings.get(flag), dict) and "value" in settings[flag]]
    if heights:
        L.append("From the pinned process profile: " + ", ".join(
            f"{label} {value} mm" for label, value in heights) + ".")
    for label, section in _route_sections(route, face, slice_rec):
        n = (section.get("stats") or {}).get("layer_count")
        L.append(f"- {label}: {n} layers")
    # Verdict
    L += ["", "## Historical verdict", "",
          (f"At commit `{state.git.commit}`, under the rules then in force (rules SHA-256 "
          f"`{rules_sha256()}`). `tdmg library verify {job['name']}` re-runs it under the "
          "current code and rules and reports the differences; it never rewrites this."), ""]
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
    L.append("Strength is not judged, and tdmg has measured no printed dimension.")
    # Confirmation
    L += ["", "## The owner's confirmation", "",
          (f"Confirmation {state.chosen.number} ({confirmations.describe(entry)}), given on "
          f"{entry['date']} at job revision {entry['revision']}, in the owner's words "
          "(verbatim):"), ""]
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


def _volatile_values(obj, path=()):
    """(key path, value, the dict holding it) of every volatile field holding a SHA-256."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _volatile((*path, k)) and _hex(v):
                yield (*path, k), v, obj
            else:
                yield from _volatile_values(v, (*path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _volatile_values(v, (*path, i))


def gcode_binding_problems(slice_dir: Path, record: dict, where: str) -> list[str]:
    """Each masked G-code hash must be the SHA-256 of that G-code file in the same slice
    folder (outputs: its key; a gcode section: its "file"), so a masked field cannot hide
    a hash that names some other bytes."""
    out = []
    for path, value, holder in _volatile_values(record):
        rel = path[1] if path[0] == "outputs" else holder.get("file")
        if not isinstance(rel, str) or jobs.path_problem(rel):
            out.append(f"{where}: {json_path(path)} names no G-code file")
            continue
        file = slice_dir / rel
        if not file.is_file() or _sha(_read(file)) != value:
            out.append(f"{where}: {json_path(path)} is not the SHA-256 of {rel}")
    return out


def compare_jobs(job_dir: Path, rebuilt: Path, stages: tuple[str, ...]) -> list[str]:
    """Every difference between the job's stage folders and the rebuild's (module
    docstring), and each masked G-code hash of either slice record bound to its file."""
    out = []
    for stage in stages:
        if stage == "slice":
            for root, who in ((job_dir, "the job's"), (rebuilt, "the rebuild's")):
                rec = _json_or_none(_read(root / stage / SLICE_RECORD))
                if isinstance(rec, dict):
                    out += gcode_binding_problems(root / stage, rec,
                                                  f"{who} {stage}/{SLICE_RECORD}")
        a_files, _ = _walk(job_dir / stage)
        b_files, _ = _walk(rebuilt / stage)
        for rel in sorted(set(a_files) - set(b_files)):
            out.append(f"{stage}/{rel}: missing in the rebuild")
        for rel in sorted(set(b_files) - set(a_files)):
            out.append(f"{stage}/{rel}: only in the rebuild")
        for rel in sorted(set(a_files) & set(b_files)):
            why = compare_file(stage, rel, _read(job_dir / stage / rel),
                               _read(rebuilt / stage / rel))
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


# --- COMPLETE, STAGED, purge.json --------------------------------------------------------------

def _manifest(root: Path, schema: str, leave_out: tuple[str, ...]) -> bytes:
    files, _ = _walk(root)
    return record_text({"schema": schema, "files": _hashes(
        root, [f for f in files if f not in leave_out])})


def complete_bytes(entry: Path) -> bytes:
    """COMPLETE: the SHA-256 of every other file of the entry."""
    return _manifest(entry, COMPLETE_SCHEMA, (COMPLETE_FILE,))


def staged_bytes(staging: Path) -> bytes:
    """STAGED: the SHA-256 of every staged file, written once the rebuild has passed and
    before the publish, so a resume can tell the published files are the checked ones."""
    return _manifest(staging, STAGED_SCHEMA, (STAGED_FILE,))


def _manifest_files(path: Path, schema: str) -> dict | None:
    data = _json_or_none(_read(path)) if path.is_file() else None
    if not (isinstance(data, dict) and data.get("schema") == schema
            and isinstance(data.get("files"), dict)
            and all(isinstance(k, str) and _hex(v) for k, v in data["files"].items())):
        return None
    return data["files"]


def verify_complete(entry: Path) -> list[str]:
    """Why prints/NAME is not a verified finished entry ([] when it is): COMPLETE present
    and in form, the same set of files, and every SHA-256 matching."""
    listed = _manifest_files(entry / COMPLETE_FILE, COMPLETE_SCHEMA)
    if listed is None:
        return [f"{_p(entry)} has no {COMPLETE_SCHEMA} {COMPLETE_FILE}"]
    try:
        files, _ = _walk(entry)
        files = [f for f in files if f != COMPLETE_FILE]
        out = [f"{_p(rel)}: not listed in {COMPLETE_FILE}" for rel in files
               if rel not in listed]
        out += [f"{_p(rel)}: listed in {COMPLETE_FILE} but missing" for rel in listed
                if rel not in files]
        out += [f"{_p(rel)}: its SHA-256 is not the one {COMPLETE_FILE} lists"
                for rel in files if rel in listed and _sha(_read(entry / rel)) != listed[rel]]
    except LibraryError as e:
        return [str(e)]
    return out


def staged_problems(entry: Path) -> list[str]:
    """Why the published files are not the staged, checked ones ([] when they are):
    STAGED lists every file but STAGED, purge.json and COMPLETE, with its SHA-256."""
    listed = _manifest_files(entry / STAGED_FILE, STAGED_SCHEMA)
    if listed is None:
        return [f"{_p(entry)} has no {STAGED_SCHEMA} {STAGED_FILE}"]
    files, _ = _walk(entry)
    files = [f for f in files if f not in (STAGED_FILE, PURGE_FILE, COMPLETE_FILE)]
    out = [f"{_p(rel)}: not staged" for rel in files if rel not in listed]
    out += [f"{_p(rel)}: staged but missing" for rel in listed if rel not in files]
    out += [f"{_p(rel)}: changed since it was staged" for rel in files
            if rel in listed and _sha(_read(entry / rel)) != listed[rel]]
    return out


def job_listing(folder: Path) -> tuple[dict[str, str], list[str]]:
    """({file: SHA-256}, folders) of everything under the job folder except finish's own
    lock file; a link or an unreadable folder anywhere inside is refused."""
    files, folders = _walk(folder)
    files = [f for f in files if f != LOCK_FILE]
    return _hashes(folder, files), folders


def not_kept(files, stages: tuple[str, ...]) -> list[str]:
    """The job's files that the library does not keep and that are not stage outputs,
    job.yaml, state.json or source/ (notes left in the job folder, say): named before the
    purge deletes them."""
    keep_dirs = (*stages, SOURCE_DIR)
    return sorted(f for f in files if f not in (JOB_FILE, STATE_FILE)
                  and f.split("/")[0] not in keep_dirs)


def jobs_folder_text(jobs_dir: Path, repo: Path | None) -> str:
    """The jobs folder as purge.json records it: relative to the checkout when inside it."""
    if repo is not None:
        try:
            return jobs_dir.resolve().relative_to(Path(repo).resolve()).as_posix()
        except ValueError:
            pass
    return str(jobs_dir)


def purge_record(name: str, words: str, day: str, listing: tuple[dict, list],
                 jobs_text: str = "jobs") -> bytes:
    files, folders = listing
    return record_text({"schema": PURGE_SCHEMA, "name": name, "owner_said": words,
                        "date": day, "jobs_folder": jobs_text,
                        "deleted": f"the job folder {name} in {jobs_text} and everything in it",
                        "files": files, "folders": folders,
                        "not_listed": [LOCK_FILE + " (finish's own lock)"]})


def _purge_record(entry: Path, name: str) -> dict | None:
    record = _json_or_none(_read(entry / PURGE_FILE)) if (entry / PURGE_FILE).is_file() \
        else None
    if not (isinstance(record, dict) and record.get("schema") == PURGE_SCHEMA
            and record.get("name") == name and isinstance(record.get("files"), dict)
            and isinstance(record.get("folders"), list)
            and isinstance(record.get("owner_said"), str)):
        return None
    return record


def entry_problems(entry: Path, name: str, record: dict) -> list[str]:
    """Why prints/NAME is not this job's finished entry, judged against purge.json's list
    of the job's files ([] when it is). COMPLETE alone certifies only itself, so: a
    provenance.json of this job; COMPLETE listing card.md, job.yaml, provenance.json,
    purge.json, STAGED and the source files; every printable file of provenance.json
    present with its SHA-256 and equal to the confirmed job file; each stage record's hash
    in provenance.json equal to purge.json's hash of the job's record; the entry's job.yaml
    and source files equal to purge.json's hashes of the job's own copies."""
    listed = _manifest_files(entry / COMPLETE_FILE, COMPLETE_SCHEMA) or {}
    prov = _json_or_none(_read(entry / PROVENANCE_FILE)) \
        if (entry / PROVENANCE_FILE).is_file() else None
    if not (isinstance(prov, dict) and prov.get("schema") == PROVENANCE_SCHEMA
            and prov.get("name") == name):
        return [f"{_p(entry)} has no {PROVENANCE_SCHEMA} {PROVENANCE_FILE} for job {name}"]
    try:
        job = parse_job(_read(entry / JOB_FILE)) if (entry / JOB_FILE).is_file() else None
    except JobError as e:
        return [f"{JOB_FILE} in {_p(entry)}: {e}"]
    if job is None or job["name"] != name:
        return [f"{_p(entry)} has no {JOB_FILE} of job {name}"]
    jobfiles = record["files"]
    sources = [job["source"]["file"]] + ([job["source"]["mask"]["file"]]
                                         if job["source"]["mask"] else [])
    out = [f"{COMPLETE_FILE} does not list {_p(rel)}" for rel in
           (CARD_FILE, JOB_FILE, PROVENANCE_FILE, PURGE_FILE, STAGED_FILE, *sources)
           if rel not in listed]
    for rel in (JOB_FILE, *sources):
        if rel in listed and jobfiles.get(rel) != listed[rel]:
            out.append(f"{_p(rel)} in the entry is not the job's ({PURGE_FILE})")
    printable = prov.get("printable_files")
    folder = prov.get("printable_folder")
    covers = ((prov.get("confirmation") or {}).get("entry") or {}).get("covers")
    if not (isinstance(printable, dict) and printable and isinstance(covers, dict)
            and folder in (PUBLIC_DIR, PRIVATE_DIR)):
        out.append(f"{PROVENANCE_FILE} names no printable files or confirmation")
    else:
        for rel, digest in printable.items():
            if listed.get(rel) != digest:
                out.append(f"printable file {_p(rel)} is missing or not the one "
                           f"{PROVENANCE_FILE} names")
        for rel, digest in covers.items():
            mine = f"{folder}/{rel.partition('/')[2]}"
            if printable.get(mine) != digest or jobfiles.get(rel) != digest:
                out.append(f"the confirmed file {_p(rel)} is not {_p(mine)} in the entry")
    stages = prov.get("stages")
    want = recipe(job["recipe"]).stages
    if not (isinstance(stages, dict) and sorted(stages) == sorted(want)):
        out.append(f"{PROVENANCE_FILE} does not name the stages {', '.join(want)}")
    else:
        for s in want:
            v = stages[s] if isinstance(stages[s], dict) else {}
            rel = f"{s}/{STAGE_RECORDS[s]}"
            if v.get("record") != rel or v.get("record_sha256") != jobfiles.get(rel):
                out.append(f"{PROVENANCE_FILE}'s hash of {rel} is not the job's "
                           f"({PURGE_FILE})")
    return out


# --- the lock, the tombstone, the deletion ------------------------------------------------------

class _Lock:
    """The job's lock: the same file as tdmg.job_runner.job_lock (an exclusive create of
    .lock in the job folder), held by finish from step 1 to the end. When the purge renames
    the job folder to its tombstone the lock moves with it (moved): no job of that name
    exists any more, and tdmg job new refuses a name whose tombstone exists. release()
    removes the lock where it now is; after the deletion it is gone already."""

    def __init__(self, folder: Path):
        self.path = folder / LOCK_FILE

    def acquire(self) -> None:
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                         | getattr(os, "O_BINARY", 0))
        except FileExistsError:
            raise LibraryError(
                f"job {self.path.parent.name} is locked: {_p(self.path)} exists. Another "
                "tdmg command is using the job, or one stopped without removing the file; "
                f"if none is running, delete {_p(self.path)}") from None
        except OSError as e:
            raise _unreadable(self.path, e) from None
        try:
            os.write(fd, f"pid {os.getpid()}\n".encode("ascii"))
        finally:
            os.close(fd)

    def moved(self, folder: Path) -> None:
        self.path = folder / LOCK_FILE

    def release(self) -> None:
        self.path.unlink(missing_ok=True)


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
    """Delete exactly this folder (the tombstone), refusing links; LibraryError when
    anything is left. What is left stays in the tombstone for the next run."""
    _no_links(folder, "job")
    _walk(folder)                       # refuses a link or an unreadable folder inside
    try:
        shutil.rmtree(folder, onexc=_onexc)
    except OSError as e:
        raise LibraryError(f"the purge stopped part way ({e.strerror or e}: "
                           f"{_p(e.filename or '')}); prints/ holds the finished entry and "
                           f"{_p(folder)} what is left of the job; run finish again to "
                           "finish the purge") from None
    if folder.exists() or folder.is_symlink():
        raise LibraryError(f"{_p(folder)} is still there after the purge; run finish again")


def tombstone_problems(root: Path, record: dict, *, exact: bool) -> list[str]:
    """What under the job folder or its tombstone purge.json does not list with the same
    SHA-256 (the lock aside); with exact, also what it lists that is missing."""
    files, folders = job_listing(root)
    listed, listed_dirs = record["files"], set(record["folders"])
    out = [f"{_p(rel)}: not in {PURGE_FILE}" for rel in files if rel not in listed]
    out += [f"{_p(rel)}: changed since {PURGE_FILE} listed it" for rel, d in files.items()
            if rel in listed and listed[rel] != d]
    out += [f"{_p(rel)}/: a folder not in {PURGE_FILE}" for rel in folders
            if rel not in listed_dirs]
    if exact:
        out += [f"{_p(rel)}: listed in {PURGE_FILE} but missing" for rel in listed
                if rel not in files]
        out += [f"{_p(rel)}/: listed in {PURGE_FILE} but missing" for rel in listed_dirs
                if rel not in folders]
    return out


def purge_job(folder: Path, tombstone: Path, record: dict, lock: _Lock) -> None:
    """Step 7's deletion: rename the job folder to its tombstone (on Windows this fails at
    once when a program has a file in it open, before anything is deleted), check that the
    tombstone holds exactly what purge.json lists (else rename it back and refuse), then
    delete it."""
    _no_links(folder, "job")
    if tombstone.exists() or tombstone.is_symlink():
        raise LibraryError(f"{_p(tombstone)} exists already; nothing was deleted: look at it "
                           "by hand")
    try:
        os.rename(folder, tombstone)
    except OSError as e:
        raise LibraryError(f"cannot move {_p(folder)} to {_p(tombstone)} ({e.strerror or e}): "
                           "a program may have a file in it open; close it and run finish "
                           "again. Nothing of the job was deleted") from None
    lock.moved(tombstone)
    problems = tombstone_problems(tombstone, record, exact=True)
    if problems:
        try:
            os.rename(tombstone, folder)
        except OSError as e:
            raise LibraryError(
                f"the job changed after {PURGE_FILE} listed it ({'; '.join(problems[:5])}), "
                f"and it could not be moved back to {_p(folder)} ({e.strerror or e}): the "
                f"job is in {_p(tombstone)} and nothing was deleted. Look at both by hand; "
                f"move it back to {_p(folder)} before running finish again") from None
        lock.moved(folder)
        raise LibraryError(f"the job changed after {PURGE_FILE} listed it ("
                           f"{'; '.join(problems[:5])}); nothing was deleted. Run finish "
                           "again to list it afresh")
    delete_job(tombstone)


# --- finish ---------------------------------------------------------------------------------------

def _today(today: datetime.date | None) -> str:
    return (datetime.date.today() if today is None else today).isoformat()


@dataclass
class _Run:
    """What one finish works on."""
    name: str
    folder: Path
    tombstone: Path
    staging: Path
    entry: Path
    jobs_dir: Path
    prints_dir: Path
    repo: Path | None
    public: bool
    words: str | None
    number: int | None
    dry_run: bool
    machine: Machine
    day: str
    say: Callable[[str], None]
    lock: _Lock | None = None


def finish(name: str, *, public: bool | None, purge_owner_said: str | None,
           confirmation: int | None = None, dry_run: bool = False,
           machine: Machine | None = None, jobs_dir: Path | None = None,
           prints_dir: Path | None = None, repo: Path | None = None,
           say: Callable[[str], None] = print, today: datetime.date | None = None) -> None:
    """tdmg finish (module docstring). Raises LibraryError on a refusal and RebuildDiffers
    when the rebuild does not match; before the purge's deletion nothing of the job is
    deleted, and a deletion that stops part way leaves the rest in the tombstone for the
    next run."""
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
    try:
        jobs_dir = Path(os.path.abspath(jobs.default_jobs_dir() if jobs_dir is None
                                        else jobs_dir))
    except JobError as e:
        raise LibraryError(str(e)) from None
    prints_dir = Path(os.path.abspath(default_prints_dir() if prints_dir is None
                                      else prints_dir))
    run = _Run(name, jobs_dir / name, jobs_dir / f"{jobs.TOMBSTONE_PREFIX}{name}",
               prints_dir / f"{STAGING_PREFIX}{name}", prints_dir / name, jobs_dir,
               prints_dir, code_checkout() if repo is None else Path(repo), public,
               purge_owner_said, confirmation, dry_run, machine, _today(today), say)
    folder, entry = run.folder, run.entry
    # Step 1: names and paths.
    for path, what in ((folder, "job"), (run.tombstone, "job tombstone"),
                       (prints_dir, "prints folder"), (run.staging, "staging folder"),
                       (entry, "library entry")):
        _no_links(path, what)
    rj, rp = folder.resolve(), prints_dir.resolve()
    if _inside(rj, rp) or _inside(rp, rj):
        raise LibraryError(f"the job {_p(folder)} and the prints folder {_p(prints_dir)} "
                           "overlap; they must be separate folders")
    if rj != jobs_dir.resolve() / name:
        raise LibraryError(f"the job must be exactly {_p(jobs_dir / name)}")
    for path, what in ((folder, "job"), (run.tombstone, "job tombstone"),
                       (run.staging, "staging folder"), (entry, "library entry")):
        if path.exists() and not path.is_dir():
            raise LibraryError(f"the {what} {_p(path)} is not a folder")
    if folder.exists() and run.tombstone.exists():
        raise LibraryError(f"both {_p(folder)} and its tombstone {_p(run.tombstone)} exist; "
                           "nothing was changed: look at them by hand")
    held = folder if folder.exists() else run.tombstone if run.tombstone.exists() else None
    if held is None:
        _no_job(run)
        return
    _walk(held)                         # a link or unreadable folder inside: refused now
    run.lock = _Lock(held)
    run.lock.acquire()
    try:
        _locked(run, held)
    finally:
        run.lock.release()


def _no_job(run: _Run) -> None:
    """Neither the job nor its tombstone exists: finished already, or refused."""
    entry, staging = run.entry, run.staging
    if entry.is_dir() and (entry / COMPLETE_FILE).is_file() and not staging.exists():
        problems = verify_complete(entry)
        if problems:
            raise LibraryError(f"{_p(entry)} does not verify: {'; '.join(problems)}")
        run.say(f"job {run.name} is already finished: {_p(entry)} is complete and "
                "verifies, and the job is gone")
        return
    if entry.exists() or staging.exists():
        raise LibraryError(f"there is no job {run.name} in {_p(run.jobs_dir)}, but "
                           f"{_p(entry if entry.exists() else staging)} is not a finished "
                           "entry; nothing was changed: look at it by hand")
    raise LibraryError(f"no job {run.name} in {_p(run.jobs_dir)}")


def _locked(run: _Run, held: Path) -> None:
    """Steps 1 (the rest) to 7, under the lock; the entry's state is read here."""
    folder, entry, staging = run.folder, run.entry, run.staging
    has_staging, has_entry = staging.exists(), entry.exists()
    complete = (entry / COMPLETE_FILE).is_file()
    for path in (staging, entry):
        if path.is_dir():
            _walk(path)
    if run.dry_run and (has_staging or has_entry or held == run.tombstone):
        raise LibraryError("an earlier finish of this job is unfinished (a staging folder, "
                           f"{_p(entry)} or the job's tombstone exists); run finish without "
                           "--dry-run to resume it")
    if has_staging and has_entry:
        raise LibraryError(f"both {_p(staging)} and {_p(entry)} exist; nothing was changed: "
                           "look at them by hand")
    run.say(f"1. names and paths: job {_p(folder)}, library entry {_p(entry)}")
    if held == run.tombstone:
        if not (has_entry and complete):
            raise LibraryError(f"{_p(run.tombstone)} exists but {_p(entry)} is not a "
                               "finished entry; nothing was changed: look at them by hand")
        _resume_tombstone(run)
        return
    if not (folder / JOB_FILE).is_file():
        raise LibraryError(f"{_p(folder)} has no {JOB_FILE}: not a job")
    if has_entry and complete:
        _resume_purge(run)
    elif has_entry:
        _resume_publish(run)
    else:
        if has_staging:
            _remove_staging(staging)
            run.say(f"   removed {_p(staging)}, left by an interrupted finish; staging again")
        _fresh(run)


def _remove_staging(staging: Path) -> None:
    _no_links(staging, "staging folder")
    _walk(staging)
    shutil.rmtree(staging, onexc=_onexc)


def _describe(c: ConfirmationStatus) -> str:
    e = c.entry
    return (f"confirmation {c.number}: {confirmations.describe(e)}, {e['date']}, "
            f"{_words(e['owner_said'])}")


def _state(run: _Run) -> State:
    state = check_state(run.folder, run.machine, run.number, run.repo, run.jobs_dir,
                        run.prints_dir)
    run.say(f"2. state: every stage done and current; {_describe(state.chosen)}; git tree "
            f"clean at {state.git.commit}")
    return state


def _not_kept_line(run: _Run, files) -> str:
    stages = recipe(load_job(run.folder)["recipe"]).stages
    extra = not_kept(files, stages)
    return ("" if not extra else
            "; not kept in the library and not stage outputs: " + ", ".join(map(_p, extra)))


def _fresh(run: _Run) -> None:
    state = _state(run)
    staging, prints_dir = run.staging, run.prints_dir
    made_prints = not prints_dir.exists()

    def tidy():
        if staging.exists():
            _remove_staging(staging)
        if made_prints and prints_dir.is_dir() and not any(prints_dir.iterdir()):
            prints_dir.rmdir()
    try:
        files = payload(state, run.public)
        files[CARD_FILE] = card(state, run.public, run.day).encode("utf-8")
        prov = record_text(provenance(state, run.public, run.machine, run.day))
        try:
            write_outputs(staging, files, PROVENANCE_FILE, prov, create_folder=True,
                          subfolders=True)
        except RecordError as e:
            raise LibraryError(str(e)) from None
        run.say(f"3. staged {_p(staging)}: {len(files) + 1} files")
        differences = rebuild(staging, state, run.machine, run.say)
        if differences:
            raise RebuildDiffers(differences)
        run.say("   the rebuild matches: every file byte for byte, except the G-code "
                "timestamp lines and slice.json's hashes of those G-code files "
                f"({REPEATABILITY})")
        if not run.dry_run:
            replace_file(staging, STAGED_FILE, staged_bytes(staging))
    except Exception:
        tidy()
        raise
    folder_name = PUBLIC_DIR if run.public else PRIVATE_DIR
    if run.dry_run:
        tidy()
        files, folders = job_listing(run.folder)
        run.say("dry run: nothing was changed; the staging folder is removed. A real run "
                "would:")
        run.say(f"5. public: {'yes' if run.public else 'no'}: the printable files in "
                f"{folder_name}/" + (" (tracked in git)" if run.public else " (git-ignored)"))
        run.say(f"6. publish: rename the staging folder to {_p(run.entry)}, write "
                f"{PURGE_FILE}, then {COMPLETE_FILE}")
        run.say(f"7. purge: delete {_p(run.folder)} ({len(files)} files, {len(folders)} "
                f"folders), with --purge-owner-said{_not_kept_line(run, files)}")
        return
    run.say(f"5. public: {'yes' if run.public else 'no'}: printable files in {folder_name}/")
    os.rename(staging, run.entry)
    run.say(f"6. published {_p(run.entry)}")
    _purge(run)


def _purge(run: _Run) -> None:
    """Write purge.json and COMPLETE, check the entry, then delete the job."""
    listing = job_listing(run.folder)
    replace_file(run.entry, PURGE_FILE, purge_record(
        run.name, run.words, run.day, listing, jobs_folder_text(run.jobs_dir, run.repo)))
    replace_file(run.entry, COMPLETE_FILE, complete_bytes(run.entry))
    run.say(f"   wrote {PURGE_FILE} ({len(listing[0])} files of the job listed) and "
            f"{COMPLETE_FILE}")
    _delete(run, listing[0])


def _check_entry(run: _Run) -> dict:
    """The entry verifies and is this job's: COMPLETE (every hash) and entry_problems."""
    record = _purge_record(run.entry, run.name)
    if record is None:
        raise LibraryError(f"{_p(run.entry)} has no {PURGE_SCHEMA} {PURGE_FILE} for job "
                           f"{run.name}; the job is not deleted")
    problems = verify_complete(run.entry) or entry_problems(run.entry, run.name, record)
    if problems:
        raise LibraryError(f"{_p(run.entry)} does not verify as this job's finished entry "
                           f"({'; '.join(problems[:6])}); the job is not deleted")
    return record


def _delete(run: _Run, files) -> None:
    record = _check_entry(run)
    note = _not_kept_line(run, files)
    purge_job(run.folder, run.tombstone, record, run.lock)
    run.say(f"7. purged {_p(run.folder)}: the owner said {_words(record['owner_said'])}"
            + note)


def _same_job(folder: Path, entry: Path) -> None:
    mine, theirs = folder / JOB_FILE, entry / JOB_FILE
    if mine.is_file() and theirs.is_file() and _read(mine) == _read(theirs):
        return
    raise LibraryError(f"{_p(entry)} already exists and is not this job's print (its "
                       f"{JOB_FILE} differs); choose another job name, or look at it by "
                       "hand. Nothing was changed")


def _resume_publish(run: _Run) -> None:
    """prints/NAME without COMPLETE (module docstring, Resume)."""
    entry, name = run.entry, run.name
    _same_job(run.folder, entry)
    state = _state(run)
    prov = _json_or_none(_read(entry / PROVENANCE_FILE)) \
        if (entry / PROVENANCE_FILE).is_file() else None
    if not (isinstance(prov, dict) and prov.get("schema") == PROVENANCE_SCHEMA
            and prov.get("name") == name):
        raise LibraryError(f"{_p(entry)} has no {PROVENANCE_SCHEMA} {PROVENANCE_FILE} for job "
                           f"{name}; nothing was changed: look at it by hand")
    if prov.get("public") != run.public:
        raise LibraryError(f"{_p(entry)} was published with --public "
                           f"{'yes' if prov.get('public') else 'no'}; run finish again with "
                           "that answer (a publish is never redone)")
    if prov.get("confirmation") != {"number": state.chosen.number,
                                    "entry": state.chosen.entry}:
        raise LibraryError(f"{_p(entry)} was published for confirmation "
                           f"{(prov.get('confirmation') or {}).get('number')}, not "
                           f"{state.chosen.number}; give --confirmation for it")
    hashes = {s: _sha(b) for s, b in state.records.items()}
    if {s: (v or {}).get("record_sha256") for s, v in (prov.get("stages") or {}).items()} \
            != hashes:
        raise LibraryError("the job's stage records changed since the publish; nothing was "
                           "changed: look at it by hand")
    for leftover in [p for p in entry.iterdir() if LEFTOVER_TMP.fullmatch(p.name)]:
        leftover.unlink()
        run.say(f"   removed {_p(leftover.name)}, left by an interrupted write")
    problems = staged_problems(entry)
    expected = payload(state, run.public)
    problems += [f"{_p(f)}: not the job's" for f in expected
                 if not (entry / f).is_file() or _read(entry / f) != expected[f]]
    if problems:
        raise LibraryError(f"{_p(entry)} is not what finish staged and checked ("
                           f"{'; '.join(problems[:6])}); nothing was changed")
    run.say(f"6. {_p(entry)} was published by an earlier run (not redone); it matches what "
            "was staged and checked, and the job")
    _purge(run)


def _differs_note(run: _Run, record: dict) -> None:
    """Say plainly where this run's answers differ from the entry's, which are kept."""
    prov = _json_or_none(_read(run.entry / PROVENANCE_FILE)) or {}
    if prov.get("public") != run.public:
        was = "yes" if prov.get("public") else "no"
        run.say(f"   note: the entry was published with --public {was}; this run's "
                f"--public {'yes' if run.public else 'no'} is not used (a publish is never "
                "redone)")
    if run.words is not None and run.words != record["owner_said"]:
        run.say(f"   note: the earlier run's purge record is kept, with the owner's words "
                f"{_words(record['owner_said'])}; this run's --purge-owner-said is not "
                "recorded")


def _resume_purge(run: _Run) -> None:
    """COMPLETE with the job folder still present: the run stopped after COMPLETE, before
    the job was moved to its tombstone, so the job must be exactly what purge.json lists
    (a job made again under the same name is not)."""
    _same_job(run.folder, run.entry)
    record = _check_entry(run)
    problems = tombstone_problems(run.folder, record, exact=True)
    if problems:
        raise LibraryError(f"{_p(run.folder)} is not the job {PURGE_FILE} lists ("
                           f"{'; '.join(problems[:5])}); it may be a new job of the same "
                           "name. Nothing was deleted")
    run.say(f"6. {_p(run.entry)} is complete and verifies; finishing the interrupted purge")
    _differs_note(run, record)
    _delete(run, record["files"])


def _resume_tombstone(run: _Run) -> None:
    """The job's tombstone with a finished entry: the deletion stopped part way. Every file
    left must be in purge.json with the same SHA-256; then it is deleted."""
    record = _check_entry(run)
    problems = tombstone_problems(run.tombstone, record, exact=False)
    if problems:
        raise LibraryError(f"{_p(run.tombstone)} holds what {PURGE_FILE} does not list ("
                           f"{'; '.join(problems[:5])}); nothing was deleted")
    run.say(f"6. {_p(run.entry)} is complete and verifies; finishing the deletion of "
            f"{_p(run.tombstone)}")
    _differs_note(run, record)
    delete_job(run.tombstone)
    run.say(f"7. purged {_p(run.folder)}: the owner said {_words(record['owner_said'])}")


# --- tdmg library check (restructure plan Task 10) ----------------------------------------------

# The git-ignored parts of an entry (.gitignore prints/*/source/, prints/*/private/): absent
# from a fresh clone, so one of these folders missing entirely is "not on this machine",
# not damage.
LOCAL_ONLY = (SOURCE_DIR, PRIVATE_DIR)
OK, INCOMPLETE, DAMAGED = "ok", "incomplete", "damaged"


def library_jobs_dir() -> Path | None:
    """The jobs folder library check looks in for a job whose finish did not end (the
    checkout's jobs/; None outside a checkout). Tests point it at a temporary folder
    (tests/conftest.py)."""
    try:
        return jobs.default_jobs_dir()
    except JobError:
        return None


@dataclass
class EntryCheck:
    """One library entry (or a leftover staging folder), as library check found it."""
    name: str
    state: str                          # OK, INCOMPLETE or DAMAGED
    problems: list[str]                 # what is wrong (INCOMPLETE or DAMAGED)
    unavailable: list[str]              # LOCAL_ONLY folders not on this machine


def _again(name: str) -> str:
    return f"run tdmg finish {name} again to resume it"


# Files an operating system writes into folders it shows (I2 of the Task 10 review): kept as
# damage, since they are not the entry's, with a message that says what they are.
OS_FILES = {".ds_store": "macOS Finder's folder settings",
            "thumbs.db": "Windows Explorer's thumbnail cache",
            "desktop.ini": "Windows Explorer's folder settings"}
APPLEDOUBLE = "._"
# finish's words in the messages of the helpers check shares with it, and check's.
_LINKS = "; library check does not follow links"
_FINISH_WORDS = (("; finish works only on plain folders", _LINKS),
                 ("; finish does not follow links, so it stops here", _LINKS),
                 ("; finish stops, and nothing of the job is deleted", ""))


def _check_words(text: str) -> str:
    for finish_words, check_words in _FINISH_WORDS:
        text = text.replace(finish_words, check_words)
    return text


def os_file(rel: str) -> str | None:
    """What wrote this file, when an operating system did (OS_FILES, AppleDouble), else
    None."""
    base = rel.rpartition("/")[2]
    if base.casefold() in OS_FILES:
        return OS_FILES[base.casefold()]
    if base.startswith(APPLEDOUBLE):
        return ("a macOS AppleDouble file: Finder's metadata, written on FAT, exFAT and "
                "network drives")
    return None


def _extra(rel: str) -> str:
    what = os_file(rel)
    if what is None:
        return f"{_p(rel)}: not listed in {COMPLETE_FILE} (an extra file)"
    return (f"{_p(rel)}: a file the operating system adds ({what}), not one of the "
            f"entry's; deleting it is safe")


def check_entry(entry: Path, jobs_dir: Path | None = None) -> EntryCheck:
    """library check of one entry (module docstring, "tdmg library check"). Anything that
    cannot be read makes the entry DAMAGED, in check's words."""
    try:
        found = _check_one(entry, jobs_dir)
    except LibraryError as e:
        return EntryCheck(entry.name, DAMAGED, [_check_words(str(e))], [])
    found.problems = [_check_words(t) for t in found.problems]
    return found


def _check_one(entry: Path, jobs_dir: Path | None) -> EntryCheck:
    name = entry.name
    _no_links(entry, "library entry")
    if not (entry / COMPLETE_FILE).exists():
        why = (f"it was published, but its finish stopped before writing {COMPLETE_FILE}"
               if (entry / STAGED_FILE).is_file() else "an interrupted tdmg finish left it")
        return EntryCheck(name, INCOMPLETE, [f"no {COMPLETE_FILE}: {why}; {_again(name)}"],
                          [])
    listed = _manifest_files(entry / COMPLETE_FILE, COMPLETE_SCHEMA)
    if listed is None:
        return EntryCheck(name, DAMAGED, [(f"{COMPLETE_FILE} is not a {COMPLETE_SCHEMA} "
                                          "manifest (damaged or edited)")], [])
    files, folders = _walk(entry)
    files = [f for f in files if f != COMPLETE_FILE]
    absent = [top for top in LOCAL_ONLY if not (entry / top).exists()
              and any(rel.startswith(top + "/") for rel in listed)]
    out = []
    for rel in sorted(listed):
        top = rel.split("/")[0]
        if rel in files:
            if _sha(_read(entry / rel)) != listed[rel]:
                out.append(f"{_p(rel)}: its SHA-256 is not the one {COMPLETE_FILE} lists "
                           "(changed or damaged)")
        elif top not in absent:
            out.append(f"{_p(rel)}: listed in {COMPLETE_FILE} but missing"
                       + (f" ({top}/ is here, so this is not a clone without it: a partial "
                          "copy, or a deleted file)" if top in LOCAL_ONLY else ""))
    out += [_extra(rel) for rel in files if rel not in listed]
    parents = {p.as_posix() for rel in listed for p in Path(rel).parents if str(p) != "."}
    out += [f"{_p(rel)}/: a folder that holds no file {COMPLETE_FILE} lists"
            for rel in folders if rel not in parents]
    out += _consistency(entry, name, listed)
    if out:
        return EntryCheck(name, DAMAGED, out, absent)
    for left in ([] if jobs_dir is None else
                 [jobs_dir / name, jobs_dir / f"{jobs.TOMBSTONE_PREFIX}{name}"]):
        if left.exists():
            return EntryCheck(name, INCOMPLETE, [
                (f"the entry verifies, but {_p(left)} is still there: the finish stopped "
                f"before its purge ended; {_again(name)}")], absent)
    return EntryCheck(name, OK, [], absent)


def _consistency(entry: Path, name: str, listed: dict) -> list[str]:
    """The entry's records agree with COMPLETE and with each other: STAGED lists what
    COMPLETE lists (but STAGED and purge.json) with the same SHA-256s; entry_problems
    (provenance.json, the printable files, the stage-record hashes, job.yaml and source
    against purge.json); and the source hashes job.yaml names are those COMPLETE lists, and
    provenance.json's source is job.yaml's. Judged from COMPLETE's list, so a folder not on
    this machine is no problem here."""
    out = []
    staged = _manifest_files(entry / STAGED_FILE, STAGED_SCHEMA) \
        if (entry / STAGED_FILE).is_file() else None
    if staged is None:
        out.append(f"no {STAGED_SCHEMA} {STAGED_FILE}")
    else:
        want = set(listed) - {STAGED_FILE, PURGE_FILE}
        out += [f"{_p(rel)}: in {STAGED_FILE}, not in {COMPLETE_FILE}"
                for rel in sorted(set(staged) - want)]
        out += [f"{_p(rel)}: in {COMPLETE_FILE}, not in {STAGED_FILE}"
                for rel in sorted(want - set(staged))]
        out += [f"{_p(rel)}: {COMPLETE_FILE}'s SHA-256 is not {STAGED_FILE}'s (changed after "
                "the rebuild was checked)" for rel in sorted(set(staged) & want)
                if staged[rel] != listed[rel]]
    try:
        record = _purge_record(entry, name)
        if record is None:
            return [*out, f"no {PURGE_SCHEMA} {PURGE_FILE} for job {name}"]
        out += entry_problems(entry, name, record)
        job = parse_job(_read(entry / JOB_FILE)) if (entry / JOB_FILE).is_file() else None
        prov = _json_or_none(_read(entry / PROVENANCE_FILE)) \
            if (entry / PROVENANCE_FILE).is_file() else None
    except (LibraryError, JobError) as e:
        return [*out, str(e)]
    except (KeyError, TypeError, ValueError, AttributeError) as e:  # a malformed record
        return [*out, (f"the entry's records cannot be read together ({type(e).__name__}: "
                      f"{e})")]
    if job is not None:
        for src in [job["source"]] + ([job["source"]["mask"]] if job["source"]["mask"]
                                      else []):
            if listed.get(src["file"]) != src["sha256"]:
                out.append(f"{JOB_FILE} names {_p(src['file'])} with a SHA-256 that is not "
                           f"the one {COMPLETE_FILE} lists")
        if isinstance(prov, dict) and prov.get("source") != job["source"]:
            out.append(f"{PROVENANCE_FILE}'s source is not {JOB_FILE}'s")
    return out


def _staging_leftover(name: str) -> EntryCheck:
    return EntryCheck(f"{STAGING_PREFIX}{name}", INCOMPLETE, [
        (f"an interrupted tdmg finish of job {name} left this staging folder (it stopped "
        f"before the publish; nothing of the job was deleted); {_again(name)}")], [])


def check_library(name: str | None = None, *, prints_dir: Path | None = None,
                  jobs_dir: Path | None = None) -> list[EntryCheck]:
    """tdmg library check [NAME]: every entry of the library (or the one named) and every
    leftover staging folder (of NAME, when named). LibraryError when it cannot check: no
    such library folder or entry, a bad name, a link in the library folder's path."""
    prints_dir = Path(os.path.abspath(default_prints_dir() if prints_dir is None
                                      else prints_dir))
    jobs_dir = library_jobs_dir() if jobs_dir is None else Path(os.path.abspath(jobs_dir))
    _no_links(prints_dir, "prints folder")
    if not prints_dir.is_dir():
        raise LibraryError(f"there is no library folder {_p(prints_dir)}; give --prints-dir")
    if name is not None:
        try:
            name = check_name(name)
        except JobError as e:
            raise LibraryError(str(e)) from None
        # The folders as the disk names them: on a case-insensitive file system
        # prints/Roadie opens as prints/roadie, and is reported as Roadie.
        out = [_judge(path, jobs_dir) for path in
               (_on_disk(prints_dir, name), _on_disk(prints_dir, STAGING_PREFIX + name))
               if path is not None and (path.is_dir() or path.is_symlink())]
        if not out:
            raise LibraryError(f"no library entry {name} in {_p(prints_dir)}")
        return out
    return [_judge(path, jobs_dir) for path in sorted(prints_dir.iterdir(),
                                                      key=lambda p: p.name)
            if path.is_dir() or path.is_symlink()]     # files beside the entries: not looked at


def _judge(path: Path, jobs_dir: Path | None) -> EntryCheck:
    """One folder of the library: a staging leftover, a folder that is no entry, or an
    entry."""
    if path.name.startswith(STAGING_PREFIX):
        return _staging_leftover(path.name.removeprefix(STAGING_PREFIX))
    if jobs.name_problem(path.name) is not None:
        return EntryCheck(path.name, DAMAGED, [
            ("not a library entry: its name is not a job name, and tdmg finish makes no "
             "such folder")], [])
    return check_entry(path, jobs_dir)


def unavailable_text(top: str) -> str:
    """The note for a git-ignored folder that is not on this machine."""
    if top == SOURCE_DIR:
        return (f"source unavailable: {SOURCE_DIR}/ is git-ignored and is not on this "
                "machine (a clone, or a copy of prints/ without it); tdmg library verify "
                "needs it")
    return (f"private files unavailable: {PRIVATE_DIR}/ is git-ignored and is not on this "
            "machine; the printable files are on the machine that finished the print")


# --- tdmg library verify (restructure plan Task 10) ---------------------------------------------

class CannotVerify(LibraryError):
    """library verify cannot run (exit 2): no such entry, the entry does not check, its
    source is not on this machine, or a stage could not run."""


def _head(repo: Path | None) -> str:
    """The code checkout's commit now, saying when tracked files have uncommitted changes;
    'unknown (...)' outside a git checkout."""
    if repo is None or not (Path(repo) / ".git").exists():
        return "unknown (not running from a git checkout)"
    try:
        commit = _git(Path(repo), "rev-parse", "HEAD").decode("ascii").strip()
        dirty = _git(Path(repo), "status", "--porcelain=v1", "--untracked-files=no").strip()
    except LibraryError as e:
        return f"unknown ({e})"
    return commit + (" (with uncommitted changes to tracked files)" if dirty else "")


def _uv_lock(repo: Path | None) -> str | None:
    """uv.lock's SHA-256 as finish records it (uv_lock_sha256); outside a git checkout,
    the file's with CRLF line ends made LF; None without one."""
    if repo is not None and (Path(repo) / ".git").exists():
        try:
            return uv_lock_sha256(Path(repo))
        except LibraryError:
            return None
    lock = None if repo is None else Path(repo) / "uv.lock"
    if lock is None or not lock.is_file():
        return None
    return _sha(lock.read_bytes().replace(b"\r\n", b"\n"))


def what_changed(prov: dict, job: dict, machine: Machine, repo: Path | None) -> list[str]:
    """What differs between the historical run (provenance.json) and this one, outside the
    outputs: the code commit, tdmg's version, uv.lock, Python and platform, the key
    libraries, the rules (rules_sha256, and the default, unit and range of each rule the
    records used), each stage's algorithm ids and profiles (with the slicer pins, and so
    whether PrusaSlicer is configured)."""
    out = []

    def differs(what, was, now):
        if was != now:
            out.append(f"{what}: was {json.dumps(was, sort_keys=True)}, now "
                       f"{json.dumps(now, sort_keys=True)}")
    code, env = prov.get("code") or {}, prov.get("environment") or {}
    head = _head(repo)
    if head != code.get("git_commit"):
        out.append(f"code commit: was {code.get('git_commit')}, now {head}")
    differs("tdmg version", code.get("tdmg_version"), __version__)
    differs("uv.lock SHA-256 (git blob at HEAD)", code.get("uv_lock_sha256"), _uv_lock(repo))
    differs("Python", env.get("python"), platform.python_version())
    differs("platform", env.get("platform"), platform.platform())
    was_libs, now_libs = env.get("libraries") or {}, _libraries()
    for dist in sorted(set(was_libs) | set(now_libs)):
        differs(f"key library {dist}", was_libs.get(dist), now_libs.get(dist))
    differs("rules_sha256 (every rule's id, default, unit and range)",
            prov.get("rules_sha256"), rules_sha256())
    registry = load_rules()
    for rid, was in sorted((prov.get("rules") or {}).items()):
        r = registry.get(rid)
        if r is None:
            out.append(f"rule {rid}: in rules/ then, not now")
            continue
        now = {"default": r.default, "unit": r.unit,
               "range": None if r.range is None else list(r.range)}
        for key in ("default", "unit", "range"):
            differs(f"rule {rid} {key}", (was or {}).get(key), now[key])
    for s in recipe(job["recipe"]).stages:
        hist = (prov.get("stages") or {}).get(s) or {}
        differs(f"stage {s} algorithm ids", hist.get("algorithms_expected"),
                stage_algorithms(job, s))
        differs(f"stage {s} profiles", (prov.get("profiles") or {}).get(s),
                stage_profiles(job, s, machine) or None)
    return out


def prusaslicer_then(prov: dict) -> bool:
    """Whether the historical run had PrusaSlicer configured: its slice stage's profiles
    hold the PrusaSlicer pin exactly when it was (tdmg.job_runner.stage_profiles)."""
    return "prusaslicer_pin_sha256" in ((prov.get("profiles") or {}).get("slice") or {})


def _keyed(items, key) -> dict:
    return {key(d): d for d in (items if isinstance(items, list) else [])
            if isinstance(d, dict)}


def _check_differences(stage: str, was, now: list[dict]) -> list[str]:
    def key(d):
        return (str(d.get("path")), str(d.get("id")))
    a, b = _keyed(was, key), _keyed(now, key)
    out = []
    for k in sorted(set(a) | set(b)):
        path, cid = k
        if k not in b:
            out.append(f"{stage} check {cid} at {path}: in the historical record, not now")
        elif k not in a:
            out.append(f"{stage} check {cid} at {path}: new now ({b[k].get('status')})")
        else:
            for field in ("status", "rule", "threshold"):
                if a[k].get(field) != b[k].get(field):
                    out.append(f"{stage} check {cid} at {path}: {field} was "
                               f"{json.dumps(a[k].get(field))}, now "
                               f"{json.dumps(b[k].get(field))}")
    return out


def _verdict_differences(stage: str, was, now: list[dict]) -> list[str]:
    def key(d):
        return str(d.get("path"))
    a, b = _keyed(was, key), _keyed(now, key)
    out = []
    for p in sorted(set(a) | set(b)):
        if p not in a or p not in b or a[p].get("value") != b[p].get("value"):
            then = json.dumps(a[p].get("value")) if p in a else "absent"
            now_ = json.dumps(b[p].get("value")) if p in b else "absent"
            out.append(f"{stage} verdict at {p}: was {then}, now {now_}")
    return out


NOT_COMPARED = (
    ("the stage folders' other files (previews, outlines and the rest; not the G-code, which "
     "is compared): the library keeps only the confirmed route's printable files, and the "
     "job's own files were deleted by the purge"),
    ("the G-code timestamp lines and slice.json's hashes of the G-code files: they change "
     f"with the time of slicing ({REPEATABILITY}); the rest of each G-code file and of "
     "slice.json is compared by SHA-256"),
    ("check measurements (a check's measured value): provenance.json holds each check's id, "
     "status, rule and threshold only"),
)


def _on_disk(prints_dir: Path, name: str) -> Path | None:
    """The folder of prints_dir named name, as the disk spells it: the exact name, else one
    that differs only in case (which a case-insensitive file system would also open as
    name), else None."""
    try:
        names = os.listdir(prints_dir)
    except OSError as e:
        raise LibraryError(f"cannot read {_p(prints_dir)} ({e.strerror or e})") from None
    if name in names:
        return prints_dir / name
    folded = sorted(n for n in names if n.casefold() == name.casefold())
    return prints_dir / folded[0] if folded else None


def _check_slicers(job: dict, machine: Machine) -> None:
    """CannotVerify when the pinned slicers the slice stage needs cannot be used on this
    machine (not found, not the pinned install): the environment, not the code. The same
    lookups the stage makes (tdmg.slicing), with the same full-tree check."""
    full = not job["stages"]["slice"]["skip_tree_check"]
    try:
        tdmg.slicing.locate(machine.slicer_dir, tdmg.slicing.load_pin(), full_tree=full)
        if machine.prusaslicer_configured():
            tdmg.slicing.locate_prusaslicer(machine.prusaslicer_dir,
                                            tdmg.slicing.load_prusa_pin(), full_tree=full)
    except SlicerError as e:
        raise CannotVerify(f"the slicer cannot be used on this machine: {e}") from None


def _scratch_base(prints_dir: Path) -> Path:
    """The folder verify makes its scratch folder in (tempfile's), refused when it is inside
    the library or the jobs folder: verify writes nothing into either."""
    base = Path(os.path.abspath(tempfile.gettempdir()))
    for folder, what in ((prints_dir, "the library"), (library_jobs_dir(), "the jobs folder")):
        if folder is not None and _inside(base.resolve(), Path(folder).resolve()):
            raise CannotVerify(f"the temporary folder {_p(base)} is inside {what} "
                               f"{_p(folder)}, and verify writes nothing there; set TEMP and "
                               "TMP (TMPDIR on macOS and Linux) to a folder outside it")
    return base


def verify(name: str, *, machine: Machine | None = None, prints_dir: Path | None = None,
           repo: Path | None = None, say: Callable[[str], None] = print) -> list[str]:
    """tdmg library verify NAME (module docstring): run the entry's job.yaml and source/
    under the current code and rules in a scratch folder; return the differences from the
    historical run ([] when identical under the comparison rule). Nothing is written into
    the library. CannotVerify when it cannot run."""
    machine = Machine() if machine is None else machine
    repo = code_checkout() if repo is None else Path(repo)
    try:
        name = check_name(name)
    except JobError as e:
        raise CannotVerify(str(e)) from None
    prints_dir = Path(os.path.abspath(default_prints_dir() if prints_dir is None
                                      else prints_dir))
    entry = _on_disk(prints_dir, name) if prints_dir.is_dir() else None
    if entry is None or not entry.is_dir():
        raise CannotVerify(f"no library entry {name} in {_p(prints_dir)}")
    if entry.name != name:
        raise CannotVerify(f"there is no entry {name}: the folder is named {_p(entry.name)} "
                           "on disk, which is not a job name (tdmg library check reports it)")
    found = check_entry(entry)
    if found.state != OK:
        raise CannotVerify(f"{_p(entry)} does not check ({'; '.join(found.problems[:6])}); "
                           f"see tdmg library check {name}")
    if SOURCE_DIR in found.unavailable:
        raise CannotVerify(f"source unavailable: {_p(entry / SOURCE_DIR)} is not on this "
                           "machine (it is git-ignored, so a clone has none). verify runs "
                           "the job from job.yaml and source/: copy source/ from the "
                           "machine that finished the print, then run tdmg library check")
    prov = _json(_read(entry / PROVENANCE_FILE))
    job_bytes = _read(entry / JOB_FILE)
    try:
        job = parse_job(job_bytes)
    except JobError as e:
        raise CannotVerify(f"{JOB_FILE} in {_p(entry)}: {e}") from None
    then, now = prusaslicer_then(prov), machine.prusaslicer_configured()
    say(f"historical run: commit {(prov.get('code') or {}).get('git_commit')}, finished "
        f"{prov.get('finished')}, PrusaSlicer "
        + ("configured (F6.portability was checked)" if then else
           "not configured (F6.portability was UNKNOWN)"))
    confirmed = (prov.get("confirmation") or {}).get("entry") or {}
    say(f"historical verdict: {_dumps(confirmed.get('verdicts'))} "
        f"(route {confirmed.get('route')}" + (f", face {confirmed.get('face')}"
                                              if confirmed.get("face") else "") + ")")
    if then != now:
        say("note: this run has PrusaSlicer " + ("configured" if now else "not configured")
            + ", unlike the historical run, so F6.portability and the slice record will "
            "differ; " + ("give --prusaslicer-dir" if then else
                          "leave out --prusaslicer-dir and unset $TDMG_PRUSASLICER_DIR")
            + " to compare like for like")
    changed = what_changed(prov, job, machine, repo)
    say("changed since the historical run (these are causes, not differences in the "
        "outputs):" if changed else "unchanged since the historical run: the code commit, "
        "versions, key libraries, rules, algorithm ids and profiles")
    for line in changed:
        say(f"  {line}")
    if "slice" in recipe(job["recipe"]).stages:
        _check_slicers(job, machine)
    base = _scratch_base(prints_dir)
    with tempfile.TemporaryDirectory(prefix="tdmg-verify-", dir=base,
                                     ignore_cleanup_errors=True) as tmp:
        scratch = Path(tmp) / name
        scratch.mkdir()
        (scratch / JOB_FILE).write_bytes(job_bytes)
        shutil.copytree(entry / SOURCE_DIR, scratch / SOURCE_DIR)
        say(f"running the job in a scratch folder ({_p(scratch)}) from job.yaml and "
            "source/ ...")
        try:
            events, status = run_job(scratch, machine)
        except JobError as e:
            raise CannotVerify(f"the job cannot run: {e}") from None
        refused = {ev.stage: (f"failed (possibly the environment): {ev.message}"
                              if set(ev.error) & set(MACHINE_ERRORS) else
                              f"refused by the current code: {ev.message}")
                   for ev in events if ev.action == "failed"}
        return compare_with_provenance(scratch, prov, status, refused, say)


# The exception classes (in RunEvent.error, with their bases) of a stage failure that may
# come from the machine rather than the code: an I/O failure, or the slicer (a crash, a
# timeout, a changed install). Any other failure is the current code refusing the input.
MACHINE_ERRORS = ("OSError", "SlicerError")


def _dumps(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def slice_digests(slice_dir: Path, record_bytes: bytes) -> dict:
    """What provenance.json keeps of the slice stage beyond its record's SHA-256, so verify
    can compare it under the rebuild's allowance (module docstring, the rebuild comparison):
    the SHA-256 of slice.json with its volatile G-code hash fields masked, in tdmg's record
    form; and each G-code file's SHA-256 with its timestamp line blanked (gcode_digest)."""
    files, _ = _walk(slice_dir)
    return {"record_masked_sha256": _sha(record_text(_masked(_json(record_bytes)))),
            "gcode_sha256_without_timestamp": {
                rel: _sha(gcode_digest(rel.rpartition("/")[2], _read(slice_dir / rel)))
                for rel in files if rel.rpartition("/")[2] in GCODE_TIMESTAMPS}}


def gcode_digest(name: str, data: bytes) -> bytes:
    """A G-code file's bytes with its timestamp line (GCODE_TIMESTAMPS) replaced by
    TIMESTAMP_MARK, when that line has the measured form; else the bytes as they are. A
    marker, not an empty line, so a file with an empty line there does not match."""
    line_no, pattern = GCODE_TIMESTAMPS[name]
    lines = data.split(b"\n")
    i = line_no - 1
    if i < len(lines) and pattern.fullmatch(
            lines[i].rstrip(b"\r").decode("utf-8", "replace")) is not None:
        lines[i] = TIMESTAMP_MARK
    return b"\n".join(lines)


TIMESTAMP_MARK = b"<timestamp>"


def _slice_differences(scratch: Path, rec: dict, data: bytes, h: dict, say) -> list[str]:
    if "record_masked_sha256" not in h:
        if say is not None:
            say("note: provenance.json holds no masked hashes of slice.json and the G-code "
                "(an entry finished before they were recorded): only the slice record's "
                "identity, algorithm, verdicts and checks are compared")
        return []
    now = slice_digests(scratch / "slice", data)
    out = gcode_binding_problems(scratch / "slice", rec, f"slice/{SLICE_RECORD}")
    if record_text(rec) != data:          # equal content then means equal bytes
        out.append(f"slice/{SLICE_RECORD}: not in tdmg's record form (the same content in "
                   "other bytes is not the historical record)")
    if now["record_masked_sha256"] != h["record_masked_sha256"]:
        out.append(f"slice/{SLICE_RECORD}: differs from the historical record beyond its "
                   f"G-code hash fields (the measured volatile fields, {REPEATABILITY})")
    was = h.get("gcode_sha256_without_timestamp") or {}
    got = now["gcode_sha256_without_timestamp"]
    for rel in sorted(set(was) | set(got)):
        if rel not in got:
            out.append(f"slice/{rel}: in the historical run, not now")
        elif rel not in was:
            out.append(f"slice/{rel}: made now, not in the historical run")
        elif was[rel] != got[rel]:
            out.append(f"slice/{rel}: differs from the historical G-code beyond its "
                       "timestamp line")
    return out


def compare_with_provenance(scratch: Path, prov: dict, status,
                            refused: dict[str, str] | None = None,
                            say: Callable[[str], None] | None = None) -> list[str]:
    """The differences between a run of the entry's job (scratch) and provenance.json, over
    the historical and the current stages: a stage the current code refused (refused:
    stage -> what to say, from run_job's failed events); each stage done; each stage record's
    SHA-256 (slice.json's with its G-code hash fields masked, and each G-code file's with
    its timestamp line blanked: slice_digests) and algorithm; each stage's verdicts and
    checks (status, rule, threshold); and, from the confirmation, the slice record's
    identity, the confirmed route's printable files (by SHA-256, so byte for byte) and
    their verdicts."""
    refused = refused or {}
    out = []
    hist = prov.get("stages") if isinstance(prov.get("stages"), dict) else {}
    now = {s.stage: s for s in status.stages}
    for stage in [s for s in hist if s not in now]:
        out.append(f"stage {stage}: in the historical run, not now")
    for stage, s in now.items():
        if stage not in hist:
            out.append(f"stage {stage}: new now, not in the historical run")
            continue
        h = hist[stage] if isinstance(hist[stage], dict) else {}
        if stage in refused:
            out.append(f"stage {stage}: {refused[stage]}")
            continue
        if s.state != DONE:
            out.append(f"stage {stage} is {s.state} now" + (f" ({s.note})" if s.note
                                                            else "")
                       + "; it was done in the historical run")
            continue
        data = _read(scratch / stage / STAGE_RECORDS[stage])
        rec = _json_or_none(data)
        rec = rec if isinstance(rec, dict) else {}
        if stage == "slice":
            out += _slice_differences(scratch, rec, data, h, say)
        elif _sha(data) != h.get("record_sha256"):
            out.append(f"{stage}/{STAGE_RECORDS[stage]}: not byte for byte the "
                       "historical record (its SHA-256 differs)")
        if rec.get("algorithm") != h.get("algorithm"):
            out.append(f"stage {stage} algorithm: was {h.get('algorithm')}, now "
                       f"{rec.get('algorithm')}")
        out += _verdict_differences(stage, h.get("verdicts"), verdicts_in(rec))
        out += _check_differences(stage, h.get("checks"), check_results(rec))
    if set(hist) != set(now):
        return [*out, ("the printable files cannot be compared: the stages are not the "
                      "historical run's")]
    if any(s.state != DONE for s in status.stages):
        return [*out, "the printable files cannot be compared: a stage is not done"]
    entry = (prov.get("confirmation") or {}).get("entry") or {}
    covers = entry.get("covers") if isinstance(entry.get("covers"), dict) else {}
    try:
        cover = confirmations.print_cover(scratch, load_job(scratch), entry.get("route"),
                                          entry.get("face"))
    except JobError as e:
        return [*out, f"the printable files cannot be bound: {e}"]
    if cover.slice_id != entry.get("slice_id"):
        out.append(f"the slice record's identity: was {entry.get('slice_id')}, now "
                   f"{cover.slice_id}")
    for rel in sorted(set(cover.covers) | set(covers)):
        if cover.covers.get(rel) != covers.get(rel):
            out.append(f"printable file {rel}: not byte for byte the historical one (its "
                       "SHA-256 differs)" if rel in cover.covers and rel in covers else
                       f"printable file {rel}: " + ("not made now" if rel in covers
                                                    else "made now, not then"))
    if cover.verdicts != entry.get("verdicts"):
        out.append(f"the printed model's verdicts: were {_dumps(entry.get('verdicts'))}, now "
                   f"{_dumps(cover.verdicts)}")
    return out

"""Shared fixtures.

**The owner's images.** The owner's selections measured in the color-palette Task 1 record
(research/verification/2026-11-11-color-palette/results.txt). The images are git-ignored,
so the owner fixtures (owner_selection_dir, owner_selection) build each selection in a
temporary folder (restructure plan Task 11; design section 7) from the first of these that
is present (build_owner_selection, OWNER_SOURCES):
1. a library source: the checkout's prints/<entry>/job.yaml and the source/ it names
   (source/ is git-ignored), with the controls recorded in its stages.select;
2. a job source: the checkout's jobs/<job>/job.yaml and source/, the same way;
3. the legacy folder artifacts/selection-runs/<name>/ (mask.png, cutout.png, preview.png,
   selection.json), copied, while it exists (Task 14 deletes Roadie's).
1 and 2 are run as `tdmg job run`'s select stage runs them (tdmg.job_runner._run_select).
The selection built must be the one the record measured: its selection_id equals the one
band-survival.txt records for that name, and its mask.png and cutout.png have the
SHA-256[:16] that results.txt records. A source that is present but gives another
selection is passed over with a warning naming why, and the next one is tried; when no
source gives the recorded selection, the test fails (it would test other images). When no
source is present, the test skips with a message naming every path it looked at, never
silently.

The library and jobs folders read here are the REAL checkout's (ROOT / "prints" and
"jobs", ROOT being tdmg.paths.REPO_ROOT), named explicitly: the autouse fixture below
points the default library and jobs folders at empty temporary ones, so the defaults
would never find them.
Nothing is written into the checkout's prints/, jobs/ or artifacts/: the selection is
built, or copied, into a session temporary folder, once per session per name.
"""

import hashlib
import json
import re
import shutil
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import tdmg.cli
import tdmg.library
from tdmg.job_runner import _run_select
from tdmg.jobs import JOB_FILE, JobError, check_source, load_job
from tdmg.selection import SelectionError

# The checkout these tests are in (tdmg.paths.REPO_ROOT when tdmg runs from it).
ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research" / "verification" / "2026-11-11-color-palette"
SELECTIONS = ROOT / "artifacts" / "selection-runs"
# Real default library functions, for the tests of that default (the fixture below
# replaces them in every test).
REAL_DEFAULT_LIBRARY = tdmg.cli.default_library
REAL_DEFAULT_PRINTS_DIR = tdmg.library.default_prints_dir


@dataclass(frozen=True)
class OwnerSources:
    """Where one owner selection's sources are: a library entry name (prints/), a job name
    (jobs/) and a legacy folder name (artifacts/selection-runs/). None: there is none."""
    library: str | None
    job: str | None
    legacy: str | None


# The results.txt name -> its sources. Roadie's print is the library entry roadie-drop
# (restructure plan Task 14); its job.yaml stages.select holds tolerance 30.0, remove_at
# [[60, 396]], keep_at [[470, 470]] and the instructions, which rebuild
# artifacts/selection-runs/roadie-tol30/selection.json byte for byte (measured in the
# repeatability baseline, research/verification/2026-11-16-repeatability/README.md). Oddie
# has no library entry or job yet, so only its legacy folder.
OWNER_SOURCES = {
    "roadie-tol30": OwnerSources(library="roadie-drop", job="roadie-drop",
                                 legacy="roadie-tol30"),
    "oddie": OwnerSources(library=None, job=None, legacy="oddie"),
}


@pytest.fixture(autouse=True)
def _library_outside_the_checkout(tmp_path_factory, monkeypatch):
    """No test reads or writes the checkout's prints/: tdmg job new's default library and
    tdmg finish's (and tdmg library check's and verify's) default prints folder are a
    fresh, empty temporary folder, and the jobs folder library check looks in is another.
    So finished prints and jobs in the checkout (prints/roadie-drop/, say) cannot change
    what a test sees. (The owner fixtures read the checkout's prints/ and jobs/ by their
    explicit paths, read only; see the module docstring.)"""
    library = tmp_path_factory.mktemp("prints-library")
    no_jobs = tmp_path_factory.mktemp("library-jobs")
    monkeypatch.setattr(tdmg.cli, "default_library", lambda: library)
    monkeypatch.setattr(tdmg.library, "default_prints_dir", lambda: library)
    monkeypatch.setattr(tdmg.library, "library_jobs_dir", lambda: no_jobs)


def parse_research_rows() -> dict:
    """Parse the kmeans_w rows and palettes from the Task 1 results.txt, and each name's
    selection_id from band-survival.txt (the same selections, same record folder)."""
    text = (RESEARCH / "results.txt").read_text(encoding="utf-8")
    ids = dict(re.findall(r"^== ([\w-]+): selection_id ([0-9a-f]{64})",
                          (RESEARCH / "band-survival.txt").read_text(encoding="utf-8"),
                          re.MULTILINE))
    out = {}
    for block in text.split("\n== ")[1:]:
        name = block.split(":", 1)[0]
        m = re.search(r"mask sha256 (\w+), cutout sha256 (\w+)", block)
        rows = {}
        for line in block.splitlines():
            f = line.split()
            if len(f) > 10 and f[0] == "kmeans_w" and f[1].isdigit():
                # columns: method N dE_mean dE_p95 pieces small small_px% times iters
                # identical label_sha256[:16] colors nearest_mean nearest_p95 not_nearest%
                rows[int(f[1])] = {"iters": int(f[8]), "sha": f[10], "not_nearest": f[14]}
            if len(f) > 2 and f[0] == "kmeans_w" and f[1].endswith(":"):
                n = int(f[1][:-1])
                rows[n]["palette"] = re.findall(r"(#[0-9a-f]{6}) ([\d.]+%)", line)
        out[name] = {"mask": m.group(1), "cutout": m.group(2), "rows": rows,
                     "selection_id": ids[name]}
    return out


@pytest.fixture(scope="session")
def research_rows():
    """parse_research_rows(), once per session."""
    return parse_research_rows()


# --- building an owner selection --------------------------------------------------------

class OwnerSelectionAbsent(Exception):
    """No source of the selection is present; the message names every path looked at."""


class OwnerSelectionDiffers(AssertionError):
    """A source is present, but none gives the recorded selection."""


@dataclass(frozen=True)
class BuiltSelection:
    folder: Path        # the selection folder, in out_dir
    source: str         # "library", "job" or "artifacts"
    path: Path          # the source folder it came from
    passed_over: tuple[str, ...]   # why earlier present sources were not used


def _sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _differs(folder: Path, want: dict) -> str | None:
    """Why the selection in folder is not the recorded one, or None."""
    record = json.loads((folder / "selection.json").read_bytes())
    if record.get("selection_id") != want["selection_id"]:
        return (f"its selection_id is {record.get('selection_id')}, not the recorded "
                f"{want['selection_id']}")
    for f, key in (("mask.png", "mask"), ("cutout.png", "cutout")):
        got = _sha16(folder / f)
        if got != want[key]:
            return f"its {f} has sha256[:16] {got}, not the recorded {want[key]}"
    return None


def _from_job_folder(folder: Path, out: Path) -> tuple[str, str | None]:
    """Build folder's selection (a library entry or a job) into out, as tdmg job run's
    select stage does. Returns ("absent", why) or ("built", None) or ("refused", why)."""
    if not (folder / JOB_FILE).is_file():
        return "absent", f"{folder / JOB_FILE} is not present"
    try:
        job = load_job(folder)
    except JobError as e:
        return "refused", str(e)
    image = folder / job["source"]["file"]
    if not image.is_file():
        return "absent", f"{image} is not present (git-ignored source images)"
    if "select" not in job["stages"]:
        return "refused", f"{folder / JOB_FILE} has no select stage"
    try:
        check_source(folder, job)
        _run_select(folder, job, job["stages"]["select"], {}, out, None)
    except (JobError, SelectionError) as e:
        return "refused", str(e)
    return "built", None


def _from_legacy(folder: Path, out: Path) -> tuple[str, str | None]:
    needed = ("selection.json", "mask.png", "cutout.png", "preview.png")
    missing = [f for f in needed if not (folder / f).is_file()]
    if missing:
        return "absent", (f"{folder} is not present or lacks {', '.join(missing)} "
                          "(git-ignored owner images)")
    out.mkdir()
    for f in needed:
        shutil.copyfile(folder / f, out / f)
    return "built", None


def build_owner_selection(name: str, out_dir: Path, want: dict, *, repo: Path = ROOT,
                          sources: dict[str, OwnerSources] = OWNER_SOURCES
                          ) -> BuiltSelection:
    """The owner selection `name`, built in out_dir (a new subfolder per source tried) from
    the first present source that gives the recorded one (`want`: selection_id, and the
    mask and cutout sha256[:16]). Reads repo/prints, repo/jobs and
    repo/artifacts/selection-runs only. Raises OwnerSelectionAbsent when no source is
    present, OwnerSelectionDiffers when present ones all give another selection."""
    s = sources[name]
    candidates = [
        ("library", s.library, repo / "prints", _from_job_folder),
        ("job", s.job, repo / "jobs", _from_job_folder),
        ("artifacts", s.legacy, repo / "artifacts" / "selection-runs", _from_legacy),
    ]
    absent, passed_over = [], []
    out_dir.mkdir(parents=True, exist_ok=True)
    for kind, entry, base, build in candidates:
        if entry is None:
            absent.append(f"{kind}: none is mapped for {name} (OWNER_SOURCES)")
            continue
        path = base / entry
        out = out_dir / f"{name}-{kind}"
        state, why = build(path, out)
        if state == "absent":
            absent.append(f"{kind}: {why}")
            continue
        why = why if state == "refused" else _differs(out, want)
        if why is not None:
            passed_over.append(f"{kind} source {path} was not used: {why}")
            continue
        for note in passed_over:
            warnings.warn(f"owner selection {name}: {note}; used the {kind} source {path}",
                          stacklevel=2)
        return BuiltSelection(out, kind, path, tuple(passed_over))
    if passed_over:
        raise OwnerSelectionDiffers(
            f"owner selection {name}: no source gives the selection recorded in "
            f"{RESEARCH.name} (the tests would test other images): "
            + "; ".join(passed_over) + ("; " + "; ".join(absent) if absent else ""))
    raise OwnerSelectionAbsent(f"owner selection {name}: no source is present: "
                               + "; ".join(absent))


@pytest.fixture(scope="session")
def owner_selection_dir(research_rows, tmp_path_factory):
    """A function name -> the owner selection's folder (selection.json, mask.png,
    cutout.png, preview.png), built once per session in a temporary folder
    (build_owner_selection). It skips when no source is present (the message names each
    path) and fails when present sources differ from the Task 1 record."""
    done: dict[str, tuple[str, object]] = {}

    def get(name):
        if name not in done:
            out = tmp_path_factory.mktemp(f"owner-{name}")
            try:
                done[name] = ("ok", build_owner_selection(name, out, research_rows[name]))
            except OwnerSelectionAbsent as e:
                done[name] = ("skip", str(e))
            except OwnerSelectionDiffers as e:
                done[name] = ("fail", str(e))
        state, value = done[name]
        if state == "skip":
            pytest.skip(value)
        if state == "fail":
            pytest.fail(value, pytrace=False)
        return value.folder
    return get


@pytest.fixture(scope="session")
def owner_selection(owner_selection_dir):
    """A function name -> (rgb (H, W, 3) uint8, mask (H, W) bool) for an owner selection,
    from owner_selection_dir (which skips or fails as it says)."""
    def load(name):
        d = owner_selection_dir(name)
        mask = np.array(Image.open(d / "mask.png")) == 255
        rgb = np.array(Image.open(d / "cutout.png").convert("RGBA"))[..., :3]
        return rgb, mask
    return load

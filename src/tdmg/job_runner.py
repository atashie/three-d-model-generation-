"""Running a job: `tdmg job run`, `tdmg job status`, `tdmg job set` and `tdmg job confirm`
(restructure plan Tasks 7 and 8; design docs/plans/2026-11-16-restructure-design.md
sections 3 and 4).

**Stage folders.** Each stage of the job's recipe runs into `jobs/NAME/<stage>/` (select,
flat, colors, colored_flat, slice), with the stage's own record (STAGE_RECORDS) written
last, exactly as the stage command writes it. Each stage is driven as its command drives
it (the _run_* functions below; tests/test_job_runner.py proves the files equal), with a
null parameter passed as "not given", never as a resolved default:
- select: SelectionSpec from instructions, alpha_min, tolerance (color_tolerance),
  remove_at and keep_at (lists of [x, y] made tuples; [] is no option); with a mask,
  select_from_mask on the job's mask file, else select_subject; then write_selection. The
  image is the job's source file, so the record's source name is its file name;
- flat: make_flat(select/, width_mm, thickness_mm, smooth_px=..., printer only if set);
- colors: make_colors with the rules and tdmg.colors.COLORS_PRINTER, as tdmg colors. The
  five keys tdmg colors takes as flags (COLOR_FLAG_KEYS) are passed as flags; the five it
  takes only from its config file (COLOR_CONFIG_KEYS: outline_color, merge,
  outline_width_mm, thin_lines, line_width_mm) are written to a config file
  (colors_config: canonical YAML of the set ones only, in a temporary folder) passed as
  config_path, and no file when none is set. So colors.json equals that of
  `tdmg colors SEL --width-mm W [flags] [--config FILE]` with FILE holding colors_config's
  bytes: its `settings.sources` says "flag" for the first five and "config" for the
  others that are set, and `settings.config_sha256` is the SHA-256 of colors_config's
  bytes (null without one);
- colored_flat: make_colored_flat(select/, colors/, thickness_mm, width_mm, printer);
- slice: make_slice on flat/ (R1), or make_color_slice on colored_flat/ (R2, face auto
  when null), with timeout_s, check_tree = not skip_tree_check, and the slicer folders.

**Input keys.** A stage's input key (stage_key) is the SHA-256 of the canonical JSON
(tdmg.records) of: KEY_SCHEMA, the recipe, the stage, its parameters as in job.yaml; the
SHA-256 of each upstream record it reads (STAGE_INPUTS: selection.json, colors.json,
flat.json, colored.json; these are byte-for-byte repeatable, research/verification/
2026-11-16-repeatability/README.md); the stage's algorithm ids (STAGE_ALGORITHMS); the
code fingerprint (code_fingerprint: the SHA-256 of every .py file of the tdmg package, by
its path in the package, and of the checkout's uv.lock when there is one); the SHA-256 of
the rule values (id, default, unit, range of every rule); and the SHA-256 of the profiles
it uses (the printer profile; for slice the OrcaSlicer pin, and the PrusaSlicer pin when
configured). The select stage adds the source image's and the mask's SHA-256; the slice
stage adds whether PrusaSlicer is configured (--prusaslicer-dir or $TDMG_PRUSASLICER_DIR),
since that turns F6.portability from UNKNOWN into a check. So a stage is stale when its
parameters, what it read, its algorithm, tdmg's code or its locked dependencies, a rule or
a profile changed. The fingerprint is of the files' bytes, so any edit to tdmg's code (a
comment too) or to uv.lock makes every stage of every job stale; the rerun is cheap when
it writes the same bytes, since a confirmation is bound to its files' hashes and stays
current. The bytes are this checkout's, so the same code checked out with other line ends
(Windows and macOS) gives another fingerprint. A dependency installed outside uv.lock is
not seen. `tdmg job run NAME --rerun STAGE` still reruns a stage on demand. Machine paths
are not part of a key. (tdmg.jobkey/2 keys had no fingerprint; every stage of a job keyed
by /2 is stale once, and runs again.)

**state.json** (STATE_SCHEMA, tdmg.jobstate/2) holds `{"schema", "stages": {stage: {"key":
..., "record_sha256": ...}}}`: the key each stage folder was last made with, and the
SHA-256 of the stage record job run found in it once the swap was done. It is canonical
JSON written with an atomic rename (tdmg.records.replace_file). A stage whose record's
bytes differ from record_sha256 is stale ("its record changed since tdmg job run wrote
it"), so a hand-edited record (a slice.json made to say PRINTABLE, say) is never taken as
done. The same job gives the same state.json bytes except for the slice stage's
record_sha256: slice.json holds G-code hashes, and G-code holds the time of slicing. So
Task 9's rebuild comparison must leave state.json out. A tdmg.jobstate/1 file (keys only,
from before) is still read; each of its stages is stale until it runs again, since its
record's hash was never stored.

**Reruns.** A stage runs when its folder has no record, when its key differs from
state.json's, when its record's algorithm or links disagree with this code and the
upstream records, or when --rerun names it. It runs into `<stage>.new/`. Once its record
exists: the stage's entry is removed from state.json (written), the old folder is renamed
to `<stage>.old/` and the new one to `<stage>/`, the old one deleted, and the new key
written. So whatever stops the swap leaves no key over the wrong folder; later stages keep
their entries, since their keys hold the hash of the upstream record they were made from.
A stage that fails before its record exists leaves its old folder and state.json as they
were. A run left half way is tidied by the next run: an `<stage>.old/` with no `<stage>/`
is put back, other `.old/` and `.new/` folders deleted.

**Outputs and source.** A stage is done only while every file its record's `outputs`
names is there with that SHA-256 (outputs_problem): a deleted or hand-edited output
(flat/model.stl, a G-code file) makes the stage stale, and job run makes it again. A hand
edit to the record itself makes it stale too (state.json's record_sha256). job status
checks the source image and mask against job.yaml (tdmg.jobs.check_source): a changed or
missing source makes the select stage stale, saying why, and job run refuses until it is
put back. These checks guard against accidental edits, and edits by an agent or a tool,
not against an adversary: state.json and job.yaml are plain files that can be edited too.

**Lock.** job run, job set and job confirm hold LOCK_FILE in the job folder (an exclusive
create, removed when done), so two of them cannot change a job at once.

**Status:** per stage done (record present, key current, record algorithm and links
agreeing, every earlier stage done), stale or not run; the verdict, algorithm and tdmg
version of a done stage; each confirmation, current or stale and why
(tdmg.confirmations.current_problem, computed on every status, so job run's status shows
it after a rerun); and what waits for the owner (unset required parameters, previews to
check with no current confirmation, a color plan that is not ready, stale confirmations).

**Confirm** (confirm, plan Task 8): records the owner's words for one subject, with the
date, the job revision and the covered hashes (tdmg.confirmations), appended to
job.yaml's confirmations through save_job, under the lock. With `corrects` (--corrects
N), the entry records that it corrects entry N, whose words were recorded wrongly: N is
kept, and is no longer current (tdmg.jobs, Confirmation entries). It refuses: blank words; a
date that is not YYYY-MM-DD or is after today; a subject the recipe has no stage for; a
stage not done (select for selection; colors, with a ready plan, for colors; every stage
for print); a covered file that differs from its record; for print, an unknown route, a
missing or unneeded face, a face that was not sliced, and a verdict that is not PRINTABLE
unless accept_not_certified (which is then recorded), and accept_not_certified when every
verdict is PRINTABLE; and a --corrects that is not an earlier entry of the same subject,
or one that is corrected already.

**Set** (set_parameters): STAGE.KEY=VALUE reads VALUE as YAML; `--text STAGE.KEY WORDS`
(texts) stores WORDS as a string exactly as given, with no YAML reading, so backslashes,
quotes, colons and line breaks stay as they are (the owner's words: select.instructions).
A parameter that does not take text refuses it, and select.mask takes a file, so not
--text.
"""

from __future__ import annotations

import copy
import datetime
import functools
import hashlib
import inspect
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

import tdmg.slicing
from tdmg import confirmations, jobs, paths
from tdmg.color_config import KEYS as COLOR_KEYS
from tdmg.color_slicing import (
    COLORSLICE_ALGORITHM,
    DEFAULT_FACE,
    FACES,
    NO_FACE_PRINTABLE,
    make_color_slice,
)
from tdmg.colored_flat import ALGORITHM as COLORFLAT_ALGORITHM
from tdmg.colored_flat import RECORD_NAME as COLORED_RECORD
from tdmg.colored_flat import make_colored_flat
from tdmg.colors import COLORS_ALGORITHM_VERSION, COLORS_PRINTER, ColorsError, make_colors
from tdmg.colors import RECORD_NAME as COLORS_RECORD
from tdmg.flat import FLAT_ALGORITHM_VERSION, FlatError, make_flat
from tdmg.jobs import JobError, check_not_linked, check_source, load_job
from tdmg.portability import PRUSA_ENV_VAR
from tdmg.profiles import load_printer
from tdmg.recipes import recipe
from tdmg.records import RecordError, canonical_json, replace_file
from tdmg.rules import load_rules
from tdmg.selection import ALGORITHM_VERSION as SELECTION_ALGORITHM
from tdmg.selection import (
    SelectionError,
    SelectionSpec,
    load_image,
    load_mask,
    select_from_mask,
    select_subject,
    write_selection,
)
from tdmg.slicer import SlicerError
from tdmg.slicing import PRINT_THIS, SLICE_ALGORITHM_VERSION, make_slice
from tdmg.slicing import RECORD_NAME as SLICE_RECORD

STATE_FILE = "state.json"
STATE_SCHEMA = "tdmg.jobstate/2"
OLD_STATE_SCHEMA = "tdmg.jobstate/1"         # keys only; read, never written
KEY_SCHEMA = "tdmg.jobkey/3"
LOCK_FILE = ".lock"
NEW_SUFFIX = ".new"
OLD_SUFFIX = ".old"
STAGE_RECORDS = {"select": "selection.json", "flat": "flat.json", "colors": COLORS_RECORD,
                 "colored_flat": COLORED_RECORD, "slice": SLICE_RECORD}
# The color keys tdmg colors takes as flags; the other tdmg.color_config keys it takes from
# its config file only.
COLOR_FLAG_KEYS = ("colors", "extract", "edges", "base", "outlines")
COLOR_CONFIG_KEYS = tuple(k for k in COLOR_KEYS if k not in COLOR_FLAG_KEYS)
COLORS_CONFIG_NAME = "colors-config.yaml"
FLAT_PRINTER = inspect.signature(make_flat).parameters["printer"].default
# What a stage may raise for a refused input or a failed write; the run stops there.
STAGE_ERRORS = (JobError, SelectionError, FlatError, ColorsError, SlicerError, RecordError,
                ValidationError, OSError)
DONE, STALE, NOT_RUN = "done", "stale", "not run"
MASK_CLEAR = ("none", "null", "~")
CONFIRM_NOTE = "confirmations: none"
CURRENT = "current"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- parameters to stage calls ----------------------------------------------------------

def colors_config(params: dict) -> bytes | None:
    """The config file the colors stage passes to make_colors: the set config-only keys
    (COLOR_CONFIG_KEYS) as canonical YAML (sorted keys, block style, ASCII, "\\n"), or None
    when none is set (no --config)."""
    values = {k: params[k] for k in COLOR_CONFIG_KEYS if params[k] is not None}
    if not values:
        return None
    return yaml.safe_dump(values, sort_keys=True, default_flow_style=False,
                          allow_unicode=False, width=jobs.YAML_WIDTH, indent=2,
                          line_break="\n").encode("ascii")


@dataclass(frozen=True)
class Machine:
    """What a run takes from this machine, not from job.yaml: the slicer folders (None:
    the stage's own default, $TDMG_ORCASLICER_DIR and $TDMG_PRUSASLICER_DIR)."""
    slicer_dir: Path | None = None
    prusaslicer_dir: Path | None = None

    def prusaslicer_configured(self) -> bool:
        """As tdmg.portability.locate_prusaslicer decides whether to run PrusaSlicer."""
        folder = (self.prusaslicer_dir if self.prusaslicer_dir is not None
                  else os.environ.get(PRUSA_ENV_VAR))
        return bool(folder)


def _run_select(folder: Path, job: dict, p: dict, inputs: dict, out: Path, machine) -> dict:
    spec = SelectionSpec(instructions=p["instructions"], alpha_min=p["alpha_min"],
                         color_tolerance=p["tolerance"],
                         remove_at=tuple(tuple(xy) for xy in p["remove_at"]),
                         keep_at=tuple(tuple(xy) for xy in p["keep_at"]))
    intake = load_image(folder / job["source"]["file"])
    if intake.file_sha256 != job["source"]["sha256"]:
        raise JobError(f"source file {job['source']['file']} changed while it was read")
    if p["mask"] is not None:
        sel = select_from_mask(intake, load_mask(folder / p["mask"], intake.rgba.shape[:2]),
                               spec)
    else:
        sel = select_subject(intake, spec)
    return write_selection(intake, sel, out)


def _run_flat(folder, job, p, inputs, out, machine) -> dict:
    chosen = {} if p["printer"] is None else {"printer": p["printer"]}  # else make_flat's
    return make_flat(inputs["select"], p["width_mm"], p["thickness_mm"], out,
                     smooth_px=p["smooth_px"], **chosen)


def _colors_error(e: ColorsError) -> ColorsError:
    """make_colors' message, naming job.yaml instead of the temporary config file and
    "command-line flags" (both are job.yaml stages.colors here)."""
    text = str(e).replace(f"config file {COLORS_CONFIG_NAME}", "job.yaml stages.colors")
    text = text.replace(COLORS_CONFIG_NAME, "job.yaml stages.colors")
    return ColorsError(text.replace("command-line flags", "job.yaml stages.colors"))


def _run_colors(folder, job, p, inputs, out, machine) -> dict:
    flags = {k: p[k] for k in COLOR_FLAG_KEYS}
    config = colors_config(p)
    kw = {"width_mm": p["width_mm"], "flags": flags, "rules": load_rules(),
          "printer": load_printer(COLORS_PRINTER)}
    try:
        if config is None:
            return make_colors(inputs["select"], out, config_path=None, **kw)
        with tempfile.TemporaryDirectory(prefix="tdmg-colors-") as tmp:
            path = Path(tmp) / COLORS_CONFIG_NAME
            path.write_bytes(config)
            return make_colors(inputs["select"], out, config_path=path, **kw)
    except ColorsError as e:
        raise _colors_error(e) from None


def _run_colored_flat(folder, job, p, inputs, out, machine) -> dict:
    return make_colored_flat(inputs["select"], inputs["colors"], out,
                             thickness_mm=p["thickness_mm"], width_mm=p["width_mm"],
                             printer=p["printer"])


def _run_slice(folder, job, p, inputs, out, machine) -> dict:
    kw = {"slicer_dir": machine.slicer_dir, "timeout_s": p["timeout_s"],
          "check_tree": not p["skip_tree_check"],
          "prusaslicer_dir": machine.prusaslicer_dir}
    if "colored_flat" in inputs:
        return make_color_slice(inputs["colored_flat"], out,
                                face=DEFAULT_FACE if p["face"] is None else p["face"], **kw)
    return make_slice(inputs["flat"], out, **kw)


RUNNERS = {"select": _run_select, "flat": _run_flat, "colors": _run_colors,
           "colored_flat": _run_colored_flat, "slice": _run_slice}
# The stage folders each stage reads (those in the recipe).
STAGE_INPUTS = {"select": (), "flat": ("select",), "colors": ("select",),
                "colored_flat": ("select", "colors"), "slice": ("flat", "colored_flat")}


def _inputs(job: dict, stage: str) -> tuple[str, ...]:
    stages = recipe(job["recipe"]).stages
    return tuple(s for s in STAGE_INPUTS[stage] if s in stages)


def stage_algorithms(job: dict, stage: str) -> list[str]:
    """The algorithm ids of a stage; the first is the one its record names."""
    if stage == "slice":
        if "colored_flat" in recipe(job["recipe"]).stages:
            return [COLORSLICE_ALGORITHM, SLICE_ALGORITHM_VERSION]   # glue plates: slice
        return [SLICE_ALGORITHM_VERSION]
    return [{"select": SELECTION_ALGORITHM, "flat": FLAT_ALGORITHM_VERSION,
             "colors": COLORS_ALGORITHM_VERSION,
             "colored_flat": COLORFLAT_ALGORITHM}[stage]]


# --- input keys and state.json ----------------------------------------------------------

def rules_sha256() -> str:
    """SHA-256 of every rule's id, default, unit and range (the values a stage uses)."""
    values = {rid: {"default": r.default, "unit": r.unit,
                    "range": None if r.range is None else list(r.range)}
              for rid, r in load_rules().items()}
    return _sha(canonical_json(values))


def package_fingerprint(package_dir: Path, lock: Path | None) -> str:
    """SHA-256 of {path in the package: SHA-256} of every .py file under package_dir,
    with "uv.lock" -> the lock file's SHA-256 (None without one), as canonical JSON."""
    files = {p.relative_to(package_dir).as_posix(): _sha(p.read_bytes())
             for p in sorted(package_dir.rglob("*.py")) if p.is_file()}
    return _sha(canonical_json({"package": files,
                                "uv.lock": None if lock is None else _sha(lock.read_bytes())}))


@functools.cache
def code_fingerprint() -> str:
    """The code fingerprint of the running tdmg (module docstring, Input keys): its package
    folder as imported (a checkout's src/tdmg or a wheel's), and the checkout's uv.lock when
    there is one. Computed once per process: the code that runs is the code imported."""
    lock = None if paths.REPO_ROOT is None else paths.REPO_ROOT / "uv.lock"
    return package_fingerprint(Path(tdmg.__file__).resolve().parent,
                               lock if lock is not None and lock.is_file() else None)


def _model_sha(model) -> str:
    return _sha(canonical_json(model.model_dump(mode="json")))


def _printer_sha(printer_id: str) -> str | None:
    """The profile's SHA-256; None when it cannot be loaded (the stage then refuses it)."""
    try:
        return _model_sha(load_printer(printer_id))
    except (OSError, ValueError, yaml.YAMLError):
        return None


def stage_profiles(job: dict, stage: str, machine: Machine) -> dict:
    p = job["stages"][stage]
    if stage == "flat":
        printer = p["printer"] or FLAT_PRINTER
        return {"printer": printer, "printer_sha256": _printer_sha(printer)}
    if stage in ("colors", "colored_flat"):
        # colored_flat without a printer takes the plan's, which is COLORS_PRINTER.
        printer = (p["printer"] if stage == "colored_flat" else None) or COLORS_PRINTER
        return {"printer": printer, "printer_sha256": _printer_sha(printer)}
    if stage == "slice":
        # Looked up at call time, so a test's replacement pin is the one hashed.
        out = {"orcaslicer_pin_sha256": _model_sha(tdmg.slicing.load_pin())}
        if machine.prusaslicer_configured():
            out["prusaslicer_pin_sha256"] = _model_sha(tdmg.slicing.load_prusa_pin())
        return out
    return {}


def stage_key(job: dict, stage: str, record_hashes: dict[str, str], machine: Machine,
              rules: str | None = None) -> str | None:
    """The stage's input key (module docstring); None when an upstream record it reads is
    missing (record_hashes: stage -> SHA-256 of its record file)."""
    inputs = {s: record_hashes.get(s) for s in _inputs(job, stage)}
    if any(v is None for v in inputs.values()):
        return None
    body = {"schema": KEY_SCHEMA, "recipe": job["recipe"], "stage": stage,
            "params": job["stages"][stage], "inputs": inputs,
            "algorithms": stage_algorithms(job, stage), "code_sha256": code_fingerprint(),
            "rules_sha256": rules_sha256() if rules is None else rules,
            "profiles": stage_profiles(job, stage, machine)}
    if stage == "select":
        mask = job["source"]["mask"]
        body["source"] = {"sha256": job["source"]["sha256"],
                          "mask_sha256": None if mask is None else mask["sha256"]}
    if stage == "slice":
        body["prusaslicer_configured"] = machine.prusaslicer_configured()
    return _sha(canonical_json(body))


def _hex(v) -> bool:
    return isinstance(v, str) and jobs.HEX64.fullmatch(v) is not None


def load_state(folder: Path, job: dict) -> dict:
    """state.json, checked, as tdmg.jobstate/2; an empty state when there is none yet. A
    tdmg.jobstate/1 file's entries get record_sha256 None: not stored, so stale."""
    path = folder / STATE_FILE
    if not path.exists():
        return {"schema": STATE_SCHEMA, "stages": {}}
    try:
        state = json.loads(path.read_bytes())
    except (ValueError, UnicodeDecodeError):
        state = None
    stages = recipe(job["recipe"]).stages
    ok = (isinstance(state, dict) and set(state) == {"schema", "stages"}
          and state["schema"] in (OLD_STATE_SCHEMA, STATE_SCHEMA)
          and isinstance(state["stages"], dict))
    if ok:
        old = state["schema"] == OLD_STATE_SCHEMA
        want = {"key"} if old else {"key", "record_sha256"}
        ok = all(s in stages and isinstance(v, dict) and set(v) == want and _hex(v["key"])
                 and (old or _hex(v["record_sha256"]))
                 for s, v in state["stages"].items())
    if not ok:
        raise JobError(f"{path} is not a {STATE_SCHEMA} file; delete it to run every stage "
                       "again")
    if state["schema"] == OLD_STATE_SCHEMA:
        state = {"schema": STATE_SCHEMA,
                 "stages": {s: {"key": v["key"], "record_sha256": None}
                            for s, v in state["stages"].items()}}
    return state


def _write_state(folder: Path, state: dict) -> None:
    """Write state.json as tdmg.jobstate/2. An entry read from a tdmg.jobstate/1 file (no
    record hash) is left out: its stage stays stale until it runs again, as it was."""
    stages = {s: v for s, v in state["stages"].items() if v["record_sha256"] is not None}
    replace_file(folder, STATE_FILE, canonical_json({"schema": STATE_SCHEMA,
                                                     "stages": stages}))


# --- records and their links ----------------------------------------------------------------

@dataclass(frozen=True)
class Record:
    raw: bytes
    data: dict

    @property
    def sha256(self) -> str:
        return _sha(self.raw)


def _record(folder: Path, stage: str) -> Record | None:
    """The stage's record, or None when it is missing or is not a JSON object."""
    path = folder / stage / STAGE_RECORDS[stage]
    if not path.is_file():
        return None
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return Record(raw, data) if isinstance(data, dict) else None


def _get(data, *path):
    for p in path:
        if not isinstance(data, dict):
            return None
        data = data.get(p)
    return data


def links_problem(stage: str, rec: dict, upstream: dict[str, Record]) -> str | None:
    """Why the record's links disagree with the upstream records now on disk, or None:
    flat.json's selection.selection_id; colors.json's input.selection_json_sha256;
    colored.json's identity.selection_id and identity.colors_id; slice.json's
    links.flat_record_sha256 and links.selection_id (R1) or links.colored_record_sha256
    (R2)."""
    checks = []
    if stage == "flat":
        checks.append((("selection", "selection_id"),
                       _get(upstream["select"].data, "selection_id")))
    elif stage == "colors":
        checks.append((("input", "selection_json_sha256"), upstream["select"].sha256))
    elif stage == "colored_flat":
        checks.append((("identity", "selection_id"),
                       _get(upstream["select"].data, "selection_id")))
        checks.append((("identity", "colors_id"), _get(upstream["colors"].data, "colors_id")))
    elif stage == "slice" and "colored_flat" in upstream:
        checks.append((("links", "colored_record_sha256"), upstream["colored_flat"].sha256))
    elif stage == "slice":
        checks.append((("links", "flat_record_sha256"), upstream["flat"].sha256))
        checks.append((("links", "selection_id"),
                       _get(upstream["flat"].data, "selection", "selection_id")))
    for path, want in checks:
        got = _get(rec, *path)
        if got != want:
            return (f"its record's {'.'.join(path)} does not match the "
                    f"{'/'.join(sorted(upstream))} record now on disk")
    return None


def outputs_problem(folder: Path, stage: str, rec: dict) -> str | None:
    """Why the files the record's `outputs` names (name in the stage folder -> SHA-256)
    are not all there with those hashes, or None. A record without outputs (colors.json of
    a plan that is not ready) names none."""
    outputs = rec.get("outputs")
    if not isinstance(outputs, dict):
        return None
    for name, digest in sorted(outputs.items()):
        path = folder / stage / name
        if not path.is_file():
            return f"its output {name} is missing"
        try:
            data = path.read_bytes()
        except OSError as e:
            return f"cannot read its output {name} ({e.strerror or e})"
        if _sha(data) != digest:
            return f"its output {name} changed since the stage made it"
    return None


def _judge(folder: Path, job: dict, stage: str, rec: Record | None, key: str | None,
           state: dict, upstream: dict[str, Record], forced: bool = False
           ) -> tuple[str, str]:
    """(DONE, "") or (STALE / NOT_RUN, why), from this stage alone."""
    if rec is None:
        return NOT_RUN, ""
    expected = stage_algorithms(job, stage)[0]
    if rec.data.get("algorithm") != expected:
        return STALE, (f"made by algorithm {rec.data.get('algorithm')}; this tdmg has "
                       f"{expected}")
    if key is None:
        return STALE, "an earlier stage has no record"
    entry = state["stages"].get(stage, {})
    if entry.get("key") != key:
        return STALE, ("its parameters, inputs, tdmg's code (or uv.lock), rules or profiles "
                       "changed since it ran, or it was not run by tdmg job run")
    if entry["record_sha256"] is None:
        return STALE, ("its record's hash was not stored (state.json from an older tdmg); "
                       "the next run reruns it")
    if entry["record_sha256"] != rec.sha256:
        return STALE, "its record changed since tdmg job run wrote it"
    problem = links_problem(stage, rec.data, upstream) or outputs_problem(folder, stage,
                                                                          rec.data)
    if problem:
        return STALE, problem
    if forced:
        return STALE, "--rerun asked for it"
    return DONE, ""


# --- status -------------------------------------------------------------------------------

@dataclass
class StageStatus:
    stage: str
    state: str                       # DONE, STALE or NOT_RUN
    note: str = ""                   # why stale or not run
    record: dict | None = None       # the stage record, when done


@dataclass
class ConfirmationStatus:
    number: int                      # 1-based, in job.yaml order
    entry: dict
    problem: str | None              # why stale; None when current
    stages_stale: bool = False       # a stage it rests on is not done: a rerun decides
    chosen_face: str | None = None   # tdmg's preferred face, when the owner printed another
    corrected_by: int | None = None  # the later entry that corrects this one (never current)

    @property
    def current(self) -> bool:
        return self.problem is None


def _same_print(entry: dict, route: str | None, face: str | None) -> bool:
    """Whether a print entry is of this route (None: any) and face (None: any)."""
    return ((route is None or entry["route"] == route)
            and (face is None or entry["face"] == face))


@dataclass
class Status:
    name: str
    recipe: str
    revision: int
    stages: list[StageStatus]
    unset: list[str]
    waits: list[str] = field(default_factory=list)
    confirmations: list[ConfirmationStatus] = field(default_factory=list)

    @property
    def all_done(self) -> bool:
        return all(s.state == DONE for s in self.stages)

    def current(self, subject: str, route: str | None = None, face: str | None = None
                ) -> bool:
        """Whether a current confirmation of `subject` exists; for print, of this route
        and face when given."""
        return any(c.current and c.entry["subject"] == subject
                   and (subject != "print" or _same_print(c.entry, route, face))
                   for c in self.confirmations)

    def matched(self, c: ConfirmationStatus) -> bool:
        """Whether a current confirmation stands in for `c`: same subject, and for print
        the same route and face."""
        e = c.entry
        return any(o.current and o.entry["subject"] == e["subject"]
                   and (e["subject"] != "print" or (o.entry["route"], o.entry["face"])
                        == (e["route"], e["face"]))
                   for o in self.confirmations)


def job_status(folder: str | Path, machine: Machine | None = None, *,
               job: dict | None = None) -> Status:
    """Each stage's state, without running anything."""
    folder = Path(folder)
    machine = Machine() if machine is None else machine
    job = load_job(folder) if job is None else job
    state = load_state(folder, job)
    rules = rules_sha256()
    try:
        check_source(folder, job)
        source_problem = None
    except JobError as e:
        source_problem = str(e)
    stages = recipe(job["recipe"]).stages
    source_stage = "select" if "select" in stages else stages[0]
    records: dict[str, Record] = {}
    out = []
    earlier_done = True
    for stage in stages:
        rec = _record(folder, stage)
        upstream = {s: records[s] for s in _inputs(job, stage) if s in records}
        key = stage_key(job, stage, {s: r.sha256 for s, r in upstream.items()}, machine,
                        rules)
        verdict, note = _judge(folder, job, stage, rec, key, state, upstream)
        if source_problem and stage == source_stage:
            verdict = STALE if verdict == DONE else verdict
            why = f"{source_problem}; tdmg job run refuses until it is put back"
            note = f"{why}; {note}" if note else why
        elif rec is None and (folder / stage).exists():
            note = "its folder has no record (an interrupted run)"
        elif rec is None and (folder / f"{stage}{OLD_SUFFIX}").is_dir():
            note = (f"an interrupted swap left {stage}{OLD_SUFFIX}; the next run restores "
                    "and reruns it")
        if verdict == DONE and not earlier_done:
            verdict, note = STALE, "an earlier stage is not done"
        st = StageStatus(stage, verdict, note, rec.data if verdict == DONE else None)
        if rec is not None:
            records[stage] = rec
        earlier_done = earlier_done and verdict == DONE
        out.append(st)
    status = Status(job["name"], job["recipe"], job["revision"], out, jobs.unset_required(job))
    by = {s.stage: s for s in out}
    slice_rec = records["slice"].data if "slice" in records else {}
    preferred = slice_rec.get("preferred_face") if isinstance(slice_rec, dict) else None
    corrected_by = {}
    for i, entry in enumerate(job["confirmations"], start=1):
        if entry.get(jobs.CORRECTS_KEY) is not None:
            corrected_by.setdefault(entry[jobs.CORRECTS_KEY], i)
    for i, entry in enumerate(job["confirmations"], start=1):
        subject = entry["subject"]
        rests_on = [s.stage for s in out] if subject == "print" else \
            [jobs.SUBJECT_STAGE[subject]]
        chosen = None
        if subject == "print" and entry["face"] and preferred and preferred != entry["face"]:
            chosen = preferred
        later = corrected_by.get(i)
        problem = (f"corrected by confirmation {later}" if later is not None
                   else confirmations.current_problem(folder, job, entry))
        status.confirmations.append(ConfirmationStatus(
            i, entry, problem, stages_stale=any(by[s].state != DONE for s in rests_on),
            chosen_face=chosen, corrected_by=later))
    status.waits = _waits(job, status)
    return status


def _set_hint(name: str, key: str) -> str:
    return f"set {key}: tdmg job set {name} {key}=VALUE"


def _waits(job: dict, status: Status) -> list[str]:
    """What waits for the owner."""
    waits = [_set_hint(job["name"], key) for key in status.unset]
    by = {s.stage: s for s in status.stages}
    for s in status.stages:
        if s.state != DONE:
            continue
        if s.stage == "select":
            if not status.current("selection"):
                waits.append("check select/preview.png: is this the subject?")
        elif s.stage == "colors":
            if s.record["ready"]:
                if not status.current("colors"):
                    waits.append("check colors/regions.png: are these the colors?")
            else:
                waits.append(f"the color plan is not ready ({s.record['not_ready_reason']}): "
                             "choose merges from colors/regions.png and set them, e.g. "
                             f"tdmg job set {job['name']} \"colors.merge=[[FROM, INTO]]\"")
    # The print instructions wait until any current print confirmation answers them (any
    # route, any face): the owner has printed. A face other than tdmg's choice is shown on
    # the confirmation's own line ("printed face X; tdmg chose Y").
    rec = by["slice"].record if "slice" in by and by["slice"].state == DONE else None
    colored = rec is not None and "faces" in rec
    if rec is not None and not status.current("print"):
        if colored:                             # a colored slice: its own instructions
            waits.append(f"to print (files in colored_flat/): {rec['print']}"
                         if rec["print"] != NO_FACE_PRINTABLE else rec["print"])
        elif rec["verdict"] == "PRINTABLE":
            waits.append(f"to print (model.stl is in flat/): {PRINT_THIS}")
        else:
            waits.append("not PRINTABLE: do not print it; see slice/slice.json")
    # A stale confirmation waits only while no current one stands in for it: the same
    # subject and, for print, the same route and face (Status.matched). The stale entry
    # stays in job.yaml for good: it is the owner's words.
    # A corrected entry waits for nothing: its correction stands in for it.
    for c in status.confirmations:
        if not c.current and c.corrected_by is None and not status.matched(c):
            waits.append(f"confirmation {c.number} ({confirmations.describe(c.entry)}) is "
                         "stale: ask the owner to confirm again (tdmg job confirm)")
    return waits


def stage_line(s: StageStatus) -> str:
    """'stage: done - verdict ... (algorithm, tdmg version)', 'stage: stale (why)' or
    'stage: not run'."""
    head = f"{s.stage}: {s.state}"
    if s.state != DONE:
        return head + (f" ({s.note})" if s.note else "")
    rec = s.record
    if s.stage == "select":
        r = rec["result"]
        detail = (f"{r['status']}, {r['selected_px']} px in {len(r['pieces_px'])} piece(s), "
                  f"{len(r['warnings'])} warning(s)")
    elif s.stage == "colors":
        detail = (f"{len(rec['palette'])} colors, ready" if rec["ready"]
                  else f"NOT READY: {rec['not_ready_reason']}")
    elif s.stage == "slice" and "faces" in rec:
        faces = ", ".join(f"face {face} {rec['faces'][face]['verdict']}" for face in FACES
                          if face in rec["faces"])
        chosen = rec["preferred_face"] if rec["params"]["face"] == "auto" else None
        detail = (f"{faces}; chosen: {'none' if chosen is None else 'face ' + chosen}")
        route = rec["glue"]["route"]
        if route is not None:
            detail += f"; glue route {'printable' if route['printable'] else 'not printable'}"
    else:
        detail = f"verdict {rec['verdict']}"
    return f"{head} - {detail} ({rec.get('algorithm')}, tdmg {rec.get('tdmg_version')})"


def confirmation_line(c: ConfirmationStatus) -> str:
    """'1. print (ams, face down), 2026-11-16, revision 4, "words": current' or
    '...: STALE (why)'."""
    e = c.entry
    words = json.dumps(e["owner_said"], ensure_ascii=True)
    if not c.current:
        state = f"STALE ({c.problem})"
    elif c.stages_stale:
        state = f"{CURRENT} (stages stale: a rerun decides)"
    else:
        state = CURRENT
    chosen = f"; printed face {e['face']}; tdmg chose {c.chosen_face}" if c.chosen_face \
        else ""
    corrects = (f", corrects confirmation {e[jobs.CORRECTS_KEY]}"
                if e.get(jobs.CORRECTS_KEY) is not None else "")
    return (f"{c.number}. {confirmations.describe(e)}, {e['date']}, revision "
            f"{e['revision']}, {words}{corrects}: {state}{chosen}")


def status_lines(status: Status) -> list[str]:
    lines = [f"job {status.name}: recipe {status.recipe}, revision {status.revision}"]
    lines += [f"  {stage_line(s)}" for s in status.stages]
    if status.confirmations:
        lines.append("confirmations:")
        lines += [f"  {confirmation_line(c)}" for c in status.confirmations]
    else:
        lines.append(CONFIRM_NOTE)
    if status.waits:
        lines.append("waits for the owner:")
        lines += [f"  {w}" for w in status.waits]
    return lines


# --- running ------------------------------------------------------------------------------

@dataclass
class RunEvent:
    stage: str
    action: str                  # "ran", "kept", "waits" or "failed"
    message: str = ""
    error: tuple[str, ...] = ()  # a failed stage: its exception's class and base names


@contextmanager
def job_lock(folder: Path) -> Iterator[None]:
    """Hold folder/LOCK_FILE (an exclusive create) while changing a job; removed after."""
    path = folder / LOCK_FILE
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
    except FileExistsError:
        raise JobError(f"job {folder.name} is locked: {path} exists. Another tdmg job run or "
                       "job set is using the job, or one stopped without removing the "
                       f"file; if none is running, delete {path}") from None
    try:
        os.write(fd, f"pid {os.getpid()}\n".encode("ascii"))
    finally:
        os.close(fd)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _plain_folder(path: Path) -> None:
    if path.is_symlink() or path.is_junction():
        raise JobError(f"{path} is a link (symlink or junction); a job's stage folders must "
                       "be plain folders")
    if path.exists() and not path.is_dir():
        raise JobError(f"{path} is a file, not a stage folder; remove it")


def _remove(path: Path) -> None:
    _plain_folder(path)
    if path.exists():
        shutil.rmtree(path)


def _tidy(folder: Path, stage: str) -> Path:
    """Undo what an interrupted run left: an `<stage>.old` with no `<stage>` is put back
    (the swap stopped half way); any other `<stage>.old` and any `<stage>.new` are
    deleted. Returns `<stage>.new`, now absent."""
    final, new, old = (folder / stage, folder / f"{stage}{NEW_SUFFIX}",
                       folder / f"{stage}{OLD_SUFFIX}")
    for path in (final, new, old):
        _plain_folder(path)
    if not final.exists() and old.exists():
        old.rename(final)                # the old results, put back
    _remove(old)
    _remove(new)
    return new


def _swap(folder: Path, stage: str) -> None:
    final, new, old = (folder / stage, folder / f"{stage}{NEW_SUFFIX}",
                       folder / f"{stage}{OLD_SUFFIX}")
    if final.exists():
        final.rename(old)
    new.rename(final)
    _remove(old)


def _stops_after(stage: str, rec: dict) -> str | None:
    """Why the next stages wait after this stage's record, or None."""
    if stage == "colors" and not rec["ready"]:
        return f"the color plan is not ready: {rec['not_ready_reason']}"
    return None


def run_job(folder: str | Path, machine: Machine | None = None, *,
            rerun: Iterable[str] = ()) -> tuple[list[RunEvent], Status]:
    """Run every stage that is not done, in order (module docstring); return what happened
    and the status after. `rerun` names stages to run again even when done. Stops at a
    stage whose required parameters are unset, at a stage that fails (refused input or a
    failed write: its old folder and state stay), and after a color plan that is not
    ready. Holds the job's lock (job_lock)."""
    folder = Path(folder)
    machine = Machine() if machine is None else machine
    check_not_linked(folder)
    load_job(folder)                    # refuse a bad job before taking the lock
    with job_lock(folder):
        job = load_job(folder)          # read again under the lock: what this run uses
        stages = recipe(job["recipe"]).stages
        rerun = set(rerun)
        unknown = sorted(rerun - set(stages))
        if unknown:
            raise JobError(f"--rerun {unknown[0]}: recipe {job['recipe']} has no such "
                           f"stage (stages: {', '.join(stages)})")
        events = _run_locked(folder, job, machine, rerun)
    return events, job_status(folder, machine, job=job)


def _run_locked(folder: Path, job: dict, machine: Machine, rerun: set[str]
                ) -> list[RunEvent]:
    check_source(folder, job)
    state = load_state(folder, job)
    unset = jobs.unset_required(job)
    rules = rules_sha256()
    events: list[RunEvent] = []
    stages = recipe(job["recipe"]).stages
    for stage in stages:
        _tidy(folder, stage)
    records: dict[str, Record] = {}
    for i, stage in enumerate(stages):
        missing = [k for k in unset if k.startswith(f"{stage}.")]
        if missing:
            events.append(RunEvent(stage, "waits", f"{', '.join(missing)} not set"))
            break
        upstream = {s: records[s] for s in _inputs(job, stage)}
        key = stage_key(job, stage, {s: r.sha256 for s, r in upstream.items()}, machine,
                        rules)
        rec = _record(folder, stage)
        verdict, _ = _judge(folder, job, stage, rec, key, state, upstream, stage in rerun)
        if verdict == DONE:
            events.append(RunEvent(stage, "kept"))
        else:
            new = _tidy(folder, stage)
            inputs = {s: folder / s for s in _inputs(job, stage)}
            try:
                RUNNERS[stage](folder, job, job["stages"][stage], inputs, new, machine)
                if not (new / STAGE_RECORDS[stage]).is_file():
                    raise JobError(f"{stage} wrote no {STAGE_RECORDS[stage]}")
            except STAGE_ERRORS as e:
                _remove(new)
                events.append(RunEvent(stage, "failed", _error_text(e),
                                       _error_names(e)))
                break
            # No key may stand over a folder it does not describe, whatever stops the swap.
            if state["stages"].pop(stage, None) is not None:
                _write_state(folder, state)
            try:
                _swap(folder, stage)
            except OSError as e:
                events.append(RunEvent(stage, "failed", (
                    f"could not replace {folder / stage} ({_error_text(e)}): close programs "
                    f"using {stage}/; the new results are discarded on the next run"),
                    _error_names(e)))
                break
            rec = _record(folder, stage)
            if rec is None:
                events.append(RunEvent(stage, "failed", f"{stage} record unreadable"))
                break
            state["stages"][stage] = {"key": key, "record_sha256": rec.sha256}
            _write_state(folder, state)
            events.append(RunEvent(stage, "ran"))
        records[stage] = rec
        why = _stops_after(stage, rec.data)
        if why:
            events.append(RunEvent(stages[i + 1] if i + 1 < len(stages) else stage, "waits",
                                   why))
            break
    return events


def _error_names(e: Exception) -> tuple[str, ...]:
    """The names of the exception's class and its bases (RunEvent.error), so a reader can
    tell an OSError of any kind, or a SlicerError, from a refusal of the input."""
    return tuple(c.__name__ for c in type(e).__mro__)


def _error_text(e: Exception) -> str:
    if isinstance(e, ValidationError):
        err = e.errors()[0]
        return f"{err['loc'][0]}: {err['msg']}"
    if isinstance(e, OSError):
        where = f": {e.filename}" if e.filename else ""
        return f"{e.strerror or e}{where}"
    return str(e)


# --- tdmg job set -------------------------------------------------------------------------

VALUE_HELP = ("values are read as YAML: 60, 0.5, true, null (clears a parameter), text, "
              "or a flow list such as [[60, 396], [470, 470]]; quote text that would read "
              "as a number, true/false or null")


def yaml_value(value) -> str:
    """A value as job set reads it back: YAML flow style, one line (60.0, null, [[1, 2]])."""
    text = yaml.safe_dump(value, default_flow_style=True, width=jobs.YAML_WIDTH,
                          allow_unicode=False).strip()
    return text[:-3].rstrip() if text.endswith("\n...") else text


def parse_value(raw: str):
    """One parameter value, by job.yaml's strict YAML rules (tdmg.jobs): plain decimal
    numbers, true/false, null or ~ (null), text, and flow lists ([[60, 396]])."""
    if raw.strip() == "":
        raise JobError(f"an empty value; write null to clear a parameter ({VALUE_HELP})")
    try:
        return yaml.load(raw, Loader=jobs._StrictLoader)
    except yaml.YAMLError as e:
        raise JobError(f"value {raw!a} is not valid YAML ({e.problem or e}); {VALUE_HELP}"
                       ) from None


def parse_assignment(text: str, job: dict) -> tuple[str, str, str]:
    """(stage, key, raw value) from STAGE.KEY=VALUE, with the stage and key known."""
    target, eq, raw = text.partition("=")
    if not eq or "." not in target:
        raise JobError(f"{text!a} is not STAGE.KEY=VALUE")
    stage, key = parse_target(target, job)
    return stage, key, raw


def parse_target(target: str, job: dict) -> tuple[str, str]:
    """(stage, key) from STAGE.KEY, with the stage and key known."""
    stage, dot, key = target.partition(".")
    if not dot:
        raise JobError(f"{target!a} is not STAGE.KEY")
    stages = recipe(job["recipe"]).stages
    if stage not in stages:
        raise JobError(f"recipe {job['recipe']} has no stage {stage!a} (stages: "
                       f"{', '.join(stages)})")
    fields = jobs.stage_fields(job["recipe"], stage)
    if key not in fields:
        raise JobError(f"stage {stage} has no parameter {key!a} (parameters: "
                       f"{', '.join(fields)})")
    return stage, key


# A --text value: stored as it is, never read as YAML.
@dataclass(frozen=True)
class Text:
    words: str


TEXT_HELP = ("--text stores text as given; give a number, true/false, null or a list as "
             "STAGE.KEY=VALUE")


def set_parameters(folder: str | Path, assignments: list[str],
                   texts: Iterable[tuple[str, str]] = ()) -> tuple[dict, bool]:
    """Apply STAGE.KEY=VALUE assignments and (STAGE.KEY, WORDS) texts (--text: WORDS
    stored as a string, exactly, with no YAML reading); return (the job, whether it
    changed).

    `select.mask=PATH` gives the job an owner-corrected mask (tdmg.jobs.set_mask; PATH is a
    file on this machine, copied into source/), and `select.mask=none` (or null) removes it;
    it must be the only assignment. Every other change is checked and written in one
    revision by tdmg.jobs.save_job (types, the stage's range checks). Holds the job's lock
    (job_lock)."""
    folder = Path(folder)
    check_not_linked(folder)
    job = load_job(folder)
    texts = list(texts)
    if not assignments and not texts:
        raise JobError("give at least one STAGE.KEY=VALUE or --text STAGE.KEY WORDS")
    parsed = [parse_assignment(a, job) for a in assignments]
    for target, words in texts:
        stage, key = parse_target(target, job)
        if (stage, key) == ("select", "mask"):
            raise JobError("select.mask takes a file: select.mask=PATH (or select.mask=none), "
                           "not --text")
        parsed.append((stage, key, Text(words)))
    targets = [f"{s}.{k}" for s, k, _ in parsed]
    repeated = sorted({t for t in targets if targets.count(t) > 1})
    if repeated:
        raise JobError(f"{', '.join(repeated)} given more than once")
    with job_lock(folder):
        return _set_locked(folder, parsed, targets)


def _set_locked(folder: Path, parsed, targets) -> tuple[dict, bool]:
    job = load_job(folder)
    if "select.mask" in targets:
        if len(parsed) > 1:
            raise JobError("set select.mask on its own (it copies a file into source/)")
        raw = parsed[0][2].strip()      # never a Text: set_parameters refuses that
        if not raw:
            raise JobError("select.mask needs a value: select.mask=PATH (a black/white mask "
                           "file), or select.mask=none to remove the mask")
        mask = None if raw.lower() in MASK_CLEAR else Path(raw)
        new = jobs.set_mask(folder, mask)
        return new, new["revision"] != job["revision"]
    new = copy.deepcopy(job)
    for stage, key, raw in parsed:
        new["stages"][stage][key] = raw.words if isinstance(raw, Text) else parse_value(raw)
    try:
        saved = jobs.save_job(folder, new)
    except JobError as e:
        text = str(e)
        if any(isinstance(raw, Text) and f"stages.{s}.{k}" in text for s, k, raw in parsed):
            text += f" ({TEXT_HELP})"
        elif any(isinstance(new["stages"][s][k], str) for s, k, _ in parsed):
            text += f" ({VALUE_HELP})"
        raise JobError(text) from None
    return saved, saved["revision"] != job["revision"]


# --- tdmg job confirm ---------------------------------------------------------------------

def confirm_date(value: str | None, today: datetime.date | None = None) -> str:
    """The confirmation's date: `value` (YYYY-MM-DD, not after today), or today's local
    date. Local, not UTC: the owner gives their words on their own calendar day. "Today"
    is this machine's date (its clock and time zone), so a machine set wrong can refuse a
    real date or default to a wrong one."""
    today = datetime.date.today() if today is None else today
    if value is None:
        return today.isoformat()
    problem = jobs.date_problem(value)
    if problem:
        raise JobError(f"--date {problem}")
    if datetime.date.fromisoformat(value) > today:
        raise JobError(f"--date {value} is after today ({today.isoformat()}); give the date "
                       "the owner said it")
    return value


def confirm(folder: str | Path, subject: str, owner_said: str, *, date: str | None = None,
            route: str | None = None, face: str | None = None,
            accept_not_certified: bool = False, machine: Machine | None = None,
            corrects: int | None = None) -> tuple[dict, dict]:
    """Record the owner's confirmation of `subject`; return (the job, the new entry).

    `owner_said` is the owner's own words, verbatim; nothing else may be passed. The entry
    (tdmg.jobs module docstring) is appended to job.yaml's confirmations with save_job,
    under the job's lock; refusals are listed in this module's docstring. `machine` matters
    only for whether PrusaSlicer is configured (part of the slice stage's key). `corrects`:
    the number of the earlier entry of this subject whose words were recorded wrongly; that
    entry is kept and is no longer current."""
    folder = Path(folder)
    machine = Machine() if machine is None else machine
    problem = jobs.owner_words_problem(owner_said)
    if problem:
        raise JobError(f"--owner-said {problem}")
    day = confirm_date(date)
    check_not_linked(folder)
    job = load_job(folder)
    if subject not in jobs.subjects(job["recipe"]):
        raise JobError(f"--subject {subject!a}: a {job['recipe']} job confirms "
                       f"{', '.join(jobs.subjects(job['recipe']))}")
    if subject != "print" and (route is not None or face is not None
                               or accept_not_certified):
        raise JobError("--route, --face and --accept-not-certified are for --subject print")
    with job_lock(folder):
        return _confirm_locked(folder, subject, owner_said, day, route, face,
                               accept_not_certified, machine, corrects)


def _confirm_locked(folder: Path, subject: str, owner_said: str, day: str,
                    route: str | None, face: str | None, accept: bool, machine: Machine,
                    corrects: int | None = None) -> tuple[dict, dict]:
    job = load_job(folder)                  # read again under the lock
    if corrects is not None:
        problem = jobs.correction_problem(corrects, subject, job["confirmations"])
        if problem:
            raise JobError(f"--corrects {problem}")
    check_source(folder, job)
    status = job_status(folder, machine, job=job)
    by = {s.stage: s for s in status.stages}
    need = [s.stage for s in status.stages] if subject == "print" else \
        [jobs.SUBJECT_STAGE[subject]]
    not_done = [by[s] for s in need if by[s].state != DONE]
    if not_done:
        s = not_done[0]
        raise JobError(f"cannot confirm {subject}: stage {s.stage} is {s.state}"
                       + (f" ({s.note})" if s.note else "") + "; run tdmg job run first")
    if subject == "colors" and not by["colors"].record["ready"]:
        raise JobError("cannot confirm colors: the color plan is not ready "
                       f"({by['colors'].record['not_ready_reason']})")
    entry = {"subject": subject, "owner_said": owner_said, "date": day,
             "revision": job["revision"]}
    if corrects is not None:
        entry[jobs.CORRECTS_KEY] = corrects
    if subject != "print":
        entry["covers"] = confirmations.subject_covers(folder, subject)
    else:
        route = confirmations.default_route(job["recipe"]) if route is None else route
        cover = confirmations.print_cover(folder, job, route, face)
        uncertified = sorted(k for k, v in cover.verdicts.items() if v != jobs.PRINTABLE)
        if uncertified and not accept:
            raise JobError(
                f"not PRINTABLE: {', '.join(f'{k} {cover.verdicts[k]}' for k in uncertified)}"
                ". Do not print it; if the owner printed it anyway, or chooses to, give "
                "--accept-not-certified (it is recorded)")
        if accept and not uncertified:
            raise JobError("every verdict is PRINTABLE: --accept-not-certified is not "
                           "needed; leave it out")
        entry.update(covers=cover.covers, route=route,
                     face=face if route in jobs.FACED_ROUTES else None,
                     slice_id=cover.slice_id, verdicts=cover.verdicts,
                     accept_not_certified=bool(uncertified))
    new = copy.deepcopy(job)
    new["confirmations"].append(entry)
    return jobs.save_job(folder, new), entry

"""Running a job: `tdmg job run`, `tdmg job status` and `tdmg job set` (restructure plan
Task 7; design docs/plans/2026-11-16-restructure-design.md section 3).

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
- colors: make_colors with rules and the bambu-a1 profile, as tdmg colors. The five keys
  tdmg colors takes as flags (COLOR_FLAG_KEYS) are passed as flags; the three it takes only
  from its config file (outline_color, merge, outline_width_mm) are written to a config
  file (colors_config: canonical YAML of the set ones only, in a temporary folder) passed as
  config_path, and no file when none is set. So colors.json equals that of `tdmg colors
  SEL --width-mm W [flags] [--config FILE]` with FILE holding colors_config's bytes: its
  `settings.sources` says "flag" for the first five and "config" for the other three, and
  `settings.config_sha256` is the SHA-256 of colors_config's bytes (null without one);
- colored_flat: make_colored_flat(select/, colors/, thickness_mm, width_mm, printer);
- slice: make_slice on flat/ (R1), or make_color_slice on colored_flat/ (R2, face auto
  when null), with timeout_s, check_tree = not skip_tree_check, and the slicer folders.

**Input keys.** A stage's input key is the SHA-256 of the canonical JSON (tdmg.records) of:
KEY_SCHEMA, the recipe, the stage, its parameters as in job.yaml, and the input keys of
every stage before it (so a change reruns that stage and every later one). The select
stage adds the source image's and the mask's SHA-256; the slice stage adds whether
PrusaSlicer is configured (--prusaslicer-dir or $TDMG_PRUSASLICER_DIR), since that turns
F6.portability from UNKNOWN into a check. Machine paths are not part of a key: the slicers
are verified against their pins. The code version is not part of a key either: after a
code change, rerun a stage by changing it, or delete its folder.

**state.json** (STATE_SCHEMA) holds `{"schema", "stages": {stage: {"key": ...}}}`, the key
each stage folder was last made with, as canonical JSON written with an atomic rename
(tdmg.records.replace_file). It holds no hashes of outputs (slice records hold G-code
hashes, and G-code holds the time of slicing), so the same job gives the same bytes.

**Reruns.** A stage runs when its folder has no record, or when its key differs from
state.json's. It runs into `<stage>.new/`; only after its record exists is the old
folder renamed to `<stage>.old/`, the new one to `<stage>/`, the old one deleted and
state.json written. A stage that fails leaves its old folder and state.json as they were.
A run left half way (an `<stage>.new/` or `<stage>.old/`) is tidied up by the next run:
an `<stage>.old/` with no `<stage>/` is put back first.

**Status:** per stage done (record present, key current and every earlier stage done),
stale (record present, but a parameter or an earlier stage changed since) or not run;
the verdict of a done stage; confirmations (none yet: tdmg job confirm is plan Task 8);
and what waits for the owner (unset required parameters, previews to check, a color plan
that is not ready).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from tdmg import jobs
from tdmg.color_config import KEYS as COLOR_KEYS
from tdmg.color_slicing import DEFAULT_FACE, FACES, NO_FACE_PRINTABLE, make_color_slice
from tdmg.colored_flat import RECORD_NAME as COLORED_RECORD
from tdmg.colored_flat import make_colored_flat
from tdmg.colors import RECORD_NAME as COLORS_RECORD
from tdmg.colors import ColorsError, make_colors
from tdmg.flat import FlatError, make_flat
from tdmg.jobs import JobError, check_not_linked, check_source, load_job
from tdmg.portability import PRUSA_ENV_VAR
from tdmg.profiles import load_printer
from tdmg.recipes import recipe
from tdmg.records import RecordError, canonical_json, replace_file
from tdmg.rules import load_rules
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
from tdmg.slicing import PRINT_THIS, make_slice
from tdmg.slicing import RECORD_NAME as SLICE_RECORD

STATE_FILE = "state.json"
STATE_SCHEMA = "tdmg.jobstate/1"
KEY_SCHEMA = "tdmg.jobkey/1"
NEW_SUFFIX = ".new"
OLD_SUFFIX = ".old"
STAGE_RECORDS = {"select": "selection.json", "flat": "flat.json", "colors": COLORS_RECORD,
                 "colored_flat": COLORED_RECORD, "slice": SLICE_RECORD}
# The color keys tdmg colors takes as flags; the other tdmg.color_config keys it takes from
# its config file only.
COLOR_FLAG_KEYS = ("colors", "extract", "edges", "base", "outlines")
COLOR_CONFIG_KEYS = tuple(k for k in COLOR_KEYS if k not in COLOR_FLAG_KEYS)
COLORS_PRINTER = "bambu-a1"                 # tdmg colors' profile
COLORS_CONFIG_NAME = "colors-config.yaml"
# What a stage may raise for a refused input or a failed write; the run stops there.
STAGE_ERRORS = (JobError, SelectionError, FlatError, ColorsError, SlicerError, RecordError,
                ValidationError, OSError)
DONE, STALE, NOT_RUN = "done", "stale", "not run"
MASK_CLEAR = ("none", "null", "~")
CONFIRM_NOTE = "confirmations: none (tdmg job confirm is not built yet)"


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


def _run_colors(folder, job, p, inputs, out, machine) -> dict:
    flags = {k: p[k] for k in COLOR_FLAG_KEYS}
    config = colors_config(p)
    kw = {"width_mm": p["width_mm"], "flags": flags, "rules": load_rules(),
          "printer": load_printer(COLORS_PRINTER)}
    if config is None:
        return make_colors(inputs["select"], out, config_path=None, **kw)
    with tempfile.TemporaryDirectory(prefix="tdmg-colors-") as tmp:
        path = Path(tmp) / COLORS_CONFIG_NAME
        path.write_bytes(config)
        return make_colors(inputs["select"], out, config_path=path, **kw)


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
# The stage folders each stage reads.
STAGE_INPUTS = {"select": (), "flat": ("select",), "colors": ("select",),
                "colored_flat": ("select", "colors"), "slice": ("flat", "colored_flat")}


# --- input keys and state.json ----------------------------------------------------------

def input_keys(job: dict, machine: Machine) -> dict[str, str]:
    """Each stage's input key, in recipe order (module docstring)."""
    keys: dict[str, str] = {}
    for stage in recipe(job["recipe"]).stages:
        body = {"schema": KEY_SCHEMA, "recipe": job["recipe"], "stage": stage,
                "params": job["stages"][stage], "before": dict(keys)}
        if stage == "select":
            mask = job["source"]["mask"]
            body["source"] = {"sha256": job["source"]["sha256"],
                              "mask_sha256": None if mask is None else mask["sha256"]}
        if stage == "slice":
            body["prusaslicer_configured"] = machine.prusaslicer_configured()
        keys[stage] = _sha(canonical_json(body))
    return keys


def load_state(folder: Path, job: dict) -> dict:
    """state.json, checked; an empty state when there is none yet."""
    path = folder / STATE_FILE
    if not path.exists():
        return {"schema": STATE_SCHEMA, "stages": {}}
    try:
        state = json.loads(path.read_bytes())
    except (ValueError, UnicodeDecodeError):
        state = None
    stages = recipe(job["recipe"]).stages
    ok = (isinstance(state, dict) and set(state) == {"schema", "stages"}
          and state["schema"] == STATE_SCHEMA and isinstance(state["stages"], dict)
          and all(s in stages and isinstance(v, dict) and set(v) == {"key"}
                  and isinstance(v["key"], str) and jobs.HEX64.fullmatch(v["key"])
                  for s, v in state["stages"].items()))
    if not ok:
        raise JobError(f"{path} is not a {STATE_SCHEMA} file; delete it to run every stage "
                       "again")
    return state


def _write_state(folder: Path, state: dict) -> None:
    replace_file(folder, STATE_FILE, canonical_json(state))


# --- status -------------------------------------------------------------------------------

@dataclass
class StageStatus:
    stage: str
    state: str                       # DONE, STALE or NOT_RUN
    note: str = ""                   # why stale or not run
    record: dict | None = None       # the stage record, when done


@dataclass
class Status:
    name: str
    recipe: str
    revision: int
    stages: list[StageStatus]
    unset: list[str]
    waits: list[str] = field(default_factory=list)

    @property
    def all_done(self) -> bool:
        return all(s.state == DONE for s in self.stages)


def _record(folder: Path, stage: str) -> dict | None:
    path = folder / stage / STAGE_RECORDS[stage]
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_bytes())
    except (ValueError, UnicodeDecodeError):
        return None


def job_status(folder: str | Path, machine: Machine | None = None, *,
               job: dict | None = None) -> Status:
    """Each stage's state, without running anything."""
    folder = Path(folder)
    machine = Machine() if machine is None else machine
    job = load_job(folder) if job is None else job
    keys = input_keys(job, machine)
    state = load_state(folder, job)
    out = []
    earlier_done = True
    for stage in recipe(job["recipe"]).stages:
        rec = _record(folder, stage)
        if rec is None:
            note = ("its folder has no record (an interrupted run)"
                    if (folder / stage).exists() else "")
            st = StageStatus(stage, NOT_RUN, note)
        elif state["stages"].get(stage, {}).get("key") != keys[stage]:
            st = StageStatus(stage, STALE, "its parameters or an earlier stage changed "
                                           "since it ran")
        elif not earlier_done:
            st = StageStatus(stage, STALE, "an earlier stage is not done")
        else:
            st = StageStatus(stage, DONE, record=rec)
        earlier_done = earlier_done and st.state == DONE
        out.append(st)
    status = Status(job["name"], job["recipe"], job["revision"], out, jobs.unset_required(job))
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
            waits.append("check select/preview.png: is this the subject?")
        elif s.stage == "colors":
            if s.record["ready"]:
                waits.append("check colors/regions.png: are these the colors?")
            else:
                waits.append(f"the color plan is not ready ({s.record['not_ready_reason']}): "
                             "choose merges from colors/regions.png and set them, e.g. "
                             f"tdmg job set {job['name']} \"colors.merge=[[FROM, INTO]]\"")
    if "slice" in by and by["slice"].state == DONE:
        rec = by["slice"].record
        if "faces" in rec:                      # a colored slice: its own instructions
            waits.append(f"to print (files in colored_flat/): {rec['print']}"
                         if rec["print"] != NO_FACE_PRINTABLE else rec["print"])
        elif rec["verdict"] == "PRINTABLE":
            waits.append(f"to print (model.stl is in flat/): {PRINT_THIS}")
        else:
            waits.append("not PRINTABLE: do not print it; see slice/slice.json")
    return waits


def stage_line(s: StageStatus) -> str:
    """'stage: done - verdict ...', 'stage: stale (why)' or 'stage: not run'."""
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
    return f"{head} - {detail}"


def status_lines(status: Status) -> list[str]:
    lines = [f"job {status.name}: recipe {status.recipe}, revision {status.revision}"]
    lines += [f"  {stage_line(s)}" for s in status.stages]
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
    (the swap stopped half way, and state.json still holds that folder's key); any other
    `<stage>.old` and any `<stage>.new` are deleted. Returns `<stage>.new`, now absent."""
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


def run_job(folder: str | Path, machine: Machine | None = None
            ) -> tuple[list[RunEvent], Status]:
    """Run every stage that is not done, in order (module docstring); return what happened
    and the status after. Stops at a stage whose required parameters are unset, at a stage
    that fails (refused input or a failed write: its old folder and state stay), and after a
    color plan that is not ready."""
    folder = Path(folder)
    machine = Machine() if machine is None else machine
    check_not_linked(folder)
    job = load_job(folder)
    check_source(folder, job)
    keys = input_keys(job, machine)
    state = load_state(folder, job)
    unset = jobs.unset_required(job)
    events: list[RunEvent] = []
    stages = recipe(job["recipe"]).stages
    for stage in stages:
        _tidy(folder, stage)
    for i, stage in enumerate(stages):
        missing = [k for k in unset if k.startswith(f"{stage}.")]
        if missing:
            events.append(RunEvent(stage, "waits", f"{', '.join(missing)} not set"))
            break
        rec = _record(folder, stage)
        if rec is not None and state["stages"].get(stage, {}).get("key") == keys[stage]:
            events.append(RunEvent(stage, "kept"))
        else:
            new = _tidy(folder, stage)
            inputs = {s: folder / s for s in STAGE_INPUTS[stage] if s in stages[:i]}
            try:
                RUNNERS[stage](folder, job, job["stages"][stage], inputs, new, machine)
                if not (new / STAGE_RECORDS[stage]).is_file():
                    raise JobError(f"{stage} wrote no {STAGE_RECORDS[stage]}")
            except STAGE_ERRORS as e:
                _remove(new)
                events.append(RunEvent(stage, "failed", _error_text(e)))
                break
            _swap(folder, stage)
            state["stages"][stage] = {"key": keys[stage]}
            _write_state(folder, state)
            rec = _record(folder, stage)
            events.append(RunEvent(stage, "ran"))
        why = _stops_after(stage, rec)
        if why:
            events.append(RunEvent(stages[i + 1] if i + 1 < len(stages) else stage, "waits",
                                   why))
            break
    return events, job_status(folder, machine, job=job)


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
    stage, dot, key = target.partition(".")
    if not eq or not dot:
        raise JobError(f"{text!a} is not STAGE.KEY=VALUE")
    stages = recipe(job["recipe"]).stages
    if stage not in stages:
        raise JobError(f"recipe {job['recipe']} has no stage {stage!a} (stages: "
                       f"{', '.join(stages)})")
    fields = jobs.stage_fields(job["recipe"], stage)
    if key not in fields:
        raise JobError(f"stage {stage} has no parameter {key!a} (parameters: "
                       f"{', '.join(fields)})")
    return stage, key, raw


def set_parameters(folder: str | Path, assignments: list[str]) -> tuple[dict, bool]:
    """Apply STAGE.KEY=VALUE assignments; return (the job, whether it changed).

    `select.mask=PATH` gives the job an owner-corrected mask (tdmg.jobs.set_mask; PATH is a
    file on this machine, copied into source/), and `select.mask=none` (or null) removes it;
    it must be the only assignment. Every other change is checked and written in one
    revision by tdmg.jobs.save_job (types, the stage's range checks)."""
    folder = Path(folder)
    job = load_job(folder)
    if not assignments:
        raise JobError("give at least one STAGE.KEY=VALUE")
    parsed = [parse_assignment(a, job) for a in assignments]
    targets = [f"{s}.{k}" for s, k, _ in parsed]
    repeated = sorted({t for t in targets if targets.count(t) > 1})
    if repeated:
        raise JobError(f"{', '.join(repeated)} given more than once")
    if "select.mask" in targets:
        if len(parsed) > 1:
            raise JobError("set select.mask on its own (it copies a file into source/)")
        raw = parsed[0][2]
        mask = None if raw.strip().lower() in MASK_CLEAR else Path(raw)
        new = jobs.set_mask(folder, mask)
        return new, new["revision"] != job["revision"]
    new = copy.deepcopy(job)
    for stage, key, raw in parsed:
        new["stages"][stage][key] = parse_value(raw)
    try:
        saved = jobs.save_job(folder, new)
    except JobError as e:
        text = str(e)
        if any(isinstance(new["stages"][s][k], str) for s, k, _ in parsed):
            text += f" ({VALUE_HELP})"
        raise JobError(text) from None
    return saved, saved["revision"] != job["revision"]

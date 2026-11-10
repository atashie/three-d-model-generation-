"""tdmg slice: slice a tdmg flat output with the pinned OrcaSlicer (S9, F6).

docs/plans/2026-11-10-slicer-check.md, Decisions 6-8, as amended by the measurements in
research/verification/2026-11-10-orcaslicer-windows/ (README and its addendum):
- the argument form is exactly the measured one, without --debug, so the slicer writes
  slicer.log only on errors; it is copied when it exists and log_written records that;
- the allowed layer counts come from the flat record's thickness and the located
  process profile (tdmg.slicer.expected_layer_counts).

The record's verdict combines the flat record's checks, minus its placeholder F6.slicer,
with the F6 checks of this run, and requires all of them. It stays NOT CERTIFIED while
F3.thin_regions (no policy yet) and F6.portability (no second slicer) are UNKNOWN.
"""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from pathlib import Path

from tdmg import __version__
from tdmg.checks import CheckResult, verdict
from tdmg.flat import FLAT_REQUIRED_CHECKS
from tdmg.flat import RECORD_SCHEMA as FLAT_SCHEMA
from tdmg.records import (
    RecordError,
    canonical_json,
    check_output_dir,
    environment,
    record_text,
    write_outputs,
)
from tdmg.rules import load_rules
from tdmg.slicer import (
    GCODE_NAME,
    STATS_NAME,
    TIMEOUT_RULE,
    Slicer,
    SlicerError,
    decode_exit,
    expected_layer_counts,
    f6_checks,
    gcode_hashes,
    load_pin,
    locate,
    platform_key,
    run_slicer,
    slicer_args,
)

RECORD_SCHEMA = "tdmg.slice/1"
SLICE_ALGORITHM_VERSION = "slice-1"
RECORD_NAME = "slice.json"
LOG_NAME = "slicer.log"
SLICE_REQUIRED_EXTRA = frozenset({"F6.slicer_exit", "F6.gcode_present", "F6.layer_count",
                                  "F6.single_object", "F6.portability"})
SLICE_REQUIRED_CHECKS = (FLAT_REQUIRED_CHECKS - {"F6.slicer"}) | SLICE_REQUIRED_EXTRA
# The command as recorded: placeholders, so the record holds no path from this machine.
COMMAND_TEMPLATE = ["<orca-slicer.exe>", *slicer_args(
    Path("<model.stl>"), {k: Path(f"<{k}.json>") for k in ("machine", "process", "filament")},
    Path("<outdir>"), Path(f"<{LOG_NAME}>"))]
APP_TREE_NOTE = ("as pinned; the full app tree is verified by scripts/setup_orcaslicer.py "
                 "and its --verify-only, not on every run")
CERTIFICATION = ("NOT CERTIFIED while F3.thin_regions (no thin-region policy yet) and "
                 "F6.portability (second slicer, PrusaSlicer, not run) are UNKNOWN; "
                 "every check of flat.json and this run is required")
REVIEW = ("Open plate_1.gcode in a G-code preview (for example OrcaSlicer's or Bambu "
          "Studio's) and check the layers and the first layer. Time and weight are the "
          "slicer's estimates for the A1 0.20 mm Standard and PLA Basic profiles, not "
          "measurements. " + CERTIFICATION + ".")


def slicer_command(slicer: Slicer) -> list[str]:
    """The program to run: the verified exe (tests replace this with the fake slicer)."""
    return [str(slicer.exe)]


def _timeout(timeout_s, rules) -> dict:
    if timeout_s is None:
        return {"value": rules[TIMEOUT_RULE].default, "rule": TIMEOUT_RULE}
    try:
        value = float(timeout_s)
    except (TypeError, ValueError):
        raise SlicerError(f"timeout_s must be a number of seconds, not {timeout_s!r}") from None
    if not (math.isfinite(value) and value > 0):
        raise SlicerError(f"timeout_s must be finite and above 0, not {timeout_s!r}")
    return {"value": value, "rule": None}


def _read_flat(flat_dir: Path) -> tuple[dict, bytes]:
    """flat.json and model.stl's bytes, checked against each other. SlicerError if not."""
    path = flat_dir / "flat.json"
    try:
        record = json.loads(path.read_bytes())
    except FileNotFoundError:
        raise SlicerError(f"{path} is missing; slice a tdmg flat output folder") from None
    except (OSError, ValueError) as err:
        raise SlicerError(f"cannot read {path}: {err}") from None
    if not isinstance(record, dict) or record.get("schema") != FLAT_SCHEMA:
        found = record.get("schema") if isinstance(record, dict) else None
        raise SlicerError(f"{path}: schema is {found!r}, not {FLAT_SCHEMA!r}")
    for key, ok in (("flat_id", isinstance(record.get("flat_id"), str)),
                    ("params.thickness_mm", isinstance(record.get("params"), dict)
                     and isinstance(record["params"].get("thickness_mm"), (int, float))),
                    ("outputs.model.stl", isinstance(record.get("outputs"), dict)
                     and isinstance(record["outputs"].get("model.stl"), str)),
                    ("checks", isinstance(record.get("checks"), list))):
        if not ok:
            raise SlicerError(f"{path}: {key} is missing or not valid")
    try:
        stl = (flat_dir / "model.stl").read_bytes()
    except OSError as err:
        raise SlicerError(f"cannot read {flat_dir / 'model.stl'}: {err}") from None
    actual = hashlib.sha256(stl).hexdigest()
    if actual != record["outputs"]["model.stl"]:
        raise SlicerError(f"{flat_dir / 'model.stl'} has sha256 {actual}, which does not "
                          f"match flat.json ({record['outputs']['model.stl']}): it changed "
                          "after tdmg flat; run tdmg flat again")
    return record, stl


def _flat_checks(record: dict) -> list[CheckResult]:
    """The flat record's checks, minus its F6.slicer placeholder."""
    try:
        return [CheckResult(**c) for c in record["checks"] if c.get("id") != "F6.slicer"]
    except TypeError as err:
        raise SlicerError(f"flat.json: a check is not valid: {err}") from None


def make_slice(flat_dir, out_dir, slicer_dir=None, timeout_s=None) -> dict:
    """Slice a tdmg flat output folder and write plate_1.gcode, the statistics, the log
    (when the slicer wrote one) and slice.json, last.

    timeout_s None takes the default of rule slicer.orca.timeout_s. A refused input, an
    unusable output folder or an unverified slicer raises SlicerError with nothing
    written. A check that FAILs (including a failed slice) still writes the record.

    slice_id is a SHA-256 of the canonical JSON of the algorithm, the flat_id, the
    model.stl hash, the pinned slicer (version, exe, library and app-tree hashes), the
    three profile hashes and the command template. The timeout is not part of it: it can
    stop a run but does not change what a completed run writes. The platform and the
    environment are not part of it either; they are recorded beside it.
    """
    flat_dir = Path(flat_dir)
    rules = load_rules()
    timeout = _timeout(timeout_s, rules)
    flat, stl = _read_flat(flat_dir)
    previous = _flat_checks(flat)
    try:
        create_folder = check_output_dir(out_dir)
    except RecordError as err:
        raise SlicerError(str(err)) from None
    pin = load_pin()
    slicer = locate(slicer_dir, pin)
    try:
        process = json.loads(slicer.profiles["process"].read_bytes())
    except (OSError, ValueError) as err:
        raise SlicerError(f"cannot read {slicer.profiles['process']}: {err}") from None
    thickness = float(flat["params"]["thickness_mm"])
    allowed = expected_layer_counts(thickness, process)

    with tempfile.TemporaryDirectory(prefix="tdmg-slice-") as tmp:
        work = Path(tmp) / "work"
        work.mkdir()
        model = Path(tmp) / "model.stl"
        model.write_bytes(stl)              # the bytes whose hash was just checked
        run = run_slicer(slicer_command(slicer), model, slicer.profiles, work,
                         timeout["value"])
        checks, stats = f6_checks(run, allowed, pin)
        files = {}
        for name in (GCODE_NAME, STATS_NAME):
            if (run.out_dir / name).is_file():
                files[name] = (run.out_dir / name).read_bytes()
        log_written = run.log_path.is_file()
        if log_written:
            files[LOG_NAME] = run.log_path.read_bytes()

    if run.timed_out:               # no code to decode; keep the platform's decoding rule
        exit_code = {"raw": None, "signed": None, "name": None,
                     "decoding": decode_exit(0, platform_key(), pin)["decoding"]}
    else:
        exit_code = decode_exit(run.returncode, platform_key(), pin)
    all_checks = previous + checks
    verified = slicer.verified
    slicer_identity = {"version": pin.version, "exe_sha256": verified["exe_sha256"],
                       "libraries": verified["libraries"],
                       "app_tree_sha256": pin.app_tree.sha256}
    identity = {"algorithm": SLICE_ALGORITHM_VERSION, "flat_id": flat["flat_id"],
                "model_stl_sha256": flat["outputs"]["model.stl"],
                "slicer": slicer_identity,
                "profiles": {k: v["sha256"] for k, v in verified["profiles"].items()},
                "command": COMMAND_TEMPLATE}
    record = {
        "schema": RECORD_SCHEMA, "tdmg_version": __version__,
        "algorithm": SLICE_ALGORITHM_VERSION,
        "slice_id": hashlib.sha256(canonical_json(identity)).hexdigest(),
        "links": {"flat_id": flat["flat_id"],
                  "model_stl_sha256": flat["outputs"]["model.stl"],
                  "selection_id": (flat.get("selection") or {}).get("selection_id")},
        "params": {"timeout_s": timeout, "thickness_mm": thickness,
                   "expected_layer_counts": sorted(allowed)},
        "slicer": {"name": pin.name, "version": pin.version, "pin": pin.id,
                   **{k: v for k, v in slicer_identity.items() if k != "version"},
                   "app_tree_note": APP_TREE_NOTE, "profiles": verified["profiles"],
                   "platform": platform_key()},
        "command": COMMAND_TEMPLATE,
        "exit": {**exit_code, "timed_out": run.timed_out},
        "stats": stats,
        "checks": [c.as_dict() for c in all_checks],
        "verdict": verdict(all_checks, SLICE_REQUIRED_CHECKS),
        "certification": CERTIFICATION,
        "gcode": gcode_hashes(files[GCODE_NAME]) if GCODE_NAME in files else None,
        "stderr_tail": run.stderr,
        "log_written": log_written,
        "outputs": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        "environment": environment(),
        "review": REVIEW,
    }
    try:
        data = record_text(record)
    except (ValueError, UnicodeEncodeError) as err:
        raise SlicerError(f"the record cannot be stored as strict JSON: {err}") from None
    try:
        write_outputs(out_dir, files, RECORD_NAME, data, create_folder=create_folder)
    except RecordError as err:
        raise SlicerError(str(err)) from None
    return record


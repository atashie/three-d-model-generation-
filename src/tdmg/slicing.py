"""tdmg slice: slice a tdmg flat output with the pinned OrcaSlicer (S9, F6).

docs/plans/2026-11-10-slicer-check.md, Decisions 6-8, as amended by the measurements in
research/verification/2026-11-10-orcaslicer-windows/ (README and its addendum):
- the argument form is exactly the measured one, without --debug, so the slicer writes
  slicer.log only on errors; it is copied when it exists and log_written records that;
- the allowed layer counts come from the flat record's thickness and the process
  profile (tdmg.slicer.expected_layer_counts).

The record's verdict combines the flat record's checks, minus its placeholder F6.slicer,
with the F6 checks of this run, and requires all of them. The certification line names
the required checks that are not PASS. Today F3.thin_regions (no policy yet) and
F6.portability (no second slicer) are always UNKNOWN, so the verdict is NOT CERTIFIED.

Check-to-use gaps: the STL and the three profiles are read once, hashed, and the
slicer runs on copies of exactly those bytes in a temporary folder. The exe and its
libraries are hashed by locate but run from the install, so a change between the hash
and the run is not detected; the install folder is assumed to be the user's own.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import re
import tempfile
from pathlib import Path

from tdmg import __version__
from tdmg.checks import CheckResult, verdict
from tdmg.flat import FLAT_REQUIRED_CHECKS, flat_identity
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
    PROFILE_KINDS,
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
FAILED_GCODE_NAME = GCODE_NAME + ".failed"   # G-code from a run that did not exit cleanly
SLICE_REQUIRED_EXTRA = frozenset({"F6.slicer_exit", "F6.gcode_present", "F6.layer_count",
                                  "F6.single_object", "F6.portability"})
SLICE_REQUIRED_CHECKS = (FLAT_REQUIRED_CHECKS - {"F6.slicer"}) | SLICE_REQUIRED_EXTRA
STATUSES = ("PASS", "FAIL", "UNKNOWN")
HEX64 = re.compile(r"[0-9a-f]{64}")
# The command as recorded: placeholders, so the record holds no path from this machine.
COMMAND_TEMPLATE = ["<orca-slicer.exe>", *slicer_args(
    Path("<model.stl>"), {k: Path(f"<{k}.json>") for k in PROFILE_KINDS},
    Path("<outdir>"), Path(f"<{LOG_NAME}>"))]
APP_TREE_NOTE = ("as pinned; the full app tree is verified by scripts/setup_orcaslicer.py "
                 "and its --verify-only, not on every run")
DO_NOT_PRINT = "a check FAILed: do not print this G-code"
REVIEW = ("Open plate_1.gcode in a G-code preview (for example OrcaSlicer's or Bambu "
          "Studio's) and check the layers and the first layer. Time and weight are the "
          "slicer's estimates for the A1 0.20 mm Standard and PLA Basic profiles, not "
          "measurements. G-code from a run that did not exit cleanly is kept as "
          f"{FAILED_GCODE_NAME}; do not print it. Every check of flat.json and of this run "
          "is required: while F3.thin_regions has no policy and F6.portability has no second "
          "slicer (PrusaSlicer), both stay UNKNOWN and the verdict is NOT CERTIFIED.")


def slicer_command(slicer: Slicer) -> list[str]:
    """The program to run: the verified exe (tests replace this with the fake slicer)."""
    return [str(slicer.exe)]


def certification(checks: list[CheckResult], required: set[str] | frozenset[str]) -> str:
    """"PRINTABLE", or "NOT CERTIFIED: " and each required check that is not PASS.

    Checks are named with their status in check order; a required check that is absent
    is named "missing" at the end.
    """
    if verdict(checks, set(required)) == "PRINTABLE":
        return "PRINTABLE"
    named = [f"{c.id} {c.status}" for c in checks if c.id in required and c.status != "PASS"]
    present = {c.id for c in checks}
    named += [f"{cid} missing" for cid in sorted(set(required) - present)]
    return "NOT CERTIFIED: " + ", ".join(named)


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


def _is_hex64(value) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _real(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def _read_flat(flat_dir: Path) -> tuple[dict, bytes, bytes]:
    """flat.json's record and bytes, and model.stl's bytes, checked. SlicerError if not.

    flat_id is recomputed with flat.flat_identity from the record's algorithm, mask hash
    and params, so an edited thickness (or any other parameter) with the old id is
    refused. The inherited checks are not part of flat_id; slice_id pins them through
    the record's hash instead.
    """
    path = flat_dir / "flat.json"
    try:
        raw = path.read_bytes()
        record = json.loads(raw)
    except FileNotFoundError:
        raise SlicerError(f"{path} is missing; slice a tdmg flat output folder") from None
    except (OSError, ValueError) as err:
        raise SlicerError(f"cannot read {path}: {err}") from None
    if not isinstance(record, dict) or record.get("schema") != FLAT_SCHEMA:
        found = record.get("schema") if isinstance(record, dict) else None
        raise SlicerError(f"{path}: schema is {found!r}, not {FLAT_SCHEMA!r}")
    selection = record.get("selection") if isinstance(record.get("selection"), dict) else {}
    params = record.get("params") if isinstance(record.get("params"), dict) else {}
    outputs = record.get("outputs") if isinstance(record.get("outputs"), dict) else {}
    fields = {"flat_id": _is_hex64(record.get("flat_id")),
              "selection.selection_id": _is_hex64(selection.get("selection_id")),
              "selection.mask_pixels_sha256": _is_hex64(selection.get("mask_pixels_sha256")),
              "algorithm": isinstance(record.get("algorithm"), str),
              "params.thickness_mm": _real(params.get("thickness_mm")),
              "outputs.model.stl": _is_hex64(outputs.get("model.stl")),
              "checks": isinstance(record.get("checks"), list)}
    bad = [name for name, ok in fields.items() if not ok]
    if bad:
        raise SlicerError(f"{path} is missing or has invalid: {', '.join(bad)}")
    try:
        recomputed = flat_identity(record["algorithm"], selection["mask_pixels_sha256"],
                                   params)
    except ValueError as err:
        raise SlicerError(f"flat.json is inconsistent: its identity cannot be computed "
                          f"({err})") from None
    if recomputed != record["flat_id"]:
        raise SlicerError("flat.json is inconsistent: flat_id does not match its algorithm, "
                          "mask and parameters")
    try:
        stl = (flat_dir / "model.stl").read_bytes()
    except OSError as err:
        raise SlicerError(f"cannot read {flat_dir / 'model.stl'}: {err}") from None
    actual = hashlib.sha256(stl).hexdigest()
    if actual != outputs["model.stl"]:
        raise SlicerError(f"{flat_dir / 'model.stl'} has sha256 {actual}, which does not "
                          f"match flat.json ({outputs['model.stl']}): it changed after "
                          "tdmg flat; run tdmg flat again")
    return record, raw, stl


def _flat_checks(record: dict) -> list[CheckResult]:
    """The flat record's checks, minus its F6.slicer placeholder, each one validated."""
    checks = []
    for c in record["checks"]:
        if not isinstance(c, dict) or not isinstance(c.get("id"), str):
            raise SlicerError(f"flat.json: a check is not valid: {c!r}")
        if c.get("status") not in STATUSES:
            raise SlicerError(f"flat.json: check {c['id']} has status {c.get('status')!r}, "
                              f"not one of {STATUSES}")
        if c["id"] == "F6.slicer":
            continue
        try:
            checks.append(CheckResult(**c))
        except TypeError as err:
            raise SlicerError(f"flat.json: check {c['id']} is not valid: {err}") from None
    return checks


def _profile_bytes(slicer: Slicer) -> dict[str, bytes]:
    """The three profiles read once and checked against the hashes locate verified."""
    out = {}
    for kind in PROFILE_KINDS:
        path = slicer.profiles[kind]
        try:
            data = path.read_bytes()
        except OSError as err:
            raise SlicerError(f"cannot read {path}: {err}") from None
        expected = slicer.verified["profiles"][kind]["sha256"]
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise SlicerError(f"{path} has sha256 {actual}, which does not match the pin "
                              f"({expected}): it changed while tdmg was running")
        out[kind] = data
    return out


def make_slice(flat_dir, out_dir, slicer_dir=None, timeout_s=None) -> dict:
    """Slice a tdmg flat output folder and write the G-code, the statistics, the log
    (when the slicer wrote one) and slice.json, last.

    timeout_s None takes the default of rule slicer.orca.timeout_s. A refused input, an
    unusable output folder or an unverified slicer raises SlicerError with nothing
    written. A check that FAILs (including a failed slice) still writes the record. When
    F6.slicer_exit is not PASS, any G-code is written as plate_1.gcode.failed.

    slice_id is a SHA-256 of the canonical JSON of: the algorithm; the flat_id, which is
    lineage (it identifies the geometry request, not the checks); the model.stl hash; the
    hash of the flat.json bytes, which pins the inherited checks; the pinned slicer
    (version, exe and library hashes as verified, and the app-tree hash as the pin claims
    it; the tree itself is checked only at setup and by --verify-only); the three profile
    hashes; and the command template. The timeout is not part of it: it can stop a run
    but does not change what a completed run writes, so a timed-out and a completed run
    of the same request share a slice_id. The platform and the environment are recorded
    beside it, not in it.
    """
    flat_dir = Path(flat_dir)
    rules = load_rules()
    timeout = _timeout(timeout_s, rules)
    flat, flat_raw, stl = _read_flat(flat_dir)
    previous = _flat_checks(flat)
    try:
        create_folder = check_output_dir(out_dir)
    except RecordError as err:
        raise SlicerError(str(err)) from None
    pin = load_pin()
    slicer = locate(slicer_dir, pin)
    profile_data = _profile_bytes(slicer)
    try:
        process = json.loads(profile_data["process"])
    except ValueError as err:
        raise SlicerError(f"cannot read {slicer.profiles['process']}: {err}") from None
    thickness = float(flat["params"]["thickness_mm"])
    allowed = expected_layer_counts(thickness, process)

    with tempfile.TemporaryDirectory(prefix="tdmg-slice-") as tmp:
        base = Path(tmp)
        (base / "work").mkdir()
        (base / "profiles").mkdir()
        model = base / "model.stl"
        model.write_bytes(stl)              # the bytes whose hash was just checked
        profiles = {}
        for kind in PROFILE_KINDS:
            profiles[kind] = base / "profiles" / slicer.profiles[kind].name
            profiles[kind].write_bytes(profile_data[kind])
        run = run_slicer(slicer_command(slicer), model, profiles, base / "work",
                         timeout["value"])
        checks, stats = f6_checks(run, allowed, pin, timeout_rule=timeout["rule"])
        exited_ok = checks[0].status == "PASS"
        files = {}
        if (run.out_dir / GCODE_NAME).is_file():
            gcode_name = GCODE_NAME if exited_ok else FAILED_GCODE_NAME
            files[gcode_name] = (run.out_dir / GCODE_NAME).read_bytes()
        if (run.out_dir / STATS_NAME).is_file():
            files[STATS_NAME] = (run.out_dir / STATS_NAME).read_bytes()
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
    flat_record_sha256 = hashlib.sha256(flat_raw).hexdigest()
    slicer_identity = {"version": pin.version, "exe_sha256": verified["exe_sha256"],
                       "libraries": verified["libraries"],
                       "app_tree_sha256": pin.app_tree.sha256}
    identity = {"algorithm": SLICE_ALGORITHM_VERSION, "flat_id": flat["flat_id"],
                "model_stl_sha256": flat["outputs"]["model.stl"],
                "slicer": slicer_identity,
                "profiles": {k: v["sha256"] for k, v in verified["profiles"].items()},
                "flat_record_sha256": flat_record_sha256,
                "command": COMMAND_TEMPLATE}
    gcode_name = next((n for n in (GCODE_NAME, FAILED_GCODE_NAME) if n in files), None)
    record = {
        "schema": RECORD_SCHEMA, "tdmg_version": __version__,
        "algorithm": SLICE_ALGORITHM_VERSION,
        "slice_id": hashlib.sha256(canonical_json(identity)).hexdigest(),
        "links": {"flat_id": flat["flat_id"], "flat_record_sha256": flat_record_sha256,
                  "model_stl_sha256": flat["outputs"]["model.stl"],
                  "selection_id": flat["selection"]["selection_id"]},
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
        "verdict": verdict(all_checks, set(SLICE_REQUIRED_CHECKS)),
        "certification": certification(all_checks, SLICE_REQUIRED_CHECKS),
        "gcode": (None if gcode_name is None else
                  {"file": gcode_name, **gcode_hashes(files[gcode_name])}),
        "stderr_tail": run.stderr,
        "log_written": log_written,
        "outputs": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        "environment": {**environment(), "platform": platform.platform()},
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

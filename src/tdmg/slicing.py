"""tdmg slice: slice a tdmg flat output with the pinned OrcaSlicer (S9, F6), and check
its portability with the pinned PrusaSlicer (F6.portability).

docs/plans/2026-11-10-slicer-check.md, Decisions 6-8, as amended by the measurements in
research/verification/2026-11-10-orcaslicer-windows/ (README and its addendum):
- the argument form is exactly the measured one, without --debug, so the slicer writes
  slicer.log only on errors; it is copied when it exists and log_written records that;
- the allowed layer counts come from the z extent of model.stl as stored (float32), not
  from the requested thickness, with a half-layer window widened by the storage rounding
  (allowed_layer_counts).

F3 is measured from the G-code (tdmg.printed; docs/plans/2026-11-10-thin-wall-policy.md,
Decisions 2 and 2a, approved by the owner): F3.printed_connectivity, F3.edge_coverage and
F3.edge_overprint are required, and the flat record's F3.thin_regions is kept as
information only.

Any required check that FAILs quarantines the G-code: it is written as
plate_1.gcode.failed, never as plate_1.gcode. By default the whole app tree is verified
on every run, so the app_tree_sha256 in slice_id is a checked fact for that run;
check_tree=False (--skip-tree-check) skips that, records app_tree_verified false, and
gives a different slice_id.

F6.portability runs PrusaSlicer 2.9.7 (tdmg.portability;
docs/plans/2026-11-11-portability-check.md) when --prusaslicer-dir or
$TDMG_PRUSASLICER_DIR gives its folder. The bed shape and height, nozzle diameter, layer
and first-layer heights and filament diameter are passed explicitly from the hash-checked
OrcaSlicer A1 profiles; every other setting is PrusaSlicer 2.9.7's default (Codex review
2026-11-11, finding 3: for example 20% infill, no elephant-foot compensation and the
Arachne perimeter generator, where the A1 profile has 15%, 0.075 mm and classic). Without
it, F6.portability is UNKNOWN. For STL it shows that a second slicer accepts the model as
modelled and slices its full height (tdmg.portability.PORTABILITY_MEANING); both slicers
share the admesh STL reader, so a 3MF output must re-run portability with truly different
readers. Its G-code is kept as
prusaslicer.portability-only.gcode.txt, generic G-code that is evidence of portability
only and never for the A1 (not a .gcode name, so no printer software offers it); a FAIL
quarantines it as prusaslicer.portability-only.gcode.txt.failed, as for plate_1.gcode.
write_outputs takes plain file names only, so it sits beside plate_1.gcode rather than in
a portability/ subfolder as the plan suggested. Each PrusaSlicer run is limited by rule
slicer.prusa.timeout_s; an explicit timeout_s applies to both slicers.

The record's verdict combines the flat record's checks, minus its placeholder F6.slicer,
with the F3 and F6 checks of this run, and requires all of them except F3.thin_regions.
The certification line names the required checks that are not PASS. When every one
passes it is PRINTABLE, and certification_note says what that means and what it does
not (PRINTABLE_MEANING). A run with an unverified app tree (check_tree=False) is never
PRINTABLE: its certification starts "NOT CERTIFIED: app tree not verified
(--skip-tree-check)".

Check-to-use gaps: the STL and the three profiles are read once, hashed, and both
slicers run on copies of exactly those bytes in a temporary folder. The exes, their
libraries and the app trees are hashed by locate but run from the installs, so a change
between the hash and the run is not detected; the install folders are assumed to be the
user's own.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import platform
import re
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np
import trimesh

from tdmg import __version__
from tdmg.checks import CheckResult, verdict
from tdmg.colored_flat import RECORD_NAME as COLORED_RECORD
from tdmg.flat import FLAT_REQUIRED_CHECKS, STL_COORD_RTOL, flat_identity
from tdmg.flat import RECORD_SCHEMA as FLAT_SCHEMA
from tdmg.portability import (
    PORTABILITY_MEANING,
    PRUSA_FAILED_GCODE_NAME,
    PRUSA_GCODE_NAME,
    PRUSA_GCODE_NOTE,
    PRUSA_TIMEOUT_RULE,
    SHARED_READER_NOTE,
    Expected,
    PrusaSlicer,
    command_templates,
    coordinate_max,
    explicit_settings,
    load_prusa_pin,
    locate_prusaslicer,
    not_configured_check,
    portability_check,
    prusa_gcode_hashes,
    run_portability,
    size_tolerance_mm,
    volume_tolerance_mm3,
)
from tdmg.printed import (
    ELEPHANT_FOOT_KEY,
    F3_SLICE_CHECK_IDS,
    TOLERANCE_RULE,
    Setup,
    f3_checks,
    flow_from_profile,
    plate_from_profile,
)
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
# The version of what slice_id names, bumped whenever the verdict for the same request can
# change, pushed or not (a local record made with an older method must not share an id
# with a newer one). The method and constants of tdmg.printed are part of it.
# slice-1: F3.thin_regions required (always UNKNOWN).
# slice-2 (2026-11-10, local only): F3.printed_connectivity, F3.edge_coverage and
#   F3.edge_overprint from the G-code required, F3.thin_regions information only; the
#   record has "printed"; slice_id adds the F3 tolerance and elefant_foot_compensation.
#   Its rotation and acceptance rules changed several times within slice-2 locally.
# slice-3 (2026-11-10): the quarter turn chosen by a two-sided score over all layers, with
#   ambiguous placements UNKNOWN; coverage and overprint judged with their sampling
#   bounds (UNKNOWN in between); the G-code reconciled with the model's height and layer
#   count, and with the statistics in F6.layer_count; commanded Z, G92 and extrusion
#   amounts checked against the filament profile.
# slice-4 (2026-11-11): F6.portability measured with the pinned PrusaSlicer 2.9.7 when it
#   is configured (UNKNOWN otherwise); slice_id adds its identity, the explicit settings
#   and its commands; the record has "portability" and "certification_note". Revised
#   before it was pushed: an unverified app tree caps the certification, each PrusaSlicer
#   run has its own timeout rule, its G-code is a .gcode.txt file, every ";Z:" is checked
#   and any open_edges line FAILs. After the Codex review (2026-11-11), still before the
#   push: PrusaSlicer's G-code must be complete and extrude on every layer at its height,
#   and the volume bound covers admesh's zeroed normals.
SLICE_ALGORITHM_VERSION = "slice-4"
RECORD_NAME = "slice.json"
LOG_NAME = "slicer.log"
FAILED_GCODE_NAME = GCODE_NAME + ".failed"   # G-code from a run with a FAILed check
SLICE_REQUIRED_EXTRA = frozenset({"F6.slicer_exit", "F6.gcode_present", "F6.layer_count",
                                  "F6.single_object", "F6.portability"})
THIN_REGIONS = "F3.thin_regions"
SLICE_REQUIRED_CHECKS = ((FLAT_REQUIRED_CHECKS - {"F6.slicer", THIN_REGIONS})
                         | set(F3_SLICE_CHECK_IDS) | SLICE_REQUIRED_EXTRA)
THIN_REGIONS_NOTE = ("information only in tdmg slice: F3.printed_connectivity, "
                     "F3.edge_coverage and F3.edge_overprint judge thin features from the "
                     "G-code")
STATUSES = ("PASS", "FAIL", "UNKNOWN")


def _thin_regions_note(note: str | None) -> str:
    """The flat note, with THIN_REGIONS_NOTE added unless it already says information only."""
    if not note:
        return THIN_REGIONS_NOTE
    return note if "information only" in note else f"{note}; {THIN_REGIONS_NOTE}"
HEX64 = re.compile(r"[0-9a-f]{64}")
# The command as recorded: placeholders, so the record holds no path from this machine.
COMMAND_TEMPLATE = ["<orca-slicer.exe>", *slicer_args(
    Path("<model.stl>"), {k: Path(f"<{k}.json>") for k in PROFILE_KINDS},
    Path("<outdir>"), Path(f"<{LOG_NAME}>"))]
DO_NOT_PRINT = f"a check FAILed: do not print this G-code; it is kept as {FAILED_GCODE_NAME}"
# Added to DO_NOT_PRINT only when PrusaSlicer wrote its G-code.
PRUSA_DO_NOT_PRINT = f" (and PrusaSlicer's as {PRUSA_FAILED_GCODE_NAME})"
TREE_NOT_VERIFIED = "app tree not verified (--skip-tree-check)"
PRINTABLE_MEANING = (
    "PRINTABLE means every required gate check passed for this file with the pinned slicers "
    "(OrcaSlicer 2.5.0 and, for portability, PrusaSlicer 2.9.7) and the A1 profile; for "
    f"portability, {PORTABILITY_MEANING}. {SHARED_READER_NOTE}. It is not a guarantee: the "
    "acceptance tolerance (acceptance.dimension.tolerance) is still a hypothesis, no "
    "calibration print has been measured, and strength is not judged.")
# Until the pinned A1 machine profile carries the A1's own start, end and filament-change
# G-code (docs/plans/2026-11-13-color-slicing.md, Decision 1), plate_1.gcode is not to be
# printed: the flattened profile missed the A1 template presets named by "include".
PRINT_THIS = ("slice model.stl in Bambu Studio to print; "
              f"{GCODE_NAME} is for checking only (its start and end G-code are not the "
              f"A1's yet: the pinned A1 profile is incomplete); {PRUSA_GCODE_NAME} is not "
              "for printing")
REVIEW = ("Open plate_1.gcode in a G-code preview (for example OrcaSlicer's or Bambu "
          "Studio's) and check the layers and the first layer. Time and weight are the "
          "slicer's estimates for the A1 0.20 mm Standard and PLA Basic profiles, not "
          "measurements. When any required check FAILs, the G-code is kept as "
          f"{FAILED_GCODE_NAME}; do not print it. F3.printed_connectivity, "
          "F3.edge_coverage and F3.edge_overprint compare what the G-code prints with the "
          "model, layer by layer (printed records the layers); they model each line as a "
          "bead of its stated width and do not judge strength. Every check of flat.json and "
          "of this run is required, except F3.thin_regions, which is information only. "
          "F6.portability runs PrusaSlicer 2.9.7 when --prusaslicer-dir or "
          "TDMG_PRUSASLICER_DIR is given; without it, it is UNKNOWN and the verdict is NOT "
          f"CERTIFIED. For STL it shows that {PORTABILITY_MEANING}. {SHARED_READER_NOTE}. "
          f"{PRUSA_GCODE_NOTE}. With --skip-tree-check the verdict is NOT CERTIFIED. "
          "PRINTABLE, when every required check passes, is "
          "explained in certification_note: the tolerance is still a hypothesis, no "
          "calibration print has been measured and strength is not judged.")


def slicer_command(slicer: Slicer) -> list[str]:
    """The program to run: the verified exe (tests replace this with the fake slicer)."""
    return [str(slicer.exe)]


def prusa_command(prusa: PrusaSlicer) -> list[str]:
    """PrusaSlicer's program: the verified console exe (tests replace it with a fake)."""
    return [str(prusa.exe)]


def stl_z_range(stl: bytes) -> tuple[float, float]:
    """(lowest, highest) z of the STL's vertices, as stored (float32 widened to float64)."""
    try:
        mesh = trimesh.load(io.BytesIO(stl), file_type="stl", process=False)
        z = np.asarray(mesh.vertices, dtype=np.float64)[:, 2]
    except (ValueError, TypeError, IndexError, AttributeError) as err:   # a malformed STL
        raise SlicerError(f"model.stl cannot be read as an STL: {err}") from None
    if z.size == 0 or not np.isfinite(z).all():
        raise SlicerError("model.stl has no vertices, or a non-finite z")
    return float(z.min()), float(z.max())


def allowed_layer_counts(stl: bytes, process_profile: dict) -> set[int]:
    """The layer counts the slicer may produce for this STL, from its z extent as stored.

    Binary STL stores float32. Rounding to nearest moves a coordinate z by at most
    |z| * 2^-24, so the extent z_max - z_min is off by at most 2 * zabs * 2^-24, with zabs
    the larger of |z_min| and |z_max|. As flat's export check does with STL_COORD_RTOL
    (2^-23, twice one coordinate's rounding), this is doubled to cover the float64
    arithmetic: storage error = 2 * STL_COORD_RTOL * zabs = zabs * 2^-22. A numerical
    bound, not a rule. Two thicknesses that round to the same float32 STL therefore get
    the same allowed set.
    """
    z_min, z_max = stl_z_range(stl)
    zabs = max(abs(z_min), abs(z_max))
    return expected_layer_counts(z_max - z_min, process_profile,
                                 storage_error_mm=2 * STL_COORD_RTOL * zabs)


def certification(checks: list[CheckResult], required: set[str] | frozenset[str],
                  trees_verified: bool = True) -> str:
    """"PRINTABLE", or "NOT CERTIFIED: " and each reason.

    When a slicer's app tree was not verified (trees_verified False), the first reason is
    TREE_NOT_VERIFIED: what ran was not checked, so it cannot be PRINTABLE. Then each
    required check that is not PASS, with its status, in check order; a required check that
    is absent is named "missing" at the end.
    """
    if trees_verified and verdict(checks, set(required)) == "PRINTABLE":
        return "PRINTABLE"
    named = [] if trees_verified else [TREE_NOT_VERIFIED]
    named += [f"{c.id} {c.status}" for c in checks if c.id in required and c.status != "PASS"]
    present = {c.id for c in checks}
    named += [f"{cid} missing" for cid in sorted(set(required) - present)]
    return "NOT CERTIFIED: " + ", ".join(named)


def _timeout(timeout_s, rules, rule: str = TIMEOUT_RULE) -> dict:
    if timeout_s is None:
        return {"value": rules[rule].default, "rule": rule}
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
        if (flat_dir / COLORED_RECORD).exists():
            raise SlicerError(
                f"{flat_dir} is a tdmg flat --colors folder ({COLORED_RECORD}); tdmg slice "
                "cannot slice colored output yet (step 4 of the color design), only a "
                "single-color tdmg flat folder with flat.json") from None
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


def elephant_foot_mm(process_profile: dict) -> float:
    """The process profile's elefant_foot_compensation in mm: finite and at least 0."""
    if ELEPHANT_FOOT_KEY not in process_profile:
        raise SlicerError(f"process profile has no {ELEPHANT_FOOT_KEY!r}")
    value = process_profile[ELEPHANT_FOOT_KEY]
    try:
        mm = float(value)
    except (TypeError, ValueError):
        raise SlicerError(f"process profile {ELEPHANT_FOOT_KEY!r} is {value!r}, not a "
                          "number") from None
    if not (math.isfinite(mm) and mm >= 0):
        raise SlicerError(f"process profile {ELEPHANT_FOOT_KEY!r} must be finite and at "
                          f"least 0, not {value!r}")
    return mm


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


def _cross_check_layers(f6: list[CheckResult], stats: dict | None,
                        printed: dict) -> list[CheckResult]:
    """F6.layer_count FAILs when the G-code's own layers disagree with the statistics.

    The statistics file is written beside the G-code; a G-code cut short with untouched
    statistics would otherwise pass the count. Only when both counts are known: an
    unmeasurable G-code leaves the F3 checks UNKNOWN instead.
    """
    counted = printed.get("layer_count")
    if stats is None or counted is None or counted == stats["layer_count"]:
        return f6
    out = []
    for c in f6:
        if c.id == "F6.layer_count":
            c = CheckResult(c.id, "FAIL", {"statistics": stats["layer_count"],
                                           "gcode": counted}, c.threshold, c.rule,
                            f"the G-code has {counted} layers but its statistics say "
                            f"{stats['layer_count']}: the G-code or the statistics are "
                            "not from the same complete slice")
        out.append(c)
    return out


def _expected_mesh(flat: dict) -> dict:
    """flat.json's mesh facts PrusaSlicer is compared with, checked. SlicerError if not."""
    mesh = flat.get("mesh") if isinstance(flat.get("mesh"), dict) else {}

    def count(v):
        return isinstance(v, int) and not isinstance(v, bool) and v >= 1

    def number(v):
        return (isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v))
    extents = mesh.get("extents_mm")
    ok = {"mesh.bodies": count(mesh.get("bodies")),
          "mesh.triangles": count(mesh.get("triangles")),
          "mesh.extents_mm": (isinstance(extents, list) and len(extents) == 3
                              and all(number(v) for v in extents)),
          "mesh.volume_mm3": number(mesh.get("volume_mm3"))}
    bad = [name for name, good in ok.items() if not good]
    if bad:
        raise SlicerError(f"flat.json is missing or has invalid: {', '.join(bad)}")
    return mesh


def make_slice(flat_dir, out_dir, slicer_dir=None, timeout_s=None,
               check_tree: bool = True, prusaslicer_dir=None) -> dict:
    """Slice a tdmg flat output folder and write the G-code, the statistics, the log
    (when the slicer wrote one) and slice.json, last.

    timeout_s None takes the default of rule slicer.orca.timeout_s. A refused input, an
    unusable output folder or an unverified slicer raises SlicerError with nothing
    written. A check that FAILs (including a failed slice) still writes the record. When
    any required check FAILs, the G-code is written as plate_1.gcode.failed (quarantined).
    check_tree=False skips the full app-tree check (exe, libraries and profiles are still
    checked) and records app_tree_verified false, for both slicers.

    prusaslicer_dir (default $TDMG_PRUSASLICER_DIR) is the PrusaSlicer folder from
    scripts/setup_prusaslicer.py. When neither is given, F6.portability is UNKNOWN. When
    one is given, it must verify, and the OrcaSlicer profiles must hold every setting
    PrusaSlicer is given, or the run is refused. PrusaSlicer runs --info and then
    --export-gcode, each with the same timeout.

    slice_id is a SHA-256 of the canonical JSON of: the algorithm; the flat_id, which is
    lineage (it identifies the geometry request, not the checks); the model.stl hash; the
    hash of the flat.json bytes, which pins the inherited checks; the pinned slicer
    (version, exe and library hashes as verified, the pinned app-tree hash and whether this
    run verified it, app_tree_verified, so a skipped check gives a different id); the three
    profile hashes; the command template; and the F3 inputs that set the verdict, the
    tolerance rule's value and the profile's elefant_foot_compensation (the plate centre
    comes from the machine profile, whose hash is already there). The timeout is not part
    of it: it can stop a run
    but does not change what a completed run writes, so a timed-out and a completed run
    of the same request share a slice_id. The platform and the environment are recorded
    beside it, not in it. The F3 measurements of the G-code ("printed") are outputs, like
    the G-code itself, so they are not part of it either. With PrusaSlicer configured,
    "portability" adds its identity (version, exe and library hashes, pinned tree hash and
    whether it was verified), the explicit settings and both command templates; without
    it, "portability" is None.
    """
    flat_dir = Path(flat_dir)
    rules = load_rules()
    timeout = _timeout(timeout_s, rules)
    prusa_timeout = _timeout(timeout_s, rules, PRUSA_TIMEOUT_RULE)
    flat, flat_raw, stl = _read_flat(flat_dir)
    # F3.thin_regions stays in the record as information; the note says so. Flat records
    # from older code do not say it, so the note is added unless it is already there.
    previous = [replace(c, note=_thin_regions_note(c.note)) if c.id == THIN_REGIONS else c
                for c in _flat_checks(flat)]
    try:
        create_folder = check_output_dir(out_dir)
    except RecordError as err:
        raise SlicerError(str(err)) from None
    pin = load_pin()
    slicer = locate(slicer_dir, pin, full_tree=check_tree)
    prusa = locate_prusaslicer(prusaslicer_dir, load_prusa_pin(), full_tree=check_tree)
    profile_data = _profile_bytes(slicer)
    try:
        process = json.loads(profile_data["process"])
    except ValueError as err:
        raise SlicerError(f"cannot read {slicer.profiles['process']}: {err}") from None
    try:
        plate = plate_from_profile(json.loads(profile_data["machine"]))
    except (ValueError, AttributeError) as err:     # unreadable JSON, or not an object
        raise SlicerError(f"cannot read the plate from {slicer.profiles['machine']}: "
                          f"{err}") from None
    try:
        flow = flow_from_profile(json.loads(profile_data["filament"]))
    except (ValueError, AttributeError) as err:     # unreadable JSON, or not an object
        raise SlicerError(f"cannot read the filament from {slicer.profiles['filament']}: "
                          f"{err}") from None
    thickness = float(flat["params"]["thickness_mm"])
    z_min, z_max = stl_z_range(stl)
    allowed = allowed_layer_counts(stl, process)
    tolerance = float(rules[TOLERANCE_RULE].default)
    elephant = elephant_foot_mm(process)
    setup = Setup(plate, flow, tolerance, elephant, frozenset(allowed))
    settings, expected = None, None
    if prusa is not None:
        # Both profiles parsed above as JSON objects (plate_from_profile and
        # flow_from_profile would have refused anything else).
        settings = explicit_settings(json.loads(profile_data["machine"]), process,
                                     json.loads(profile_data["filament"]))
        mesh = _expected_mesh(flat)
        expected = Expected(
            parts=mesh["bodies"], facets=mesh["triangles"],
            size_mm=[float(v) for v in mesh["extents_mm"]],
            volume_mm3=float(mesh["volume_mm3"]), layer_counts=sorted(allowed),
            first_layer_mm=float(process["initial_layer_print_height"]),
            layer_mm=float(process["layer_height"]),
            size_tol_mm=size_tolerance_mm(coordinate_max(stl)),
            volume_tol_mm3=volume_tolerance_mm3(stl))

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
        f6, stats = f6_checks(run, allowed, pin, timeout_rule=timeout["rule"])
        gcode = ((run.out_dir / GCODE_NAME).read_bytes()
                 if (run.out_dir / GCODE_NAME).is_file() else None)
        exited = next(c for c in f6 if c.id == "F6.slicer_exit").status == "PASS"
        f3, printed = f3_checks(gcode, stl, setup,
                                None if exited else "the slicer failed (F6.slicer_exit)")
        f6 = _cross_check_layers(f6, stats, printed)
        prusa_gcode, measurements = None, None
        if prusa is None:
            portability = not_configured_check()
        else:
            (base / "prusa").mkdir()
            info_run, gcode_run, prusa_gcode = run_portability(
                prusa_command(prusa), model, settings, base / "prusa",
                prusa_timeout["value"], prusa)
            portability, measurements = portability_check(info_run, gcode_run, prusa_gcode,
                                                          expected, prusa_timeout["rule"])
        checks = f3 + f6 + [portability]
        quarantined = any(c.status == "FAIL" for c in previous + checks
                          if c.id in SLICE_REQUIRED_CHECKS)
        files = {}
        if gcode is not None:
            files[FAILED_GCODE_NAME if quarantined else GCODE_NAME] = gcode
        prusa_name = PRUSA_FAILED_GCODE_NAME if quarantined else PRUSA_GCODE_NAME
        if prusa_gcode is not None:
            files[prusa_name] = prusa_gcode
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
                       "app_tree_sha256": pin.app_tree.sha256,
                       "app_tree_verified": "app_tree" in verified}
    identity = {"algorithm": SLICE_ALGORITHM_VERSION, "flat_id": flat["flat_id"],
                "model_stl_sha256": flat["outputs"]["model.stl"],
                "slicer": slicer_identity,
                "profiles": {k: v["sha256"] for k, v in verified["profiles"].items()},
                "flat_record_sha256": flat_record_sha256,
                "command": COMMAND_TEMPLATE,
                "f3": {"tolerance": {"rule": TOLERANCE_RULE, "value_mm": tolerance},
                       "elefant_foot_compensation_mm": elephant},
                "portability": None if prusa is None else {
                    "slicer": prusa.identity(),
                    "settings": {k: v["value"] for k, v in settings.items()},
                    "commands": command_templates(settings)}}
    gcode_name = next((n for n in (GCODE_NAME, FAILED_GCODE_NAME) if n in files), None)
    if prusa is None:
        portability_record = {"configured": False, "reason": portability.note,
                              "note": PRUSA_GCODE_NOTE, "slicer": None, "settings": None,
                              "commands": None, "expected": None, "tolerances": None,
                              "info": None, "gcode": None}
    else:
        written = prusa_gcode is not None
        portability_record = {
            "configured": True, "reason": None, "note": PRUSA_GCODE_NOTE,
            "slicer": {"name": prusa.pin.name, "pin": prusa.pin.id, **prusa.identity()},
            "settings": settings, "commands": command_templates(settings),
            "expected": expected.as_dict(), "tolerances": measurements["tolerances"],
            "info": measurements["info"],
            "gcode": {**measurements["gcode"], "file": prusa_name if written else None,
                      "quarantined": quarantined if written else None,
                      **(prusa_gcode_hashes(prusa_gcode) if written else
                         {"sha256": None, "normalised_sha256": None,
                          "normalised_lines": None})}}
    trees_verified = (slicer_identity["app_tree_verified"]
                      and (prusa is None or prusa.identity()["app_tree_verified"]))
    cert = certification(all_checks, SLICE_REQUIRED_CHECKS, trees_verified)
    record = {
        "schema": RECORD_SCHEMA, "tdmg_version": __version__,
        "algorithm": SLICE_ALGORITHM_VERSION,
        "slice_id": hashlib.sha256(canonical_json(identity)).hexdigest(),
        "links": {"flat_id": flat["flat_id"], "flat_record_sha256": flat_record_sha256,
                  "model_stl_sha256": flat["outputs"]["model.stl"],
                  "selection_id": flat["selection"]["selection_id"]},
        "params": {"timeout_s": timeout, "prusaslicer_timeout_s": prusa_timeout,
                   "thickness_mm": thickness,
                   "stl_z_mm": {"min": z_min, "max": z_max, "extent": z_max - z_min},
                   "expected_layer_counts": sorted(allowed)},
        "slicer": {"name": pin.name, "version": pin.version, "pin": pin.id,
                   **{k: v for k, v in slicer_identity.items() if k != "version"},
                   "profiles": verified["profiles"],
                   "platform": platform_key()},
        "command": COMMAND_TEMPLATE,
        "exit": {**exit_code, "timed_out": run.timed_out},
        "stats": stats,
        "printed": printed,
        "checks": [c.as_dict() for c in all_checks],
        "verdict": "PRINTABLE" if cert == "PRINTABLE" else "NOT CERTIFIED",
        "certification": cert,
        "certification_note": PRINTABLE_MEANING if cert == "PRINTABLE" else None,
        "portability": portability_record,
        "gcode": (None if gcode_name is None else
                  {"file": gcode_name, "quarantined": quarantined,
                   **gcode_hashes(files[gcode_name])}),
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

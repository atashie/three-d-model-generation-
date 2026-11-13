"""tdmg slice for a tdmg flat --colors folder (docs/plans/2026-11-13-color-slicing.md,
Decisions 2 to 7 as amended, and Task 6).

make_color_slice slices the AMS version face up (the default), face down or both with the
pinned OrcaSlicer, each color on its own filament, slices each glue plate as an R1 part,
runs F6.portability
on the portable model.3mf with the pinned PrusaSlicer, and writes slice.json (schema
tdmg.colorslice/1) last. It prints nothing.

1. Refused, with nothing written (SlicerError, as tdmg.slicing refuses): colored.json
   missing or unreadable, not schema tdmg.colorflat/1, not algorithm colorflat-3, its
   colorflat_id not the hash of its identity, its required_checks not the set
   tdmg.colored_flat gives for its glue section, a body row or a check that is not valid;
   any output it lists missing (FileNotFoundError: "missing"), or with a SHA-256 that is not
   the record's (the STLs, model.3mf, palette.json, top.png and parts.png); a palette.json
   that does not describe the record's AMS shells; shells rebuilt from the AMS STLs that do
   not PASS export_3mf_check against model.3mf; and everything tdmg.slicing refuses
   (output folder, slicers, profiles, timeout).
2. The colored record's own checks are not a refusal: as tdmg.slicing.make_slice does
   with flat.json's checks, they are carried into each verdict (minus the F6.slicer
   placeholder; F3.thin_regions stays as information) and a FAIL among the required ones
   quarantines the G-code. Each face carries the AMS route's checks (every AMS body's and
   the AMS assembly's); each glue plate carries its own body's and the glue assembly's.
3. The shells: each AMS STL parsed back and merged exactly (tdmg.checks.merge_exact), as
   tdmg.colored_flat's gate reads it, in the record's model_3mf.shells order (the base
   first, then the inlays by palette index). Face down is tdmg.orca_input.turn_over.
4. Per face: orca-input.3mf (tdmg.orca_input.write_orca_input; a slicer input, not a
   deliverable) gated by F2.orca_input_matches_bodies; the filament profiles, each the
   pinned filament.json with only filament_colour set to its color (plan Decision 2,
   amended after Task 2), in filament_map order; the pinned OrcaSlicer with the measured
   argument form of tdmg.slicer.slicer_args, the filaments joined by ";" as Task 2 ran it
   (without its --debug 3, as R1); R1's F6 checks (F6.slicer_exit, F6.gcode_present,
   F6.layer_count with the layer count from the bodies' z extent as stored, and
   F6.single_object), with F6.layer_count cross-checked against the G-code's own layers;
   and tdmg.color_gcode.color_slice_checks.
5. Each glue-*.stl: tdmg.slicing.slice_stl, R1's run and checks, with R1's required set
   minus F2.target_width (controller decision, 2026-11-13: a plate of pieces has no
   target width; the record says so under not_applicable). F4.body_count is computed here
   (glue_body_count_check): the STL's bodies must equal the plate's pieces in the glue
   report (1 for the glue base); a report whose per-color counts and piece list disagree
   is refused.
6. F6.portability (Decision 6): PrusaSlicer --info on model.3mf must read one manifold
   object, unrepaired, with the AMS bodies' parts (connected pieces) and triangles, and
   their overall size within R1's size tolerance; --export-gcode must slice it (one
   extruder) to the allowed layers, as R1 judges its G-code. The volume is information
   (VOLUME_NOTE; controller decision, 2026-11-13): PrusaSlicer's volume, the palette sum
   and the difference are recorded in measured, and do not decide the status.
7. Verdicts: per face, PRINTABLE only if every required check passes: the inherited ones
   (the record's required_checks minus the glue-only ones, F6.slicer and
   F3.thin_regions), F2.orca_input_matches_bodies, color_gcode.required_check_ids, R1's
   four slicer F6 checks and F6.portability. Per glue plate, GLUE_REQUIRED_CHECKS and
   the record's required glue-only checks (F4.glue_fit, F4.glue_partition). The glue route
   is printable only when every glue plate is PRINTABLE (glue_route). A FAIL
   quarantines that face's or plate's G-code (.failed); PrusaSlicer's G-code is quarantined when
   F6.portability or an inherited AMS check FAILs.

colorslice_id is the SHA-256 of the canonical JSON of: the algorithm (COLORSLICE_ALGORITHM);
the colorflat_id (lineage) and the colored.json hash (which pins the inherited checks and,
through its output hashes, every STL, model.3mf and palette.json); each face's
orca-input.3mf hash; the pinned slicer and profiles as tdmg.slicing names them; the
derived filament profiles' hashes; the command template; the F3 inputs (tolerance rule
value, elefant_foot_compensation); the faces; PrusaSlicer's identity, settings and command
templates (None without it); and each glue plate's slice_id. The timeouts, the environment
and the platform are recorded beside it, not in it.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import platform
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np
import trimesh

from tdmg import __version__
from tdmg import slicing as _slicing  # its slicer_command and prusa_command, by module
from tdmg.checks import CheckResult, merge_exact
from tdmg.color_checks import export_3mf_check, orca_input_check
from tdmg.color_gcode import (
    COLOR_CHANGES,
    COLOR_TIME,
    COLOR_WASTE,
    color_slice_checks,
    f3_warning_ids,
    per_tool_id,
    required_check_ids,
)
from tdmg.colored_flat import (
    ALGORITHM as COLORFLAT_ALGORITHM,
)
from tdmg.colored_flat import (
    COLORED_REQUIRED_CHECKS,
    GLUE_ONLY_CHECKS,
    MODEL_3MF,
    PALETTE_NAME,
    colorflat_id,
)
from tdmg.colored_flat import RECORD_NAME as COLORED_RECORD
from tdmg.colored_flat import RECORD_SCHEMA as COLORFLAT_SCHEMA
from tdmg.flat import STL_COORD_RTOL
from tdmg.flat import _body_count as body_count
from tdmg.orca_input import ENCODING as ORCA_ENCODING
from tdmg.orca_input import ORCA_INPUT_NAME, filament_map, turn_over, write_orca_input
from tdmg.portability import (
    PRUSA_FAILED_GCODE_NAME,
    PRUSA_GCODE_NAME,
    PRUSA_GCODE_NOTE,
    Expected,
    command_templates,
    not_configured_check,
    portability_check,
    prusa_gcode_hashes,
    run_portability,
    size_tolerance_mm,
)
from tdmg.printed import CONNECTIVITY, COVERAGE
from tdmg.records import (
    RecordError,
    canonical_json,
    check_output_dir,
    environment,
)
from tdmg.rules import load_rules
from tdmg.slicer import (
    GCODE_NAME,
    STATS_NAME,
    SlicerError,
    SlicerRun,
    expected_layer_counts,
    f6_checks,
    gcode_hashes,
    output_tail,
    run_process,
)
from tdmg.slicing import (
    COMMAND_TEMPLATE,
    FAILED_GCODE_NAME,
    LOG_NAME,
    SLICE_ALGORITHM_VERSION,
    SLICE_REQUIRED_CHECKS,
    STATUSES,
    THIN_REGIONS,
    Context,
    _cross_check_layers,
    _exit_code,
    _is_hex64,
    _thin_regions_note,
    _timeout,
    certification,
    prepare,
    slice_stl,
    store,
)
from tdmg.threemf import Shell

COLOR_RECORD_SCHEMA = "tdmg.colorslice/1"
# The version of what colorslice_id names, bumped whenever the verdict for the same request
# can change. colorslice-1 (2026-11-13): plan docs/plans/2026-11-13-color-slicing.md, Task 6.
COLORSLICE_ALGORITHM = "colorslice-1"
FACES = ("up", "down")
FACE_FOLDER = {"up": "face-up", "down": "face-down"}
FILAMENT_FOLDER = "filaments"
FILAMENT_KEY = "filament_colour"
ORCA_CHECK = "F2.orca_input_matches_bodies"
SLICER_F6_IDS = frozenset({"F6.slicer_exit", "F6.gcode_present", "F6.layer_count",
                           "F6.single_object"})
# The inherited checks a face requires: the colored record's required ones, without the
# glue-only ones (a face is the AMS route), the F6.slicer placeholder (this run slices)
# and F3.thin_regions (information, as in R1).
INHERITED_DROPPED = frozenset({"F6.slicer", THIN_REGIONS})
# Plan Decision 6 asks of model.3mf only that --info reads one manifold object and that it
# slices; the volume is information (controller decision, 2026-11-13, Task 6).
VOLUME_NOTE = (
    "The volume is information, not a condition: PrusaSlicer's --info volume, the palette "
    "sum (the AMS bodies' volumes in colored.json) and their difference are in measured. No "
    "derivation of how PrusaSlicer 2.9.7 computes a 3MF's volume exists: R1's "
    "volume_tolerance_mm3 is derived for admesh's get_volume on an STL, and float32 "
    "emulations of that computation and of an its_volume-like one on model.3mf's triangles "
    "(in file order, centred or not) did not reproduce PrusaSlicer's printed 3MF volumes "
    "(Task 6, 2026-11-13; step 3 Task 5 measured differences of -1.23 to +0.25 mm3, cause "
    "not investigated).")
COLOR_PORTABILITY_MEANING = (
    "a second slicer (PrusaSlicer 2.9.7) reads model.3mf as one manifold object, unrepaired, "
    "with the AMS bodies' parts (connected pieces), triangles and size, and slices it on one "
    "extruder to its full height, with extrusion on every layer at its height (its other "
    "settings are PrusaSlicer's defaults)")
TARGET_WIDTH = "F2.target_width"
BODY_COUNT = "F4.body_count"
TARGET_WIDTH_NA = ("not applicable to a glue plate: a plate of pieces has no target width; "
                   "the colored record's width belongs to the whole model (controller "
                   "decision, 2026-11-13, Task 6)")
GLUE_REQUIRED_CHECKS = SLICE_REQUIRED_CHECKS - {TARGET_WIDTH}
SIZE_NOTE = ("the size tolerance is R1's size_tolerance_mm, derived for PrusaSlicer's STL "
             "import; for model.3mf its --info sizes matched the bodies' extents to all 6 "
             "decimals on the four owner plans (step 3, Task 5)")
ORCA_INPUT_NOTE = ("orca-input.3mf is the OrcaSlicer-only slicing input (encoding B_msc), "
                   "built from the same gated AMS meshes as model.3mf: not a deliverable; "
                   "print from model.3mf")
FILAMENT_NOTE = ("Each filament profile is the pinned filament.json with only "
                 "filament_colour set to its color (OrcaSlicer computes the flush volumes "
                 "and the tool order from it; the 3MF does not carry it). Not pinned "
                 "profiles: their hashes are recorded, and the parsed JSON of each differs "
                 "from the pinned one in exactly that key.")
COLOR_PRINTABLE_MEANING = (
    "PRINTABLE means every required gate check passed for this face with the pinned "
    "slicers (OrcaSlicer 2.5.0 on orca-input.3mf and, for portability, PrusaSlicer 2.9.7 on "
    "model.3mf) and the A1 profile. It is not a guarantee: the acceptance tolerance "
    "(acceptance.dimension.tolerance) is still a hypothesis, no calibration print has been "
    "measured, no tdmg G-code has been printed, and strength is not judged.")
PRINT_TAIL = (
    "give each color the filament listed; each face's plate_1.gcode is for checking only "
    "(tdmg's G-code is not yet printed or compared with Bambu Studio's own slice); "
    f"{PRUSA_GCODE_NAME} is not for printing")
# The owner's default face (plan Task 7, 2026-11-13: "Face up (Recommended)").
DEFAULT_FACE = "up"
FACE_CHOICES = {"up": ("up",), "down": ("down",), "both": ("up", "down")}
PRINT_FACE = {
    ("up",): "to print face up: open model.3mf in Bambu Studio (it is face up) and "
             + PRINT_TAIL,
    ("down",): "to print face down: open model.3mf in Bambu Studio and turn it over "
               "(model.3mf is face up; face down is it turned 180 degrees about the y axis, "
               "the inlays on the bed), then " + PRINT_TAIL,
    ("up", "down"): "both faces are PRINTABLE; the owner's default is face up (plan Task "
                    "7): open model.3mf in Bambu Studio (it is face up; turn it over for "
                    "face down) and " + PRINT_TAIL}


def face_warnings(checks: list[CheckResult], fmap: list[dict]) -> list[dict]:
    """The face's warning checks (tdmg.color_gcode.f3_warning_ids) that do not PASS, for
    the record and the CLI: one per tool whose F3.edge_coverage does not pass, with its
    largest gap, and one for all the connectivity checks together (not per layer)."""
    by = {c.id: c for c in checks}
    warn = set(f3_warning_ids(len(fmap)))
    out = []
    for t, f in enumerate(fmap):
        c = by.get(per_tool_id(COVERAGE, t))
        if c is None or c.id not in warn or c.status == "PASS":
            continue
        gap = (c.measured or {}).get("max_gap_mm") if isinstance(c.measured, dict) else None
        who = _who(f)
        text = (f"{who}: edge coverage {c.status}, edges up to {gap:.2f} mm from its "
                "printed lines (for example thin areas the slicer skips, or a part left "
                "unprinted)" if gap is not None else
                f"{who}: edge coverage {c.status} ({c.note.split(';')[0]})")
        out.append({"ids": [c.id], "status": c.status, "filament": f["filament"],
                    "index": f["index"], "hex": f["hex"], "max_gap_mm": gap,
                    "text": text})
    conn = [i for i in (CONNECTIVITY, *(per_tool_id(CONNECTIVITY, t)
                                         for t in range(len(fmap))))
            if i in by and i in warn and by[i].status != "PASS"]
    if conn:
        def where(ids):
            return ", ".join("the whole model" if i == CONNECTIVITY else
                             _who(fmap[int(i.rsplit(".T", 1)[1])]) for i in ids)
        failed = [i for i in conn if by[i].status == "FAIL"]
        unknown = [i for i in conn if by[i].status == "UNKNOWN"]
        parts = []
        if failed:
            each = "; ".join(f"{where([i])} {_mismatch(by[i].measured)}" for i in failed)
            parts.append(f"connectivity check FAIL: {each}; on the owner's plans a "
                         "connectivity FAIL is where two colors' lines meet edge to edge, "
                         "see research/verification/2026-11-13-color-slicing/"
                         "owner-review.txt")
        if unknown:
            reason = by[unknown[0]].note.split(";")[0]
            parts.append(f"connectivity check UNKNOWN for {where(unknown)}: {reason}")
        out.append({"ids": conn, "status": sorted({by[i].status for i in conn}),
                    "filament": None, "index": None, "hex": None, "max_gap_mm": None,
                    "text": "; ".join(parts)})
    return out


def _count(n, what: str) -> str:
    return f"{n} {what}" + ("" if n == 1 else "s")


def _mismatch(m) -> str:
    """What a FAILed connectivity check measured (tdmg.printed's record: the first
    mismatched layer's parts and holes, printed and in the model, and every mismatched z),
    e.g. "printed 7 parts against 1 in the model (3 of 15 layers differ, z 2.6 to 3)"."""
    if not isinstance(m, dict) or m.get("parts_printed") is None:
        return "(its measurements are not recorded)"
    said = []
    if m["parts_printed"] != m["parts_model"]:
        said.append(f"{_count(m['parts_printed'], 'part')} against {m['parts_model']}")
    if m["holes_printed"] != m["holes_model"]:
        said.append(f"{_count(m['holes_printed'], 'hole')} against {m['holes_model']}")
    head = ("printed " + " and ".join(said) + " in the model" if said else
            "printed parts and holes that do not match the model's one to one")
    zs = m.get("mismatched_z") or [m.get("first_z")]
    span = f"z {zs[0]:g}" if len(zs) == 1 else f"z {zs[0]:g} to {zs[-1]:g}"
    return (f"{head} ({m.get('layers_mismatched', len(zs))} of {m.get('layers')} layers "
            f"differ, {span})")


def _who(f: dict) -> str:
    """"base #rrggbb (filament n)" or "color i #rrggbb (filament n)"."""
    return (("base" if f["role"] == "base" else f"color {f['index']}")
            + f" {f['hex']} (filament {f['filament']})")


def print_message(printable_faces) -> str | None:
    """What to print, for the PRINTABLE faces ("up", "down"); None when there are none.
    model.3mf is the file to print from, and it is face up."""
    faces = tuple(f for f in FACES if f in printable_faces)
    return PRINT_FACE.get(faces)


def glue_route(plates: dict) -> dict:
    """The glue route as one print: printable only when every glue plate is PRINTABLE.
    blocking: the plates that are not, in plate order."""
    blocking = [name for name, p in plates.items() if p["verdict"] != "PRINTABLE"]
    return {"printable": bool(plates) and not blocking, "blocking": blocking}
COLOR_DO_NOT_PRINT = (f"a check FAILed: the G-code of that face or plate is kept as "
                      f"{FAILED_GCODE_NAME}; do not print it")
COLOR_REVIEW = (
    "Each face sliced (face up by default; face-up/, face-down/) is sliced from "
    "orca-input.3mf, each color on its own filament (filament_map). Open its plate_1.gcode "
    "in a G-code preview to check the "
    "colors, the layers and the prime tower; it is for checking only, not for printing. To "
    "print, open model.3mf in Bambu Studio and assign the filaments as listed. Changes, "
    "flush, prime tower and time are information (F6.color_waste, F6.color_time), from the "
    "G-code; time is the slicer's estimate. F3 is gated outer edge only (the owner's "
    "decision, Task 7): the silhouette's edge coverage and overprint and each tool's "
    "overprint are required; each tool's coverage and all connectivity are warnings "
    "(the face's warnings). Glue plates are sliced as R1 parts. "
    "F6.portability runs PrusaSlicer 2.9.7 on model.3mf when --prusaslicer-dir or "
    "TDMG_PRUSASLICER_DIR is given; its volume is information, not a condition. "
    "When any required check FAILs, that G-code is kept as plate_1.gcode.failed; do not "
    "print it.")


def is_colored_folder(folder) -> bool:
    """A tdmg flat --colors folder: colored.json and no flat.json."""
    folder = Path(folder)
    return (folder / COLORED_RECORD).exists() and not (folder / "flat.json").exists()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checks(raw, where: str) -> list[CheckResult]:
    """CheckResults from a record's check dicts, each validated. SlicerError if not."""
    if not isinstance(raw, list):
        raise SlicerError(f"{COLORED_RECORD}: {where} has no list of checks")
    out = []
    for c in raw:
        if not isinstance(c, dict) or not isinstance(c.get("id"), str):
            raise SlicerError(f"{COLORED_RECORD}: a check of {where} is not valid: {c!r}")
        if c.get("status") not in STATUSES:
            raise SlicerError(f"{COLORED_RECORD}: check {c['id']} of {where} has status "
                              f"{c.get('status')!r}, not one of {STATUSES}")
        try:
            check = CheckResult(**c)
        except TypeError as err:
            raise SlicerError(f"{COLORED_RECORD}: check {c['id']} of {where} is not valid: "
                              f"{err}") from None
        if check.id == THIN_REGIONS:
            check = replace(check, note=_thin_regions_note(check.note))
        out.append(check)
    return out


def _row_facts(row: dict, path: Path) -> None:
    """A body row's mesh facts and checks, as the colored path reads them (the AMS rows'
    parts and volume for F6.portability, the glue rows' facts for PrusaSlicer and their
    checks for the verdict). SlicerError naming colored.json if any is not valid."""
    def count(v):
        return isinstance(v, int) and not isinstance(v, bool) and v >= 1

    def number(v):
        return (isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v))
    extents = row.get("extents_mm")
    ok = {"bodies": count(row.get("bodies")), "triangles": count(row.get("triangles")),
          "extents_mm": (isinstance(extents, list) and len(extents) == 3
                         and all(number(v) for v in extents)),
          "volume_mm3": number(row.get("volume_mm3"))}
    bad = [name for name, good in ok.items() if not good]
    if bad:
        raise SlicerError(f"{path}: body row {row['file']} is missing or has invalid: "
                          f"{', '.join(bad)}")
    _checks(row.get("checks"), f"body row {row['file']} (checks)")


def read_colored(colored_dir: Path) -> tuple[dict, bytes, dict[str, bytes]]:
    """colored.json's record and bytes, and every output it lists (name -> bytes), each
    checked against its hash. SlicerError for anything refused (module docstring, 1)."""
    path = colored_dir / COLORED_RECORD
    try:
        raw = path.read_bytes()
        record = json.loads(raw)
    except FileNotFoundError:
        raise SlicerError(f"{path} is missing; slice a tdmg flat --colors output folder") \
            from None
    except (OSError, ValueError) as err:
        raise SlicerError(f"cannot read {path}: {err}") from None
    if not isinstance(record, dict) or record.get("schema") != COLORFLAT_SCHEMA:
        found = record.get("schema") if isinstance(record, dict) else None
        raise SlicerError(f"{path}: schema is {found!r}, not {COLORFLAT_SCHEMA!r}")
    if record.get("algorithm") != COLORFLAT_ALGORITHM:
        raise SlicerError(f"{path}: algorithm is {record.get('algorithm')!r}, not "
                          f"{COLORFLAT_ALGORITHM!r}; run tdmg flat --colors again")
    identity = record.get("identity")
    if not isinstance(identity, dict) or identity.get("algorithm") != COLORFLAT_ALGORITHM:
        raise SlicerError(f"{path} is inconsistent: its identity is not a "
                          f"{COLORFLAT_ALGORITHM} identity")
    try:
        recomputed = colorflat_id(identity)
    except ValueError as err:
        raise SlicerError(f"{path} is inconsistent: its identity cannot be hashed ({err})") \
            from None
    if recomputed != record.get("colorflat_id"):
        raise SlicerError(f"{path} is inconsistent: colorflat_id does not match its identity")
    outputs = record.get("outputs")
    if not isinstance(outputs, dict) or not all(_is_hex64(v) for v in outputs.values()):
        raise SlicerError(f"{path} has no valid outputs (name -> SHA-256)")
    glue = record.get("glue")
    if not isinstance(glue, dict) or not isinstance(glue.get("built"), bool):
        raise SlicerError(f"{path} has no valid glue section")
    required = COLORED_REQUIRED_CHECKS if glue["built"] else \
        COLORED_REQUIRED_CHECKS - GLUE_ONLY_CHECKS
    if record.get("required_checks") != sorted(required):
        raise SlicerError(f"{path} is inconsistent: required_checks is not the set tdmg flat "
                          "--colors gives for its glue section")
    bodies = record.get("bodies")
    if not isinstance(bodies, list) or not bodies:
        raise SlicerError(f"{path} has no body rows")
    for b in bodies:
        if not (isinstance(b, dict) and isinstance(b.get("file"), str)
                and b["file"] in outputs and b.get("route") in ("ams", "glue")
                and isinstance(b.get("name"), str) and isinstance(b.get("hex"), str)
                and isinstance(b.get("index"), int) and b.get("role") in
                ("base", "inlay", "pieces")):
            raise SlicerError(f"{path}: a body row is not valid or its file is not among "
                              f"the outputs: {b.get('file') if isinstance(b, dict) else b!r}")
        _row_facts(b, path)
    for route, roles in (("ams", ("base", "inlay")), ("glue", ("base", "pieces"))):
        rows = [b for b in bodies if b["route"] == route]
        if rows and (any(b["role"] not in roles for b in rows)
                     or sum(b["role"] == "base" for b in rows) != 1):
            raise SlicerError(f"{path}: the {route} rows need one base and roles {roles}")
    if any(b["route"] == "glue" for b in bodies) != glue["built"]:
        raise SlicerError(f"{path} is inconsistent: glue rows and the glue section disagree")
    m3 = record.get("model_3mf")
    if (not isinstance(m3, dict) or m3.get("file") != MODEL_3MF
            or m3.get("palette") != PALETTE_NAME or MODEL_3MF not in outputs
            or PALETTE_NAME not in outputs or not isinstance(m3.get("shells"), list)):
        raise SlicerError(f"{path} has no valid model_3mf section")
    files = {}
    for name, expected in outputs.items():
        if Path(name).name != name or name == COLORED_RECORD:
            raise SlicerError(f"{path}: output name {name!r} is not a plain file name")
        try:
            data = (colored_dir / name).read_bytes()
        except FileNotFoundError:
            raise SlicerError(f"{colored_dir / name} is missing ({COLORED_RECORD} lists it); "
                              "run tdmg flat --colors again") from None
        except OSError as err:
            raise SlicerError(f"cannot read {colored_dir / name}: {err}") from None
        actual = _sha(data)
        if actual != expected:
            raise SlicerError(f"{colored_dir / name} has sha256 {actual}, which does not "
                              f"match {COLORED_RECORD} ({expected}): it changed after tdmg "
                              "flat --colors; run it again")
        files[name] = data
    return record, raw, files


def ams_shells(record: dict, files: dict[str, bytes]) -> list[Shell]:
    """The AMS shells as the gate reads them: each AMS STL parsed back and merged exactly,
    in model_3mf.shells order. palette.json must describe exactly these shells."""
    rows = {b["name"]: b for b in record["bodies"] if b["route"] == "ams"}
    names = record["model_3mf"]["shells"]
    if sorted(names) != sorted(rows) or len(set(names)) != len(names):
        raise SlicerError(f"{COLORED_RECORD} is inconsistent: model_3mf.shells {names} are "
                          f"not its AMS bodies {sorted(rows)}")
    shells = []
    for name in names:
        row = rows[name]
        try:
            mesh = merge_exact(trimesh.load(io.BytesIO(files[row["file"]]), file_type="stl",
                                            process=False))
        except (ValueError, TypeError, IndexError, AttributeError) as err:
            raise SlicerError(f"{row['file']} cannot be read as an STL: {err}") from None
        shells.append(Shell(name, row["role"], row["index"], row["hex"],
                            np.asarray(mesh.vertices, dtype=np.float32),
                            np.asarray(mesh.faces, dtype=np.int64)))
    try:
        palette = json.loads(files[PALETTE_NAME])
        listed = [(s["shell"], s["body"], s["role"], s["index"], s["hex"])
                  for s in palette["shells"]]
        ok = (palette["model_3mf_sha256"] == _sha(files[MODEL_3MF])
              and palette["colorflat_id"] == record["colorflat_id"])
    except (ValueError, KeyError, TypeError) as err:
        raise SlicerError(f"{PALETTE_NAME} cannot be read: {err}") from None
    want = [(i, s.name, s.role, s.index, s.hex) for i, s in enumerate(shells)]
    if listed != want or not ok:
        raise SlicerError(f"{PALETTE_NAME} does not describe the AMS shells of "
                          f"{COLORED_RECORD} and model.3mf")
    return shells


def filament_profiles(pinned: bytes, fmap: list[dict]) -> list[dict]:
    """The derived filament profiles, in filament_map order: {"filament", "file", "bytes",
    "sha256", "filament_colour", "differs_from_pinned_in"}. Each is the pinned profile's
    JSON with only filament_colour set to [the color's hex in upper case], written as Task
    2 wrote it (json.dumps, indent 1). SlicerError if the parsed result differs from the
    pinned profile in any other key."""
    base = json.loads(pinned)
    out = []
    for f in fmap:
        colour = [f["hex"].upper()]
        data = json.dumps({**base, FILAMENT_KEY: colour}, indent=1).encode("utf-8")
        back = json.loads(data)
        differs = sorted(k for k in set(base) | set(back) if base.get(k, ...) != back.get(k, ...))
        if any(k != FILAMENT_KEY for k in differs) or back[FILAMENT_KEY] != colour:
            raise SlicerError(f"the derived filament profile {f['filament']} differs from the "
                              f"pinned one in {differs}, not only {FILAMENT_KEY}")
        out.append({"filament": f["filament"],
                    "file": f"{FILAMENT_FOLDER}/filament-{f['filament']}.json", "bytes": data,
                    "sha256": _sha(data), FILAMENT_KEY: colour,
                    "differs_from_pinned_in": differs})
    return out


def color_slicer_args(model: str, machine: str, process: str, filaments: list[str],
                      out_dir: str, log: str) -> list[str]:
    """tdmg.slicer.slicer_args' measured form, with the filaments joined by ";" (Task 2)."""
    return [model, "--load-settings", f"{machine};{process}", "--load-filaments",
            ";".join(filaments), "--slice", "0", "--outputdir", out_dir,
            "--export-statistics", "--logfile", log]


def command_template(n: int) -> list[str]:
    """The OrcaSlicer command as recorded: placeholders, so the record holds no path."""
    return ["<orca-slicer.exe>", *color_slicer_args(
        f"<{ORCA_INPUT_NAME}>", "<machine.json>", "<process.json>",
        [f"<filament-{i + 1}.json>" for i in range(n)], "<outdir>", f"<{LOG_NAME}>")]


def z_extent(shells: list[Shell]) -> tuple[float, float]:
    z = np.concatenate([np.asarray(s.vertices, np.float32)[:, 2] for s in shells])
    return float(z.astype(np.float64).min()), float(z.astype(np.float64).max())


def allowed_counts(shells: list[Shell], process: dict) -> set[int]:
    """tdmg.slicing.allowed_layer_counts' rule on the bodies' z extent as stored."""
    z_min, z_max = z_extent(shells)
    zabs = max(abs(z_min), abs(z_max))
    return expected_layer_counts(z_max - z_min, process,
                                 storage_error_mm=2 * STL_COORD_RTOL * zabs)


def _portability(ctx: Context, model_3mf: bytes, shells: list[Shell], rows: list[dict],
                 allowed) -> tuple[CheckResult, dict, bytes | None, dict | None]:
    """F6.portability on model.3mf: the check, its record section, PrusaSlicer's G-code and
    the identity section."""
    prusa = ctx.prusa
    if prusa is None:
        check = not_configured_check()
        return check, {"configured": False, "reason": check.note, "note": PRUSA_GCODE_NOTE,
                       "model": MODEL_3MF, "slicer": None, "settings": None,
                       "commands": None, "expected": None, "tolerances": None, "info": None,
                       "gcode": None}, None, None
    settings = ctx.settings()
    verts = np.concatenate([np.asarray(s.vertices, np.float32) for s in shells]
                           ).astype(np.float64)
    expected = Expected(
        parts=sum(int(r["bodies"]) for r in rows), facets=sum(len(s.faces) for s in shells),
        size_mm=[float(v) for v in verts.max(axis=0) - verts.min(axis=0)],
        volume_mm3=float(sum(float(r["volume_mm3"]) for r in rows)),
        layer_counts=sorted(allowed),
        first_layer_mm=float(ctx.process["initial_layer_print_height"]),
        layer_mm=float(ctx.process["layer_height"]),
        size_tol_mm=size_tolerance_mm(float(np.abs(verts).max())), volume_tol_mm3=None)
    with tempfile.TemporaryDirectory(prefix="tdmg-colorslice-prusa-") as tmp:
        base = Path(tmp)
        model = base / MODEL_3MF
        model.write_bytes(model_3mf)        # the bytes whose hash was checked
        (base / "prusa").mkdir()
        info_run, gcode_run, gcode = run_portability(
            _slicing.prusa_command(prusa), model, settings, base / "prusa",
            ctx.prusa_timeout["value"], prusa, placeholder=f"<{MODEL_3MF}>")
    check, measurements = portability_check(
        info_run, gcode_run, gcode, expected, ctx.prusa_timeout["rule"], model=MODEL_3MF,
        source="the AMS bodies of colored.json", meaning=COLOR_PORTABILITY_MEANING,
        volume_note=VOLUME_NOTE)
    commands = command_templates(settings, f"<{MODEL_3MF}>")
    section = {"configured": True, "reason": None, "note": PRUSA_GCODE_NOTE,
               "model": MODEL_3MF,
               "slicer": {"name": prusa.pin.name, "pin": prusa.pin.id, **prusa.identity()},
               "settings": settings, "commands": commands,
               "expected": {**expected.as_dict(), "volume_judged": False,
                            "volume_note": VOLUME_NOTE, "size_note": SIZE_NOTE},
               "tolerances": measurements["tolerances"], "info": measurements["info"],
               "gcode": measurements["gcode"]}
    identity = {"slicer": prusa.identity(),
                "settings": {k: v["value"] for k, v in settings.items()},
                "commands": commands, "volume_judged": False}
    return check, section, gcode, identity


def _face_summary(checks: list[CheckResult]) -> dict:
    by = {c.id: c for c in checks}

    def get(cid, key):
        m = by[cid].measured if cid in by else None
        return m.get(key) if isinstance(m, dict) else None
    return {"changes": get(COLOR_CHANGES, "changes"),
            "flush_mm3": get(COLOR_WASTE, "flush_mm3"),
            "prime_tower_mm3": get(COLOR_WASTE, "prime_tower_mm3"),
            "time_s": get(COLOR_TIME, "total_estimated_time_s")}


def slice_face(ctx: Context, face: str, shells: list[Shell], filaments: list[dict],
               inherited: list[CheckResult], inherited_required: frozenset[str],
               portability: CheckResult, allowed) -> dict:
    """One face: orca-input.3mf, its gate check, the OrcaSlicer run and the checks.
    Returns {"record", "files" (by path in the output folder), "identity"}."""
    folder = FACE_FOLDER[face]
    orca = write_orca_input(shells)
    f2 = orca_input_check(orca, shells)
    fmap = filament_map(shells)
    setup = ctx.setup(allowed)
    with tempfile.TemporaryDirectory(prefix="tdmg-colorslice-") as tmp:
        base = Path(tmp)
        (base / "work").mkdir()
        (base / "profiles").mkdir()
        model = base / ORCA_INPUT_NAME
        model.write_bytes(orca)
        paths = {}
        for kind in ("machine", "process"):
            paths[kind] = base / "profiles" / ctx.slicer.profiles[kind].name
            paths[kind].write_bytes(ctx.profile_data[kind])
        fils = []
        for f in filaments:
            p = base / "profiles" / Path(f["file"]).name
            p.write_bytes(f["bytes"])
            fils.append(str(p.resolve()))
        work = (base / "work").resolve()
        out_dir, log = work / "out", work / LOG_NAME
        out_dir.mkdir()
        if any(";" in p for p in (*fils, str(paths["machine"].resolve()),
                                   str(paths["process"].resolve()))):
            raise SlicerError(f"a profile path in {base} contains ';', which "
                              "--load-settings and --load-filaments cannot take")
        args = [*_slicing.slicer_command(ctx.slicer), *color_slicer_args(
            str(model.resolve()), str(paths["machine"].resolve()),
            str(paths["process"].resolve()), fils, str(out_dir), str(log))]
        returncode, timed_out, out, err = run_process(args, work, ctx.timeout["value"])
        run = SlicerRun(args, returncode, timed_out, ctx.timeout["value"], output_tail(out),
                        output_tail(err), out_dir, log)
        f6, stats = f6_checks(run, allowed, ctx.pin, timeout_rule=ctx.timeout["rule"])
        gcode = ((out_dir / GCODE_NAME).read_bytes()
                 if (out_dir / GCODE_NAME).is_file() else None)
        raw_stats = None
        if stats is not None:              # f6_checks read it; read it again as raw JSON
            raw_stats = json.loads((out_dir / STATS_NAME).read_bytes())
        exited = next(c for c in f6 if c.id == "F6.slicer_exit").status == "PASS"
        color, color_record = color_slice_checks(
            gcode, shells, setup, raw_stats,
            None if exited else "the slicer failed (F6.slicer_exit)")
        counted = len(color_record["layers"]) if color_record["measured"] else None
        f6 = _cross_check_layers(f6, stats, {"layer_count": counted})
        stats_bytes = ((out_dir / STATS_NAME).read_bytes()
                       if (out_dir / STATS_NAME).is_file() else None)
        log_bytes = log.read_bytes() if log.is_file() else None
    checks = [*inherited, f2, *color, *f6, portability]
    required = (inherited_required | {ORCA_CHECK} | required_check_ids(len(shells))
                | SLICER_F6_IDS | {"F6.portability"})
    quarantined = any(c.status == "FAIL" for c in checks if c.id in required)
    files = {f"{folder}/{ORCA_INPUT_NAME}": orca}
    gcode_name = None
    if gcode is not None:
        gcode_name = FAILED_GCODE_NAME if quarantined else GCODE_NAME
        files[f"{folder}/{gcode_name}"] = gcode
    if stats_bytes is not None:
        files[f"{folder}/{STATS_NAME}"] = stats_bytes
    if log_bytes is not None:
        files[f"{folder}/{LOG_NAME}"] = log_bytes
    cert = certification(checks, required, ctx.trees_verified())
    z_min, z_max = z_extent(shells)
    record = {
        "face": face, "folder": folder,
        "orca_input": {"file": f"{folder}/{ORCA_INPUT_NAME}", "sha256": _sha(orca),
                       "encoding": ORCA_ENCODING, "note": ORCA_INPUT_NOTE},
        "filament_map": fmap,
        "verdict": "PRINTABLE" if cert == "PRINTABLE" else "NOT CERTIFIED",
        "certification": cert,
        "certification_note": COLOR_PRINTABLE_MEANING if cert == "PRINTABLE" else None,
        "required_checks": sorted(required),
        "summary": _face_summary(color),
        "warnings": face_warnings(color, fmap),
        "params": {"z_mm": {"min": z_min, "max": z_max, "extent": z_max - z_min},
                   "expected_layer_counts": sorted(allowed)},
        "exit": {**_exit_code(run, ctx.pin), "timed_out": run.timed_out},
        "stats": stats,
        "checks": [c.as_dict() for c in checks],
        "color": color_record,
        "gcode": (None if gcode_name is None else
                  {"file": f"{folder}/{gcode_name}", "quarantined": quarantined,
                   **gcode_hashes(gcode)}),
        "stderr_tail": run.stderr, "log_written": log_bytes is not None}
    return {"record": record, "files": files, "quarantined": quarantined,
            "identity": {"orca_input_sha256": _sha(orca)}}


def glue_piece_counts(record: dict) -> dict[str, int]:
    """The number of bodies each glue plate must have, by STL name: 1 for the glue base;
    for a color's plate, its pieces in the glue report. SlicerError unless the report's
    per-color counts ("colors": pieces) and its piece list ("pieces": index) agree, and
    every glue plate has its count."""
    report = record["glue"].get("report")
    try:
        per_color = {int(c["index"]): int(c["pieces"]) for c in report["colors"]}
        listed: dict[int, int] = {}
        for piece in report["pieces"]:
            listed[int(piece["index"])] = listed.get(int(piece["index"]), 0) + 1
        dup = len(per_color) != len(report["colors"])
    except (KeyError, TypeError, ValueError) as err:
        raise SlicerError(f"{COLORED_RECORD}: the glue report gives no piece count per "
                          f"color ({err})") from None
    if dup or {k: v for k, v in per_color.items() if v} != listed:
        raise SlicerError(f"{COLORED_RECORD}: the glue report's pieces per color "
                          f"{per_color} disagree with its piece list {listed}")
    plates = {row["index"] for row in record["bodies"]
              if row["route"] == "glue" and row["role"] == "pieces"}
    reported = {k for k, v in per_color.items() if v}
    rows = [row["index"] for row in record["bodies"]
            if row["route"] == "glue" and row["role"] == "pieces"]
    twice = sorted({i for i in rows if rows.count(i) > 1})
    if twice:
        raise SlicerError(f"{COLORED_RECORD}: two glue plate rows for color(s) {twice}")
    if reported - plates:
        raise SlicerError(f"{COLORED_RECORD}: the glue report has pieces for colors "
                          f"{sorted(reported - plates)} with no glue plate row (a glue "
                          "print needs every plate)")
    out = {}
    for row in record["bodies"]:
        if row["route"] != "glue":
            continue
        if row["role"] == "base":
            out[row["file"]] = 1
        elif per_color.get(row["index"], 0) >= 1:
            out[row["file"]] = per_color[row["index"]]
        else:
            raise SlicerError(f"{COLORED_RECORD}: the glue report has no pieces for "
                              f"{row['file']}")
    return out


def glue_body_count_check(stl: bytes, expected: int) -> CheckResult:
    """F4.body_count for a glue plate: the bodies of its STL, read as the gate reads it
    (parsed back and merged exactly; tdmg.flat's count of connected bodies), must be the
    plate's pieces in the glue report (1 for the base)."""
    mesh = merge_exact(trimesh.load(io.BytesIO(stl), file_type="stl", process=False))
    n = body_count(mesh)
    how = ("bodies in the plate's STL against its pieces in colored.json's glue report "
           "(1 for the glue base)")
    return CheckResult(BODY_COUNT, "PASS" if n == expected else "FAIL", n, expected, None,
                       how if n == expected else f"{how}: {n} bodies, not {expected}")


def slice_glue_plate(ctx: Context, record: dict, colored_sha: str, row: dict, stl: bytes,
                     assembly: list[CheckResult], pieces: int,
                     required: frozenset[str] = GLUE_REQUIRED_CHECKS) -> dict:
    """One glue plate as an R1 part (tdmg.slicing.slice_stl), with R1's checks and
    required set except F2.target_width (not applicable), and F4.body_count against the
    plate's pieces. Its files go in a folder named after the STL."""
    folder = row["file"].removesuffix(".stl")
    previous = (_checks(row.get("checks"), row["file"]) + assembly
                + [glue_body_count_check(stl, pieces)])
    mesh = {k: row.get(k) for k in ("bodies", "triangles", "extents_mm", "volume_mm3")}
    part = slice_stl(ctx, stl, previous, mesh, required=required,
                     model_name=row["file"], source="colored.json")
    z_min, z_max = part["z"]
    identity = {"algorithm": SLICE_ALGORITHM_VERSION, "colorflat_id": record["colorflat_id"],
                "colored_record_sha256": colored_sha, "plate": row["file"],
                "model_stl_sha256": _sha(stl), "slicer": ctx.slicer_identity(),
                "profiles": ctx.profile_hashes(), "command": COMMAND_TEMPLATE,
                "f3": ctx.f3_identity(), "required": sorted(required),
                "expected_bodies": pieces, **part["identity"]}
    files = {f"{folder}/{name}": data for name, data in part["files"].items()}
    rec = part["record"]
    if rec["gcode"] is not None:
        rec["gcode"] = {**rec["gcode"], "file": f"{folder}/{rec['gcode']['file']}"}
    if rec["portability"]["gcode"] is not None and rec["portability"]["gcode"]["file"]:
        rec["portability"]["gcode"]["file"] = f"{folder}/{rec['portability']['gcode']['file']}"
    plate = {
        "plate": row["file"], "folder": folder, "algorithm": SLICE_ALGORITHM_VERSION,
        "slice_id": _sha(canonical_json(identity)),
        "links": {"colorflat_id": record["colorflat_id"],
                  "colored_record_sha256": colored_sha, "model_stl_sha256": _sha(stl)},
        "role": row["role"], "index": row["index"], "hex": row["hex"],
        "params": {"thickness_mm": None,
                   "thickness_note": "a glue plate has no requested thickness of its own; "
                                     "its layer counts come from its STL's z extent",
                   "stl_z_mm": {"min": z_min, "max": z_max, "extent": z_max - z_min},
                   "expected_layer_counts": sorted(part["allowed"])},
        "required_checks": sorted(required),
        "not_applicable": {TARGET_WIDTH: TARGET_WIDTH_NA},
        "inherited_note": ("R1's checks (plan Decision 5). The inherited checks are this "
                           "plate's body checks and the glue assembly's from colored.json, "
                           "plus F4.body_count against the plate's pieces in the glue "
                           "report; F2.target_width is not applicable."),
        "command": COMMAND_TEMPLATE, **rec}
    return {"record": plate, "files": files, "slice_id": plate["slice_id"]}


def make_color_slice(colored_dir, out_dir, slicer_dir=None, timeout_s=None,
                     check_tree: bool = True, prusaslicer_dir=None,
                     face: str = DEFAULT_FACE) -> dict:
    """Slice a tdmg flat --colors folder (module docstring) and write, in out_dir:
    face-up/ and face-down/ (orca-input.3mf, plate_1.gcode or plate_1.gcode.failed, the
    statistics, the log when written), filaments/ (the derived filament profiles), one
    folder per glue plate (R1's files), PrusaSlicer's G-code from model.3mf, and slice.json
    last. Returns the record. SlicerError for a refused input, with nothing written.
    face: "up" (the default, the owner's decision of 2026-11-13), "down" or "both"; only
    the faces sliced are in the record and in colorslice_id ("faces")."""
    colored_dir = Path(colored_dir)
    _timeout(timeout_s, load_rules())                  # refused before anything else
    if face not in FACE_CHOICES:
        raise SlicerError(f"face must be one of {sorted(FACE_CHOICES)}, not {face!r}")
    sliced = FACE_CHOICES[face]
    record_in, raw, files_in = read_colored(colored_dir)
    shells = ams_shells(record_in, files_in)
    model_3mf = files_in[MODEL_3MF]
    model_check = export_3mf_check(model_3mf, shells)
    if model_check.status != "PASS":
        raise SlicerError(f"the AMS STLs rebuilt as the gate reads them do not match "
                          f"model.3mf ({model_check.id} {model_check.status}: "
                          f"{model_check.note})")
    ams_rows = {b["name"]: b for b in record_in["bodies"] if b["route"] == "ams"}
    rows = [ams_rows[s.name] for s in shells]
    assembly = record_in.get("assembly") if isinstance(record_in.get("assembly"), dict) \
        else {}
    inherited = [c for r in rows for c in _checks(r.get("checks"), r["file"])]
    inherited += [c for c in _checks(assembly.get("ams"), "assembly.ams")
                  if c.id != "F6.slicer"]
    inherited_required = frozenset(record_in["required_checks"]) - GLUE_ONLY_CHECKS \
        - INHERITED_DROPPED
    glue_assembly = [c for c in _checks(assembly.get("glue", []), "assembly.glue")
                     if c.id != "F6.slicer"]
    pieces = glue_piece_counts(record_in) if record_in["glue"]["built"] else {}
    # A glue plate requires R1's set (less F2.target_width) and the record's required
    # glue-only checks (the glue assembly's F4.glue_fit and F4.glue_partition), as a face
    # requires the record's AMS checks.
    glue_required = GLUE_REQUIRED_CHECKS | (frozenset(record_in["required_checks"])
                                            & GLUE_ONLY_CHECKS)
    try:
        create_folder = check_output_dir(out_dir)
    except RecordError as err:
        raise SlicerError(str(err)) from None
    ctx = prepare(slicer_dir, timeout_s, check_tree, prusaslicer_dir)
    fmap = filament_map(shells)
    filaments = filament_profiles(ctx.profile_data["filament"], fmap)
    colored_sha = _sha(raw)
    faces = {"up": shells, "down": turn_over(shells) if "down" in sliced else None}
    allowed = allowed_counts(shells, ctx.process)
    if "down" in sliced and allowed_counts(faces["down"], ctx.process) != allowed:
        raise SlicerError("the turned bodies allow other layer counts than face up")

    portability, port_section, prusa_gcode, port_identity = _portability(
        ctx, model_3mf, shells, rows, allowed)
    files: dict[str, bytes] = {f["file"]: f["bytes"] for f in filaments}
    prusa_quarantined = any(c.status == "FAIL" for c in [*inherited, portability]
                            if c.id in inherited_required | {"F6.portability"})
    if prusa_gcode is not None:
        name = PRUSA_FAILED_GCODE_NAME if prusa_quarantined else PRUSA_GCODE_NAME
        files[name] = prusa_gcode
        port_section["gcode"] = {**port_section["gcode"], "file": name,
                                 "quarantined": prusa_quarantined,
                                 **prusa_gcode_hashes(prusa_gcode)}
    elif port_section["gcode"] is not None:
        port_section["gcode"] = {**port_section["gcode"], "file": None, "quarantined": None,
                                 "sha256": None, "normalised_sha256": None,
                                 "normalised_lines": None}
    port_section["check"] = portability.as_dict()

    face_records, face_ids = {}, {}
    for side in sliced:
        done = slice_face(ctx, side, faces[side], filaments, inherited, inherited_required,
                          portability, allowed)
        face_records[side] = done["record"]
        face_ids[side] = done["identity"]
        files.update(done["files"])

    plates = {}
    glue = record_in["glue"]
    for row in record_in["bodies"]:
        if row["route"] != "glue":
            continue
        done = slice_glue_plate(ctx, record_in, colored_sha, row, files_in[row["file"]],
                                glue_assembly, pieces[row["file"]], glue_required)
        plates[done["record"]["folder"]] = done["record"]
        files.update(done["files"])

    template = command_template(len(shells))
    identity = {"algorithm": COLORSLICE_ALGORITHM, "colorflat_id": record_in["colorflat_id"],
                "colored_record_sha256": colored_sha,
                "faces": {f: face_ids[f] for f in sliced},
                "slicer": ctx.slicer_identity(), "profiles": ctx.profile_hashes(),
                "filaments": [f["sha256"] for f in filaments], "command": template,
                "f3": ctx.f3_identity(), "portability": port_identity,
                "glue_plates": {name: p["slice_id"] for name, p in plates.items()}}
    pinned = ctx.profile_data["filament"]
    z_min, z_max = z_extent(shells)
    record = {
        "schema": COLOR_RECORD_SCHEMA, "tdmg_version": __version__,
        "algorithm": COLORSLICE_ALGORITHM,
        "colorslice_id": _sha(canonical_json(identity)),
        "links": {"colorflat_id": record_in["colorflat_id"],
                  "colored_record_sha256": colored_sha,
                  "model_3mf_sha256": _sha(model_3mf),
                  "palette_sha256": _sha(files_in[PALETTE_NAME]),
                  "colors_id": record_in["identity"].get("colors_id"),
                  "selection_id": record_in["identity"].get("selection_id")},
        "params": {"face": face, "timeout_s": ctx.timeout,
                   "prusaslicer_timeout_s": ctx.prusa_timeout,
                   "thickness_mm": (record_in["identity"].get("params") or {}).get(
                       "thickness_mm"),
                   "z_mm": {"min": z_min, "max": z_max, "extent": z_max - z_min},
                   "expected_layer_counts": sorted(allowed)},
        "slicer": ctx.slicer_record(),
        "command": template,
        "filament_map": fmap,
        "filaments": {"note": FILAMENT_NOTE, "pinned_sha256": _sha(pinned),
                      "profiles": [{k: v for k, v in f.items() if k != "bytes"}
                                   for f in filaments]},
        "model_3mf": {"file": MODEL_3MF, "sha256": _sha(model_3mf),
                      "check": model_check.as_dict(),
                      "note": "the file to print from: open it in Bambu Studio and give "
                              "each color the filament in filament_map"},
        "inherited": {"required": sorted(inherited_required),
                      "note": "every AMS body's checks and the AMS assembly's from "
                              "colored.json, minus F6.slicer; F3.thin_regions is "
                              "information only"},
        "portability": port_section,
        "faces": face_records,
        "glue": {"built": glue["built"], "reason": glue.get("reason"), "plates": plates,
                 "route": glue_route(plates) if glue["built"] else None},
        "verdicts": {**{FACE_FOLDER[f]: face_records[f]["verdict"] for f in sliced},
                     **{name: p["verdict"] for name, p in plates.items()}},
        "outputs": {name: _sha(data) for name, data in files.items()},
        "environment": {**environment(), "platform": platform.platform()},
        "review": COLOR_REVIEW,
    }
    store(record, out_dir, files, create_folder, subfolders=True)
    return record


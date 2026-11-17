"""What a confirmation covers, read from a job folder, and whether it is still current
(restructure plan Task 8; design docs/plans/2026-11-16-restructure-design.md section 4).

The entry schema is in tdmg.jobs (its module docstring); tdmg.job_runner.confirm writes
entries and job_status reports them. This module only reads files.

**What is covered.** Each covered file is hashed from disk, never taken from a record:
- selection: select/selection.json and select/preview.png;
- colors: colors/colors.json and colors/regions.png;
- print: the route's printable files (tdmg.recipes Route.required_files) in the print
  stage's folder (tdmg.jobs.print_stage): single, flat/model.stl; ams,
  colored_flat/model.3mf and colored_flat/palette.json (the palette says which shell is
  which color); glue, every glue plate colored_flat/glue-*.stl that colored.json lists.
  A print entry also holds the slice record's identity (slice_id for R1, colorslice_id for
  R2) and the verdict for each printed model file: single, slice.json's verdict; ams,
  faces.<face>.verdict; glue, each plate's verdict in glue.plates. slice.json's own bytes
  are not covered: they hold G-code hashes, and G-code holds the time of slicing.

Before anything is covered, each file on disk must be the one its record names: a
non-print file must match its record's `outputs` hash (preview.png in selection.json,
regions.png in colors.json); a print file must match the slice record's links
(links.model_stl_sha256 for R1 and for each glue plate, links.model_3mf_sha256 and
links.palette_sha256 for ams). So a verdict is never bound to a file other than the one
sliced, and a hand-edited file is refused.

**Staleness** (current_problem) is computed each time, never stored: an entry is stale
when a covered file is missing or its SHA-256 differs from the entry's, or, for print,
when what the entry covers would now be different: the slice record's identity, a
verdict, the set of glue plates, or a printable file no longer matching the slice
record. A rerun that writes the same bytes leaves the entry current.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from tdmg import jobs
from tdmg.jobs import JobError
from tdmg.recipes import recipe

SLICE_RECORD = "slice/slice.json"
# The record that names each non-print subject's other file in its `outputs`.
SUBJECT_RECORD = {"selection": ("select/selection.json", "select/preview.png"),
                  "colors": ("colors/colors.json", "colors/regions.png")}
COLORED_RECORD = "colored_flat/colored.json"
# The slice record's identity field, by whether the recipe is multicolor (R2) or not (R1).
IDENTITY_FIELD = {False: "slice_id", True: "colorslice_id"}


def sha256_file(folder: Path, rel: str) -> str:
    """The SHA-256 of folder/rel; JobError when it is not a file."""
    path = folder / rel
    if not path.is_file():
        raise JobError(f"{rel} is missing from {folder}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(folder: Path, rel: str) -> dict:
    path = folder / rel
    if not path.is_file():
        raise JobError(f"{rel} is missing from {folder}")
    try:
        data = json.loads(path.read_bytes())
    except (ValueError, UnicodeDecodeError):
        raise JobError(f"{rel} is not JSON") from None
    if not isinstance(data, dict):
        raise JobError(f"{rel} is not a JSON object")
    return data


def _get(data, *path):
    for p in path:
        if not isinstance(data, dict):
            return None
        data = data.get(p)
    return data


def _must_match(rel: str, digest: str, want, what: str) -> None:
    if digest != want:
        raise JobError(f"{rel} on disk is not the file {what} names (its SHA-256 is "
                       f"{digest}, {what} says {want}); run tdmg job run again")


def subject_covers(folder: Path, subject: str) -> dict[str, str]:
    """{path: SHA-256} for a selection or colors confirmation, checked against the record."""
    record_rel, other = SUBJECT_RECORD[subject]
    covers = {rel: sha256_file(folder, rel) for rel in jobs.SUBJECT_FILES[subject]}
    record = _json(folder, record_rel)
    name = other.rpartition("/")[2]
    _must_match(other, covers[other], _get(record, "outputs", name), record_rel)
    return covers


@dataclass(frozen=True)
class PrintCover:
    covers: dict[str, str]          # path -> SHA-256, from disk
    slice_id: str
    verdicts: dict[str, str]        # printed model path -> slice verdict


def default_route(recipe_id: str) -> str:
    """The route a print confirmation takes unless told: the recipe's first (R1 single,
    R2 ams)."""
    return recipe(recipe_id).routes[0].name


def print_cover(folder: Path, job: dict, route_name: str, face: str | None) -> PrintCover:
    """What a print confirmation of this route (and face) covers now; JobError when it
    cannot be bound (module docstring)."""
    rid = job["recipe"]
    r = recipe(rid)
    try:
        route = r.route(route_name)
    except KeyError as e:
        raise JobError(e.args[0]) from None
    if route.name in jobs.FACED_ROUTES:
        if face not in jobs.CONFIRM_FACES:
            raise JobError(f"route {route.name} needs --face up or --face down: the face "
                           "the owner printed (say which; it is not guessed)")
    elif face is not None:
        raise JobError(f"route {route.name} has no face; leave out --face")
    stage = jobs.print_stage(rid)
    colored = "colored_flat" in r.stages
    rec = _json(folder, SLICE_RECORD)
    identity = rec.get(IDENTITY_FIELD[colored])
    if not isinstance(identity, str) or jobs.HEX64.fullmatch(identity) is None:
        raise JobError(f"{SLICE_RECORD} has no {IDENTITY_FIELD[colored]}")
    if route.record is None:
        names = route.files
    else:
        try:
            names = route.required_files(_json(folder, f"{stage}/{route.record}"))
        except ValueError as e:
            raise JobError(str(e)) from None
    covers = {f"{stage}/{n}": sha256_file(folder, f"{stage}/{n}") for n in names}
    verdicts: dict[str, str] = {}
    if route.name == "single":
        rel = f"{stage}/model.stl"
        _must_match(rel, covers[rel], _get(rec, "links", "model_stl_sha256"), SLICE_RECORD)
        verdicts[rel] = rec.get("verdict")
    elif route.name == "ams":
        for name, link in (("model.3mf", "model_3mf_sha256"),
                           ("palette.json", "palette_sha256")):
            rel = f"{stage}/{name}"
            _must_match(rel, covers[rel], _get(rec, "links", link), SLICE_RECORD)
        faces = rec.get("faces") if isinstance(rec.get("faces"), dict) else {}
        if face not in faces:
            sliced = ", ".join(f for f in jobs.CONFIRM_FACES if f in faces) or "none"
            raise JobError(f"face {face} was not sliced (faces sliced: {sliced}); set "
                           f"slice.face and run tdmg job run again")
        verdicts[f"{stage}/model.3mf"] = _get(faces, face, "verdict")
    elif route.name == "glue":
        plates = _get(rec, "glue", "plates")
        plates = plates if isinstance(plates, dict) else {}
        by_file = {p.get("plate"): p for p in plates.values() if isinstance(p, dict)}
        if sorted(by_file) != sorted(names):
            raise JobError(f"{SLICE_RECORD} glue.plates do not match the glue plates "
                           f"{route.record} lists; run tdmg job run again")
        for name in names:
            rel = f"{stage}/{name}"
            plate = by_file[name]
            _must_match(rel, covers[rel], _get(plate, "links", "model_stl_sha256"),
                        f"{SLICE_RECORD} glue.plates")
            verdicts[rel] = plate.get("verdict")
    else:                                       # a route added to tdmg.recipes later
        raise JobError(f"tdmg job confirm does not know route {route.name} yet")
    bad = {k: v for k, v in verdicts.items() if v not in jobs.VERDICTS}
    if bad:
        raise JobError(f"{SLICE_RECORD} gives no verdict for {', '.join(bad)}")
    return PrintCover(covers, identity, verdicts)


def current_problem(folder: Path, job: dict, entry: dict) -> str | None:
    """Why the confirmation no longer covers what is in the job folder, or None when it is
    current (module docstring)."""
    folder = Path(folder)
    for rel, digest in entry["covers"].items():
        path = folder / rel
        if not path.is_file():
            return f"{rel} is missing"
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return f"{rel} changed"
    if entry["subject"] != "print":
        return None
    try:
        now = print_cover(folder, job, entry["route"], entry["face"])
    except JobError as e:
        return str(e)
    if sorted(now.covers) != sorted(entry["covers"]):
        return "the glue plates changed"
    if now.slice_id != entry["slice_id"]:
        return "the slice is a different one (its identity changed)"
    if now.verdicts != entry["verdicts"]:
        return "a slice verdict changed"
    return None


def describe(entry: dict) -> str:
    """'print (ams, face down)', 'selection', ..."""
    if entry["subject"] != "print":
        return entry["subject"]
    parts = [entry["route"]] + ([f"face {entry['face']}"] if entry["face"] else [])
    if entry["accept_not_certified"]:
        parts.append("accepted NOT CERTIFIED")
    return f"print ({', '.join(parts)})"

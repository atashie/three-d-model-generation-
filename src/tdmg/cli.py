"""Command-line interface. Phase 0 exposes the registries. Phase 1 has `select` (subject
selection for review), `flat` (flat geometry from a selection, gated on the written
STL) and `slice` (the flat STL sliced with the pinned OrcaSlicer, F6, and checked for
portability with the pinned PrusaSlicer). R2 adds `colors` (the color plan of a selection,
for review) and `strip` (the two calibration strips, built, gated and sliced); `make` and
`check` follow. `job new` starts a job: a folder in jobs/ with the source image and
job.yaml (tdmg.jobs); `job set` changes its parameters, `job run` runs its stages,
`job status` shows where it stands and `job confirm` records the owner's confirmation
(tdmg.job_runner). `finish` moves a confirmed print into the library, prints/, and purges
the job; `library check` checks the library's entries and `library verify` runs one again
under the current code and rules (tdmg.library)."""

import inspect
import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from tdmg import __version__
from tdmg.calibration_strip import (
    BASE_STL,
    CLEARANCE_DIR,
    KNOWN_FAILURE_DATE,
    KNOWN_FAILURE_MEASURED,
    KNOWN_FAILURE_PLAIN,
    MODEL_3MF,
    PIECES_STL,
    SKIN_COLOR_NAMES,
    SKIN_DIR,
    TEMPLATE_NAME,
    StripError,
    blocking_failures,
    make_strips,
)
from tdmg.calibration_strip import RECORD_NAME as STRIP_RECORD
from tdmg.color_outline import THIN_SHARE_RULE
from tdmg.color_slicing import (
    DEFAULT_FACE,
    FACE_FOLDER,
    FACES,
    do_not_print,
    is_colored_folder,
    make_color_slice,
    not_chosen_line,
)
from tdmg.colored_flat import RECORD_NAME as COLORED_RECORD
from tdmg.colored_flat import make_colored_flat
from tdmg.colors import COLORS_PRINTER, ColorsError, extracted_text, make_colors
from tdmg.flat import FlatError, make_flat
from tdmg.job_runner import (
    Machine,
    confirm,
    confirmation_line,
    job_status,
    run_job,
    set_parameters,
    status_lines,
    yaml_value,
)
from tdmg.jobs import (
    DEFAULT_ORIGIN,
    JOB_FILE,
    ORIGINS,
    SOURCE_DIR,
    JobError,
    default_jobs_dir,
    job_dir,
    new_job,
    unset_required,
)
from tdmg.library import (
    NOT_COMPARED,
    LibraryError,
    RebuildDiffers,
    check_library,
    finish,
    unavailable_text,
    verify,
)
from tdmg.paths import REPO_ROOT
from tdmg.portability import PRUSA_FAILED_GCODE_NAME, PRUSA_GCODE_NAME, PRUSA_GCODE_NOTE
from tdmg.profiles import load_printer, printer_ids
from tdmg.recipes import ATTRIBUTE_LABELS, CLASSES, RECIPES, class_of, class_status
from tdmg.records import RecordError
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
from tdmg.slicer import GCODE_NAME, SlicerError
from tdmg.slicing import (
    DO_NOT_PRINT,
    FAILED_GCODE_NAME,
    PRINT_THIS,
    PRUSA_DO_NOT_PRINT,
    make_slice,
)

# make_flat's default printer, shown in tdmg flat's help.
FLAT_PRINTER = inspect.signature(make_flat).parameters["printer"].default

app = typer.Typer(help="Image -> FDM-printable 3MF/STL. See docs/guide/00-start-here.md.",
                  no_args_is_help=True)


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command()
def rules() -> None:
    """List every design rule with its value and evidence status."""
    for r in load_rules().values():
        rng = f" [{r.range[0]:g}-{r.range[1]:g}]" if r.range else ""
        typer.echo(f"{r.id:48s} {r.default!s:>9} {r.unit:7s}{rng:14s} {r.kind:10s} "
                   f"{r.best_provenance}/{r.best_validation}")


@app.command()
def recipes() -> None:
    """List the print recipes, their status and output class, then the classes."""
    for r in RECIPES:
        colors = "/".join(c.value for c in r.colors)
        attrs = f"{r.geometry.value}-{r.articulation.value}-{colors}-{r.assembly.value}"
        typer.echo(f"{r.id}  {r.name:24s} {attrs:16s} {r.status.value:12s} "
                   f"{class_of(r.id) or '-':10s} "
                   f"phase {r.roadmap_phase}  ({ATTRIBUTE_LABELS[r.geometry.value]})")
    typer.echo("")
    for name, ids in CLASSES.items():
        typer.echo(f"class {name:10s} {class_status(name).value:12s} {', '.join(ids)}")


@app.command()
def printers() -> None:
    """List printer profiles with their key limits."""
    for pid in printer_ids():
        p = load_printer(pid)
        mm = p.multi_material
        mm_txt = (f"up to {mm.default_max_filaments} filaments by default "
                  f"({', '.join(u.name for u in mm.units)})") if mm else "none"
        bx, by, bz = p.build_volume_mm
        typer.echo(f"{p.id:12s} {p.name:18s} bed {bx:g}x{by:g}x{bz:g} mm  "
                   f"nozzle {p.nozzle_diameter_mm} mm  multi-material: {mm_txt}")


def _points(values: list[str] | None, flag: str) -> tuple[tuple[int, int], ...]:
    out = []
    for v in values or []:
        try:
            x, y = (int(s) for s in v.split(","))
        except ValueError:
            raise typer.BadParameter(f"{flag} expects X,Y in pixels, got {v!r}") from None
        out.append((x, y))
    return tuple(out)


def _os_error(e: OSError) -> None:
    where = f": {e.filename}" if e.filename else ""
    typer.echo(f"error: {e.strerror or e}{where}", err=True)


@app.command()
def select(
    image: Annotated[Path, typer.Argument(exists=True, dir_okay=False,
                                          help="PNG or JPEG input.")],
    out: Annotated[Path, typer.Option("--out", help="New or empty folder for the outputs.")],
    instructions: Annotated[str | None, typer.Option(
        help="What should become the model, in your words. Stored verbatim; "
             "code does not interpret it.")] = None,
    remove_at: Annotated[list[str] | None, typer.Option(
        "--remove-at", help="X,Y: remove the colour region at this pixel. Repeatable.")] = None,
    keep_at: Annotated[list[str] | None, typer.Option(
        "--keep-at", help="X,Y: keep only the piece(s) at these pixels. Repeatable.")] = None,
    tolerance: Annotated[float | None, typer.Option(
        "--tolerance", help="RGB distance for --remove-at. Default from rules.")] = None,
    alpha_min: Annotated[int | None, typer.Option(
        "--alpha-min", help="Lowest alpha (1-255) counted as opaque. Default from rules.")] = None,
    mask: Annotated[Path | None, typer.Option(
        "--mask", exists=True, dir_okay=False,
        help="Corrected black/white mask; replaces --remove-at/--keep-at.")] = None,
) -> None:
    """Select the subject: write mask, cutout, preview and selection.json for review."""
    try:
        spec = SelectionSpec(instructions=instructions, alpha_min=alpha_min,
                             color_tolerance=tolerance,
                             remove_at=_points(remove_at, "--remove-at"),
                             keep_at=_points(keep_at, "--keep-at"))
    except ValidationError as e:
        err = e.errors()[0]
        typer.echo(f"error: {err['loc'][0]}: {err['msg']}", err=True)
        raise typer.Exit(2) from None
    try:
        intake = load_image(image)
        if mask is not None:
            sel = select_from_mask(intake, load_mask(mask, intake.rgba.shape[:2]), spec)
        else:
            sel = select_subject(intake, spec)
        rec = write_selection(intake, sel, out)
    except SelectionError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:              # unreadable input, unwritable output, disk full ...
        _os_error(e)
        raise typer.Exit(2) from None
    r = rec["result"]
    typer.echo(f"status {r['status']}: {r['selected_px']} px in {len(r['pieces_px'])} piece(s), "
               f"{len(r['holes_px'])} hole(s)")
    for w in r["warnings"]:
        typer.echo(f"warning: {w}")
    typer.echo(f"selection_id {rec['selection_id']}")
    typer.echo(f"wrote {out / 'preview.png'} - check the subject before going on")


def _compact(value) -> str:
    """A measurement for one terminal line: floats to 4 significant digits, dicts as
    key=value for their scalar entries (lists inside a dict, such as F3's largest pieces,
    stay in flat.json)."""
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, list):
        return "[" + ", ".join(_compact(v) for v in value) + "]"
    if isinstance(value, dict):
        return ", ".join(f"{k}={_compact(v)}" for k, v in sorted(value.items())
                         if not isinstance(v, (list, dict)))
    return str(value)


def _check_line(check: dict) -> str:
    """'  ID STATUS - measured M; threshold T: note', leaving out the parts that are absent."""
    parts = [f"{name} {_compact(check[name])}" for name in ("measured", "threshold")
             if check[name] is not None]
    line = f"  {check['id']} {check['status']}"
    if parts:
        line += " - " + "; ".join(parts)
    if check["note"]:
        line += f": {check['note']}"
    return line


def _smoothing_line(record: dict) -> str:
    """'smoothing off', or the sigma, its source, the sampled outline change and the area
    removed and added, in mm (ASCII only, so any console encoding can print it).

    The outline change is the record's hausdorff_lower_bound_px in mm: a boundary-to-
    region distance, so a change enclosed by the other region (a filled hole) counts 0.
    """
    smoothing = record["smoothing"]
    if not smoothing["applied"]:
        return "smoothing off"
    sigma = smoothing["sigma_px"]
    source = f"rule {sigma['rule']}" if sigma["rule"] else "set by --smooth-px"
    scale = record["transform"]["scale_mm_per_px"]
    bound = smoothing["hausdorff_lower_bound_px"]
    moved = ("unknown" if bound is None else
             f"at least {bound * scale:.3g} mm (sampled; boundary-to-region)")
    removed = smoothing["removed_area_px2"] * scale ** 2
    added = smoothing["added_area_px2"] * scale ** 2
    return (f"smoothing sigma {sigma['value']:g} px ({source}): outline changed by {moved}, "
            f"area -{removed:.3g}/+{added:.3g} mm^2")


@app.command()
def flat(
    ctx: typer.Context,
    selection: Annotated[Path, typer.Argument(exists=True, file_okay=False,
                                              metavar="SELECTION_DIR",
                                              help="A tdmg select output folder.")],
    thickness_mm: Annotated[float, typer.Option(
        "--thickness-mm", help="Thickness of the flat solid, in mm.")],
    out: Annotated[Path, typer.Option("--out", help="New or empty folder for the outputs.")],
    width_mm: Annotated[float | None, typer.Option(
        "--width-mm", help="Width of the selection in the model, in mm. Required, except "
                           "with --colors, where it defaults to the plan's width and "
                           "must equal it.")] = None,
    printer: Annotated[str | None, typer.Option(
        "--printer", help=f"Printer profile id (see `tdmg printers`); default {FLAT_PRINTER}, "
                          "or with --colors the plan's printer, which it must equal.")
    ] = None,
    smooth_px: Annotated[float | None, typer.Option(
        "--smooth-px", help="Gaussian smoothing of the outline in image pixels; default from "
                            "rule flat.smooth.sigma_px; 0 keeps the exact pixel outline. "
                            "Not allowed with --colors.")] = None,
    colors_dir: Annotated[Path | None, typer.Option(
        "--colors", exists=True, file_okay=False, metavar="COLORS_DIR",
        help="A tdmg colors output folder (a ready plan of this selection): make "
             "the colored AMS and glue bodies instead.")] = None,
) -> None:
    """Make a flat solid from a selection: write model.stl, outline.png and flat.json.

    Exit codes:
      0  files written, and no check FAILed (UNKNOWN checks allowed)
      1  files written, and at least one check FAILed
      2  input or usage error: nothing is written; or an I/O failure
         while writing, which can leave a folder without flat.json:
         such a folder is incomplete and must not be used
    Exit 0 does not mean the part is certified; read verdict in flat.json.

    With --colors COLORS_DIR, write the AMS bodies (ams-base.stl,
    ams-color-<i>-<rrggbb>.stl), model.3mf (the AMS bodies as one
    multicolor 3MF, one shell per color) and palette.json (what each
    shell is), the glue bodies (glue-base.stl,
    glue-color-<i>-<rrggbb>.stl), top.png, parts.png and colored.json.
    The exit codes are the same, with colored.json for flat.json. A plan
    that keeps a drawn outline band (outlines: keep with an outline
    family) gets no glue bodies and no parts.png.
    """
    # Typer's Rich help keeps the single line breaks of every paragraph after the first,
    # so the list above renders line for line. Each line is under 76 characters, so an
    # 80-column terminal does not wrap it (tests/test_cli.py checks this).
    if colors_dir is not None:
        _colored_flat(selection, colors_dir, out, thickness_mm=thickness_mm,
                      width_mm=width_mm, printer=printer, smooth_px=smooth_px)
        return
    if width_mm is None:
        # Required without --colors: the same usage error (exit 2) and text that a
        # required option gives.
        ctx.fail("Missing option '--width-mm'.")
    try:
        chosen = {} if printer is None else {"printer": printer}   # else make_flat's default
        rec = make_flat(selection, width_mm, thickness_mm, out, smooth_px=smooth_px,
                        **chosen)
    except (FlatError, SelectionError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:              # unreadable selection, unwritable output, disk full ...
        _os_error(e)
        raise typer.Exit(2) from None
    typer.echo(f"verdict {rec['verdict']}")
    typer.echo(_smoothing_line(rec))
    for warning in rec["warnings"]:
        typer.echo(f"warning: {warning}", err=True)
    for c in rec["checks"]:
        if c["status"] != "PASS":
            typer.echo(_check_line(c))
    mesh = rec["mesh"]
    size = " x ".join(f"{e:.2f}" for e in mesh["extents_mm"])
    bodies = f"{mesh['bodies']} bod{'y' if mesh['bodies'] == 1 else 'ies'}"
    typer.echo(f"size {size} mm, {mesh['triangles']} triangles, {bodies}")
    typer.echo(f"flat_id {rec['flat_id']}")
    typer.echo(f"wrote {out / 'model.stl'}")
    typer.echo(f"wrote {out / 'outline.png'} - open outline.png to check what smoothing and "
               "cleaning changed")
    typer.echo(f"wrote {out / 'flat.json'}")
    if any(c["status"] == "FAIL" for c in rec["checks"]):
        raise typer.Exit(1)


def _colored_flat(selection: Path, colors_dir: Path, out: Path, **kw) -> None:
    """tdmg flat --colors: make_colored_flat, its summary lines and flat's exit codes."""
    try:
        rec = make_colored_flat(selection, colors_dir, out, **kw)
    except (FlatError, SelectionError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:              # unreadable input, unwritable output, disk full ...
        _os_error(e)
        raise typer.Exit(2) from None
    typer.echo(f"verdict {rec['verdict']}")
    for warning in rec["warnings"]:
        typer.echo(f"warning: {warning}", err=True)
    checks = [(b["name"], c) for b in rec["bodies"] for c in b["checks"]]
    checks += [(route, c) for route, cs in rec["assembly"].items() for c in cs]
    for where, c in checks:
        if c["status"] != "PASS":
            typer.echo(f"  {where}: {_check_line(c).lstrip()}")
    for b in rec["bodies"]:
        size = " x ".join(f"{e:.2f}" for e in b["extents_mm"])
        typer.echo(f"{b['name']}: color {b['index']} {b['hex']} ({b['role']}), "
                   f"{b['triangles']} triangles, {b['volume_mm3']:.1f} mm3, {size} mm")
    glue = rec["glue"]
    if glue["built"]:
        pieces = len(glue["report"]["pieces"])
        typer.echo(f"glue: {pieces} piece{'' if pieces == 1 else 's'}, "
                   f"{len(glue['report']['folds'])} regions folded")
    else:
        typer.echo(f"glue: not built - {glue['reason']}")
    typer.echo(f"colorflat_id {rec['colorflat_id']}")
    for name in rec["outputs"]:
        typer.echo(f"wrote {out / name}")
    typer.echo(f"wrote {out / COLORED_RECORD}")
    pngs = "top.png and parts.png" if "parts.png" in rec["outputs"] else "top.png"
    typer.echo(f"open {pngs}; then open {rec['model_3mf']['file']} in your slicer and "
               f"give each color a filament ({rec['model_3mf']['palette']})")
    if any(c["status"] == "FAIL" for _, c in checks):
        raise typer.Exit(1)


def _portability_line(rec: dict) -> str:
    """'portability: ...': PrusaSlicer's verdict and what it read, or why it did not run.
    rec is a tdmg.slicing record, or a colorslice record's portability section."""
    port = rec.get("portability", rec)
    check = (port["check"] if "check" in port else
             next(c for c in rec["checks"] if c["id"] == "F6.portability"))
    if not port["configured"]:
        return f"portability: {check['status']} - {port['reason']}"
    slicer = port["slicer"]
    head = f"portability: {slicer['name']} {slicer['version']} {check['status']} - "
    parsed = port["info"]["parsed"]
    if parsed is None:
        read = "--info not read"
    else:
        size = " x ".join(f"{v:.2f}" for v in parsed["size_mm"])
        parts = f"{parsed['parts']} part{'' if parsed['parts'] == 1 else 's'}"
        read = (f"{parts}, {parsed['facets']} facets, size {size} mm, volume "
                f"{parsed['volume_mm3']:.6g} mm3")
    layers = port["gcode"]["layers"]
    sliced = "no G-code" if layers is None else f"{layers} layers"
    return f"{head}{read}, {sliced}; {PRUSA_GCODE_NOTE}"


def _number(value, unit: str, digits: int = 1) -> str:
    return "?" if value is None else f"{value:.{digits}f} {unit}"


def _filament_line(fmap: list[dict]) -> str:
    """'filament 1: base #f60606, filament 2: color 1 #f5f5f5, ...'"""
    return ", ".join(f"filament {f['filament']}: "
                     + ("base" if f["role"] == "base" else f"color {f['index']}")
                     + f" {f['hex']}" for f in fmap)


def _chosen(rec: dict) -> str | None:
    """auto's chosen face (preferred_face), or None (none chosen, or an explicit --face)."""
    return rec["preferred_face"] if rec["params"]["face"] == "auto" else None


def _has_fail(part: dict) -> bool:
    """A required check FAILed (a warning that FAILs is printed, never blocking)."""
    return any(c["status"] == "FAIL" and c["id"] in part["required_checks"]
               for c in part["checks"])


def _color_failed(rec: dict) -> bool:
    """Whether a colored slice exits 1: a required check FAILed, or F6.portability FAILed.
    Under auto with a chosen face (preferred_face; Decision 1a of
    docs/plans/2026-11-16-face-down-default.md; a chosen face is always PRINTABLE), only
    that face counts: a FAIL on the other face does not. With no face chosen, or an
    explicit --face, every face counts. Glue plates always count."""
    chosen = _chosen(rec)
    faces = [rec["faces"][chosen]] if chosen is not None else list(rec["faces"].values())
    return (any(_has_fail(p) for p in [*faces, *rec["glue"]["plates"].values()])
            or rec["portability"]["check"]["status"] == "FAIL")


def _color_slice_output(rec: dict, out: Path) -> None:
    """tdmg slice's output for a colored folder (tdmg.color_slicing)."""
    sliced = [face for face in FACES if face in rec["faces"]]
    for face in sliced:
        f = rec["faces"][face]
        s = f["summary"]
        changes = "?" if s["changes"] is None else str(s["changes"])
        typer.echo(f"{FACE_FOLDER[face]}: {f['certification']}")
        typer.echo(f"  {changes} color changes, flush {_number(s['flush_mm3'], 'mm3')}, "
                   f"prime tower {_number(s['prime_tower_mm3'], 'mm3')}, time "
                   f"{_number(s['time_s'], 's', 0)} (slicer estimates)")
        if f["certification_note"]:
            typer.echo(f"  {f['certification_note']}")
        for w in f["warnings"]:
            typer.echo(f"  warning: {w['text']}")
    for name, plate in rec["glue"]["plates"].items():
        typer.echo(f"{name} (glue plate, sliced as an R1 part): {plate['certification']}")
    route = rec["glue"]["route"]
    if route is not None and route["printable"]:
        typer.echo("glue route: printable: every glue plate is PRINTABLE; a glue print needs "
                   "all of them")
        for name, plate in rec["glue"]["plates"].items():     # R1's rule: never our G-code
            typer.echo(f"{name}: slice {plate['plate']} in Bambu Studio to print; its "
                       f"{GCODE_NAME} is for checking only")
    elif route is not None:
        typer.echo(f"glue route: not printable: {', '.join(route['blocking'])} not PRINTABLE "
                   "(a glue print needs every plate)")
    if not rec["glue"]["built"]:
        typer.echo(f"glue: not built - {rec['glue']['reason']}")
    typer.echo(_portability_line(rec["portability"]))
    if not rec["slicer"]["app_tree_verified"]:
        typer.echo("app tree not verified (--skip-tree-check)")
    typer.echo(_filament_line(rec["filament_map"]))
    if rec["params"]["face"] == "auto":         # the choice and why (Decision 1a)
        chosen = rec["preferred_face"]
        typer.echo(f"chosen: {'none' if chosen is None else f'face {chosen}'}: "
                   f"{rec['preferred_face_reason']}")
        for face in sliced:
            if chosen is not None and face != chosen \
                    and rec["faces"][face]["verdict"] != "PRINTABLE":
                typer.echo(not_chosen_line(face, rec["faces"][face]))
    typer.echo(rec["print"])          # the record's own instructions (print_instructions)
    typer.echo(f"colorslice_id {rec['colorslice_id']}")
    for name in rec["outputs"]:
        evidence = Path(name).name in (PRUSA_GCODE_NAME, PRUSA_FAILED_GCODE_NAME)
        typer.echo(f"wrote {out / name}"
                   + (" (portability evidence only; not for printing)" if evidence else ""))
    typer.echo(f"wrote {out / 'slice.json'}")


@app.command("slice")
def slice_(
    flat_dir: Annotated[Path, typer.Argument(
        exists=True, file_okay=False, metavar="FLAT_DIR",
        help="A tdmg flat output folder (single-color, or made with --colors).")],
    out: Annotated[Path, typer.Option("--out", help="New or empty folder for the outputs.")],
    slicer_dir: Annotated[Path | None, typer.Option(
        "--slicer-dir", help="OrcaSlicer folder from scripts/setup_orcaslicer.py; default "
                             "$TDMG_ORCASLICER_DIR")] = None,
    timeout_s: Annotated[float | None, typer.Option(
        "--timeout-s", help="Stop each slicer run after this many seconds; default from "
                            "rules slicer.orca.timeout_s (OrcaSlicer) and "
                            "slicer.prusa.timeout_s (each PrusaSlicer run)")] = None,
    skip_tree_check: Annotated[bool, typer.Option(
        "--skip-tree-check", help="Do not hash every file of the slicers' app folders "
                                  "(saves a few seconds per slicer); recorded as "
                                  "app_tree_verified false, and the verdict cannot be "
                                  "PRINTABLE")] = False,
    prusaslicer_dir: Annotated[Path | None, typer.Option(
        "--prusaslicer-dir", help="PrusaSlicer folder from scripts/setup_prusaslicer.py, for "
                                  "F6.portability; default $TDMG_PRUSASLICER_DIR; without "
                                  "either, F6.portability is UNKNOWN")] = None,
    face: Annotated[str | None, typer.Option(
        "--face", help="For a tdmg flat --colors folder: the face(s) to slice, up, down, "
                       "both or auto; default auto: both faces sliced, face down chosen "
                       "when it is PRINTABLE, else face up (both: reports the two, chooses "
                       "none)",
        show_default=False)] = None,
) -> None:
    """Slice a flat model with the pinned OrcaSlicer: write the G-code and slice.json.

    With PrusaSlicer configured, F6.portability checks that a second slicer
    accepts model.stl as modelled and slices its full height (both read STL
    with admesh); prusaslicer.portability-only.gcode.txt is generic G-code,
    never for the A1.

    A tdmg flat --colors folder is sliced face up and face down, and face
    down is printed if it is PRINTABLE, else face up if it is (--face up,
    down or both for one face, or both without a choice), each color on
    its own filament, and each glue plate as a single-color part;
    F6.portability then reads model.3mf.

    Exit codes:
      0  files written, and no required check FAILed (UNKNOWN checks
         and warnings allowed); without --face, a FAIL on the face not
         chosen is allowed when the chosen face is PRINTABLE
      1  files written, and a required check FAILed
      2  input or setup error (including a missing or unverified
         slicer): nothing is written; or an I/O failure while
         writing, which can leave a folder without slice.json:
         such a folder is incomplete and must not be used
    Exit 0 does not mean the part is certified; read verdict in slice.json.
    """
    colored = is_colored_folder(flat_dir)
    try:
        make = make_color_slice if colored else make_slice
        # Any --face given is refused for a single-color folder, the default's value too.
        if not colored and face is not None:
            raise SlicerError("--face applies to a tdmg flat --colors folder only")
        extra = {"face": DEFAULT_FACE if face is None else face} if colored else {}
        rec = make(flat_dir, out, slicer_dir=slicer_dir, timeout_s=timeout_s,
                   check_tree=not skip_tree_check, prusaslicer_dir=prusaslicer_dir, **extra)
    except SlicerError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:              # unreadable input, unwritable output, disk full ...
        _os_error(e)
        raise typer.Exit(2) from None
    if colored:
        _color_slice_output(rec, out)
        if _color_failed(rec):
            failed = [n for n, p in rec["glue"]["plates"].items() if _has_fail(p)]
            typer.echo(do_not_print(_chosen(rec), failed))
            raise typer.Exit(1)
        return
    typer.echo(rec["certification"])     # the verdict, with the checks that block it
    if rec["certification_note"]:
        typer.echo(rec["certification_note"])     # what PRINTABLE means, and does not
    if rec["certification"] == "PRINTABLE":
        typer.echo(PRINT_THIS)
    if not rec["slicer"]["app_tree_verified"]:
        typer.echo("app tree not verified (--skip-tree-check)")
    code = rec["exit"]
    if code["timed_out"]:
        typer.echo(f"slicer stopped after {rec['params']['timeout_s']['value']:g} s")
    else:
        shown = code["signed"] if code["signed"] is not None else code["raw"]
        typer.echo(f"slicer exit {shown} ({code['name'] or 'not in the v2.5.0 table'})")
    for c in rec["checks"]:
        if c["status"] != "PASS":
            typer.echo(_check_line(c))
    stats = rec["stats"]
    if stats is not None:
        typer.echo(f"{stats['layer_count']} layers, {stats['time_s']:.1f} s, "
                   f"{stats['weight_g']:.4g} g (slicer estimates)")
    typer.echo(_portability_line(rec))
    typer.echo(f"slice_id {rec['slice_id']}")
    for name in rec["outputs"]:
        evidence = name in (PRUSA_GCODE_NAME, PRUSA_FAILED_GCODE_NAME)
        typer.echo(f"wrote {out / name}"
                   + (" (portability evidence only; not for printing)" if evidence else ""))
    typer.echo(f"wrote {out / 'slice.json'}")
    if any(c["status"] == "FAIL" for c in rec["checks"]):
        prusa_written = PRUSA_FAILED_GCODE_NAME in rec["outputs"]
        typer.echo(DO_NOT_PRINT + (PRUSA_DO_NOT_PRINT if prusa_written else ""))
        raise typer.Exit(1)


def _time(seconds) -> str:
    return "?" if seconds is None else f"{seconds / 60:.0f} min"


def _accepted_lines(note: dict) -> list[str]:
    """One plain line per part with the owner-accepted failure, from the note's this_run
    (the full cause and this_run_text stay in strip.json; review P1)."""
    checks = _count_words(len(note["checks"]), "check")
    lines = []
    for run in note["this_run"]:
        zs = ", ".join(f"{m['z_mm']:g}" for m in run["mismatched"])
        # Codex review 2026-11-14, finding 2: what this run measured (counts), then the
        # cause as measured on KNOWN_FAILURE_DATE, not as this run's.
        lines.append(f"the {run['part']} plate fails {checks}: {KNOWN_FAILURE_MEASURED}, on "
                     f"{run['layers_mismatched']} of {run['layers']} layers (z {zs} mm).")
        lines.append(f"On {KNOWN_FAILURE_DATE} these were {KNOWN_FAILURE_PLAIN}, and you "
                     "decided to print it anyway. This run's parts are counted, not sized. "
                     f"Details: {STRIP_RECORD}")
    return lines


def _count_words(n: int, noun: str) -> str:
    word = {1: "one", 2: "two", 3: "three"}.get(n, str(n))
    return f"{word} {noun}{'' if n == 1 else 's'}"


def _strip_ok(section: dict) -> bool:
    """A strip the owner can print: PRINTABLE, or NOT CERTIFIED by the owner-accepted
    failure alone (its known_failures note)."""
    return section["verdict"] == "PRINTABLE" or section["known_failures"] is not None


def _strip_output(rec: dict, out: Path) -> list[tuple[str, str]]:
    """tdmg strip's lines; returns the blocking failures of both strips."""
    cl, sk = rec["clearance"], rec["skin"]
    typer.echo(f"clearance strip: {cl['certification']}")
    for name, plate in cl["plates"].items():
        s = plate["summary"]
        layers = "?" if s["layer_count"] is None else str(s["layer_count"])
        typer.echo(f"  {name} plate: {plate['certification']} - {layers} layers, time "
                   f"{_time(s['time_s'])}, filament {_number(s['weight_g'], 'g', 2)}")
    note = cl["known_failures"]
    if note is not None:
        for line in _accepted_lines(note):
            typer.echo(f"  {line}")
    typer.echo(f"skin strip: {sk['certification']}")
    s = sk["summary"]
    changes = "?" if s["changes"] is None else str(s["changes"])
    typer.echo(f"  face up: {changes} color changes, time {_time(s['time_s'])}, filament "
               f"{_number(s['weight_g'], 'g', 2)}")
    # Codex review 2026-11-14, finding 3: the white tool's coverage and connectivity are
    # required for the strip; the black tool's and the whole model's stay warnings.
    warnings = sk["face"]["warnings"]
    for w in warnings:
        typer.echo(f"  warning: {w['text']}")
    if warnings:
        typer.echo("  the skin strip has warnings: before printing, check it in Bambu "
                   "Studio's preview")
    typer.echo("times and filament are the slicer's estimates")
    blocking = {"clearance": blocking_failures(cl), "skin": blocking_failures(sk)}
    typer.echo(f"to print, in {out}:")
    for strip, section in (("clearance", cl), ("skin", sk)):
        if blocking[strip]:
            failed = ", ".join(f"{part}: {check}" for part, check in blocking[strip])
            typer.echo(f"  do not print the {strip} strip: a required check FAILed "
                       f"({failed}); its G-code is kept as {FAILED_GCODE_NAME}")
        elif not _strip_ok(section):
            typer.echo(f"  the {strip} strip is not certified: do not print it yet")
        elif strip == "clearance":
            typer.echo(f"  clearance strip: open {CLEARANCE_DIR}/{BASE_STL} and "
                       f"{CLEARANCE_DIR}/{PIECES_STL} in Bambu Studio and print them as two "
                       "plates in the same filament")
            typer.echo(f"    do not move, turn or arrange the pieces; {TEMPLATE_NAME} says "
                       "how to keep them in order")
        else:
            colors = ", ".join(
                f"filament {f['filament']} {SKIN_COLOR_NAMES[f['hex']]} "
                f"({'the base' if f['role'] == 'base' else 'the patches'})"
                for f in sk["filament_map"])
            typer.echo(f"  skin strip: open {SKIN_DIR}/{MODEL_3MF} in Bambu Studio and print "
                       f"it on the AMS: {colors}")
    typer.echo(f"  after printing, fill in {TEMPLATE_NAME}; the record is {STRIP_RECORD}")
    typer.echo(f"  the {GCODE_NAME} files are for checking only, not for printing")
    typer.echo(f"strip_id {rec['strip_id']}")
    return blocking["clearance"] + blocking["skin"]


@app.command()
def strip(
    out: Annotated[Path, typer.Argument(metavar="OUT",
                                        help="New or empty folder for the outputs.")],
    slicer_dir: Annotated[Path | None, typer.Option(
        "--slicer-dir", help="OrcaSlicer folder from scripts/setup_orcaslicer.py; default "
                             "$TDMG_ORCASLICER_DIR")] = None,
    timeout_s: Annotated[float | None, typer.Option(
        "--timeout-s", help="Stop each slicer run after this many seconds; default from "
                            "rule slicer.orca.timeout_s")] = None,
) -> None:
    """Make the two calibration strips: build, check and slice them.

    The clearance strip (clearance/base.stl and pieces.stl) tests the
    glue gap; the skin strip (skin/model.3mf) tests the white skin
    depth over black. Writes strip.json and results-template.md, the
    form to fill in after printing. PrusaSlicer is not run.

    Exit codes:
      0  files written, and no required check FAILed, except the
         owner-accepted F3.printed_connectivity failure of the
         clearance base plate (UNKNOWN checks and warnings allowed)
      1  files written, and another required check FAILed
      2  input or setup error (including a missing or unverified
         slicer, an OUT that is a file or a non-empty folder, or a
         strip that cannot be built as asked):
         nothing is written; or an I/O failure while writing,
         which can leave a folder without strip.json: such a
         folder is incomplete and must not be used
    Exit 0 does not mean a strip is certified; read verdicts in
    strip.json.
    """
    try:
        rec = make_strips(out, slicer_dir=slicer_dir, timeout_s=timeout_s)
    except (SlicerError, StripError) as e:     # StripError: a strip that cannot be built
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:              # unwritable output, disk full ...
        _os_error(e)
        raise typer.Exit(2) from None
    if _strip_output(rec, out):
        raise typer.Exit(1)


def _base(value: str | None) -> str | int | None:
    if value is None or value == "auto":
        return value
    try:
        return int(value)
    except ValueError:
        raise typer.BadParameter(f"--base expects auto or a color index, got {value!r}"
                                 ) from None


@app.command()
def colors(
    selection: Annotated[Path, typer.Argument(exists=True, file_okay=False,
                                              metavar="SELECTION_DIR",
                                              help="A tdmg select output folder.")],
    width_mm: Annotated[float, typer.Option(
        "--width-mm", help="Width of the selection in the model, in mm.")],
    out: Annotated[Path, typer.Option("--out", help="New or empty folder for the outputs.")],
    n_colors: Annotated[int | None, typer.Option(
        "--colors", help="Most colors in the final palette; default the printer's palette "
                         "(4 on the A1).")
    ] = None,
    extract: Annotated[int | None, typer.Option(
        "--extract", help="Colors to extract before merges, at least --colors; default "
                          "the rule color.extract.default_count (6).")] = None,
    edges: Annotated[str | None, typer.Option(
        "--edges", help="smooth (default), furry or exact.")] = None,
    base: Annotated[str | None, typer.Option(
        "--base", help="auto (default: the largest color) or a color index.")] = None,
    outlines: Annotated[str | None, typer.Option(
        "--outlines", help="drop (default) or keep the cartoon outline.")] = None,
    config: Annotated[Path | None, typer.Option(
        "--config", help="YAML file with colors, extract, edges, base, outlines, "
                         "outline_color, merge and outline_width_mm; flags override it. "
                         "outline_color, merge (by extraction index) and "
                         "outline_width_mm (the kept outline's width; default the rule "
                         "color.outline.keep_width) are set in this file only.")
    ] = None,
) -> None:
    """Suggest a palette for a selection: write labels.png, regions.png and colors.json.

    Exit codes:
      0  files written; the plan is ready
      1  files written, but the plan is not ready: more colors
         remain than --colors allows. Choose merges from
         regions.png; a plan that is not ready cannot be built
      2  input, config or I/O error: nothing is written, except
         that an I/O failure while writing can leave a folder
         without colors.json, which must not be used
    Open regions.png to review the colors before building geometry.
    """
    flags = {"colors": n_colors, "extract": extract, "edges": edges, "base": _base(base),
             "outlines": outlines}
    try:
        rec = make_colors(selection, out, width_mm=width_mm, flags=flags, config_path=config,
                          rules=load_rules(), printer=load_printer(COLORS_PRINTER))
    except ColorsError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:              # unreadable input, unwritable output, disk full ...
        _os_error(e)
        raise typer.Exit(2) from None
    for line in _colors_lines(rec):
        typer.echo(line)
    for name in rec["outputs"]:
        note = (" - open regions.png to check the colors before building geometry"
                if name == "regions.png" else "")
        typer.echo(f"wrote {out / name}{note}")
    typer.echo(f"wrote {out / 'colors.json'}")
    if not rec["ready"]:
        typer.echo(f"NOT READY: {rec['not_ready_reason']}")
        typer.echo("The files are written for review only; this plan cannot be built.")
        raise typer.Exit(1)


def _colors_lines(rec: dict) -> list[str]:
    """The extracted colors, merges, the final palette, what was dropped or vanished, and
    colors_id (ASCII only)."""
    s = rec["settings"]["settings"]
    ext = rec["extraction"]
    lines = [(f"extracted: {ext['n_extracted']} colors (asked {ext['extract']}); "
              "outline_color and merge use these indices")]
    o = rec["outline"]
    for e in ext["palette"]:
        lines.append(f"  {e['index']} {e['hex']} {e['share']:6.1%}  "
                     f"{extracted_text(e, o, rec['shade_pairs'], ext['palette'])}")
    if o["family"]:
        how = {"auto": f"thinness above {o['thresholds'].get(THIN_SHARE_RULE)}",
               "config": "outline_color in the config"}[o["found_by"]]
        lines.append(f"outline: family {o['family']} ({how}); core {o['core']} "
                     f"{o['core_hex']}; outlines {o['outlines']}")
    for note in o["notes"]:
        lines.append(f"outline: {note}")
    for m in rec["merges"]:
        lines.append(f"merged: {m['from']} {m['from_hex']} into {m['into']} {m['into_hex']}")
    for p in rec["shade_pairs"]:
        lines.append(f"shade pair (flagged, not merged): {p['i']} {p['hex_i']} and {p['j']} "
                     f"{p['hex_j']}, hue difference {p['dh_deg']:.1f} deg; to merge, add "
                     f"merge: [{p['merge']}] to the config file")
    lines.append(f"palette: {len(rec['palette'])} colors (at most {s['colors']}), edges "
                 f"{s['edges']}, {rec['mm_per_px']:.4f} mm/px")
    for p in rec["palette"]:
        lines.append(f"  {p['index']} {p['hex']} {p['share']:6.1%}"
                     + ("  base" if p["base"] else ""))
    q = rec["quantize"]
    if q["n_distinct_colors"] < q["n_requested"]:
        lines.append(f"note: the selection has only {q['n_distinct_colors']} distinct colors")
    if q["dropped"]:
        lines.append(f"dropped: {q['dropped']} palette color(s) got no pixel when quantizing")
    for h in rec["cleanup"]["dropped_hex"]:
        lines.append(f"dropped: {h} - cleanup merged all of it into its neighbours")
    for v in rec["smoothing"]["vanished"]:
        lines.append(f"vanished: {v['hex']} (index {v['index']}) - the {s['edges']} edges "
                     "remove it entirely; it is still in labels.png")
    lines.append(f"cleanup changed {rec['cleanup']['pixels_changed']} px in "
                 f"{rec['cleanup']['passes']} passes")
    lines.append(f"colors_id {rec['colors_id']}")
    return lines


job_app = typer.Typer(help="Jobs: one print's working folder in jobs/, its job.yaml and "
                           "its stages.",
                      no_args_is_help=True)
app.add_typer(job_app, name="job")


def _origin_help(field: str) -> str:
    return f"For --origin generated: {field}. Recorded verbatim; default unknown."


@job_app.command("new")
def job_new(
    name: Annotated[str, typer.Argument(
        help="Job name: lowercase letters, digits and hyphens, at most 63 characters.")],
    output_class: Annotated[str, typer.Option(
        "--class", help=f"Output class: {', '.join(CLASSES)} (see tdmg recipes).")],
    image: Annotated[Path, typer.Option("--image", help="The source image (PNG or JPEG).")],
    colors: Annotated[bool, typer.Option(
        "--colors", help="A multicolor print: the class's multicolor recipe.")] = False,
    mask: Annotated[Path | None, typer.Option(
        "--mask", help="An owner-corrected black/white selection mask, the image's size; "
                       "copied to source/ and used by the select stage.")] = None,
    origin: Annotated[str, typer.Option(
        "--origin", help=f"Where the image came from: {', '.join(ORIGINS)}.")
    ] = DEFAULT_ORIGIN,
    prompt: Annotated[str | None, typer.Option(
        "--prompt", help=_origin_help("the prompt"))] = None,
    generator: Annotated[str | None, typer.Option(
        "--generator", help=_origin_help("the generator"))] = None,
    generator_version: Annotated[str | None, typer.Option(
        "--generator-version", help=_origin_help("the generator's version"))] = None,
    settings: Annotated[str | None, typer.Option(
        "--settings", help=_origin_help("the generator's settings"))] = None,
    references: Annotated[str | None, typer.Option(
        "--references", help=_origin_help("the reference inputs"))] = None,
    chosen: Annotated[str | None, typer.Option(
        "--chosen", help=_origin_help("which candidate was chosen"))] = None,
    edits: Annotated[str | None, typer.Option(
        "--edits", help=_origin_help("edits made after generation"))] = None,
    width_mm: Annotated[float | None, typer.Option(
        "--width-mm", help="Width of the selection in the model, in mm; can be left "
                           "unset for now.")] = None,
    thickness_mm: Annotated[float | None, typer.Option(
        "--thickness-mm", help="Thickness of the flat solid, in mm; can be left unset "
                               "for now.")] = None,
    jobs_dir: Annotated[Path | None, typer.Option(
        "--jobs-dir", help="Folder that holds the jobs; default jobs/ in the source "
                           "checkout (required when tdmg is installed from a wheel).")
    ] = None,
    prints_dir: Annotated[Path | None, typer.Option(
        "--prints-dir", help="The print library; a name already in it is refused. Default: "
                             "prints/ in the source checkout (also with --jobs-dir); "
                             "outside a checkout, none is checked unless this is "
                             "given.")] = None,
) -> None:
    """Start a job: make JOBS_DIR/NAME/ with the image (and mask) in
    source/ and job.yaml, every stage's parameters at their defaults.

    The class resolves to one recipe; a class with no recipe that is
    implemented or in progress is refused. Nothing is run yet.

    Exit codes:
      0  job made
      2  refused (bad name, existing job, a name already in the
         library or still being purged by tdmg finish, class not
         ready, image missing or unreadable, bad mask); nothing is
         written; or
         an I/O failure while writing, which can leave a folder
         without job.yaml: such a folder is incomplete
    """
    generated = {"prompt": prompt, "generator": generator, "version": generator_version,
                 "settings": settings, "references": references, "chosen": chosen,
                 "edits": edits}
    try:
        where = default_jobs_dir() if jobs_dir is None else jobs_dir
        library = default_library() if prints_dir is None else prints_dir
        job = new_job(where, name, output_class, image, colors=colors, mask=mask,
                      origin=origin, generated=generated, width_mm=width_mm,
                      thickness_mm=thickness_mm, prints_dir=library)
    except JobError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:              # unreadable input, unwritable output, disk full ...
        _os_error(e)
        raise typer.Exit(2) from None
    r = next(x for x in RECIPES if x.id == job["recipe"])
    folder = where / job["name"]
    typer.echo(f"job {job['name']}: class {job['class']}, recipe {r.id} ({r.name})")
    typer.echo(f"stages: {', '.join(r.stages)}")
    typer.echo(f"source: {job['source']['file']} (origin {job['source']['origin']})")
    if job["source"]["mask"] is not None:
        typer.echo(f"mask: {job['source']['mask']['file']}")
    unset = unset_required(job)
    if unset:
        typer.echo(f"not set yet (needed before those stages run): {', '.join(unset)}")
    if library is None:
        typer.echo("the print library was not checked for this name (tdmg is not running "
                   "from a source checkout; give --prints-dir to check one)")
    typer.echo(f"wrote {folder / JOB_FILE}")


def default_library() -> Path | None:
    """The print library tdmg job new checks when --prints-dir is not given: the
    checkout's prints/, even with --jobs-dir; None outside a checkout. (Tests point it at a
    temporary folder: tests/conftest.py.)"""
    return None if REPO_ROOT is None else REPO_ROOT / "prints"


JobsDir = Annotated[Path | None, typer.Option(
    "--jobs-dir", help="Folder that holds the jobs; default jobs/ in the source checkout.")]
SlicerDir = Annotated[Path | None, typer.Option(
    "--slicer-dir", help="OrcaSlicer folder from scripts/setup_orcaslicer.py; default "
                         "$TDMG_ORCASLICER_DIR (needed when the slice stage runs).")]
PrusaDir = Annotated[Path | None, typer.Option(
    "--prusaslicer-dir", help="PrusaSlicer folder from scripts/setup_prusaslicer.py, for "
                              "F6.portability; default $TDMG_PRUSASLICER_DIR. Whether it "
                              "is configured is part of the slice stage's input key.")]


def _job_folder(name: str, jobs_dir: Path | None) -> Path:
    where = default_jobs_dir() if jobs_dir is None else jobs_dir
    folder = job_dir(where, name)
    if not folder.is_dir():
        raise JobError(f"no job {name} in {where} (start one with tdmg job new)")
    return folder


@job_app.command("set")
def job_set(
    name: Annotated[str, typer.Argument(help="Job name.")],
    assignments: Annotated[list[str] | None, typer.Argument(
        metavar="STAGE.KEY=VALUE...",
        help="Parameters to set, e.g. flat.width_mm=60 or "
             "\"select.keep_at=[[470, 470]]\".")] = None,
    text: Annotated[tuple[str, str] | None, typer.Option(
        "--text", metavar="STAGE.KEY WORDS",
        help="Set one text parameter to WORDS exactly as given, with no YAML reading "
             "(backslashes, quotes and colons stay as they are): the owner's words, "
             "e.g. --text select.instructions 'THEIR WORDS'. The two values after --text "
             "are taken as they are, so WORDS may start with - or --.")] = None,
    jobs_dir: JobsDir = None,
) -> None:
    """Set stage parameters in job.yaml (one new revision for all of
    them).

    VALUE is read as YAML, by job.yaml's strict rules: a number (60 is
    60.0 where the stage takes a float), true or false, null or ~ (clear
    the parameter: the stage command's default applies), text, or a flow
    list ([[60, 396], [470, 470]] for remove_at and keep_at, [[1, 2]] for
    colors.merge). Quote text that would read as a number, a boolean or
    null. none is text (colors.outline_color takes it), except in
    select.mask=none.

    --text STAGE.KEY WORDS stores WORDS as text, exactly: YAML is not
    read, so nothing in the words is turned into a tab, a line break or
    a number. Use it for the owner's words (select.instructions).

    select.mask=PATH copies an owner-corrected black/white mask into
    source/ and uses it; select.mask=none removes it. Set it on its own.

    Exit codes:
      0  job.yaml written, or nothing changed
      2  refused (unknown stage or parameter, a value of the wrong
         type or out of range); job.yaml is not changed
    """
    assignments = assignments or []
    text = [] if text is None or text[0] is None else [text]
    try:
        folder = _job_folder(name, jobs_dir)
        job, changed = set_parameters(folder, assignments, text)
    except JobError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:
        _os_error(e)
        raise typer.Exit(2) from None
    if not changed:
        typer.echo(f"job {name}: nothing changed (revision {job['revision']})")
        return
    typer.echo(f"job {name}: revision {job['revision']}")
    for a in assignments:
        stage, key = a.partition("=")[0].split(".", 1)
        typer.echo(f"  {stage}.{key}={yaml_value(job['stages'][stage][key])}")
    for target, _ in text:      # the stored text, ASCII-escaped as JSON, to check
        stage, key = target.split(".", 1)
        value = json.dumps(job["stages"][stage][key], ensure_ascii=True)
        typer.echo(f"  {stage}.{key} (text) = {value}")
    typer.echo(f"wrote {folder / JOB_FILE}")


def _stage_failed(stage: str, rec: dict) -> bool:
    """Whether the stage command would exit 1 on this record."""
    if stage == "colors":
        return not rec["ready"]
    if stage == "colored_flat":
        checks = [c for b in rec["bodies"] for c in b["checks"]]
        checks += [c for cs in rec["assembly"].values() for c in cs]
        return any(c["status"] == "FAIL" for c in checks)
    if stage == "slice" and "faces" in rec:
        return _color_failed(rec)
    if stage in ("flat", "slice"):
        return any(c["status"] == "FAIL" for c in rec["checks"])
    return False


def _status_output(status) -> None:
    for line in status_lines(status):
        typer.echo(line)


@job_app.command("run")
def job_run(
    name: Annotated[str, typer.Argument(help="Job name.")],
    slicer_dir: SlicerDir = None,
    prusaslicer_dir: PrusaDir = None,
    rerun: Annotated[list[str] | None, typer.Option(
        "--rerun", metavar="STAGE",
        help="Run this stage again even when it is done (after a code change that kept "
             "its algorithm id); a stage after it runs again when the new record "
             "differs. Repeatable.")] = None,
    jobs_dir: JobsDir = None,
) -> None:
    """Run every stage of the job that is not done, in order, into
    JOBS_DIR/NAME/<stage>/, then print the status.

    A stage runs when its folder has no record or its input key differs
    from state.json's. The key covers its parameters, the hashes of the
    records it reads, its algorithm id, the rules and the profiles (and
    for select the source and mask hashes). It runs into
    <stage>.new/, which replaces the old folder only once its record
    is written: a stage that fails keeps its old results. The run stops
    at a required parameter not set, at a stage that fails, and after a
    color plan that is not ready.

    Exit codes:
      0  every stage done, and no stage would have exited 1
      1  a stage's checks FAILed or its plan is not ready (as the
         stage command's exit 1), or a stage waits for a parameter
      2  refused: a bad job, a changed source file, or a stage that
         refused its input or could not write (as its exit 2)
    """
    try:
        folder = _job_folder(name, jobs_dir)
        events, status = run_job(folder, Machine(slicer_dir, prusaslicer_dir),
                                 rerun=rerun or ())
    except JobError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:
        _os_error(e)
        raise typer.Exit(2) from None
    except Exception as e:  # noqa: BLE001 - a bug: say so, and exit 2 like any refusal
        typer.echo(f"error: unexpected {type(e).__name__} in tdmg job run: {e}", err=True)
        raise typer.Exit(2) from None
    for ev in events:
        text = {"ran": "ran", "kept": "done, not run again", "waits": "waits",
                "failed": "failed"}[ev.action]
        typer.echo(f"{ev.stage}: {text}" + (f": {ev.message}" if ev.message else ""))
    _status_output(status)
    if any(ev.action == "failed" for ev in events):
        raise typer.Exit(2)
    failed = any(s.state == "done" and _stage_failed(s.stage, s.record)
                 for s in status.stages)
    if failed or not status.all_done:
        raise typer.Exit(1)


@job_app.command("status")
def job_status_command(
    name: Annotated[str, typer.Argument(help="Job name.")],
    prusaslicer_dir: PrusaDir = None,
    jobs_dir: JobsDir = None,
) -> None:
    """Print each stage's state (done, stale or not run), the verdicts
    and what waits for the owner, without running anything.

    The slice stage's key depends on whether PrusaSlicer is configured
    (--prusaslicer-dir or $TDMG_PRUSASLICER_DIR): give the same as to
    tdmg job run, or the slice shows as stale.

    Exit codes:
      0  status printed
      2  the job cannot be read
    """
    try:
        folder = _job_folder(name, jobs_dir)
        status = job_status(folder, Machine(None, prusaslicer_dir))
    except JobError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:
        _os_error(e)
        raise typer.Exit(2) from None
    _status_output(status)


@job_app.command("confirm")
def job_confirm(
    name: Annotated[str, typer.Argument(help="Job name.")],
    subject: Annotated[str, typer.Option(
        "--subject", help="What the owner confirms: selection (select/preview.png), colors "
                          "(colors/regions.png) or print (the file printed).")],
    owner_said: Annotated[str, typer.Option(
        "--owner-said", help="The owner's own words, verbatim, exactly as they said or "
                             "wrote them. Never words the owner did not say, and never a "
                             "summary or paraphrase. Recorded as given.")],
    face: Annotated[str | None, typer.Option(
        "--face", help="For --subject print, route ams: the face the owner printed, up or "
                       "down (as the owner says; never guessed from the slice).")] = None,
    route: Annotated[str | None, typer.Option(
        "--route", help="For --subject print: how it was printed: single (R1), ams or "
                        "glue (R2); default single for R1, ams for R2.")] = None,
    accept_not_certified: Annotated[bool, typer.Option(
        "--accept-not-certified",
        help="For --subject print: the owner printed (or chooses to print) a file whose "
             "slice verdict is not PRINTABLE. Recorded in the confirmation.")] = False,
    date: Annotated[str | None, typer.Option(
        "--date", help="The date the owner gave the words, YYYY-MM-DD (their local "
                       "date); default today's date on this machine. Checked against "
                       "this machine's date: not after today.")] = None,
    corrects: Annotated[int | None, typer.Option(
        "--corrects", metavar="N",
        help="This entry corrects confirmation N (its number in tdmg job status), whose "
             "words were recorded wrongly; same subject. N is kept as it is and is no "
             "longer current, so finish never uses it.")] = None,
    prusaslicer_dir: PrusaDir = None,
    jobs_dir: JobsDir = None,
) -> None:
    """Record the owner's confirmation in job.yaml: their words verbatim,
    the date, the job's revision and the SHA-256 of every file it covers.

    Covered: selection, select/selection.json and select/preview.png;
    colors, colors/colors.json and colors/regions.png; print, the
    printable files (single: flat/model.stl; ams: colored_flat/model.3mf
    and palette.json, with the face; glue: every glue plate), the slice
    record's identity and its verdicts. Each file is hashed from disk and
    must be the one its record names.

    Pass only words the owner gave. Confirmations are only ever added:
    a new one never changes an earlier one. tdmg job status and job run
    show a confirmation as stale when a covered file changes. When the
    words of an earlier entry were recorded wrongly, record the right
    ones with --corrects N: entry N is kept, and is no longer current.

    A print confirmation is not permission to purge the job: tdmg finish
    asks the owner for that separately (--purge-owner-said).

    Refused: empty words; a stage not done (print needs every stage);
    a color plan not ready; a file differing from its records; for print,
    a face not sliced, ams without --face, and a verdict that is not
    PRINTABLE without --accept-not-certified.

    Exit codes:
      0  confirmation recorded
      2  refused; job.yaml is not changed
    """
    try:
        folder = _job_folder(name, jobs_dir)
        job, _ = confirm(folder, subject, owner_said, date=date, route=route, face=face,
                         accept_not_certified=accept_not_certified,
                         machine=Machine(None, prusaslicer_dir), corrects=corrects)
    except JobError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:
        _os_error(e)
        raise typer.Exit(2) from None
    status = job_status(folder, Machine(None, prusaslicer_dir), job=job)
    typer.echo(f"job {name}: revision {job['revision']}")
    typer.echo(f"recorded {confirmation_line(status.confirmations[-1])}")
    for path, digest in job["confirmations"][-1]["covers"].items():
        typer.echo(f"  covers {path} {digest}")
    typer.echo(f"wrote {folder / JOB_FILE}")



@app.command("finish")
def finish_command(
    name: Annotated[str, typer.Argument(help="Job name (the job in JOBS_DIR/NAME).")],
    public: Annotated[str | None, typer.Option(
        "--public", metavar="yes|no",
        help="The owner's answer: may the design be public? yes: the printable files go "
             "to files/ (tracked in git); no: to private/ (git-ignored). Required.")] = None,
    purge_owner_said: Annotated[str | None, typer.Option(
        "--purge-owner-said",
        help="The owner's own words, verbatim, giving permission to delete the job's "
             "working data. Never words the owner did not say. Required, except with "
             "--dry-run; a dry run given them prints them back as they would be "
             "recorded.")] = None,
    confirmation: Annotated[int | None, typer.Option(
        "--confirmation", metavar="N",
        help="The print confirmation to finish (its number in tdmg job status); needed "
             "when current print confirmations differ in route or face.")] = None,
    dry_run: Annotated[bool, typer.Option(
        "--dry-run", help="Check, stage and rebuild, say what would be published and "
                          "deleted, and change nothing.")] = False,
    slicer_dir: SlicerDir = None,
    prusaslicer_dir: PrusaDir = None,
    jobs_dir: JobsDir = None,
    prints_dir: Annotated[Path | None, typer.Option(
        "--prints-dir", help="The library folder; default prints/ in the source "
                             "checkout.")] = None,
) -> None:
    """Finish a confirmed print: copy it into the library, prove it
    rebuilds, publish it as PRINTS_DIR/NAME, then delete JOBS_DIR/NAME.

    Steps: (1) check the name and that no folder is a link; (2) check
    every stage is done and current, the print confirmation is current,
    and the git tree is clean; (3) stage PRINTS_DIR/.staging-NAME with
    job.yaml, source/, the confirmed route's printable files,
    provenance.json and card.md; (4) rebuild the job from job.yaml and
    source/ in a scratch folder and compare every file (only the
    G-code timestamp lines and slice.json's hashes of those G-code
    files may differ); (5) printable files in files/ or private/ by
    --public; (6) rename the staging folder to PRINTS_DIR/NAME, write
    purge.json, then COMPLETE (every file's SHA-256) last; (7) rename
    JOBS_DIR/NAME to JOBS_DIR/.purging-NAME, check it holds exactly
    what purge.json lists, and delete it.

    Run it again after an interruption: it continues from the step it
    stopped at, never publishes twice, and deletes the job only once
    PRINTS_DIR/NAME has COMPLETE and every hash in it matches.

    Give the same --prusaslicer-dir as tdmg job run (it is part of the
    slice stage's key), and --slicer-dir for the rebuild.

    Exit codes:
      0  finished (or the dry run passed, or it was already finished)
      1  the rebuild does not match the job: nothing is published or
         deleted, and the staging folder is removed
      2  refused (bad name, a link, an existing print, a stage not done,
         no current print confirmation, a dirty git tree, no --public,
         no purge words) or an I/O failure. Before step 7 deletes
         anything the job is untouched; a deletion that stops part way
         leaves the rest in JOBS_DIR/.purging-NAME, which the next run
         deletes
    """
    answer = None if public is None else {"yes": True, "no": False}.get(public.lower())
    if public is not None and answer is None:
        typer.echo(f"error: --public must be yes or no, not {public!a}", err=True)
        raise typer.Exit(2)
    try:
        finish(name, public=answer, purge_owner_said=purge_owner_said,
               confirmation=confirmation, dry_run=dry_run,
               machine=Machine(slicer_dir, prusaslicer_dir), jobs_dir=jobs_dir,
               prints_dir=prints_dir, say=typer.echo)
    except RebuildDiffers as e:
        typer.echo("error: the rebuild does not match the job; nothing was published or "
                   "deleted (the staging folder is removed):", err=True)
        for d in e.differences:
            typer.echo(f"  {d}", err=True)
        raise typer.Exit(1) from None
    except (LibraryError, JobError, RecordError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:
        _os_error(e)
        raise typer.Exit(2) from None
    except Exception as e:  # noqa: BLE001 - a bug: say so, and exit 2 like any refusal
        typer.echo(f"error: unexpected {type(e).__name__} in tdmg finish: {e}; run it "
                   "again to resume", err=True)
        raise typer.Exit(2) from None


library_app = typer.Typer(help="The print library, prints/: check its entries, and verify "
                               "one under the current code and rules.",
                          no_args_is_help=True)
app.add_typer(library_app, name="library")
PrintsDir = Annotated[Path | None, typer.Option(
    "--prints-dir", help="The library folder; default prints/ in the source checkout.")]


@library_app.command("check")
def library_check(
    name: Annotated[str | None, typer.Argument(
        help="The entry to check (PRINTS_DIR/NAME); every entry when left out.")] = None,
    require_private: Annotated[bool, typer.Option(
        "--require-private",
        help="Treat source/ or private/ not on this machine as a failure (exit 1): use it "
             "after copying prints/ to another machine, where they should have come "
             "along.")] = False,
    prints_dir: PrintsDir = None,
    jobs_dir: Annotated[Path | None, typer.Option(
        "--jobs-dir", help="Where to look for a job whose finish did not end; default "
                           "jobs/ in the source checkout.")] = None,
) -> None:
    """Check the library's entries: each has COMPLETE, and every file
    is the one COMPLETE lists (SHA-256), with no file missing or extra;
    STAGED, purge.json, provenance.json and job.yaml agree with
    COMPLETE; the source is present.

    source/ and private/ are git-ignored, so a clone has neither: a
    folder of them missing entirely is reported as unavailable (not on
    this machine), not as damage. A file in them that is missing or
    different is damage.

    An entry without COMPLETE, a leftover .staging-NAME folder, or an
    entry whose job (or its .purging- tombstone) is still in the jobs
    folder is incomplete: an interrupted tdmg finish; run tdmg finish
    NAME again. A file the operating system adds (.DS_Store, ._*,
    Thumbs.db, desktop.ini) is damage, said as such: deleting it is
    safe.

    Exit codes:
      0  every entry is complete and every hash matches. source/ or
         private/ not on this machine is a note, not a failure (it is
         the normal state of a clone), unless --require-private
      1  an entry is damaged (a file changed, missing or extra; COMPLETE
         not in its form; the records disagree) or incomplete
      2  cannot check: no library folder, no entry NAME, a bad name
    """
    try:
        found = check_library(name, prints_dir=prints_dir, jobs_dir=jobs_dir)
    except LibraryError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:
        _os_error(e)
        raise typer.Exit(2) from None
    except Exception as e:  # noqa: BLE001 - a bug: say so, and exit 2 like any refusal
        typer.echo(f"error: unexpected {type(e).__name__} in tdmg library check: {e}",
                   err=True)
        raise typer.Exit(2) from None
    failed = False
    for c in found:
        missing = [unavailable_text(top) for top in c.unavailable]
        word = {"ok": "ok", "incomplete": "INCOMPLETE", "damaged": "DAMAGED"}[c.state]
        if c.state == "ok" and missing and require_private:
            word = "UNAVAILABLE"
        typer.echo(f"{c.name}: {word}")
        for p in c.problems:
            typer.echo(f"  {p}")
        for m in missing:
            typer.echo(f"  note: {m}")
        failed |= c.state != "ok" or (require_private and bool(missing))
    if not found:
        typer.echo("the library has no entries")
    typer.echo(f"{len(found)} checked: {sum(c.state == 'ok' for c in found)} ok, "
               f"{sum(c.state == 'incomplete' for c in found)} incomplete, "
               f"{sum(c.state == 'damaged' for c in found)} damaged; "
               f"{sum(SOURCE_DIR in c.unavailable for c in found)} without their source on "
               "this machine")
    if failed:
        raise typer.Exit(1)


@library_app.command("verify")
def library_verify(
    name: Annotated[str, typer.Argument(help="The entry (PRINTS_DIR/NAME).")],
    slicer_dir: SlicerDir = None,
    prusaslicer_dir: PrusaDir = None,
    prints_dir: PrintsDir = None,
) -> None:
    """Run an entry's job again under the current code and rules, in a
    scratch folder, from its job.yaml and source/, and report how it
    differs from the historical run that provenance.json records.

    Compared: every stage done; each stage record's SHA-256 (byte for
    byte; slice.json with its G-code hash fields masked, and each G-code
    file without its timestamp line, as finish's rebuild compares them);
    each stage's algorithm, verdicts and checks (status, rule,
    threshold); the slice record's identity; the confirmed route's
    printable files (SHA-256, so byte for byte) and their verdicts. Not
    compared: the stages' other files (the job's own were purged) and
    the checks' measured values (provenance.json does not hold them). It
    also says what changed since then: code commit, versions, key
    libraries, rules, algorithm ids, profiles.

    The slice stage's results depend on whether PrusaSlicer is
    configured; verify says which the historical run had. Give the
    --slicer-dir (and --prusaslicer-dir) the slice stage needs. Nothing
    is written into the library; the historical verdict is never
    rewritten.

    Exit codes:
      0  identical under the comparison rule
      1  it differs (information, not an error: the code or the rules
         may have changed; see what changed), including a stage the
         current code refuses
      2  cannot run: no such entry, the entry does not check (tdmg
         library check), the source is not on this machine, the pinned
         slicer cannot be used on this machine, or the temporary folder
         is inside prints/ or jobs/
    """
    try:
        differences = verify(name, machine=Machine(slicer_dir, prusaslicer_dir),
                             prints_dir=prints_dir, say=typer.echo)
    except (LibraryError, JobError, RecordError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:
        _os_error(e)
        raise typer.Exit(2) from None
    except Exception as e:  # noqa: BLE001 - a bug: say so, and exit 2 like any refusal
        typer.echo(f"error: unexpected {type(e).__name__} in tdmg library verify: {e}",
                   err=True)
        raise typer.Exit(2) from None
    if differences:
        typer.echo(f"differs from the historical run ({len(differences)}):")
        for d in differences:
            typer.echo(f"  {d}")
    else:
        typer.echo("identical to the historical run under the comparison rule")
    for text in NOT_COMPARED:
        typer.echo(f"  not compared: {text}")
    if differences:
        raise typer.Exit(1)


def main() -> None:
    """The tdmg console script (pyproject [project.scripts]) and python -m tdmg.cli.

    Click expands every argument on Windows by default (expanduser, expandvars, glob), so
    the owner's words ('$HOME', '%USERNAME%', '~ x', '*.png') would be rewritten even
    inside shell single quotes; tdmg records words verbatim, so that is turned off. Tested
    in tests/test_entry_point.py."""
    app(windows_expand_args=False)


if __name__ == "__main__":
    main()

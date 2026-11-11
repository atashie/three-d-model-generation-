"""Command-line interface. Phase 0 exposes the registries. Phase 1 has `select` (subject
selection for review), `flat` (flat geometry from a selection, gated on the written
STL) and `slice` (the flat STL sliced with the pinned OrcaSlicer, F6, and checked for
portability with the pinned PrusaSlicer). R2 adds `colors` (the color plan of a selection,
for review); `make` and `check` follow."""

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from tdmg import __version__
from tdmg.color_outline import THIN_SHARE_RULE
from tdmg.colors import ColorsError, extracted_text, make_colors
from tdmg.flat import FlatError, make_flat
from tdmg.portability import PRUSA_FAILED_GCODE_NAME, PRUSA_GCODE_NAME, PRUSA_GCODE_NOTE
from tdmg.profiles import load_printer, printer_ids
from tdmg.recipes import ATTRIBUTE_LABELS, RECIPES
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
from tdmg.slicing import DO_NOT_PRINT, PRINT_THIS, PRUSA_DO_NOT_PRINT, make_slice

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
    """List the print recipes and their status."""
    for r in RECIPES:
        colors = "/".join(c.value for c in r.colors)
        attrs = f"{r.geometry.value}-{r.articulation.value}-{colors}-{r.assembly.value}"
        typer.echo(f"{r.id}  {r.name:24s} {attrs:16s} {r.status.value:12s} "
                   f"phase {r.roadmap_phase}  ({ATTRIBUTE_LABELS[r.geometry.value]})")


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
    selection: Annotated[Path, typer.Argument(exists=True, file_okay=False,
                                              metavar="SELECTION_DIR",
                                              help="A tdmg select output folder.")],
    width_mm: Annotated[float, typer.Option(
        "--width-mm", help="Width of the selection in the model, in mm.")],
    thickness_mm: Annotated[float, typer.Option(
        "--thickness-mm", help="Thickness of the flat solid, in mm.")],
    out: Annotated[Path, typer.Option("--out", help="New or empty folder for the outputs.")],
    printer: Annotated[str, typer.Option(
        "--printer", help="Printer profile id (see `tdmg printers`).")] = "bambu-a1",
    smooth_px: Annotated[float | None, typer.Option(
        "--smooth-px", help="Gaussian smoothing of the outline in image pixels; default from "
                            "rule flat.smooth.sigma_px; 0 keeps the exact pixel outline")] = None,
) -> None:
    """Make a flat solid from a selection: write model.stl, outline.png and flat.json.

    Exit codes:
      0  files written, and no check FAILed (UNKNOWN checks allowed)
      1  files written, and at least one check FAILed
      2  input or usage error: nothing is written; or an I/O failure
         while writing, which can leave a folder without flat.json:
         such a folder is incomplete and must not be used
    Exit 0 does not mean the part is certified; read verdict in flat.json.
    """
    # Typer's Rich help keeps the single line breaks of every paragraph after the first,
    # so the list above renders line for line. Each line is under 76 characters, so an
    # 80-column terminal does not wrap it (tests/test_cli.py checks this).
    try:
        rec = make_flat(selection, width_mm, thickness_mm, out, printer=printer,
                        smooth_px=smooth_px)
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


def _portability_line(rec: dict) -> str:
    """'portability: ...': PrusaSlicer's verdict and what it read, or why it did not run."""
    check = next(c for c in rec["checks"] if c["id"] == "F6.portability")
    port = rec["portability"]
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


@app.command("slice")
def slice_(
    flat_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False, metavar="FLAT_DIR",
                                             help="A tdmg flat output folder.")],
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
) -> None:
    """Slice a flat model with the pinned OrcaSlicer: write the G-code and slice.json.

    With PrusaSlicer configured, F6.portability checks that a second slicer
    accepts model.stl as modelled and slices its full height (both read STL
    with admesh); prusaslicer.portability-only.gcode.txt is generic G-code,
    never for the A1.

    Exit codes:
      0  files written, and no check FAILed (UNKNOWN checks allowed)
      1  files written, and at least one check FAILed
      2  input or setup error (including a missing or unverified
         slicer): nothing is written; or an I/O failure while
         writing, which can leave a folder without slice.json:
         such a folder is incomplete and must not be used
    Exit 0 does not mean the part is certified; read verdict in slice.json.
    """
    try:
        rec = make_slice(flat_dir, out, slicer_dir=slicer_dir, timeout_s=timeout_s,
                         check_tree=not skip_tree_check, prusaslicer_dir=prusaslicer_dir)
    except SlicerError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:              # unreadable input, unwritable output, disk full ...
        _os_error(e)
        raise typer.Exit(2) from None
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
                          rules=load_rules(), printer=load_printer("bambu-a1"))
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


if __name__ == "__main__":
    app()

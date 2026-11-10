"""Command-line interface. Phase 0 exposes the registries. Phase 1 has `select` (subject
selection for review) and `flat` (flat geometry from a selection, gated on the written
STL); `make` and `check` follow."""

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from tdmg import __version__
from tdmg.flat import FlatError, make_flat
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
    """'smoothing off', or the sigma, its source, the sampled boundary change and the
    area removed and added, in mm (ASCII only, so any console encoding can print it)."""
    smoothing = record["smoothing"]
    if not smoothing["applied"]:
        return "smoothing off"
    sigma = smoothing["sigma_px"]
    source = f"rule {sigma['rule']}" if sigma["rule"] else "set by --smooth-px"
    scale = record["transform"]["scale_mm_per_px"]
    bound = smoothing["boundary_hausdorff_lower_bound_px"]
    moved = "unknown" if bound is None else f"at least {bound * scale:.3g} mm (sampled)"
    removed = smoothing["removed_area_px2"] * scale ** 2
    added = smoothing["added_area_px2"] * scale ** 2
    return (f"smoothing sigma {sigma['value']:g} px ({source}): boundary changed by {moved}, "
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


if __name__ == "__main__":
    app()

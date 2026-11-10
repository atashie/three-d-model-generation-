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


@app.command()
def flat(
    selection: Annotated[Path, typer.Argument(exists=True, file_okay=False,
                                              help="A tdmg select output folder.")],
    width_mm: Annotated[float, typer.Option(
        "--width-mm", help="Width of the selection in the model, in mm.")],
    thickness_mm: Annotated[float, typer.Option(
        "--thickness-mm", help="Thickness of the flat solid, in mm.")],
    out: Annotated[Path, typer.Option("--out", help="New or empty folder for the outputs.")],
    printer: Annotated[str, typer.Option(
        "--printer", help="Printer profile id (see `tdmg printers`).")] = "bambu-a1",
) -> None:
    """Make a flat solid from a selection: write model.stl, outline.png and flat.json.

    Exit codes: 0 if the files were written and no check FAILed.

    (A NOT CERTIFIED verdict with only UNKNOWN checks still exits 0.)

    1 if any check FAILed; the files are still written, for review.

    2 for input and usage errors; nothing is written.
    """
    try:
        rec = make_flat(selection, width_mm, thickness_mm, out, printer=printer)
    except (FlatError, SelectionError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    except OSError as e:              # unreadable selection, unwritable output, disk full ...
        _os_error(e)
        raise typer.Exit(2) from None
    typer.echo(f"verdict {rec['verdict']}")
    for c in rec["checks"]:
        if c["status"] != "PASS":
            note = f": {c['note']}" if c["note"] else ""
            typer.echo(f"  {c['id']} {c['status']}{note}")
    mesh = rec["mesh"]
    size = " x ".join(f"{e:.2f}" for e in mesh["extents_mm"])
    bodies = f"{mesh['bodies']} bod{'y' if mesh['bodies'] == 1 else 'ies'}"
    typer.echo(f"size {size} mm, {mesh['triangles']} triangles, {bodies}")
    typer.echo(f"flat_id {rec['flat_id']}")
    typer.echo(f"wrote {out / 'model.stl'}")
    typer.echo(f"wrote {out / 'outline.png'} - open outline.png to check what cleaning removed")
    if any(c["status"] == "FAIL" for c in rec["checks"]):
        raise typer.Exit(1)


if __name__ == "__main__":
    app()

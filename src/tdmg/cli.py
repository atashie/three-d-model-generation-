"""Command-line interface. Phase 0 exposes the registries. Phase 1 starts with `select`
(subject selection for review); `make` and `check` follow."""

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from tdmg import __version__
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
        where = f": {e.filename}" if e.filename else ""
        typer.echo(f"error: {e.strerror or e}{where}", err=True)
        raise typer.Exit(2) from None
    r = rec["result"]
    typer.echo(f"status {r['status']}: {r['selected_px']} px in {len(r['pieces_px'])} piece(s), "
               f"{len(r['holes_px'])} hole(s)")
    for w in r["warnings"]:
        typer.echo(f"warning: {w}")
    typer.echo(f"selection_id {rec['selection_id']}")
    typer.echo(f"wrote {out / 'preview.png'} - check the subject before going on")


if __name__ == "__main__":
    app()

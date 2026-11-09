"""Command-line interface. Phase 0 exposes the registries; `make` and `check` arrive in Phase 1."""

import typer

from tdmg import __version__
from tdmg.profiles import load_printer, printer_ids
from tdmg.recipes import ATTRIBUTE_LABELS, RECIPES
from tdmg.rules import load_rules

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


if __name__ == "__main__":
    app()

"""How much of the kept outline band survives the region cleanup, by band width
(docs/plans/2026-11-11-color-palette.md, Task 7e-b; research README addendum
"kept band width against cleanup").

For each selection and each width W in WIDTHS_MM it runs tdmg.color_plan.plan_colors with
the `tdmg colors` defaults (extract 6, outline_color auto), outlines keep, outline_width_mm
W and each of the selection's merge settings in MERGES, printer bambu-a1, at WIDTH_MM wide.
Then:
- band: the pixels of plan.outline.band (tdmg.color_outline.stroke_band; painted in the
  core color after the merges);
- lost: band pixels whose label after clean_regions (plan.cleaned) is not the core's
  final color: the band pixels the cleanup took away;
- cleanup: clean_regions' pixels_changed and passes, and the final palette.
Software only, no print.

Usage (from the repo root):
  uv run python research/verification/2026-11-11-color-palette/measure_band_survival.py \
      artifacts/selection-runs/roadie-tol30 artifacts/selection-runs/oddie
"""

from __future__ import annotations

import hashlib
import platform
import sys
from pathlib import Path

import numpy as np
import scipy

from tdmg.color import printable_limits_px
from tdmg.color_config import resolve_color_config
from tdmg.color_plan import plan_colors
from tdmg.colors import mask_mm_per_px
from tdmg.profiles import load_printer
from tdmg.rules import load_rules
from tdmg.selection import read_selection

WIDTH_MM = 60.0
WIDTHS_MM = (0.45, 0.5, 0.6)
# The merge settings measured per selection: Oddie with its blues merged (the Task 7e-b
# first measurement) and with blues and greens merged (the owner's Task 7d choice).
MERGES = {"roadie-tol30": [[]], "oddie": [[[3, 1]], [[3, 1], [2, 0]]]}


def main(selection_dirs: list[str]) -> None:
    rules, printer = load_rules(), load_printer("bambu-a1")
    me = Path(__file__)
    print(f"{me.name} sha256 {hashlib.sha256(me.read_bytes()).hexdigest()}; python "
          f"{platform.python_version()}, numpy {np.__version__}, scipy {scipy.__version__}")
    print(f"width {WIDTH_MM} mm, printer {printer.id}, outlines keep, extract 6, "
          "outline_color auto")
    for d in selection_dirs:
        name = Path(d).name
        sel = read_selection(d, cutout=True)
        mm = mask_mm_per_px(sel.mask, WIDTH_MM)
        limits = printable_limits_px(mm, rules, printer)
        for merge in MERGES.get(name, [[]]):
            print(f"== {name}: selection_id {sel.record['selection_id']}, {mm:.6f} mm/px, "
                  f"opening {limits.min_width_px:.3f} px, merge {merge}")
            _widths(sel, limits, rules, printer, merge, mm)


def _widths(sel, limits, rules, printer, merge, mm) -> None:
    for w in WIDTHS_MM:
        flags = {"colors": None, "edges": None, "base": None, "outlines": "keep",
                 "merge": merge, "outline_width_mm": w}
        s = resolve_color_config(flags, None, rules, printer).settings
        p = plan_colors(sel.cutout_rgb, sel.mask, s, limits, rules)
        band = p.outline.band
        ci = p.cleaned.hex.index(p.extracted.hex[p.outline.core])
        lost = band & (p.cleaned.labels != ci)
        print(f"   W {w} mm ({w / mm:.2f} px): band {int(band.sum())} px, lost in cleanup "
              f"{int(lost.sum())} px ({lost.sum() / band.sum():.1%}); cleanup changed "
              f"{p.log.pixels_changed} px in {p.log.passes} passes; final "
              f"{list(p.cleaned.hex)}")


if __name__ == "__main__":
    main(sys.argv[1:])

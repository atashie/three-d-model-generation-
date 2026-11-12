"""Task 5 of docs/plans/2026-11-12-color-geometry.md: the glue route on the approved plans.

For each approved owner plan (artifacts/colors-runs/*-f64, git-ignored), S, the regions and
the cells are built as in measure_bodies.py (color_regions, color_cells), then
tdmg.color_glue.glue_geometry at T = 3.0 mm with the rule defaults (color.skin.depth_mm,
color.glue.clearance_mm, color.glue.min_piece_side_mm, flat.sliver.opening_width,
(flat.island.min_square_side x the printer's nozzle)^2), and
tdmg.color_checks.glue_checks with the plan's printer.

With the owner's amendment to Decision 8 ("Fold small pieces too"): a candidate folds
when none of its pieces reaches the min-piece area; the others keep only those pieces,
their pockets are cut from the pieces' buffers, and the rest goes to the base.

It prints per plan: the folds, the leftover area per color that went to the base (and the
small pieces dropped), the rebuild's pinch joins, pieces per color (count, smallest and
largest area), empty pockets, the smallest glue gap and the F4.glue_fit threshold, F4.glue_partition, the uncovered pocket area, every check's status (failing ones with their
measurements), triangles per plate, and times.

Run: uv run python research/verification/2026-11-12-color-geometry/measure_glue.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from tdmg.color_checks import glue_checks
from tdmg.color_geometry import color_cells, color_regions
from tdmg.color_glue import glue_geometry
from tdmg.colors_verify import verify_colors
from tdmg.flat import ISLAND_RULE, OPENING_RULE
from tdmg.profiles import load_printer
from tdmg.rules import load_rules
from tdmg.selection import read_selection
from tdmg.smoothing import smooth_labels

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_bodies import SKIN_RULE, THICKNESS_MM
from measure_regions import ROOT, RUNS, silhouette

CLEARANCE_RULE = "color.glue.clearance_mm"
MIN_SIDE_RULE = "color.glue.min_piece_side_mm"


def main():
    rules = load_rules()
    opening = float(rules[OPENING_RULE].default)
    skin = float(rules[SKIN_RULE].default)
    clearance = float(rules[CLEARANCE_RULE].default)
    side = float(rules[MIN_SIDE_RULE].default)
    for plan, sel in RUNS:
        sel_dir = ROOT / "artifacts" / "selection-runs" / sel
        v = verify_colors(ROOT / "artifacts" / "colors-runs" / plan, sel_dir,
                          check_preview=False)
        mask = read_selection(sel_dir).mask
        printer = load_printer(v.record["identity"]["printer"])
        nozzle = float(printer.nozzle_diameter_mm)
        island = (float(rules[ISLAND_RULE].default) * nozzle) ** 2
        region, transform = silhouette(mask, v.width_mm, rules, nozzle)
        fine = smooth_labels(v.labels, v.sigma_px, v.supersample).fine
        regions = color_regions(fine, v.supersample, transform, region,
                                n_colors=len(v.palette), base_index=v.base_index,
                                thin_width_mm=opening)
        cells = color_cells(regions, region, v.base_index)
        t0 = time.perf_counter()
        glue = glue_geometry(cells, thickness_mm=THICKNESS_MM, skin_mm=skin,
                             clearance_mm=clearance, min_piece_side_mm=side,
                             opening_mm=opening, min_island_mm2=island)
        t1 = time.perf_counter()
        result = glue_checks(glue, printer=printer, rules=rules)
        t2 = time.perf_counter()
        rep = glue.report
        print(f"== {plan}: T {THICKNESS_MM} mm, d {skin} mm, clearance {clearance} mm, "
              f"min piece {side} mm ({rep['min_piece_area_mm2']} mm^2), opening {opening} "
              f"mm, island {island:.4g} mm^2, base {v.base_index}; {len(cells.cells)} "
              f"cells in; glue_geometry {t1 - t0:.2f} s, glue_checks {t2 - t1:.2f} s")
        print(f"  folds: {len(rep['folds'])}")
        for f in rep["folds"]:
            print(f"    color {f['label']} ({f['cells']} cells, {f['region_area_mm2']:.4g} "
                  f"mm^2 unshrunk; {f['pieces']} pieces, {f['area_mm2']:.4g} mm^2, largest "
                  f"{f['largest_piece_mm2']:.4g} mm^2) -> "
                  f"{'base ' if f['into_base'] else 'color '}{f['into']}, shared "
                  f"{f['shared_mm']:.4g} mm; neighbours "
                  + ", ".join(f"{c}: {length:.4g}" for c, length in f["neighbours"]))
        print(f"  leftover to the base: total {rep['leftover_mm2']:.4g} mm^2; per color:")
        for r in rep["leftover"]:
            print(f"    color {r['index']}: {r['candidates']} candidates, "
                  f"{r['candidate_area_mm2']:.4g} mm^2 -> pockets "
                  f"{r['pocket_area_mm2']:.4g} mm^2, leftover {r['leftover_mm2']:.4g} mm^2;"
                  f" {r['small_pieces']} small pieces dropped "
                  f"({r['small_pieces_mm2']:.4g} mm^2)")
        pin = rep["rebuild"]["pinches"]
        print(f"  rebuild (information): grid {rep['grid_mm']:.6g} mm, "
              f"{len(glue.cells.cells)} cells; pinches {pin['fixed']} joined in "
              f"{pin['rounds']} rounds, area moved {pin['area_moved_mm2']:.2e} mm^2; "
              f"silhouette pinches {rep['silhouette_pinches']}")
        print(f"  pockets {len(glue.pockets)}, pieces {len(glue.pieces)}; per color:")
        for c in rep["colors"]:
            print(f"    color {c['index']}: {c['pockets']} pockets, {c['pieces']} pieces, "
                  f"smallest {c['smallest_mm2']:.4g} mm^2, largest {c['largest_mm2']:.4g} "
                  f"mm^2, total {c['area_mm2']:.4g} mm^2")
        print(f"  empty pockets: {rep['empty_pockets']}")
        print(f"  uncovered pocket area (information): total {rep['uncovered_mm2']:.4g} "
              f"mm^2; largest per pocket "
              + ", ".join(f"#{p['number']} {p['uncovered_mm2']:.3g}/{p['area_mm2']:.4g}"
                          for p in sorted(rep["pockets"],
                                          key=lambda p: -p["uncovered_mm2"])[:3]))
        part, fit = result["assembly"]
        m, t = part.measured, part.threshold
        print(f"  {part.id} {part.status}: S xor cells {m['snap_silhouette_mm2']:.2e}/"
              f"{t['snap_silhouette_mm2']:.2e} mm^2, pocket overlap {m['overlap_mm2']:.1e}/"
              f"{t['area_tol_mm2']:.1e} mm^2, outside S {m['outside_mm2']:.1e} mm^2, base "
              f"volume error {m['volume_error_mm3']:.2e}/{t['volume_tol_mm3']:.2e} mm^3")
        gap = fit.measured["min_gap_mm"]
        print(f"  {fit.id} {fit.status}: min gap "
              f"{'none' if gap is None else f'{gap:.6f}'} mm >= threshold "
              f"{fit.threshold['min_gap_mm']:.6f} mm (margin "
              f"{fit.threshold['margin_mm']:.3e}: wall chord "
              f"{fit.threshold['shrink_chord_mm']:.3e}, opening chord "
              f"{fit.threshold['opening_chord_mm']:.3e}, pocket move "
              f"{fit.threshold['pocket_move_mm']:.3e}, snap "
              f"{fit.threshold['snap_move_mm']:.3e}); per piece smallest 3: "
              + ", ".join(f"#{r['number']} {r['gap_mm']:.6f}"
                          for r in sorted(fit.measured["per_piece"],
                                          key=lambda r: (r["gap_mm"] is not None, r["gap_mm"] or 0))[:3]))
        for r in fit.measured["per_piece"]:
            if not r["pass"]:
                print(f"    FAIL piece {r}")
        for body in glue.bodies:
            checks = result["bodies"][body.name] + result["plates"][body.name]
            fails = [c for c in checks if c.status != "PASS"]
            tri = next(c for c in result["plates"][body.name] if c.id == "F5.triangles")
            print(f"  {body.name}: {len(body.parts)} parts, plate triangles {tri.measured}"
                  f" / {tri.threshold}; {len(checks)} checks "
                  f"{'all PASS' if not fails else 'NOT ALL PASS'}")
            print("    " + ", ".join(f"{c.id} {c.status}" for c in checks))
            for c in fails:
                print(f"    {c.id} {c.status}: {c.measured}")


if __name__ == "__main__":
    main()

"""Task 4 of docs/plans/2026-11-12-color-geometry.md: AMS bodies and checks on the approved plans.

For each approved owner plan (artifacts/colors-runs/*-f64, git-ignored), S is built as in
measure_regions.py (imported from it), then color_regions, color_cells (the storage grid
and labelled cells), ams_bodies at T = 3.0 mm and d = color.skin.depth_mm (rule default),
and ams_checks with colors = the plan's colors setting and palette_cap from the plan's
printer profile.

It prints per plan: the grid and the grid shift, every check's status and a compact
measured value, the pinch fixes, triangles per body and in total, the smallest cell, the failing F1
measurements with the first degenerate faces, and times.

Run: uv run python research/verification/2026-11-12-color-geometry/measure_bodies.py
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import numpy as np
import shapely
import trimesh

from tdmg.checks import merge_exact
from tdmg.color_checks import ams_checks
from tdmg.color_config import palette_cap
from tdmg.color_geometry import ams_bodies, color_cells, color_regions
from tdmg.colors_verify import verify_colors
from tdmg.flat import OPENING_RULE, encode_stl
from tdmg.profiles import load_printer
from tdmg.rules import load_rules
from tdmg.selection import read_selection
from tdmg.smoothing import smooth_labels

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_regions import ROOT, RUNS, silhouette

THICKNESS_MM = 3.0  # the plans' approved test thickness (60 x 3 mm), an input
SKIN_RULE = "color.skin.depth_mm"
LISTED = 4  # display only: how many bad faces are described per body


def bad_faces(body, region, base_top):
    """Faces of the stored STL that are degenerate (repeated index or zero area), described
    by their float64 source triangle: z values, shortest edge, and the distance of the
    centroid to S's boundary and to the base-colored cells' boundary."""
    data = encode_stl(body.mesh)
    g = merge_exact(trimesh.load(io.BytesIO(data), file_type="stl", process=False))
    f = np.asarray(g.faces)
    t = np.asarray(g.vertices)[f]
    cross = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    bad = np.nonzero(~cross.any(axis=1) | (f[:, 0] == f[:, 1]) | (f[:, 1] == f[:, 2])
                     | (f[:, 0] == f[:, 2]))[0]
    t64 = np.asarray(body.mesh.vertices)[np.asarray(body.mesh.faces)]  # STL keeps the order
    top = shapely.union_all(base_top).boundary if base_top else None
    out = []
    for k in bad[:LISTED]:
        tri = t64[k]
        edge = np.linalg.norm(tri - np.roll(tri, 1, axis=0), axis=1).min()
        c = shapely.Point(tri[:, :2].mean(axis=0))
        out.append(f"z {sorted(set(tri[:, 2].tolist()))}, shortest edge {edge:.1e}, "
                   f"to S boundary {region.boundary.distance(c):.1e}, to base_top boundary "
                   f"{top.distance(c) if top is not None else float('nan'):.1e}")
    return len(bad), out


def compact(check):
    m = check.measured
    if check.id.startswith("F1."):
        return {k: v for k, v in m.items() if k != "body_volumes"} if isinstance(m, dict) else m
    if check.id == "F2.export_matches_geometry":
        return (f"bound_err {m['max_bound_error_mm']:.1e}/{check.threshold['coord_tol_mm']:.1e}"
                f" vol_err {m['volume_error_mm3']:.1e}/{check.threshold['volume_tol_mm3']:.1e}")
    if check.id == "F4.color_partition":
        t = check.threshold
        snap = "; ".join(f"{e['index']}: {e['mm2']:.2e}/{e['bound_mm2']:.2e}"
                         for e in m["snap_colors"])
        return (f"raw: {m['raw_pieces']} pieces, overlap {m['raw_overlap_mm2']:.1e}, "
                f"symdiff {m['raw_symmetric_difference_mm2']:.1e} / "
                f"{t['raw_area_tol_mm2']:.1e} mm^2; snap (d {t['snap_move_mm']:.2e} mm): "
                f"S {m['snap_silhouette_mm2']:.2e}/{t['snap_silhouette_mm2']:.2e}, per "
                f"color {snap} mm^2; cells: {m['pieces']}, overlap {m['overlap_mm2']:.1e}, "
                f"symdiff {m['symmetric_difference_mm2']:.1e} / {t['area_tol_mm2']:.1e} "
                f"mm^2; vol_err {m['volume_error_mm3']:.2e}/{t['volume_tol_mm3']:.2e} mm^3")
    if check.id == "F2.fits_build_volume":
        return [round(v, 3) for v in m]
    return f"{m} / {check.threshold}"


def main():
    rules = load_rules()
    opening = float(rules[OPENING_RULE].default)
    skin = float(rules[SKIN_RULE].default)
    for plan, sel in RUNS:
        sel_dir = ROOT / "artifacts" / "selection-runs" / sel
        v = verify_colors(ROOT / "artifacts" / "colors-runs" / plan, sel_dir,
                          check_preview=False)
        mask = read_selection(sel_dir).mask
        printer = load_printer(v.record["identity"]["printer"])
        region, transform = silhouette(mask, v.width_mm, rules,
                                       float(printer.nozzle_diameter_mm))
        fine = smooth_labels(v.labels, v.sigma_px, v.supersample).fine
        regions = color_regions(fine, v.supersample, transform, region,
                                n_colors=len(v.palette), base_index=v.base_index,
                                thin_width_mm=opening)
        colors = v.record["identity"]["settings"]["colors"]
        cap = palette_cap(printer)
        t0 = time.perf_counter()
        cells = color_cells(regions, region, v.base_index)
        t1 = time.perf_counter()
        bodies = ams_bodies(cells, thickness_mm=THICKNESS_MM, skin_mm=skin)
        t2 = time.perf_counter()
        result = ams_checks(bodies, cells, THICKNESS_MM, colors=colors,
                            palette_cap=cap, printer=printer, rules=rules)
        t3 = time.perf_counter()
        top = cells.of(v.base_index)
        smallest = min((c.area, k) for c, k in zip(cells.cells, cells.labels, strict=True))
        rep = cells.report
        print(f"== {plan}: T {THICKNESS_MM} mm, d {skin} mm, colors {colors}, cap {cap}; "
              f"color_cells {t1 - t0:.2f} s, ams_bodies {t2 - t1:.2f} s, ams_checks "
              f"{t3 - t2:.2f} s")
        print(f"  grid G {rep['grid_mm']:.6g} mm (max |x|,|y| {rep['max_abs_coord_mm']:.4f}"
              f" mm); {rep['faces']} faces, {rep['cells']} cells; grid shift (information):"
              f" S {rep['silhouette_shift_mm2']:.2e} mm^2 (perimeter x G sqrt(2)/2 = "
              f"{region.length * rep['grid_mm'] * 2 ** 0.5 / 2:.2e}), relabelled "
              f"{rep['relabelled_mm2']:.2e} mm^2, per color "
              + ", ".join(f"{c['index']}: {c['cells']} cells {c['shift_mm2']:.2e}"
                          for c in rep["colors"]))
        pin = rep["pinches"]
        print(f"  pinches (information): {pin['fixed']} fixed in {pin['rounds']} rounds, "
              f"radius {pin['radius_mm']:.3g} mm, area moved {pin['area_moved_mm2']:.2e} "
              f"mm^2, per color {pin['colors']}; silhouette pinches "
              f"{pin['silhouette_pinches']}")
        total = 0
        for b in bodies:
            checks = result["bodies"][b.name]
            fails = [c for c in checks if c.status != "PASS"]
            total += len(b.mesh.faces)
            parts = [len(polys) for polys, _, _ in b.slabs]
            print(f"  {b.name}: {len(b.mesh.faces)} triangles, cells per z range {parts}; "
                  f"{'all PASS' if not fails else 'NOT ALL PASS'}")
            for c in checks:
                if c.status != "PASS" or c.id == "F2.export_matches_geometry":
                    print(f"    {c.id} {c.status}: {compact(c)}")
            if fails:
                n, described = bad_faces(b, region, top)
                print(f"    {n} degenerate STL faces; first {len(described)}:")
                for line in described:
                    print(f"      {line}")
        print(f"  total triangles {total}; smallest cell {smallest[0]:.3e} mm^2 "
              f"(color {smallest[1]})")
        for c in result["assembly"]:
            print(f"  {c.id} {c.status}: {compact(c)}")


if __name__ == "__main__":
    main()

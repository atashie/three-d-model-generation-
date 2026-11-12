"""Task 1 of docs/plans/2026-11-12-color-geometry.md: measure vectorizing the fine label map.

For each approved owner plan (artifacts/colors-runs/*-f64, git-ignored), at the plan's
width and 3 mm thick, with the 0.6 mm skin:
- the R1 silhouette S: smooth_outline at flat.smooth.sigma_px, intersected with the image
  box, to_model, clean (the R1 rules);
- the fine map: smooth_labels with the plan's sigma and supersample;
- per color: mask_outline(fine == c) scaled by 1/s, and coverage_is_valid on them all;
- for each SIMPLIFY_PX candidate: coverage_simplify, vertex count, the largest
  boundary-to-boundary distance from the raw polygons (hausdorff, densified), and, after
  clipping to S in mm with each GRID_MM candidate, the pairwise overlap area, the gap area
  (area of S minus the union of the clipped colors) and the extruded triangle count;
- the run time of each stage.

Run: uv run python research/verification/2026-11-12-color-geometry/measure_vectorize.py
Output goes to stdout; the record is vectorize.txt in this folder.
"""

from __future__ import annotations

import itertools
import time
import tracemalloc
from pathlib import Path

import numpy as np
import shapely
from shapely import affinity

from tdmg.colors_verify import verify_colors
from tdmg.flat import (
    HAUSDORFF_STEP_PX,
    ISLAND_RULE,
    OPENING_RULE,
    SMOOTH_RULE,
    _apply_transform,
    _polygons,
    clean,
    extrude,
    mask_outline,
    to_model,
)
from tdmg.profiles import load_printer
from tdmg.rules import load_rules
from tdmg.selection import read_selection
from tdmg.smoothing import smooth_labels, smooth_outline

ROOT = Path(__file__).resolve().parents[3]
RUNS = [
    ("roadie-drop", "artifacts/colors-runs/roadie-tol30-60-drop-v3-f64",
     "artifacts/selection-runs/roadie-tol30"),
    ("roadie-keep", "artifacts/colors-runs/roadie-tol30-60-keep-v4-f64",
     "artifacts/selection-runs/roadie-tol30"),
    ("oddie-merge-blues", "artifacts/colors-runs/oddie-60-merge-blues-v3-f64",
     "artifacts/selection-runs/oddie"),
    ("oddie-keep-merge", "artifacts/colors-runs/oddie-60-keep-merge-blues-greens-v4-f64",
     "artifacts/selection-runs/oddie"),
]
SKIN_MM = 0.6
THICKNESS_MM = 3.0
SIMPLIFY_FRACTIONS = (0.0, 0.5, 1.0)   # x 1/s image px
GRIDS_MM = (None, 1e-6, 1e-5)
DENSIFY = 0.25                          # hausdorff densify fraction (measurement only)


def silhouette(mask, width_mm, rules, nozzle):
    h, w = mask.shape
    outline = smooth_outline(mask, float(rules[SMOOTH_RULE].default))
    outline = shapely.intersection(outline, shapely.box(0, 0, w, h))
    model, transform = to_model(outline, width_mm)
    island = (float(rules[ISLAND_RULE].default) * nozzle) ** 2
    parts, _ = clean(model, float(rules[OPENING_RULE].default), island,
                     HAUSDORFF_STEP_PX * transform["scale_mm_per_px"])
    return shapely.union_all(parts), transform


def color_polygons(fine, s):
    colors = [int(c) for c in np.unique(fine)]
    polys = [affinity.scale(mask_outline(fine == c), 1 / s, 1 / s, origin=(0, 0))
             for c in colors]
    return colors, polys


def vertices(geoms):
    return int(sum(shapely.get_num_coordinates(g) for g in geoms))


def overlap_and_gap(clipped, region):
    overlap = 0.0
    for a, b in itertools.combinations(clipped, 2):
        overlap += shapely.intersection(a, b).area
    gap = region.area - shapely.union_all(clipped).area
    return overlap, gap


def measure(name, plan_dir, sel_dir, rules):
    out = [f"== {name}: {plan_dir}"]
    t = time.perf_counter()
    v = verify_colors(ROOT / plan_dir, ROOT / sel_dir, check_preview=False)
    mask = read_selection(ROOT / sel_dir).mask
    nozzle = float(load_printer(v.record["identity"]["printer"]).nozzle_diameter_mm)
    out.append(f"verify_colors {time.perf_counter() - t:.2f} s; image {mask.shape[1]} x "
               f"{mask.shape[0]} px, width {v.width_mm} mm, sigma {v.sigma_px} px, "
               f"supersample {v.supersample}, palette {len(v.palette)}, base {v.base_index}")
    t = time.perf_counter()
    region, transform = silhouette(mask, v.width_mm, rules, nozzle)
    out.append(f"silhouette {time.perf_counter() - t:.2f} s; area {region.area:.4f} mm^2, "
               f"scale {transform['scale_mm_per_px']:.6f} mm/px")
    t = time.perf_counter()
    fine = smooth_labels(v.labels, v.sigma_px, v.supersample).fine
    out.append(f"smooth_labels {time.perf_counter() - t:.2f} s; fine {fine.shape[1]} x "
               f"{fine.shape[0]}")
    t = time.perf_counter()
    colors, raw = color_polygons(fine, v.supersample)
    out.append(f"vectorize {time.perf_counter() - t:.2f} s; colors {colors}; raw vertices "
               f"{vertices(raw)}; coverage_is_valid {bool(shapely.coverage_is_valid(raw))}")
    s = v.supersample
    for frac in SIMPLIFY_FRACTIONS:
        tol = frac / s
        t = time.perf_counter()
        simp = raw if tol == 0 else list(shapely.coverage_simplify(raw, tol))
        t_simp = time.perf_counter() - t
        dev = max(shapely.hausdorff_distance(a.boundary, b.boundary, densify=DENSIFY)
                  for a, b in zip(raw, simp, strict=True)) if tol else 0.0
        valid = bool(shapely.coverage_is_valid(simp))
        out.append(f"  SIMPLIFY_PX {tol:.4f} ({frac} / s): {t_simp:.2f} s, vertices "
                   f"{vertices(simp)}, max boundary deviation {dev:.4f} px "
                   f"({dev * transform['scale_mm_per_px']:.5f} mm), coverage valid {valid}")
        mm = [_apply_transform(p, transform) for p in simp]
        for grid in GRIDS_MM:
            t = time.perf_counter()
            clipped = [shapely.intersection(p, region, grid_size=grid) for p in mm]
            t_clip = time.perf_counter() - t
            overlap, gap = overlap_and_gap(clipped, region)
            triangles = 0
            for p in clipped:
                polys, _ = _polygons(p)
                if polys:
                    triangles += len(extrude(polys, SKIN_MM).faces)
            base_tris = len(extrude(_polygons(region)[0], THICKNESS_MM - SKIN_MM).faces)
            out.append(f"    grid {grid}: clip {t_clip:.2f} s, overlap {overlap:.3e} mm^2, "
                       f"gap {gap:.3e} mm^2, skin triangles {triangles}, "
                       f"+ base below skin {base_tris}")
    tracemalloc.start()
    smooth_labels(v.labels, v.sigma_px, v.supersample)
    color_polygons(fine, s)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    out.append(f"tracemalloc peak (smooth_labels + vectorize) {peak / 2**20:.0f} MiB")
    return out


def main():
    rules = load_rules()
    for name, plan, sel in RUNS:
        for line in measure(name, plan, sel, rules):
            print(line, flush=True)


if __name__ == "__main__":
    main()

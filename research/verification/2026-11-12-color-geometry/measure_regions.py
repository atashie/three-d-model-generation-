"""Task 3 of docs/plans/2026-11-12-color-geometry.md: color_regions on the approved plans.

For each approved owner plan (artifacts/colors-runs/*-f64, git-ignored):
- S is built as R1 builds it: smooth_outline at flat.smooth.sigma_px, intersected with the
  image box, to_model, clean (the R1 opening and island rules);
- tdmg.color_geometry.color_regions runs with thin_width_mm = flat.sliver.opening_width.

It prints the time of color_regions; the base top's part count; the base-colored area that
is not the base color in the plan (the base top minus the base color's own fine region
clipped to S), with its positive-area pieces and how many touch S's outline; per inlay
color its status, parts, and thin area and pieces; the base top's thin area; the warnings.

Run: uv run python research/verification/2026-11-12-color-geometry/measure_regions.py
"""

from __future__ import annotations

import time
from pathlib import Path

import shapely

from tdmg.color_geometry import color_regions, fine_regions_px
from tdmg.colors_verify import verify_colors
from tdmg.flat import (
    HAUSDORFF_STEP_PX,
    ISLAND_RULE,
    OPENING_RULE,
    SMOOTH_RULE,
    apply_transform,
    clean,
    to_model,
)
from tdmg.profiles import load_printer
from tdmg.rules import load_rules
from tdmg.selection import read_selection
from tdmg.smoothing import smooth_labels, smooth_outline

ROOT = Path(__file__).resolve().parents[3]
RUNS = [
    ("roadie-tol30-60-drop-v3-f64", "roadie-tol30"),
    ("roadie-tol30-60-keep-v4-f64", "roadie-tol30"),
    ("oddie-60-merge-blues-v3-f64", "oddie"),
    ("oddie-60-keep-merge-blues-greens-v4-f64", "oddie"),
]
TOUCH_MM = 1e-9   # "touches the outline": within this distance of S's boundary (display)


def silhouette(mask, width_mm, rules, nozzle):
    h, w = mask.shape
    outline = smooth_outline(mask, float(rules[SMOOTH_RULE].default))
    outline = shapely.intersection(outline, shapely.box(0, 0, w, h))
    model, transform = to_model(outline, width_mm)
    island = (float(rules[ISLAND_RULE].default) * nozzle) ** 2
    parts, _ = clean(model, float(rules[OPENING_RULE].default), island,
                     HAUSDORFF_STEP_PX * transform["scale_mm_per_px"])
    return shapely.union_all(parts), transform


def main():
    rules = load_rules()
    opening = float(rules[OPENING_RULE].default)
    for plan, sel in RUNS:
        sel_dir = ROOT / "artifacts" / "selection-runs" / sel
        v = verify_colors(ROOT / "artifacts" / "colors-runs" / plan, sel_dir,
                          check_preview=False)
        mask = read_selection(sel_dir).mask
        nozzle = float(load_printer(v.record["identity"]["printer"]).nozzle_diameter_mm)
        region, transform = silhouette(mask, v.width_mm, rules, nozzle)
        fine = smooth_labels(v.labels, v.sigma_px, v.supersample).fine
        t = time.perf_counter()
        result = color_regions(fine, v.supersample, transform, region,
                               n_colors=len(v.palette), base_index=v.base_index,
                               thin_width_mm=opening)
        elapsed = time.perf_counter() - t
        own = fine_regions_px(fine, v.supersample, labels=[v.base_index])[v.base_index]
        own = shapely.intersection(apply_transform(own, transform), region)
        foreign = shapely.union_all(result.base_top).difference(own)
        pieces = [p for p in shapely.get_parts(foreign) if p.area > 0]
        touching = [p for p in pieces if p.distance(region.boundary) < TOUCH_MM]
        print(f"== {plan}: color_regions {elapsed:.2f} s; S {region.area:.1f} mm^2")
        print(f"  base top: {len(result.base_top)} parts; not base color in the plan "
              f"{foreign.area:.3e} mm^2 in {len(pieces)} positive-area pieces "
              f"({len(touching)} touch the outline); thin "
              f"{result.report['base_thin']['area_mm2']:.2f} mm^2")
        for c in result.report["colors"]:
            print(f"  color {c['index']}: {c['status']}, {c['parts']} parts, "
                  f"{c['area_mm2']:.2f} mm^2; thin {c['thin']['area_mm2']:.2f} mm^2 in "
                  f"{c['thin']['pieces']} pieces")
        print(f"  warnings: {result.warnings}")


if __name__ == "__main__":
    main()

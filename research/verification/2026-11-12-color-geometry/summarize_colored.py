"""Task 7 of docs/plans/2026-11-12-color-geometry.md: summarize the owner-plan runs.

Each run was made with the CLI (60 mm from the plan, 3 mm thick, rule defaults):
  uv run tdmg flat artifacts/selection-runs/<sel> --colors artifacts/colors-runs/<plan>
      --thickness-mm 3 --out artifacts/colored-runs/<plan>
The output folders are git-ignored; this prints, from each colored.json, the id, the
verdict, the non-PASS checks, every body (route, color, triangles, footprint area), the
folds, the glue pieces (or why the glue version was not built) and the warnings.

Run: uv run python research/verification/2026-11-12-color-geometry/summarize_colored.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLANS = ("roadie-tol30-60-drop-v3-f64", "roadie-tol30-60-keep-v4-f64",
         "oddie-60-merge-blues-v3-f64", "oddie-60-keep-merge-blues-greens-v4-f64")


def main():
    for plan in PLANS:
        rec = json.loads((ROOT / "artifacts" / "colored-runs" / plan / "colored.json")
                         .read_text(encoding="utf-8"))
        print(f"== {plan}")
        print(f"  colorflat_id {rec['colorflat_id']}; verdict {rec['verdict']}")
        rows = [(b["name"], c) for b in rec["bodies"] for c in b["checks"]]
        rows += [(route, c) for route, checks in rec["assembly"].items() for c in checks]
        open_checks = sorted({f"{c['id']} {c['status']}" for _, c in rows
                              if c["status"] != "PASS"})
        print(f"  non-PASS checks (all bodies and routes): {open_checks}")
        for b in rec["bodies"]:
            print(f"  {b['route']:4} {b['name']:8} {b['role']:5} {b['hex']} "
                  f"{b['triangles']:7d} triangles, footprint {b['footprint_area_mm2']:.2f} mm^2")
        if not rec["glue"]["built"]:
            print(f"  glue: not built - {rec['glue']['reason']}")
            print(f"  warnings: {rec['warnings']}")
            continue
        glue = rec["glue"]["report"]
        folds = [(f["label"], f["into"], round(f["region_area_mm2"], 2)) for f in glue["folds"]]
        print(f"  folds (label, into, region mm^2): {folds}")
        pieces = glue["pieces"]
        areas = [p["area_mm2"] for p in pieces]
        print(f"  glue pieces: {len(pieces)}, smallest {min(areas):.2f} mm^2, "
              f"largest {max(areas):.2f} mm^2; leftover to base {glue['leftover_mm2']:.2f} mm^2")
        print(f"  warnings: {rec['warnings']}")


if __name__ == "__main__":
    main()

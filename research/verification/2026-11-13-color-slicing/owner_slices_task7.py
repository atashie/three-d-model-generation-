"""After the owner's Task 7 decisions (default face up; F3 gated "Outer edge only"):
`tdmg slice` (tdmg.color_slicing.make_color_slice) on the owner's four colored plans,
with both pinned slicers, face up (the default), and once with face="both" for Roadie
drop, compared with the Task 5 cross-check. owner_slices_task6.py and
owner-slices-task6.txt are the Task 6 record (before the decisions) and are kept.

Usage (from the repo root, Windows, both slicers installed as in CLAUDE.md):
    uv run python research/verification/2026-11-13-color-slicing/owner_slices_task7.py

Each plan's folder artifacts/colored-runs/<plan> is sliced into
artifacts/slice-runs/color2-<plan> (and color2-<plan>-both; git-ignored; they must not
exist yet). The summary is printed and written to owner-slices-task7.txt beside this
script. Per face it lists the verdict, the required checks that are not PASS and the
warnings (recorded, not required). The comparison reads
raw/crosscheck-task5.json (Task 5: the same reader and checks on the Task 2 G-codes, which
were sliced with --debug 3 and with filament profiles written with Windows line ends; the
parsed profiles are equal). Research code: not part of the package.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "src"))

from tdmg.color_gcode import GATED_CHECK_IDS, per_tool_id
from tdmg.color_slicing import make_color_slice
from tdmg.printed import F3_SLICE_CHECK_IDS

PLANS = ("roadie-tol30-60-drop-v3-f64", "roadie-tol30-60-keep-v4-f64",
         "oddie-60-merge-blues-v3-f64", "oddie-60-keep-merge-blues-greens-v4-f64")
ORCA = REPO / "artifacts/tools/orcaslicer-2.5.0"
PRUSA = REPO / "artifacts/tools/prusaslicer-2.9.7"


def short(cid: str) -> str:
    return cid.split(".", 1)[1]


def r3(v):
    return None if v is None else round(v, 3)


def main() -> None:
    task5 = json.loads((HERE / "raw/crosscheck-task5.json").read_text("utf-8"))
    lines = []

    def out(text=""):
        print(text)
        lines.append(text)
    out("Task 7 decisions applied: tdmg slice on the owner's four colored plans, face up "
        "by default, and Roadie drop with both faces (OrcaSlicer 2.5.0 and PrusaSlicer "
        "2.9.7, pinned)")
    runs = [(plan, "up") for plan in PLANS] + [(PLANS[0], "both")]
    for plan, face in runs:
        name = f"color2-{plan}" + ("-both" if face == "both" else "")
        dest = REPO / "artifacts/slice-runs" / name
        t0 = time.time()
        rec = make_color_slice(REPO / "artifacts/colored-runs" / plan, dest, ORCA,
                               prusaslicer_dir=PRUSA, face=face)
        seconds = time.time() - t0
        out()
        out(f"== {plan}, face {face} ({seconds:.0f} s) -> artifacts/slice-runs/{name}")
        out(f"   colorslice_id {rec['colorslice_id']}")
        out("   filaments: " + ", ".join(
            f"{f['filament']}={'base' if f['role'] == 'base' else 'color ' + str(f['index'])}"
            f" {f['hex']}" for f in rec["filament_map"]))
        port = rec["portability"]
        check = port["check"]
        m = check["measured"] or {}
        diff = (None if m.get("volume_mm3") is None else
                m["volume_mm3"] - port["expected"]["volume_mm3"])
        out(f"   F6.portability (model.3mf): {check['status']}; parts {m.get('parts')} / "
            f"{port['expected']['parts']}, facets {m.get('facets')} / "
            f"{port['expected']['facets']}, layers {m.get('layers')}, volume "
            f"{m.get('volume_mm3')} mm3 (PrusaSlicer minus palette sum "
            f"{'?' if diff is None else f'{diff:+.3f}'} mm3, information)")
        n = len(rec["filament_map"])
        for face in rec["faces"]:
            f = rec["faces"][face]
            by = {c["id"]: c for c in f["checks"]}
            s = f["summary"]
            f6 = " ".join(f"{short(c)}={by[c]['status']}" for c in GATED_CHECK_IDS)
            slicer = " ".join(f"{short(c)}={by[c]['status']}" for c in (
                "F6.slicer_exit", "F6.gcode_present", "F6.layer_count", "F6.single_object"))
            f3 = " ".join(f"{short(c)}={by[c]['status']}" for c in F3_SLICE_CHECK_IDS)
            tools = "; ".join(f"T{t} " + "/".join(by[per_tool_id(c, t)]["status"]
                                                  for c in F3_SLICE_CHECK_IDS)
                              for t in range(n))
            out(f"   face {face}: {f['verdict']}")
            out(f"     {f6} | F2.orca_input_matches_bodies="
                f"{by['F2.orca_input_matches_bodies']['status']} | {slicer}")
            out(f"     F3 silhouette {f3}; per tool (conn/cov/over) {tools}")
            out(f"     changes {s['changes']}, flush {r3(s['flush_mm3'])} mm3, prime tower "
                f"{r3(s['prime_tower_mm3'])} mm3, time {s['time_s']} s; G-code "
                f"{f['gcode']['file'] if f['gcode'] else None}")
            t5 = task5[f"{plan}-{face}"]
            mine = {"changes": s["changes"], "flush_mm3": r3(s["flush_mm3"]),
                    "prime_tower_mm3": r3(s["prime_tower_mm3"]), "time_s": s["time_s"]}
            theirs = {k: t5["mine"][k] for k in mine}
            statuses = {**{c: by[c]["status"] for c in (*GATED_CHECK_IDS,
                                                        *F3_SLICE_CHECK_IDS)},
                        **{per_tool_id(c, t): by[per_tool_id(c, t)]["status"]
                           for t in range(n) for c in F3_SLICE_CHECK_IDS}}
            t5_statuses = {**t5["statuses"], **t5["per_tool_f3"]}
            differ = [k for k in mine if mine[k] != theirs[k]]
            differ += [k for k in statuses if statuses[k] != t5_statuses.get(k)]
            out(f"     against Task 5: {'equal' if not differ else 'differs: ' + str(differ)}"
                + ("" if not differ else f" (Task 5 {theirs})"))
            out(f"     certification: {f['certification']}")
            for w in f["warnings"]:
                out(f"     warning: {w['text']}")
        glue = rec["glue"]
        if glue["route"] is not None:
            route = glue["route"]
            out("   glue route: " + ("printable" if route["printable"] else
                                     f"not printable; blocking {route['blocking']}"))
        if not glue["built"]:
            out(f"   glue: not built ({glue['reason'][:80]}...)")
        for name, p in glue["plates"].items():
            pby = {c["id"]: c["status"] for c in p["checks"]}
            out(f"   {name}: {p['verdict']} | layers {p['stats'] and p['stats']['layer_count']}"
                f" | F3 " + "/".join(pby[c] for c in F3_SLICE_CHECK_IDS)
                + f" | F6.portability {pby['F6.portability']}")
            out(f"     certification: {p['certification']}")
    (HERE / "owner-slices-task7.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

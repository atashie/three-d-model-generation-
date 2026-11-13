"""Task 5 cross-check: tdmg.color_gcode on the eight Task 2 "colours" G-codes, against this
record's own numbers (raw/analysis-colours.json, raw/rules-colours.json).

Usage (from the repo root, Windows; OUT is the Task 2 work folder that holds
orca/colours/<plan>-<face>/out/plate_1.gcode, which this record does not keep):
    uv run python research/verification/2026-11-13-color-slicing/crosscheck_task5.py OUT

Prints one row per G-code and writes raw/crosscheck-task5.json. The bodies are the four
owner plans' AMS STLs in artifacts/colored-runs/ (git-ignored), read as the gate reads them
(STL parsed back, merged exactly), in shell order from palette.json; face down is
tdmg.orca_input.turn_over. The setup is the pinned profiles' (plate, filament flow,
elefant_foot_compensation) and rule acceptance.dimension.tolerance.

Research code: not part of the package. The record's per-tool and total volumes are
rounded to 3 decimals, so "equal" means equal at that rounding.
"""

from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import trimesh

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "src"))

from tdmg import slicer  # noqa: E402
from tdmg.checks import merge_exact  # noqa: E402
from tdmg.color_gcode import (  # noqa: E402
    COLOR_CHANGES,
    COLOR_FILAMENT,
    COLOR_TIME,
    COLOR_WASTE,
    FILAMENTS_USED,
    GATED_CHECK_IDS,
    TOOL_PLACEMENT,
    color_slice_checks,
    per_tool_id,
)
from tdmg.orca_input import turn_over  # noqa: E402
from tdmg.printed import (  # noqa: E402
    F3_SLICE_CHECK_IDS,
    Setup,
    flow_from_profile,
    plate_from_profile,
)
from tdmg.rules import load_rules  # noqa: E402
from tdmg.slicing import elephant_foot_mm  # noqa: E402
from tdmg.threemf import Shell  # noqa: E402

PLANS = ("roadie-tol30-60-drop-v3-f64", "roadie-tol30-60-keep-v4-f64",
         "oddie-60-merge-blues-v3-f64", "oddie-60-keep-merge-blues-greens-v4-f64")
RUNS = REPO / "artifacts/colored-runs"


def shells_of(plan: str) -> list[Shell]:
    pal = json.loads((RUNS / plan / "palette.json").read_text("utf-8"))
    out = []
    for s in sorted(pal["shells"], key=lambda s: s["shell"]):
        data = (RUNS / plan / f"{s['body']}.stl").read_bytes()
        m = merge_exact(trimesh.load(io.BytesIO(data), file_type="stl", process=False))
        out.append(Shell(s["body"], s["role"], s["index"], s["hex"],
                         np.asarray(m.vertices, np.float32), np.asarray(m.faces, np.int64)))
    return out


def setup_for(shells) -> Setup:
    pin = slicer.load_pin()
    orc = slicer.locate(REPO / "artifacts/tools/orcaslicer-2.5.0", pin, full_tree=False)
    machine = json.loads(Path(orc.profiles["machine"]).read_text("utf-8"))
    process = json.loads(Path(orc.profiles["process"]).read_text("utf-8"))
    filament = json.loads(Path(orc.profiles["filament"]).read_text("utf-8"))
    top = max(float(np.asarray(s.vertices, np.float32)[:, 2].max()) for s in shells)
    tolerance = float(load_rules()["acceptance.dimension.tolerance"].default)
    return Setup(plate_from_profile(machine), flow_from_profile(filament), tolerance,
                 elephant_foot_mm(process), frozenset(slicer.expected_layer_counts(top,
                                                                                    process)))


def r3(v):
    return None if v is None else round(v, 3)


def main(out: Path) -> None:
    analysis = json.loads((HERE / "raw/analysis-colours.json").read_text("utf-8"))
    rules = json.loads((HERE / "raw/rules-colours.json").read_text("utf-8"))
    rows, full = [], {}
    for plan in PLANS:
        up = shells_of(plan)
        for face, shells in (("up", up), ("down", turn_over(up))):
            stem = f"{plan}-{face}"
            run = out / "orca/colours" / stem / "out"
            gcode = (run / slicer.GCODE_NAME).read_bytes()
            stats = json.loads((run / slicer.STATS_NAME).read_bytes())
            t0 = time.time()
            checks, record = color_slice_checks(gcode, shells, setup_for(shells), stats)
            seconds = time.time() - t0
            by = {c.id: c for c in checks}
            a, ru = analysis[stem], rules[stem]
            cc = by[COLOR_CHANGES].measured
            waste, filament = by[COLOR_WASTE].measured, by[COLOR_FILAMENT].measured
            mine = {
                "start_load": cc["start_load"],
                "changes": cc["changes"], "rule_c": cc["rule_c_count"],
                "minimum": cc["info_minimum_from_start_load"],
                "statistics_changes": cc["info_statistics_filament_changes"],
                "orders": {str(lay["n"]): lay["order"] for lay in record["layers"]
                           if len(lay["order"]) > 1 or lay["order"] != [0]},
                "flush_mm3": r3(waste["flush_mm3"]),
                "prime_tower_mm3": r3(waste["prime_tower_mm3"]),
                "time_s": by[COLOR_TIME].measured["total_estimated_time_s"],
                "model_mm3": [r3(f["mm3"]) for f in filament["model_by_tool"]],
                "tower_mm3": [r3(f["mm3"]) for f in waste["prime_tower_by_tool"]],
                "flush_by_tool_mm3": [r3(f["mm3"]) for f in waste["flush_by_tool"]]}
            tools = sorted((t for t in a["per_tool"] if t != "None"), key=int)
            theirs = {
                "start_load": ru["start_tools"][0][0] if len(ru["start_tools"]) == 1 else None,
                "changes": a["real_changes"], "rule_c": ru["d4c_formula"],
                "minimum": ru["d4d_exact_minimum_from_loaded"],
                "statistics_changes": a["statistics_filament_changes"],
                "orders": a["orders_by_layer"],
                "flush_mm3": a["flush_mm3"], "prime_tower_mm3": a["prime_tower_mm3"],
                "time_s": a["time_s"]["total_estimated_time"],
                "model_mm3": [a["per_tool"][t]["model_mm3"] for t in tools],
                "tower_mm3": [a["per_tool"][t]["prime_tower_mm3"] for t in tools],
                "flush_by_tool_mm3": [a["per_tool"][t]["flush_mm3"] for t in tools]}
            differ = sorted(k for k in mine if mine[k] != theirs[k])
            statuses = {i: by[i].status for i in (*GATED_CHECK_IDS, *F3_SLICE_CHECK_IDS)}
            per_tool_f3 = {per_tool_id(c, t): by[per_tool_id(c, t)].status
                           for t in range(len(shells)) for c in F3_SLICE_CHECK_IDS}
            placement = by[TOOL_PLACEMENT].measured
            rows.append((stem, statuses, mine, differ, seconds))
            full[stem] = {"statuses": statuses, "per_tool_f3": per_tool_f3,
                          "mine": mine, "record": theirs, "differ": differ,
                          "tool_placement": placement.get("tools") if placement else None,
                          "tool_placement_note": by[TOOL_PLACEMENT].note,
                          "filaments_used_note": by[FILAMENTS_USED].note,
                          "f3_notes": {i: by[i].note for i in F3_SLICE_CHECK_IDS},
                          "seconds": round(seconds, 1)}
            print(f"{stem}: " + " ".join(f"{k.split('.')[-1]}={v}" for k, v in
                                          statuses.items())
                  + f" | changes {mine['changes']} rule_c {mine['rule_c']} min "
                  f"{mine['minimum']} start T{mine['start_load']} flush {mine['flush_mm3']} "
                  f"tower {mine['prime_tower_mm3']} time {mine['time_s']} | differs from the "
                  f"record: {differ or 'nothing'} | {seconds:.0f} s")
            for t, d in (placement or {}).get("tools", {}).items():
                print(f"    T{t}: layers {d['layers'][0]}-{d['layers'][-1]}, largest outside "
                      f"its body {d['max_outside_mm']:.4f} mm (allowance "
                      f"{d['at_allowance_mm']:g}, layer {d['worst_layer']}); per-tool F3 "
                      + ", ".join(f"{c.split('.')[1]} {per_tool_f3[per_tool_id(c, int(t))]}"
                                  for c in F3_SLICE_CHECK_IDS))
    (HERE / "raw/crosscheck-task5.json").write_text(json.dumps(full, indent=1),
                                                    encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

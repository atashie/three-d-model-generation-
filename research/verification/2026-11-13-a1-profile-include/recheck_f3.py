"""Re-run the F3 checks of the current tdmg.printed on the kept slice5c G-codes.

    uv run python research/verification/2026-11-13-a1-profile-include/recheck_f3.py

For Roadie and Oddie: f3_checks on artifacts/slice-runs/<sel>-60x3-slice5c/plate_1.gcode
with the model and profiles that slice used, compared with the measured values in that
run's slice.json. Shows whether a reader change since that run alters any F3 result.
"""
import json
from pathlib import Path

from tdmg.printed import Setup, f3_checks, plate_from_profile
from tdmg.rules import load_rules
from tdmg.slicing import allowed_layer_counts, elephant_foot_mm, flow_from_profile

PROFILES = Path("artifacts/tools/orcaslicer-2.5.0/profiles-flat")
machine, process, filament = (json.loads((PROFILES / name).read_text(encoding="utf-8"))
                              for name in ("machine.json", "process.json", "filament.json"))
tolerance = float(load_rules()["acceptance.dimension.tolerance"].default)
for sel in ("roadie-tol30", "oddie"):
    stl = Path(f"artifacts/flat-runs/{sel}-60x3-s5/model.stl").read_bytes()
    run = Path(f"artifacts/slice-runs/{sel}-60x3-slice5c")
    setup = Setup(plate_from_profile(machine), flow_from_profile(filament), tolerance,
                  elephant_foot_mm(process), frozenset(allowed_layer_counts(stl, process)))
    checks, _ = f3_checks((run / "plate_1.gcode").read_bytes(), stl, setup)
    recorded = {c["id"]: c for c in json.loads((run / "slice.json").read_text(
        encoding="utf-8"))["checks"]}
    for c in checks:
        same = (c.status == recorded[c.id]["status"]
                and json.loads(json.dumps(c.measured)) == recorded[c.id]["measured"])
        print(f"{sel} {c.id}: {c.status}; status and measured equal to slice5c's: {same}")

"""Codex review 5, findings 1 and 2: the fixed reader (firmware conditionals, flush
position) on the owner's Task 7 G-codes, without slicing again.

Usage (from the repo root, Windows):
    uv run python research/verification/2026-11-13-color-slicing/recheck_review5.py

For each artifacts/slice-runs/color2-<plan>[-both]/slice.json written by
owner_slices_task7.py, and each face in it, runs tdmg.color_gcode.color_slice_checks on
that face's plate_1.gcode against the plan's bodies (as crosscheck_task5.py reads them)
and compares every color check's status, and the measured values of F6.color_changes,
F6.tool_placement (apart from the new "flushes" and "unknown" entries) and the
information checks, with the record. Prints one line per face and each flush's nozzle
position and how many are on the printable plate. Research code: not part of the package.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "src"))

from crosscheck_task5 import setup_for, shells_of  # noqa: E402

from tdmg.color_gcode import (  # noqa: E402
    COLOR_CHANGES,
    INFO_CHECK_IDS,
    TOOL_PLACEMENT,
    color_slice_checks,
)
from tdmg.orca_input import turn_over  # noqa: E402

PLANS = ("roadie-tol30-60-drop-v3-f64", "roadie-tol30-60-keep-v4-f64",
         "oddie-60-merge-blues-v3-f64", "oddie-60-keep-merge-blues-greens-v4-f64")
NEW = {"flushes", "unknown"}


def main() -> None:
    for plan in PLANS:
        for suffix in ("", "-both"):
            folder = REPO / "artifacts/slice-runs" / f"color2-{plan}{suffix}"
            if not (folder / "slice.json").is_file():
                continue
            record = json.loads((folder / "slice.json").read_bytes())
            up = shells_of(plan)
            for face, entry in sorted(record["faces"].items()):
                shells = up if face == "up" else turn_over(up)
                sub = folder / ("face-up" if face == "up" else "face-down")
                stats = json.loads((sub / "plate_1.statistics.json").read_bytes())
                checks, _ = color_slice_checks((sub / "plate_1.gcode").read_bytes(), shells,
                                               setup_for(shells), stats)
                old = {c["id"]: c for c in entry["checks"]}
                mine = {c.id: c for c in checks}
                differ = [i for i, c in mine.items() if i in old
                          and old[i]["status"] != c.status]
                for i in (COLOR_CHANGES, *INFO_CHECK_IDS):
                    if old[i]["measured"] != json.loads(json.dumps(mine[i].measured)):
                        differ.append(f"{i} measured")
                placed = {k: v for k, v in mine[TOOL_PLACEMENT].measured.items()
                          if k not in NEW}
                if old[TOOL_PLACEMENT]["measured"] != json.loads(json.dumps(placed)):
                    differ.append(f"{TOOL_PLACEMENT} measured")
                missing = [i for i in mine if i not in old]
                flushes = mine[TOOL_PLACEMENT].measured["flushes"]
                print(f"{folder.name} face {face}: {len(mine)} checks, statuses and values "
                      f"differ: {differ or 'none'}; not in the record: {missing or 'none'}; "
                      f"tool_placement {mine[TOOL_PLACEMENT].status}")
                print(f"    {len(flushes)} flushes at bed "
                      f"{sorted({tuple(f['at_bed_mm']) for f in flushes})}, on the plate: "
                      f"{sum(1 for f in flushes if f['on_plate'])}")


if __name__ == "__main__":
    main()

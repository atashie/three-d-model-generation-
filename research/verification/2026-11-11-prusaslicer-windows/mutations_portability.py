"""The Codex review's G-code mutations (2026-11-11, finding 1), run through portability_check.

Usage: uv run python research/verification/2026-11-11-prusaslicer-windows/mutations_portability.py SLICE_DIR...
Each SLICE_DIR is a `tdmg slice` output folder with both slicers (slice.json and
prusaslicer.portability-only.gcode.txt). The --info run is rebuilt from the record's
stdout; the expected values and tolerances come from the record. Each mutation of the
real G-code is checked in memory; nothing is written.
"""
import json
import pathlib
import sys

from tdmg.portability import (
    PRUSA_GCODE_END as END,
)
from tdmg.portability import (
    PRUSA_GCODE_NAME,
    Expected,
    PrusaRun,
    portability_check,
)


def mutations(g: bytes) -> dict[str, bytes]:
    last_z = g.rindex(b"\n;Z:")
    after_last_z = g.index(b"\n", last_z + 1) + 1
    lines = g.split(b"\n")
    markers = b"\n".join(x for x in lines if x in (b";LAYER_CHANGE",) or x.startswith(b";Z:"))
    # The last layer's extruding moves removed: G1 lines with X or Y and E dropped there.
    head, tail = g[:last_z], g[last_z:]
    no_ext = b"\n".join(x for x in tail.split(b"\n")
                        if not (x.startswith(b"G1 ") and b" E" in x
                                and (b" X" in x or b" Y" in x)))
    return {
        "original": g,
        "cut just after the last ;Z:": g[:after_last_z],
        "cut halfway through the last layer": g[:(after_last_z + len(g)) // 2],
        "only ;LAYER_CHANGE and ;Z: lines": markers + b"\n",
        # The same two with the closing line put back, so only the motion check can see them.
        "cut just after the last ;Z:, closing line added": g[:after_last_z] + END + b"\n",
        "only markers, closing line added": markers + b"\n" + END + b"\n",
        "last layer without extruding moves": head + no_ext,
        "relative extrusion (M82 -> M83)": g.replace(b"\nM82", b"\nM83", 1),
        "one layer's Z move raised by 0.2 mm": g.replace(b"\nG1 Z1.8 ", b"\nG1 Z2 ", 1),
    }


def main(dirs: list[str]) -> None:
    for d in map(pathlib.Path, dirs):
        record = json.loads((d / "slice.json").read_bytes())
        port = record["portability"]
        exp_d, tol = port["expected"], port["tolerances"]
        exp = Expected(parts=exp_d["parts"], facets=exp_d["facets"], size_mm=exp_d["size_mm"],
                       volume_mm3=exp_d["volume_mm3"], layer_counts=exp_d["layer_counts"],
                       first_layer_mm=0.2, layer_mm=0.2, size_tol_mm=tol["size_mm"],
                       volume_tol_mm3=tol["volume_mm3"])
        info = PrusaRun(0, False, 300.0, port["info"]["stdout_tail"], "")
        gcode_run = PrusaRun(0, False, 300.0, "", "")
        g = (d / PRUSA_GCODE_NAME).read_bytes()
        print(f"== {d.name} (first layer and layer height 0.2 mm, the pinned A1 profile)")
        for name, data in mutations(g).items():
            check, _ = portability_check(info, gcode_run, data, exp, None)
            note = check.note if check.status != "PASS" else ""
            print(f"   {name}: {check.status} {note[:150]}")


if __name__ == "__main__":
    main(sys.argv[1:])

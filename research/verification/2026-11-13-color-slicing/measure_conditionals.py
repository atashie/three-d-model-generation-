"""Codex review 5, findings 1 and 2: what the pinned slicer writes inside the firmware's
conditional blocks (M622 ... M623), and where the nozzle is during each FLUSH block.

Usage (from the repo root):
    uv run python research/verification/2026-11-13-color-slicing/measure_conditionals.py \
        GCODE [GCODE ...]

For each G-code, prints per context (start: before the first "; CHANGE_LAYER"; end: from
the first "; FEATURE: Custom" after it; skippable: inside "; SKIPPABLE_START" ... END;
toolchange: inside "; CP TOOLCHANGE START" ... END; layers: anywhere else) the commands
found inside M622 ... M623 (at any nesting depth): T commands, G90/G91, M82/M83, G92,
moves with E > 0 (E-only or with X/Y), M620/M621. Then, for every FLUSH block, the last
X, Y and Z commanded before FLUSH_START (None when unknown: after G28, M623, a firmware
G-command or SKIPPABLE_END), and whether any move inside it has X, Y or Z.

Research code: not part of the package. Its position tracking follows tdmg.printed's
rules for unknown positions; it does not check what it reads.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

WORD = re.compile(r"([A-Z])(-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))")
FIRMWARE = {"G392", "G380", "G39", "G39.3", "G39.4", "G29.2", "G29.4", "G2814"}


def words(code: str) -> dict[str, float]:
    out = {}
    for w in code.split()[1:]:
        m = WORD.fullmatch(w)
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


def measure(path: Path) -> dict:
    layers = end = False
    skippable = change = False
    depth = 0
    rel_xy = False
    x = y = z = None
    found = collections.defaultdict(collections.Counter)
    examples = collections.defaultdict(list)
    flushes = []
    flush = None
    for lineno, raw in enumerate(path.read_text("utf-8").splitlines(), 1):
        line = raw.strip()
        if line.startswith(";"):
            tag = line[1:].strip()
            if tag == "CHANGE_LAYER":
                layers = True
            elif tag.startswith("FEATURE:") and layers and tag.endswith("Custom"):
                end = True
            elif tag == "SKIPPABLE_START":
                skippable = True
            elif tag == "SKIPPABLE_END":
                skippable = False
                x = y = z = None
            elif tag == "CP TOOLCHANGE START":
                change = True
            elif tag == "CP TOOLCHANGE END":
                change = False
            elif tag == "FLUSH_START":
                flush = {"line": lineno, "x": x, "y": y, "z": z, "depth": depth,
                         "moves_xyz": 0}
            elif tag == "FLUSH_END":
                flushes.append(flush)
                flush = None
            continue
        code = line.split(";", 1)[0].strip()
        if not code:
            continue
        cmd = code.split()[0]
        context = ("end" if end else "skippable" if skippable else "toolchange" if change
                   else "layers" if layers else "start")
        w = words(code)
        if depth > 0:
            what = None
            if re.fullmatch(r"T\d+", cmd):
                what = cmd if cmd in ("T255", "T1000") else "T<n>"
            elif cmd in ("G90", "G91", "M82", "M83", "G92", "M620", "M621"):
                what = cmd
            elif cmd in ("G0", "G1", "G2", "G3") and w.get("E", 0) > 0:
                what = "extrusion with X/Y" if ("X" in w or "Y" in w) else "E-only extrusion"
            if what:
                found[context][what] += 1
                if len(examples[(context, what)]) < 2:
                    examples[(context, what)].append(f"{lineno}: {code}")
        if cmd == "M622":
            depth += 1
        elif cmd == "M623":
            depth -= 1
            x = y = z = None
        elif cmd == "G90":
            rel_xy = False
        elif cmd == "G91":
            rel_xy = True
        elif cmd == "G28" or cmd in FIRMWARE:
            x = y = z = None
        elif cmd in ("G0", "G1", "G2", "G3"):
            if flush is not None and ({"X", "Y", "Z"} & set(w)):
                flush["moves_xyz"] += 1
            if rel_xy:
                x = None if x is None else x + w.get("X", 0.0)
                y = None if y is None else y + w.get("Y", 0.0)
                z = None if z is None else z + w.get("Z", 0.0)
            else:
                x, y, z = w.get("X", x), w.get("Y", y), w.get("Z", z)
    positions = collections.Counter((f["x"], f["y"]) for f in flushes)
    return {"file": str(path), "inside_conditionals": {k: dict(v) for k, v in found.items()},
            "examples": {f"{k[0]} / {k[1]}": v for k, v in examples.items()},
            "flush_blocks": len(flushes),
            "flush_positions_xy": [[list(k), n] for k, n in positions.items()],
            "flush_z": sorted({f["z"] for f in flushes}, key=lambda v: (v is None, v)),
            "flush_inside_conditional": sum(1 for f in flushes if f["depth"] > 0),
            "flush_moves_with_xyz": sum(f["moves_xyz"] for f in flushes)}


if __name__ == "__main__":
    out = [measure(Path(p)) for p in sys.argv[1:]]
    print(json.dumps(out, indent=1))

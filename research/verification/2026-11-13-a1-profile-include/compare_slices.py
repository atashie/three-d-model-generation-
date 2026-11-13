"""Compare the owner's R1 slices before (slice-4, generic start G-code) and after the fix.

    uv run python research/verification/2026-11-13-a1-profile-include/compare_slices.py

Reads artifacts/slice-runs/<sel>-60x3-f64/ (2026-11-11) and <sel>-60x3-slice5c/
(2026-11-13) for sel in roadie-tol30 and oddie: slice.json and plate_1.gcode (or
plate_1.gcode.failed). Prints verdict, every check's status, layers, time, weight, the F3
numbers and the first lines of the start G-code.
"""
import json
import pathlib

RUNS = pathlib.Path("artifacts/slice-runs")
F3 = ("F3.printed_connectivity", "F3.edge_coverage", "F3.edge_overprint")
F3_KEYS = ("layers", "layers_mismatched", "max_gap_mm", "share_over_allowance", "layers_over",
           "max_excess_mm", "angle_deg")


def gcode(folder):
    for name in ("plate_1.gcode", "plate_1.gcode.failed"):
        if (folder / name).exists():
            return name, (folder / name).read_text(encoding="utf-8").splitlines()
    return None, []


def start_block(lines):
    """The lines after EXECUTABLE_BLOCK_START, up to the first ; CHANGE_LAYER."""
    i = next(n for n, line in enumerate(lines) if line.startswith("; EXECUTABLE_BLOCK_START"))
    end = next(n for n, line in enumerate(lines) if line.startswith("; CHANGE_LAYER") and n > i)
    return lines[i + 1:end]


for sel in ("roadie-tol30", "oddie"):
    old_dir, new_dir = RUNS / f"{sel}-60x3-f64", RUNS / f"{sel}-60x3-slice5c"
    old = json.loads((old_dir / "slice.json").read_text(encoding="utf-8"))
    new = json.loads((new_dir / "slice.json").read_text(encoding="utf-8"))
    print(f"=== {sel} 60x3: old {old_dir.name} ({old['algorithm']}) -> new {new_dir.name} "
          f"({new['algorithm']})")
    print(f"verdict: {old['verdict']} -> {new['verdict']}")
    print(f"certification: {old['certification']} -> {new['certification']}")
    for key in ("layer_count", "time_s", "weight_g", "volume_mm3"):
        print(f"{key}: {old['stats'][key]} -> {new['stats'][key]}")
    print(f"gcode sha256: {old['gcode']['sha256'][:16]}... -> {new['gcode']['sha256'][:16]}... "
          f"(quarantined {old['gcode']['quarantined']} -> {new['gcode']['quarantined']})")
    print(f"slice_id: {old['slice_id'][:16]}... -> {new['slice_id'][:16]}...")
    oc = {c["id"]: c for c in old["checks"]}
    nc = {c["id"]: c for c in new["checks"]}
    for cid in list(oc) + [c for c in nc if c not in oc]:
        a = oc.get(cid, {}).get("status")
        b = nc.get(cid, {}).get("status")
        print(f"  {cid}: {a} -> {b}{'   CHANGED' if a != b else ''}")
    for cid in F3:
        for label, rec in (("old", oc[cid]), ("new", nc[cid])):
            m = rec.get("measured") or {}
            shown = {k: m[k] for k in F3_KEYS if k in m}
            note = "" if rec["measured"] is not None else f" note: {rec.get('note')}"
            print(f"  {cid} {label}: {shown}{note}")
    for label, folder in (("old", old_dir), ("new", new_dir)):
        name, lines = gcode(folder)
        block = start_block(lines)
        print(f"{label} {name}: start G-code {len(block)} lines, M620 lines "
              f"{sum(line.startswith('M620') for line in block)}; first lines after the "
              "header:")
        first = [line for line in block if line.strip()][:12]
        for line in first:
            print(f"    {line}")
    print()

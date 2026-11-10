"""Addendum measurements for OrcaSlicer 2.5.0 on Windows (README section "Addendum, 2026-11-10").

Usage: uv run python research/verification/2026-11-10-orcaslicer-windows/measure_more.py \
    ORCA_EXE PROFILE_DIR WORK_DIR > research/verification/2026-11-10-orcaslicer-windows/more.txt
PROFILE_DIR holds machine.json, process.json, filament.json from flatten_profiles.py.

(a) Does --logfile write a log on an exit-0 run, with and without --debug?
(b) How many objects do the statistics list for two separate boxes in one STL?
(c) Layer counts for thicknesses that are not a whole number of 0.2 mm layers, against
    the plain formula 1 + round((t - first) / h) with first = h = 0.2 mm.
"""
import json
import pathlib
import shutil
import subprocess
import sys

import trimesh

exe, prof, work = (pathlib.Path(a).resolve() for a in sys.argv[1:4])
if work.exists() and any(work.iterdir()):  # safety: never delete existing data (added 2026-11-10)
    sys.exit(f"refusing: {work} exists and is not empty; pass a new folder")
work.mkdir(parents=True, exist_ok=True)
work.mkdir(parents=True)
process = json.loads((prof / "process.json").read_text())
first, h = float(process["initial_layer_print_height"]), float(process["layer_height"])
print(f"profile: initial_layer_print_height {first}, layer_height {h}")


def run(name, mesh, extra=()):
    d = work / name
    (d / "out").mkdir(parents=True)
    mesh.export(d / "m.stl")
    cmd = [str(exe), str(d / "m.stl"), "--load-settings",
           f"{prof / 'machine.json'};{prof / 'process.json'}",
           "--load-filaments", str(prof / "filament.json"), "--slice", "0",
           "--outputdir", str(d / "out"), "--export-statistics", "--logfile", str(d / "log.txt"),
           *extra]
    p = subprocess.run(cmd, capture_output=True, timeout=900)
    st = d / "out" / "plate_1.statistics.json"
    stats = json.loads(st.read_text()) if st.exists() else None
    log = d / "log.txt"
    return p.returncode, stats, (log.stat().st_size if log.exists() else None), log


def box(x, y, z, at=(0, 0)):
    return trimesh.creation.box((x, y, z)).apply_translation((at[0] + x / 2, at[1] + y / 2, z / 2))


print("\n(a) log file on exit-0 runs (20 mm cube)")
for label, extra in (("no --debug", ()), ("--debug 1", ("--debug", "1")),
                     ("--debug 2", ("--debug", "2")), ("--debug 3", ("--debug", "3")),
                     ("--debug 4", ("--debug", "4"))):
    rc, stats, size, log = run("log_" + label.replace(" ", "").replace("-", ""),
                               box(20, 20, 20), extra)
    tri = ""
    if size:
        lines = [ln for ln in log.read_text(errors="replace").splitlines() if "triangle" in ln]
        tri = f"; lines mentioning 'triangle': {len(lines)}"
    print(f"  {label}: returncode {rc}, log bytes {size}{tri}")

print("\n(b) two separate 10 x 10 x 3 mm boxes, 10 mm apart, in one STL")
two = trimesh.util.concatenate([box(10, 10, 3), box(10, 10, 3, at=(20, 0))])
print(f"  bodies in the STL: {len(two.split(only_watertight=False))}")
rc, stats, _, _ = run("two_boxes", two)
print(f"  returncode {rc}, objects in statistics: {len(stats['objects'])}, "
      f"names {[o['name'] for o in stats['objects']]}, "
      f"layer_count {stats['summary']['layer_count']}")

print("\n(c) layer counts against 1 + round((t - first) / h)")
print("  t_mm  (t-first)/h  formula  slicer")
for t in (3.0, 3.05, 3.1, 3.15, 1.1, 2.1, 0.3, 0.5):
    q = (t - first) / h
    rc, stats, _, _ = run(f"t{t}", box(20, 20, t))
    layers = stats["summary"]["layer_count"] if stats else None
    print(f"  {t:<5} {q:<11.6f} {1 + round(q):<8} {layers}  (returncode {rc})")

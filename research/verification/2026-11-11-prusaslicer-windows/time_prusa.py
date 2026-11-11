"""Time PrusaSlicer 2.9.7's --info and --export-gcode runs (addendum, 2026-11-11).

Usage: uv run python research/verification/2026-11-11-prusaslicer-windows/time_prusa.py \
    PRUSA_CONSOLE_EXE WORK_DIR REPEATS [MODEL.stl ...]
WORK_DIR must not exist or be empty. A 20 mm cube is generated there (trimesh's box, as in
measure_prusa.py); each model is copied there as <its folder name>.stl. Each run is the
measured command form with the explicit A1 settings, timed with time.perf_counter around
subprocess.run (wall clock, including process start). Prints one line per run and a
summary per model and action.
"""
import pathlib
import shutil
import subprocess
import sys
import time

import trimesh

exe, work = pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2]).resolve()
repeats = int(sys.argv[3])
models = [pathlib.Path(a).resolve() for a in sys.argv[4:]]
if work.exists() and any(work.iterdir()):
    sys.exit(f"refusing: {work} is not empty")
work.mkdir(parents=True, exist_ok=True)
trimesh.creation.box((20, 20, 20)).apply_translation((10, 10, 10)).export(work / "cube.stl")
for m in models:
    shutil.copy(m, work / f"{m.parent.name}.stl")
SETTINGS = ["--bed-shape", "0x0,256x0,256x256,0x256", "--max-print-height", "256",
            "--nozzle-diameter", "0.4", "--layer-height", "0.2", "--first-layer-height", "0.2",
            "--filament-diameter", "1.75"]
names = ["cube"] + [m.parent.name for m in models]
times = {}
for i in range(repeats):
    for n in names:
        for action in ("info", "gcode"):
            args = (["--info", f"{n}.stl"] if action == "info" else
                    ["--export-gcode", f"{n}.stl", "-o", f"{n}-{i}.gcode", *SETTINGS])
            t = time.perf_counter()
            p = subprocess.run([str(exe), *args], cwd=work, capture_output=True, timeout=600)
            took = time.perf_counter() - t
            times.setdefault((n, action), []).append(took)
            print(f"run {i + 1} {n} {action}: returncode {p.returncode}, {took:.2f} s")
for (n, action), ts in times.items():
    print(f"summary {n} {action}: {len(ts)} runs, min {min(ts):.2f} s, max {max(ts):.2f} s")
print(f"slowest run: {max(max(ts) for ts in times.values()):.2f} s")

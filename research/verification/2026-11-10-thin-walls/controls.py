"""Control cases for measure_coverage.py: two 10 mm squares joined by a 5 mm bridge of a
given width, extruded 3 mm, sliced with the pinned OrcaSlicer, then measured.

Usage: uv run python research/verification/2026-11-10-thin-walls/controls.py SLICER_DIR WORK_DIR
WORK_DIR must not exist or be empty.
"""
import pathlib
import subprocess
import sys

import shapely
import trimesh

from tdmg.flat import extrude
from tdmg.slicer import locate, run_slicer

slicer_dir, work = sys.argv[1], pathlib.Path(sys.argv[2]).resolve()
if work.exists() and any(work.iterdir()):
    sys.exit(f"refusing: {work} is not empty")
work.mkdir(parents=True, exist_ok=True)
sl = locate(slicer_dir)
here = pathlib.Path(__file__).resolve().parent
for w in (0.15, 0.3, 0.45, 0.6, 1.0):
    shape = shapely.union_all([shapely.box(0, 0, 10, 10), shapely.box(15, 0, 25, 10),
                               shapely.box(10, 5 - w / 2, 15, 5 + w / 2)])
    mesh = extrude([shape], 3.0)
    case = work / f"bridge_{w}"
    case.mkdir()
    stl = case / "model.stl"
    mesh.export(stl)
    (case / "run").mkdir()
    r = run_slicer([str(sl.exe)], stl, sl.profiles, case / "run", timeout=300)
    print(f"== bridge width {w} mm: slicer returncode {r.returncode}")
    out = subprocess.run([sys.executable, "-I", str(here / "measure_coverage.py"),
                          str(case / "run" / "out" / "plate_1.gcode"), str(stl)],
                         capture_output=True, text=True)
    lines = out.stdout.strip().splitlines()
    print("\n".join(lines[:2] + lines[-1:]) if lines else out.stderr[-500:])

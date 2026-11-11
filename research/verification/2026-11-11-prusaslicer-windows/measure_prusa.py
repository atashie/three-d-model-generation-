"""Measure the PrusaSlicer 2.9.7 command line on Windows: --info and --export-gcode.

Usage: uv run python research/verification/2026-11-11-prusaslicer-windows/measure_prusa.py \
    PRUSA_CONSOLE_EXE WORK_DIR [MODEL.stl ...]
WORK_DIR must not exist or be empty. Synthetic cases (20 mm cube, open cube, too-big box,
garbage, missing) are generated there. Slicing uses explicit settings only (no vendor
profile): an A1-sized bed 256 x 256 x 256 mm, 0.4 mm nozzle, 0.2 mm layers and first layer,
1.75 mm filament - the same values as the pinned OrcaSlicer A1 profiles.
"""
import pathlib
import shutil
import subprocess
import sys

import trimesh

exe, work = pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2]).resolve()
models = [pathlib.Path(a).resolve() for a in sys.argv[3:]]
if work.exists() and any(work.iterdir()):
    sys.exit(f"refusing: {work} is not empty")
work.mkdir(parents=True, exist_ok=True)
trimesh.creation.box((20, 20, 20)).export(work / "cube.stl")
o = trimesh.creation.box((20, 20, 20))
o.faces = o.faces[1:]
o.export(work / "open.stl")
trimesh.creation.box((300, 20, 5)).apply_translation((150, 10, 2.5)).export(work / "toobig.stl")
(work / "garbage.stl").write_bytes(b"not an stl")
for m in models:
    shutil.copy(m, work / f"{m.parent.name}.stl")
SETTINGS = ["--bed-shape", "0x0,256x0,256x256,0x256", "--max-print-height", "256",
            "--nozzle-diameter", "0.4", "--layer-height", "0.2", "--first-layer-height", "0.2",
            "--filament-diameter", "1.75"]
names = ["cube", "open", "toobig", "garbage", "missing"] + [m.parent.name for m in models]
for n in names:
    for action in ("info", "gcode"):
        args = (["--info", f"{n}.stl"] if action == "info"
                else ["--export-gcode", f"{n}.stl", "-o", f"{n}.gcode", *SETTINGS])
        p = subprocess.run([str(exe), *args], cwd=work, capture_output=True, text=True,
                           timeout=600)
        out = (p.stdout + p.stderr).strip().splitlines()
        line = f"{n} {action}: returncode {p.returncode}"
        if action == "info":
            keep = [x.strip() for x in out if x.split("=")[0].strip() in
                    ("size_x", "size_y", "size_z", "number_of_facets", "manifold",
                     "open_edges", "number_of_parts", "volume")]
            line += " | " + "; ".join(keep) if keep else f" | {out[-1] if out else ''}"
        else:
            g = work / f"{n}.gcode"
            if g.exists():
                text = g.read_text(errors="replace").splitlines()
                layers = sum(1 for x in text if x.startswith(";LAYER_CHANGE"))
                zs = [x for x in text if x.startswith(";Z:")]
                line += f" | gcode {g.stat().st_size} bytes, {layers} layers, last {zs[-1] if zs else None}"
            else:
                line += f" | no gcode | {out[-1] if out else ''}"
        print(line)

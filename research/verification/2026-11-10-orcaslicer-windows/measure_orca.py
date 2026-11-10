"""Measure OrcaSlicer 2.5.0 CLI behaviour on Windows: success, exit codes, outputs.

Usage: uv run python research/verification/2026-11-10-orcaslicer-windows/measure_orca.py \
    ORCA_EXE PROFILE_DIR WORK_DIR [MODEL.stl ...]
PROFILE_DIR holds machine.json, process.json, filament.json from flatten_profiles.py.
Synthetic cases (cube, open cube, too big, garbage, missing) are generated in WORK_DIR.
"""
import json, pathlib, shutil, subprocess, sys, time
import trimesh

exe, prof, work = (pathlib.Path(a).resolve() for a in sys.argv[1:4])
models = [pathlib.Path(a).resolve() for a in sys.argv[4:]]
shutil.rmtree(work, ignore_errors=True); work.mkdir(parents=True)
trimesh.creation.box((20, 20, 20)).apply_translation((10, 10, 10)).export(work / "cube.stl")
openm = trimesh.creation.box((20, 20, 20)); openm.faces = openm.faces[1:]; openm.export(work / "open.stl")
trimesh.creation.box((300, 20, 5)).apply_translation((150, 10, 2.5)).export(work / "toobig.stl")
(work / "garbage.stl").write_bytes(b"not an stl")
cases = [("cube", work / "cube.stl", []), ("open_cube", work / "open.stl", []),
         ("too_big", work / "toobig.stl", []), ("garbage", work / "garbage.stl", []),
         ("missing", work / "missing.stl", [])]
cases += [(m.parent.name, m, []) for m in models]
cases += [(f"{m.parent.name}_mtcpp1000", m, ["--mtcpp=1000"]) for m in models[:1]]
for name, stl, extra in cases:
    d = work / name; (d / "out").mkdir(parents=True)
    cmd = [str(exe), str(stl), "--load-settings", f"{prof/'machine.json'};{prof/'process.json'}",
           "--load-filaments", str(prof / "filament.json"), "--slice", "0",
           "--outputdir", str(d / "out"), "--export-statistics", "--logfile", str(d / "log.txt"), *extra]
    t = time.perf_counter(); p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    rc = p.returncode; signed = rc - 2**32 if rc >= 2**31 else rc
    files = sorted(f.name for f in (d / "out").iterdir())
    summary = {}
    st = d / "out" / "plate_1.statistics.json"
    if st.exists():
        s = json.loads(st.read_text())["summary"]
        summary = {k: s[k] for k in ("layer_count", "time", "volume", "weight")}
    err = p.stderr.strip().splitlines()[-1][-160:] if p.stderr.strip() else ""
    print(f"{name}: returncode {rc} (signed {signed}) {time.perf_counter()-t:.1f}s files {files} "
          f"{json.dumps(summary)} stderr: {err}")

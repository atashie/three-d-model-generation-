"""Run native imports separately so a DLL crash cannot hide other results."""
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
results = []


def record(command, identity, timeout):
    try:
        run = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        result = dict(**identity, exit_code=run.returncode,
                      stdout=run.stdout, stderr=run.stderr)
    except subprocess.TimeoutExpired as error:
        def decoded(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        result = dict(**identity, exit_code=None, timed_out_seconds=timeout,
                      stdout=decoded(error.stdout), stderr=decoded(error.stderr))
    results.append(result)
    (root / "optional-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(result, flush=True)


# Clear stale evidence before starting, and persist after every subprocess.
(root / "optional-results.json").write_text("[]", encoding="utf-8")
for module in ["pymeshlab", "open3d", "rembg", "onnxruntime", "bpy",
               "orca123d", "meshlib.mrmeshpy", "pymeshfix", "igl", "point_cloud_utils"]:
    record([sys.executable, "-u", "-c", f"import {module}; print('imported {module}')"],
           dict(module=module), 120)
record([sys.executable, "-u", str(root.parent / "2026-11-08-stack-smoke/opt_import_smoke.py")],
       dict(script="opt_import_smoke.py"), 180)

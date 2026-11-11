"""The open-cube and outside-bed controls through tdmg slice with PrusaSlicer configured.

Usage: uv run python research/verification/2026-11-11-prusaslicer-windows/controls_portability.py ORCA_DIR PRUSA_DIR WORK_DIR
Each case is written as a minimal flat folder (as in
research/verification/2026-11-10-thin-walls/controls_slice.py): model.stl and a flat.json
with schema, a flat_id from tdmg.flat.flat_identity, a stand-in mask hash, params, the
STL's hash, a mesh section (needed by F6.portability) and no flat checks.
"""
import hashlib
import io
import json
import pathlib
import sys
import time

import numpy as np
import trimesh

from tdmg.flat import RECORD_SCHEMA, flat_identity
from tdmg.slicing import make_slice

orca, prusa, work = sys.argv[1], sys.argv[2], pathlib.Path(sys.argv[3]).resolve()
if work.exists() and any(work.iterdir()):
    sys.exit(f"refusing: {work} is not empty")
work.mkdir(parents=True, exist_ok=True)

cube = trimesh.creation.box((20, 20, 20)).apply_translation((10, 10, 10))
open_cube = trimesh.creation.box((20, 20, 20)).apply_translation((10, 10, 10))
open_cube.faces = open_cube.faces[1:]
toobig = trimesh.creation.box((300, 20, 5)).apply_translation((150, 10, 2.5))
cases = {"cube_20": (cube, 20.0), "open_cube_20": (open_cube, 20.0),
         "outside_bed_300x20x5": (toobig, 5.0)}
for name, (mesh, thickness) in cases.items():
    flat = work / name / "flat"
    flat.mkdir(parents=True)
    stl = mesh.export(file_type="stl")
    back = trimesh.load(io.BytesIO(stl), file_type="stl", process=False)
    v = np.asarray(back.vertices, dtype=np.float64)
    tri = v[np.asarray(back.faces)]
    volume = float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6)
    (flat / "model.stl").write_bytes(stl)
    mask = hashlib.sha256(f"control {name}".encode()).hexdigest()   # a stand-in, not a mask
    params = {"thickness_mm": thickness, "control": name}
    (flat / "flat.json").write_text(json.dumps({
        "schema": RECORD_SCHEMA, "algorithm": "portability-control",
        "flat_id": flat_identity("portability-control", mask, params),
        "selection": {"selection_id": mask, "mask_pixels_sha256": mask},
        "params": params, "outputs": {"model.stl": hashlib.sha256(stl).hexdigest()},
        "mesh": {"bodies": 1, "triangles": len(back.faces), "volume_mm3": volume,
                 "extents_mm": [float(x) for x in v.max(0) - v.min(0)]},
        "checks": []}))
    t = time.perf_counter()
    rec = make_slice(flat, work / name / "slice", orca, prusaslicer_dir=prusa)
    took = time.perf_counter() - t
    c = {x["id"]: x for x in rec["checks"]}
    p = rec["portability"]
    g = p["gcode"]
    parsed = p["info"]["parsed"]
    print(f"== {name}: {took:.1f} s; OrcaSlicer exit {rec['exit']['signed']}, layers "
          f"{rec['stats'] and rec['stats']['layer_count']}, F6.layer_count "
          f"{c['F6.layer_count']['status']}")
    print(f"   F6.portability {c['F6.portability']['status']}: {c['F6.portability']['note']}")
    print(f"   --info rc {p['info']['returncode']}: "
          + (f"manifold {parsed['manifold']}, open_edges {parsed['open_edges']}, facets "
             f"{parsed['facets']}, parts {parsed['parts']}, volume {parsed['volume_mm3']}"
             if parsed else "not parsed"))
    print(f"   --export-gcode rc {g['returncode']}, file {g['file']}, layers {g['layers']}, "
          f"last Z {g['last_z_mm']}, quarantined {g['quarantined']}")
    print(f"   stdout tail: {g['stdout_tail'].strip().splitlines()[-1:]}")
    print(f"   certification: {rec['certification']}")
    print(f"   outputs: {sorted(rec['outputs'])}")

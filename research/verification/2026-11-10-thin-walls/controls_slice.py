"""The bridge controls and the review's hair cases through tdmg slice (make_slice).

Usage: uv run python research/verification/2026-11-10-thin-walls/controls_slice.py SLICER_DIR WORK_DIR
WORK_DIR must not exist or be empty. Prints each case's three F3 verdicts and key measures.

Each case is a polygon extruded 3 mm (tdmg.flat.extrude) and written as a minimal flat
folder: model.stl and a flat.json that tdmg slice accepts (schema, a flat_id computed with
tdmg.flat.flat_identity from a stated algorithm, a stand-in mask hash and the params, and
the STL's hash). It has no flat checks, because the 0.15-0.45 mm bridges are narrower
than flat's cleaning would keep; so the certification line also names the missing flat
checks, and only the F3 verdicts are of interest here.
"""
import hashlib
import json
import pathlib
import sys
import time

import shapely

from tdmg.flat import RECORD_SCHEMA, extrude, flat_identity
from tdmg.slicing import make_slice

slicer_dir, work = sys.argv[1], pathlib.Path(sys.argv[2]).resolve()
if work.exists() and any(work.iterdir()):
    sys.exit(f"refusing: {work} is not empty")
work.mkdir(parents=True, exist_ok=True)

body = shapely.box(0, 0, 20, 10)
cases = {f"bridge_{w}": shapely.union_all([shapely.box(0, 0, 10, 10),
                                          shapely.box(15, 0, 25, 10),
                                          shapely.box(10, 5 - w / 2, 15, 5 + w / 2)])
         for w in (0.15, 0.3, 0.45, 0.6, 1.0)}
cases.update({
    "hair_end_0.3x5": shapely.union_all([body, shapely.box(20, 4.85, 25, 5.15)]),
    "hair_side_0.3x3": shapely.union_all([body, shapely.box(9.85, 10, 10.15, 13)]),
    "hair_end_0.2x3": shapely.union_all([body, shapely.box(20, 4.9, 23, 5.1)]),
    "spike_tri_1.0base_x4": shapely.union_all([body, shapely.Polygon([(20, 4.5), (24, 5),
                                                                       (20, 5.5)])]),
    "rect_60x3_hair_end_0.3x4": shapely.union_all([shapely.box(0, 0, 60, 3),
                                                   shapely.box(60, 1.35, 64, 1.65)]),
})
for name, shape in cases.items():
    flat = work / name / "flat"
    flat.mkdir(parents=True)
    stl = extrude([shape], 3.0).export(file_type="stl")
    (flat / "model.stl").write_bytes(stl)
    mask = hashlib.sha256(f"control {name}".encode()).hexdigest()   # a stand-in, not a mask
    params = {"thickness_mm": 3.0, "control": name}
    (flat / "flat.json").write_text(json.dumps({
        "schema": RECORD_SCHEMA, "algorithm": "thin-wall-control",
        "flat_id": flat_identity("thin-wall-control", mask, params),
        "selection": {"selection_id": mask, "mask_pixels_sha256": mask},
        "params": params, "outputs": {"model.stl": hashlib.sha256(stl).hexdigest()},
        "checks": []}))
    t = time.perf_counter()
    rec = make_slice(flat, work / name / "slice", slicer_dir)
    took = time.perf_counter() - t
    c = {x["id"]: x for x in rec["checks"]}
    con, cov, over = (c["F3.printed_connectivity"], c["F3.edge_coverage"],
                      c["F3.edge_overprint"])
    a = rec["printed"]["alignment"] or {}
    print(f"== {name}: {took:.1f} s; slicer exit {rec['exit']['signed']}; "
          f"layers {rec['stats'] and rec['stats']['layer_count']}; "
          f"turn {a.get('angle_deg')}, tied {a.get('tied_angles_deg')}")
    print(f"   F3.printed_connectivity {con['status']}: "
          + (f"{con['measured']['layers_mismatched']} of {con['measured']['layers']} layers "
             f"differ" if con["measured"] else con["note"][:120]))
    m = cov["measured"] or {}
    print(f"   F3.edge_coverage {cov['status']}: max gap {m.get('max_gap_mm', 0):.3f} mm at "
          f"z {m.get('worst_z')} (allowance {m.get('allowance_mm')}), "
          f"{m.get('layers_over')} layer(s) over")
    m = over["measured"] or {}
    print(f"   F3.edge_overprint {over['status']}: max {m.get('max_over_mm', 0):.3f} mm at "
          f"z {m.get('worst_z')} (allowance {m.get('allowance_mm')}), "
          f"{m.get('layers_over')} layer(s) over")
    print(f"   gcode {rec['gcode']['file']}, quarantined {rec['gcode']['quarantined']}")

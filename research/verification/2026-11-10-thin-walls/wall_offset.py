"""Distance from the outer-wall centreline to the model edge at one layer.

Usage: uv run python research/verification/2026-11-10-thin-walls/wall_offset.py GCODE STL Z
Alignment: bounding-box centres, no rotation (valid for the owner's models, which
OrcaSlicer did not rotate; see measure_coverage.py for the rotation-aware version).
"""
import pathlib
import sys

import numpy as np
import shapely
import trimesh
from shapely import affinity

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from measure_coverage import extrusions, section  # noqa: E402

gcode, stl, zq = sys.argv[1], sys.argv[2], float(sys.argv[3])
layers = extrusions(gcode)
z = min(layers, key=lambda k: abs(k - zq))
segs = [s for s in layers[z] if s[5] == "Outer wall"]
cl = shapely.union_all(shapely.linestrings([[(a, b), (c, d)] for a, b, c, d, _, _ in segs]))
model = section(trimesh.load(stl, process=False), z)
mb, cb = model.bounds, cl.bounds
model = affinity.translate(model, (cb[0] + cb[2] - mb[0] - mb[2]) / 2,
                           (cb[1] + cb[3] - mb[1] - mb[3]) / 2)
pts = shapely.get_coordinates(shapely.segmentize(cl, 0.1))
d = shapely.distance(shapely.points(pts), model.boundary)
inside = shapely.contains_xy(model, pts[:, 0], pts[:, 1])
print(f"z={z} outer-wall centreline to model edge: median {np.median(d):.4f} mm, "
      f"p5 {np.percentile(d, 5):.4f}, p95 {np.percentile(d, 95):.4f}; "
      f"inside model {100 * inside.mean():.1f}%")

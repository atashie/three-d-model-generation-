"""flat-3 (float64 blur) against flat-2 (float32) on the owner's two models at 60 x 3 mm:
the STL bytes, the largest vertex move, and the slice results. Reads the git-ignored runs:
artifacts/flat-runs/<m>-60x3-s4 (flat-2) and -s5 (flat-3), artifacts/slice-runs/
<m>-60x3-printable (flat-2) and -f64 (flat-3)."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import shapely
import trimesh

ROOT = Path(sys.argv[1])
for m in ("roadie-tol30", "oddie"):
    old, new = (ROOT / "artifacts" / "flat-runs" / f"{m}-60x3-{s}" for s in ("s4", "s5"))
    a, b = ((d / "model.stl").read_bytes() for d in (old, new))
    print(f"{m}: STL sha256 flat-2 {hashlib.sha256(a).hexdigest()[:16]}, "
          f"flat-3 {hashlib.sha256(b).hexdigest()[:16]}, identical {a == b}")
    ma, mb = (trimesh.load(d / "model.stl", force="mesh") for d in (old, new))
    print(f"  facets {len(ma.faces)} -> {len(mb.faces)}; volume {ma.volume:.6f} -> "
          f"{mb.volume:.6f} mm^3; extents {np.round(ma.extents, 6).tolist()} -> "
          f"{np.round(mb.extents, 6).tolist()}")
    if ma.vertices.shape == mb.vertices.shape:
        va = ma.vertices[np.lexsort(ma.vertices.T[::-1])]
        vb = mb.vertices[np.lexsort(mb.vertices.T[::-1])]
        print(f"  largest vertex move (sorted vertices) {np.abs(va - vb).max():.3g} mm")
    # The shapes themselves: the mid-height cross-sections, compared as polygons in the
    # model's own x, y (to_2D the identity, so both sections share one frame).
    sa, sb = (shapely.union_all([shapely.Polygon(p) for p in
                                 x.section(plane_origin=[0, 0, 1.5], plane_normal=[0, 0, 1])
                                 .to_planar(to_2D=np.eye(4))[0].polygons_full])
              for x in (ma, mb))
    print(f"  mid-height section: Hausdorff {sa.hausdorff_distance(sb):.3g} mm, "
          f"symmetric difference {sa.symmetric_difference(sb).area:.3g} mm^2, "
          f"vertices {shapely.get_num_coordinates(sa)} -> {shapely.get_num_coordinates(sb)}")
    for name, d in (("flat-2", "printable"), ("flat-3", "f64")):
        rec = json.loads((ROOT / "artifacts" / "slice-runs" / f"{m}-60x3-{d}"
                          / "slice.json").read_text(encoding="utf-8"))
        checks = {c["id"]: c for c in rec["checks"]}
        cov = checks["F3.edge_coverage"]["measured"].get("max_gap_mm")
        over = checks["F3.edge_overprint"]["measured"]
        over = next((v for k, v in over.items() if k.startswith("max")), over)
        failed = [c["id"] for c in rec["checks"] if c["status"] == "FAIL"]
        print(f"  {name}: verdict {rec['verdict']}, edge_coverage {cov}, "
              f"edge_overprint {over}, FAIL checks {failed}, "
              f"portability {checks['F6.portability']['status']}")

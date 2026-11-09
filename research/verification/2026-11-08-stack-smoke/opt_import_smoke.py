import importlib, sys, numpy as np, trimesh
ok = {}
for mod in ["pymeshfix", "igl", "pymeshlab", "open3d", "onnxruntime", "rembg", "orca123d", "point_cloud_utils", "Vision"]:
    try:
        m = importlib.import_module(mod); ok[mod] = getattr(m, "__version__", "imported")
    except Exception as e:
        ok[mod] = f"IMPORT FAIL: {type(e).__name__}: {e}"[:120]
for k, v in ok.items(): print(f"{k:18s} {v}")
# functional checks
import onnxruntime as ort; print("onnxruntime providers:", ort.get_available_providers())
a = trimesh.creation.box((10,10,10)); b = trimesh.creation.box((10,10,10)); b.apply_translation((30,0,0))
two = trimesh.util.concatenate([a, b])
import pymeshfix
v, f = pymeshfix.clean_from_arrays(np.ascontiguousarray(two.vertices, dtype=np.float64), np.ascontiguousarray(two.faces, dtype=np.int32))
print("pymeshfix default on 2 disjoint cubes -> components kept:", trimesh.Trimesh(v, f).body_count)
import pymeshlab
ms = pymeshlab.MeshSet(); ms.add_mesh(pymeshlab.Mesh(two.vertices, two.faces))
t = ms.get_topological_measures(); print("pymeshlab two-manifold:", t["is_mesh_two_manifold"], "boundary_edges:", t["boundary_edges"])
import open3d as o3d
m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(two.vertices), o3d.utility.Vector3iVector(two.faces))
print("open3d watertight:", m.is_watertight())

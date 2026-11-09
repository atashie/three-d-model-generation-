"""Smoke test: image -> contours -> shapely -> extrude -> validate -> STL/3MF, on py3.13 arm64."""
import hashlib, sys, io, math
from pathlib import Path
import numpy as np, cv2, trimesh, shapely
from shapely.geometry import Polygon
from shapely.validation import make_valid
import manifold3d

OUT = Path(sys.argv[1]); OUT.mkdir(exist_ok=True)
res = {}

# 1. synthetic 400x400 px "image": ring (outer r=150, hole r=60) + tiny 3px speck
img = np.zeros((400, 400), np.uint8)
cv2.circle(img, (200, 200), 150, 255, -1); cv2.circle(img, (200, 200), 60, 0, -1)
cv2.circle(img, (20, 20), 1, 255, -1)

def image_to_polys(img, mm_per_px, min_area_mm2):
    contours, hier = cv2.findContours(img, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    hier = hier[0]; polys = []
    for i, c in enumerate(contours):
        if hier[i][3] != -1: continue                      # holes handled with their parent
        holes = [contours[j][:, 0, :] for j in range(len(contours)) if hier[j][3] == i]
        shell = c[:, 0, :]
        if len(shell) < 3: continue
        p = Polygon(shell * mm_per_px, [h * mm_per_px for h in holes if len(h) >= 3])
        p = make_valid(p).buffer(0)
        if p.area >= min_area_mm2: polys.append(p)
    return polys

mm_per_px = 50.0 / 400                                      # 400 px -> 50 mm wide
polys = image_to_polys(img, mm_per_px, min_area_mm2=1.0)
res["n_polys_after_speck_filter"] = len(polys)
ring = polys[0]
exp_area = math.pi * (150**2 - 60**2) * mm_per_px**2
res["area_mm2"] = round(ring.area, 2); res["area_expected_mm2"] = round(exp_area, 2)
res["area_rel_err"] = round(abs(ring.area - exp_area) / exp_area, 4)
res["ring_has_hole"] = len(ring.interiors) == 1

def build(height=3.0):
    m = trimesh.creation.extrude_polygon(ring.simplify(0.02), height)
    return m
m = build()
res["trimesh_watertight"] = bool(m.is_watertight); res["trimesh_winding_consistent"] = bool(m.is_winding_consistent)
res["trimesh_volume_positive"] = bool(m.volume > 0); res["volume_mm3"] = round(m.volume, 1)
res["euler_number"] = int(m.euler_number)                 # ring (genus 1) solid surface -> 0
res["bounds_mm"] = np.round(m.extents, 2).tolist()

# 2. independent check with manifold3d
mm = manifold3d.Manifold(manifold3d.Mesh(vert_properties=np.asarray(m.vertices, np.float32),
                                         tri_verts=np.asarray(m.faces, np.uint32)))
res["manifold3d_status"] = str(mm.status()); res["manifold3d_volume"] = round(mm.volume(), 1)
res["manifold3d_genus"] = mm.genus()

# 3. determinism: build twice, export binary STL, compare hashes
h = [hashlib.sha256(build().export(file_type="stl")).hexdigest() for _ in range(2)]
res["stl_bytes_identical_across_runs"] = h[0] == h[1]
(OUT / "ring.stl").write_bytes(build().export(file_type="stl"))

# 4. two-object, two-color 3MF via lib3mf; read back and check spec-level manifoldness
import lib3mf
w = lib3mf.get_wrapper(); model = w.CreateModel()
cg = model.AddColorGroup()
cols = [cg.AddColor(w.RGBAToColor(220, 30, 30, 255)), cg.AddColor(w.RGBAToColor(30, 30, 220, 255))]
base = trimesh.creation.box((60, 60, 1.0)); base.apply_translation((25, 25, 0.5))
top = build(); top.apply_translation((0, 0, 1.0))
for name, mesh, cid in [("base", base, cols[0]), ("ring", top, cols[1])]:
    o = model.AddMeshObject(); o.SetName(name)
    verts = []
    for v in mesh.vertices:
        p = lib3mf.Position(); p.Coordinates[0], p.Coordinates[1], p.Coordinates[2] = map(float, v); verts.append(p)
    tris = []
    for f in mesh.faces:
        t = lib3mf.Triangle(); t.Indices[0], t.Indices[1], t.Indices[2] = map(int, f); tris.append(t)
    o.SetGeometry(verts, tris); o.SetObjectLevelProperty(cg.GetResourceID(), cid)
    model.AddBuildItem(o, w.GetIdentityTransform())
p3 = OUT / "two_color.3mf"; model.QueryWriter("3mf").WriteToFile(str(p3))
m2 = w.CreateModel(); m2.QueryReader("3mf").ReadFromFile(str(p3))
it = m2.GetMeshObjects(); back = []
while it.MoveNext():
    o = it.GetCurrentMeshObject(); back.append((o.GetName(), o.GetTriangleCount(), o.IsManifoldAndOriented()))
res["lib3mf_readback"] = back

# 5. trimesh reads the 3MF as a scene (colors are known to be dropped)
sc = trimesh.load(str(p3)); res["trimesh_3mf_geoms"] = len(sc.geometry)

# 6. build123d parametric part (keychain tag with hole) -> STL -> trimesh check
from build123d import Box, Cylinder, Pos, export_stl
tag = Box(40, 20, 3) - Pos(-14, 0, 0) * Cylinder(2.5, 3)
export_stl(tag, str(OUT / "tag.stl"))
t = trimesh.load(str(OUT / "tag.stl"))
res["build123d_tag_watertight"] = bool(t.is_watertight)
res["build123d_tag_volume"] = round(t.volume, 1)
res["build123d_tag_volume_expected"] = round(40*20*3 - math.pi*2.5**2*3, 1)

for k, v in res.items(): print(f"{k:34s} {v}")

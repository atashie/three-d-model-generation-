import sys, uuid, hashlib, lib3mf, trimesh
w = lib3mf.get_wrapper(); model = w.CreateModel()
NS = uuid.UUID("00000000-0000-0000-0000-000000000000")
def det(name): return str(uuid.uuid5(NS, name))
mesh = trimesh.creation.box((10, 10, 10))
o = model.AddMeshObject(); o.SetName("cube")
vs = []
for v in mesh.vertices:
    p = lib3mf.Position(); p.Coordinates[0], p.Coordinates[1], p.Coordinates[2] = map(float, v); vs.append(p)
ts = []
for f in mesh.faces:
    t = lib3mf.Triangle(); t.Indices[0], t.Indices[1], t.Indices[2] = map(int, f); ts.append(t)
o.SetGeometry(vs, ts); o.SetUUID(det("object:cube"))
it = model.AddBuildItem(o, w.GetIdentityTransform()); it.SetUUID(det("item:cube"))
model.SetBuildUUID(det("build"))
model.QueryWriter("3mf").WriteToFile(sys.argv[1])

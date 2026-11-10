"""Read owner-supplied STL exports; exact-coordinate indexing only, no repair."""
import hashlib
import json
from pathlib import Path
import numpy as np
import trimesh
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SOURCE = Path.home() / "Downloads/three-d-test/makersLabModels"
results = []
canvas = Image.new("RGB", (1000, 800), "#f3f4f6")
draw = ImageDraw.Draw(canvas)
for row, name in enumerate(("oddie.stl", "roadie.stl")):
    path = SOURCE / name
    raw = trimesh.load(path, force="mesh", process=False)
    # STL stores triangle corners, not shared vertex indices. Unify only exact
    # coordinate matches to recover adjacency, without snapping or deleting faces.
    vertices, inverse = np.unique(raw.vertices, axis=0, return_inverse=True)
    mesh = trimesh.Trimesh(vertices, inverse[raw.faces], process=False)
    counts = np.bincount(mesh.edges_unique_inverse)
    links = [{} for _ in mesh.vertices]
    for a, b, c in mesh.faces:
        for v, i, j in ((a,b,c),(b,c,a),(c,a,b)):
            links[v].setdefault(int(i), []).append(int(j))
            links[v].setdefault(int(j), []).append(int(i))
    invalid = 0
    for graph in links:
        if not graph or any(len(n) != 2 for n in graph.values()):
            invalid += 1
            continue
        seen, stack = set(), [next(iter(graph))]
        while stack:
            node = stack.pop()
            if node not in seen:
                seen.add(node)
                stack.extend(graph[node])
        invalid += len(seen) != len(graph)
    bodies = mesh.split(only_watertight=False, repair=False)
    record = dict(name=name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  bytes=path.stat().st_size, triangles=len(mesh.faces), vertices=len(vertices),
                  watertight=bool(mesh.is_watertight), closed_edge_manifold=bool(np.all(counts == 2)),
                  boundary_edges=int(np.count_nonzero(counts == 1)),
                  overfull_edges=int(np.count_nonzero(counts > 2)),
                  closed_vertex_manifold=invalid == 0, invalid_vertex_links=int(invalid),
                  winding_consistent=bool(mesh.is_winding_consistent),
                  duplicate_faces=int(len(mesh.faces)-len(np.unique(np.sort(mesh.faces,axis=1),axis=0))),
                  zero_area_faces=int(np.count_nonzero(mesh.area_faces == 0)),
                  bodies=len(bodies), components=[dict(signed_volume=float(b.volume),
                      watertight=bool(b.is_watertight), winding_consistent=bool(b.is_winding_consistent),
                      triangles=len(b.faces), extents=b.extents.tolist()) for b in bodies],
                  extents=mesh.extents.tolist(), units="unspecified by STL",
                  finite=bool(np.isfinite(mesh.vertices).all()), repaired=False,
                  certification="NOT CERTIFIED: geometry inspection only",
                  generator=None, generation_seconds=None, credits=None)
    results.append(record)
    print(json.dumps(record), flush=True)
    draw.text((20,row*400+10), f"{name}: MakerLab export, no repair", fill="black")
    # STL display assumes Z up; two opposite oblique views, not an orientation claim.
    for col, yaw in enumerate((np.pi/6, np.pi*7/6)):
        rx = trimesh.transformations.rotation_matrix(-np.pi/2, [1,0,0])
        rz = trimesh.transformations.rotation_matrix(yaw, [0,0,1])
        rotation = (rx @ rz)[:3,:3]
        points = (mesh.vertices-mesh.bounds.mean(axis=0)) @ rotation.T
        scale = 330 / np.ptp(points[:,:2],axis=0).max()
        screen = points[:,:2]*[scale,-scale]+[250+col*500, row*400+215]
        normals = mesh.face_normals @ rotation.T
        shades = np.clip(0.3 + 0.7*np.abs(normals @ [0.3,0.4,0.866]),0,1)
        for face in np.argsort(points[mesh.faces,2].mean(axis=1)):
            color = tuple((np.array([90,160,210])*shades[face]).astype(np.uint8))
            draw.polygon([tuple(p) for p in screen[mesh.faces[face]]], fill=color)
(HERE / "makerlab-metrics.json").write_text(json.dumps(results,indent=2))
canvas.save(HERE / "makerlab-previews.png")

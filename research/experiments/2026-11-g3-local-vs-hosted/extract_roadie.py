"""One-off, reviewed selection: preserve the bird component, omit the frame."""
import hashlib
import json
from pathlib import Path
import numpy as np
import trimesh
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
source = Path.home() / "Downloads/three-d-test/makersLabModels/roadie.stl"
assert hashlib.sha256(source.read_bytes()).hexdigest() == "fbbd7aff54c7fa9c09365e4820a9a17bc47ef9f54433fd336a84537880b58472"
raw = trimesh.load(source, process=False)
v, inverse = np.unique(raw.vertices, axis=0, return_inverse=True)
mesh = trimesh.Trimesh(v, inverse[raw.faces], process=False)
components = trimesh.graph.connected_components(mesh.face_adjacency, nodes=np.arange(len(mesh.faces)))
assert sorted(map(len, components)) == [29164, 91626]
# Identified from the inspected export: 91,626-face interior bird and
# 29,164-face circular frame. These counts are evidence for this file only.
selection = next(c for c in components if len(c) == 91626)
bird = trimesh.Trimesh(mesh.vertices, mesh.faces[selection], process=False)
out = ROOT / "artifacts/makerlab"
out.mkdir(parents=True, exist_ok=True)
target = out / "roadie-bird-only.stl"
bird.export(target)
back = trimesh.load(target, process=False)
assert np.array_equal(back.triangles, bird.triangles)
v, inverse = np.unique(back.vertices, axis=0, return_inverse=True)
back = trimesh.Trimesh(v, inverse[back.faces], process=False)
assert back.is_watertight and back.is_winding_consistent and back.volume > 0
assert len(trimesh.graph.connected_components(back.face_adjacency,nodes=np.arange(len(back.faces)))) == 1
record = dict(source=str(source), output=str(target), triangles=len(back.faces),
              sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
              selected_triangles_unchanged=True, watertight=bool(back.is_watertight),
              winding_consistent=bool(back.is_winding_consistent), volume=float(back.volume),
              bodies=1, extents=back.extents.tolist(), units="unspecified by STL",
              operation="Removed disconnected frame; no scaling, smoothing, hole filling or new geometry",
              certification="NOT CERTIFIED: slicing, thickness and physical scale unverified")
(Path(__file__).parent / "roadie-extraction.json").write_text(json.dumps(record,indent=2))
canvas=Image.new("RGB",(900,450),"#f3f4f6")
draw=ImageDraw.Draw(canvas)
draw.text((20,10),"Roadie: bird only, original geometry retained",fill="black")
for col,yaw in enumerate((np.pi/6,np.pi*7/6)):
    rotation=(trimesh.transformations.rotation_matrix(-np.pi/2,[1,0,0]) @
              trimesh.transformations.rotation_matrix(yaw,[0,0,1]))[:3,:3]
    p=(back.vertices-back.bounds.mean(axis=0)) @ rotation.T
    scale=350/np.ptp(p[:,:2],axis=0).max()
    xy=p[:,:2]*[scale,-scale]+[225+col*450,235]
    shades=np.clip(0.3+0.7*np.abs((back.face_normals @ rotation.T) @ [0.3,0.4,0.866]),0,1)
    for f in np.argsort(p[back.faces,2].mean(axis=1)):
        draw.polygon([tuple(q) for q in xy[back.faces[f]]],fill=tuple((np.array([90,160,210])*shades[f]).astype(np.uint8)))
canvas.save(out/'roadie-bird-only.png')
print(json.dumps(record,indent=2))

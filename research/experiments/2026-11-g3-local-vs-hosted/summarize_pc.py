"""Compare serialized geometry and render two diagnostic views per input."""
import json
from pathlib import Path
import numpy as np
import trimesh
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / "artifacts/triposr-runs"
pairs = [("chair-2", "chair-3"), ("hamburger-1", "hamburger-2"),
         ("teapot-1", "teapot-2"), ("oddie-1", "oddie-2"), ("roadie-1", "roadie-2")]


def canonical(mesh):
    order = np.lexsort(mesh.vertices.T[::-1])
    inverse = np.empty(len(order), dtype=int)
    inverse[order] = np.arange(len(order))
    faces = inverse[mesh.faces]
    # Rotate triangle indices without reversing winding, then sort triangles.
    starts = faces.argmin(axis=1)
    faces = np.take_along_axis(faces, (starts[:, None] + np.arange(3)) % 3, axis=1)
    faces = faces[np.lexsort(faces.T[::-1])]
    return mesh.vertices[order], faces


summary = []
canvas = Image.new("RGB", (1000, 5 * 380), "#f3f4f6")
draw = ImageDraw.Draw(canvas)
for row, (first, second) in enumerate(pairs):
    a = json.loads((RUNS / first / "mesh-metrics.json").read_text())
    b = json.loads((RUNS / second / "mesh-metrics.json").read_text())
    ma = trimesh.load(RUNS / first / "mesh.obj", force="mesh", process=False)
    mb = trimesh.load(RUNS / second / "mesh.obj", force="mesh", process=False)
    va, fa = canonical(ma)
    vb, fb = canonical(mb)
    a["repeat"] = dict(second_run=second, seconds=b["wall_to_mesh_seconds"],
                       byte_identical=a["output_sha256"] == b["output_sha256"],
                       canonical_vertices_exact=bool(np.array_equal(va, vb)),
                       canonical_faces_exact=bool(np.array_equal(fa, fb)))
    if va.shape == vb.shape:
        a["repeat"]["max_sorted_vertex_distance"] = float(np.linalg.norm(va-vb, axis=1).max())
    a["resources"] = [json.loads((RUNS / n / "resources.json").read_text()) for n in (first, second)]
    summary.append(a)
    draw.text((20, row*380+10), f'{a["input"]} | {a["triangles"]:,} triangles | raw, unrepaired', fill="black")
    # Display-only orientation from upstream to_gradio_3d_orientation.
    display = ma.copy()
    display.apply_transform(trimesh.transformations.rotation_matrix(-np.pi/2, [1,0,0]))
    display.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [0,1,0]))
    vertices = display.vertices - display.bounds.mean(axis=0)
    for col, angle in enumerate((np.pi, np.pi + np.pi/3)):
        rotation = np.array([[np.cos(angle), 0, np.sin(angle)], [0,1,0],
                             [-np.sin(angle),0,np.cos(angle)]])
        points = vertices @ rotation.T
        scale = 310 / np.ptp(points[:,:2],axis=0).max()
        projected = points[:,:2] * [scale, -scale] + [250+col*500, row*380+205]
        normals = display.face_normals @ rotation.T
        shades = 0.35 + 0.65 * np.abs(normals @ np.array([0.3,0.4,0.866]))
        colors = np.clip(ma.visual.face_colors[:,:3] * shades[:,None],0,255).astype(np.uint8)
        for f in np.argsort(points[ma.faces,2].mean(axis=1)):
            draw.polygon([tuple(p) for p in projected[ma.faces[f]]], fill=tuple(colors[f]))
(RUNS / "summary.json").write_text(json.dumps(summary,indent=2))
canvas.save(RUNS / "previews.png")
for a in summary:
    print(a["input"],round(a["wall_to_mesh_seconds"],2),a["triangles"],a["bodies"],a["repeat"])

"""The core geometry stack imports and agrees with itself on a shape with a known answer.

This is a smoke test of the environment, not of the pipeline. Phase 1 adds the real tests
listed in research/verification/2026-11-08-stack-smoke/README.md section 5.
"""

import numpy as np
import pytest
from shapely.geometry import Polygon


def test_core_imports():
    import build123d  # noqa: F401
    import cv2  # noqa: F401
    import lib3mf  # noqa: F401
    import manifold3d  # noqa: F401
    import trimesh  # noqa: F401
    import vtracer  # noqa: F401


def test_extruded_square_with_hole_is_a_valid_solid():
    import manifold3d
    import trimesh

    ring = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)], [[(5, 5), (15, 5), (15, 15), (5, 15)]])
    # Name the triangulation engine explicitly: trimesh otherwise picks the first one installed.
    mesh = trimesh.creation.extrude_polygon(ring, 3.0, engine="manifold")
    assert mesh.is_watertight and mesh.is_winding_consistent
    assert mesh.volume == pytest.approx(300 * 3.0)

    m = manifold3d.Manifold(manifold3d.Mesh(vert_properties=np.asarray(mesh.vertices, np.float32),
                                            tri_verts=np.asarray(mesh.faces, np.uint32)))
    assert m.status() == manifold3d.Error.NoError
    assert m.volume() == pytest.approx(900.0, rel=1e-6)
    assert m.genus() == 1


def test_lib3mf_accepts_a_closed_box():
    import lib3mf
    import trimesh

    box = trimesh.creation.box((10, 10, 10))
    w = lib3mf.get_wrapper()
    obj = w.CreateModel().AddMeshObject()
    verts, tris = [], []
    for v in box.vertices:
        p = lib3mf.Position()
        p.Coordinates[0], p.Coordinates[1], p.Coordinates[2] = map(float, v)
        verts.append(p)
    for f in box.faces:
        t = lib3mf.Triangle()
        t.Indices[0], t.Indices[1], t.Indices[2] = map(int, f)
        tris.append(t)
    obj.SetGeometry(verts, tris)
    assert obj.IsManifoldAndOriented()

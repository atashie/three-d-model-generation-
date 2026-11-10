import io
import json
import warnings

import numpy as np
import pytest
import trimesh
from manifold3d import Manifold

from tdmg.checks import CheckResult, merge_exact, topology_checks, verdict

F1 = {
    "F1.finite",
    "F1.no_degenerate_faces",
    "F1.no_duplicate_faces",
    "F1.edge_manifold",
    "F1.consistent_orientation",
    "F1.vertex_manifold",
    "F1.positive_volume",
}
RULES = {
    "F1.edge_manifold": "format.3mf.edge_manifold",
    "F1.consistent_orientation": "format.3mf.consistent_orientation",
    "F1.vertex_manifold": "gate.topology.vertex_manifold",
}


def raw(vertices, faces) -> trimesh.Trimesh:
    return trimesh.Trimesh(np.asarray(vertices, float), np.asarray(faces, np.int64),
                           process=False)


def cube() -> trimesh.Trimesh:
    box = trimesh.creation.box()
    return raw(box.vertices, box.faces)


def holed_box() -> trimesh.Trimesh:
    block = Manifold.cube([10.0, 10.0, 10.0])
    hole = Manifold.cylinder(12.0, 2.0, 2.0, 32).translate([5.0, 5.0, -1.0])
    out = (block - hole).to_mesh()
    return raw(np.asarray(out.vert_properties)[:, :3], np.asarray(out.tri_verts))


def statuses(mesh) -> dict[str, str]:
    results = topology_checks(mesh)
    ids = [r.id for r in results]
    assert len(ids) == len(set(ids)) and set(ids) == F1
    return {r.id: r.status for r in results}


def failing(mesh) -> set[str]:
    return {k for k, v in statuses(mesh).items() if v != "PASS"}


@pytest.mark.parametrize("make", [cube, holed_box])
def test_positive_fixtures_pass_every_f1_check(make):
    mesh = make()
    assert statuses(mesh) == {k: "PASS" for k in F1}


def test_holed_box_is_genus_one():
    # Guards the fixture: the through-hole really exists.
    block = Manifold.cube([10.0, 10.0, 10.0])
    hole = Manifold.cylinder(12.0, 2.0, 2.0, 32).translate([5.0, 5.0, -1.0])
    assert (block - hole).genus() == 1


def test_rule_ids_and_thresholds():
    by_id = {r.id: r for r in topology_checks(cube())}
    for check, rule in RULES.items():
        assert by_id[check].rule == rule
        assert by_id[check].threshold is True
    for check in F1 - RULES.keys():
        assert by_id[check].rule is None


def test_removed_face_fails_edge_manifold():
    mesh = cube()
    mesh = raw(mesh.vertices, mesh.faces[1:])
    # Removing a face leaves its 3 edges used once. That necessarily also leaves each
    # directed edge without its reverse and turns 3 vertex links into open paths.
    assert failing(mesh) == {
        "F1.edge_manifold", "F1.consistent_orientation", "F1.vertex_manifold"}
    by_id = {r.id: r for r in topology_checks(mesh)}
    assert by_id["F1.edge_manifold"].measured == {"boundary_edges": 3, "overfull_edges": 0}


def test_flipped_face_fails_only_consistent_orientation():
    mesh = cube()
    faces = mesh.faces.copy()
    faces[0] = faces[0][::-1]
    assert failing(raw(mesh.vertices, faces)) == {"F1.consistent_orientation"}


def test_two_cubes_sharing_one_vertex_fail_only_vertex_manifold():
    # The key case: edge-manifold and consistently oriented, yet pinched at one point.
    a = trimesh.creation.box()
    b = trimesh.creation.box()
    b.apply_translation([1.0, 1.0, 1.0])
    soup = raw(np.vstack([a.vertices, b.vertices]),
               np.vstack([a.faces, b.faces + len(a.vertices)]))
    mesh = merge_exact(soup)
    assert len(mesh.vertices) == 15
    assert mesh.is_watertight  # trimesh's own test does not see the pinch
    assert failing(mesh) == {"F1.vertex_manifold"}
    by_id = {r.id: r for r in topology_checks(mesh)}
    assert by_id["F1.vertex_manifold"].measured == {"bad_vertices": 1, "unused_vertices": 0}
    assert by_id["F1.positive_volume"].measured == {"body_volumes": [1.0, 1.0]}


def test_unused_vertex_is_not_a_bad_vertex_link():
    mesh = cube()
    mesh = raw(np.vstack([mesh.vertices, [[5.0, 5.0, 5.0]]]), mesh.faces)
    assert statuses(mesh) == {k: "PASS" for k in F1}
    by_id = {r.id: r for r in topology_checks(mesh)}
    assert by_id["F1.vertex_manifold"].measured == {"bad_vertices": 0, "unused_vertices": 1}


def test_two_triangle_pillow_is_caught():
    # The same triangle in both windings: closed, edge-manifold and oriented, and each
    # vertex link is a 2-cycle, which the vertex test accepts. Duplicate and volume catch it.
    mesh = raw([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2], [0, 2, 1]])
    assert failing(mesh) == {"F1.no_duplicate_faces", "F1.positive_volume"}


def test_inverted_inner_cavity_fails_positive_volume():
    # Each connected shell is judged on its own, so a correct inward-facing cavity shell
    # has negative volume and fails. Conservative; revisit when a recipe needs voids.
    outer = trimesh.creation.box(extents=[2.0, 2.0, 2.0])
    inner = trimesh.creation.box()
    mesh = raw(np.vstack([outer.vertices, inner.vertices]),
               np.vstack([outer.faces, inner.faces[:, ::-1] + len(outer.vertices)]))
    assert failing(mesh) == {"F1.positive_volume"}
    by_id = {r.id: r for r in topology_checks(mesh)}
    assert sorted(by_id["F1.positive_volume"].measured["body_volumes"]) == [-1.0, 8.0]


@pytest.mark.parametrize("scale", [1e150, 1e200])
def test_huge_coordinates_never_pass_on_infinite_volume(scale):
    mesh = cube()
    mesh = raw(mesh.vertices * scale, mesh.faces)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        results = topology_checks(mesh)
    by_id = {r.id: r for r in results}
    volume = by_id["F1.positive_volume"]
    assert volume.status == "FAIL"
    assert volume.measured == {"body_volumes": None, "nonfinite_volumes": 1}
    assert "too large" in volume.note
    json.dumps([r.as_dict() for r in results], allow_nan=False)
    # At 1e200 the cross products overflow, so zero area cannot be decided.
    expected_area = "PASS" if scale == 1e150 else "UNKNOWN"
    assert by_id["F1.no_degenerate_faces"].status == expected_area


def test_duplicated_face_fails_no_duplicate_faces():
    mesh = cube()
    mesh = raw(mesh.vertices, np.vstack([mesh.faces, mesh.faces[:1]]))
    # A repeated face puts a third face on each of its 3 edges, so the edge, orientation
    # and vertex-link checks necessarily fail too. Coordinates, areas and volume stay valid.
    assert failing(mesh) == {
        "F1.no_duplicate_faces", "F1.edge_manifold", "F1.consistent_orientation",
        "F1.vertex_manifold"}
    by_id = {r.id: r for r in topology_checks(mesh)}
    assert by_id["F1.no_duplicate_faces"].measured == {"duplicate_faces": 1}


def test_zero_area_face_fails_only_no_degenerate_faces():
    # Split the edge a-b of one face at its midpoint m, and close the gap with the
    # zero-area triangle (a, b, m). Three collinear points; the surface stays closed,
    # edge-manifold, oriented and vertex-manifold, so only the area check can see it.
    mesh = cube()
    vertices, faces = mesh.vertices.copy(), mesh.faces.tolist()
    a, b, c = faces[0]
    m = len(vertices)
    vertices = np.vstack([vertices, (vertices[a] + vertices[b]) / 2])
    faces = [[a, m, c], [m, b, c], *faces[1:], [a, b, m]]
    mesh = raw(vertices, faces)
    assert failing(mesh) == {"F1.no_degenerate_faces"}
    by_id = {r.id: r for r in topology_checks(mesh)}
    assert by_id["F1.no_degenerate_faces"].measured == {"repeated_index": 0, "zero_area": 1}


def test_repeated_index_is_degenerate():
    mesh = cube()
    faces = np.vstack([mesh.faces, [[0, 0, 1]]])
    by_id = {r.id: r for r in topology_checks(raw(mesh.vertices, faces))}
    assert by_id["F1.no_degenerate_faces"].status == "FAIL"
    assert by_id["F1.no_degenerate_faces"].measured["repeated_index"] == 1


def test_inside_out_cube_fails_only_positive_volume():
    mesh = cube()
    assert failing(raw(mesh.vertices, mesh.faces[:, ::-1])) == {"F1.positive_volume"}


def test_non_finite_coordinates_fail_finite_and_stay_json_safe():
    mesh = cube()
    vertices = mesh.vertices.copy()
    vertices[0, 0] = np.nan
    results = topology_checks(raw(vertices, mesh.faces))
    by_id = {r.id: r for r in results}
    assert by_id["F1.finite"].status == "FAIL"
    assert by_id["F1.positive_volume"].status != "PASS"
    assert by_id["F1.no_degenerate_faces"].status != "PASS"
    json.dumps([r.as_dict() for r in results], allow_nan=False)


def test_empty_mesh_fails_every_check_without_crashing():
    results = topology_checks(raw(np.zeros((0, 3)), np.zeros((0, 3))))
    assert {r.id for r in results} == F1
    assert all(r.status == "FAIL" and "no faces" in r.note for r in results)
    json.dumps([r.as_dict() for r in results], allow_nan=False)


def test_merge_exact_after_stl_round_trip():
    data = trimesh.creation.box().export(file_type="stl")
    loaded = trimesh.load(io.BytesIO(data), file_type="stl", process=False)
    assert len(loaded.vertices) == 36
    mesh = merge_exact(loaded)
    assert len(mesh.vertices) == 8 and len(mesh.faces) == 12
    assert statuses(mesh) == {k: "PASS" for k in F1}


def test_merge_exact_does_not_snap_near_coordinates():
    vertices = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1e-12, 0, 0]]
    mesh = merge_exact(raw(vertices, [[0, 1, 2], [3, 2, 1]]))
    assert len(mesh.vertices) == 4


def result(id_: str, status: str) -> CheckResult:
    return CheckResult(id=id_, status=status, measured=0, threshold=None, rule=None)


def test_verdict():
    ok = [result("a", "PASS"), result("b", "PASS")]
    assert verdict(ok, {"a", "b"}) == "PRINTABLE"
    assert verdict(ok, {"a", "b", "c"}) == "NOT CERTIFIED"
    assert verdict([result("a", "PASS"), result("b", "FAIL")], {"a", "b"}) == "NOT CERTIFIED"
    assert verdict([result("a", "PASS"), result("b", "UNKNOWN")], {"a", "b"}) == (
        "NOT CERTIFIED")
    # A failing check that is not required does not block; a duplicate id must also pass.
    assert verdict([*ok, result("x", "FAIL")], {"a", "b"}) == "PRINTABLE"
    assert verdict([*ok, result("a", "FAIL")], {"a", "b"}) == "NOT CERTIFIED"


def test_verdict_refuses_empty_required_set():
    with pytest.raises(ValueError):
        verdict([result("a", "PASS")], set())


def test_as_dict_is_strict_json():
    results = topology_checks(holed_box())
    text = json.dumps([r.as_dict() for r in results], allow_nan=False)
    back = json.loads(text)
    assert back[0].keys() == {"id", "status", "measured", "threshold", "rule", "note"}

"""The multicolor 3MF writer (tdmg.threemf) and its gate check F2.export_3mf_matches_bodies
(tdmg.color_checks.export_3mf_check).

docs/plans/2026-11-12-color-3mf.md, Decisions 1 (encoding D), 2, 3 and 4, Tasks 2 and 3.
"""

import io
import json
import zipfile

import numpy as np
import pytest
import trimesh
from lxml import etree
from test_color_checks import CASES, bodies_of, run_checks

from tdmg.checks import merge_exact
from tdmg.color_checks import _bad_directed_edges, export_3mf_check
from tdmg.flat import encode_stl
from tdmg.threemf import (
    MODEL_PART,
    NS_CORE,
    NS_M,
    OBJECT_NAME,
    Shell,
    ThreeMFError,
    color_3mf,
    f32_text,
    model_xml,
    package,
    palette_manifest,
    shell_ranges,
    write_multishell_3mf,
)

Q = f"{{{NS_CORE}}}"
M = f"{{{NS_M}}}"


def gated(mesh):
    """The mesh as the gate sees it: its STL bytes parsed back and merged exactly."""
    return merge_exact(trimesh.load(io.BytesIO(encode_stl(mesh)), file_type="stl",
                                    process=False))


def box(extents, centre):
    m = trimesh.creation.box(extents)
    m.apply_translation(centre)
    return gated(m)


def two_cubes():
    """A 20 x 20 x 2.4 base and a 10 x 10 x 0.6 inlay standing on it (touching)."""
    a = box((20, 20, 2.4), (10, 10, 1.2))
    b = box((10, 10, 0.6), (10, 10, 2.7))
    return [Shell("ams-base", "base", 0, "#f60606", a.vertices, a.faces),
            Shell("ams-color-1-f5f5f5", "inlay", 1, "#f5f5f5", b.vertices, b.faces)]


def gated_shells(case):
    """The AMS bodies of a test case as make_colored_flat builds the shells."""
    cells, bodies = bodies_of(case)
    meshes = run_checks(cells, bodies, colors=4)["meshes"]
    hexes = ["#f60606", "#f5f5f5", "#f0f10a", "#451812"]
    return [Shell(f"ams-{b.name}", "base" if b.name == "base" else "inlay", b.index,
                  hexes[b.index], meshes[b.name].vertices, meshes[b.name].faces)
            for b in bodies]


def model_of(data: bytes) -> etree._Element:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return etree.fromstring(z.read(MODEL_PART))


def repack(root) -> bytes:
    return package(etree.tostring(root, xml_declaration=True, encoding="UTF-8"))


# --- the writer ------------------------------------------------------------------------


def test_model_xml_is_well_formed_core_and_materials_only():
    shells = two_cubes()
    root = model_of(write_multishell_3mf(shells))
    assert root.tag == f"{Q}model"
    assert root.get("unit") == "millimeter"
    assert dict(root.nsmap) == {None: NS_CORE, "m": NS_M}
    namespaces = {etree.QName(e).namespace for e in root.iter()}
    assert namespaces == {NS_CORE, NS_M}
    objects = root.findall(f"{Q}resources/{Q}object")
    assert len(objects) == 1
    obj = objects[0]
    assert (obj.get("type"), obj.get("name")) == ("model", OBJECT_NAME)
    groups = root.findall(f"{Q}resources/{M}colorgroup")
    assert len(groups) == 1
    assert [c.get("color") for c in groups[0]] == ["#F60606FF", "#F5F5F5FF"]
    items = root.findall(f"{Q}build/{Q}item")
    assert [i.get("objectid") for i in items] == [obj.get("id")]
    assert "transform" not in items[0].attrib
    triangles = obj.findall(f"{Q}mesh/{Q}triangles/{Q}triangle")
    assert len(triangles) == sum(len(s.faces) for s in shells)
    p1 = [t.get("p1") for t in triangles]
    assert p1 == ["0"] * len(shells[0].faces) + ["1"] * len(shells[1].faces)
    assert {t.get("pid") for t in triangles} == {groups[0].get("id")}
    text = etree.tostring(root).decode()
    assert "UUID" not in text.upper() and "metadata" not in text


def test_vertices_are_separate_per_shell_and_triangles_offset():
    shells = two_cubes()
    root = model_of(write_multishell_3mf(shells))
    v = root.findall(f".//{Q}vertex")
    t = root.findall(f".//{Q}triangle")
    assert len(v) == len(shells[0].vertices) + len(shells[1].vertices)
    ranges = shell_ranges(shells)
    for s, r in zip(shells, ranges, strict=True):
        v0, v1 = r["vertices"]
        got = np.array([[int(e.get(k)) for k in ("v1", "v2", "v3")]
                        for e in t[r["triangles"][0]:r["triangles"][1]]])
        assert ((got >= v0) & (got < v1)).all()
        assert (got - v0 == np.asarray(s.faces)).all()


def test_repeat_runs_are_byte_identical():
    a = write_multishell_3mf(two_cubes())
    b = write_multishell_3mf([Shell(s.name, s.role, s.index, s.hex, np.array(s.vertices),
                                    np.array(s.faces)) for s in two_cubes()])
    assert a == b


def test_coordinates_round_trip_exactly_as_float32():
    values = np.array([0.0, -0.0, 0.1, 1 / 3, 2.0 ** -18, 60 - 2.0 ** -18, 255.99998,
                       1e-7, 123.456], dtype=np.float32)
    texts = f32_text(values)
    assert all(np.float32(t) == x for t, x in zip(texts, values, strict=True))
    # The writer turns -0.0 into 0 (they are the same number).
    v = np.array([[-0.0, 0.1, 1 / 3], [1, 0, 0], [0, 1, 0]], np.float32).astype(np.float64)
    s = [Shell("ams-base", "base", 0, "#000000", v, np.array([[0, 1, 2]]))]
    xs = model_of(write_multishell_3mf(s)).findall(f".//{Q}vertex")
    assert xs[0].get("x") == "0" and np.float32(xs[0].get("y")) == np.float32(0.1)
    shells = gated_shells("circle")
    root = model_of(write_multishell_3mf(shells))
    got = np.array([[np.float32(e.get(k)) for k in "xyz"] for e in root.iter(f"{Q}vertex")])
    want = np.vstack([np.asarray(s.vertices, np.float32) for s in shells])
    assert got.dtype == np.float32 and np.array_equal(got, want)


def test_zip_metadata_is_fixed():
    data = write_multishell_3mf(two_cubes())
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None
        infos = z.infolist()
    assert [i.filename for i in infos] == ["[Content_Types].xml", "_rels/.rels", MODEL_PART]
    for i in infos:
        assert i.date_time == (1980, 1, 1, 0, 0, 0)
        assert i.external_attr == 0o644 << 16
        assert i.create_system == 3
        assert i.compress_type == zipfile.ZIP_DEFLATED
        assert i.comment == b"" and i.extra == b""


def test_two_cubes_read_back_by_lib3mf():
    shells = two_cubes()
    c = export_3mf_check(write_multishell_3mf(shells), shells)
    assert c.status == "PASS", c.measured
    m = c.measured
    assert (m["unit"], m["objects"], m["build_items"], m["object_name"]) == (
        "MilliMeter", 1, 1, OBJECT_NAME)
    assert m["triangles"] == 24 and m["vertices"] == 16
    assert [r["color"] for r in m["shells"]] == ["#F60606FF", "#F5F5F5FF"]
    assert m["manifold_and_oriented"] is True and m["reader_warnings"] == []
    json.dumps(c.as_dict(), allow_nan=False)


@pytest.mark.parametrize("change, match", [
    ("empty", "no shells"),
    ("order", "base first"),
    ("hex", "hex must be"),
    ("float64", "not a float32 number"),
    ("nan", "not finite"),
    ("index", "out of range"),
    ("inlay_order", "ascending"),
])
def test_writer_refusals(change, match):
    shells = two_cubes()
    a, b = shells
    if change == "empty":
        shells = []
    elif change == "order":
        shells = [b, a]
    elif change == "hex":
        shells = [Shell(a.name, a.role, a.index, "f60606", a.vertices, a.faces), b]
    elif change == "float64":
        v = np.array(a.vertices, np.float64)
        v[0, 0] = 0.1
        shells = [Shell(a.name, a.role, a.index, a.hex, v, a.faces), b]
    elif change == "nan":
        v = np.array(a.vertices, np.float64)
        v[0, 0] = np.nan
        shells = [Shell(a.name, a.role, a.index, a.hex, v, a.faces), b]
    elif change == "index":
        f = np.array(a.faces)
        f[0, 0] = len(a.vertices)
        shells = [Shell(a.name, a.role, a.index, a.hex, a.vertices, f), b]
    elif change == "inlay_order":
        shells = [a, b, Shell("c", "inlay", 1, "#000000", b.vertices, b.faces)]
    with pytest.raises(ThreeMFError, match=match):
        write_multishell_3mf(shells)


def test_color_3mf():
    assert color_3mf("#a1b2c3") == "#A1B2C3FF"
    with pytest.raises(ThreeMFError):
        color_3mf("#a1b2c")


def test_palette_manifest():
    shells = two_cubes()
    data = write_multishell_3mf(shells)
    text = palette_manifest(shells, data, colorflat_id="c" * 64, top_area_mm2=[300.0, 100.0],
                            volume_mm3=[960.0, 60.0])
    assert text.endswith(b"}\n") and text == palette_manifest(
        shells, data, colorflat_id="c" * 64, top_area_mm2=[300.0, 100.0],
        volume_mm3=[960.0, 60.0])
    m = json.loads(text)
    import hashlib
    assert m["model_3mf_sha256"] == hashlib.sha256(data).hexdigest()
    assert m["colorflat_id"] == "c" * 64 and m["object_name"] == OBJECT_NAME
    assert [r["body"] for r in m["shells"]] == ["ams-base", "ams-color-1-f5f5f5"]
    assert [r["role"] for r in m["shells"]] == ["base", "inlay"]
    assert m["shells"][1] == {"shell": 1, "body": "ams-color-1-f5f5f5", "role": "inlay",
                              "index": 1, "hex": "#f5f5f5", "color_3mf": "#F5F5F5FF",
                              "vertices": [8, 16], "triangles": [12, 24],
                              "top_area_mm2": 100.0, "volume_mm3": 60.0}
    assert "AMS slot" in m["note"] and "slot" not in json.dumps(m["shells"])
    with pytest.raises(ThreeMFError, match="one top area"):
        palette_manifest(shells, data, colorflat_id="c", top_area_mm2=[1.0],
                         volume_mm3=[1.0, 2.0])


# --- F2.export_3mf_matches_bodies --------------------------------------------------------


@pytest.mark.parametrize("case", CASES)
def test_the_gated_bodies_pass(case):
    shells = gated_shells(case)
    assert len(shells) >= 3
    c = export_3mf_check(write_multishell_3mf(shells), shells)
    assert c.id == "F2.export_3mf_matches_bodies"
    assert c.status == "PASS", c.measured
    assert [r["name"] for r in c.measured["shells"]] == [s.name for s in shells]
    assert c.threshold["shells"] == [{"name": s.name, "color": color_3mf(s.hex), **r}
                                     for s, r in zip(shells, shell_ranges(shells),
                                                     strict=True)]


def _vertex_moved(root):
    v = root.find(f".//{Q}vertex")
    x = np.float32(v.get("x"))
    v.set("x", f32_text(np.array([np.nextafter(x, np.float32(np.inf))]))[0])


def _unit(root):
    root.set("unit", "inch")


def _name(root):
    root.find(f".//{Q}object").set("name", "other")


def _extra_object(root):
    obj = root.find(f".//{Q}object")
    extra = etree.fromstring(etree.tostring(obj))
    extra.set("id", "3")
    obj.getparent().append(extra)
    etree.SubElement(root.find(f"{Q}build"), f"{Q}item", {"objectid": "3"})


def _transform(root):
    root.find(f".//{Q}item").set("transform", "1 0 0 0 1 0 0 0 1 1 0 0")


@pytest.mark.parametrize("edit, what", [
    (_vertex_moved, "vertices_equal"), (_unit, "unit"), (_name, "object_name"),
    (_extra_object, "objects"), (_transform, "item_ok")])
def test_an_edited_3mf_fails(edit, what):
    shells = gated_shells("box")
    root = model_of(write_multishell_3mf(shells))
    edit(root)
    c = export_3mf_check(repack(root), shells)
    assert c.status == "FAIL", what
    if what == "vertices_equal":
        assert not c.measured["shells"][0]["vertices_equal"]
        assert all(r["pass"] for r in c.measured["shells"][1:])
    elif what == "unit":
        assert c.measured["unit"] == "Inch"
    elif what == "object_name":
        assert c.measured["object_name"] == "other"
    elif what == "objects":
        assert c.measured["objects"] == 2 and c.measured["build_items"] == 2
    else:
        assert c.measured["item_ok"] is False


def test_a_tiny_scale_that_lib3mf_calls_no_transform_fails():
    # Codex review 4, finding 1: lib3mf's HasObjectTransform treats a matrix this close to
    # identity as none, but other readers apply it (trimesh: x max 20.002 on a 20 mm box).
    shells = gated_shells("box")
    root = model_of(write_multishell_3mf(shells))
    root.find(f".//{Q}item").set("transform", "1.0001 0 0 0 1 0 0 0 1 0 0 0")
    c = export_3mf_check(repack(root), shells)
    assert c.status == "FAIL"
    assert c.measured["item_ok"] is False
    assert c.measured["item_transform"][0][0] == pytest.approx(1.0001)


def _with_entries(data: bytes, entries) -> bytes:
    """data's zip with (name, bytes) entries put before its own, metadata as the writer's."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        own = [(i.filename, z.read(i)) for i in z.infolist()]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, part in [*entries, *own]:
            z.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), part)
    return buf.getvalue()


@pytest.mark.parametrize("alias", ["3D/3DMODEL.MODEL", "/3D/3dmodel.model", "3D/extra.xml"])
def test_an_extra_or_aliased_package_part_fails(alias):
    # Codex review 4, finding 2: a case or leading-slash alias of the model part, holding
    # other geometry, is ignored by lib3mf but loaded by trimesh. Only the writer's three
    # parts are allowed.
    shells = gated_shells("box")
    data = write_multishell_3mf(shells)
    root = model_of(data)
    _vertex_moved(root)
    bad = _with_entries(data, [(alias, etree.tostring(root, xml_declaration=True,
                                                       encoding="UTF-8"))])
    c = export_3mf_check(bad, shells)
    assert c.status == "FAIL"
    assert alias in c.measured["package_parts"]
    assert c.threshold["package_parts"] == ["[Content_Types].xml", "_rels/.rels",
                                            MODEL_PART]


def test_the_package_parts_are_measured_on_a_pass():
    shells = gated_shells("box")
    c = export_3mf_check(write_multishell_3mf(shells), shells)
    assert c.status == "PASS"
    assert c.measured["package_parts"] == c.threshold["package_parts"]
    assert c.measured["item_transform"] == [[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]]


def test_a_missing_shell_fails():
    shells = gated_shells("box")
    c = export_3mf_check(write_multishell_3mf(shells[:-1]), shells)
    assert c.status == "FAIL"
    assert c.measured["triangles"] < c.threshold["triangles"]


def test_a_swapped_color_fails():
    shells = gated_shells("box")
    a, b = shells[1], shells[2]
    swapped = [shells[0], Shell(a.name, a.role, a.index, b.hex, a.vertices, a.faces),
               Shell(b.name, b.role, b.index, a.hex, b.vertices, b.faces), *shells[3:]]
    c = export_3mf_check(write_multishell_3mf(swapped), shells)
    assert c.status == "FAIL"
    rows = c.measured["shells"]
    assert rows[0]["pass"] and rows[1]["wrong_color_triangles"] == len(a.faces)
    assert rows[2]["wrong_color_triangles"] == len(b.faces)


def test_a_triangle_with_another_shells_color_fails():
    shells = gated_shells("box")
    root = model_of(write_multishell_3mf(shells))
    root.find(f".//{Q}triangle").set("p1", "1")      # the base's first triangle, color 1
    c = export_3mf_check(repack(root), shells)
    assert c.status == "FAIL" and c.measured["shells"][0]["wrong_color_triangles"] == 1


def test_an_open_or_flipped_shell_fails_even_when_it_matches():
    """The per-shell closed-and-oriented test does not rely on the gated mesh being right."""
    shells = two_cubes()
    f = np.array(shells[1].faces)
    f[0] = f[0, ::-1]
    flipped = [shells[0], Shell(shells[1].name, "inlay", 1, shells[1].hex,
                                shells[1].vertices, f)]
    c = export_3mf_check(write_multishell_3mf(flipped), flipped)
    assert c.status == "FAIL"
    assert c.measured["shells"][1]["vertices_equal"] and c.measured["shells"][1][
        "triangles_equal"]
    assert c.measured["shells"][1]["bad_directed_edges"] > 0
    assert c.measured["shells"][0]["bad_directed_edges"] == 0


def test_not_a_3mf_fails_with_the_read_error():
    shells = two_cubes()
    c = export_3mf_check(b"not a zip", shells)
    assert c.status == "FAIL" and "read_error" in c.measured


def test_model_xml_is_the_zipped_part():
    shells = two_cubes()
    with zipfile.ZipFile(io.BytesIO(write_multishell_3mf(shells))) as z:
        assert z.read(MODEL_PART) == model_xml(shells)


def test_a_triangle_with_p2_unlike_p1_fails():
    """A triangle whose corners have different colors is not one body's color."""
    shells = gated_shells("box")
    root = model_of(write_multishell_3mf(shells))
    t = root.find(f".//{Q}triangle")
    t.set("p2", "1")
    t.set("p3", "0")
    c = export_3mf_check(repack(root), shells)
    assert c.status == "FAIL"
    assert c.measured["shells"][0]["wrong_color_triangles"] == 1
    assert all(r["pass"] for r in c.measured["shells"][1:])


def test_two_swapped_triangles_fail():
    shells = gated_shells("box")
    root = model_of(write_multishell_3mf(shells))
    tris = root.findall(f".//{Q}triangle")
    a, b = tris[0], tris[1]
    for k in ("v1", "v2", "v3"):
        va, vb = a.get(k), b.get(k)
        a.set(k, vb)
        b.set(k, va)
    c = export_3mf_check(repack(root), shells)
    assert c.status == "FAIL"
    row = c.measured["shells"][0]
    assert row["vertices_equal"] and not row["triangles_equal"]
    assert row["bad_directed_edges"] == 0 and row["wrong_color_triangles"] == 0


def test_a_triangle_with_rotated_corners_fails():
    """Same triangle, same winding, other first corner: the order is pinned exactly."""
    shells = gated_shells("box")
    root = model_of(write_multishell_3mf(shells))
    t = root.find(f".//{Q}triangle")
    v1, v2, v3 = t.get("v1"), t.get("v2"), t.get("v3")
    t.set("v1", v2)
    t.set("v2", v3)
    t.set("v3", v1)
    c = export_3mf_check(repack(root), shells)
    assert c.status == "FAIL"
    row = c.measured["shells"][0]
    assert not row["triangles_equal"] and row["bad_directed_edges"] == 0


def test_bad_directed_edges_counts_faces_with_repeated_indices():
    tetra = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2]])
    assert _bad_directed_edges(tetra) == 0
    # (0, 0, 1) alone passes the edge pairing ((0,0) is its own reverse; (0,1) and (1,0)
    # each once), so the repeated index must be counted on its own.
    assert _bad_directed_edges(np.array([[0, 0, 1]])) > 0
    assert _bad_directed_edges(np.vstack([tetra, [[2, 2, 2]]])) > 0


def test_f32_text_never_prints_minus_zero():
    for values in ([-0.0], [-0.0, 0.0], [0.0, -0.0], [-0.0, 1.5]):
        texts = f32_text(np.array(values, np.float32))
        assert "-0" not in list(texts), values
        assert texts[0] == "0"


def _tree_model_xml(shells):
    """Reference: the same document as one lxml tree, one element per vertex and
    triangle (the writer's form before it wrote those elements as text)."""
    from tdmg.threemf import COLOR_GROUP_ID, NS_XML, OBJECT_ID
    model = etree.Element(f"{Q}model", nsmap={None: NS_CORE, "m": NS_M})
    model.set("unit", "millimeter")
    model.set(f"{{{NS_XML}}}lang", "en-US")
    res = etree.SubElement(model, f"{Q}resources")
    group = etree.SubElement(res, f"{M}colorgroup", {"id": str(COLOR_GROUP_ID)})
    for s in shells:
        etree.SubElement(group, f"{M}color", {"color": color_3mf(s.hex)})
    obj = etree.SubElement(res, f"{Q}object", {
        "id": str(OBJECT_ID), "type": "model", "name": OBJECT_NAME,
        "pid": str(COLOR_GROUP_ID), "pindex": "0"})
    mesh = etree.SubElement(obj, f"{Q}mesh")
    vertices = etree.SubElement(mesh, f"{Q}vertices")
    triangles = etree.SubElement(mesh, f"{Q}triangles")
    offset = 0
    for i, s in enumerate(shells):
        for x, y, z in f32_text(np.asarray(s.vertices, np.float32)):
            etree.SubElement(vertices, f"{Q}vertex", {"x": x, "y": y, "z": z})
        for a, b, c in (np.asarray(s.faces) + offset).tolist():
            etree.SubElement(triangles, f"{Q}triangle", {
                "v1": str(a), "v2": str(b), "v3": str(c), "pid": str(COLOR_GROUP_ID),
                "p1": str(i)})
        offset += len(s.vertices)
    etree.SubElement(etree.SubElement(model, f"{Q}build"), f"{Q}item",
                     {"objectid": str(OBJECT_ID)})
    return etree.tostring(model, xml_declaration=True, encoding="UTF-8")


@pytest.mark.parametrize("which", ["two_cubes", "circle", "checker"])
def test_model_xml_text_equals_the_lxml_tree_serialization(which):
    shells = two_cubes() if which == "two_cubes" else gated_shells(which)
    assert model_xml(shells) == _tree_model_xml(shells)

"""The OrcaSlicer-only slicing input (tdmg.orca_input): the face-down turn, the
orca-input.3mf writer, and its gate check F2.orca_input_matches_bodies
(tdmg.color_checks.orca_input_check).

docs/plans/2026-11-13-color-slicing.md, Decisions 2 and 3, Tasks 3 and 4.
"""

import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest
import trimesh
from lxml import etree
from test_threemf import M, Q, gated, gated_shells, two_cubes

from tdmg.checks import _signed_volume, topology_checks
from tdmg.color_checks import orca_input_check
from tdmg.flat import encode_stl
from tdmg.orca_input import (
    ASSEMBLY_NAME,
    ORCA_PART_NAMES,
    SETTINGS_PART,
    filament_map,
    model_settings,
    orca_model_xml,
    turn_over,
    write_orca_input,
)
from tdmg.threemf import (
    CONTENT_TYPES,
    MODEL_PART,
    PART_NAMES,
    RELS,
    Shell,
    ThreeMFError,
    color_3mf,
    f32_text,
    package,
    write_multishell_3mf,
)

CASES = ["box", "circle", "checker"]


def stacked(shells):
    return np.vstack([np.asarray(s.vertices, np.float64) for s in shells])


# --- Task 3: the face-down turn ----------------------------------------------------------


@pytest.mark.parametrize("case", CASES)
def test_turned_coordinates_are_the_exact_float32_values(case):
    shells = gated_shells(case)
    allv = stacked(shells)
    x0, x1, top = allv[:, 0].min(), allv[:, 0].max(), allv[:, 2].max()
    turned = turn_over(shells)
    for s, t in zip(shells, turned, strict=True):
        v = np.asarray(s.vertices, np.float64)
        tv = np.asarray(t.vertices)
        assert tv.dtype == np.float32
        # Task 2's construction: float64, then float32; the float64 value is a float32.
        want64 = np.column_stack([x0 + x1 - v[:, 0], v[:, 1], top - v[:, 2]])
        assert np.array_equal(want64.astype(np.float32).astype(np.float64), want64)
        assert np.array_equal(tv.astype(np.float64), want64)


@pytest.mark.parametrize("case", CASES)
def test_turned_bodies_pass_f1_as_the_gate_reads_them(case):
    for t in turn_over(gated_shells(case)):
        mesh = gated(trimesh.Trimesh(np.asarray(t.vertices, np.float64), t.faces,
                                     process=False))
        failed = [(c.id, c.measured) for c in topology_checks(mesh) if c.status != "PASS"]
        assert not failed, (t.name, failed)


@pytest.mark.parametrize("case", CASES)
def test_volumes_are_equal_and_windings_kept(case):
    shells = gated_shells(case)
    for s, t in zip(shells, turn_over(shells), strict=True):
        before = _signed_volume(np.asarray(s.vertices, np.float64), np.asarray(s.faces))
        after = _signed_volume(np.asarray(t.vertices, np.float64), np.asarray(t.faces))
        assert before > 0 and after > 0
        # The same solid; only the float64 sum's rounding differs (Task 2: ~1e-15 rel).
        assert after == pytest.approx(before, rel=1e-12, abs=0)
        assert np.array_equal(np.asarray(t.faces), np.asarray(s.faces))


@pytest.mark.parametrize("case", CASES)
def test_turning_twice_gives_the_original_exactly(case):
    shells = gated_shells(case)
    back = turn_over(turn_over(shells))
    for s, b in zip(shells, back, strict=True):
        assert (b.name, b.role, b.index, b.hex) == (s.name, s.role, s.index, s.hex)
        assert np.array_equal(np.asarray(b.vertices), np.asarray(s.vertices, np.float32))
        assert np.array_equal(np.asarray(b.faces), np.asarray(s.faces))


@pytest.mark.parametrize("case", CASES)
def test_inlays_sit_at_z0_to_the_skin_depth_and_extents_mirror(case):
    shells = gated_shells(case)
    allv = stacked(shells)
    x0, x1, top = allv[:, 0].min(), allv[:, 0].max(), allv[:, 2].max()
    turned = turn_over(shells)
    for s, t in zip(shells, turned, strict=True):
        v = np.asarray(s.vertices, np.float64)
        tv = np.asarray(t.vertices, np.float64)
        lo, hi = v.min(0), v.max(0)
        tlo, thi = tv.min(0), tv.max(0)
        assert (tlo[0], thi[0]) == (x0 + x1 - hi[0], x0 + x1 - lo[0])
        assert (tlo[1], thi[1]) == (lo[1], hi[1])
        assert np.array_equal(np.sort(tv[:, 1]), np.sort(v[:, 1]))
        # z: T - z exactly (T - float32(2.4) is 0.5999999..., not float32(0.6)).
        assert (tlo[2], thi[2]) == (top - hi[2], top - lo[2])
        if s.role == "inlay":
            assert tlo[2] == 0.0 and thi[2] == top - lo[2] and thi[2] < 1.0
        else:
            assert (tlo[2], thi[2]) == (0.0, top)
    # the whole model keeps its x bounds
    tall = stacked(turned)
    assert (tall[:, 0].min(), tall[:, 0].max()) == (x0, x1)


def test_the_two_cube_inlay_top_is_three_minus_float32_2_4():
    shells = two_cubes()   # base 0..2.4, inlay 2.4..3.0
    turned = turn_over(shells)
    inlay = np.asarray(turned[1].vertices)
    assert inlay[:, 2].min() == 0.0
    assert float(inlay[:, 2].max()) == 3.0 - float(np.float32(2.4))
    assert float(inlay[:, 2].max()) != float(np.float32(0.6))


def test_minus_zero_is_not_written():
    for s in turn_over(two_cubes()):
        v = np.asarray(s.vertices)
        assert not (np.signbit(v) & (v == 0)).any()


def _one_triangle(v):
    return [Shell("ams-base", "base", 0, "#000000", np.array(v, np.float32),
                  np.array([[0, 1, 2]]))]


def test_an_inexact_coordinate_is_refused():
    # x0 = float32(0.1) has bits down to 2^-27; 0.1 + 60 - 30 needs them at exponent 2^4,
    # where float32's last bit is 2^-19: not a float32 number.
    shells = _one_triangle([[0.1, 0, 0], [60, 0, 0], [30, 1, 1]])
    with pytest.raises(ThreeMFError, match="not exactly a float32"):
        turn_over(shells)


def test_a_model_not_standing_on_z0_is_refused():
    shells = _one_triangle([[0, 0, 0.5], [1, 0, 0.5], [0, 1, 1]])
    with pytest.raises(ThreeMFError, match="lowest z"):
        turn_over(shells)


def test_turn_over_refuses_what_the_writer_refuses():
    a, b = two_cubes()
    with pytest.raises(ThreeMFError, match="base first"):
        turn_over([b, a])


def test_the_turned_stl_parses_back_to_the_same_mesh():
    """The turned vertices are float32 numbers, so STL keeps them exactly."""
    for t in turn_over(gated_shells("circle")):
        mesh = trimesh.Trimesh(np.asarray(t.vertices, np.float64), t.faces, process=False)
        back = trimesh.load(io.BytesIO(encode_stl(mesh)), file_type="stl", process=False)
        tri = np.asarray(t.vertices, np.float64)[np.asarray(t.faces)]
        assert np.array_equal(np.asarray(back.triangles), tri)


def test_a_rounding_float64_sum_is_refused():
    from tdmg.orca_input import _exact_difference
    assert _exact_difference(np.array([3.0]), np.array([np.float32(2.4)]))[0] == (
        3.0 - float(np.float32(2.4)))
    with pytest.raises(ThreeMFError, match="rounds"):
        _exact_difference(np.array([1.0]), np.array([2.0 ** -60]))


# --- Task 4: orca-input.3mf and F2.orca_input_matches_bodies ----------------------------

REPO = Path(__file__).resolve().parents[1]
PROTOTYPE = REPO / "research/verification/2026-11-12-color-3mf"


def prototype():
    """Step 3's hand-written builders (research code, read-only), which wrote the B_msc
    files that Task 2 sliced."""
    sys.path.insert(0, str(PROTOTYPE))
    try:
        import measure_import
    finally:
        sys.path.remove(str(PROTOTYPE))
    return measure_import


def as_bodies(shells):
    """The shells in the prototype's body form: (name, float32 vertices, faces, HEX)."""
    return [(s.name, np.asarray(s.vertices, np.float32), np.asarray(s.faces),
             s.hex[1:].upper()) for s in shells]


def parts_of(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {i.filename: z.read(i) for i in z.infolist()}


def repack_orca(model: bytes, settings: bytes) -> bytes:
    return package(model, ((SETTINGS_PART, settings),))


def model_root(data: bytes):
    return etree.fromstring(parts_of(data)[MODEL_PART])


def from_root(root, data: bytes) -> bytes:
    return repack_orca(etree.tostring(root, xml_declaration=True, encoding="UTF-8"),
                       parts_of(data)[SETTINGS_PART])


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("face", ["up", "down"])
def test_the_writer_is_the_sliced_prototype_byte_for_byte(case, face):
    shells = gated_shells(case)
    if face == "down":
        shells = turn_over(shells)
    mi = prototype()
    bodies = as_bodies(shells)
    assert orca_model_xml(shells) == mi.model_xml(bodies, "B")
    assert model_settings(shells) == mi.bambu_model_settings(bodies)
    assert parts_of(write_orca_input(shells)) == {
        "[Content_Types].xml": CONTENT_TYPES, "_rels/.rels": RELS,
        MODEL_PART: mi.model_xml(bodies, "B"),
        SETTINGS_PART: mi.bambu_model_settings(bodies)}


def test_repeat_runs_are_byte_identical():
    a = write_orca_input(gated_shells("checker"))
    b = write_orca_input([Shell(s.name, s.role, s.index, s.hex,
                                np.array(s.vertices, np.float64), np.array(s.faces))
                          for s in gated_shells("checker")])
    assert a == b


def test_zip_order_and_metadata_are_fixed():
    data = write_orca_input(two_cubes())
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None
        infos = z.infolist()
    assert tuple(i.orig_filename for i in infos) == ORCA_PART_NAMES == (
        "[Content_Types].xml", "_rels/.rels", MODEL_PART, SETTINGS_PART)
    for i in infos:
        assert i.date_time == (1980, 1, 1, 0, 0, 0)
        assert i.external_attr == 0o644 << 16 and i.create_system == 3
        assert i.compress_type == zipfile.ZIP_DEFLATED
        assert i.comment == b"" and i.extra == b""


def test_the_model_is_one_components_object_of_one_mesh_per_body():
    shells = gated_shells("checker")
    n = len(shells)
    root = model_root(write_orca_input(shells))
    groups = root.findall(f"{Q}resources/{M}colorgroup")
    assert [g.get("id") for g in groups] == [str(i + 1) for i in range(n)]
    assert [[c.get("color") for c in g] for g in groups] == [[color_3mf(s.hex)]
                                                             for s in shells]
    objects = root.findall(f"{Q}resources/{Q}object")
    assert [o.get("id") for o in objects] == [str(i) for i in range(n + 1, 2 * n + 2)]
    meshes, assembly = objects[:-1], objects[-1]
    assert [o.get("name") for o in meshes] == [s.name for s in shells]
    assert [(o.get("pid"), o.get("pindex")) for o in meshes] == [(str(i + 1), "0")
                                                                 for i in range(n)]
    assert assembly.get("name") == ASSEMBLY_NAME and assembly.find(f"{Q}mesh") is None
    comps = assembly.findall(f"{Q}components/{Q}component")
    assert [dict(c.attrib) for c in comps] == [{"objectid": o.get("id")} for o in meshes]
    items = root.findall(f"{Q}build/{Q}item")
    assert [dict(i.attrib) for i in items] == [{"objectid": assembly.get("id")}]
    for o, s in zip(meshes, shells, strict=True):
        tris = o.findall(f"{Q}mesh/{Q}triangles/{Q}triangle")
        got = np.array([[int(t.get(k)) for k in ("v1", "v2", "v3")] for t in tris])
        assert np.array_equal(got, np.asarray(s.faces))
        assert all(set(t.attrib) == {"v1", "v2", "v3"} for t in tris)
    text = etree.tostring(root).decode()
    assert "UUID" not in text.upper() and "metadata" not in text


def base_two_shells():
    """The checker bodies relabelled as a plan whose base is palette index 2: the base,
    then inlays of palette indices 0, 1 and 3 (the writer and the check read only the
    labels and the meshes)."""
    s = gated_shells("checker")
    hexes = {0: "#f5f5f5", 1: "#f0f10a", 2: "#f60606", 3: "#451812"}
    return [Shell(sh.name, sh.role, idx, hexes[idx], sh.vertices, sh.faces)
            for sh, idx in zip(s, (2, 0, 1, 3), strict=True)]


def test_each_part_gets_its_shell_position_plus_one_as_extruder():
    for shells in (gated_shells("checker"), base_two_shells()):
        settings_of(shells)


def test_filament_map_names_each_filament_body_index_and_hex():
    shells = base_two_shells()
    assert filament_map(shells) == [
        {"filament": i + 1, "body": s.name, "role": s.role, "index": s.index,
         "hex": s.hex} for i, s in enumerate(shells)]
    assert [r["index"] for r in filament_map(shells)] == [2, 0, 1, 3]
    assert filament_map(shells)[0] == {"filament": 1, "body": shells[0].name,
                                       "role": "base", "index": 2, "hex": "#f60606"}


def test_a_base_of_palette_index_2_is_filament_1_and_passes():
    shells = base_two_shells()
    for face in (shells, turn_over(shells)):
        c = orca_input_check(write_orca_input(face), face)
        assert c.status == "PASS", c.measured
        assert [r["extruder"] for r in c.measured["parts"]] == [1, 2, 3, 4]
        assert [p["extruder"] for p in c.threshold["parts"]] == [1, 2, 3, 4]


def test_a_swapped_extruder_fails():
    shells = base_two_shells()
    parts = parts_of(write_orca_input(shells))
    s = parts[SETTINGS_PART]
    a, b = b'key="extruder" value="2"', b'key="extruder" value="3"'
    assert s.count(a) == 1 and s.count(b) == 1
    swapped = s.replace(a, b"@@").replace(b, a).replace(b"@@", b)
    c = orca_input_check(repack_orca(parts[MODEL_PART], swapped), shells)
    assert c.status == "FAIL"
    rows = c.measured["parts"]
    assert [r["extruder"] for r in rows] == [1, 3, 2, 4]
    assert [r["pass"] for r in rows] == [True, False, False, True]


def settings_of(shells):
    cfg = etree.fromstring(model_settings(shells))
    n = len(shells)
    (obj,) = cfg.findall("object")
    assert obj.get("id") == str(2 * n + 1)
    meta = {m.get("key"): m.get("value") for m in obj.findall("metadata")}
    assert meta == {"name": ASSEMBLY_NAME, "extruder": "1"}
    parts = obj.findall("part")
    assert [(p.get("id"), p.get("subtype")) for p in parts] == [
        (str(n + 1 + i), "normal_part") for i in range(n)]
    got = [{m.get("key"): m.get("value") for m in p.findall("metadata")} for p in parts]
    assert got == [{"name": s.name, "extruder": str(i + 1)} for i, s in enumerate(shells)]
    assert got[0]["extruder"] == "1"


def test_the_writer_takes_any_palette_indices_check_shells_takes():
    a, b = two_cubes()
    gap = [a, Shell(b.name, b.role, 2, b.hex, b.vertices, b.faces)]
    c = orca_input_check(write_orca_input(gap), gap)
    assert c.status == "PASS" and [r["extruder"] for r in c.measured["parts"]] == [1, 2]
    with pytest.raises(ThreeMFError, match="base first"):
        write_orca_input([b, a])
    with pytest.raises(ThreeMFError, match="ascending"):
        write_orca_input([a, b, Shell("c", "inlay", 1, "#000000", b.vertices, b.faces)])


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("face", ["up", "down"])
def test_the_gated_and_turned_bodies_pass(case, face):
    shells = gated_shells(case)
    if face == "down":
        shells = turn_over(shells)
    c = orca_input_check(write_orca_input(shells), shells)
    assert c.id == "F2.orca_input_matches_bodies"
    assert c.status == "PASS", c.measured
    m = c.measured
    n = len(shells)
    assert (m["unit"], m["objects"], m["mesh_objects"], m["components_objects"],
            m["color_groups"], m["build_items"]) == ("MilliMeter", n + 1, n, 1, n, 1)
    assert m["reader_warnings"] == [] and m["item_ok"] is True
    assert m["package_parts"] == list(ORCA_PART_NAMES) and m["package_files_equal"]
    assert m["settings_equal"] is True and m["components"] == n
    assert [r["name"] for r in m["parts"]] == [s.name for s in shells]
    assert [r["extruder"] for r in m["parts"]] == list(range(1, n + 1))
    assert all(r["pass"] and r["transform_identity"] and r["manifold_and_oriented"]
               and r["bad_directed_edges"] == 0 for r in m["parts"])
    assert c.threshold["parts"] == [
        {"name": s.name, "object_id": n + 1 + i, "extruder": i + 1,
         "color": color_3mf(s.hex)} for i, s in enumerate(shells)]
    json.dumps(c.as_dict(), allow_nan=False)


def test_a_turned_file_fails_against_the_face_up_bodies():
    shells = gated_shells("box")
    c = orca_input_check(write_orca_input(turn_over(shells)), shells)
    assert c.status == "FAIL"
    assert not any(r["vertices_equal"] for r in c.measured["parts"])
    assert c.measured["settings_equal"] is True   # same names and extruders


def test_a_moved_vertex_fails():
    shells = gated_shells("box")
    data = write_orca_input(shells)
    root = model_root(data)
    v = root.findall(f"{Q}resources/{Q}object")[1].find(f".//{Q}vertex")
    x = np.float32(v.get("x"))
    v.set("x", f32_text(np.array([np.nextafter(x, np.float32(np.inf))]))[0])
    c = orca_input_check(from_root(root, data), shells)
    assert c.status == "FAIL"
    rows = c.measured["parts"]
    assert not rows[1]["vertices_equal"] and rows[1]["triangles_equal"]
    assert rows[0]["pass"] and all(r["pass"] for r in rows[2:])


def test_a_missing_part_fails():
    shells = gated_shells("box")
    c = orca_input_check(write_orca_input(shells[:-1]), shells)
    assert c.status == "FAIL"
    assert c.measured["mesh_objects"] == len(shells) - 1
    assert c.measured["parts"][-1] == {"name": shells[-1].name, "missing": True,
                                       "pass": False}


def test_an_extra_part_fails():
    shells = gated_shells("box")
    c = orca_input_check(write_orca_input(shells), shells[:-1])
    assert c.status == "FAIL"
    assert c.measured["components"] == len(shells)


def test_an_extra_component_in_the_xml_fails():
    shells = gated_shells("box")
    data = write_orca_input(shells)
    root = model_root(data)
    comps = root.find(f".//{Q}components")
    etree.SubElement(comps, f"{Q}component", {"objectid": comps[0].get("objectid")})
    c = orca_input_check(from_root(root, data), shells)
    assert c.status == "FAIL"
    assert c.measured["components"] == len(shells) + 1
    assert c.measured["settings_equal"] is True


def _settings_edit(old: bytes, new: bytes):
    def edit(settings: bytes) -> bytes:
        assert settings.count(old) == 1
        return settings.replace(old, new)
    return edit


@pytest.mark.parametrize("edit, extruders", [
    # the second part (palette index 1) put on extruder 3
    (_settings_edit(b'<metadata key="extruder" value="2"/>',
                    b'<metadata key="extruder" value="3"/>'), [1, 3, 3]),
    # a comment only: same extruders, other bytes
    (_settings_edit(b"<config>", b"<config><!-- edited -->"), [1, 2, 3]),
])
def test_an_edited_model_settings_fails(edit, extruders):
    shells = gated_shells("box")
    data = write_orca_input(shells)
    parts = parts_of(data)
    bad = repack_orca(parts[MODEL_PART], edit(parts[SETTINGS_PART]))
    c = orca_input_check(bad, shells)
    assert c.status == "FAIL"
    assert c.measured["settings_equal"] is False
    assert [r["extruder"] for r in c.measured["parts"]] == extruders
    assert all(r["vertices_equal"] and r["triangles_equal"] for r in c.measured["parts"])


def test_unreadable_model_settings_fail_with_what_was_read():
    shells = gated_shells("box")
    parts = parts_of(write_orca_input(shells))
    c = orca_input_check(repack_orca(parts[MODEL_PART], b"<config"), shells)
    assert c.status == "FAIL"
    assert "settings_error" in c.measured
    assert all(r["extruder"] is None for r in c.measured["parts"])


@pytest.mark.parametrize("transform", ["1 0 0 0 1 0 0 0 1 1 0 0",
                                       "1.0001 0 0 0 1 0 0 0 1 0 0 0"])
def test_a_component_transform_fails(transform):
    shells = gated_shells("box")
    data = write_orca_input(shells)
    root = model_root(data)
    root.findall(f".//{Q}component")[2].set("transform", transform)
    c = orca_input_check(from_root(root, data), shells)
    assert c.status == "FAIL"
    rows = c.measured["parts"]
    assert rows[2]["transform_identity"] is False and not rows[2]["pass"]
    assert rows[2]["vertices_equal"]
    assert all(r["pass"] for i, r in enumerate(rows) if i != 2)


def test_a_build_item_transform_fails():
    shells = gated_shells("box")
    data = write_orca_input(shells)
    root = model_root(data)
    root.find(f".//{Q}item").set("transform", "1.0001 0 0 0 1 0 0 0 1 0 0 0")
    c = orca_input_check(from_root(root, data), shells)
    assert c.status == "FAIL" and c.measured["item_ok"] is False


def test_a_wrong_part_name_or_color_fails():
    shells = gated_shells("box")
    data = write_orca_input(shells)
    root = model_root(data)
    root.findall(f"{Q}resources/{Q}object")[0].set("name", "other")
    root.findall(f"{Q}resources/{M}colorgroup")[1][0].set("color", "#000000FF")
    c = orca_input_check(from_root(root, data), shells)
    assert c.status == "FAIL"
    rows = c.measured["parts"]
    assert rows[0]["name"] == "other" and not rows[0]["pass"]
    assert rows[1]["color"] == "#000000FF" and not rows[1]["pass"]


@pytest.mark.parametrize("alias", ["3D/3DMODEL.MODEL", "/3D/3dmodel.model",
                                   "Metadata/Model_Settings.config", "3D/extra.xml"])
def test_an_extra_or_aliased_package_part_fails(alias):
    shells = gated_shells("box")
    data = write_orca_input(shells)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        own = [(i.filename, z.read(i)) for i in z.infolist()]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, part in [(alias, own[2][1]), *own]:
            z.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), part)
    c = orca_input_check(buf.getvalue(), shells)
    assert c.status == "FAIL"
    assert alias in c.measured["package_parts"]
    assert all(r["pass"] for r in c.measured["parts"])   # the name check alone fails it


def test_a_backslash_part_name_fails():
    shells = gated_shells("box")
    data = write_orca_input(shells)
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(buf, "w") as z:
        for i in src.infolist():
            info = zipfile.ZipInfo(i.filename, (1980, 1, 1, 0, 0, 0))
            if i.filename == SETTINGS_PART:
                info.filename = info.orig_filename = "Metadata\\model_settings.config"
            z.writestr(info, src.read(i))
    c = orca_input_check(buf.getvalue(), shells)
    assert c.status == "FAIL"
    assert "Metadata\\model_settings.config" in c.measured["package_parts"]


@pytest.mark.parametrize("part", ["[Content_Types].xml", "_rels/.rels"])
def test_edited_package_files_fail(part):
    shells = gated_shells("box")
    parts = parts_of(write_orca_input(shells))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, b in parts.items():
            z.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)),
                       b.replace(b"?>", b"?><!-- edited -->", 1) if name == part else b)
    c = orca_input_check(buf.getvalue(), shells)
    assert c.status == "FAIL" and c.measured["package_files_equal"] is False


def test_an_open_or_flipped_part_fails_even_when_it_matches():
    shells = two_cubes()
    f = np.array(shells[1].faces)
    f[0] = f[0, ::-1]
    flipped = [shells[0], Shell(shells[1].name, "inlay", 1, shells[1].hex,
                                shells[1].vertices, f)]
    c = orca_input_check(write_orca_input(flipped), flipped)
    assert c.status == "FAIL"
    row = c.measured["parts"][1]
    assert row["vertices_equal"] and row["triangles_equal"]
    assert row["bad_directed_edges"] > 0 and row["manifold_and_oriented"] is False
    assert c.measured["parts"][0]["pass"]


@pytest.mark.parametrize("data", [b"not a zip", b""])
def test_not_a_3mf_fails_with_the_read_error(data):
    c = orca_input_check(data, two_cubes())
    assert c.status == "FAIL" and "read_error" in c.measured


def test_model_3mf_is_not_an_orca_input():
    shells = two_cubes()
    c = orca_input_check(write_multishell_3mf(shells), shells)
    assert c.status == "FAIL"
    assert c.measured["package_parts"] == list(PART_NAMES)

import dataclasses
import re

import pytest

import tdmg.recipes as recipes_module
from tdmg.recipes import (
    CLASSES,
    GLUE_FILE,
    RECIPES,
    USABLE,
    Articulation,
    Geometry,
    Status,
    class_of,
    class_status,
    recipe,
    resolve,
)


def test_recipe_ids_are_unique_and_ordered():
    ids = [r.id for r in RECIPES]
    assert ids == [f"R{i}" for i in range(1, len(ids) + 1)]


def test_flat_joints_imply_flat_geometry():
    # A1 is defined as in-plane, so it implies G1 (docs/PLAN.md section 3).
    for r in RECIPES:
        if r.articulation is Articulation.A1:
            assert r.geometry is Geometry.G1, r.id


def test_roadmap_order_matches_owner_decision():
    # Owner confirmed R1 -> R2 -> R3 -> R4 on 2026-11-09.
    phases = [recipe(i).roadmap_phase for i in ("R1", "R2", "R3", "R4")]
    assert phases == sorted(phases)


def test_statuses():
    # docs/plans/2026-11-16-restructure.md Task 4: R1 and R2 are in progress, the rest planned.
    assert Status.IN_PROGRESS.value == "in progress"
    assert {r.id: r.status for r in RECIPES} == {
        "R1": Status.IN_PROGRESS, "R2": Status.IN_PROGRESS, **{
            f"R{i}": Status.PLANNED for i in range(3, 9)}}


def test_status_order_is_best_first():
    # class_status takes the first of the class's statuses in this order.
    assert list(Status) == [Status.IMPLEMENTED, Status.IN_PROGRESS, Status.PLANNED,
                            Status.NOT_PLANNED]


def test_stages_and_routes():
    assert recipe("R1").stages == ("select", "flat", "slice")
    assert recipe("R2").stages == ("select", "colors", "colored_flat", "slice")
    assert [r.name for r in recipe("R1").routes] == ["single"]
    assert recipe("R1").route("single").required_files() == ("model.stl",)
    assert [r.name for r in recipe("R2").routes] == ["ams", "glue"]
    assert recipe("R2").route("ams").required_files() == ("model.3mf", "palette.json")
    with pytest.raises(KeyError, match="R1 has no route 'ams'"):
        recipe("R1").route("ams")
    for r in RECIPES:
        if r.status not in USABLE:
            assert r.stages == () and r.routes == (), r.id


def test_r1_file_name_is_what_flat_writes():
    from tdmg.flat import MODEL_STL

    assert recipe("R1").route("single").files == (MODEL_STL,)


def test_r2_ams_file_names_are_what_flat_colors_writes():
    from tdmg.colored_flat import MODEL_3MF, PALETTE_NAME

    assert recipe("R2").route("ams").files == (MODEL_3MF, PALETTE_NAME)


@pytest.mark.parametrize("index, hex_code", [(0, "#a1b2c3"), (1, "#A1B2C3"), (2, "000000"),
                                             (10, "#ffffff"), (123, "#0f0f0f")])
def test_glue_pattern_matches_body_file(index, hex_code):
    from tdmg.colored_flat import body_file

    for base in (index, index + 1):        # once as the base, once as an inlay
        name = body_file("glue", index, hex_code, base)
        assert re.fullmatch(GLUE_FILE, name, flags=re.ASCII), name
        assert not re.fullmatch(GLUE_FILE, body_file("ams", index, hex_code, base))


def _glue_record(files=("glue-base.stl", "glue-color-2-a1b2c3.stl"), outputs=None, **glue):
    rows = [{"file": f, "route": "glue"} for f in files]
    rows.insert(0, {"file": "ams-base.stl", "route": "ams"})
    if outputs is None:
        outputs = {f: "0" * 64 for f in ("ams-base.stl", *files, "model.3mf")}
    return {"glue": {"built": True, "reason": None, "report": {"pieces": []}, **glue},
            "bodies": rows, "outputs": outputs}


def test_glue_route_lists_the_plates_in_record_order():
    glue = recipe("R2").route("glue")
    assert glue.required_files(_glue_record()) == ("glue-base.stl", "glue-color-2-a1b2c3.stl")
    assert glue.required_files(_glue_record(files=("glue-base.stl",))) == ("glue-base.stl",)


def test_glue_route_needs_its_record():
    with pytest.raises(ValueError, match="needs colored.json"):
        recipe("R2").route("glue").required_files()


UNSAFE = ["glue-x/../../evil.stl", "glue-x\\..\\..\\evil.stl", "glue-..stl",
          "glue-base.stl:evil", "glue-base\0.stl", "/glue-base.stl", "C:glue-base.stl"]


@pytest.mark.parametrize("name", UNSAFE)
def test_glue_route_refuses_a_path_as_a_file_name(name):
    record = _glue_record(files=("glue-base.stl", name))
    with pytest.raises(ValueError, match="is not a bare file name"):
        recipe("R2").route("glue").required_files(record)


@pytest.mark.parametrize("name", ["glue-x.stl", "glue-color-1-abc.stl", "glue-color-01-aabbcc.stl",
                                  "glue-color-1-AABBCC.stl", "glue-color-1-aabbcc.STL",
                                  "glue-base.stl\n", "glue-color-١-aabbcc.stl", "pieces.stl"])
def test_glue_route_refuses_a_name_body_file_does_not_make(name):
    record = _glue_record(files=("glue-base.stl", name))
    with pytest.raises(ValueError, match="does not match"):
        recipe("R2").route("glue").required_files(record)


@pytest.mark.parametrize("outputs", [
    {"glue-base.stl": "0"},                                          # a plate missing
    {"glue-base.stl": "0", "glue-color-2-a1b2c3.stl": "0", "glue-color-3-000000.stl": "0"},
    {"glue-base.stl": "0", "glue-color-2-a1b2c3.stl": "0", "glue-x/../../evil.stl": "0"},
])
def test_glue_route_cross_checks_outputs(outputs):
    with pytest.raises(ValueError, match="outputs (lack|hold)"):
        recipe("R2").route("glue").required_files(_glue_record(outputs=outputs))


@pytest.mark.parametrize("key", ["Glue-color-3-000000.stl", "GLUE-COLOR-4-000000.STL",
                                 "glue-base.STL"])
def test_glue_route_matches_unlisted_output_keys_without_case(key):
    outputs = {"glue-base.stl": "0", key: "0"}
    with pytest.raises(ValueError, match="which bodies do not list"):
        recipe("R2").route("glue").required_files(
            _glue_record(files=("glue-base.stl",), outputs=outputs))


@pytest.mark.parametrize("record", [
    _glue_record(files=("glue-base.stl", "glue-color-1-ääbbcc.stl")),
    _glue_record(files=("glue-base.stl", "glüe/../x.stl")),
    _glue_record(built="是", reason="план"),
    _glue_record(files=("glue-base.stl",), outputs={"glue-base.stl": "0", "glue-ü.stl": "0"}),
])
def test_refusal_messages_are_ascii(record):
    with pytest.raises(ValueError) as e:
        recipe("R2").route("glue").required_files(record)
    assert str(e.value).isascii(), str(e.value).encode("unicode_escape")
    with pytest.raises(ValueError) as e:
        resolve("figürine", colors=False)
    assert str(e.value).isascii()
    with pytest.raises(KeyError) as k:
        recipe("R2").route("ämś")
    assert str(k.value).isascii()


def test_glue_route_refuses_repeats_and_a_missing_base():
    glue = recipe("R2").route("glue")
    with pytest.raises(ValueError, match="'glue-base.stl' more than once"):
        glue.required_files(_glue_record(files=("glue-base.stl", "glue-base.stl")))
    with pytest.raises(ValueError, match="does not list glue-base.stl"):
        glue.required_files(_glue_record(files=("glue-color-2-a1b2c3.stl",)))
    with pytest.raises(ValueError, match="lists no glue body"):
        glue.required_files(_glue_record(files=()))


def test_glue_route_says_why_when_glue_was_not_built():
    record = _glue_record(built=False, reason="the plan has a hole", report=None)
    with pytest.raises(ValueError) as e:
        recipe("R2").route("glue").required_files(record)
    assert str(e.value) == ("route 'glue': colored.json glue.built is False, not true "
                            "(glue version not built: the plan has a hole)")


def _without(record, key):
    return {k: v for k, v in record.items() if k != key}


@pytest.mark.parametrize("record, message", [
    ([], "is not a JSON object"),
    (_without(_glue_record(), "glue"), "has no glue.built"),
    ({**_glue_record(), "glue": None}, "has no glue.built"),
    (_glue_record(built=1), "glue.built is 1, not true"),
    (_glue_record(built="true"), "glue.built is 'true', not true"),
    (_glue_record(report=None), "glue.report is NoneType, not an object"),
    (_glue_record(report=[]), "glue.report is list, not an object"),
    ({**_glue_record(), "glue": {"built": True}}, "has no glue.report"),
    (_without(_glue_record(), "bodies"), "has no bodies list"),
    ({**_glue_record(), "bodies": {"file": "glue-base.stl"}}, "has no bodies list"),
    ({**_glue_record(), "bodies": ["glue-base.stl"]}, r"bodies\[0\] is not an object"),
    ({**_glue_record(), "bodies": [{"file": "glue-base.stl"}]}, r"bodies\[0\] is not an object"),
    ({**_glue_record(), "bodies": [{"route": "glue"}]}, r"bodies\[0\] has no string file"),
    ({**_glue_record(), "bodies": [{"route": "glue", "file": 3}]}, "has no string file"),
    (_without(_glue_record(), "outputs"), "has no outputs object"),
    ({**_glue_record(), "outputs": ["glue-base.stl"]}, "has no outputs object"),
])
def test_glue_route_refuses_a_malformed_record(record, message):
    with pytest.raises(ValueError, match=message):
        recipe("R2").route("glue").required_files(record)


def test_classes_name_real_recipes_once():
    ids = [i for members in CLASSES.values() for i in members]
    assert len(ids) == len(set(ids))
    for i in ids:
        recipe(i)
    assert class_of("R2") == "flat-icon" and class_of("R3") is None


def test_resolve_flat_icon():
    assert resolve("flat-icon", colors=False).id == "R1"
    assert resolve("flat-icon", colors=True).id == "R2"


@pytest.mark.parametrize("name, members", [("figurine", "R4 planned, R7 planned"),
                                           ("flexi", "R6 planned, R8 planned")])
@pytest.mark.parametrize("colors", [False, True])
def test_resolve_refuses_a_planned_class(name, members, colors):
    with pytest.raises(ValueError) as e:
        resolve(name, colors=colors)
    assert str(e.value) == (f"output class {name!r} is planned: no recipe in it is "
                            f"implemented or in progress ({members})")


@pytest.mark.parametrize("members, colors, kind", [(("R1",), True, "multicolor"),
                                                   (("R2",), False, "single-color")])
def test_resolve_refuses_a_class_without_the_requested_color(monkeypatch, members, colors,
                                                             kind):
    monkeypatch.setattr(recipes_module, "CLASSES", {"test-class": members})
    status = f"{members[0]} in progress"
    with pytest.raises(ValueError) as e:
        resolve("test-class", colors=colors)
    assert str(e.value) == (f"output class 'test-class' has no {kind} recipe that is "
                            f"implemented or in progress ({status})")


def test_resolve_picks_the_first_usable_match_in_class_order(monkeypatch):
    # R6 is planned; make it usable to show order decides between two C1 recipes.
    r6 = dataclasses.replace(recipe("R6"), status=Status.IN_PROGRESS)
    monkeypatch.setattr(recipes_module, "RECIPES",
                        tuple(r6 if r.id == "R6" else r for r in RECIPES))
    monkeypatch.setattr(recipes_module, "CLASSES", {"a": ("R6", "R1"), "b": ("R1", "R6")})
    assert resolve("a", colors=False).id == "R6"
    assert resolve("b", colors=False).id == "R1"
    assert resolve("b", colors=True).id == "R6"


def test_resolve_refuses_an_unknown_class():
    with pytest.raises(ValueError, match="unknown output class 'keychain' "
                                         r"\(known: flat-icon, figurine, flexi\)"):
        resolve("keychain", colors=False)


def test_class_status():
    assert class_status("flat-icon") is Status.IN_PROGRESS
    assert class_status("figurine") is Status.PLANNED


def test_generated_table_shows_classes_and_status():
    from gen_docs import render_recipes

    text = render_recipes()
    assert "| 1 | in progress | flat-icon |" in text
    assert "| 5 | planned | figurine |" in text
    assert "| flat-icon | R1, R2 | in progress |" in text
    assert "| flexi | R6, R8 | planned |" in text
    assert "| R1 | select, flat, slice | single | `model.stl` | - |" in text
    assert ("| R2 | select, colors, colored_flat, slice | ams | "
            "`model.3mf`, `palette.json` | - |") in text
    assert ("| glue | `glue-base.stl` and every `glue-color-<i>-<rrggbb>.stl`, as listed in "
            "`colored.json` bodies (route glue) and outputs | `colored.json` `glue.built` true, "
            "`colored.json` `glue.report` an object |") in text

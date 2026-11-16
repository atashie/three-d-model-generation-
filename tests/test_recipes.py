import pytest

from tdmg.recipes import (
    CLASSES,
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


def test_stages_and_outputs():
    assert recipe("R1").stages == ("select", "flat", "slice")
    assert recipe("R2").stages == ("select", "colors", "colored_flat", "slice")
    assert [r.name for r in recipe("R1").outputs] == ["single"]
    assert recipe("R1").route("single").required_files() == ("model.stl",)
    assert [r.name for r in recipe("R2").outputs] == ["ams", "glue"]
    assert recipe("R2").route("ams").required_files() == ("model.3mf", "palette.json")
    with pytest.raises(KeyError, match="R1 has no route 'ams'"):
        recipe("R1").route("ams")
    for r in RECIPES:
        if r.status not in USABLE:
            assert r.stages == () and r.outputs == (), r.id


def test_r2_output_names_match_what_flat_colors_writes():
    from tdmg.colored_flat import MODEL_3MF, PALETTE_NAME, body_file

    assert recipe("R2").route("ams").files == (MODEL_3MF, PALETTE_NAME)
    glue = recipe("R2").route("glue")
    rows = [{"file": body_file("glue", i, "#a1b2c3", 0), "route": "glue"} for i in (0, 2)]
    rows.append({"file": body_file("ams", 0, "#a1b2c3", 0), "route": "ams"})
    record = {"glue": {"built": True, "reason": None, "report": {"pieces": []}}, "bodies": rows}
    assert glue.required_files(record) == ("glue-base.stl", "glue-color-2-a1b2c3.stl")


@pytest.mark.parametrize("record, message", [
    ({"glue": {"built": False, "reason": "x", "report": None}, "bodies": []}, "glue.built"),
    ({"glue": {"built": True, "report": None}, "bodies": []}, "glue.report"),
    ({"bodies": []}, "glue.built"),
    ({"glue": {"built": True, "report": {}}, "bodies": []}, r"lists no glue-\*\.stl"),
    ({"glue": {"built": True, "report": {}},
      "bodies": [{"file": "pieces.stl", "route": "glue"}]}, "do not match"),
])
def test_glue_route_refuses_an_incomplete_record(record, message):
    with pytest.raises(ValueError, match=message):
        recipe("R2").route("glue").required_files(record)


def test_glue_route_needs_its_record():
    with pytest.raises(ValueError, match="needs colored.json"):
        recipe("R2").route("glue").required_files()


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
    assert "| R1 | select, flat, slice | single | `model.stl` |" in text
    assert ("| R2 | select, colors, colored_flat, slice | ams | "
            "`model.3mf`, `palette.json` |") in text
    assert "| glue | every `glue-*.stl` in `colored.json` bodies (route glue)" in text

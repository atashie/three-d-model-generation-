from tdmg.recipes import RECIPES, Articulation, Geometry, recipe


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

"""Tests for tdmg.test_strip: the clearance and skin calibration strips
(docs/plans/2026-11-14-test-strip.md, Decisions 1 to 3 and Task 1)."""

from __future__ import annotations

import dataclasses
import io
import math
from itertools import combinations

import numpy as np
import pytest
import shapely
import trimesh

import tdmg.test_strip as ts
from tdmg.checks import merge_exact, topology_checks
from tdmg.color_checks import (
    color_partition_check,
    glue_fit_check,
    glue_fit_margin,
    glue_partition_check,
)
from tdmg.color_geometry import vertex_dist
from tdmg.flat import encode_stl
from tdmg.rules import load_rules
from tdmg.test_strip import (
    OWNER_DEPTHS_MM,
    OWNER_GAPS_MM,
    THICKNESS_MM,
    StripError,
    clearance_layout,
    clearance_strip,
    min_wall_mm,
    skin_layout,
    skin_strip,
)

RULES = load_rules()
WALL = RULES["fdm.wall.min_thickness"].default
HOLE = RULES["fdm.hole.min_diameter"].default
SKIN = RULES["color.skin.depth_mm"].default


@pytest.fixture(scope="module")
def clearance():
    return clearance_strip(OWNER_GAPS_MM, rules=RULES)


@pytest.fixture(scope="module")
def skin():
    return skin_strip(OWNER_DEPTHS_MM, rules=RULES)


def stored(mesh):
    return merge_exact(trimesh.load(io.BytesIO(encode_stl(mesh)), file_type="stl",
                                    process=False))


def assert_closed(body):
    checks = topology_checks(stored(body.mesh))
    assert [(c.id, c.measured) for c in checks if c.status != "PASS"] == [], body.name
    assert {c.id for c in checks} >= {"F1.edge_manifold", "F1.vertex_manifold"}


# --- the owner's values and the layout -------------------------------------------------


def test_owner_values_are_the_plans():
    # docs/plans/2026-11-14-test-strip.md, "The owner's answers (2026-11-14)".
    assert OWNER_GAPS_MM == (0.10, 0.15, 0.20, 0.25, 0.30, 0.35)
    assert OWNER_DEPTHS_MM == (0.2, 0.4, 0.6, 0.8, 1.0)
    assert THICKNESS_MM == 3.0
    assert (ts.POCKET_SIDE_MM, ts.POCKET_SPACING_MM, ts.EDGE_MARGIN_MM) == (10.0, 5.0, 5.0)
    assert (ts.PATCH_SIDE_MM, ts.PATCH_SPACING_MM) == (12.0, 4.0)
    assert ts.POCKET_HOLES == (1, 2, 3, 4, 5, 6)
    assert ts.PATCH_HOLES == (0, 1, 2, 3, 4, 5, 0)


def test_the_hole_depth_is_inside_the_hole_rules_conditions():
    # fdm.hole.min_diameter's 2.0 mm holds for holes 2 to 6 mm deep; the strips are
    # THICKNESS_MM deep through.
    cond = RULES["fdm.hole.min_diameter"].conditions
    assert cond["hole_depth_min_mm"] <= THICKNESS_MM <= cond["hole_depth_max_mm"]


@pytest.mark.parametrize("make", [clearance_layout, skin_layout])
def test_layout_walls_and_holes_meet_the_rules(make):
    layout = make(rules=RULES)
    assert min_wall_mm(layout) >= WALL
    for centres, holes in zip(layout.hole_centres, layout.holes, strict=True):
        for (x, y), hole in zip(centres, holes, strict=True):
            # The circle of the rule's diameter at the centre lies inside the hole.
            assert shapely.distance(shapely.Point(x, y), hole.exterior) >= HOLE / 2
    # Every square is EDGE_MARGIN_MM from the strip's left, right and top edges.
    minx, _, maxx, maxy =shapely.union_all(layout.squares).bounds
    assert (minx, maxx, maxy) == (ts.EDGE_MARGIN_MM, layout.width_mm - ts.EDGE_MARGIN_MM,
                                  layout.height_mm - ts.EDGE_MARGIN_MM)


def test_a_rule_that_the_layout_cannot_meet_is_refused():
    rules = dict(RULES)
    rules["fdm.wall.min_thickness"] = RULES["fdm.wall.min_thickness"].model_copy(
        update={"default": 5.0})
    with pytest.raises(StripError, match="fdm.wall.min_thickness"):
        clearance_layout(rules=rules)


# --- the clearance strip ---------------------------------------------------------------


def test_clearance_strip_shape(clearance):
    assert clearance.gaps_mm == OWNER_GAPS_MM
    assert len(clearance.pieces) == len(clearance.glues) == 6
    assert clearance.base.name == "base"
    assert clearance.base.z_range_mm == (0.0, THICKNESS_MM)
    for piece in clearance.pieces:
        assert piece.z_range_mm == (0.0, SKIN)
        assert len(piece.parts) == 1


def test_each_piece_has_its_own_gap_to_its_pocket(clearance):
    grid = clearance.cells.grid_mm
    for k, (gap, piece, pocket, square) in enumerate(zip(
            clearance.gaps_mm, clearance.pieces, clearance.pockets,
            clearance.layout.squares, strict=True)):
        # The pocket is the layout's square (the leftover cleaning keeps its corners).
        assert pocket.equals(square), k
        glue = clearance.glues[k]
        margin = glue_fit_margin(grid, pinch_joined=bool(glue.cells.pinch_fixes),
                                 rounding_mm=3 * vertex_dist([glue.cells.silhouette]))
        measured = shapely.distance(piece.parts[0], pocket.boundary)
        assert shapely.contains_properly(pocket, piece.parts[0])
        assert gap - margin["margin_mm"] <= measured <= gap + margin["margin_mm"], k
    # Ascending gaps give strictly smaller pieces.
    areas = [p.parts[0].area for p in clearance.pieces]
    assert areas == sorted(areas, reverse=True) and len(set(areas)) == 6


def test_every_glue_call_passes_its_checks(clearance):
    for glue in clearance.glues:
        for check in (glue_fit_check(glue), glue_partition_check(glue)):
            assert check.status == "PASS", (check.id, check.measured)


def test_the_base_is_identical_across_the_glue_calls(clearance):
    first = clearance.glues[0]
    for glue in clearance.glues[1:]:
        assert [shapely.to_wkb(c) for c in glue.cells.cells] == \
            [shapely.to_wkb(c) for c in first.cells.cells]
        assert glue.cells.labels == first.cells.labels
        assert np.array_equal(glue.bodies[0].mesh.vertices, first.bodies[0].mesh.vertices)
        assert np.array_equal(glue.bodies[0].mesh.faces, first.bodies[0].mesh.faces)
    assert np.array_equal(clearance.base.mesh.faces, first.bodies[0].mesh.faces)


def test_a_base_that_differs_between_calls_is_refused(monkeypatch):
    real = ts.glue_geometry
    calls = []

    def shifted(cells, **kw):
        calls.append(kw["clearance_mm"])
        glue = real(cells, **kw)
        if len(calls) == 3:  # swap one cell's order: the bases now differ
            rebuilt = glue.cells
            cells2 = rebuilt.cells[1:] + rebuilt.cells[:1]
            labels2 = rebuilt.labels[1:] + rebuilt.labels[:1]
            glue = dataclasses.replace(glue, cells=dataclasses.replace(
                rebuilt, cells=cells2, labels=labels2))
        return glue

    monkeypatch.setattr(ts, "glue_geometry", shifted)
    with pytest.raises(StripError, match="differ"):
        clearance_strip(OWNER_GAPS_MM, rules=RULES)


def label_holes(silhouette, squares):
    """Per square, the holes of the gridded silhouette below it (centroid x inside the
    square's x span, centroid y below it)."""
    holes = [shapely.Polygon(r) for r in silhouette.interiors]
    out = []
    for sq in squares:
        x0, y0, x1, _ = sq.bounds
        out.append([h for h in holes
                    if x0 <= h.centroid.x <= x1 and h.centroid.y < y0])
    return holes, out


def test_k_holes_below_pocket_k(clearance):
    silhouette = clearance.cells.silhouette
    holes, below = label_holes(silhouette, clearance.layout.squares)
    assert [len(b) for b in below] == [1, 2, 3, 4, 5, 6]
    assert len(holes) == 21  # each hole under exactly one pocket
    # Through-holes in the base body too: the base's cells' union has them.
    base_union = shapely.union_all(clearance.base.parts)
    assert len(base_union.interiors) == 21


def gridded_walls(silhouette, squares):
    """The smallest wall among the gridded holes, the squares and the outer edge."""
    holes = [shapely.Polygon(r) for r in silhouette.interiors]
    edge = silhouette.exterior
    shapes = holes + list(squares)
    walls = [shapely.distance(a, b) for a, b in combinations(shapes, 2)]
    walls += [shapely.distance(s, edge) for s in shapes]
    return min(walls)


def gridded_hole_radius(silhouette, layout):
    """The smallest distance from a hole centre to the solid (0 if a centre is solid)."""
    centres = [c for cs in layout.hole_centres for c in cs]
    return min(shapely.distance(shapely.Point(c), silhouette) for c in centres)


def test_clearance_walls_and_holes_on_the_grid(clearance):
    s = clearance.cells.silhouette
    assert gridded_walls(s, clearance.pockets) >= WALL
    # Each hole centre is at least half the rule's diameter from the solid: the hole is
    # at least that diameter across.
    assert gridded_hole_radius(s, clearance.layout) >= HOLE / 2


def test_clearance_meshes_are_closed(clearance):
    assert_closed(clearance.base)
    for piece in clearance.pieces:
        assert_closed(piece)


def test_clearance_bytes_repeat():
    a = clearance_strip(OWNER_GAPS_MM, rules=RULES)
    b = clearance_strip(OWNER_GAPS_MM, rules=RULES)
    assert encode_stl(a.base.mesh) == encode_stl(b.base.mesh)
    for p, q in zip(a.pieces, b.pieces, strict=True):
        assert encode_stl(p.mesh) == encode_stl(q.mesh)


# --- the skin strip --------------------------------------------------------------------


def test_skin_strip_bodies(skin):
    assert skin.depths_mm == OWNER_DEPTHS_MM
    assert (skin.base.name, skin.white.name) == ("base", f"color-{ts.SKIN_WHITE_INDEX}")
    assert skin.cells.base_index == ts.SKIN_BASE_INDEX
    # Every white cell's top is at the thickness; the full patch is (0, T).
    assert all(z1 == THICKNESS_MM for _, _, z1 in skin.white.slabs)
    squares = skin.layout.squares
    expected = 0.0
    for depth, sq in zip(skin.depths_mm, squares[1:6], strict=True):
        expected += sq.area * depth
    expected += squares[6].area * THICKNESS_MM
    assert skin.white.expected_volume_mm3 == pytest.approx(expected, rel=1e-12)
    assert stored(skin.white.mesh).volume == pytest.approx(expected, rel=1e-9)


def test_skin_ranges_per_patch(skin):
    t = THICKNESS_MM
    by_patch = {}
    for cell, patch in zip(skin.cells.cells, skin.patches, strict=True):
        by_patch.setdefault(patch, []).append(cell)
    assert sorted(by_patch) == [0, 2, 3, 4, 5, 6, 7]  # patch 1 is black: base cells only
    for z_cells, z0, z1 in skin.white.slabs:
        patch = {skin.patches[skin.cells.cells.index(c)] for c in z_cells}
        if z0 == 0.0:
            assert patch == {7}
        else:
            assert len(patch) == 1
            depth = skin.depths_mm[patch.pop() - 2]
            assert z0 == t - depth
    for z_cells, z0, z1 in skin.base.slabs:
        assert z0 == 0.0
        patch = {skin.patches[skin.cells.cells.index(c)] for c in z_cells}
        if z1 == t:
            assert patch == {0}
        else:
            assert len(patch) == 1
            assert z1 == t - skin.depths_mm[patch.pop() - 2]
    # Nothing of the base under the full patch.
    assert not any(skin.patches[skin.cells.cells.index(c)] == 7 for c in skin.base.parts)


def test_skin_partition_passes(skin):
    check = color_partition_check(skin.cells, [skin.base, skin.white], THICKNESS_MM)
    assert check.status == "PASS", check.measured


def test_skin_holes_walls_and_meshes(skin):
    s = skin.cells.silhouette
    _, below = label_holes(s, skin.layout.squares)
    assert [len(b) for b in below] == [0, 1, 2, 3, 4, 5, 0]
    assert gridded_walls(s, skin.layout.squares) >= WALL
    assert gridded_hole_radius(s, skin.layout) >= HOLE / 2
    assert_closed(skin.base)
    assert_closed(skin.white)


def test_skin_bytes_repeat():
    a = skin_strip(OWNER_DEPTHS_MM, rules=RULES)
    b = skin_strip(OWNER_DEPTHS_MM, rules=RULES)
    assert encode_stl(a.base.mesh) == encode_stl(b.base.mesh)
    assert encode_stl(a.white.mesh) == encode_stl(b.white.mesh)


def test_the_pocket_depth_is_the_skin_rule(clearance):
    for glue in clearance.glues:
        assert glue.skin_mm == SKIN
    # The base's pocket cells are cut to T - d; its other cells span the thickness.
    assert {(z0, z1) for _, z0, z1 in clearance.base.slabs} == {
        (0.0, THICKNESS_MM - SKIN), (0.0, THICKNESS_MM)}


# --- bad inputs ------------------------------------------------------------------------


BAD_GAPS = [
    ([0.1, 0.15, 0.2, 0.25, 0.3], "6"),
    ([0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4], "6"),
    ([0.1, 0.15, 0.2, 0.2, 0.3, 0.35], "ascending"),
    ([0.15, 0.1, 0.2, 0.25, 0.3, 0.35], "ascending"),
    ([0.0, 0.15, 0.2, 0.25, 0.3, 0.35], "above 0"),
    ([-0.1, 0.15, 0.2, 0.25, 0.3, 0.35], "above 0"),
    ([0.1, 0.15, 0.2, 0.25, 0.3, math.inf], "finite"),
    ([0.1, 0.15, 0.2, 0.25, 0.3, math.nan], "finite"),
    ([True, 0.15, 0.2, 0.25, 0.3, 0.35], "number"),
    ([0.1, 0.15, 0.2, 0.25, 0.3, "0.35"], "number"),
    ([0.1, 0.15, 0.2, 0.25, 0.3, 5.0], "half"),
    ("0.1", "sequence"),
    (0.1, "sequence"),
]


@pytest.mark.parametrize(("gaps", "message"), BAD_GAPS)
def test_bad_gaps_are_refused(gaps, message):
    with pytest.raises(StripError, match=message) as info:
        clearance_strip(gaps, rules=RULES)
    assert "gaps_mm" in str(info.value)


BAD_DEPTHS = [
    ([0.2, 0.4, 0.6, 0.8], "5"),
    ([0.2, 0.4, 0.6, 0.8, 1.0, 1.2], "5"),
    ([0.2, 0.4, 0.4, 0.8, 1.0], "ascending"),
    ([0.0, 0.4, 0.6, 0.8, 1.0], "above 0"),
    ([0.2, 0.4, 0.6, 0.8, math.inf], "finite"),
    ([False, 0.4, 0.6, 0.8, 1.0], "number"),
    ([0.2, 0.4, 0.6, 0.8, 3.0], "thickness"),
    ("abc", "sequence"),
]


@pytest.mark.parametrize(("depths", "message"), BAD_DEPTHS)
def test_bad_depths_are_refused(depths, message):
    with pytest.raises(StripError, match=message) as info:
        skin_strip(depths, rules=RULES)
    assert "depths_mm" in str(info.value)


def test_strip_error_is_a_value_error():
    assert issubclass(StripError, ValueError)

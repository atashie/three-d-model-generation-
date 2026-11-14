"""Tests for tdmg.calibration_strip: the clearance and skin calibration strips
(docs/plans/2026-11-14-test-strip.md, Decisions 1 to 3 and Task 1)."""

from __future__ import annotations

import dataclasses
import io
import math
import os
import subprocess
import sys
from itertools import combinations

import numpy as np
import pytest
import shapely
import trimesh
from shapely import affinity

import tdmg.calibration_strip as ts
from tdmg.calibration_strip import (
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
from tdmg.checks import merge_exact, topology_checks
from tdmg.color_checks import (
    body_export_check,
    color_partition_check,
    glue_fit_check,
    glue_fit_margin,
    glue_partition_check,
)
from tdmg.color_geometry import EPS, snap_move_mm, vertex_dist
from tdmg.flat import encode_stl
from tdmg.rules import load_rules

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
    """The stored mesh passes every F1 check and its own F2.export_matches_geometry (the
    Body's bounds, z range, expected volume and per-slab occupancy, with the derived
    float32-storage tolerances)."""
    mesh = stored(body.mesh)
    checks = topology_checks(mesh)
    assert [(c.id, c.measured) for c in checks if c.status != "PASS"] == [], body.name
    assert {c.id for c in checks} >= {"F1.edge_manifold", "F1.vertex_manifold"}
    export = body_export_check(mesh, body)
    assert export.status == "PASS", (body.name, export.measured)


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
    # As the module checks it: each side of a wall can move by one grid snap.
    assert min_wall_mm(layout) - 2 * snap_move_mm(layout.grid_mm) >= WALL
    for centres, holes in zip(layout.hole_centres, layout.holes, strict=True):
        for (x, y), hole in zip(centres, holes, strict=True):
            # The circle of the rule's diameter at the centre lies inside the hole.
            assert shapely.distance(shapely.Point(x, y), hole.exterior) >= HOLE / 2
    # Every square is EDGE_MARGIN_MM from the strip's left, right and top edges.
    minx, _, maxx, maxy = shapely.union_all(layout.squares).bounds
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
    snap = snap_move_mm(grid)
    for k, (gap, piece, pocket, square) in enumerate(zip(
            clearance.gaps_mm, clearance.pieces, clearance.pockets,
            clearance.layout.squares, strict=True)):
        # The pocket is the layout's square (the leftover cleaning keeps its corners).
        assert pocket.equals(square), k
        glue = clearance.glues[k]
        margin = glue_fit_margin(grid, pinch_joined=bool(glue.cells.pinch_fixes),
                                 rounding_mm=3 * vertex_dist([glue.cells.silhouette]))
        polygon = piece.parts[0]
        measured = shapely.distance(polygon, pocket.boundary)
        assert shapely.contains_properly(pocket, polygon)
        # At least the gap less F4.glue_fit's margin; at most one snap above it.
        assert gap - margin["margin_mm"] <= measured <= gap + snap, k
        # Every side, not only the nearest: the piece's straight edges are its pocket's
        # inset by the gap, each moved by at most one snap (the pocket is on the grid).
        px0, py0, px1, py1 = pocket.bounds
        inset = (px0 + gap, py0 + gap, px1 - gap, py1 - gap)
        for side, (got, want) in enumerate(zip(polygon.bounds, inset, strict=True)):
            assert abs(got - want) <= snap, (k, side, got, want)
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
    # The strip's base is the first call's glue base (the others equal it, above).
    assert clearance.base is first.bodies[0]


def _cells_rotated(glue):
    """The rebuilt cells in another order."""
    rebuilt = glue.cells
    return dataclasses.replace(glue, cells=dataclasses.replace(
        rebuilt, cells=rebuilt.cells[1:] + rebuilt.cells[:1],
        labels=rebuilt.labels[1:] + rebuilt.labels[:1]))


def _pocket_moved(glue):
    """Pocket 1's polygon moved by one grid step."""
    first = glue.pockets[0]
    moved = dataclasses.replace(first, polygon=affinity.translate(
        first.polygon, glue.grid_mm, 0))
    return dataclasses.replace(glue, pockets=(moved, *glue.pockets[1:]))


def _base_vertices_moved(glue):
    """The glue base mesh with every vertex moved by one grid step in x."""
    base = glue.bodies[0]
    mesh = trimesh.Trimesh(base.mesh.vertices + [glue.grid_mm, 0.0, 0.0], base.mesh.faces,
                           process=False, validate=False)
    return dataclasses.replace(glue, bodies=(dataclasses.replace(base, mesh=mesh),
                                             *glue.bodies[1:]))


@pytest.mark.parametrize("perturb", [_cells_rotated, _pocket_moved, _base_vertices_moved])
def test_a_base_that_differs_between_calls_is_refused(monkeypatch, perturb):
    real = ts.glue_geometry
    calls = []

    def perturbed(cells, **kw):
        calls.append(kw["clearance_mm"])
        glue = real(cells, **kw)
        return perturb(glue) if len(calls) == 3 else glue

    monkeypatch.setattr(ts, "glue_geometry", perturbed)
    with pytest.raises(StripError, match="differ"):
        clearance_strip(OWNER_GAPS_MM, rules=RULES)
    assert len(calls) == 3  # refused at the perturbed call


def test_a_gap_that_leaves_a_leftover_is_refused():
    # At 1.9 mm the kept piece's clearance band no longer reaches the pocket's corners
    # (its rounded corners have radius r + c, so the cusps are wider than the opening):
    # they become base, the pocket shrinks, and the pockets would depend on the gap.
    gaps = (0.1, 0.15, 0.2, 0.25, 0.3, 1.9)
    with pytest.raises(StripError, match="leftover") as info:
        clearance_strip(gaps, rules=RULES)
    assert "1.9" in str(info.value)


def test_a_glue_call_with_a_pinch_fix_is_refused(monkeypatch):
    real = ts.glue_geometry

    def pinched(cells, **kw):
        glue = real(cells, **kw)
        fix = {"vertex": [0.0, 0.0], "label": 0, "losers": [1], "clipped": False,
               "area_mm2": 0.0, "bound_mm2": 0.0}
        return dataclasses.replace(glue, cells=dataclasses.replace(
            glue.cells, pinch_fixes=(fix,)))

    monkeypatch.setattr(ts, "glue_geometry", pinched)
    with pytest.raises(StripError, match="pinch"):
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
    terms = [sq.area * depth for depth, sq in zip(skin.depths_mm, squares[1:6],
                                                  strict=True)]
    terms.append(squares[6].area * THICKNESS_MM)
    expected = math.fsum(terms)
    # Derived tolerance: _body takes each height as T - (T - d), not d. T - d is rounded
    # once (at most EPS T / 2 off) and the outer subtraction once more (at most EPS T / 2),
    # so each height is within EPS T of d, times the patch's area; each product and the
    # body's running sum add at most EPS x the total per term.
    tol = math.fsum(sq.area * EPS * THICKNESS_MM for sq in squares[1:7]) \
        + len(terms) * EPS * expected
    assert abs(skin.white.expected_volume_mm3 - expected) <= tol
    # The stored mesh against the Body: bounds, z range, volume and occupancy.
    assert_closed(skin.white)


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


CHILD = """
import hashlib
from tdmg.calibration_strip import (OWNER_DEPTHS_MM, OWNER_GAPS_MM, clearance_strip,
                                    skin_strip)
from tdmg.flat import encode_stl
from tdmg.rules import load_rules
rules = load_rules()
c = clearance_strip(OWNER_GAPS_MM, rules=rules)
s = skin_strip(OWNER_DEPTHS_MM, rules=rules)
for body in (c.base, *c.pieces, s.base, s.white):
    print(body.name, hashlib.sha256(encode_stl(body.mesh)).hexdigest())
"""


def test_two_fresh_processes_give_identical_stl_bytes():
    outputs = []
    for hash_seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        done = subprocess.run([sys.executable, "-c", CHILD], env=env, capture_output=True,
                              text=True, check=True, timeout=300)
        outputs.append(done.stdout.split())
    assert len(outputs[0]) == 2 * (1 + 6 + 2)
    assert outputs[0] == outputs[1]


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

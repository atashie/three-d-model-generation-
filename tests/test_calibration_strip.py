"""Tests for tdmg.calibration_strip: the clearance and skin calibration strips
(docs/plans/2026-11-14-test-strip.md, Decisions 1 to 4 and Tasks 1 and 2)."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import io
import json
import math
import os
import subprocess
import sys
from dataclasses import replace
from itertools import combinations
from pathlib import Path

import numpy as np
import pytest
import shapely
import test_slice
import trimesh
from shapely import affinity

import tdmg.calibration_strip as ts
import tdmg.color_slicing as cs
import tdmg.slicing
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
    export_3mf_check,
    glue_fit_check,
    glue_fit_margin,
    glue_partition_check,
)
from tdmg.color_gcode import f3_warning_ids, required_check_ids
from tdmg.color_geometry import EPS, snap_move_mm, vertex_dist
from tdmg.flat import _body_count, encode_stl
from tdmg.rules import load_rules
from tdmg.slicer import SlicerError
from tdmg.slicing import SLICE_REQUIRED_CHECKS
from tdmg.threemf import Shell

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
    minx, miny, maxx, maxy = shapely.union_all(layout.squares).bounds
    if make is clearance_layout:
        # Every square is EDGE_MARGIN_MM from the strip's left, right and top edges.
        assert (minx, maxx, maxy) == (ts.EDGE_MARGIN_MM, layout.width_mm - ts.EDGE_MARGIN_MM,
                                      layout.height_mm - ts.EDGE_MARGIN_MM)
    else:
        # Turned a quarter turn counterclockwise: from the front, back and left edges.
        assert (miny, maxy, minx) == (ts.EDGE_MARGIN_MM, layout.height_mm - ts.EDGE_MARGIN_MM,
                                      ts.EDGE_MARGIN_MM)


def test_the_skin_strip_is_long_along_y_and_the_clearance_strip_along_x():
    # Plan Task 2 amendment: the pinned OrcaSlicer turns a part long along x on the A1
    # (align_to_y_axis), and the color checks place the model unturned.
    skin = skin_layout(rules=RULES)
    clearance = clearance_layout(rules=RULES)
    assert skin.height_mm > skin.width_mm
    assert clearance.width_mm > clearance.height_mm
    # The same strip, turned: the skin strip's extents are its x layout's, swapped.
    n = len(ts.PATCH_HOLES)
    length = 2 * ts.EDGE_MARGIN_MM + n * ts.PATCH_SIDE_MM + (n - 1) * ts.PATCH_SPACING_MM
    assert skin.height_mm == length
    # The same label band and margin as the clearance strip, with the larger square.
    assert skin.width_mm == clearance.height_mm - ts.POCKET_SIDE_MM + ts.PATCH_SIDE_MM
    # Patches front to back: each square's y above the previous one's, x the same.
    ys = [sq.bounds[1] for sq in skin.squares]
    assert ys == sorted(ys) and len(set(ys)) == n
    assert len({sq.bounds[0] for sq in skin.squares}) == 1


def test_a_skin_layout_long_along_x_is_refused(monkeypatch):
    monkeypatch.setattr(ts, "SKIN_ALONG_Y", False)
    with pytest.raises(StripError, match="longer in y"):
        skin_layout(rules=RULES)


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


def test_a_gap_that_folds_every_piece_is_refused():
    # At 4.5 mm the shrunk piece (1 mm a side) is below color.glue.min_piece_side_mm, so
    # glue_geometry folds every pocket into the base: no pockets, no pieces, no leftover.
    gaps = (0.1, 0.2, 0.3, 0.4, 0.5, 4.5)
    with pytest.raises(StripError, match="color.glue.min_piece_side_mm") as info:
        clearance_strip(gaps, rules=RULES)
    assert "4.5" in str(info.value)


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


def label_holes(silhouette, squares, along_y=False):
    """Per square, the holes of the gridded silhouette beside it: below it (centroid x
    inside the square's x span, centroid y below it), or with along_y to its right
    (centroid y inside the square's y span, centroid x right of it)."""
    holes = [shapely.Polygon(r) for r in silhouette.interiors]
    out = []
    for sq in squares:
        x0, y0, x1, y1 = sq.bounds
        out.append([h for h in holes
                    if ((y0 <= h.centroid.y <= y1 and h.centroid.x > x1) if along_y
                        else (x0 <= h.centroid.x <= x1 and h.centroid.y < y0))])
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
    holes, beside = label_holes(s, skin.layout.squares, along_y=True)
    assert [len(b) for b in beside] == [0, 1, 2, 3, 4, 5, 0]
    assert len(holes) == 15  # each hole beside exactly one patch
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


# --- Task 2: make_strips (gating, files and slicing) ------------------------------------
#
# The fake OrcaSlicer is tests/test_slice.py's (fixture fake): its G-code has no layers, so
# the F3 and color checks are UNKNOWN and the strips NOT CERTIFIED unless a test makes the
# required ones pass. The real slicer runs in the test marked slicer.

fake = test_slice.fake

FILES = {
    "clearance/base.stl", "clearance/pieces.stl",
    "clearance/slice/base/plate_1.gcode", "clearance/slice/base/plate_1.statistics.json",
    "clearance/slice/pieces/plate_1.gcode", "clearance/slice/pieces/plate_1.statistics.json",
    "skin/model.3mf", "skin/palette.json",
    "skin/slice/filaments/filament-1.json", "skin/slice/filaments/filament-2.json",
    "skin/slice/face-up/orca-input.3mf", "skin/slice/face-up/plate_1.gcode",
    "skin/slice/face-up/plate_1.statistics.json"}
GLUE_IDS = {"F4.glue_fit", "F4.glue_partition"}
AMS_IDS = {"F1.finite", "F1.no_degenerate_faces", "F1.no_duplicate_faces",
           "F1.edge_manifold", "F1.consistent_orientation", "F1.vertex_manifold",
           "F1.positive_volume", "F2.export_matches_geometry",
           "F2.export_3mf_matches_bodies", "F2.fits_build_volume", "F4.color_partition",
           "F4.filaments", "F5.triangles"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _files(out: Path) -> set[str]:
    return {str(p.relative_to(out)).replace("\\", "/") for p in out.rglob("*") if p.is_file()}


def _stl(data: bytes):
    return merge_exact(trimesh.load(io.BytesIO(data), file_type="stl", process=False))


def _pass_required(monkeypatch, warnings="FAIL"):
    """Make every required F3 check of the plates, and every required color check of the
    face, PASS (the fake's G-code cannot be measured); the face's warning checks get the
    status warnings."""
    real_f3 = tdmg.slicing.f3_checks

    def f3(*a, **kw):
        checks, printed = real_f3(*a, **kw)
        return [replace(c, status="PASS") for c in checks], printed
    monkeypatch.setattr(tdmg.slicing, "f3_checks", f3)
    real_color = cs.color_slice_checks

    def color(gcode, shells, setup, statistics=None, not_measured=None):
        checks, record = real_color(gcode, shells, setup, statistics, not_measured)
        n = len(list(shells))
        req, warn = required_check_ids(n), set(f3_warning_ids(n))
        return [replace(c, status="PASS") if c.id in req else
                replace(c, status=warnings) if c.id in warn else c for c in checks], record
    monkeypatch.setattr(cs, "color_slice_checks", color)


@pytest.fixture
def orca(fake):
    """The fake OrcaSlicer, reporting each model's own layer count."""
    return lambda **kw: fake(layers="auto", **kw)


def test_make_strips_writes_the_folder_and_the_record(fake, orca, tmp_path):
    out = tmp_path / "strip"
    rec = ts.make_strips(out, orca())
    assert _files(out) == FILES | {"strip.json"}
    assert json.loads((out / "strip.json").read_bytes()) == rec
    assert (rec["schema"], rec["algorithm"]) == ("tdmg.strip/1", "strip-2")
    assert rec["source"] == "docs/plans/2026-11-14-test-strip.md"
    assert (Path(__file__).parents[1] / rec["source"]).is_file()
    assert rec["outputs"] == {n: _sha((out / n).read_bytes()) for n in FILES}
    assert str(tmp_path) not in (out / "strip.json").read_text(encoding="utf-8")
    geometry = rec["geometry"]
    assert rec["geometry_id"] == _sha(ts.canonical_json(geometry))
    assert geometry["gaps_mm"] == list(OWNER_GAPS_MM)
    assert geometry["depths_mm"] == list(OWNER_DEPTHS_MM)
    assert geometry["source"] == rec["source"]
    # The slicer identity and profile hashes, as tdmg slice records them.
    assert rec["slicer"]["pin"] == "orcaslicer-2.5.0"
    assert rec["slicer"]["exe_sha256"] == fake.pin.exe.sha256
    assert set(rec["slicer"]["profiles"]) == {"machine", "process", "filament"}

    # The clearance strip: base.stl is one body, pieces.stl the six pieces in gap order.
    cl = rec["clearance"]
    base = _stl((out / "clearance/base.stl").read_bytes())
    pieces = _stl((out / "clearance/pieces.stl").read_bytes())
    assert (_body_count(base), _body_count(pieces)) == (1, 6)
    assert [p["gap_mm"] for p in cl["pockets"]] == list(OWNER_GAPS_MM)
    assert [p["holes"] for p in cl["pockets"]] == [1, 2, 3, 4, 5, 6]
    xs = [p["piece_bounds_mm"][0] for p in cl["pockets"]]
    assert xs == sorted(xs)                                   # left to right, gap order
    for p in cl["pockets"]:
        assert p["gap_mm"] - 1e-5 <= p["measured_gap_mm"] <= p["gap_mm"] + 1e-5
    assert cl["files"]["base"]["sha256"] == rec["outputs"]["clearance/base.stl"]
    assert cl["files"]["pieces"]["bodies"] == 6
    assert len(cl["glue"]) == 6 and [g["gap_mm"] for g in cl["glue"]] == list(OWNER_GAPS_MM)
    want = sorted(SLICE_REQUIRED_CHECKS - {"F2.target_width", "F6.portability"} | GLUE_IDS)
    for name, n in (("base", 1), ("pieces", 6)):
        plate = cl["plates"][name]
        assert plate["required_checks"] == want
        assert "F2.target_width" in plate["not_applicable"]
        assert set(plate["not_required"]) == {"F6.portability"}
        by = [c for c in plate["checks"] if c["id"] == "F4.body_count"]
        assert [(c["status"], c["measured"], c["threshold"]) for c in by] == [("PASS", n, n)]
        assert [c["id"] for c in plate["checks"]].count("F4.glue_fit") == 6
        assert [c["id"] for c in plate["checks"]].count("F4.glue_partition") == 6
        assert all(c["status"] == "PASS" for c in plate["checks"]
                   if c["id"].startswith(("F1.", "F2.", "F4.", "F5.")))
        assert plate["gcode"]["file"] == f"clearance/slice/{name}/plate_1.gcode"
        assert "missing" not in plate["certification"]
        # The fake's G-code cannot be measured: F3 UNKNOWN, so NOT CERTIFIED.
        assert plate["certification"].startswith("NOT CERTIFIED: F3.")
    assert cl["verdict"] == "NOT CERTIFIED"

    # The skin strip: model.3mf, one shell per color, read back as the gate reads it.
    sk = rec["skin"]
    palette = json.loads((out / "skin/palette.json").read_bytes())
    assert palette["strip_geometry_id"] == rec["geometry_id"]
    assert "colorflat_id" not in palette
    assert [(s["index"], s["hex"]) for s in palette["shells"]] == [
        (0, "#000000"), (1, "#FFFFFF")]
    assert palette["model_3mf_sha256"] == rec["outputs"]["skin/model.3mf"]
    assert sk["model_3mf"]["check"]["status"] == "PASS"
    assert [d["depth_mm"] for d in sk["patches"]] == [None, *OWNER_DEPTHS_MM, THICKNESS_MM]
    assert [d["holes"] for d in sk["patches"]] == [0, 1, 2, 3, 4, 5, 0]
    face = sk["face"]
    assert face["face"] == "up"
    req = set(face["required_checks"])
    assert req == (AMS_IDS | required_check_ids(2) | {
        "F2.orca_input_matches_bodies", "F6.slicer_exit", "F6.gcode_present",
        "F6.layer_count", "F6.single_object"})
    assert "F6.portability" not in req
    ids = {c["id"] for c in face["checks"]}
    assert set(sk["not_required"]) == ids - req
    assert set(sk["not_required"]) >= {"F6.portability", *f3_warning_ids(2)}
    assert face["gcode"]["file"] == "skin/slice/face-up/plate_1.gcode"
    assert face["orca_input"]["file"] == "skin/slice/face-up/orca-input.3mf"
    assert [f["file"] for f in sk["filaments"]["profiles"]] == [
        "skin/slice/filaments/filament-1.json", "skin/slice/filaments/filament-2.json"]
    assert sk["verdict"] == "NOT CERTIFIED"
    assert rec["verdicts"] == {"clearance": "NOT CERTIFIED", "skin": "NOT CERTIFIED"}


def test_the_skin_shells_match_the_3mf(orca, tmp_path):
    out = tmp_path / "strip"
    ts.make_strips(out, orca())
    rules = load_rules()
    strip = skin_strip(OWNER_DEPTHS_MM, rules=rules)
    shells = []
    for body, (index, hex_code), role, name in zip(
            (strip.base, strip.white), ts.SKIN_PALETTE, ("base", "inlay"),
            ("skin-base", "skin-color-1-ffffff"), strict=True):
        mesh = stored(body.mesh)
        shells.append(Shell(name, role, index, hex_code, mesh.vertices, mesh.faces))
    assert export_3mf_check((out / "skin/model.3mf").read_bytes(), shells).status == "PASS"


def test_printable_when_every_required_check_passes_and_warnings_do_not_block(
        orca, tmp_path, monkeypatch):
    _pass_required(monkeypatch, warnings="FAIL")
    out = tmp_path / "strip"
    rec = ts.make_strips(out, orca())
    assert rec["verdicts"] == {"clearance": "PRINTABLE", "skin": "PRINTABLE"}
    for section in (rec["clearance"], rec["skin"]):
        assert section["certification"] == "PRINTABLE"
        assert section["certification_note"] == ts.STRIP_PRINTABLE_MEANING
    face = rec["skin"]["face"]
    assert face["gcode"]["quarantined"] is False
    assert face["warnings"]                    # the warning FAILs are recorded
    assert {c["status"] for c in face["checks"] if c["id"] in f3_warning_ids(2)} == {"FAIL"}
    assert "skin/slice/face-up/plate_1.gcode" in rec["outputs"]


def test_a_required_fail_makes_its_strip_not_certified(orca, tmp_path, monkeypatch):
    _pass_required(monkeypatch)
    real = tdmg.slicing.f3_checks          # already passing; FAIL one on the pieces plate

    def pieces_fail(gcode, stl, setup, not_measured=None):
        checks, printed = real(gcode, stl, setup, not_measured)
        if _body_count(_stl(stl)) == 6:
            checks = [replace(c, status="FAIL") if c.id == "F3.edge_coverage" else c
                      for c in checks]
        return checks, printed
    monkeypatch.setattr(tdmg.slicing, "f3_checks", pieces_fail)
    out = tmp_path / "strip"
    rec = ts.make_strips(out, orca())
    cl = rec["clearance"]
    assert rec["verdicts"] == {"clearance": "NOT CERTIFIED", "skin": "PRINTABLE"}
    assert cl["plates"]["base"]["verdict"] == "PRINTABLE"
    assert cl["certification"] == "NOT CERTIFIED: pieces: F3.edge_coverage FAIL"
    assert cl["certification_note"] is None
    # The FAILed plate's G-code is quarantined, as tdmg slice does.
    assert (out / "clearance/slice/pieces/plate_1.gcode.failed").is_file()
    assert not (out / "clearance/slice/pieces/plate_1.gcode").exists()


def _fail_on_base(monkeypatch, ids):
    """On top of _pass_required: the base plate's F3 checks in ids FAIL."""
    _pass_required(monkeypatch)
    real = tdmg.slicing.f3_checks

    def base_fail(gcode, stl, setup, not_measured=None):
        checks, printed = real(gcode, stl, setup, not_measured)
        if _body_count(_stl(stl)) == 1:
            checks = [replace(c, status="FAIL") if c.id in ids else c for c in checks]
        return checks, printed
    monkeypatch.setattr(tdmg.slicing, "f3_checks", base_fail)


def test_the_owner_accepted_connectivity_fail_gets_a_note(orca, tmp_path, monkeypatch):
    # The owner's decision of 2026-11-14 ("Keep the FAIL, print anyway"): noted, not
    # relabelled.
    _fail_on_base(monkeypatch, {"F3.printed_connectivity"})
    rec = ts.make_strips(tmp_path / "strip", orca())
    cl = rec["clearance"]
    assert cl["verdict"] == "NOT CERTIFIED"
    assert cl["certification"] == "NOT CERTIFIED: base: F3.printed_connectivity FAIL"
    assert rec["verdicts"] == {"clearance": "NOT CERTIFIED", "skin": "PRINTABLE"}
    note = cl["known_failures"]
    assert note["checks"] == ["F3.printed_connectivity"]
    assert note["parts"] == ["base"]
    assert note["decision"] == ts.KNOWN_FAILURE_DECISION
    assert "Keep the FAIL, print anyway" in note["decision"]
    assert note["source"] == ts.SOURCE
    assert "infill" in note["cause"] and "NOT CERTIFIED" in note["note"]
    assert rec["skin"]["known_failures"] is None
    # The G-code is still quarantined: the verdict is not changed.
    assert (tmp_path / "strip/clearance/slice/base/plate_1.gcode.failed").is_file()


@pytest.mark.parametrize("ids", [
    {"F3.edge_coverage"},                                   # another check
    {"F3.printed_connectivity", "F3.edge_coverage"},        # more than the accepted one
])
def test_any_other_failure_gets_no_note(orca, tmp_path, monkeypatch, ids):
    _fail_on_base(monkeypatch, ids)
    rec = ts.make_strips(tmp_path / "strip", orca())
    assert rec["clearance"]["verdict"] == "NOT CERTIFIED"
    assert rec["clearance"]["known_failures"] is None


def test_an_unverified_app_tree_gets_no_note(orca, tmp_path, monkeypatch):
    _fail_on_base(monkeypatch, {"F3.printed_connectivity"})
    rec = ts.make_strips(tmp_path / "strip", orca(), check_tree=False)
    assert rec["clearance"]["known_failures"] is None
    assert rec["skin"]["known_failures"] is None


def test_known_failures_needs_every_other_required_check_to_pass():
    def part(statuses, cert, required=("F3.printed_connectivity", "F1.finite")):
        return {"required_checks": list(required), "certification": cert,
                "checks": [{"id": i, "status": s} for i, s in statuses]}
    ok = part([("F3.printed_connectivity", "FAIL"), ("F1.finite", "PASS")],
              "NOT CERTIFIED: F3.printed_connectivity FAIL")
    good = part([("F3.printed_connectivity", "PASS"), ("F1.finite", "PASS")], "PRINTABLE")
    assert ts.known_failures({"a": ok, "b": good})["parts"] == ["a"]
    assert ts.known_failures({"a": good}) is None                       # nothing failed
    unknown = part([("F3.printed_connectivity", "FAIL"), ("F1.finite", "UNKNOWN")],
                   "NOT CERTIFIED: F3.printed_connectivity FAIL, F1.finite UNKNOWN")
    assert ts.known_failures({"a": unknown}) is None
    missing = part([("F3.printed_connectivity", "FAIL")],
                   "NOT CERTIFIED: F3.printed_connectivity FAIL, F1.finite missing")
    assert ts.known_failures({"a": missing}) is None
    # The record's own certification must agree (an unverified tree is named there).
    tree = part([("F3.printed_connectivity", "FAIL"), ("F1.finite", "PASS")],
                "NOT CERTIFIED: app tree not verified (--skip-tree-check), "
                "F3.printed_connectivity FAIL")
    assert ts.known_failures({"a": tree}) is None


def test_a_failed_slice_fails_both_strips(orca, tmp_path):
    rec = ts.make_strips(tmp_path / "strip", orca(exit=-50))
    assert rec["verdicts"] == {"clearance": "NOT CERTIFIED", "skin": "NOT CERTIFIED"}
    assert "F6.slicer_exit FAIL" in rec["clearance"]["certification"]
    assert "F6.slicer_exit FAIL" in rec["skin"]["certification"]


def test_strip_verdict():
    assert ts.strip_verdict({"a": "PRINTABLE", "b": "PRINTABLE"}) == ("PRINTABLE",
                                                                       "PRINTABLE")
    assert ts.strip_verdict({"a": "PRINTABLE", "b": "NOT CERTIFIED: F6.x FAIL, F3.y UNKNOWN"}
                            ) == ("NOT CERTIFIED", "NOT CERTIFIED: b: F6.x FAIL, F3.y UNKNOWN")
    assert ts.strip_verdict({}) == ("NOT CERTIFIED", "NOT CERTIFIED: nothing was sliced")


def test_every_check_that_is_not_required_has_a_reason():
    from tdmg.checks import CheckResult
    checks = [CheckResult(i, "UNKNOWN", None, None, None) for i in (
        "F6.portability", "F6.color_waste", "F3.edge_coverage.T1", "F1.finite")]
    reasons = ts.not_required_reasons(checks, {"F1.finite"})
    assert set(reasons) == {"F6.portability", "F6.color_waste", "F3.edge_coverage.T1"}
    assert all(isinstance(r, str) and r for r in reasons.values())
    with pytest.raises(StripError, match="F9.new"):
        ts.not_required_reasons([CheckResult("F9.new", "PASS", None, None, None)], set())


def test_palette_manifest_takes_exactly_one_link():
    from tdmg.threemf import ThreeMFError, palette_manifest, write_multishell_3mf
    mesh = stored(skin_strip(OWNER_DEPTHS_MM, rules=RULES).white.mesh)
    shells = [Shell("s", "base", 0, "#000000", mesh.vertices, mesh.faces)]
    data = write_multishell_3mf(shells)
    kw = {"top_area_mm2": [1.0], "volume_mm3": [1.0]}
    a = json.loads(palette_manifest(shells, data, colorflat_id="x", **kw))
    b = json.loads(palette_manifest(shells, data, link={"strip_geometry_id": "x"}, **kw))
    assert a.pop("colorflat_id") == b.pop("strip_geometry_id") == "x" and a == b
    for bad in ({}, {"colorflat_id": "x", "link": {"k": "x"}}, {"link": {"a": 1, "b": 2}}):
        with pytest.raises(ThreeMFError, match="exactly one"):
            palette_manifest(shells, data, **bad, **kw)


def _comparable(rec):
    """The record without what tdmg slice's records also let differ between runs: the
    G-code bytes' hash (the fake, like the real slicer, writes a time into its header;
    the normalised hash stays)."""
    rec = copy.deepcopy(rec)
    rec["outputs"] = {k: v for k, v in rec["outputs"].items() if "plate_1.gcode" not in k}
    for part in [*rec["clearance"]["plates"].values(), rec["skin"]["face"]]:
        if part["gcode"]:
            del part["gcode"]["sha256"]
    return rec


def test_repeat_runs_give_the_same_record_and_files(orca, tmp_path):
    root = orca()
    a = ts.make_strips(tmp_path / "a", root)
    b = ts.make_strips(tmp_path / "b", root)
    assert _comparable(a) == _comparable(b)
    assert a["strip_id"] == b["strip_id"]
    for name in FILES:
        if "plate_1.gcode" not in name:
            assert ((tmp_path / "a" / name).read_bytes()
                    == (tmp_path / "b" / name).read_bytes()), name


@pytest.mark.parametrize("kind", ["non-empty", "file"])
def test_a_bad_output_folder_is_refused_with_nothing_written(orca, tmp_path, kind):
    out = tmp_path / "strip"
    if kind == "file":
        out.write_text("x")
    else:
        out.mkdir()
        (out / "keep.txt").write_text("x")
    with pytest.raises(SlicerError, match="choose a new one"):
        ts.make_strips(out, orca())
    if kind == "file":
        assert out.read_text() == "x"
    else:
        assert _files(out) == {"keep.txt"}


def test_a_bad_timeout_is_refused_first(orca, tmp_path):
    with pytest.raises(SlicerError, match="timeout_s"):
        ts.make_strips(tmp_path / "strip", orca(), timeout_s=-1)
    assert not (tmp_path / "strip").exists()


def test_a_missing_slicer_is_refused_with_nothing_written(tmp_path, monkeypatch):
    monkeypatch.delenv("TDMG_ORCASLICER_DIR", raising=False)
    monkeypatch.delenv("TDMG_PRUSASLICER_DIR", raising=False)
    with pytest.raises(SlicerError):
        ts.make_strips(tmp_path / "strip", tmp_path / "nowhere")
    assert not (tmp_path / "strip").exists()


@pytest.mark.slicer
@pytest.mark.skipif(not os.environ.get("TDMG_ORCASLICER_DIR"),
                    reason="TDMG_ORCASLICER_DIR is not set to a verified OrcaSlicer install")
def test_the_strips_with_the_real_slicer(tmp_path):
    # Measured 2026-11-14 on the PC (plan Task 2 amendments): the skin strip and the pieces
    # plate are PRINTABLE; the base plate is NOT CERTIFIED by F3.printed_connectivity alone
    # (infill islands), which the owner decided to keep and print anyway.
    out = tmp_path / "strip"
    rec = ts.make_strips(out)
    cl = rec["clearance"]
    assert cl["plates"]["pieces"]["certification"] == "PRINTABLE"
    assert cl["plates"]["base"]["certification"] == \
        "NOT CERTIFIED: F3.printed_connectivity FAIL"
    assert cl["certification"] == "NOT CERTIFIED: base: F3.printed_connectivity FAIL"
    assert cl["verdict"] == "NOT CERTIFIED"
    assert cl["known_failures"]["checks"] == ["F3.printed_connectivity"]
    assert cl["known_failures"]["parts"] == ["base"]
    assert rec["skin"]["certification"] == "PRINTABLE", rec["skin"]["certification"]
    assert rec["skin"]["known_failures"] is None
    for name, plate in cl["plates"].items():
        by = {c["id"]: c["status"] for c in plate["checks"]}
        assert by["F6.slicer_exit"] == by["F6.layer_count"] == by["F4.body_count"] == "PASS"
        assert by["F3.edge_coverage"] == by["F3.edge_overprint"] == "PASS"
        assert plate["gcode"]["quarantined"] is (name == "base")
    face = rec["skin"]["face"]
    assert face["summary"]["changes"] is not None and face["summary"]["changes"] > 0
    assert rec["slicer"]["app_tree_verified"] is True

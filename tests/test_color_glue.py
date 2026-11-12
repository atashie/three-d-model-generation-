"""Glue route (tdmg.color_glue) and its checks (tdmg.color_checks: F4.glue_fit, glue_checks).

docs/plans/2026-11-12-color-geometry.md, Decisions 6-9, Task 5.
"""

import dataclasses
import io
import json
import math

import numpy as np
import pytest
import shapely
import trimesh
from shapely import affinity

import tdmg.color_glue
from tdmg.checks import merge_exact, topology_checks
from tdmg.color_checks import (
    ColorCheckError,
    body_export_check,
    glue_checks,
    glue_fit_check,
    glue_fit_margin,
    glue_partition_check,
)
from tdmg.color_geometry import (
    PINCH_K,
    ColorRegions,
    color_cells,
    color_regions,
    pinch_vertices,
    snap_move_mm,
)
from tdmg.color_glue import GlueError, glue_geometry
from tdmg.flat import QUAD_SEGS, encode_stl, to_model
from tdmg.profiles import load_printer
from tdmg.rules import load_rules

# Test inputs: the current rule defaults (color.glue.clearance_mm, color.glue.min_piece_
# side_mm, color.skin.depth_mm, flat.sliver.opening_width, (flat.island.min_square_side x
# the A1's 0.4 mm nozzle)^2) and the plans' test thickness.
T, D, C, SIDE, OPENING, ISLAND = 3.0, 0.6, 0.2, 2.0, 0.4, 0.64
CHORD = 1 - math.cos(math.pi / (4 * QUAD_SEGS))


def test_inputs_are_the_rule_defaults():
    rules = load_rules()
    nozzle = float(load_printer("bambu-a1").nozzle_diameter_mm)
    assert rules["color.glue.clearance_mm"].default == C
    assert rules["color.glue.min_piece_side_mm"].default == SIDE
    assert rules["color.skin.depth_mm"].default == D
    assert rules["flat.sliver.opening_width"].default == OPENING
    assert (rules["flat.island.min_square_side"].default * nozzle) ** 2 == pytest.approx(
        ISLAND)


def cells_from(inlays, s, base=0):
    """Cells for hand-drawn inlays {label: [polygons]} in S; the base is the rest."""
    union = shapely.union_all([p for ps in inlays.values() for p in ps])
    base_top = [p for p in shapely.get_parts(shapely.difference(s, union)) if p.area > 0]
    return color_cells(ColorRegions(inlays, base_top, {}, []), s, base)


def glue_of(cells, **kw):
    args = {"thickness_mm": T, "skin_mm": D, "clearance_mm": C, "min_piece_side_mm": SIDE,
            "opening_mm": OPENING, "min_island_mm2": ISLAND} | kw
    return glue_geometry(cells, **args)


def checks_of(glue):
    return glue_checks(glue, printer=load_printer("bambu-a1"), rules=load_rules())


def stored(mesh):
    return merge_exact(trimesh.load(io.BytesIO(encode_stl(mesh)), file_type="stl",
                                    process=False))


def assert_all_pass(glue):
    result = checks_of(glue)
    for name, checks in result["bodies"].items():
        assert [(c.id, c.measured) for c in checks if c.status != "PASS"] == [], name
    for name, checks in result["plates"].items():
        assert [c.id for c in checks if c.status != "PASS"] == [], name
    assert [c.id for c in result["assembly"]] == ["F4.glue_partition", "F4.glue_fit"]
    for check in result["assembly"]:
        assert check.status == "PASS", (check.id, check.measured)
    return result


def margin():
    return glue_fit_margin(SQUARE_CELLS.grid_mm)["margin_mm"]


R = OPENING / 2
# The area a convex right-angle corner loses when rounded to radius rho with QUAD_SEGS
# chords per quarter: rho^2 minus the quarter polygon's area, (QUAD_SEGS / 2) rho^2
# sin(pi / (2 QUAD_SEGS)).
def corner_loss(rho):
    return rho ** 2 - QUAD_SEGS / 2 * rho ** 2 * math.sin(math.pi / (2 * QUAD_SEGS))


def corner_baseline(uncovered, corners):
    """uncovered is the area of `corners` right-angle corners rounded to about r + c:
    between the exact circle's loss, (1 - pi / 4) (r + c)^2 each, and the 8-chord
    polygon's, corner_loss(r + c) (the buffer of the opened piece's chords is neither
    exactly), with 1e-6 mm^2 for the snaps."""
    return ((1 - math.pi / 4) * (R + C) ** 2 * corners - 1e-6 <= uncovered
            <= corner_loss(R + C) * corners + 1e-6)


S20 = shapely.box(0, 0, 20, 20)
SQUARE = shapely.box(5, 5, 15, 15)
SQUARE_CELLS = cells_from({1: [SQUARE]}, S20)


# --- a square and an L -----------------------------------------------------------------


def test_square_inlay_one_piece_with_the_clearance_gap():
    glue = glue_of(SQUARE_CELLS)
    assert glue.report["folds"] == []
    assert [(p.index, p.pocket) for p in glue.pieces] == [(1, 1)]
    piece, pocket = glue.pieces[0].polygon, glue.pockets[0].polygon
    snap = snap_move_mm(glue.grid_mm)
    # The buffer leaves the four corners, rounded to r + c, outside its reach; they are
    # cusps narrower than the opening, so the leftover's cleaning keeps them in the
    # pocket: the pocket is the whole square and nothing goes to the base.
    assert pocket.equals(SQUARE)
    [left] = glue.report["leftover"]
    assert (left["leftover_mm2"], left["small_pieces"]) == (0.0, 0)
    fit = glue_fit_check(glue)
    assert fit.status == "PASS"
    # Every wall is the square's own: the gap is c, to the snaps.
    assert fit.measured["min_gap_mm"] == pytest.approx(C, abs=2 * snap)
    # The shrink keeps convex corners sharp; the opening then rounds them to radius
    # r = opening / 2, drawn with 4 QUAD_SEGS chords per circle: a^2 - 4 r^2 plus that
    # polygon's area, 2 QUAD_SEGS r^2 sin(pi / (2 QUAD_SEGS)).
    rounded = (10 - 2 * C) ** 2 - 4 * corner_loss(R)
    assert piece.area == pytest.approx(rounded, abs=piece.length * snap)
    # The pocket is d deep: base volume = area(S) T - area(pocket) d.
    base = glue.bodies[0]
    assert base.name == "base"
    assert base.expected_volume_mm3 == pytest.approx(S20.area * T - pocket.area * D)
    assert stored(base.mesh).volume == pytest.approx(S20.area * T - pocket.area * D)
    plate = glue.bodies[1]
    assert (plate.name, plate.z_range_mm) == ("color-1", (0.0, D))
    assert stored(plate.mesh).volume == pytest.approx(piece.area * D)
    # Uncovered: those four corners, (4 - pi) (r + c)^2 to the chords.
    assert corner_baseline(glue.report["pockets"][0]["uncovered_mm2"], 4)
    assert_all_pass(glue)


def test_l_shape_concave_corner_gap_is_at_least_clearance_minus_margin():
    ell = shapely.union_all([shapely.box(5, 5, 15, 10), shapely.box(5, 10, 10, 15)])
    glue = glue_of(cells_from({1: [ell]}, S20))
    piece = glue.pieces[0].polygon
    fit = glue_fit_check(glue)
    assert fit.status == "PASS"
    snap = snap_move_mm(glue.grid_mm)
    corner = shapely.Point(10, 10)  # the concave (reflex) pocket corner
    # The shrink's chords around the concave corner come to c cos(pi / (4 QUAD_SEGS));
    # the clearance fix erodes the piece by that shortfall, so it is c away to the snap.
    assert piece.distance(corner) >= C - snap
    assert piece.distance(corner) == pytest.approx(C, abs=snap)
    assert fit.measured["min_gap_mm"] >= C - margin()
    # The fix erodes the whole piece by that shortfall, so the straight walls are c
    # plus it away.
    short = glue.report["clearance_fix"]["largest_shortfall_mm"]
    assert short == pytest.approx(C * CHORD, rel=1e-3)
    for wall in (shapely.LineString([(5, 5), (5, 15)]),
                 shapely.LineString([(5, 5), (15, 5)]),
                 shapely.LineString([(15, 5), (15, 10)]),
                 shapely.LineString([(5, 15), (10, 15)])):
        assert piece.distance(wall) == pytest.approx(C + short, abs=snap)
    assert_all_pass(glue)


def notch(degrees):
    """A 20 mm-wide polygon whose top edge has a concave notch turning by degrees."""
    h = 10 * math.tan(math.radians(degrees / 2))
    return shapely.Polygon([(2, 2), (22, 2), (22, 12), (12, 12 - h), (2, 12)])


@pytest.mark.parametrize("degrees", [3, 8, 11.25, 16, 16.8, 16.85, 20, 33, 60, 80])
def test_a_shallow_concave_notch_keeps_the_clearance(degrees):
    # Codex review 3: GEOS draws a round join of angle A with round(A / (pi / (2
    # QUAD_SEGS))) chords, so a 16.8 degree arc is one chord, c (1 - cos(8.4 deg)) =
    # 0.00215 mm short; that FAILed F4.glue_fit (gap 0.197855 mm). The clearance fix
    # erodes the piece by its measured shortfall instead.
    s24 = shapely.box(0, 0, 24, 24)
    glue = glue_of(cells_from({1: [notch(degrees)]}, s24))
    fit = glue_fit_check(glue)
    snaps = fit.threshold["snap_move_mm"] + fit.threshold["pocket_move_mm"]
    assert fit.measured["min_gap_mm"] >= C - snaps
    assert fit.status == "PASS"
    assert_all_pass(glue)


def test_the_clearance_fix_is_reported():
    glue = glue_of(cells_from({1: [notch(16.8)]}, shapely.box(0, 0, 24, 24)))
    fix = glue.report["clearance_fix"]
    assert fix["pieces_eroded"] == 1
    assert fix["rounds"] >= 1
    # The shortfall the shrink left: one 16.8 degree chord, c (1 - cos(8.4 deg)), plus
    # at most the opening's chord error.
    assert fix["largest_shortfall_mm"] >= C * (1 - math.cos(math.radians(8.4))) - 1e-9


def test_a_piece_that_cannot_be_cleared_is_refused(monkeypatch):
    monkeypatch.setattr(tdmg.color_glue, "CLEARANCE_ROUNDS", 0)
    with pytest.raises(GlueError, match="a piece is still .* short of the clearance"):
        glue_of(cells_from({1: [notch(16.8)]}, shapely.box(0, 0, 24, 24)))
    # The square's piece needs no erosion, but its outward buffer's chords at the rounded
    # corners come closer than c: the wall is grown, which also needs a round.
    with pytest.raises(GlueError, match="the pocket wall is still .* short"):
        glue_of(SQUARE_CELLS)


# --- folding ----------------------------------------------------------------------------


def test_tiny_region_inside_one_color_folds_into_it():
    hole = shapely.box(9, 9, 10, 10)
    cells = cells_from({1: [SQUARE.difference(hole)], 2: [hole]}, S20)
    glue = glue_of(cells)
    [fold] = glue.report["folds"]
    assert (fold["label"], fold["into"], fold["into_base"]) == (2, 1, False)
    assert fold["area_mm2"] == 0.0  # shrunk to 0.6 mm, the opening removes it
    assert fold["shared_mm"] == pytest.approx(4.0)
    assert 2 not in glue.cells.labels
    assert [p.index for p in glue.pockets] == [1]
    assert glue.pockets[0].polygon.equals(SQUARE)
    assert len(glue.pieces) == 1
    assert_all_pass(glue)


def between(left, right, left_y=(5, 15), right_y=(5, 15)):
    """X (color 3, 1 x 4 mm) between a left and a right region of the given colors."""
    s = shapely.box(0, 0, 30, 20)
    x = shapely.box(12, 8, 13, 12)
    regions = {3: [x]}
    regions.setdefault(left, []).append(shapely.box(5, left_y[0], 12, left_y[1]))
    regions.setdefault(right, []).append(shapely.box(13, right_y[0], 20, right_y[1]))
    return cells_from(regions, s)


def test_tiny_region_folds_into_the_longer_shared_boundary():
    # Color 2 (left) shares 4 mm with X, color 1 (right) 3 mm: the longer wins, not the
    # lower index. The base shares 1 + 1 + 1 = 3 mm.
    glue = glue_of(between(2, 1, right_y=(9, 15)))
    [fold] = glue.report["folds"]
    assert fold["label"] == 3
    assert 0 < fold["area_mm2"] < SIDE ** 2
    assert fold["neighbours"] == [[0, pytest.approx(3.0)], [1, pytest.approx(3.0)],
                                  [2, pytest.approx(4.0)]]
    assert (fold["into"], fold["shared_mm"]) == (2, pytest.approx(4.0))
    assert_all_pass(glue)


def test_a_tie_goes_to_the_lower_color_index():
    glue = glue_of(between(2, 1))  # 4 mm each side
    [fold] = glue.report["folds"]
    assert (fold["into"], fold["shared_mm"]) == (1, pytest.approx(4.0))


def test_a_tie_with_the_base_goes_to_the_color():
    s = shapely.box(0, 0, 30, 20)
    x = shapely.box(12, 8, 13, 12)
    left = shapely.box(5, 5, 12, 15)                         # 4 mm with X
    right = shapely.box(13, 5, 20, 15).difference(shapely.box(13, 10, 14, 12))
    # X touches color 2 on y 8..10 of its right side (2 mm), the base in the notch on
    # y 10..12 (2 mm) and on top and bottom (1 + 1): the base 4 mm ties color 1's 4 mm.
    glue = glue_of(cells_from({1: [left], 2: [right], 3: [x]}, s))
    fold = glue.report["folds"][0]
    assert fold["label"] == 3
    assert dict(fold["neighbours"]) == {
        0: pytest.approx(4.0), 1: pytest.approx(4.0), 2: pytest.approx(2.0)}
    assert fold["into"] == 1


def test_tiny_region_in_the_base_folds_into_the_base():
    dot = shapely.box(9, 9, 10, 10)
    glue = glue_of(cells_from({1: [dot]}, S20))
    [fold] = glue.report["folds"]
    assert (fold["label"], fold["into"], fold["into_base"]) == (1, 0, True)
    assert glue.pockets == () and glue.pieces == ()
    assert [b.name for b in glue.bodies] == ["base"]
    base = glue.bodies[0]
    assert base.expected_volume_mm3 == pytest.approx(S20.area * T)  # solid: no pocket
    assert stored(base.mesh).volume == pytest.approx(S20.area * T)
    result = assert_all_pass(glue)
    assert result["assembly"][1].measured["min_gap_mm"] is None


def test_a_tiny_part_of_s_with_no_neighbour_folds_into_the_base():
    # S is one 1.5 mm square of color 1 and nothing else: no shared boundary at all.
    s = shapely.box(0, 0, 1.5, 1.5)
    glue = glue_of(color_cells(ColorRegions({1: [s]}, [], {}, []), s, 0))
    [fold] = glue.report["folds"]
    assert (fold["into"], fold["shared_mm"], fold["neighbours"]) == (0, 0.0, [])
    assert glue.pockets == () and set(glue.cells.labels) == {0}
    assert_all_pass(glue)


def test_cascading_folds_reach_a_fixed_point():
    # X1 (color 2, 1 x 1 mm) inside X2 (color 3, a 2.2 mm square), inside color 1.
    # Both shrink to nothing alone; X1 folds first (tie on area 0, lower label), into
    # its only neighbour X2; X2 with X1 is then a 2.2 mm square, shrunk to 1.8 mm
    # (3.24 mm^2 < 4), so it folds into color 1.
    x1 = shapely.box(9.6, 9.6, 10.6, 10.6)
    x2 = shapely.box(9, 9, 11.2, 11.2)
    cells = cells_from({1: [SQUARE.difference(x2)], 2: [x1], 3: [x2.difference(x1)]}, S20)
    glue = glue_of(cells)
    folds = glue.report["folds"]
    assert [(f["label"], f["into"]) for f in folds] == [(2, 3), (3, 1)]
    assert folds[0]["area_mm2"] == 0.0
    # Recomputed: the 1.8 mm square, its corners rounded by the opening.
    assert folds[1]["area_mm2"] == pytest.approx(1.8 ** 2 - 4 * corner_loss(R), abs=1e-5)
    assert set(glue.cells.labels) == {0, 1}
    assert len(glue.pockets) == 1
    again = glue_of(cells_from({1: [SQUARE]}, S20))
    assert again.report["folds"] == []
    assert_all_pass(glue)


def test_a_fold_that_creates_a_base_pinch_is_joined_in_the_rebuild():
    # At v = (10, 10): X (color 1) NW, color 2 NE, color 3 SW, the base SE. X shares
    # 3 mm with the base (top, left) and 1.5 mm with each color, so it folds into the
    # base, which then meets itself at v only: a pinch in the base's upper slab. The
    # pockets keep their corners (the cusps are narrower than the opening), so the
    # rebuild (color_cells) joins it with a diamond.
    x = shapely.box(8.5, 10, 10, 11.5)
    cells = cells_from({1: [x], 2: [shapely.box(10, 10, 18, 18)],
                        3: [shapely.box(2, 2, 10, 10)]}, S20)
    assert pinch_vertices(cells.cells, cells.labels, grid_mm=cells.grid_mm) == []
    glue = glue_of(cells)
    assert [(f["label"], f["into"]) for f in glue.report["folds"]] == [(1, 0)]
    pinches = glue.report["rebuild"]["pinches"]
    assert pinches["fixed"] == 1
    assert glue.cells.pinch_fixes[0]["vertex"] == [10.0, 10.0]
    assert glue.cells.pinch_fixes[0]["label"] == 0
    assert pinch_vertices(glue.cells.cells, glue.cells.labels,
                          grid_mm=glue.grid_mm) == []
    fit = glue_fit_check(glue)  # the margin allows for the diamond
    assert fit.threshold["pocket_move_mm"] == pytest.approx(
        snap_move_mm(glue.grid_mm) + PINCH_K * glue.grid_mm)
    assert_all_pass(glue)


# --- small pieces, thin bands (the "Fold small pieces too" amendment) ------------------


def blobs(band_width, left=(2, 5, 8, 11), right=(12, 5, 18, 11)):
    """Two blobs of color 1 joined by a horizontal band of band_width at y 8."""
    y0, y1 = 8 - band_width / 2, 8 + band_width / 2
    return shapely.union_all([shapely.box(*left), shapely.box(left[2], y0, right[0], y1),
                              shapely.box(*right)])


def test_a_thin_band_between_two_blobs_becomes_base():
    # A 0.5 mm band (< 2 c + opening = 0.8 mm) joins two 6 mm blobs: one candidate, two
    # pieces. The pockets are only around the pieces; the band goes to the base.
    shape = blobs(0.5)
    glue = glue_of(cells_from({1: [shape]}, S20))
    assert glue.report["folds"] == []
    assert len(glue.pockets) == 2 and len(glue.pieces) == 2
    assert [p.pieces for p in glue.pockets] == [(1,), (2,)]
    band = shapely.box(8, 7.75, 12, 8.25)
    pockets = shapely.union_all([p.polygon for p in glue.pockets])
    # The band's middle is base. Near each blob the pocket reaches a little into the
    # band: the shrink's fillets at the band's corners leave a small bump on the piece,
    # and its buffer by c crosses x = 8 (measured 0.06 mm^2 for both ends together).
    assert shapely.intersection(pockets, shapely.box(9, 7.75, 11, 8.25)).area == 0
    assert shapely.intersection(pockets, band).area < band.area / 10
    [left] = glue.report["leftover"]
    # The band less the ends within the pieces' reach, and the corner cusps at the
    # band's ends that hold no piece.
    assert band.area / 2 < left["leftover_mm2"] < band.area + 1
    assert left["candidate_area_mm2"] == pytest.approx(shape.area)
    assert left["leftover_mm2"] == pytest.approx(
        left["candidate_area_mm2"] - left["pocket_area_mm2"])
    # Uncovered: each blob's four corners, plus the band's stub that stays in the pocket
    # (narrower than the opening; 0.031 mm^2 measured), plus the band of the clearance
    # fix's erosion along the piece (its perimeter x the shortfall, 0.021 mm^2).
    short = glue.report["clearance_fix"]["largest_shortfall_mm"]
    for row, piece in zip(glue.report["pockets"], glue.pieces, strict=True):
        extra = piece.polygon.length * short
        assert 4 * corner_loss(R + C) < row["uncovered_mm2"] < (
            4 * corner_loss(R + C) + 0.05 + extra)
    assert_all_pass(glue)


def test_a_neck_narrower_than_the_opening_stays_in_the_pocket_uncovered():
    # A 0.3 mm neck (< the 0.4 mm opening) between two 6 mm blobs: the shrink cuts it,
    # so two pieces; the leftover's cleaning removes the neck, so it stays in the one
    # pocket as uncovered area (glue fills it) and nothing goes to the base.
    glue = glue_of(cells_from({1: [blobs(0.3)]}, S20))
    assert len(glue.pockets) == 1 and len(glue.pieces) == 2
    [left] = glue.report["leftover"]
    assert left["leftover_mm2"] == 0.0
    # The neck (4 x 0.3 mm) plus the blobs' eight corners rounded to r + c, less a
    # little at the neck's ends (1.467 mm^2 measured).
    assert glue.report["pockets"][0]["uncovered_mm2"] == pytest.approx(
        4 * 0.3 + 8 * corner_loss(R + C), abs=0.05)
    assert glue_fit_check(glue).status == "PASS"
    assert_all_pass(glue)


def test_a_candidate_keeps_its_big_piece_and_drops_the_small_one():
    # A 6 mm blob joined by a 0.5 mm band to a 2 mm blob: the small one shrinks and opens
    # to about 2.5 mm^2 < 4 mm^2. Only the big piece and its pocket are kept.
    shape = blobs(0.5, right=(12, 7, 14, 9))
    glue = glue_of(cells_from({1: [shape]}, S20))
    assert glue.report["folds"] == []
    assert len(glue.pockets) == 1 and len(glue.pieces) == 1
    assert glue.pieces[0].polygon.within(shapely.box(2, 5, 8, 11))
    assert glue.pockets[0].polygon.within(shapely.box(2, 5, 8.5, 11))  # bump: see above
    [left] = glue.report["leftover"]
    assert left["small_pieces"] == 1
    # The 1.6 mm square with rounded corners, plus the band's bump (see above).
    assert 1.6 ** 2 - 4 * corner_loss(R) < left["small_pieces_mm2"] < SIDE ** 2
    assert left["leftover_mm2"] > 4  # the 2 mm blob and the band are base now
    assert_all_pass(glue)


def test_a_candidate_of_only_small_pieces_folds_whole():
    # Two 2 mm blobs joined by a band: pieces of about 2.5 mm^2 each, 5 mm^2 together.
    # Folding on the total (the first rule) kept it; the amended rule folds it.
    shape = blobs(0.5, left=(6, 7, 8, 9), right=(12, 7, 14, 9))
    glue = glue_of(cells_from({1: [shape]}, S20))
    [fold] = glue.report["folds"]
    assert (fold["into"], fold["pieces"]) == (0, 2)
    assert fold["area_mm2"] > SIDE ** 2 > fold["largest_piece_mm2"]
    assert glue.pockets == () and glue.pieces == ()
    assert_all_pass(glue)


# --- a misplaced piece, an empty pocket ---------------------------------------------------


def test_a_piece_moved_toward_its_wall_fails_glue_fit():
    glue = glue_of(SQUARE_CELLS)
    moved = dataclasses.replace(glue.pieces[0],
                                polygon=affinity.translate(glue.pieces[0].polygon, 0.1))
    bad = dataclasses.replace(glue, pieces=(moved,))
    fit = glue_fit_check(bad)
    assert fit.status == "FAIL"
    assert fit.measured["min_gap_mm"] == pytest.approx(0.1, abs=1e-5)
    assert fit.measured["per_piece"][0]["inside"] is True
    out = dataclasses.replace(glue.pieces[0],
                              polygon=affinity.translate(glue.pieces[0].polygon, 0.3))
    assert glue_fit_check(dataclasses.replace(glue, pieces=(out,))).measured[
        "per_piece"][0]["inside"] is False


def test_a_piece_moved_inside_the_bounds_fails_its_export_check():
    # Codex review 3: three same-color squares; the middle piece's mesh moved 1 mm in x,
    # past its pocket wall at x = 11. Bounds, volume and F1 stay as they were.
    squares = [shapely.box(a, a, a + 3, a + 3) for a in (2, 8, 14)]
    glue = glue_of(cells_from({1: squares}, S20))
    assert len(glue.pieces) == 3
    body = glue.bodies[1]
    mesh = stored(body.mesh)
    vertices = np.array(mesh.vertices)
    middle = (vertices[:, 0] > 7.5) & (vertices[:, 0] < 11.5) & (vertices[:, 1] > 7.5) \
        & (vertices[:, 1] < 11.5)
    vertices[middle, 0] += 1.0
    moved = trimesh.Trimesh(vertices, mesh.faces, process=False, validate=False)
    assert body_export_check(mesh, body).status == "PASS"
    assert {c.status for c in topology_checks(moved)} == {"PASS"}
    check = body_export_check(moved, body)
    assert check.status == "FAIL"
    assert check.measured["max_bound_error_mm"] <= check.threshold["coord_tol_mm"]
    assert check.measured["volume_error_mm3"] <= check.threshold["volume_tol_mm3"]
    [row] = check.measured["occupancy"]
    piece = glue.pieces[1].polygon
    expected = shapely.symmetric_difference(piece, affinity.translate(piece, 1.0)).area
    assert row["symmetric_difference_mm2"] == pytest.approx(expected)


def test_an_empty_pocket_fails_glue_fit():
    glue = glue_of(SQUARE_CELLS)
    fit = glue_fit_check(dataclasses.replace(glue, pieces=()))
    assert fit.status == "FAIL"
    assert fit.measured["empty_pockets"] == [1]


def test_margin_is_the_two_snaps_and_the_rounding():
    g = 2.0 ** -19
    m = glue_fit_margin(g, rounding_mm=1e-14)
    assert set(m) == {"margin_mm", "snap_move_mm", "pocket_move_mm", "rounding_mm"}
    assert m["snap_move_mm"] == m["pocket_move_mm"] == g * math.sqrt(2) / 2
    assert m["rounding_mm"] == 1e-14
    assert m["margin_mm"] == pytest.approx(sum(v for k, v in m.items() if k != "margin_mm"))
    joined = glue_fit_margin(g, pinch_joined=True)
    assert joined["pocket_move_mm"] == g * math.sqrt(2) / 2 + PINCH_K * g
    assert joined["rounding_mm"] == 0.0
    # No chord terms: the construction measures and removes them (the clearance fix).
    assert m["margin_mm"] < C * CHORD / 100


# --- oblique S, several colors, determinism ----------------------------------------------


def oblique_cells():
    fine = np.zeros((12, 16), np.uint8)
    fine[3:9, 2:7] = 1
    fine[5:12, 8:14] = 2
    fine[1:3, 10:12] = 3  # 1 x 1 px at 4.66 mm/px: a big piece
    fine[2:3, 8:9] = 3  # 0.5 x 0.5 px (2.3 mm square) in the base: below 4 mm^2, folds
    full, transform = to_model(shapely.box(0, 0, 8, 6), 37.3)
    s = shapely.Point(18, 14).buffer(12, quad_segs=QUAD_SEGS).intersection(full)
    regions = color_regions(fine, 2, transform, s, n_colors=4, base_index=0,
                            thin_width_mm=OPENING)
    return color_cells(regions, s, 0)


def test_oblique_s_every_body_passes():
    glue = glue_of(oblique_cells())
    assert [(f["label"], f["into"]) for f in glue.report["folds"]] == [(3, 0)]
    assert {p.index for p in glue.pieces} >= {1, 2, 3}
    result = assert_all_pass(glue)
    assert set(result["stl"]) == {"base", "color-1", "color-2", "color-3"}
    # Numbering: by color index, then pocket order; consecutive from 1.
    rows = glue.report["pieces"]
    assert [r["number"] for r in rows] == list(range(1, len(rows) + 1))
    assert [r["index"] for r in rows] == sorted(r["index"] for r in rows)
    json.dumps(glue.report, allow_nan=False)


def test_repeat_runs_are_identical():
    a, b = glue_of(oblique_cells()), glue_of(oblique_cells())
    assert json.dumps(a.report) == json.dumps(b.report)
    ra, rb = checks_of(a), checks_of(b)
    assert ra["stl"] == rb["stl"]
    assert repr(ra["assembly"]) == repr(rb["assembly"])


# --- refusals ----------------------------------------------------------------------------


@pytest.mark.parametrize("name, value", [
    ("thickness_mm", True), ("thickness_mm", float("nan")),
    ("skin_mm", 0), ("clearance_mm", 0.0), ("clearance_mm", -0.2),
    ("clearance_mm", float("inf")), ("clearance_mm", False),
    ("min_piece_side_mm", 0), ("min_piece_side_mm", -1.0), ("min_piece_side_mm", True),
    ("opening_mm", 0), ("opening_mm", "0.4"), ("min_island_mm2", -0.1),
    ("min_island_mm2", True), ("min_island_mm2", float("nan")),
])
def test_refusals(name, value):
    with pytest.raises(GlueError, match=name):
        glue_of(SQUARE_CELLS, **{name: value})


def test_thickness_at_or_below_the_skin_is_refused():
    for t in (D, 0.5):
        with pytest.raises(GlueError, match="above skin_mm"):
            glue_of(SQUARE_CELLS, thickness_mm=t)


def test_refuses_non_cells_and_non_glue():
    with pytest.raises(GlueError, match="Cells"):
        glue_of("cells")
    with pytest.raises(ColorCheckError, match="Glue"):
        glue_fit_check(SQUARE_CELLS)
    with pytest.raises(ColorCheckError, match="Glue"):
        checks_of(None)


# --- quality review additions ------------------------------------------------------------


def test_glue_fit_boundary_probe():
    # Move the square's piece toward the x = 5 wall so its gap is just above, then just
    # below, the threshold.
    glue = glue_of(SQUARE_CELLS)
    fit = glue_fit_check(glue)
    gap, limit = fit.measured["min_gap_mm"], fit.threshold["min_gap_mm"]
    piece = glue.pieces[0]
    for step, status in ((gap - (limit + 1e-7), "PASS"), (gap - (limit - 1e-7), "FAIL")):
        moved = dataclasses.replace(piece, polygon=affinity.translate(piece.polygon, -step))
        probe = glue_fit_check(dataclasses.replace(glue, pieces=(moved,)))
        assert probe.status == status, (step, probe.measured["min_gap_mm"], limit)


def test_a_piece_in_a_pocket_of_another_color_fails_glue_fit():
    glue = glue_of(SQUARE_CELLS)
    other = dataclasses.replace(glue.pieces[0], index=2)
    fit = glue_fit_check(dataclasses.replace(glue, pieces=(other,)))
    assert fit.status == "FAIL"
    assert fit.measured["per_piece"][0]["same_color"] is False


def test_smallest_first_decides_which_label_survives():
    # X1 (color 2, 1.3 x 4 mm) and X2 (color 3, 1.4 x 4 mm) in a corner of S, side by
    # side. Alone, X1 shares most with X2 (4 mm against 1.3 mm of base) and X2 most with
    # the base (4 + 1.4 mm against 4 mm). X1 is smaller, so it folds first, into X2; the
    # 2.7 x 4 mm result keeps a piece, as color 3. Folding X2 first would have sent both
    # into the base.
    x1, x2 = shapely.box(0, 0, 1.3, 4), shapely.box(1.3, 0, 2.7, 4)
    glue = glue_of(cells_from({2: [x1], 3: [x2]}, S20))
    folds = glue.report["folds"]
    assert [(f["label"], f["into"]) for f in folds] == [(2, 3)]
    assert [p.index for p in glue.pockets] == [3]
    assert_all_pass(glue)


def test_a_nonzero_base_index():
    # Base color 2; color 0 a square inlay, color 1 a dot that folds into the base.
    dot = shapely.box(1, 1, 2, 2)
    cells = cells_from({0: [SQUARE], 1: [dot]}, S20, base=2)
    glue = glue_of(cells)
    assert glue.base_index == 2
    assert [(f["label"], f["into"], f["into_base"]) for f in glue.report["folds"]] == [
        (1, 2, True)]
    assert [b.name for b in glue.bodies] == ["base", "color-0"]
    assert glue.bodies[0].index == 2
    assert [p.index for p in glue.pockets] == [0]
    assert_all_pass(glue)


def test_glue_partition_fails_for_a_dropped_cell():
    glue = glue_of(SQUARE_CELLS)
    assert glue_partition_check(glue).status == "PASS"
    cells = glue.cells
    k = max(range(len(cells.cells)), key=lambda i: cells.cells[i].area)
    keep = [i for i in range(len(cells.cells)) if i != k]
    dropped = dataclasses.replace(cells, cells=tuple(cells.cells[i] for i in keep),
                                  labels=tuple(cells.labels[i] for i in keep))
    check = glue_partition_check(dataclasses.replace(glue, cells=dropped))
    assert check.status == "FAIL"
    assert check.measured["snap_silhouette_mm2"] > check.threshold["snap_silhouette_mm2"]


def test_glue_partition_fails_for_overlapping_pockets():
    glue = glue_of(SQUARE_CELLS)
    twin = dataclasses.replace(glue.pockets[0], number=2, pieces=())
    check = glue_partition_check(dataclasses.replace(glue, pockets=(glue.pockets[0], twin)))
    assert check.status == "FAIL"
    assert check.measured["overlap_mm2"] == pytest.approx(SQUARE.area)


def test_a_candidate_without_a_kept_piece_after_folding_is_refused(monkeypatch):
    # _fold never leaves one; with folding switched off, the tiny dot reaches step 4.
    monkeypatch.setattr(tdmg.color_glue, "_fold", lambda *args: [])
    with pytest.raises(GlueError, match="no piece of at least"):
        glue_of(cells_from({1: [shapely.box(9, 9, 10, 10)]}, S20))

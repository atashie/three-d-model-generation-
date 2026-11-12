"""AMS bodies (tdmg.color_geometry: storage grid, cells, prism mesher, ams_bodies) and their
checks (tdmg.color_checks).

docs/plans/2026-11-12-color-geometry.md, Decisions 6 (as amended during Task 4) and 9,
Task 4.
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

import tdmg.flat
from tdmg.checks import F1_CHECK_IDS, merge_exact, topology_checks
from tdmg.color_checks import (
    ColorCheckError,
    ams_checks,
    body_export_check,
    color_partition_check,
    filaments_check,
    partition_tolerance,
)
from tdmg.color_geometry import (
    PINCH_K,
    Body,
    Cells,
    ColorGeometryError,
    ColorRegions,
    ams_bodies,
    color_cells,
    color_regions,
    pinch_vertices,
    prism_mesh,
    storage_grid_mm,
    vertex_dist,
)
from tdmg.flat import QUAD_SEGS, encode_stl, to_model
from tdmg.profiles import load_printer
from tdmg.rules import load_rules

T = 3.0      # test thickness, mm (a test input)
SKIN = 0.6   # test skin depth, mm (the rule's current default; a test input here)


def image_box(width_px, height_px, width_mm):
    return to_model(shapely.box(0, 0, width_px, height_px), width_mm)


def plan(case):
    """A synthetic plan: (regions, S)."""
    if case == "box":
        fine = np.zeros((8, 8), np.uint8)
        fine[4:, :4] = 1
        fine[4:, 4:] = 2
        full, transform = image_box(8, 8, 8)
        s, silhouette, n = 1, full, 3
    elif case == "circle":  # an oblique S, supersample 2, a real scale
        fine = np.zeros((12, 16), np.uint8)
        fine[3:9, 2:7] = 1
        fine[5:12, 8:14] = 2
        full, transform = image_box(8, 6, 37.3)
        s, n = 2, 3
        silhouette = shapely.Point(18, 14).buffer(12, quad_segs=QUAD_SEGS).intersection(full)
    else:  # "checker": a four-color corner inside an S with rounded corners
        fine = np.kron(np.array([[0, 1], [2, 3]]), np.ones((5, 5))).astype(np.uint8)
        full, transform = image_box(10, 10, 23.7)
        s, n, silhouette = 1, 4, full.buffer(-1.3, quad_segs=QUAD_SEGS)
    regions = color_regions(fine, s, transform, silhouette, n_colors=n, base_index=0,
                            thin_width_mm=0.4)
    return regions, silhouette


def cells_of(case):
    regions, silhouette = plan(case)
    return color_cells(regions, silhouette, 0)


def bodies_of(case):
    cells = cells_of(case)
    return cells, ams_bodies(cells, thickness_mm=T, skin_mm=SKIN)


def stored(mesh):
    """The mesh as the gate sees it: STL bytes parsed back and merged exactly."""
    return merge_exact(trimesh.load(io.BytesIO(encode_stl(mesh)), file_type="stl",
                                    process=False))


def f1_failures(mesh):
    return [(c.id, c.measured) for c in topology_checks(stored(mesh)) if c.status != "PASS"]


def run_checks(cells, bodies, colors=3, cap=4):
    return ams_checks(bodies, cells, T, colors=colors, palette_cap=cap,
                      printer=load_printer("bambu-a1"), rules=load_rules())


CASES = ["box", "circle", "checker"]


# --- storage grid ------------------------------------------------------------------------


@pytest.mark.parametrize("value, grid", [
    (60.0, 2.0 ** -18), (63.999, 2.0 ** -18), (64.0, 2.0 ** -17), (1.0, 2.0 ** -23),
    (0.75, 2.0 ** -24), (300.0, 2.0 ** -15)])
def test_storage_grid_is_two_to_the_e_minus_24(value, grid):
    assert storage_grid_mm(value) == grid


@pytest.mark.parametrize("max_abs", [0.3, 8.0, 37.3, 60.0, 255.9, 1000.0])
def test_grid_multiples_below_two_to_the_e_are_float32_numbers(max_abs):
    g = storage_grid_mm(max_abs)
    e = math.frexp(max_abs)[1]
    assert max_abs < 2.0 ** e and g == 2.0 ** (e - 24)
    rng = np.random.default_rng(20261112)
    k = rng.integers(-(2 ** 24), 2 ** 24, size=20000, endpoint=True)
    k = np.concatenate([k, [2 ** 24, -(2 ** 24), 2 ** 24 - 1, 1, 0]])
    x = k.astype(np.float64) * g
    assert np.all(np.abs(x) <= 2.0 ** e)
    assert np.array_equal(x.astype(np.float32).astype(np.float64), x)
    # One step past 2^e needs 25 significant bits: not a float32 number.
    beyond = (2 ** 24 + 1) * g
    assert float(np.float32(beyond)) != beyond
    # And a model reaching 2^e gets the next grid, which is coarser.
    assert storage_grid_mm(2.0 ** e) == 2 * g


def test_storage_grid_at_the_ends_of_float32_range():
    # Top: max_abs below 2^127 gives G = 2^103, and every multiple up to 2^127 (k = 2^24)
    # is a finite float32. 2^127 itself would need G = 2^104, whose top point 2^128
    # overflows, so it is refused.
    top = float(np.nextafter(2.0 ** 127, 0))
    assert storage_grid_mm(top) == 2.0 ** 103
    k = np.array([2 ** 24, 2 ** 24 - 1, 1, -(2 ** 24)], dtype=np.float64)
    x = k * 2.0 ** 103
    with np.errstate(over="raise"):
        assert np.array_equal(x.astype(np.float32).astype(np.float64), x)
    with pytest.raises(ColorGeometryError, match="max_abs_coord"):
        storage_grid_mm(2.0 ** 127)
    # Bottom: G = 2^-149, the float32 subnormal step, is the finest grid.
    assert storage_grid_mm(2.0 ** -126) == 2.0 ** -149
    x = np.array([1, 3, 2 ** 23 + 1, 2 ** 24], dtype=np.float64) * 2.0 ** -149
    assert np.array_equal(x.astype(np.float32).astype(np.float64), x)
    with pytest.raises(ColorGeometryError, match="max_abs_coord"):
        storage_grid_mm(2.0 ** -127)


@pytest.mark.parametrize("value", [0, -1.0, math.nan, math.inf, True, "1", 2.0 ** 200,
                                   1e-300])
def test_storage_grid_refusals(value):
    with pytest.raises(ColorGeometryError, match="max_abs_coord"):
        storage_grid_mm(value)


# --- cells -------------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES)
def test_cells_are_on_the_grid_and_tile_the_gridded_s(case):
    regions, silhouette = plan(case)
    cells = color_cells(regions, silhouette, 0)
    g = cells.grid_mm
    xy = np.concatenate([shapely.get_coordinates(c) for c in cells.cells])
    assert g == storage_grid_mm(np.abs(np.concatenate(
        [shapely.get_coordinates(silhouette)]
        + [shapely.get_coordinates(p) for ps in regions.inlays.values() for p in ps]
        + [shapely.get_coordinates(p) for p in regions.base_top])).max())
    assert np.array_equal(np.round(xy / g) * g, xy)
    assert np.array_equal(xy.astype(np.float32).astype(np.float64), xy)
    assert all(c.is_valid and c.area > 0 for c in cells.cells)
    assert len(cells.labels) == len(cells.cells)
    assert shapely.symmetric_difference(shapely.union_all(list(cells.cells)),
                                        cells.silhouette).area == 0.0
    assert set(cells.labels) == {0, *regions.inlays}


def test_box_cells_are_exact():
    regions, silhouette = plan("box")
    cells = color_cells(regions, silhouette, 0)
    assert cells.report["silhouette_shift_mm2"] == 0.0
    assert cells.report["relabelled_mm2"] == 0.0
    assert all(c["shift_mm2"] == 0.0 for c in cells.report["colors"])
    assert sorted(cells.labels) == [0, 1, 2]
    assert [c.area for c in cells.of(1)] == [16.0]


@pytest.mark.parametrize("case", ["circle", "checker"])
def test_grid_shift_is_reported_and_within_the_snap_bound(case):
    # Snap-rounding moves each boundary point by at most half a grid diagonal, G sqrt(2)/2,
    # so an area changes by at most about its perimeter x that (a check on the report).
    regions, silhouette = plan(case)
    cells = color_cells(regions, silhouette, 0)
    half = cells.grid_mm * math.sqrt(2) / 2
    report = cells.report
    assert 0 < report["silhouette_shift_mm2"] <= silhouette.length * half
    pieces = {0: list(regions.base_top)} | {c: list(p) for c, p in regions.inlays.items()}
    for entry in report["colors"]:
        own = shapely.union_all(pieces[entry["index"]])
        assert entry["shift_mm2"] <= (own.length + silhouette.length) * half
        assert entry["cells"] == len(cells.of(entry["index"]))
    json.dumps(report, allow_nan=False)


def test_a_sub_grid_sliver_is_absorbed_not_a_cell():
    # A base-top part far below one grid cell, along an inlay edge, is absorbed by the
    # snap-rounded noding: it is not a cell of its own. Built by hand so it does not
    # depend on GEOS rounding. (The test first used a sliver that color_regions left
    # between a polygonal circle S and a color edge, 1.1e-16 mm^2 on Windows and Linux;
    # on macOS arm64 that rounding differs, likely by fused multiply-adds, and no sliver
    # arose, so the precondition failed there.) The sliver is a triangle on x = 5 with
    # its apex 2^-49 mm to the left: every coordinate is a float64 number, its area is
    # 3 x 2^-49 (5.3e-15 mm^2), and the grid here is 2^-20 mm.
    s = shapely.box(0, 0, 10, 10)
    apex = 5 - 2.0 ** -49
    sliver = shapely.Polygon([(5, 2), (5, 8), (apex, 5)])
    inlay = shapely.Polygon([(0, 0), (5, 0), (5, 2), (apex, 5), (5, 8), (5, 10), (0, 10)])
    regions = ColorRegions({1: [inlay]}, [shapely.box(5, 0, 10, 10), sliver], {}, [])
    assert min(p.area for p in regions.base_top) < 1e-12
    cells = color_cells(regions, s, 0, fix_pinches=False)  # no diamond cells
    assert cells.grid_mm == 2.0 ** -20
    assert min(c.area for c in cells.cells) > 1.0
    assert len(cells.cells) == sum(len(p) for p in regions.inlays.values()) + 1
    assert sorted(cells.labels) == [0, 1]


def tiny_tip_regions():
    """Two inlay tips cut off at vertices of an oblique (polygonal circle) S edge.

    Each tip is S beyond a chord perpendicular to the vertex's bisector at depth delta.
    S's interior angle there is 180 - 360/32 degrees (QUAD_SEGS 8), so a tip's area is
    delta^2 x tan(84.375 deg), about 10.2 delta^2: 7e-7 and 2e-5 mm^2 for the depths
    below.
    """
    silhouette = shapely.Point(0, 0).buffer(10, quad_segs=QUAD_SEGS)
    xy = shapely.get_coordinates(silhouette.exterior)[:-1]
    tips = []
    for vertex, delta in ((xy[3], math.sqrt(7e-7 / 10.2)), (xy[11], math.sqrt(2e-5 / 10.2))):
        u = vertex / np.linalg.norm(vertex)  # outward bisector at this vertex
        w = np.array([-u[1], u[0]])
        c = vertex - delta * u
        cut = shapely.Polygon([c - 5 * w, c + 5 * w, c + 5 * w + 5 * u, c - 5 * w + 5 * u])
        tips.append(shapely.intersection(silhouette, cut))
    base = shapely.difference(silhouette, shapely.union_all(tips))
    return ColorRegions({1: [tips[0]], 2: [tips[1]]}, [base], {}, []), silhouette


def test_tiny_tips_at_an_oblique_edge_become_cells_and_pass():
    # Task 4 (added in the Task 3 quality review): sub-micron parts from clipping by an
    # oblique S. A part this small still makes its color a body, so it counts as one
    # filament in F4.filaments.
    regions, silhouette = tiny_tip_regions()
    areas = [p.area for c in (1, 2) for p in regions.inlays[c]]
    assert 6e-7 < areas[0] < 8e-7 and 1.8e-5 < areas[1] < 2.2e-5
    cells = color_cells(regions, silhouette, 0)
    for c, area in zip((1, 2), areas, strict=True):
        (cell,) = cells.of(c)
        assert cell.area == pytest.approx(area, rel=0.05)
    bodies = ams_bodies(cells, thickness_mm=T, skin_mm=SKIN)
    result = run_checks(cells, bodies, colors=3, cap=4)
    for name, checks in result["bodies"].items():
        assert {c.status for c in checks} == {"PASS"}, name
    status = {c.id: c for c in result["assembly"]}
    assert status["F4.color_partition"].status == "PASS"
    assert status["F4.filaments"].measured == 3
    assert filaments_check(bodies, colors=2, palette_cap=4).status == "FAIL"


def test_repeat_cells_are_identical():
    a, b = cells_of("circle"), cells_of("circle")
    assert [c.wkb for c in a.cells] == [c.wkb for c in b.cells]
    assert a.labels == b.labels and a.report == b.report


@pytest.mark.parametrize("args, name", [
    ({"base_index": True}, "base_index"),
    ({"base_index": 1}, "base_index"),
    ({"base_index": -1}, "base_index"),
    ({"regions": {}}, "regions"),
    ({"silhouette": shapely.Polygon()}, "silhouette"),
])
def test_color_cells_refusals(args, name):
    regions, silhouette = plan("box")
    full = {"regions": regions, "silhouette": silhouette, "base_index": 0} | args
    with pytest.raises(ColorGeometryError, match=name):
        color_cells(full["regions"], full["silhouette"], full["base_index"])


# --- prism mesher --------------------------------------------------------------------------


def assert_closed(mesh, volume):
    assert f1_failures(mesh) == []
    assert mesh.is_watertight
    assert mesh.volume == pytest.approx(volume, rel=1e-12)


def test_two_by_two_checker_of_heights_is_closed():
    cells = [shapely.box(0, 1, 1, 2), shapely.box(1, 1, 2, 2), shapely.box(1, 0, 2, 1),
             shapely.box(0, 0, 1, 1)]  # clockwise from the top left
    mesh = prism_mesh(cells, [(0, 1), (0, 2), (0, 3), (0, 4)])
    assert_closed(mesh, 10.0)
    # Different bottoms too: every pair of neighbours overlaps in z.
    mesh = prism_mesh(cells, [(0, 1), (0.5, 2), (0.25, 3), (0, 4)])
    assert_closed(mesh, 1 + 1.5 + 2.75 + 4)


def test_two_level_checker_is_non_manifold_and_f1_reports_it():
    # Diagonal cells that are both taller than the cells between them touch along one
    # vertical edge: the geometry is non-manifold, whatever the mesher does.
    cells = [shapely.box(0, 1, 1, 2), shapely.box(1, 1, 2, 2), shapely.box(1, 0, 2, 1),
             shapely.box(0, 0, 1, 1)]
    failures = dict(f1_failures(prism_mesh(cells, [(0, 2), (0, 1), (0, 2), (0, 1)])))
    assert failures["F1.edge_manifold"]["overfull_edges"] == 1


def test_l_shape_alone_and_split_into_two_heights():
    ell = shapely.Polygon([(0, 0), (3, 0), (3, 1), (1, 1), (1, 3), (0, 3)])
    assert_closed(prism_mesh([ell], [(0, 2)]), 5 * 2)
    a = shapely.Polygon([(0, 0), (1, 0), (1, 1), (1, 3), (0, 3)])  # (1, 1) shared
    b = shapely.Polygon([(1, 0), (3, 0), (3, 1), (1, 1)])
    assert_closed(prism_mesh([a, b], [(0, 2), (0, 0.5)]), 3 * 2 + 2 * 0.5)


def test_polygon_with_a_hole_and_with_an_island_in_it():
    ring = shapely.box(0, 0, 4, 4).difference(shapely.box(1, 1, 3, 3))
    assert_closed(prism_mesh([ring], [(0, 1)]), 12.0)
    island = shapely.box(1, 1, 3, 3)
    assert_closed(prism_mesh([ring, island], [(0, 1), (0, 2.5)]), 12 + 4 * 2.5)
    assert_closed(prism_mesh([island, ring], [(0.5, 2.5), (0, 1)]), 12 + 4 * 2.0)


def test_three_cells_meeting_the_outline_at_one_point():
    # A, B and C meet at P = (1, 0) on the outline, each at its own height: the outer
    # walls at P and the steps between the cells must share the vertical edges at P.
    a = shapely.Polygon([(0, 0), (1, 0), (0, 2)])
    b = shapely.Polygon([(1, 0), (2, 2), (0, 2)])
    c = shapely.Polygon([(1, 0), (2, 0), (2, 2)])
    mesh = prism_mesh([a, b, c], [(0, 1), (0, 2), (0, 3)])
    assert_closed(mesh, a.area * 1 + b.area * 2 + c.area * 3)
    v = np.asarray(mesh.vertices)
    at_p = sorted(v[(v[:, 0] == 1) & (v[:, 1] == 0), 2].tolist())
    assert at_p == [0, 1, 2, 3]


def test_cell_order_changes_the_numbering_not_the_solid():
    a = shapely.box(0, 0, 1, 1)
    b = shapely.box(1, 0, 2, 1)
    m1 = prism_mesh([a, b], [(0, 1), (0, 2)])
    m2 = prism_mesh([b, a], [(0, 2), (0, 1)])
    assert m1.volume == m2.volume == 3.0
    assert sorted(map(tuple, m1.vertices.tolist())) == sorted(map(tuple, m2.vertices.tolist()))
    assert encode_stl(prism_mesh([a, b], [(0, 1), (0, 2)])) == encode_stl(m1)


def random_cells(rng, n_points, grid):
    """Voronoi cells of random grid points in a 40 mm box, noded on the grid, some dropped.

    Voronoi vertices join three cells, so no two cells meet only at a point (the case
    test_two_level_checker_is_non_manifold_and_f1_reports_it covers).
    """
    pts = shapely.multipoints(np.round(rng.uniform(0, 40, (n_points, 2)) / grid) * grid)
    box = shapely.box(0, 0, 40, 40)
    regions = [r.intersection(box) for r in shapely.get_parts(
        shapely.voronoi_polygons(pts, extend_to=box))]
    lines = shapely.union_all([shapely.boundary(r) for r in regions], grid_size=grid)
    faces = [f for f in shapely.get_parts(shapely.polygonize(shapely.get_parts(lines)))
             if f.area > 0]
    keep = rng.random(len(faces)) > 0.2
    return [f for f, k in zip(faces, keep, strict=True) if k]


def test_random_grid_cells_are_always_closed_after_stl_storage():
    rng = np.random.default_rng(20261112)
    grid = storage_grid_mm(40.0)
    for _ in range(12):
        cells = random_cells(rng, int(rng.integers(5, 40)), grid)
        # Every range contains [0.5, 1], so neighbours always overlap in z.
        ranges = [(float(rng.choice([0.0, 0.5])), float(rng.choice([1.0, 2.0, 3.0])))
                  for _ in cells]
        mesh = prism_mesh(cells, ranges)
        expected = sum(c.area * (hi - lo) for c, (lo, hi) in zip(cells, ranges,
                                                                 strict=True))
        assert f1_failures(mesh) == []
        assert mesh.volume == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize("cells, ranges, match", [
    ([], [], "at least one cell"),
    ([shapely.box(0, 0, 1, 1)], [(0, 1), (0, 2)], "one \\(lo, hi\\) per cell"),
    ([shapely.box(0, 0, 1, 1)], [(1, 1)], "lo < hi"),
    ([shapely.box(0, 0, 1, 1)], [(0, math.inf)], "lo < hi"),
    ([shapely.Polygon()], [(0, 1)], "valid, non-empty Polygon"),
    ([shapely.box(0, 0, 1, 1), shapely.box(0, 0, 1, 1)], [(0, 1), (0, 1)], "overlap"),
])
def test_prism_mesh_refusals(cells, ranges, match):
    with pytest.raises(ColorGeometryError, match=match):
        prism_mesh(cells, ranges)


# --- bodies -----------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES)
def test_bodies_are_base_then_inlays_by_index(case):
    cells, bodies = bodies_of(case)
    n = 4 if case == "checker" else 3
    assert [b.name for b in bodies] == ["base"] + [f"color-{i}" for i in range(1, n)]
    assert [b.index for b in bodies] == list(range(n))
    assert all(isinstance(b, Body) for b in bodies)
    assert bodies[0].z_range_mm == (0.0, T)
    assert all(b.z_range_mm == (T - SKIN, T) for b in bodies[1:])
    assert bodies[0].parts == cells.cells
    for b in bodies[1:]:
        assert list(b.parts) == cells.of(b.index)
        assert b.mesh.vertices.dtype == np.float64


@pytest.mark.parametrize("case", CASES)
def test_each_body_passes_f1_and_its_export_check(case):
    _, bodies = bodies_of(case)
    for body in bodies:
        mesh = stored(body.mesh)
        checks = topology_checks(mesh) + [body_export_check(mesh, body)]
        assert {c.id for c in checks} == F1_CHECK_IDS | {"F2.export_matches_geometry"}
        assert {c.status for c in checks} == {"PASS"}, [c for c in checks
                                                        if c.status != "PASS"]


@pytest.mark.parametrize("case", CASES)
def test_body_volumes_sum_to_area_times_thickness(case):
    cells, bodies = bodies_of(case)
    area_tol, _ = partition_tolerance(cells)
    expected = cells.silhouette.area * T
    assert abs(sum(b.expected_volume_mm3 for b in bodies) - expected) <= area_tol * T
    for b in bodies:  # the float64 meshes, before STL storage
        assert b.mesh.volume == pytest.approx(b.expected_volume_mm3, rel=1e-12)


@pytest.mark.parametrize("case", CASES)
def test_surface_is_the_meshes_area(case):
    _, bodies = bodies_of(case)
    for b in bodies:
        assert b.surface_mm2 == pytest.approx(b.mesh.area, rel=1e-12)


@pytest.mark.parametrize("case", CASES)
def test_the_base_is_one_body_when_s_is_connected(case):
    _, silhouette = plan(case)
    assert isinstance(silhouette, shapely.Polygon)
    _, bodies = bodies_of(case)
    assert len(bodies[0].mesh.split(only_watertight=False)) == 1


def test_base_expected_volume_and_slabs():
    cells, bodies = bodies_of("box")
    base = bodies[0]
    top = sum(c.area for c in cells.of(0))
    assert base.expected_volume_mm3 == pytest.approx(
        cells.silhouette.area * (T - SKIN) + top * SKIN)
    assert [(z0, z1) for _, z0, z1 in base.slabs] == [(0.0, T - SKIN), (0.0, T)]
    assert list(base.slabs[1][0]) == cells.of(0)


def test_no_base_top_gives_a_plain_slab():
    full, _ = image_box(4, 4, 4)
    cells = color_cells(ColorRegions({1: [full]}, [], {}, []), full, 0)
    base, inlay = ams_bodies(cells, thickness_mm=T, skin_mm=SKIN)
    assert [z for _, *z in base.slabs] == [[0.0, T - SKIN]]
    assert base.z_range_mm == (0.0, T - SKIN)
    assert base.mesh.bounds.tolist() == [[0, 0, 0], [4, 4, T - SKIN]]
    assert inlay.mesh.bounds.tolist() == [[0, 0, T - SKIN], [4, 4, T]]


def test_inlay_and_base_share_exact_z_values():
    _, bodies = bodies_of("circle")
    assert set(np.unique(bodies[0].mesh.vertices[:, 2]).tolist()) == {0.0, T - SKIN, T}
    for b in bodies[1:]:
        assert set(np.unique(b.mesh.vertices[:, 2]).tolist()) == {T - SKIN, T}


def test_inlay_and_base_share_their_xy_vertices():
    _, bodies = bodies_of("circle")
    base = {tuple(v) for v in bodies[0].mesh.vertices[:, :2].tolist()}
    for b in bodies[1:]:
        assert {tuple(v) for v in b.mesh.vertices[:, :2].tolist()} <= base


def pinches_of(cells):
    return pinch_vertices(cells.cells, cells.labels, grid_mm=cells.grid_mm)


def kron_case():
    """Color 1's two squares touch at one pixel corner inside an oblique S."""
    fine = np.kron(np.array([[0, 1, 2], [2, 3, 1]]), np.ones((5, 5))).astype(np.uint8)
    full, transform = image_box(15, 10, 41.9)
    silhouette = shapely.Point(20, 14).buffer(13, quad_segs=QUAD_SEGS).intersection(full)
    regions = color_regions(fine, 1, transform, silhouette, n_colors=4, base_index=0,
                            thin_width_mm=0.4)
    return regions, silhouette


def assert_pinch_free_and_closed(cells, bodies=None):
    assert pinches_of(cells) == []
    bodies = bodies or ams_bodies(cells, thickness_mm=T, skin_mm=SKIN)
    for b in bodies:
        assert f1_failures(b.mesh) == [], b.name
    assert color_partition_check(cells, bodies, T).status == "PASS"
    return bodies


def assert_moved_within_diamonds(cells):
    report = cells.report["pinches"]
    radius = PINCH_K * cells.grid_mm
    assert report["radius_mm"] == radius
    assert 0 < report["area_moved_mm2"] <= report["fixed"] * 2 * radius ** 2
    assert report["area_moved_mm2"] == pytest.approx(
        sum(c["area_moved_mm2"] for c in report["colors"]))
    assert report["fixed"] == sum(c["fixed"] for c in report["colors"])


def test_pinch_vertices_finds_a_corner_contact():
    regions, silhouette = kron_case()
    cells = color_cells(regions, silhouette, 0, fix_pinches=False)
    found = pinches_of(cells)
    assert [labels for _, labels in found] == [[1]]


def test_corner_contact_is_joined_and_every_body_passes_f1():
    regions, silhouette = kron_case()
    cells = color_cells(regions, silhouette, 0)
    report = cells.report["pinches"]
    assert report["fixed"] == 1
    assert [(c["index"], c["fixed"]) for c in report["colors"]] == [(1, 1)]
    assert_moved_within_diamonds(cells)
    assert_pinch_free_and_closed(cells)
    # Color 1 is now one piece; nothing else changed beyond the diamond.
    assert len(shapely.get_parts(shapely.union_all(cells.of(1)))) == 1
    json.dumps(cells.report, allow_nan=False)


def test_pinch_on_the_outline_is_joined():
    # A and C (color 1) touch at P = (2, 0) on S's lower edge, with the base cell B
    # between them above P and outside S below it.
    a = shapely.Polygon([(0, 0), (2, 0), (0, 2)])
    c = shapely.Polygon([(2, 0), (4, 0), (4, 2)])
    b = shapely.Polygon([(2, 0), (4, 2), (0, 2)])
    silhouette = shapely.box(0, 0, 4, 2)
    regions = ColorRegions({1: [a, c]}, [b], {}, [])
    before = color_cells(regions, silhouette, 0, fix_pinches=False)
    assert [labels for _, labels in pinches_of(before)] == [[1]]
    cells = color_cells(regions, silhouette, 0)
    assert cells.report["pinches"]["fixed"] == 1
    assert_moved_within_diamonds(cells)
    assert_pinch_free_and_closed(cells)
    assert shapely.union_all(list(cells.cells)).equals(silhouette)


def test_two_labels_pinching_at_one_vertex_lowest_wins():
    tl, tr = shapely.box(0, 1, 1, 2), shapely.box(1, 1, 2, 2)
    br, bl = shapely.box(1, 0, 2, 1), shapely.box(0, 0, 1, 1)
    regions = ColorRegions({1: [tl, br], 2: [tr, bl]}, [], {}, [])
    silhouette = shapely.box(0, 0, 2, 2)
    before = color_cells(regions, silhouette, 0, fix_pinches=False)
    assert [labels for _, labels in pinches_of(before)] == [
        [1, 2]]
    cells = color_cells(regions, silhouette, 0)
    report = cells.report["pinches"]
    assert report["fixed"] == 1
    assert [(c["index"], c["fixed"]) for c in report["colors"]] == [(1, 1)]
    assert_moved_within_diamonds(cells)
    assert_pinch_free_and_closed(cells)
    assert len(shapely.get_parts(shapely.union_all(cells.of(1)))) == 1
    assert len(shapely.get_parts(shapely.union_all(cells.of(2)))) == 2


@pytest.mark.parametrize("case", CASES)
def test_no_pinch_leaves_the_cells_unchanged(case):
    regions, silhouette = plan(case)
    fixed = color_cells(regions, silhouette, 0)
    plain = color_cells(regions, silhouette, 0, fix_pinches=False)
    assert fixed.report["pinches"]["fixed"] == 0
    assert fixed.report["pinches"]["rounds"] == 0
    assert [c.wkb for c in fixed.cells] == [c.wkb for c in plain.cells]
    assert fixed.labels == plain.labels
    assert {k: v for k, v in fixed.report.items() if k != "pinches"} == {
        k: v for k, v in plain.report.items() if k != "pinches"}


def test_pinches_that_do_not_converge_are_refused(monkeypatch):
    import tdmg.color_geometry as cg
    monkeypatch.setattr(cg, "PINCH_ROUNDS", 0)
    regions, silhouette = kron_case()
    with pytest.raises(ColorGeometryError, match="pinch"):
        color_cells(regions, silhouette, 0)


@pytest.mark.parametrize("k", [1, 2, 3, 4])
def test_pinch_fix_k(monkeypatch, k):
    # PINCH_K is a numerical choice (its comment derives K > 1). K = 1 leaves pinches on
    # some of these maps, so color_cells refuses them; every K from 2 up joins them all.
    import tdmg.color_geometry as cg
    assert PINCH_K == 2
    monkeypatch.setattr(cg, "PINCH_K", k)
    rng = np.random.default_rng(12345)
    cases = [kron_case()] + [random_fine_case(rng) for _ in range(60)]
    refused = 0
    for regions, silhouette in cases:
        try:
            cells = color_cells(regions, silhouette, 0)
        except ColorGeometryError as exc:
            assert "pinch" in str(exc)
            refused += 1
            continue
        assert cells.report["pinches"]["radius_mm"] == k * cells.grid_mm
        assert cells.report["pinches"]["rounds"] <= 1
        assert_pinch_free_and_closed(cells)
    assert (refused > 0) == (k == 1)


def random_fine_case(rng):
    """A checkerboard-ish fine map (many corner contacts) in a box or an oblique S."""
    h, w = (int(v) for v in rng.integers(3, 9, 2))
    n = int(rng.integers(2, 5))
    fine = rng.integers(0, n, (h, w)).astype(np.uint8)
    s = int(rng.choice([1, 2]))
    fine = np.kron(fine, np.ones((s, s), np.uint8))
    full, transform = image_box(w, h, float(rng.uniform(5, 60)))
    if rng.random() < 0.5:
        silhouette = full
    else:
        x0, y0, x1, y1 = full.bounds
        silhouette = shapely.Point((x0 + x1) / 2, (y0 + y1) / 2).buffer(
            0.45 * max(x1 - x0, y1 - y0), quad_segs=QUAD_SEGS).intersection(full)
    regions = color_regions(fine, s, transform, silhouette, n_colors=n, base_index=0,
                            thin_width_mm=0.4)
    return regions, silhouette


def test_random_checkerboard_maps_are_pinch_free_and_closed_after_stl_storage():
    rng = np.random.default_rng(20261112)
    fixed = 0
    for _ in range(25):
        regions, silhouette = random_fine_case(rng)
        cells = color_cells(regions, silhouette, 0)
        fixed += cells.report["pinches"]["fixed"]
        if cells.report["pinches"]["fixed"]:
            assert_moved_within_diamonds(cells)
        assert_pinch_free_and_closed(cells)
    assert fixed > 10  # the maps did force corner contacts


def test_repeat_bodies_are_identical():
    _, first = bodies_of("circle")
    _, second = bodies_of("circle")
    for a, b in zip(first, second, strict=True):
        assert encode_stl(a.mesh) == encode_stl(b.mesh)


@pytest.mark.parametrize("changes, name", [
    ({"thickness_mm": 0.6}, "thickness_mm"),
    ({"thickness_mm": 0.5}, "thickness_mm"),
    ({"thickness_mm": True}, "thickness_mm"),
    ({"thickness_mm": math.nan}, "thickness_mm"),
    ({"thickness_mm": math.inf}, "thickness_mm"),
    ({"thickness_mm": 0.0}, "thickness_mm"),
    ({"skin_mm": True}, "skin_mm"),
    ({"skin_mm": -0.1}, "skin_mm"),
    ({"skin_mm": math.nan}, "skin_mm"),
    ({"skin_mm": 0}, "skin_mm"),
])
def test_ams_bodies_refusals(changes, name):
    cells = cells_of("box")
    args = {"thickness_mm": T, "skin_mm": SKIN} | changes
    with pytest.raises(ColorGeometryError, match=name):
        ams_bodies(cells, **args)


def test_ams_bodies_refuses_a_non_cells_argument():
    regions, _ = plan("box")
    with pytest.raises(ColorGeometryError, match="cells"):
        ams_bodies(regions, thickness_mm=T, skin_mm=SKIN)


# --- F4.color_partition ------------------------------------------------------------------


def with_cells(cells, new_cells, new_labels):
    return dataclasses.replace(cells, cells=tuple(new_cells), labels=tuple(new_labels))


@pytest.mark.parametrize("case", CASES)
def test_partition_passes_on_the_cells(case):
    cells, bodies = bodies_of(case)
    check = color_partition_check(cells, bodies, T)
    assert (check.id, check.status, check.rule) == ("F4.color_partition", "PASS", None)
    assert check.measured["overlap_mm2"] == 0.0
    assert check.measured["symmetric_difference_mm2"] == 0.0
    assert check.measured["grid_shift"]["grid_mm"] == cells.grid_mm
    assert check.measured["grid_shift"]["colors"] == cells.report["colors"]
    assert "derived" in check.note and "information" in check.note
    json.dumps(check.as_dict(), allow_nan=False)


def test_partition_tolerance_is_perimeters_times_vertex_dist():
    cells = cells_of("circle")
    tol, dist = partition_tolerance(cells)
    assert dist == vertex_dist([cells.silhouette, *cells.cells])
    perimeter = sum(c.length for c in cells.cells) + cells.silhouette.length
    assert tol == pytest.approx(perimeter * dist)


@pytest.mark.parametrize("case", CASES)
def test_an_inlay_moved_by_10_microns_fails_partition_with_overlap_and_gap(case):
    cells, bodies = bodies_of(case)
    # Toward S's middle in x, so the moved inlay runs into a neighbour.
    toward = math.copysign(0.01, cells.silhouette.centroid.x
                           - shapely.union_all(cells.of(1)).centroid.x)
    moved = [affinity.translate(c, toward, 0) if k == 1 else c
             for c, k in zip(cells.cells, cells.labels, strict=True)]
    check = color_partition_check(with_cells(cells, moved, cells.labels), bodies, T)
    assert check.status == "FAIL"
    tol = check.threshold["area_tol_mm2"]
    assert check.measured["overlap_mm2"] > tol
    assert check.measured["gap_mm2"] > tol


@pytest.mark.parametrize("case", CASES)
def test_a_deleted_region_fails_partition_with_a_gap(case):
    cells, bodies = bodies_of(case)
    kept = [(c, k) for c, k in zip(cells.cells, cells.labels, strict=True) if k != 2]
    check = color_partition_check(with_cells(cells, *zip(*kept, strict=True)), bodies, T)
    assert check.status == "FAIL"
    assert check.measured["gap_mm2"] > check.threshold["area_tol_mm2"]
    assert check.measured["overlap_mm2"] <= check.threshold["area_tol_mm2"]


def test_a_volume_mismatch_alone_fails_partition():
    cells, bodies = bodies_of("box")
    wrong = dataclasses.replace(bodies[0],
                                expected_volume_mm3=bodies[0].expected_volume_mm3 + 0.01)
    check = color_partition_check(cells, [wrong, *bodies[1:]], T)
    assert check.status == "FAIL"
    assert check.measured["volume_error_mm3"] > check.threshold["volume_tol_mm3"]
    assert check.measured["overlap_mm2"] == check.measured["gap_mm2"] == 0.0


def manual_cells(silhouette, boxes, labels, base_index=0):
    """Cells built by hand, already on the grid: the raw inputs are the cells themselves."""
    grid = storage_grid_mm(float(np.abs(shapely.get_coordinates(silhouette)).max()))
    return Cells(grid, silhouette, tuple(boxes), tuple(labels), base_index, {},
                 silhouette, tuple(zip(labels, boxes, strict=True)), ())


@pytest.mark.parametrize("inlay, base_top, what, area", [
    (shapely.box(0, 0, 2, 2), shapely.box(2.5, 0, 4, 2), "raw_gap_mm2", 1.0),
    (shapely.box(0, 0, 3, 2), shapely.box(2, 0, 4, 2), "raw_overlap_mm2", 2.0),
])
def test_a_hole_or_an_overlap_in_the_regions_fails_partition(inlay, base_top, what, area):
    # The cells of such regions tile their own union, so only a check against the raw
    # inputs can see the 1 mm^2 hole (x from 2 to 2.5) or the 2 mm^2 overlap (x from 2
    # to 3).
    silhouette = shapely.box(0, 0, 4, 2)
    cells = color_cells(ColorRegions({1: [inlay]}, [base_top], {}, []), silhouette, 0)
    bodies = ams_bodies(cells, thickness_mm=T, skin_mm=SKIN)
    check = color_partition_check(cells, bodies, T)
    assert check.status == "FAIL"
    assert check.measured[what] == pytest.approx(area)
    assert check.measured[what] > check.threshold["raw_area_tol_mm2"]
    # The cells themselves tile their union, so the cell-level measures are 0.
    assert check.measured["overlap_mm2"] == check.measured["symmetric_difference_mm2"] == 0


def test_a_hole_also_fails_the_snap_and_volume_bounds():
    silhouette = shapely.box(0, 0, 4, 2)
    regions = ColorRegions({1: [shapely.box(0, 0, 2, 2)]}, [shapely.box(2.5, 0, 4, 2)],
                           {}, [])
    cells = color_cells(regions, silhouette, 0)
    check = color_partition_check(cells, ams_bodies(cells, thickness_mm=T, skin_mm=SKIN), T)
    assert check.measured["snap_silhouette_mm2"] == pytest.approx(1.0)
    assert check.measured["snap_silhouette_mm2"] > check.threshold["snap_silhouette_mm2"]
    assert check.measured["volume_error_mm3"] == pytest.approx(1.0 * T)
    assert check.measured["volume_error_mm3"] > check.threshold["volume_tol_mm3"]


@pytest.mark.parametrize("case", CASES)
def test_partition_snap_bounds_are_the_tube_around_the_raw_boundary(case):
    regions, silhouette = plan(case)
    cells = color_cells(regions, silhouette, 0)
    check = color_partition_check(cells, ams_bodies(cells, thickness_mm=T, skin_mm=SKIN),
                                  T)
    d = cells.grid_mm * math.sqrt(2) / 2
    vertices = sum(len(r.coords) - 1 for r in (silhouette.exterior, *silhouette.interiors))
    assert check.threshold["snap_move_mm"] == d
    assert check.threshold["snap_silhouette_mm2"] == pytest.approx(
        2 * d * silhouette.length + vertices * math.pi * d ** 2)
    assert check.measured["snap_silhouette_mm2"] <= check.threshold["snap_silhouette_mm2"]
    for entry in check.measured["snap_colors"]:
        assert entry["mm2"] <= entry["bound_mm2"]
    assert check.measured["raw_overlap_mm2"] == check.measured["raw_gap_mm2"] == 0.0


def test_partition_snap_bound_includes_the_pinch_diamonds():
    regions, silhouette = kron_case()
    cells = color_cells(regions, silhouette, 0)
    assert cells.report["pinches"]["fixed"] == 1
    (fix,) = cells.pinch_fixes
    assert fix["label"] == 1 and fix["losers"] and not fix["clipped"]
    check = color_partition_check(cells, ams_bodies(cells, thickness_mm=T, skin_mm=SKIN),
                                  T)
    assert check.status == "PASS"
    bounds = {e["index"]: e for e in check.measured["snap_colors"]}
    for label in [1, *fix["losers"]]:
        assert bounds[label]["pinch_mm2"] == fix["bound_mm2"]
    assert fix["bound_mm2"] >= 2 * (PINCH_K * cells.grid_mm) ** 2


def test_partition_overlap_uses_a_tree_on_many_pieces():
    # 2,500 unit cells tiling a 50 x 50 S, then one extra cell overlapping its neighbour.
    boxes = [shapely.box(i, j, i + 1, j + 1) for i in range(50) for j in range(50)]
    silhouette = shapely.box(0, 0, 50, 50)
    labels = [1] * 1250 + [0] * 1250
    good = manual_cells(silhouette, boxes, labels)
    bodies = ams_bodies(good, thickness_mm=T, skin_mm=SKIN)
    assert color_partition_check(good, bodies, T).status == "PASS"
    bad = with_cells(good, [*boxes, shapely.box(0.5, 0, 1.5, 1)], [*labels, 1])
    check = color_partition_check(bad, bodies, T)
    assert check.status == "FAIL"
    assert check.measured["overlap_mm2"] == pytest.approx(1.0)


def test_partition_refuses_a_non_cells_argument():
    regions, _ = plan("box")
    with pytest.raises(ValueError, match="cells"):
        color_partition_check(regions, [], T)


# --- F4.filaments ----------------------------------------------------------------------


def five_cells():
    boxes = [shapely.box(i, 0, i + 1, 1) for i in range(5)]
    return manual_cells(shapely.box(0, 0, 5, 1), boxes, (0, 1, 2, 3, 4))


def five_bodies():
    return ams_bodies(five_cells(), thickness_mm=T, skin_mm=SKIN)


def test_five_bodies_fail_filaments_at_four():
    check = filaments_check(five_bodies(), colors=4, palette_cap=4)
    assert (check.id, check.status, check.measured, check.threshold) == (
        "F4.filaments", "FAIL", 5, 4)
    assert "palette_cap" in check.note and "colors" in check.note


def test_four_bodies_pass_filaments():
    check = filaments_check(five_bodies()[:4], colors=4, palette_cap=4)
    assert (check.status, check.measured, check.threshold) == ("PASS", 4, 4)


def test_filaments_threshold_is_the_smaller_limit():
    bodies = five_bodies()[:4]
    assert filaments_check(bodies, colors=3, palette_cap=4).status == "FAIL"
    assert filaments_check(bodies, colors=5, palette_cap=3).status == "FAIL"
    assert filaments_check(bodies, colors=5, palette_cap=4).threshold == 4


@pytest.mark.parametrize("colors, cap", [(True, 4), (0, 4), (4, 1.5), (4, None)])
def test_filaments_refuses_bad_limits(colors, cap):
    with pytest.raises(ValueError):
        filaments_check(five_bodies(), colors=colors, palette_cap=cap)


# --- per-body export check -----------------------------------------------------------


@pytest.mark.parametrize("change", ["scale", "shift_x", "shift_z"])
def test_a_body_changed_after_encoding_fails_its_export_check(change):
    _, bodies = bodies_of("circle")
    for body in bodies:
        mesh = stored(body.mesh)
        vertices = np.array(mesh.vertices)
        if change == "scale":
            vertices *= 1.001
        elif change == "shift_x":
            vertices[:, 0] += 0.001
        else:
            vertices[:, 2] += 0.001
        moved = trimesh.Trimesh(vertices, mesh.faces, process=False, validate=False)
        assert body_export_check(moved, body).status == "FAIL"
        assert {c.status for c in topology_checks(moved)} == {"PASS"}  # F1 cannot see it


def test_an_inlay_checked_against_another_body_fails():
    _, bodies = bodies_of("box")
    assert body_export_check(stored(bodies[1].mesh), bodies[2]).status == "FAIL"


def moved_inside_bounds(mesh, box, dx=1.0):
    """The mesh with the vertices inside box (x0, y0, x1, y1) moved dx in x: one
    component moved, bounds and volume unchanged (the Codex review 3 fault)."""
    vertices = np.array(mesh.vertices)
    x0, y0, x1, y1 = box
    inside = ((vertices[:, 0] > x0) & (vertices[:, 0] < x1) & (vertices[:, 1] > y0)
              & (vertices[:, 1] < y1))
    assert inside.any()
    vertices[inside, 0] += dx
    return trimesh.Trimesh(vertices, mesh.faces, process=False, validate=False)


THREE_SQUARES = [shapely.box(a, a, a + 3, a + 3) for a in (2, 8, 14)]


def test_a_component_moved_inside_the_bounds_fails_the_inlay_export_check():
    # Three same-color squares in a 20 mm S; the middle one's mesh moved 1 mm in x. The
    # bounds and the volume stay the same; the occupancy at mid-skin does not.
    base_top = [shapely.box(0, 0, 20, 20).difference(shapely.union_all(THREE_SQUARES))]
    cells = color_cells(ColorRegions({1: THREE_SQUARES}, base_top, {}, []),
                        shapely.box(0, 0, 20, 20), 0)
    bodies = ams_bodies(cells, thickness_mm=T, skin_mm=SKIN)
    inlay = bodies[1]
    mesh = stored(inlay.mesh)
    good = body_export_check(mesh, inlay)
    assert good.status == "PASS"
    [row] = good.measured["occupancy"]
    assert row["z_mm"] == pytest.approx(T - SKIN / 2)
    assert row["symmetric_difference_mm2"] <= row["area_tol_mm2"]
    moved = moved_inside_bounds(mesh, (7.5, 7.5, 11.5, 11.5))
    assert {c.status for c in topology_checks(moved)} == {"PASS"}  # F1 cannot see it
    check = body_export_check(moved, inlay)
    assert check.status == "FAIL"
    assert check.measured["max_bound_error_mm"] <= check.threshold["coord_tol_mm"]
    assert check.measured["volume_error_mm3"] <= check.threshold["volume_tol_mm3"]
    [row] = check.measured["occupancy"]
    assert row["symmetric_difference_mm2"] == pytest.approx(2 * 3.0)  # 3 out, 3 in


def test_a_component_moved_inside_the_bounds_fails_the_base_export_check():
    # S is three separate strips; the base's middle component moved 1 mm in x.
    strips = [shapely.box(a, 2, a + 3, 18) for a in (2, 8, 14)]
    s = shapely.union_all(strips)
    dot = shapely.box(3, 3, 4, 4)
    cells = color_cells(ColorRegions({1: [dot]}, [s.difference(dot)], {}, []), s, 0)
    base = ams_bodies(cells, thickness_mm=T, skin_mm=SKIN)[0]
    mesh = stored(base.mesh)
    assert body_export_check(mesh, base).status == "PASS"
    check = body_export_check(moved_inside_bounds(mesh, (7.5, 0, 11.5, 20)), base)
    assert check.status == "FAIL"
    assert check.measured["max_bound_error_mm"] <= check.threshold["coord_tol_mm"]
    assert check.measured["volume_error_mm3"] <= check.threshold["volume_tol_mm3"]
    rows = check.measured["occupancy"]
    assert [r["z_range_mm"] for r in rows] == [[0.0, T - SKIN], [T - SKIN, T]]
    for row in rows:  # 16 mm^2 out and 16 mm^2 in, at both heights
        assert row["symmetric_difference_mm2"] == pytest.approx(2 * 16.0)


# --- ams_checks ---------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES)
def test_ams_checks_gates_the_stl_bytes(case):
    cells, bodies = bodies_of(case)
    result = run_checks(cells, bodies, colors=4)
    assert list(result["bodies"]) == [b.name for b in bodies]
    for body in bodies:
        assert result["stl"][body.name] == encode_stl(body.mesh)
        checks = result["bodies"][body.name]
        assert [c.id for c in checks][-1] == "F2.export_matches_geometry"
        assert {c.status for c in checks} == {"PASS"}
    ids = [c.id for c in result["assembly"]]
    assert ids == ["F4.color_partition", "F4.filaments", "F2.fits_build_volume",
                   "F5.triangles"]
    assert {c.status for c in result["assembly"]} == {"PASS"}
    triangles = next(c for c in result["assembly"] if c.id == "F5.triangles")
    assert triangles.measured == sum(len(b.mesh.faces) for b in bodies)
    fits = next(c for c in result["assembly"] if c.id == "F2.fits_build_volume")
    union = np.vstack([b.mesh.vertices for b in bodies])
    assert fits.measured == pytest.approx((union.max(axis=0) - union.min(axis=0)).tolist())
    for c in result["assembly"]:
        json.dumps(c.as_dict(), allow_nan=False)


def test_ams_checks_fails_filaments_for_five_bodies():
    result = run_checks(five_cells(), five_bodies(), colors=4, cap=4)
    status = {c.id: c.status for c in result["assembly"]}
    assert status["F4.filaments"] == "FAIL"
    assert status["F4.color_partition"] == "PASS"


TWO_BOXES = shapely.MultiPolygon([shapely.box(0, 0, 4, 4), shapely.box(4, 4, 8, 8)])


@pytest.mark.parametrize("inlays, base_top", [
    ({}, list(TWO_BOXES.geoms)),                         # base only
    ({1: list(TWO_BOXES.geoms)}, []),                    # one inlay covering both
    ({1: [TWO_BOXES.geoms[0]]}, [TWO_BOXES.geoms[1]]),   # a different label each side
])
def test_a_silhouette_pinch_is_reported_not_joined_and_f1_fails(inlays, base_top):
    # S's two squares touch at (4, 4). That is S's own shape, not a color choice: it is
    # reported, nothing is joined, and the base body FAILs F1 there.
    regions = ColorRegions(inlays, base_top, {}, [])
    cells = color_cells(regions, TWO_BOXES, 0)
    report = cells.report["pinches"]
    assert report["silhouette_pinches"] == 1
    assert report["fixed"] == 0 and report["rounds"] == 0
    bodies = ams_bodies(cells, thickness_mm=T, skin_mm=SKIN)
    base = dict(f1_failures(bodies[0].mesh))
    assert base["F1.edge_manifold"]["overfull_edges"] >= 1
    assert "F1.vertex_manifold" in base


def test_a_ring_touching_its_own_hole_with_an_island_in_it_is_not_a_pinch():
    # The shell's hole touches its outer ring at (0, 2), and a same-label island fills
    # the hole: around (0, 2) the label covers one run (the shell's two sides and the
    # island between them), so it is not a pinch.
    # (0, 2) is a vertex of the outer ring too, as in noded cells.
    shell = shapely.Polygon([(0, 0), (4, 0), (4, 4), (0, 4), (0, 2)],
                            [[(0, 2), (2, 1), (2, 3)]])
    island = shapely.Polygon([(0, 2), (2, 1), (2, 3)])
    assert shell.is_valid
    assert pinch_vertices([shell, island], [1, 1], grid_mm=1.0) == []
    # With a different label in the hole, the shell's two sides meet only at (0, 2),
    # between label 2 and outside: a real pinch of label 1.
    assert pinch_vertices([shell, island], [1, 2], grid_mm=1.0) == [((0.0, 2.0), [1])]
    # And with nothing in the hole, S itself pinches at (0, 2), label 1 with it.
    assert pinch_vertices([shell], [1], grid_mm=1.0) == [((0.0, 2.0), [1])]


def test_pinch_vertices_sorts_sectors_exactly_on_the_grid():
    # Directions that differ by one grid step at a large coordinate still sort apart.
    g = storage_grid_mm(60.0)
    c = (40.0, 40.0)
    cells = [shapely.Polygon([c, (c[0] + 1, c[1]), (c[0] + 1, c[1] + g)]),
             shapely.Polygon([c, (c[0] + 1, c[1] + g), (c[0] + 1, c[1] + 2 * g)]),
             shapely.Polygon([c, (c[0] + 1, c[1] + 2 * g), (c[0], c[1] + 1)])]
    assert pinch_vertices(cells, [1, 1, 2], grid_mm=g) == []  # 1, 1, 2, then outside
    assert pinch_vertices(cells, [1, 2, 1], grid_mm=g) == [(c, [1])]  # 1, 2, 1, outside
    assert pinch_vertices([cells[0], cells[2]], [1, 1], grid_mm=g) == [(c, [1])]


def test_pinch_vertices_refuses_off_grid_coordinates():
    with pytest.raises(ColorGeometryError, match="grid"):
        pinch_vertices([shapely.box(0, 0, 1.5, 1)], [1], grid_mm=1.0)


@pytest.mark.parametrize("fake, match", [
    (lambda cell: shapely.GeometryCollection(), "no triangles"),
    (lambda cell: shapely.GeometryCollection([shapely.Polygon([(0, 0), (1, 0), (0.5, 0.5)]),
                                              shapely.Polygon([(1, 0), (1, 1), (0.5, 0.5)]),
                                              shapely.Polygon([(1, 1), (0, 1), (0.5, 0.5)]),
                                              shapely.Polygon([(0, 1), (0, 0), (0.5, 0.5)])]),
     "added a vertex"),
    (lambda cell: shapely.GeometryCollection([shapely.Polygon([(0, 0), (1, 0), (1, 1)])]),
     "area"),
])
def test_triangulation_checks(monkeypatch, fake, match):
    monkeypatch.setattr(shapely, "constrained_delaunay_triangles", fake)
    with pytest.raises(ColorGeometryError, match=match):
        prism_mesh([shapely.box(0, 0, 1, 1)], [(0, 1)])


def test_ams_checks_refuses_no_bodies_and_bodies_of_other_cells():
    cells, bodies = bodies_of("box")
    with pytest.raises(ColorCheckError, match="no bodies"):
        run_checks(cells, [])
    _, other = bodies_of("circle")
    with pytest.raises(ColorCheckError, match="cells"):
        run_checks(cells, other)
    with pytest.raises(ColorCheckError, match="cells"):
        run_checks(cells, bodies[:1] + bodies[2:])  # color-1 missing


def test_encode_stl_is_public():
    _, bodies = bodies_of("box")
    assert encode_stl(bodies[0].mesh)[:80] is not None
    assert not hasattr(tdmg.flat, "_encode_stl")

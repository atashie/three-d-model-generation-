"""tdmg.printed: the printed footprint read from OrcaSlicer-style G-code, against the model.

The G-code is synthetic (tests/gcode_fixtures.py), so each case has a known answer.
"""

import math

import numpy as np
import pytest
import shapely
from gcode_fixtures import START, WIDTH, fill, gcode, layer, path_moves, solid, walls
from shapely import affinity

from tdmg.flat import extrude
from tdmg.printed import (
    ARC_STEP_MM,
    EDGE_SAMPLE_MM,
    UnsupportedGcode,
    align,
    footprint,
    gaps,
    layer_metrics,
    model_section,
    parse_gcode,
)

BED = (100.0, 100.0)            # where the synthetic slicer puts the model's lower corner


def bed(geometry, angle=0):
    """The model as the slicer would place it: optionally turned, then moved."""
    turned = affinity.rotate(geometry, angle, origin=(0, 0)) if angle else geometry
    x0, y0, _, _ = turned.bounds
    return affinity.translate(turned, BED[0] - x0, BED[1] - y0)


def square(side=10.0):
    return shapely.box(0, 0, side, side)


def bridge(width):
    """The control of the research record: two 10 mm squares joined by a 5 mm bridge."""
    return shapely.union_all([shapely.box(0, 0, 10, 10), shapely.box(15, 0, 25, 10),
                              shapely.box(10, 5 - width / 2, 15, 5 + width / 2)])


def measure(model, text, allowance=0.2):
    """Parse, align on the first layer and measure every layer of an extruded model."""
    mesh = extrude([model], 1.0)
    layers = parse_gcode(text)
    first = min(layers)
    alignment = align(model_section(mesh, layers[first].mid_z), layers[first].segments)
    return alignment, {z: layer_metrics(model_section(mesh, lay.mid_z),
                                        footprint(lay.segments), alignment, allowance)
                       for z, lay in layers.items()}


# --- Parsing ------------------------------------------------------------------------

def test_parse_reads_layers_widths_and_features():
    text = gcode([layer(0.2, path_moves([(0, 0), (1, 0), (1, 1)], 0.5)),
                  layer(0.4, path_moves([(0, 0), (2, 0)], 0.3, "Gap infill"))])
    layers = parse_gcode(text)
    assert sorted(layers) == [0.2, 0.4]
    assert layers[0.2].height == 0.2 and layers[0.2].mid_z == pytest.approx(0.1)
    assert [(s.x0, s.y0, s.x1, s.y1, s.width, s.feature) for s in layers[0.2].segments] == [
        (0, 0, 1, 0, 0.5, "Outer wall"), (1, 0, 1, 1, 0.5, "Outer wall")]
    assert [(s.width, s.feature) for s in layers[0.4].segments] == [(0.3, "Gap infill")]


def test_custom_moves_are_excluded():
    # START holds a purge line in "Custom" before any width or layer, as the A1 start code
    # does; it is neither refused nor counted.
    layers = parse_gcode(gcode([layer(0.2, path_moves([(0, 0), (1, 0)]))]))
    assert [s.feature for lay in layers.values() for s in lay.segments] == ["Outer wall"]


def test_travel_retraction_and_unretraction_are_not_plastic():
    body = ("; FEATURE: Outer wall\n; LINE_WIDTH: 0.42\nG1 X0 Y0\nG1 E-.8 F1800\n"
            "G1 X5 Y5 F42000\nG1 E.8\nG1 X6 Y5 E.03\nG1 X7 Y5 E-.1\nG1 X8 Y5 E0\n")
    segs = parse_gcode(gcode([layer(0.2, body)]))[0.2].segments
    assert [(s.x0, s.y0, s.x1, s.y1) for s in segs] == [(5, 5, 6, 5)]


def test_relative_positioning_is_followed():
    body = ("; FEATURE: Outer wall\n; LINE_WIDTH: 0.42\nG1 X1 Y1\nG91\nG1 X2 E.1\n"
            "G90\nG1 X0 Y0 E.1\n")
    segs = parse_gcode(gcode([layer(0.2, body)]))[0.2].segments
    assert [(s.x0, s.y0, s.x1, s.y1) for s in segs] == [(1, 1, 3, 1), (3, 1, 0, 0)]


def arc_points(segs):
    return np.array([(s.x0, s.y0) for s in segs] + [(segs[-1].x1, segs[-1].y1)])


@pytest.mark.parametrize("command", ["G2", "G3"])
def test_a_full_circle_arc_matches_the_circle_within_the_chord_bound(command):
    r = 5.0
    body = (f"; FEATURE: Outer wall\n; LINE_WIDTH: {WIDTH}\nG1 X{r} Y0\n"
            f"{command} X{r} Y0 I{-r} J0 E1\n")          # start = end: a full circle
    segs = parse_gcode(gcode([layer(0.2, body)]))[0.2].segments
    pts = arc_points(segs)
    lengths = np.hypot(*(pts[1:] - pts[:-1]).T)
    assert lengths.max() <= ARC_STEP_MM
    assert np.allclose(np.hypot(pts[:, 0], pts[:, 1]), r)        # every chord end on the arc
    # A chord of length c on radius r is at most r - sqrt(r^2 - c^2/4) inside the arc.
    sagitta = r - math.sqrt(r * r - ARC_STEP_MM ** 2 / 4)
    printed = footprint(segs)
    ring = shapely.Point(0, 0).buffer(r, quad_segs=1024).exterior.buffer(WIDTH / 2)
    assert shapely.hausdorff_distance(printed.exterior, ring.exterior) <= sagitta + 1e-3
    assert len(printed.interiors) == 1
    turn = np.unwrap(np.arctan2(pts[:, 1], pts[:, 0]))
    assert turn[-1] - turn[0] == pytest.approx(-2 * math.pi if command == "G2" else 2 * math.pi)


def test_g2_turns_clockwise_and_g3_anticlockwise():
    body = ("; FEATURE: Outer wall\n; LINE_WIDTH: 0.42\nG1 X5 Y0\n"
            "{} X0 Y-5 I-5 J0 E.5\n")
    cw = arc_points(parse_gcode(gcode([layer(0.2, body.format("G2"))]))[0.2].segments)
    ccw = arc_points(parse_gcode(gcode([layer(0.2, body.format("G3"))]))[0.2].segments)
    assert (cw[:, 1] <= 1e-9).all() and (cw[:, 0] >= -1e-9).all()     # the quarter below
    assert ccw[:, 1].max() == pytest.approx(5, abs=1e-3)               # three quarters round


@pytest.mark.parametrize(("text", "message"), [
    # Absolute extrusion: E is a position, so the plastic laid down is not read.
    (("M82\n; CHANGE_LAYER\n; Z_HEIGHT: 0.2\n; LAYER_HEIGHT: 0.2\n; FEATURE: Outer wall\n"
     "; LINE_WIDTH: 0.42\nG1 X0 Y0\nG1 X1 Y0 E1\n"), "absolute extrusion"),
    # No M83 at all: the extrusion mode is not known.
    (("; CHANGE_LAYER\n; Z_HEIGHT: 0.2\n; LAYER_HEIGHT: 0.2\n; FEATURE: Outer wall\n"
     "; LINE_WIDTH: 0.42\nG1 X0 Y0\nG1 X1 Y0 E1\n"), "absolute extrusion"),
    (START + "; Z_HEIGHT: 0.2\n; LAYER_HEIGHT: 0.2\n; FEATURE: Outer wall\nG1 X0 Y0\n"
     "G1 X1 Y0 E.1\n", "LINE_WIDTH"),
    (START + "; Z_HEIGHT: 0.2\n; LAYER_HEIGHT: 0.2\n; FEATURE: Outer wall\n"
     "; LINE_WIDTH: 0.42\nG1 X0 Y0\nG2 X1 Y0 R.5 E.1\n", "R-form"),
    (START + "; Z_HEIGHT: 0.2\n; LAYER_HEIGHT: 0.2\n; FEATURE: Outer wall\n"
     "; LINE_WIDTH: 0.42\nG1 X0 Y0\nG2 X0 Y0 I1 J0 P2 E.1\n", "P"),
    (START + "; FEATURE: Outer wall\n; LINE_WIDTH: 0.42\nG1 X0 Y0\nG1 X1 Y0 E.1\n",
     "Z_HEIGHT"),
    (START + "; Z_HEIGHT: 0.2\n; FEATURE: Outer wall\n; LINE_WIDTH: 0.42\nG1 X0 Y0\n"
     "G1 X1 Y0 E.1\n", "LAYER_HEIGHT"),
    (START + "; Z_HEIGHT: 0.2\n; LAYER_HEIGHT: 0.2\n; LINE_WIDTH: 0.42\n; FEATURE: Outer wall\n"
     "G28\nG1 X1 Y0 E.1\n", "unknown position"),
    (START + "; Z_HEIGHT: 0.2\n; LAYER_HEIGHT: 0.2\n; FEATURE: Outer wall\n"
     "; LINE_WIDTH: 0\nG1 X0 Y0\nG1 X1 Y0 E.1\n", "LINE_WIDTH"),
    (START + "G20\n", "inch"),
    (START, "no Z_HEIGHT"),
    ("G28\nG1 X10 Y10\n", "no Z_HEIGHT"),              # what the fake slicer writes by default
])
def test_unsupported_gcode_is_refused(text, message):
    with pytest.raises(UnsupportedGcode, match=message):
        parse_gcode(text)


def test_travel_arcs_are_followed_without_being_refused():
    # The real G-code lifts the nozzle with "G3 Z.6 I1.217 J0 P1" travel spirals.
    body = ("; FEATURE: Outer wall\n; LINE_WIDTH: 0.42\nG1 X0 Y0\nG3 Z.6 I1.217 J0 P1 F42000\n"
            "G1 X1 Y0 E.1\n")
    segs = parse_gcode(gcode([layer(0.2, body)]))[0.2].segments
    assert [(s.x0, s.y0, s.x1, s.y1) for s in segs] == [(0, 0, 1, 0)]


# --- The model section and the alignment --------------------------------------------

def test_model_section_is_the_outline_at_that_height():
    model = shapely.Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(3, 3), (3, 6), (6, 6),
                                                                      (6, 3)]])
    section = model_section(extrude([model], 1.0), 0.1)
    assert section.area == pytest.approx(model.area)
    assert len(section.interiors) == 1
    assert model_section(extrude([model], 1.0).export(file_type="stl"), 0.5).area == (
        pytest.approx(model.area))
    assert model_section(extrude([model], 1.0), 2.0).is_empty


def l_shape():
    return shapely.Polygon([(0, 0), (20, 0), (20, 5), (5, 5), (5, 15), (0, 15)])


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_alignment_finds_the_quarter_turn(angle):
    model = l_shape()
    printed = bed(model, angle)
    alignment, metrics = measure(model, gcode([layer(0.2, solid(printed))]))
    assert alignment.angle == angle
    # The refinement's mean pull is biased by sampling at corners: measured 0.0035 mm here.
    assert shapely.hausdorff_distance(alignment.apply(model), printed) < 0.01
    assert metrics[0.2]["max_gap_mm"] < 0.1


def test_alignment_without_an_outer_wall_is_unsupported():
    model = square()
    text = gcode([layer(0.2, fill(bed(model)))])
    layers = parse_gcode(text)
    with pytest.raises(UnsupportedGcode, match="Outer wall"):
        align(model_section(extrude([model], 1.0), 0.1), layers[0.2].segments)


# --- Metrics --------------------------------------------------------------------------

def test_a_covered_square_is_one_part_with_corner_gaps_only():
    model = square()
    alignment, metrics = measure(model, gcode([layer(0.2, solid(bed(model))),
                                               layer(0.4, solid(bed(model)))]))
    assert (alignment.angle, alignment.shift) == (0, pytest.approx(BED, abs=0.01))
    for m in metrics.values():
        assert (m["parts_model"], m["parts_printed"]) == (1, 1)
        assert (m["holes_model"], m["holes_printed"]) == (0, 0)
        # The outer bead's round corner misses the square's corner by (sqrt 2 - 1) w / 2.
        assert m["max_gap_mm"] == pytest.approx((math.sqrt(2) - 1) * WIDTH / 2, abs=1e-3)
        assert m["share_over_allowance"] == 0
        assert m["at_bed_mm"][0] in (pytest.approx(100, abs=0.01), pytest.approx(110, abs=0.01))


def test_a_lost_bridge_splits_the_footprint():
    model = bridge(0.3)
    printed = bed(shapely.union_all([shapely.box(0, 0, 10, 10), shapely.box(15, 0, 25, 10)]))
    _, metrics = measure(model, gcode([layer(0.2, solid(printed))]))
    m = metrics[0.2]
    assert (m["parts_model"], m["parts_printed"]) == (1, 2)
    # Half the 5 mm bridge is unprinted from its middle to either square.
    assert m["max_gap_mm"] == pytest.approx(2.5, abs=EDGE_SAMPLE_MM)
    assert 0 < m["share_over_allowance"] < 1


def test_an_unprinted_tip_gives_a_large_edge_gap():
    model = shapely.union_all([square(), shapely.Polygon([(10, 4), (16, 5), (10, 6)])])
    printed = bed(square())
    _, metrics = measure(model, gcode([layer(0.2, solid(printed))]))
    m = metrics[0.2]
    assert (m["parts_model"], m["parts_printed"]) == (1, 1)          # connectivity is fine
    assert m["max_gap_mm"] == pytest.approx(6.0, abs=0.05)           # the 6 mm spike's tip
    # Matching bounding boxes alone would put the model 3 mm to the left (x 113 here): the
    # printed box lacks the spike. The nearest-point refinement finds the true place.
    assert m["at_bed_mm"] == [pytest.approx(116, abs=0.05), pytest.approx(105, abs=0.05)]
    assert m["at_model_mm"] == [pytest.approx(16, abs=0.05), pytest.approx(5, abs=0.05)]


def test_a_model_hole_is_counted_and_a_closed_hole_is_found():
    model = shapely.Polygon([(0, 0), (10, 0), (10, 10), (0, 10)],
                            [[(4, 4), (4, 6), (6, 6), (6, 4)]])
    _, open_ = measure(model, gcode([layer(0.2, walls(bed(model)))]))
    assert (open_[0.2]["holes_model"], open_[0.2]["holes_printed"]) == (1, 1)
    _, closed = measure(model, gcode([layer(0.2, solid(bed(square())))]))
    assert (closed[0.2]["holes_model"], closed[0.2]["holes_printed"]) == (1, 0)


def test_voids_inside_the_model_are_not_holes():
    # Sparse infill leaves voids between its lines, inside the model: intended, not holes.
    model = square()
    sparse = walls(bed(model)) + fill(bed(model), spacing=2.0)
    _, metrics = measure(model, gcode([layer(0.2, sparse)]))
    printed = footprint(parse_gcode(gcode([layer(0.2, sparse)]))[0.2].segments)
    assert printed.geom_type == "Polygon" and len(printed.interiors) > 1
    assert (metrics[0.2]["holes_model"], metrics[0.2]["holes_printed"]) == (0, 0)


def test_gaps_equal_shapely_distance():
    # The fast distance is exact: the same numbers as shapely.distance, including inside
    # the footprint, in its holes and far outside.
    model = shapely.Polygon([(0, 0), (10, 0), (10, 10), (0, 10)],
                            [[(4, 4), (4, 6), (6, 6), (6, 4)]])
    printed = footprint(parse_gcode(gcode([layer(0.2, walls(bed(model))
                                                 + fill(bed(model), spacing=2.0))]))[0.2].segments)
    rng = np.random.default_rng(0)
    pts = rng.uniform(95, 115, size=(2000, 2))
    assert np.array_equal(gaps(pts, printed), shapely.distance(shapely.points(pts), printed))
    assert (gaps(pts, shapely.Polygon()) == math.inf).all()

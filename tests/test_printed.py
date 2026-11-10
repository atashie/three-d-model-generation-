"""tdmg.printed: the printed footprint read from OrcaSlicer-style G-code, against the model.

The G-code is synthetic (tests/gcode_fixtures.py), so each case has a known answer. It is
placed as the slicer places a model: its bounding box centred on the A1's 256 mm plate.
"""

import json
import math
import re

import numpy as np
import pytest
import shapely
from gcode_fixtures import START, WIDTH, fill, gcode, layer, path_moves, solid, walls

import tdmg.printed
from tdmg.flat import extrude
from tdmg.printed import (
    ARC_STEP_MM,
    EDGE_SAMPLE_MM,
    MODEL_FEATURES,
    QUARTER_TURNS,
    Alignment,
    Plate,
    UnsupportedGcode,
    analyse,
    f3_checks,
    footprint,
    gaps,
    model_section,
    parse_gcode,
    plate_from_profile,
)

# The A1's printable_area (artifacts/tools/... profiles-flat/machine.json: 0x0 to 256x256).
PLATE = Plate(0.0, 0.0, 256.0, 256.0)


def placed(geometry, model=None, angle=0):
    """geometry where the slicer puts it for this model: the model's bounding box centred
    on the plate, after a quarter turn about that centre."""
    x0, y0, x1, y1 = (model if model is not None else geometry).bounds
    return Alignment(angle, ((x0 + x1) / 2, (y0 + y1) / 2), PLATE.centre, None).apply(geometry)


def square(side=10.0):
    return shapely.box(0, 0, side, side)


def bridge(width):
    """The control of the research record: two 10 mm squares joined by a 5 mm bridge."""
    return shapely.union_all([shapely.box(0, 0, 10, 10), shapely.box(15, 0, 25, 10),
                              shapely.box(10, 5 - width / 2, 15, 5 + width / 2)])


def measure(model, text, allowance=0.2):
    """The best turn's alignment and layers (ties are judged in f3_checks)."""
    alignment, layers = analyse(text, extrude([model], 1.0), PLATE, allowance, allowance)[0]
    return alignment, {m["z"]: m for m in layers}


def checks_for(model, printed_geometry, layers=(0.2, 0.4)):
    """f3_checks on G-code that prints printed_geometry, placed for model, on each layer."""
    body = solid(placed(printed_geometry, model))
    stl = extrude([model], 1.0).export(file_type="stl")
    return f3_checks(gcode([layer(z, body) for z in layers]).encode(), stl, PLATE, 0.2, 0.075)


def checks_for_text(text, model=None):
    """f3_checks on this G-code text for model (a 10 mm square by default)."""
    stl = extrude([model if model is not None else square()], 1.0).export(file_type="stl")
    return f3_checks(text.encode(), stl, PLATE, 0.2, 0.075)


def parse(text):
    return parse_gcode(text, PLATE)


# --- The plate ----------------------------------------------------------------------

def test_the_plate_comes_from_printable_area():
    plate = plate_from_profile({"printable_area": ["0x0", "256x0", "256x256", "0x256"]})
    assert plate == PLATE and plate.centre == (128.0, 128.0)
    assert plate.within_bound(-256, 512) and not plate.within_bound(-256.1, 0)


@pytest.mark.parametrize("profile", [{}, {"printable_area": "0x0,256x0,256x256"},
                                     {"printable_area": ["0x0", "256x0", "ax256"]},
                                     {"printable_area": ["0x0", "nanx0", "256x256"]},
                                     {"printable_area": ["0x0", "0x0", "0x0"]}])
def test_a_bad_printable_area_is_refused(profile):
    with pytest.raises(ValueError, match="printable_area"):
        plate_from_profile(profile)


# --- Parsing ------------------------------------------------------------------------

def test_parse_reads_layers_widths_and_features():
    text = gcode([layer(0.2, path_moves([(0, 0), (1, 0), (1, 1)], 0.5)),
                  layer(0.4, path_moves([(0, 0), (2, 0)], 0.3, "Gap infill"))])
    layers = parse(text)
    assert sorted(layers) == [0.2, 0.4]
    assert layers[0.2].height == 0.2 and layers[0.2].mid_z == pytest.approx(0.1)
    assert [(s.x0, s.y0, s.x1, s.y1, s.width, s.feature) for s in layers[0.2].segments] == [
        (0, 0, 1, 0, 0.5, "Outer wall"), (1, 0, 1, 1, 0.5, "Outer wall")]
    assert [(s.width, s.feature) for s in layers[0.4].segments] == [(0.3, "Gap infill")]


def test_custom_moves_are_excluded():
    # START holds a purge line in "Custom" before any width or layer, as the A1 start code
    # does; it is neither refused nor counted.
    layers = parse(gcode([layer(0.2, path_moves([(0, 0), (1, 0)]))]))
    assert [s.feature for lay in layers.values() for s in lay.segments] == ["Outer wall"]


@pytest.mark.parametrize("feature", sorted(MODEL_FEATURES))
def test_every_model_feature_is_read(feature):
    layers = parse(gcode([layer(0.2, path_moves([(0, 0), (1, 0)], feature=feature))]))
    assert [s.feature for s in layers[0.2].segments] == [feature]


def test_travel_retraction_and_unretraction_are_not_plastic():
    body = ("; FEATURE: Outer wall\n; LINE_WIDTH: 0.42\nG1 X0 Y0\nG1 E-.8 F1800\n"
            "G1 X5 Y5 F42000\nG1 E.8\nG1 X6 Y5 E.03\nG1 X7 Y5 E-.1\nG1 X8 Y5 E0\n")
    segs = parse(gcode([layer(0.2, body)]))[0.2].segments
    assert [(s.x0, s.y0, s.x1, s.y1) for s in segs] == [(5, 5, 6, 5)]


def test_relative_positioning_is_followed():
    body = ("; FEATURE: Outer wall\n; LINE_WIDTH: 0.42\nG1 X1 Y1\nG91\nG1 X2 E.1\n"
            "G90\nG1 X0 Y0 E.1\n")
    segs = parse(gcode([layer(0.2, body)]))[0.2].segments
    assert [(s.x0, s.y0, s.x1, s.y1) for s in segs] == [(1, 1, 3, 1), (3, 1, 0, 0)]


def arc_points(segs):
    return np.array([(s.x0, s.y0) for s in segs] + [(segs[-1].x1, segs[-1].y1)])


@pytest.mark.parametrize("command", ["G2", "G3"])
def test_a_full_circle_arc_matches_the_circle_within_the_chord_bound(command):
    r = 5.0
    body = (f"; FEATURE: Outer wall\n; LINE_WIDTH: {WIDTH}\nG1 X{r} Y0\n"
            f"{command} X{r} Y0 I{-r} J0 E1\n")          # start = end: a full circle
    segs = parse(gcode([layer(0.2, body)]))[0.2].segments
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
    cw = arc_points(parse(gcode([layer(0.2, body.format("G2"))]))[0.2].segments)
    ccw = arc_points(parse(gcode([layer(0.2, body.format("G3"))]))[0.2].segments)
    assert (cw[:, 1] <= 1e-9).all() and (cw[:, 0] >= -1e-9).all()     # the quarter below
    assert ccw[:, 1].max() == pytest.approx(5, abs=1e-3)               # three quarters round


GOOD = "; FEATURE: Outer wall\n; LINE_WIDTH: 0.42\nG1 X100 Y100\nG1 X101 Y100 E.1\n"


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
    (START + "G20\n", "G20"),                          # inches
    (START, "no Z_HEIGHT"),
    ("G28\nG1 X10 Y10\n", "no Z_HEIGHT"),              # what the fake slicer writes by default
    # Non-finite or absurd numbers: refused, not followed.
    (gcode([layer(0.2, GOOD + "G1 Xnan Y105 E.1\n")]), "'Xnan'"),
    (gcode([layer(0.2, GOOD + "G1 Xinf Y105 E.1\n")]), "'Xinf'"),
    (gcode([layer(0.2, GOOD + "G1 X101 Y101 Enan\n")]), "'Enan'"),
    (gcode([layer(0.2, GOOD.replace("0.42", "nan"))]), "not finite"),
    (START + "; Z_HEIGHT: nan\n; LAYER_HEIGHT: 0.2\n" + GOOD, "not finite"),
    (gcode([layer(0.2, GOOD + "G1 X1e30 Y105 E.1\n")]), "'X1e30'"),
    (gcode([layer(0.2, GOOD + "G1 X100000 Y105 E.1\n")]), "beyond the plate"),
    (gcode([layer(0.2, GOOD + "G1 X600 Y105\n")]), "beyond the plate"),     # travel too
    (gcode([layer(0.2, GOOD + "G2 X101.1 Y100 I1e7 J0 E.1\n")]), "'I1e7'"),
    (gcode([layer(0.2, GOOD + "G2 X101.1 Y100 I10000000 J0 E.1\n")]), "arc"),  # once a hang
    (gcode([layer(0.2, GOOD + "G2 X101 Y100 I300 J0 E.1\n")]), "arc"),     # beyond the bound
    # Layers: a repeated Z_HEIGHT, or one with no LAYER_HEIGHT even if it prints nothing.
    (gcode([layer(0.2, GOOD), layer(0.2, GOOD, height=0.1)]), "repeats"),
    (START + layer(0.2, GOOD) + "; CHANGE_LAYER\n; Z_HEIGHT: 0.4\n" + layer(0.6, GOOD),
     "0.4 have no LAYER_HEIGHT"),
    (START + "; LAYER_HEIGHT: 0.2\n; Z_HEIGHT: 0.2\n" + GOOD, "LAYER_HEIGHT"),
    # Extrusions that are not the model's: refused, with the feature named.
    (gcode([layer(0.2, GOOD + path_moves([(90, 90), (95, 90)], feature="Brim"))]), "'Brim'"),
    (gcode([layer(0.2, GOOD + path_moves([(90, 90), (95, 90)], feature="Skirt"))]), "'Skirt'"),
    (gcode([layer(0.2, GOOD + path_moves([(90, 90), (95, 90)], feature="Support"))]),
     "'Support'"),
    (gcode([layer(0.2, GOOD + path_moves([(90, 90), (95, 90)], feature="Prime tower"))]),
     "'Prime tower'"),
    (gcode([layer(0.2, GOOD + path_moves([(90, 90), (95, 90)], feature="Overhang wall"))]),
     "'Overhang wall'"),
])
def test_unsupported_gcode_is_refused(text, message):
    with pytest.raises(UnsupportedGcode, match=message):
        parse(text)


def test_travel_arcs_are_followed_without_being_refused():
    # The real G-code lifts the nozzle with "G3 Z.6 I1.217 J0 P1" travel spirals.
    body = ("; FEATURE: Outer wall\n; LINE_WIDTH: 0.42\nG1 X0 Y0\nG3 Z.6 I1.217 J0 P1 F42000\n"
            "G1 X1 Y0 E.1\n")
    segs = parse(gcode([layer(0.2, body)]))[0.2].segments
    assert [(s.x0, s.y0, s.x1, s.y1) for s in segs] == [(0, 0, 1, 0)]


def test_a_feature_that_only_travels_is_not_refused():
    body = GOOD + "; FEATURE: Skirt\nG1 X90 Y90 F42000\nG1 E-.8\n"
    assert len(parse(gcode([layer(0.2, body)]))[0.2].segments) == 1


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


@pytest.mark.parametrize("angle", QUARTER_TURNS)
def test_alignment_finds_the_quarter_turn_and_places_the_box_on_the_plate_centre(angle):
    model = l_shape()
    printed = placed(model, angle=angle)
    alignment, metrics = measure(model, gcode([layer(0.2, solid(printed))]))
    assert alignment.angle == angle
    assert alignment.centre == (10.0, 7.5) and alignment.plate_centre == (128.0, 128.0)
    assert alignment.apply(model).symmetric_difference(printed).area < 1e-9
    assert metrics[0.2]["max_gap_mm"] < 0.1
    record = alignment.as_dict()
    assert record["shift_mm"] == [118.0, 120.5]
    assert np.allclose(alignment.to_model(alignment.to_bed(np.array([[3.0, 4.0]]))), [3, 4])


def test_the_placement_does_not_depend_on_the_print():
    # Only fill, no outer wall, and short of the edges: the placement is still the known
    # one, and the gaps show what is missing.
    model = square()
    alignment, metrics = measure(model, gcode([layer(0.2, fill(placed(model)))]))
    assert alignment.shift == (123.0, 123.0)
    assert metrics[0.2]["max_gap_mm"] > 0.3


# --- Metrics --------------------------------------------------------------------------

def test_a_covered_square_is_one_part_with_corner_gaps_only():
    model = square()
    alignment, metrics = measure(model, gcode([layer(0.2, solid(placed(model))),
                                               layer(0.4, solid(placed(model)))]))
    assert alignment.angle in QUARTER_TURNS      # a square looks the same at every turn
    for m in metrics.values():
        assert (m["parts_model"], m["parts_printed"]) == (1, 1)
        assert (m["holes_model"], m["holes_printed"]) == (0, 0)
        assert m["unmatched"] == []
        # The outer bead's round corner misses the square's corner by (sqrt 2 - 1) w / 2.
        assert m["max_gap_mm"] == pytest.approx((math.sqrt(2) - 1) * WIDTH / 2, abs=1e-3)
        assert m["share_over_allowance"] == 0
        assert m["at_bed_mm"][0] in (pytest.approx(123), pytest.approx(133))


def test_a_lost_bridge_splits_the_footprint():
    model = bridge(0.3)
    squares = shapely.union_all([shapely.box(0, 0, 10, 10), shapely.box(15, 0, 25, 10)])
    _, metrics = measure(model, gcode([layer(0.2, solid(placed(squares, model)))]))
    m = metrics[0.2]
    assert (m["parts_model"], m["parts_printed"]) == (1, 2)
    assert m["unmatched"] == [{"what": "model part", "overlaps": 2,
                               "at_model_mm": pytest.approx(
                                   list(model.representative_point().coords[0]))}]
    # Half the 5 mm bridge is unprinted from its middle to either square.
    assert m["max_gap_mm"] == pytest.approx(2.5, abs=EDGE_SAMPLE_MM)
    assert 0 < m["share_over_allowance"] < 1


def test_an_unprinted_tip_on_a_long_body_gives_its_length_as_the_gap():
    body = shapely.box(0, 0, 60, 3)
    model = shapely.union_all([body, shapely.box(60, 1.35, 65, 1.65)])     # a 5 mm hair
    _, metrics = measure(model, gcode([layer(0.2, solid(placed(body, model)))]))
    m = metrics[0.2]
    assert (m["parts_model"], m["parts_printed"]) == (1, 1)          # connectivity is fine
    assert m["max_gap_mm"] == pytest.approx(5.0, abs=0.05)
    assert m["at_model_mm"] == [pytest.approx(65, abs=0.05), pytest.approx(1.5, abs=0.2)]


@pytest.mark.parametrize(("model", "printed", "gap"), [
    # The review's one-sided shortfalls: a fitted shift once split these into two
    # half-gaps under 0.2 mm and PASSed them; with the known placement they FAIL.
    (shapely.box(0, 0, 60, 3), shapely.box(0, 0, 60, 2.75), 0.25),
    (square(), shapely.box(0, 0, 9.75, 10), 0.25),
    # A 0.3 mm wide hair 0.25 mm long at the end of a 60 x 3 mm body, left unprinted.
    (shapely.union_all([shapely.box(0, 0, 60, 3), shapely.box(60, 1.35, 60.25, 1.65)]),
     shapely.box(0, 0, 60, 3), 0.25),
    # A long hair: once not converging (UNKNOWN); now a FAIL with the hair's length.
    (shapely.union_all([shapely.box(0, 0, 60, 3), shapely.box(60, 1.35, 70, 1.65)]),
     shapely.box(0, 0, 60, 3), 10.0),
])
def test_one_sided_shortfalls_fail_coverage(model, printed, gap):
    (connectivity, coverage), record = checks_for(model, printed)
    assert coverage.status == "FAIL", coverage
    assert coverage.measured["worst_z"] == pytest.approx(0.4)
    # At least the shortfall; at a corner of a shortened box the bead's round end adds up
    # to about 0.05 mm (0.296 mm measured for 0.25 mm).
    assert gap - 0.03 <= coverage.measured["max_gap_mm"] <= gap + 0.06
    assert connectivity.status == "PASS"
    assert 0 in record["alignment"]["tied_angles_deg"]     # a bar is the same turned 180


def test_a_model_hole_is_matched_and_a_closed_hole_is_found():
    model = shapely.Polygon([(0, 0), (10, 0), (10, 10), (0, 10)],
                            [[(4, 4), (4, 6), (6, 6), (6, 4)]])
    _, open_ = measure(model, gcode([layer(0.2, walls(placed(model)))]))
    assert (open_[0.2]["holes_model"], open_[0.2]["holes_printed"]) == (1, 1)
    assert not [u for u in open_[0.2]["unmatched"] if u["what"].endswith("hole")]
    _, closed = measure(model, gcode([layer(0.2, solid(placed(square(), model)))]))
    m = closed[0.2]
    assert (m["holes_model"], m["holes_printed"]) == (1, 0)
    assert m["unmatched"] == [{"what": "model hole", "overlaps": 0,
                               "at_model_mm": pytest.approx([5, 5], abs=1)}]


def test_a_filled_hole_and_a_bridged_slot_do_not_compensate():
    # The review's case: the model has a hole and a slot open to the outside. The print
    # fills the hole and bridges the slot's mouth, enclosing a void. Counting gave
    # holes [1, 1] and a PASS; matching finds both.
    slot = shapely.box(0, 0, 10, 10).difference(shapely.box(4.5, 5, 5.5, 10.1))
    model = shapely.Polygon(slot.exterior.coords, [shapely.box(2, 2, 3, 3).exterior.coords])
    printed = shapely.box(0, 0, 10, 10).difference(shapely.box(4.5, 5, 5.5, 9.3))
    (connectivity, _), record = checks_for(model, printed)
    assert connectivity.status == "FAIL"
    assert record["layers"][1]["holes"] == [1, 1]
    found = {u["what"]: u for u in connectivity.measured["unmatched"]}
    assert set(found) == {"model hole", "printed hole"}
    assert found["model hole"]["at_model_mm"] == pytest.approx([2.5, 2.5], abs=0.5)
    assert 4.5 < found["printed hole"]["at_model_mm"][0] < 5.5
    assert 5 < found["printed hole"]["at_model_mm"][1] < 9.3
    assert "model hole overlapping 0 at model" in connectivity.note


def test_voids_inside_the_model_are_not_holes():
    # Sparse infill leaves voids between its lines, inside the model: intended, not holes.
    model = square()
    sparse = walls(placed(model)) + fill(placed(model), spacing=2.0)
    _, metrics = measure(model, gcode([layer(0.2, sparse)]))
    printed = footprint(parse(gcode([layer(0.2, sparse)]))[0.2].segments)
    assert printed.geom_type == "Polygon" and len(printed.interiors) > 1
    assert (metrics[0.2]["holes_model"], metrics[0.2]["holes_printed"]) == (0, 0)
    assert metrics[0.2]["unmatched"] == []


def test_gaps_equal_shapely_distance():
    # The fast distance is exact: the same numbers as shapely.distance, including inside
    # the footprint, in its holes and far outside.
    model = shapely.Polygon([(0, 0), (10, 0), (10, 10), (0, 10)],
                            [[(4, 4), (4, 6), (6, 6), (6, 4)]])
    printed = footprint(parse(gcode([layer(0.2, walls(placed(model))
                                           + fill(placed(model), spacing=2.0))]))[0.2].segments)
    rng = np.random.default_rng(0)
    pts = rng.uniform(118, 138, size=(2000, 2))
    assert np.array_equal(gaps(pts, printed), shapely.distance(shapely.points(pts), printed))
    assert (gaps(pts, shapely.Polygon()) == math.inf).all()


# --- f3_checks ------------------------------------------------------------------------

def test_a_layer_that_prints_nothing_fails_coverage():
    # A Z_HEIGHT layer with no extrusion where the model has a section: no gap can be
    # measured (it would be infinite), so the layer is named and the check FAILs.
    model = square()
    body = solid(placed(model))
    text = gcode([layer(0.2, body), layer(0.4, ""), layer(0.6, body)])
    stl = extrude([model], 1.0).export(file_type="stl")
    checks, record = f3_checks(text.encode(), stl, PLATE, 0.2, 0.075)
    connectivity, coverage = checks
    assert connectivity.status == "FAIL" and connectivity.measured["mismatched_z"] == [0.4]
    assert coverage.status == "FAIL"
    assert coverage.measured["nothing_printed_z"] == [0.4]
    assert "0.4" in coverage.note and "print nothing" in coverage.note
    assert record["layers"][1] == {"z": 0.4, "max_gap_mm": None, "parts": [1, 0],
                                   "holes": [0, 0], "unmatched": 1}
    json.dumps(record, allow_nan=False)                       # strict JSON


def test_f3_checks_on_a_covered_square():
    (connectivity, coverage), record = checks_for(square(), square())
    assert [connectivity.status, coverage.status] == ["PASS", "PASS"]
    assert coverage.threshold == {"first_layer_mm": pytest.approx(0.275),
                                  "other_layers_mm": 0.2}
    assert coverage.rule == "acceptance.dimension.tolerance"
    assert record["measured"] is True and record["alignment"]["angle_deg"] in QUARTER_TURNS
    assert record["alignment"]["plate_centre_mm"] == [128.0, 128.0]
    json.dumps(record, allow_nan=False)


@pytest.mark.parametrize(("gcode_bytes", "reason"), [
    (None, "no G-code was written"),
    (b"\xff\xfe", "not UTF-8"),
    (b"G28\nG1 X10 Y10\n", "no Z_HEIGHT"),
])
def test_f3_checks_are_unknown_when_not_measurable(gcode_bytes, reason):
    stl = extrude([square()], 1.0).export(file_type="stl")
    checks, record = f3_checks(gcode_bytes, stl, PLATE, 0.2, 0.075)
    assert [c.status for c in checks] == ["UNKNOWN", "UNKNOWN"]
    assert all(reason in c.note for c in checks)
    assert record["measured"] is False and reason in record["reason"]


def test_any_analysis_error_is_unknown(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(tdmg.printed, "analyse", broken)
    stl = extrude([square()], 1.0).export(file_type="stl")
    checks, record = f3_checks(b"; Z_HEIGHT: 0.2\n", stl, PLATE, 0.2, 0.075)
    assert [c.status for c in checks] == ["UNKNOWN", "UNKNOWN"]
    assert record["reason"] == "analysis error: RuntimeError: boom"
    assert all("analysis error: RuntimeError: boom" in c.note for c in checks)


def test_a_nearly_straight_arc_with_a_large_radius_is_read():
    # Arc fitting writes such arcs (a 207 mm radius in the Roadie G-code): the sweep is
    # small, so the arc stays on the plate although its circle does not.
    r = 400.0
    a = 5.0 / r                                   # a 5 mm arc
    x1, y1 = 100 + r * (math.cos(a) - 1), 100 + r * math.sin(a)
    body = (f"; FEATURE: Outer wall\n; LINE_WIDTH: 0.42\nG1 X100 Y100\n"
            f"G3 X{x1:.6f} Y{y1:.6f} I{-r} J0 E.2\n")
    segs = parse(gcode([layer(0.2, body)]))[0.2].segments
    assert sum(math.hypot(s.x1 - s.x0, s.y1 - s.y0) for s in segs) == pytest.approx(5, abs=1e-3)


# --- Strict reading: what is not understood is refused, never dropped -------------------

STRAY = "G1 X200 Y200\n"        # travel far away; an extrusion there would be an extra part


def _square_text(extra: str) -> str:
    body = solid(placed(square()))
    return gcode([layer(0.2, body), layer(0.4, body + extra)])


def test_a_stray_part_written_plainly_fails():
    # The control for the forms below: read, it is an extra printed part.
    (connectivity, _), _ = checks_for_text(_square_text(STRAY + "G1 X205 Y200 E.2\n"))
    assert connectivity.status == "FAIL"


@pytest.mark.parametrize(("extra", "reason"), [
    (STRAY + "G01 X205 Y200 E.2\n", "'G01'"),                     # a leading zero
    (STRAY + "G1X205Y200E.2\n", "'G1X205Y200E.2'"),               # no spaces
    (STRAY + "g1 X205 Y200 E.2\n", "'g1'"),                       # lower case
    (STRAY + "N10 G1 X205 Y200 E.2*33\n", "'N10'"),               # a line number
    (STRAY + "G1 X205 Y200 E.2*33\n", "'E.2\\*33'"),              # a checksum
    (STRAY + "G1 X205 Y200 E2e-1\n", "'E2e-1'"),                  # an exponent
    (STRAY + "G5 I1 J1 P1 Q1 X205 Y200 E.2\n", "G5"),             # a Bezier move
    ("G18\nG1 X128 Y128\nG2 X130 Y128 I1 J0 E.1\nG17\n", "G18"),  # an arc in another plane
    ("G19\n", "G19"),
    ("G10\nG11\n", "G10"),                                        # firmware retraction
    ("G4 P100\n", "G4"),                                          # not seen in this G-code
    # A Custom extrusion between model extrusions: not start or end code.
    ("; FEATURE: Custom\n" + STRAY + "G1 X205 Y200 E.2\n", "Custom extrusion"),
    ("plain text\n", "'plain'"),
])
def test_forms_this_parser_does_not_read_are_unknown(extra, reason):
    (connectivity, coverage), record = checks_for_text(_square_text(extra))
    assert [connectivity.status, coverage.status] == ["UNKNOWN", "UNKNOWN"], record["reason"]
    assert re.search(reason, record["reason"]), record["reason"]


def test_custom_at_the_start_and_end_is_still_excluded():
    # gcode() writes a Custom purge before the first layer and a Custom move after the last.
    (connectivity, coverage), _ = checks_for_text(_square_text(""))
    assert [connectivity.status, coverage.status] == ["PASS", "PASS"]


def test_m_and_t_codes_are_ignored_except_the_extrusion_mode():
    extra = "M204 S6000\nM73 P3 R7\nM622.1 S1\nT255\nM1002 judge_flag g29_before_print_flag\n"
    (connectivity, coverage), _ = checks_for_text(_square_text(extra))
    assert [connectivity.status, coverage.status] == ["PASS", "PASS"]
    (connectivity, _), record = checks_for_text(_square_text("M82\n" + STRAY
                                                             + "G1 X205 Y200 E.2\n"))
    assert connectivity.status == "UNKNOWN" and "absolute extrusion" in record["reason"]


# --- Rotation ties -----------------------------------------------------------------------

@pytest.mark.parametrize("turn", [0, 180])
def test_a_tie_between_turns_keeps_the_worse_result(turn):
    # The review's bar: a 60 x 3 mm body with an unprinted hair at one end and a printed
    # tab at the other. Turned 0 or 180 degrees the medians are within EDGE_SAMPLE_MM / 2,
    # so the turn cannot be told apart. Under the wrong one the tab would land on the hair
    # and hide it; both are measured and the worse is kept, which FAILs either way.
    body = shapely.box(0, 0, 60, 3)
    tab = shapely.box(-0.18, 1.1, 0, 1.9)
    model = shapely.union_all([body, shapely.box(60, 1.35, 60.35, 1.65), tab])
    printed = shapely.union_all([body, tab])
    stl = extrude([model], 1.0).export(file_type="stl")
    text = gcode([layer(z, solid(placed(printed, model, turn))) for z in (0.2, 0.4)])
    (_, coverage), record = f3_checks(text.encode(), stl, PLATE, 0.2, 0.075)
    assert coverage.status == "FAIL"
    assert coverage.measured["max_gap_mm"] >= 0.3
    assert {0, 180} <= set(record["alignment"]["tied_angles_deg"])


def test_a_clear_turn_has_no_tie():
    model = l_shape()
    (_, coverage), record = checks_for(model, model)
    assert record["alignment"]["tied_angles_deg"] == [0]
    assert coverage.status == "PASS"

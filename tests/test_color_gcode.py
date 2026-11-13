"""tdmg.color_gcode: the multicolor G-code reader and F6.color_changes, F6.tool_placement,
F6.filaments_used, the per-color F3 and the information measures.

docs/plans/2026-11-13-color-slicing.md, Decision 4 (amended after Task 2) and Task 5. The
G-code is hand-written (tests/gcode_fixtures.py's beads, with the A1's tool-change markers
as research/verification/2026-11-13-color-slicing/README.md lists them), so each case has a
known answer. The real-slicer tests at the end slice with the pinned OrcaSlicer.
"""

import io
import json
import math
import os
import re
from pathlib import Path

import numpy as np
import pytest
import shapely
import trimesh
from gcode_fixtures import FLOW, START, layer, path_moves, solid
from test_printed import PLATE, placed

from tdmg import color_gcode
from tdmg.checks import verdict
from tdmg.color_gcode import (
    COLOR_CHANGES,
    COLOR_FILAMENT,
    COLOR_TIME,
    COLOR_WASTE,
    FILAMENTS_USED,
    GATED_CHECK_IDS,
    INFO_CHECK_IDS,
    TOOL_PLACEMENT,
    color_slice_checks,
    f3_required_ids,
    f3_warning_ids,
    layer_sets,
    min_changes,
    per_tool_id,
    read_multicolor,
    required_check_ids,
)
from tdmg.flat import extrude
from tdmg.orca_input import turn_over
from tdmg.printed import F3_SLICE_CHECK_IDS, Setup, UnsupportedGcode
from tdmg.threemf import Shell

HEXES = ["#f60606", "#f5f5f5", "#f0f10a", "#451812"]
SQUARE = shapely.box(0, 0, 20, 20)
A = shapely.box(2, 6, 8, 14)              # inlay 1 (tool 1)
B = shapely.box(12, 6, 18, 14)            # inlay 2 (tool 2)
RING = SQUARE.difference(A).difference(B)


def _slab(geometry, z0, z1):
    m = extrude([geometry], z1 - z0)
    m.apply_translation((0, 0, z0))
    return m


def _shell(name, role, index, mesh):
    return Shell(name, role, index, HEXES[index], np.asarray(mesh.vertices, np.float32),
                 np.asarray(mesh.faces, np.int64))


def bodies():
    """A 20 x 20 x 0.4 base with two pockets in its top layer, and an inlay in each."""
    base = trimesh.util.concatenate([_slab(SQUARE, 0, 0.2), _slab(RING, 0.2, 0.4)])
    return [_shell("ams-base", "base", 0, base),
            _shell("ams-color-1-f5f5f5", "inlay", 1, _slab(A, 0.2, 0.4)),
            _shell("ams-color-2-f0f10a", "inlay", 2, _slab(B, 0.2, 0.4))]


def setup():
    return Setup(PLATE, FLOW, 0.2, 0.075, frozenset({2}))


def header(colours=HEXES[:3], filament="1,2,3"):
    return ("; HEADER_BLOCK_START\n; model printing time: 1m 2s; total estimated time: "
            f"1h 3m 4s\n; filament: {filament}\n; HEADER_BLOCK_END\n; CONFIG_BLOCK_START\n"
            f"; filament_colour = {';'.join(c.upper() for c in colours)}\n"
            "; CONFIG_BLOCK_END\n")


def start(*loads):
    """The fixtures' Custom start, then the A1 start load(s) and its T1000."""
    text = START + "M620 M ;enable remap\n"
    for t in loads:
        text += f"M620 S{t}A\n    T{t}\nG92 E0\nG1 E50 F200\nM621 S{t}A\n"
    return text + "M83\nT1000\n"


def change(n, z, flush=(23.7, 4.1)):
    """One A1 tool change to T<n> at layer height z, with a flush of these E-only moves."""
    total = sum(flush)
    body = "".join(f"G1 E{e} F523\n" for e in flush)
    return ("; FEATURE: Prime tower\n; LINE_WIDTH: 0.5\n; CP TOOLCHANGE START\n"
            f"; WIPE_TOWER_START\nG1 E-1.2 F1800\nM620 S{n}A\nG392 S0\nG1 X267 F18000\n"
            f"M620.10 A0 F523\nT{n}\nM620.10 A1 F523 L{total:g} H0.4 T240\nG1 Y128 F9000\n"
            "G92 E0\nG1 E18 F523\nG92 E0\n"
            f"; FLUSH_START\n{body}; FLUSH_END\nG1 E-2 F1800\nG1 E2 F300\n"
            "M622 J1\nG1 E-2 F1800\nM623\n"
            f"M621 S{n}A\nG392 S0\nG1 X20 Y220 F42000\nG1 Z{z:.3f}\nG1 E2 F1800\nG4 S0\n"
            f"G3 Z{z + 0.4:.3f} I1.217 J0 P1 F42000\nG1 Z{z:.3f}\n"
            "G1 X25 Y220 E0.2\nG3 X25 Y221 I0 J0.5 E0.05\nG4 S0\n; WIPE_TOWER_END\n"
            "; CP TOOLCHANGE END\n")


def prints(region):
    """Model beads that cover region, placed as the slicer places the 20 mm model."""
    return solid(placed(region, SQUARE))


END = ("; FEATURE: Custom\n; filament end gcode\nM620 S255\nG1 X267 F15000\nT255\n"
       "M621 S255\nG1 E-.8\n")


def text_of(steps1, steps2, loads=(0,), head=None, end=END):
    """Two layers; each step is a region (print it with the current tool), a tool number
    (change to it) or G-code text (written as it is)."""
    out = head if head is not None else header()
    out += start(*loads)
    for z, steps in ((0.2, steps1), (0.4, steps2)):
        body = "".join(change(s, z) if isinstance(s, int) else s if isinstance(s, str)
                       else prints(s) for s in steps)
        out += layer(z, body)
    return out + end


GOOD = {"steps1": [SQUARE], "steps2": [RING, 1, A, 2, B]}


def run(text, shells=None, statistics=None):
    checks, record = color_slice_checks(text.encode(), shells or bodies(), setup(), statistics)
    json.dumps([c.as_dict() for c in checks], allow_nan=False)
    json.dumps(record, allow_nan=False)
    return {c.id: c for c in checks}, record


def status(checks, ids=GATED_CHECK_IDS):
    return [checks[i].status for i in ids]


# --- Expected values from the bodies -----------------------------------------------------


def test_layer_sets_use_the_mid_height_strictly_inside_each_body():
    mc = read_multicolor(text_of(**GOOD), PLATE, FLOW)
    assert layer_sets(mc.layers, bodies()) == [[0], [0, 1, 2]]
    down = turn_over(bodies())
    assert layer_sets(mc.layers, down) == [[0, 1, 2], [0]]


@pytest.mark.parametrize(("sets", "loaded", "expected"), [
    ([[0], [0, 1, 2]], 0, 2),
    ([[0, 1, 2], [0]], 0, 3),          # starting on the base, layer 1 cannot end on it
    ([[0, 1, 2], [0]], 2, 2),          # 2 -> 1 -> 0
    ([[0, 1, 2], [0]], 3, 3),          # the loaded tool is on no layer
    ([[0, 1], [0, 1], [0]], 1, 3),     # 1 0 | 0 1 | 0: no order ends layer 2 on 0 for free
    ([[0], [], [1]], 0, 1),
])
def test_min_changes_is_the_exact_minimum(sets, loaded, expected):
    assert min_changes(sets, loaded) == _brute(sets, loaded) == expected


def _brute(sets, loaded):
    """The minimum over every order of every layer (each tool once per layer)."""
    from itertools import permutations, product
    return min(_count(orders, loaded)
               for orders in product(*[list(permutations(s)) for s in sets if s]))


def _count(orders, loaded):
    prev, n = loaded, 0
    for o in orders:
        n += (len(o) - 1) + (1 if o[0] != prev else 0)
        prev = o[-1]
    return n


# --- A correct print ----------------------------------------------------------------------


def test_a_correct_two_layer_print_passes():
    checks, record = run(text_of(**GOOD))
    assert status(checks) == ["PASS"] * 3, [checks[i].note for i in GATED_CHECK_IDS]
    assert status(checks, F3_SLICE_CHECK_IDS) == ["PASS"] * 3, [
        checks[i].note for i in F3_SLICE_CHECK_IDS]
    m = checks[COLOR_CHANGES].measured
    assert (m["changes"], m["rule_c_count"], m["start_load"], m["layer_1_first_tool"]) == (
        2, 2, 0, 0)
    assert m["info_minimum_from_start_load"] == 2 and m["end_unload"] == [255]
    assert [lay["order"] for lay in record["layers"]] == [[0], [0, 1, 2]]
    assert [lay["bodies"] for lay in record["layers"]] == [[0], [0, 1, 2]]
    assert checks[TOOL_PLACEMENT].measured["tools"]["1"]["layers"] == [2]
    assert checks[TOOL_PLACEMENT].measured["tools"]["0"]["layers"] == [1, 2]
    # The placement is fixed: centred on the plate, not turned (Task 2's measurement).
    assert checks[TOOL_PLACEMENT].measured["angle_deg"] == 0
    assert record["silhouette"]["alignment"]["angle_deg"] == 0
    assert [t["angle_deg"] for t in record["silhouette"]["alignment"]["scores"]] == [0]
    # The owner's "Outer edge only" (Task 7, 2026-11-13): the silhouette's coverage and
    # overprint and each tool's overprint are required; the rest of F3 are warnings.
    required = required_check_ids(3)
    assert required == frozenset((*GATED_CHECK_IDS, "F3.edge_coverage", "F3.edge_overprint",
                                  *(per_tool_id("F3.edge_overprint", t) for t in range(3))))
    warnings = set(f3_warning_ids(3))
    assert warnings == {"F3.printed_connectivity", *(
        per_tool_id(c, t) for t in range(3)
        for c in ("F3.printed_connectivity", "F3.edge_coverage"))}
    assert not warnings & required
    assert all("Required for PRINTABLE" in checks[i].note and "Outer edge only"
               in checks[i].note for i in required if i.startswith("F3."))
    assert all("A warning, recorded and not required" in checks[i].note for i in warnings)
    assert not required & set(INFO_CHECK_IDS)
    assert verdict(list(checks.values()), set(required)) == "PRINTABLE"
    for cid in INFO_CHECK_IDS:
        assert checks[cid].status == "UNKNOWN" and "information only" in checks[cid].note
    assert checks[TOOL_PLACEMENT].measured["prime_tower_into_model_mm"] is None


def test_the_information_measures_are_read_from_the_gcode():
    checks, record = run(text_of(**GOOD))
    area = math.pi * 1.75 ** 2 / 4
    waste = checks[COLOR_WASTE].measured
    assert waste["flush_mm3"] == pytest.approx(2 * (23.7 + 4.1) * area)
    assert waste["flush_length_L_mm"] == [pytest.approx(27.8)] * 2
    assert [f["tool"] for f in waste["flush_by_tool"]] == [0, 1, 2]
    assert waste["flush_by_tool"][0]["mm3"] == 0.0
    assert waste["prime_tower_mm3"] == pytest.approx(2 * 0.25 * area)
    # Other E-only E in the change: the 18 mm refill, the 2 mm unretract twice.
    assert waste["other_e_only_in_changes_mm3"] == pytest.approx(2 * 22 * area)
    time = checks[COLOR_TIME].measured
    assert (time["model_printing_time_s"], time["total_estimated_time_s"]) == (62, 3784)
    model = checks[COLOR_FILAMENT].measured["model_by_tool"]
    assert all(f["mm3"] > 0 for f in model)
    assert [c["from"] for c in record["toolchanges"]] == [0, 1]
    assert [c["to"] for c in record["toolchanges"]] == [1, 2]


def test_the_statistics_are_recorded_beside_the_gcode():
    stats = {"summary": {"filament_changes": 2, "time": 3784.2, "filaments": [
        {"id": 1, "model": {"volume": 10.0}, "prime_tower": {"volume": 1.0},
         "flush": {"volume": 2.0}}]}}
    checks, _ = run(text_of(**GOOD), statistics=stats)
    assert checks[COLOR_CHANGES].measured["info_statistics_filament_changes"] == 2
    assert checks[COLOR_TIME].measured["statistics_time_s"] == 3784.2
    assert checks[COLOR_WASTE].measured["statistics"] == [
        {"id": 1, "prime_tower_mm3": 1.0, "flush_mm3": 2.0}]
    assert checks[COLOR_FILAMENT].measured["statistics"] == [{"id": 1, "model_mm3": 10.0}]


def test_face_down_with_another_start_load_passes_and_records_the_minimum():
    down = turn_over(bodies())
    # Turned over, layer 1 holds every body; the start code loads T2, the first tool there.
    a, b, ring = (placed_turned(g) for g in (A, B, RING))
    text = text_of([b, 1, a, 0, ring], [SQUARE], loads=(2,))
    checks, _ = run(text, down)
    assert status(checks) == ["PASS"] * 3, [checks[i].note for i in GATED_CHECK_IDS]
    m = checks[COLOR_CHANGES].measured
    assert (m["changes"], m["start_load"], m["info_minimum_from_start_load"]) == (2, 2, 2)
    # Ending layer 1 away from the base costs one more change than the minimum: still PASS.
    text = text_of([b, 0, ring, 1, a], [0, SQUARE], loads=(2,))
    checks, _ = run(text, down)
    assert status(checks) == ["PASS"] * 3, [checks[i].note for i in GATED_CHECK_IDS]
    m = checks[COLOR_CHANGES].measured
    assert (m["changes"], m["rule_c_count"], m["info_minimum_from_start_load"]) == (3, 3, 2)


def placed_turned(region):
    """region of the face-up model where it lies face down (x -> 20 - x)."""
    return shapely.affinity.scale(region, xfact=-1, origin=(10, 10))


# --- Faults with known answers -------------------------------------------------------------


def test_a_change_too_many_fails_color_changes_only():
    checks, _ = run(text_of([SQUARE], [RING, 1, A, 2, B, 1]))
    assert status(checks) == ["FAIL", "PASS", "PASS"]
    assert "3 tool changes where the order needs 2" in checks[COLOR_CHANGES].note


def test_a_tool_on_the_wrong_layer_fails():
    small = shapely.box(3, 7, 5, 9)
    checks, _ = run(text_of([SQUARE, 1, small], [A, 0, RING, 2, B]))
    assert status(checks)[:2] == ["FAIL", "FAIL"]
    assert "layer 1: tools [0, 1]" in checks[COLOR_CHANGES].note
    assert "T1 prints on layer 1, where its body is not" in checks[TOOL_PLACEMENT].note


def test_a_tool_outside_its_body_fails_tool_placement():
    moved = shapely.affinity.translate(A, 3, 0)
    checks, _ = run(text_of([SQUARE], [RING, 1, moved, 2, B]))
    assert status(checks) == ["PASS", "FAIL", "PASS"]
    assert "T1 prints" in checks[TOOL_PLACEMENT].note and "outside its body" in checks[
        TOOL_PLACEMENT].note
    assert checks[TOOL_PLACEMENT].measured["tools"]["1"]["max_outside_mm"] > 2.5


def test_a_tool_just_over_the_allowance_fails_and_just_under_passes():
    # The inlay's beads moved out by 0.3 mm (over 0.2) and by 0.1 mm (under, with the
    # sampling bound 0.06 mm). Its neighbour's plastic is not its own: the base's ring is
    # judged against the base.
    for dx, want in ((0.3, "FAIL"), (0.1, "PASS")):
        moved = shapely.affinity.translate(A, -dx, 0)
        checks, _ = run(text_of([SQUARE], [RING, 1, moved, 2, B]))
        assert checks[TOOL_PLACEMENT].status == want, (dx, checks[TOOL_PLACEMENT].note)


def test_a_missing_body_on_a_layer_fails():
    checks, _ = run(text_of([SQUARE], [RING, 1, A]))
    assert status(checks) == ["FAIL", "FAIL", "FAIL"]
    assert "the body of T2 is on layer 2, but T2 does not print there" in checks[
        TOOL_PLACEMENT].note
    assert "loads tools [0, 1]" in checks[FILAMENTS_USED].note


def test_an_extra_filament_fails():
    # T3 prints the second inlay where the plan has T2 for it.
    checks, _ = run(text_of([SQUARE], [RING, 1, A, 3, B], head=header(HEXES, "1,2,3,4")))
    assert status(checks) == ["FAIL", "FAIL", "FAIL"]
    assert "tools [3] print model features but print no body" in checks[TOOL_PLACEMENT].note
    note = checks[FILAMENTS_USED].note
    assert "loads tools [0, 1, 3]" in note and "header lists filaments" in note
    # Four filaments configured although three print: still a FAIL.
    checks, _ = run(text_of(**GOOD, head=header(HEXES, "1,2,3")))
    assert checks[FILAMENTS_USED].status == "FAIL"
    assert "filament_colour" in checks[FILAMENTS_USED].note


def test_a_wrong_filament_colour_fails():
    checks, _ = run(text_of(**GOOD, head=header([HEXES[0], HEXES[2], HEXES[1]])))
    assert status(checks) == ["PASS", "PASS", "FAIL"]


def test_no_filament_lines_leave_filaments_used_unknown():
    checks, _ = run(text_of(**GOOD, head=""))
    assert checks[FILAMENTS_USED].status == "UNKNOWN"


def test_a_tool_returning_within_a_layer_fails():
    checks, _ = run(text_of([SQUARE], [RING.difference(shapely.box(0, 0, 20, 4)), 1, A, 0,
                                       shapely.box(0, 0, 20, 4), 2, B]))
    assert checks[COLOR_CHANGES].status == "FAIL"
    note = checks[COLOR_CHANGES].note
    assert "more than one run" in note and "3 tool changes where the order needs 2" in note


def test_two_loads_in_the_start_block_fail():
    checks, _ = run(text_of(**GOOD, loads=(1, 0)))
    assert checks[COLOR_CHANGES].status == "FAIL"
    assert "loads 2 filaments ([1, 0])" in checks[COLOR_CHANGES].note


def test_a_start_load_that_is_not_the_first_tool_of_layer_1_fails():
    checks, _ = run(text_of([0, SQUARE], [RING, 1, A, 2, B], loads=(1,)))
    assert checks[COLOR_CHANGES].status == "FAIL"
    note = checks[COLOR_CHANGES].note
    assert "loads T1, but layer 1 starts with T0" in note
    assert "tool changes where" not in note         # rule (c) holds: 3 = 0 + 1 + 2


@pytest.mark.parametrize(("raw", "message"), [
    # A bare change: no M620 pair, no CP TOOLCHANGE block.
    ("T1\n", "change to T1 is not inside M620 S1A"),
    # In its M620 pair but outside a CP TOOLCHANGE block.
    ("M620 S1A\nT1\nM621 S1A\n", "change to T1 is not inside"),
    # In a CP TOOLCHANGE block but inside another tool's M620 pair.
    ("; CP TOOLCHANGE START\nM620 S2A\nT1\nM621 S2A\n; CP TOOLCHANGE END\n",
     "change to T1 is not inside M620 S1A"),
])
def test_a_change_outside_the_change_sequence_fails(raw, message):
    checks, _ = run(text_of([SQUARE], [RING, raw, A, 2, B]))
    assert checks[COLOR_CHANGES].status == "FAIL", checks[COLOR_CHANGES].note
    assert message in checks[COLOR_CHANGES].note
    assert checks[TOOL_PLACEMENT].status == "PASS"


def test_a_load_in_the_end_code_fails():
    end = END.replace("M620 S255", "M620 S1A\nT1\nM621 S1A\nM620 S255")
    checks, _ = run(text_of(**GOOD, end=end))
    assert checks[COLOR_CHANGES].status == "FAIL"
    assert "the end code loads filament(s) [1]" in checks[COLOR_CHANGES].note


# --- What cannot be read is UNKNOWN, never PASS -------------------------------------------


def _all_unknown(checks):
    gated = [checks[i].status for i in (*GATED_CHECK_IDS, *F3_SLICE_CHECK_IDS)]
    return gated == ["UNKNOWN"] * 6


@pytest.mark.parametrize(("old", "new", "reason"), [
    ("G4 S0\n", "G4 X1\n", "not a dwell"),                                  # in the tower
    ("G3 X25 Y221 I0 J0.5 E0.05", "G3 X25 Y221 R0.5 E0.05", "R-form"),
    ("G3 X25 Y221 I0 J0.5 E0.05", "G5 X25 Y221 I0 J0.5 E0.05", "G5"),
    ("G1 E23.7 F523", "G1 Z1 E23.7 F523", "not an E-only extrusion"),       # Z in a flush
    ("G1 E23.7 F523", "G1 E-23.7 F523", "not an E-only extrusion"),         # retract
    ("M621 S1A", "M621 S2A", "does not close the open M620"),
    ("M620 S1A", "M620 S1", "not an M620 form"),
    ("; CP TOOLCHANGE END\n", "; CP TOOLCHANGE END\n; FLUSH_START\n; FLUSH_END\n",
     "FLUSH_START outside"),
    ("    T0\n", "    T0\n    T1001\n", "T1001"),
    ("T1\n", "T1 S1\n", "a tool command with words"),
    ("G1 X267 F18000\n", "G1 X267 F18000\nT1000\n", "T1000 outside the start code"),
    ("; Z_HEIGHT: 0.4\n", "; Z_HEIGHT: 0.4\n; Z_HEIGHT: 0.6\n", "Z_HEIGHT"),
    ("T255\n", "T255\n; CHANGE_LAYER\n", "a layer after the end code began"),
    ("M620 S255\n", "", "T255"),
])
def test_what_the_reader_cannot_read_makes_every_check_unknown(old, new, reason):
    text = text_of(**GOOD)
    assert old in text
    checks, record = run(text.replace(old, new, 1))
    assert _all_unknown(checks), [(c.id, c.status) for c in checks.values()]
    assert reason in record["reason"], record["reason"]


def test_no_gcode_or_a_failed_slice_is_unknown():
    for gcode, why in ((None, None), (b"", None), (text_of(**GOOD).encode(), "the slicer failed")):
        checks, record = color_slice_checks(gcode, bodies(), setup(), not_measured=why)
        assert all(c.status == "UNKNOWN" for c in checks)
        assert record["measured"] is False and record["reason"]
        assert len(checks) == 3 + 3 + 3 * 3 + 3


def test_not_utf8_is_unknown():
    checks, record = color_slice_checks(b"\xff\xfe", bodies(), setup())
    assert all(c.status == "UNKNOWN" for c in checks) and "UTF-8" in record["reason"]


def test_a_model_extrusion_before_any_load_fails_and_is_not_a_filament():
    text = text_of(**GOOD).replace("M620 S0A\n    T0\nG92 E0\nG1 E50 F200\nM621 S0A\n", "")
    checks, _ = run(text)
    assert status(checks) == ["FAIL", "FAIL", "FAIL"]
    assert "tools [None] print model features" in checks[TOOL_PLACEMENT].note


def test_r1_gcode_is_read_by_r1_unchanged():
    # The reader's prime-tower mode is not R1's: a tool change in R1 G-code stays refused.
    from tdmg.printed import parse_gcode
    with pytest.raises(UnsupportedGcode):
        parse_gcode(text_of(**GOOD), PLATE, FLOW)


# --- Review fixes (2026-11-13): F3 required, the tower, the turn ambiguity ----------------


def printable(checks, tools=3):
    return verdict(list(checks.values()), set(required_check_ids(tools))) == "PRINTABLE"


@pytest.mark.parametrize(("steps1", "steps2", "caught", "warned"), [
    # half of inlay 1: only its own coverage warns
    ([SQUARE], [RING, 1, shapely.box(2, 6, 5, 14), 2, B], [], ["F3.edge_coverage.T1"]),
    # only a dot of inlay 1: its coverage and the silhouette's connectivity warn
    ([SQUARE], [RING, 1, shapely.box(4, 9, 5, 10), 2, B], [],
     ["F3.printed_connectivity", "F3.edge_coverage.T1"]),
    # half the base's layer 1: still caught by the silhouette's required coverage
    ([shapely.box(0, 0, 20, 10)], [RING, 1, A, 2, B], ["F3.edge_coverage"],
     ["F3.edge_coverage.T0"]),
], ids=["half inlay", "dot inlay", "half base L1"])
def test_a_body_left_partly_unprinted_after_the_owner_decision(steps1, steps2, caught,
                                                               warned):
    """The F6 checks pass these: they judge plastic outside a body, not a body left
    unprinted. Under "Outer edge only" (owner, 2026-11-13) half the base's first layer is
    still caught by a required check; half an inlay and a dot of one only warn (the
    trade-off the owner accepted)."""
    checks, _ = run(text_of(steps1, steps2))
    assert status(checks) == ["PASS"] * 3
    failed = [i for i in sorted(required_check_ids(3)) if checks[i].status != "PASS"]
    assert failed == caught
    assert [i for i in f3_warning_ids(3) if checks[i].status != "PASS"] == warned
    assert printable(checks) == (not caught)


def _tower_line(y):
    """A prime-tower bead along the model's lower edge (model y = y), outside any change."""
    return path_moves(placed(shapely.LineString([(2, y), (18, y)]), SQUARE).coords,
                      feature="Prime tower")


def test_prime_tower_beads_over_the_model_fail_tool_placement():
    blob = re.sub(r"; FEATURE: [^\n]*", "; FEATURE: Prime tower", prints(B))
    checks, _ = run(text_of([SQUARE], [RING, 1, A, blob, 2, B]))
    assert checks[TOOL_PLACEMENT].status == "FAIL"
    assert "the prime tower reaches" in checks[TOOL_PLACEMENT].note
    assert checks[TOOL_PLACEMENT].measured["prime_tower_into_model_mm"] > 2


@pytest.mark.parametrize(("y", "want"), [
    (-0.4, "PASS"),     # the bead (0.42 mm) stays outside the model
    (-0.1, "PASS"),     # 0.11 mm in: within 0.2 mm, with the 0.06 mm sampling bound
    (0.1, "FAIL"),      # 0.31 mm in
])
def test_the_prime_tower_gets_the_tools_allowance(y, want):
    checks, _ = run(text_of([SQUARE], [RING, 1, A, 2, B, _tower_line(y)]))
    assert checks[TOOL_PLACEMENT].status == want, checks[TOOL_PLACEMENT].note


def test_a_tool_change_inside_a_flush_fails_tool_placement():
    # A T2 inside the first change's flush: T2 then prints inlay 1.
    raw = change(1, 0.4).replace("; FLUSH_START\n", "; FLUSH_START\nT2\n", 1)
    checks, _ = run(text_of([SQUARE], [RING, raw, A, 2, B]))
    assert checks[TOOL_PLACEMENT].status == "FAIL", checks[TOOL_PLACEMENT].note


def _turned(region, angle):
    return shapely.affinity.rotate(region, angle, origin=(10, 10))


def test_swapped_inlay_colours_fail_tool_placement():
    # T1 prints inlay 2's place and T2 inlay 1's: the same G-code as a correct print turned
    # 180 degrees (the square silhouette and the inlays are symmetric under that turn).
    checks, _ = run(text_of([SQUARE], [RING, 1, B, 2, A]))
    assert checks[TOOL_PLACEMENT].status == "FAIL"
    assert "T1 prints" in checks[TOOL_PLACEMENT].note
    assert status(checks)[0::2] == ["PASS", "PASS"]


@pytest.mark.parametrize("angle", [90, 180, 270])
def test_a_correct_print_turned_by_a_quarter_turn_fails(angle):
    checks, _ = run(text_of([_turned(SQUARE, angle)],
                            [_turned(RING, angle), 1, _turned(A, angle), 2,
                             _turned(B, angle)]))
    assert checks[TOOL_PLACEMENT].status == "FAIL", checks[TOOL_PLACEMENT].note


def test_a_geometry_error_is_unknown_and_keeps_the_other_checks(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(color_gcode, "analyse_sections", boom)
    checks, record = run(text_of(**GOOD))
    geometry = [TOOL_PLACEMENT, *f3_required_ids(3)]
    assert all(checks[i].status == "UNKNOWN" for i in geometry)
    assert "analysis error: RuntimeError: boom" in record["geometry_reason"]
    assert checks[COLOR_CHANGES].status == "PASS" and checks[FILAMENTS_USED].status == "PASS"
    assert not printable(checks)


def test_a_model_with_no_section_at_the_first_layer_is_unknown():
    lifted = [Shell(s.name, s.role, s.index, s.hex,
                    (np.asarray(s.vertices, np.float64) + [0, 0, 0.2]).astype(np.float32),
                    s.faces) for s in bodies()]
    checks, record = run(text_of(**GOOD), lifted)
    assert "no section at the first layer" in record["geometry_reason"]
    assert all(checks[i].status == "UNKNOWN" for i in [TOOL_PLACEMENT, *f3_required_ids(3)])
    assert checks[COLOR_CHANGES].status == "FAIL"       # layer 1 holds no body


@pytest.mark.parametrize("command", ["M600", "M601"])
def test_a_manual_filament_change_or_pause_is_unknown(command):
    checks, record = run(text_of([SQUARE], [RING, 1, A, f"{command}\n", 2, B]))
    assert _all_unknown(checks) and command in record["reason"]


# --- Codex review 5: firmware conditionals and the flush position -----------------------

# What the firmware may skip (M622 J<n> ... M623) cannot be known to print. The three cases
# Codex review 5 (finding 1) ran: each passed every required check before the fix.


def test_an_inlay_inside_a_conditional_block_is_unknown():
    checks, record = run(text_of([SQUARE], [RING, 1, "M622 J1\n", A, "M623\n", 2, B]))
    assert _all_unknown(checks), [(c.id, c.status) for c in checks.values()]
    assert "conditional" in record["reason"]


def test_a_tool_change_inside_a_conditional_block_is_unknown():
    wrapped = "M622 J1\n" + change(1, 0.4) + "M623\n"
    checks, record = run(text_of([SQUARE], [RING, wrapped, A, 2, B]))
    assert _all_unknown(checks), [(c.id, c.status) for c in checks.values()]
    assert "conditional" in record["reason"]


def test_a_mode_set_only_inside_a_conditional_block_is_unknown_after_it():
    # G91 and M82 before the block, G90 and M83 inside it: after M623 the printer is in
    # either mode, so the next move cannot be read, even with X, Y and Z restored.
    block = "G91\nM82\nM622 J1\nG90\nM83\nM623\n"
    checks, record = run(text_of([SQUARE], [RING, block, 1, A, 2, B]))
    assert _all_unknown(checks), [(c.id, c.status) for c in checks.values()]
    assert "mode" in record["reason"]


def test_a_mode_inside_a_conditional_that_equals_the_mode_before_is_read():
    # As the A1 start code and time-lapse blocks write it (research record,
    # measure_conditionals.py): G90 and M83 inside, the same as before the block.
    block = "M622 J1\nG90\nM83\nG92 E0\nM623\nG1 X0 Y0 Z.4\n"
    checks, _ = run(text_of([SQUARE], [RING, block, 1, A, 2, B]))
    assert status(checks) == ["PASS"] * 3


@pytest.mark.parametrize(("raw", "reason"), [
    ("M622 J1\n", "without its M623"),
    ("M623\n", "M623 without"),
    ("M622 J1\nM620 S1A\nM621 S1A\nM623\n", "conditional"),
])
def test_unpaired_conditionals_and_loads_inside_them_are_unknown(raw, reason):
    checks, record = run(text_of([SQUARE], [RING, 1, A, 2, B, raw]))
    assert _all_unknown(checks) and reason in record["reason"], record["reason"]


def test_a_flush_inside_the_model_fails_tool_placement():
    # Codex review 5, finding 2: the flush moved to X128 Y128 Z0.4, inside the model.
    text = text_of(**GOOD).replace("G1 X267 F18000\n", "G1 X128 Z0.4 F18000\n")
    checks, _ = run(text)
    c = checks[TOOL_PLACEMENT]
    assert c.status == "FAIL" and "flush" in c.note, c.note
    assert c.measured["flushes"][0]["at_bed_mm"] == [128.0, 128.0]


def test_a_flush_just_beside_the_model_gets_the_tools_allowance():
    # The model spans bed x 118 to 138; a flush at x 138.1 is 0.1 mm away (FAIL, within
    # 0.2 mm), at x 138.5 0.5 mm away (PASS).
    for x, want in ((138.1, "FAIL"), (138.5, "PASS")):
        text = text_of(**GOOD).replace("G1 X267 F18000\n", f"G1 X{x} F18000\n")
        checks, _ = run(text)
        assert checks[TOOL_PLACEMENT].status == want, (x, checks[TOOL_PLACEMENT].note)


def test_a_flush_from_an_unknown_position_leaves_tool_placement_unknown():
    text = text_of(**GOOD).replace("; FLUSH_START\n", "M622 J1\nM623\n; FLUSH_START\n")
    checks, _ = run(text)
    c = checks[TOOL_PLACEMENT]
    assert c.status == "UNKNOWN" and "unknown position" in c.note, c.note


def test_the_real_flush_position_off_the_bed_passes():
    checks, _ = run(text_of(**GOOD))
    flushes = checks[TOOL_PLACEMENT].measured["flushes"]
    assert [f["at_bed_mm"] for f in flushes] == [[267.0, 128.0]] * 2
    assert all(f["from_model_mm"] > 100 for f in flushes)


# --- Real slicer ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
OWNER_PLAN = REPO / "artifacts/colored-runs/roadie-tol30-60-drop-v3-f64"


def owner_or_synthetic_shells():
    """The owner's Roadie drop plan, when its artifacts are here (git-ignored, not in CI);
    otherwise a small synthetic plan (tests/test_threemf.gated_shells)."""
    if (OWNER_PLAN / "palette.json").is_file():
        from tdmg.checks import merge_exact
        pal = json.loads((OWNER_PLAN / "palette.json").read_text("utf-8"))
        shells = []
        for s in sorted(pal["shells"], key=lambda s: s["shell"]):
            m = merge_exact(trimesh.load(io.BytesIO((OWNER_PLAN / f"{s['body']}.stl")
                                                    .read_bytes()), file_type="stl",
                                         process=False))
            shells.append(Shell(s["body"], s["role"], s["index"], s["hex"],
                                np.asarray(m.vertices, np.float32),
                                np.asarray(m.faces, np.int64)))
        return "owner", shells
    from test_threemf import gated_shells
    return "synthetic", gated_shells("box")


def slice_colors(shells, tmp_path):
    """Slice orca-input.3mf of these shells with the pinned OrcaSlicer, the fixed A1
    profiles and one derived filament per body (the pinned profile with filament_colour
    set to its color), as Task 2 did; returns (G-code bytes, statistics, setup)."""
    from tdmg import slicer
    from tdmg.orca_input import write_orca_input
    from tdmg.printed import flow_from_profile, plate_from_profile
    from tdmg.rules import load_rules
    from tdmg.slicing import elephant_foot_mm

    pin = slicer.load_pin()
    orc = slicer.locate(os.environ["TDMG_ORCASLICER_DIR"], pin, full_tree=False)
    model = tmp_path / "orca-input.3mf"
    model.write_bytes(write_orca_input(shells))
    pinned = json.loads(Path(orc.profiles["filament"]).read_text("utf-8"))
    filaments = []
    for i, s in enumerate(shells):
        p = tmp_path / f"filament-{i}.json"
        p.write_text(json.dumps({**pinned, "filament_colour": [s.hex.upper()]}), "utf-8")
        filaments.append(str(p))
    out = tmp_path / "out"
    out.mkdir()
    args = [str(orc.exe), str(model), "--load-settings",
            f"{orc.profiles['machine']};{orc.profiles['process']}",
            "--load-filaments", ";".join(filaments), "--slice", "0", "--outputdir", str(out),
            "--export-statistics", "--logfile", str(tmp_path / "slicer.log")]
    rc, timed_out, _, err = slicer.run_process(args, tmp_path, 900)
    assert not timed_out and slicer.decode_exit(rc, slicer.platform_key(), pin)["signed"] == 0, (
        slicer.output_tail(err))
    machine = json.loads(Path(orc.profiles["machine"]).read_text("utf-8"))
    process = json.loads(Path(orc.profiles["process"]).read_text("utf-8"))
    tolerance = float(load_rules()["acceptance.dimension.tolerance"].default)
    top = max(float(np.asarray(s.vertices, np.float32).max(axis=0)[2]) for s in shells)
    layers = slicer.expected_layer_counts(top, process)
    st = Setup(plate_from_profile(machine), flow_from_profile(pinned), tolerance,
               elephant_foot_mm(process), frozenset(layers))
    stats = json.loads((out / slicer.STATS_NAME).read_bytes())
    return (out / slicer.GCODE_NAME).read_bytes(), stats, st


@pytest.mark.slicer
@pytest.mark.skipif(not os.environ.get("TDMG_ORCASLICER_DIR"),
                    reason="TDMG_ORCASLICER_DIR is not set to a verified OrcaSlicer install")
@pytest.mark.parametrize("face", ["up", "down"])
def test_the_real_slicer_passes_all_three_checks(face, tmp_path):
    kind, shells = owner_or_synthetic_shells()
    if face == "down":
        shells = turn_over(shells)
    gcode, stats, st = slice_colors(shells, tmp_path)
    checks, record = color_slice_checks(gcode, shells, st, stats)
    by = {c.id: c for c in checks}
    assert [by[i].status for i in GATED_CHECK_IDS] == ["PASS"] * 3, (
        kind, [by[i].note for i in GATED_CHECK_IDS])
    assert record["measured"] and record["geometry_reason"] is None
    m = by[COLOR_CHANGES].measured
    assert m["changes"] == m["info_statistics_filament_changes"]
    assert by[COLOR_WASTE].measured["prime_tower_mm3"] > 0
    assert by[TOOL_PLACEMENT].measured["prime_tower_into_model_mm"] is None
    # Under the owner's "Outer edge only" (Task 7, 2026-11-13) the silhouette's
    # connectivity is a warning: it still FAILs on every multicolor layer (neighbouring
    # bodies' beads meet edge to edge; research record, Task 5 addendum). The Roadie drop
    # plan is PRINTABLE face up; face down its silhouette edge coverage is UNKNOWN (0.251
    # against 0.275 mm, Task 5), so it is not. The synthetic plan: PRINTABLE both faces.
    required = required_check_ids(len(shells))
    want = "NOT CERTIFIED" if (kind, face) == ("owner", "down") else "PRINTABLE"
    assert verdict(checks, set(required)) == want, (
        kind, face, [(i, by[i].status) for i in sorted(required) if by[i].status != "PASS"])
    not_passing = [i for i in sorted(required) if by[i].status != "PASS"]
    assert all(i.startswith("F3.") for i in not_passing), not_passing
    assert by["F3.printed_connectivity"].status == "FAIL", (kind, by[
        "F3.printed_connectivity"].note)
    json.dumps([c.as_dict() for c in checks], allow_nan=False)

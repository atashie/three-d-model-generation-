"""The OrcaSlicer-only slicing input (tdmg.orca_input): the face-down turn, the
orca-input.3mf writer, and its gate check F2.orca_input_matches_bodies
(tdmg.color_checks.orca_input_check).

docs/plans/2026-11-13-color-slicing.md, Decisions 2 and 3, Tasks 3 and 4.
"""

import io

import numpy as np
import pytest
import trimesh
from test_threemf import gated, gated_shells, two_cubes

from tdmg.checks import _signed_volume, topology_checks
from tdmg.flat import encode_stl
from tdmg.orca_input import turn_over
from tdmg.threemf import Shell, ThreeMFError

CASES = ["box", "circle", "checker"]


def stacked(shells):
    return np.vstack([np.asarray(s.vertices, np.float64) for s in shells])


# --- Task 3: the face-down turn ----------------------------------------------------------


@pytest.mark.parametrize("case", CASES)
def test_turned_coordinates_are_the_exact_float32_values(case):
    shells = gated_shells(case)
    allv = stacked(shells)
    x0, x1, top = allv[:, 0].min(), allv[:, 0].max(), allv[:, 2].max()
    turned = turn_over(shells)
    for s, t in zip(shells, turned, strict=True):
        v = np.asarray(s.vertices, np.float64)
        tv = np.asarray(t.vertices)
        assert tv.dtype == np.float32
        # Task 2's construction: float64, then float32; the float64 value is a float32.
        want64 = np.column_stack([x0 + x1 - v[:, 0], v[:, 1], top - v[:, 2]])
        assert np.array_equal(want64.astype(np.float32).astype(np.float64), want64)
        assert np.array_equal(tv.astype(np.float64), want64)


@pytest.mark.parametrize("case", CASES)
def test_turned_bodies_pass_f1_as_the_gate_reads_them(case):
    for t in turn_over(gated_shells(case)):
        mesh = gated(trimesh.Trimesh(np.asarray(t.vertices, np.float64), t.faces,
                                     process=False))
        failed = [(c.id, c.measured) for c in topology_checks(mesh) if c.status != "PASS"]
        assert not failed, (t.name, failed)


@pytest.mark.parametrize("case", CASES)
def test_volumes_are_equal_and_windings_kept(case):
    shells = gated_shells(case)
    for s, t in zip(shells, turn_over(shells), strict=True):
        before = _signed_volume(np.asarray(s.vertices, np.float64), np.asarray(s.faces))
        after = _signed_volume(np.asarray(t.vertices, np.float64), np.asarray(t.faces))
        assert before > 0 and after > 0
        # The same solid; only the float64 sum's rounding differs (Task 2: ~1e-15 rel).
        assert after == pytest.approx(before, rel=1e-12, abs=0)
        assert np.array_equal(np.asarray(t.faces), np.asarray(s.faces))


@pytest.mark.parametrize("case", CASES)
def test_turning_twice_gives_the_original_exactly(case):
    shells = gated_shells(case)
    back = turn_over(turn_over(shells))
    for s, b in zip(shells, back, strict=True):
        assert (b.name, b.role, b.index, b.hex) == (s.name, s.role, s.index, s.hex)
        assert np.array_equal(np.asarray(b.vertices), np.asarray(s.vertices, np.float32))
        assert np.array_equal(np.asarray(b.faces), np.asarray(s.faces))


@pytest.mark.parametrize("case", CASES)
def test_inlays_sit_at_z0_to_the_skin_depth_and_extents_mirror(case):
    shells = gated_shells(case)
    allv = stacked(shells)
    x0, x1, top = allv[:, 0].min(), allv[:, 0].max(), allv[:, 2].max()
    turned = turn_over(shells)
    for s, t in zip(shells, turned, strict=True):
        v = np.asarray(s.vertices, np.float64)
        tv = np.asarray(t.vertices, np.float64)
        lo, hi = v.min(0), v.max(0)
        tlo, thi = tv.min(0), tv.max(0)
        assert (tlo[0], thi[0]) == (x0 + x1 - hi[0], x0 + x1 - lo[0])
        assert (tlo[1], thi[1]) == (lo[1], hi[1])
        assert np.array_equal(np.sort(tv[:, 1]), np.sort(v[:, 1]))
        # z: T - z exactly (T - float32(2.4) is 0.5999999..., not float32(0.6)).
        assert (tlo[2], thi[2]) == (top - hi[2], top - lo[2])
        if s.role == "inlay":
            assert tlo[2] == 0.0 and thi[2] == top - lo[2] and thi[2] < 1.0
        else:
            assert (tlo[2], thi[2]) == (0.0, top)
    # the whole model keeps its x bounds
    tall = stacked(turned)
    assert (tall[:, 0].min(), tall[:, 0].max()) == (x0, x1)


def test_the_two_cube_inlay_top_is_three_minus_float32_2_4():
    shells = two_cubes()   # base 0..2.4, inlay 2.4..3.0
    turned = turn_over(shells)
    inlay = np.asarray(turned[1].vertices)
    assert inlay[:, 2].min() == 0.0
    assert float(inlay[:, 2].max()) == 3.0 - float(np.float32(2.4))
    assert float(inlay[:, 2].max()) != float(np.float32(0.6))


def test_minus_zero_is_not_written():
    for s in turn_over(two_cubes()):
        v = np.asarray(s.vertices)
        assert not (np.signbit(v) & (v == 0)).any()


def _one_triangle(v):
    return [Shell("ams-base", "base", 0, "#000000", np.array(v, np.float32),
                  np.array([[0, 1, 2]]))]


def test_an_inexact_coordinate_is_refused():
    # x0 = float32(0.1) has bits down to 2^-27; 0.1 + 60 - 30 needs them at exponent 2^4,
    # where float32's last bit is 2^-19: not a float32 number.
    shells = _one_triangle([[0.1, 0, 0], [60, 0, 0], [30, 1, 1]])
    with pytest.raises(ThreeMFError, match="not exactly a float32"):
        turn_over(shells)


def test_a_model_not_standing_on_z0_is_refused():
    shells = _one_triangle([[0, 0, 0.5], [1, 0, 0.5], [0, 1, 1]])
    with pytest.raises(ThreeMFError, match="lowest z"):
        turn_over(shells)


def test_turn_over_refuses_what_the_writer_refuses():
    a, b = two_cubes()
    with pytest.raises(ThreeMFError, match="base first"):
        turn_over([b, a])


def test_the_turned_stl_parses_back_to_the_same_mesh():
    """The turned vertices are float32 numbers, so STL keeps them exactly."""
    for t in turn_over(gated_shells("circle")):
        mesh = trimesh.Trimesh(np.asarray(t.vertices, np.float64), t.faces, process=False)
        back = trimesh.load(io.BytesIO(encode_stl(mesh)), file_type="stl", process=False)
        tri = np.asarray(t.vertices, np.float64)[np.asarray(t.faces)]
        assert np.array_equal(np.asarray(back.triangles), tri)


def test_a_rounding_float64_sum_is_refused():
    from tdmg.orca_input import _exact_difference
    assert _exact_difference(np.array([3.0]), np.array([np.float32(2.4)]))[0] == (
        3.0 - float(np.float32(2.4)))
    with pytest.raises(ThreeMFError, match="rounds"):
        _exact_difference(np.array([1.0]), np.array([2.0 ** -60]))

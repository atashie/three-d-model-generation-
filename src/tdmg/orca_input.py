"""The OrcaSlicer-only slicing input (docs/plans/2026-11-13-color-slicing.md, Decisions 2
and 3, Tasks 3 and 4).

`tdmg slice` gives OrcaSlicer its own input file, built from the same gated AMS meshes
(tdmg.threemf.Shell) as the portable model.3mf: the OrcaSlicer CLI prints model.3mf
(encoding D) on one filament (step 3, research/verification/2026-11-12-color-3mf/), so it
cannot measure the color changes. This file is a slicer input, not a deliverable: the
file to print from stays model.3mf (docs/PLAN.md section 2 point 7).

This module holds what builds that input, apart from tdmg.threemf, whose guarantees are
about the portable deliverable:
- turn_over: the face-down bodies (Decision 3);
- write_orca_input: orca-input.3mf, encoding B_msc (Decision 2).
Its read-back gate check is tdmg.color_checks.orca_input_check.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from tdmg.threemf import Shell, ThreeMFError, check_shells


def _exact_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a - b in float64, refusing (ThreeMFError) any element where the float64 result is
    not the exact real difference. The rounding error of each subtraction is computed
    exactly by Knuth's TwoSum (valid in round-to-nearest without overflow, which the
    finite float32 inputs cannot reach)."""
    a = np.asarray(a, dtype=np.float64)
    nb = -np.asarray(b, dtype=np.float64)
    s = a + nb
    bv = s - a
    err = (a - (s - bv)) + (nb - bv)
    if np.any(err != 0):
        raise ThreeMFError("a turned coordinate is not exactly a float32 number "
                           "(its float64 sum rounds)")
    return s


def turn_over(shells: Sequence[Shell]) -> list[Shell]:
    """The face-down bodies: every shell rotated 180 degrees about the y axis through the
    model's centre (plan Decision 3): x -> x0 + x1 - x, y unchanged, z -> T - z, where x0,
    x1 are the model's x bounds over all shells and T is its top (its thickness: the model
    must stand on z = 0, or ThreeMFError).

    The rotation is proper (determinant +1), so the faces are kept as they are: windings
    stay outward and each closed, oriented shell stays closed and oriented by index.

    Guaranteed for every returned coordinate: it is the float32 number equal to the exact
    real value x0 + x1 - x (or T - z, or y), with no rounding anywhere. Each sum is done
    in float64 and its rounding error measured exactly (TwoSum); then the float64 result
    must be a float32 number. A coordinate that fails either test is refused with
    ThreeMFError, never rounded. The gated meshes pass: their coordinates lie on one
    storage grid G = 2^(e-24) (tdmg.color_geometry.storage_grid_mm), so x0 + x1 - x is a
    multiple of G within the model's x range, which float32 holds exactly (Task 2 measured
    0 inexact on all four owner plans). -0.0 cannot appear (an exact zero difference is
    +0.0 in round-to-nearest). Turning twice gives the original vertices exactly.

    Shells must be as tdmg.threemf.check_shells accepts them (it raises ThreeMFError);
    names, roles, indices and hexes are kept, and the order too.
    """
    shells = list(shells)
    arrays = check_shells(shells)
    allv = np.concatenate([v for v, _ in arrays])
    x0, x1 = np.float64(allv[:, 0].min()), np.float64(allv[:, 0].max())
    z0, top = np.float64(allv[:, 2].min()), np.float64(allv[:, 2].max())
    if z0 != 0:
        raise ThreeMFError(f"the model's lowest z is {z0!r}, not 0: it must stand on the "
                           f"bed to be turned over")
    span = _exact_difference(np.array([x0]), np.array([-x1]))[0]   # x0 + x1, exactly
    out = []
    for s, (v, f) in zip(shells, arrays, strict=True):
        v64 = v.astype(np.float64)
        turned = np.column_stack([_exact_difference(span, v64[:, 0]), v64[:, 1],
                                  _exact_difference(top, v64[:, 2])])
        t32 = turned.astype(np.float32)
        if not np.array_equal(t32.astype(np.float64), turned):
            raise ThreeMFError(f"shell {s.name!r}: a turned coordinate is not exactly a "
                               f"float32 number")
        out.append(Shell(s.name, s.role, s.index, s.hex, t32, f.copy()))
    return out

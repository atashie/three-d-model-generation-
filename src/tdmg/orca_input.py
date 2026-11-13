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
Its read-back gate check is tdmg.color_checks.orca_input_check. filament_map says which
filament prints which color: the body at position i in shell order (the base first, then
the inlays by palette index) is filament i + 1, for any base palette index.

Deliberate copy of what was sliced: [Content_Types].xml (tdmg.threemf's bytes) has no
entry for the .config extension of Metadata/model_settings.config. OPC wants a content
type for every part, so this departs from the standard, but it is exactly the package
the step 3 prototype wrote and Task 2 sliced (lib3mf strict reads it without a warning;
OrcaSlicer 2.5.0 applies its extruders). Adding the entry would be an unsliced change.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from lxml import etree

from tdmg.threemf import (
    NS_CORE,
    NS_M,
    NS_XML,
    PART_NAMES,
    UNIT,
    Shell,
    ThreeMFError,
    check_shells,
    color_3mf,
    f32_text,
    package,
)

ORCA_INPUT_NAME = "orca-input.3mf"
SETTINGS_PART = "Metadata/model_settings.config"
ORCA_PART_NAMES = (*PART_NAMES, SETTINGS_PART)   # the zip entries, in order
ASSEMBLY_NAME = "assembly"      # the components object's name, as in the sliced prototype
PART_SUBTYPE = "normal_part"
ENCODING = ("B_msc: one m:colorgroup per body (one m:color each); one mesh object per body "
            "(base first, then inlays by palette index), each with its colorgroup as its "
            "object-level property; one components object 'assembly' with one component "
            "per mesh object, no transforms; one build item on it; "
            "Metadata/model_settings.config giving each part extruder = its position in "
            "shell order + 1 (the base 1)")


def colorgroup_id(position: int) -> int:
    """Resource id of the colorgroup of the body at this position (0 = the base)."""
    return position + 1


def mesh_object_id(position: int, n: int) -> int:
    """Resource id of the mesh object of the body at this position, of n bodies."""
    return n + 1 + position


def assembly_id(n: int) -> int:
    """Resource id of the components object, of n bodies."""
    return 2 * n + 1


def extruder(position: int) -> int:
    """The OrcaSlicer filament (1-based) the body at this position in shell order is
    printed with: position + 1, so the base (always first) is filament 1 and the inlays
    follow by palette index, whatever the base's palette index (controller decision,
    2026-11-13, after Task 4; the plan's "palette index + 1" holds when the base is
    palette index 0 and the indices are 0..n-1, as in all four owner plans)."""
    return position + 1


def filament_map(shells: Sequence[Shell]) -> list[dict]:
    """Which filament prints which color, for the record and the message (Task 6): per
    shell in order, {"filament": extruder(position), "body", "role", "index" (palette
    index), "hex"}. The same rule the writer and orca_input_check use."""
    check_shells(shells)
    return [{"filament": extruder(i), "body": s.name, "role": s.role, "index": s.index,
             "hex": s.hex} for i, s in enumerate(shells)]


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


# --- orca-input.3mf (Decision 2) --------------------------------------------------------


def orca_model_xml(shells: Sequence[Shell]) -> bytes:
    """3D/3dmodel.model of encoding B_msc (ENCODING), as the step 3 prototype
    research/verification/2026-11-12-color-3mf/measure_import.py model_xml(bodies, "B")
    wrote it for the files Task 2 sliced (tests compare the bytes). Resource ids:
    colorgroups 1..n, mesh objects n+1..2n, the assembly 2n+1. Each mesh object is named
    after its shell and carries its colorgroup as object-level property (pid, pindex 0);
    its triangles carry no property. The colorgroups do not set OrcaSlicer's filament
    colors (Task 2: the CLI takes them from filament_colour); they are kept because the
    sliced prototype had them.

    Written as tdmg.threemf.model_xml writes its mesh: an lxml skeleton with empty
    <vertices/> and <triangles/> per mesh object, the vertex and triangle elements as
    text in lxml's serialized form (f32_text coordinates), no metadata, no UUIDs.
    """
    arrays = check_shells(shells)
    n = len(shells)
    q = f"{{{NS_CORE}}}"
    model = etree.Element(f"{q}model", nsmap={None: NS_CORE, "m": NS_M})
    model.set("unit", UNIT)
    model.set(f"{{{NS_XML}}}lang", "en-US")
    res = etree.SubElement(model, f"{q}resources")
    for i, s in enumerate(shells):
        g = etree.SubElement(res, f"{{{NS_M}}}colorgroup", {"id": str(colorgroup_id(i))})
        etree.SubElement(g, f"{{{NS_M}}}color", {"color": color_3mf(s.hex)})
    for i, s in enumerate(shells):
        obj = etree.SubElement(res, f"{q}object", {
            "id": str(mesh_object_id(i, n)), "type": "model", "name": s.name,
            "pid": str(colorgroup_id(i)), "pindex": "0"})
        mesh = etree.SubElement(obj, f"{q}mesh")
        etree.SubElement(mesh, f"{q}vertices")
        etree.SubElement(mesh, f"{q}triangles")
    asm = etree.SubElement(res, f"{q}object", {"id": str(assembly_id(n)), "type": "model",
                                                "name": ASSEMBLY_NAME})
    comps = etree.SubElement(asm, f"{q}components")
    for i in range(n):
        etree.SubElement(comps, f"{q}component", {"objectid": str(mesh_object_id(i, n))})
    build = etree.SubElement(model, f"{q}build")
    etree.SubElement(build, f"{q}item", {"objectid": str(assembly_id(n))})
    skeleton = etree.tostring(model, xml_declaration=True, encoding="UTF-8")
    empty = b"<vertices/><triangles/>"
    pieces = skeleton.split(empty)
    if len(pieces) != n + 1:      # lxml serialized the skeleton in another form
        raise ThreeMFError("unexpected XML skeleton")
    out = [pieces[0]]
    for (v, f), rest in zip(arrays, pieces[1:], strict=True):
        vertices = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in f32_text(v))
        triangles = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>'
                            for a, b, c in f.tolist())
        out += [b"<vertices>", vertices.encode("ascii"), b"</vertices><triangles>",
                triangles.encode("ascii"), b"</triangles>", rest]
    return b"".join(out)


def model_settings(shells: Sequence[Shell]) -> bytes:
    """Metadata/model_settings.config (Bambu/Orca project metadata, not 3MF core or
    Materials), as the step 3 prototype's bambu_model_settings wrote it: one <object>
    for the assembly (name, extruder 1), and one <part> per mesh object, by its resource
    id, subtype normal_part, with its name and extruder(position)."""
    check_shells(shells)
    n = len(shells)
    cfg = etree.Element("config")
    obj = etree.SubElement(cfg, "object", {"id": str(assembly_id(n))})
    etree.SubElement(obj, "metadata", {"key": "name", "value": ASSEMBLY_NAME})
    etree.SubElement(obj, "metadata", {"key": "extruder", "value": "1"})
    for i, s in enumerate(shells):
        p = etree.SubElement(obj, "part", {"id": str(mesh_object_id(i, n)),
                                           "subtype": PART_SUBTYPE})
        etree.SubElement(p, "metadata", {"key": "name", "value": s.name})
        etree.SubElement(p, "metadata", {"key": "extruder", "value": str(extruder(i))})
    return etree.tostring(cfg, xml_declaration=True, encoding="UTF-8")


def write_orca_input(shells: Sequence[Shell]) -> bytes:
    """The orca-input.3mf bytes for these shells (face up, or turn_over's face down).

    The package is tdmg.threemf.package's (same content types and relationships parts,
    fixed order, dates, modes and deflate), with Metadata/model_settings.config as a
    fourth part. As in the sliced prototype, [Content_Types].xml has no entry for the
    .config extension: OPC wants a content type for every part, but lib3mf (strict) reads
    the file with no warning and OrcaSlicer 2.5.0 reads the extruders from it (Task 2).
    Refused (ThreeMFError): what tdmg.threemf.check_shells refuses.
    """
    return package(orca_model_xml(shells), ((SETTINGS_PART, model_settings(shells)),))

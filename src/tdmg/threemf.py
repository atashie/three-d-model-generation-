"""Deterministic multicolor 3MF writer (docs/plans/2026-11-12-color-3mf.md, R2 step 3).

Encoding D (plan Decision 1, chosen by the import tests in
research/verification/2026-11-12-color-3mf/README.md): one <object type="model"> whose
mesh holds every AMS body as its own closed shell, one <m:colorgroup> with one <m:color>
per body, and each triangle carrying pid and p1 of its body's color. PrusaSlicer 2.9.7
slices it in place, OrcaSlicer 2.5.0 opens it in place (on one filament), and the owner's
Bambu Studio opened it in place with its colors. The shells touch along their shared
walls; the 3MF manifold rule holds per shell, by vertex index, and touching shells are
covered by the core spec only as a self-intersection warning (rule
format.3mf.self_intersection_is_warning).

What the writer guarantees (and why), for the same shells:
- Coordinates: each vertex coordinate must be a float32 number (the gated meshes are
  parsed back from binary STL, so they are). It is written as the shortest decimal that
  rounds back to the same float32 (numpy's Dragon4, format_float_positional with
  unique=True; the same formatting as f32 in
  research/verification/2026-11-12-color-3mf/measure_import.py, which wrote the
  import-tested files). Dragon4's unique mode guarantees that a correctly rounding
  float32 parse of the text gives the identical value. A reader that parses through
  float64 first rounds twice, which could in principle land on the other neighbour. The
  writer's self-check covers that case: np.float32(text) parses through float64 (measured:
  np.float32 of 1 + 2^-24 + 2^-60 gives 1.0, where a direct float32 parse gives the next
  float32), and every distinct value must come back equal. A 3-million-value sample
  (grid multiples, uniform values and random bit patterns; 2026-11-12, not kept) never
  failed it. The gate's lib3mf read-back (tdmg.color_checks.export_3mf_check) also
  compares every coordinate exactly, so a reader that differed would FAIL, not pass.
- XML: one function builds it (lxml for the document, the vertex and triangle elements
  as text in lxml's serialized form; tests compare it with a full lxml tree), with a
  fixed attribute order, namespaces 3MF core 2015/02 and Materials 2015/02 only, unit
  millimeter, xml:lang en-US, no metadata and no UUIDs (the Production extension is not
  used).
- Package: [Content_Types].xml, _rels/.rels and 3D/3dmodel.model, in that order, each
  dated 1980-01-01 00:00:00 (the earliest date a zip entry can hold), made on "Unix"
  (create_system 3) with mode 0644, so the bytes do not depend on the platform zipfile
  runs on. Compression: deflate at zlib's default level, the form the import tests used
  (OPC allows stored or deflate; deflate makes the files several times smaller).
  The deflated bytes depend on CPython's zipfile (colored.json records the python
  version) and on the zlib that Python's zlib module links (zlib.ZLIB_RUNTIME_VERSION,
  recorded as zlib_python; Pillow's zlib, recorded as zlib, can differ); the XML inside
  depends on neither.

No file I/O: the functions return bytes.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from lxml import etree

from tdmg.records import record_text

NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
NS_M = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
REL_3D = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
NS_XML = "http://www.w3.org/XML/1998/namespace"
MODEL_PART = "3D/3dmodel.model"
PART_NAMES = ("[Content_Types].xml", "_rels/.rels", MODEL_PART)   # the zip entries, in order
UNIT = "millimeter"
OBJECT_NAME = "model"          # the single object's name, as in the import-tested file D
COLOR_GROUP_ID = 1             # resource ids: the colorgroup, then the object
OBJECT_ID = 2
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
ZIP_MODE = 0o644
ZIP_UNIX = 3                   # zip "version made by" host system: Unix
ZIP_COMPRESSION = zipfile.ZIP_DEFLATED
PALETTE_SCHEMA = "tdmg.palette/1"
ENCODING = ("one mesh object with one closed shell per body (base first, then inlays by "
            "palette index), vertices separate per shell; one m:colorgroup with one "
            "m:color per body; each triangle carries pid and p1 of its body's color")
HEX = re.compile(r"#[0-9a-fA-F]{6}")
ROLES = ("base", "inlay")

CONTENT_TYPES = (
    f'<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="{NS_CT}">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
    'relationships+xml"/><Default Extension="model" ContentType="application/'
    'vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>').encode()
RELS = (f'<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="{NS_REL}">'
        f'<Relationship Target="/{MODEL_PART}" Id="rel0" Type="{REL_3D}"/>'
        '</Relationships>').encode()


class ThreeMFError(ValueError):
    """The shells cannot be written as a 3MF as asked."""


@dataclass(frozen=True, eq=False)
class Shell:
    """One body as a shell of the 3MF object.

    name: the body's name (its STL name without .stl, e.g. "ams-base"); role: "base" or
    "inlay"; index: its palette index; hex: "#rrggbb"; vertices (V, 3) float32 numbers
    (any float dtype); faces (F, 3) indices into vertices, outward wound.
    """

    name: str
    role: str
    index: int
    hex: str
    vertices: np.ndarray
    faces: np.ndarray


def color_3mf(hex_code: str) -> str:
    """The 3MF sRGB color of a palette hex: "#RRGGBBFF" (opaque, upper case)."""
    if not isinstance(hex_code, str) or not HEX.fullmatch(hex_code):
        raise ThreeMFError(f"hex must be '#rrggbb', got {hex_code!r}")
    return f"#{hex_code[1:].upper()}FF"


def _arrays(shell: Shell) -> tuple[np.ndarray, np.ndarray]:
    v = np.asarray(shell.vertices)
    f = np.asarray(shell.faces)
    if v.ndim != 2 or v.shape[1] != 3 or not len(v) or not np.issubdtype(v.dtype, np.floating):
        raise ThreeMFError(f"shell {shell.name!r}: vertices must be a non-empty (V, 3) "
                           f"float array")
    if f.ndim != 2 or f.shape[1] != 3 or not len(f) or not np.issubdtype(f.dtype, np.integer):
        raise ThreeMFError(f"shell {shell.name!r}: faces must be a non-empty (F, 3) "
                           f"integer array")
    if not np.isfinite(v).all():
        raise ThreeMFError(f"shell {shell.name!r}: a vertex coordinate is not finite")
    v32 = v.astype(np.float32)
    if not np.array_equal(v32.astype(np.float64), v.astype(np.float64)):
        raise ThreeMFError(f"shell {shell.name!r}: a vertex coordinate is not a float32 "
                           f"number (the shells must be the gated STL meshes)")
    if f.min() < 0 or f.max() >= len(v):
        raise ThreeMFError(f"shell {shell.name!r}: a face index is out of range")
    return v32 + np.float32(0.0), f.astype(np.int64)   # + 0: -0.0 becomes 0.0


def check_shells(shells: Sequence[Shell]) -> list[tuple[np.ndarray, np.ndarray]]:
    """Refuse (ThreeMFError) shells that are not base first, then inlays by ascending
    palette index, each with a '#rrggbb' hex and valid float32 vertices and faces. Returns
    each shell's (float32 vertices, int64 faces)."""
    shells = list(shells)
    if not shells:
        raise ThreeMFError("no shells to write")
    for i, s in enumerate(shells):
        if not isinstance(s, Shell):
            raise ThreeMFError(f"shell {i} is not a tdmg.threemf.Shell")
        if s.role not in ROLES or (s.role == "base") != (i == 0):
            raise ThreeMFError(f"shell order must be the base first, then inlays: shell {i} "
                               f"has role {s.role!r}")
        color_3mf(s.hex)
        if isinstance(s.index, bool) or not isinstance(s.index, int) or s.index < 0:
            raise ThreeMFError(f"shell {s.name!r}: index must be an int >= 0")
    inlays = [s.index for s in shells[1:]]
    if inlays != sorted(set(inlays)) or shells[0].index in inlays:
        raise ThreeMFError(f"inlays must follow the base by ascending, distinct palette "
                           f"index, got base {shells[0].index}, inlays {inlays}")
    return [_arrays(s) for s in shells]


def shell_ranges(shells: Sequence[Shell]) -> list[dict]:
    """Per shell, its half-open vertex and triangle ranges in the object:
    {"vertices": [start, end], "triangles": [start, end]}."""
    out, v0, t0 = [], 0, 0
    for s in shells:
        nv, nt = len(np.asarray(s.vertices)), len(np.asarray(s.faces))
        out.append({"vertices": [v0, v0 + nv], "triangles": [t0, t0 + nt]})
        v0, t0 = v0 + nv, t0 + nt
    return out


def f32_text(values: np.ndarray) -> np.ndarray:
    """Shortest round-trip decimal text of each float32 value (an object array of str).

    Each distinct value is formatted once and checked: np.float32(text) must equal it.
    -0.0 is written as 0 (adding 0.0 turns it into +0.0), whatever the input order.
    """
    values = np.asarray(values, dtype=np.float32) + np.float32(0.0)
    unique, inverse = np.unique(values, return_inverse=True)
    texts = []
    for x in unique:
        t = np.format_float_positional(x, unique=True, trim="-")
        if np.float32(t) != x:      # cannot happen with Dragon4's unique mode
            raise ThreeMFError(f"float32 {x!r} does not round-trip through {t!r}")
        texts.append(t)
    return np.asarray(texts, dtype=object)[inverse.reshape(values.shape)]


def model_xml(shells: Sequence[Shell]) -> bytes:
    """3D/3dmodel.model for encoding D (see the module docstring).

    lxml builds and serializes the document with empty <vertices/> and <triangles/>
    elements; the vertex and triangle elements are then written as text in the form lxml
    serializes them (attributes in this order, double quotes, no whitespace; the values
    are digits, '.' and '-', which need no escaping). This keeps the bytes of a full lxml
    tree without holding one element object per vertex and triangle in memory.
    """
    arrays = check_shells(shells)
    q = f"{{{NS_CORE}}}"
    model = etree.Element(f"{q}model", nsmap={None: NS_CORE, "m": NS_M})
    model.set("unit", UNIT)
    model.set(f"{{{NS_XML}}}lang", "en-US")
    res = etree.SubElement(model, f"{q}resources")
    group = etree.SubElement(res, f"{{{NS_M}}}colorgroup", {"id": str(COLOR_GROUP_ID)})
    for s in shells:
        etree.SubElement(group, f"{{{NS_M}}}color", {"color": color_3mf(s.hex)})
    obj = etree.SubElement(res, f"{q}object", {
        "id": str(OBJECT_ID), "type": "model", "name": OBJECT_NAME,
        "pid": str(COLOR_GROUP_ID), "pindex": "0"})
    mesh = etree.SubElement(obj, f"{q}mesh")
    etree.SubElement(mesh, f"{q}vertices")
    etree.SubElement(mesh, f"{q}triangles")
    build = etree.SubElement(model, f"{q}build")
    etree.SubElement(build, f"{q}item", {"objectid": str(OBJECT_ID)})
    skeleton = etree.tostring(model, xml_declaration=True, encoding="UTF-8")
    empty = b"<vertices/><triangles/>"
    if skeleton.count(empty) != 1:      # lxml serialized the skeleton in another form
        raise ThreeMFError("unexpected XML skeleton")
    head, tail = skeleton.split(empty)
    vertices, triangles = [], []
    offset = 0
    pid = COLOR_GROUP_ID
    for i, (v, f) in enumerate(arrays):
        vertices += [f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in f32_text(v)]
        triangles += [f'<triangle v1="{a}" v2="{b}" v3="{c}" pid="{pid}" p1="{i}"/>'
                      for a, b, c in (f + offset).tolist()]
        offset += len(v)
    return b"".join([head, b"<vertices>", "".join(vertices).encode("ascii"),
                     b"</vertices><triangles>", "".join(triangles).encode("ascii"),
                     b"</triangles>", tail])


def package(model: bytes) -> bytes:
    """The 3MF zip of one model part, with fixed entry order, dates, modes and method."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in zip(PART_NAMES, (CONTENT_TYPES, RELS, model), strict=True):
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.compress_type = ZIP_COMPRESSION
            info.create_system = ZIP_UNIX
            info.external_attr = ZIP_MODE << 16
            z.writestr(info, data)
    return buf.getvalue()


def write_multishell_3mf(shells: Sequence[Shell]) -> bytes:
    """The 3MF bytes of encoding D for these shells (base first, then inlays by index).

    Refused (ThreeMFError): no shells, a wrong order or role, a bad hex, empty or
    malformed arrays, a coordinate that is not finite or not a float32 number, a face
    index out of range.
    """
    return package(model_xml(shells))


def palette_manifest(shells: Sequence[Shell], model_3mf: bytes, *, colorflat_id: str,
                     top_area_mm2: Sequence[float], volume_mm3: Sequence[float]) -> bytes:
    """palette.json (plan Decision 2): what each shell of model.3mf is, as record JSON
    (tdmg.records.record_text: indented, key-sorted, one trailing newline).

    Per shell, in the object's order: its body name, role, palette index, hex, the 3MF
    color, its vertex and triangle ranges in the object (shell_ranges), its top area
    (the area of the model's top in that color) and its volume, both as the caller
    measured them (colored.json's body rows). Also the colorflat_id and the 3MF's SHA-256.
    It names colors, never AMS slots (docs/PLAN.md section 2 point 7).
    """
    check_shells(shells)
    if len(top_area_mm2) != len(shells) or len(volume_mm3) != len(shells):
        raise ThreeMFError("one top area and one volume per shell are needed")
    rows = []
    for i, (s, r, area, vol) in enumerate(zip(shells, shell_ranges(shells), top_area_mm2,
                                              volume_mm3, strict=True)):
        rows.append({"shell": i, "body": s.name, "role": s.role, "index": s.index,
                     "hex": s.hex, "color_3mf": color_3mf(s.hex), **r,
                     "top_area_mm2": float(area), "volume_mm3": float(vol)})
    manifest = {
        "schema": PALETTE_SCHEMA, "colorflat_id": colorflat_id,
        "model_3mf_sha256": hashlib.sha256(model_3mf).hexdigest(),
        "object_name": OBJECT_NAME, "unit": UNIT, "encoding": ENCODING,
        "shells": rows,
        "note": ("Colors are named by palette index and hex, not by AMS slot: assign a "
                 "filament to each color in the slicer. The shells touch along their "
                 "shared walls; each is closed on its own."),
    }
    return record_text(manifest)

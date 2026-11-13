"""Import experiment for plan docs/plans/2026-11-12-color-3mf.md, Task 1.

Writes candidate multicolor 3MF files by hand (zipfile + lxml), validates them with lib3mf,
then imports and slices them with the pinned OrcaSlicer 2.5.0 and PrusaSlicer 2.9.7.

Usage (from the repo root, Windows):
    uv run python research/verification/2026-11-12-color-3mf/measure_import.py build OUT
    uv run python research/verification/2026-11-12-color-3mf/measure_import.py orca OUT [VARIANT]
    uv run python research/verification/2026-11-12-color-3mf/measure_import.py prusa OUT

OUT is a work folder (the scratchpad); only small text summaries are copied into this
research folder by hand. Slicers are verified against their pins before any run.

Research code: not part of the package, not tested. OrcaSlicer and PrusaSlicer are AGPL and
are only run as subprocesses.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
import zipfile
from pathlib import Path

import numpy as np
from lxml import etree

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from tdmg import portability, slicer

ROADIE = REPO / "artifacts/colored-runs/roadie-tol30-60-drop-v3-f64"
ROADIE_BODIES = [("base #f60606", "ams-base.stl", "F60606"),
                 ("color-1 #f5f5f5", "ams-color-1-f5f5f5.stl", "F5F5F5"),
                 ("color-2 #f0f10a", "ams-color-2-f0f10a.stl", "F0F10A"),
                 ("color-3 #451812", "ams-color-3-451812.stl", "451812")]
NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
NS_M = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
REL_3D = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
TIMEOUT_S = 600


# --- Bodies -------------------------------------------------------------------------------

def read_stl(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """(vertices float32 (V,3), faces int (F,3)) of a binary STL, merging only exactly equal
    float32 vertices (first-appearance order)."""
    data = path.read_bytes()
    n = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + 50 * n:
        raise ValueError(f"{path} is not a binary STL of {n} facets")
    rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)),
                                              ("a", "<u2")]), count=n, offset=84)
    tri = np.ascontiguousarray(rec["v"]).reshape(-1, 3)
    _uniq, first, inverse = np.unique(tri.view(np.dtype((np.void, 12))).ravel(),
                                     return_index=True, return_inverse=True)
    order = np.argsort(first)            # keep first-appearance order
    rank = np.empty_like(order)
    rank[order] = np.arange(len(order))
    verts = tri[first[order]]
    faces = rank[inverse].reshape(-1, 3)
    return verts.astype(np.float32), faces


def synthetic_bodies() -> list[tuple[str, np.ndarray, np.ndarray, str]]:
    """20 x 20 x 3 base with a 10 x 10 x 0.6 pocket at the top centre, and the inlay."""
    import manifold3d as m3d
    base = m3d.Manifold.cube([20, 20, 3]) - m3d.Manifold.cube([10, 10, 0.6]).translate(
        [5, 5, 2.4])
    inlay = m3d.Manifold.cube([10, 10, 0.6]).translate([5, 5, 2.4])
    out = []
    for name, man, hexc in (("base #f60606", base, "F60606"),
                            ("color-1 #f5f5f5", inlay, "F5F5F5")):
        mesh = man.to_mesh()
        out.append((name, np.asarray(mesh.vert_properties, dtype=np.float32)[:, :3],
                    np.asarray(mesh.tri_verts, dtype=np.int64), hexc))
    return out


def roadie_bodies():
    return [(name, *read_stl(ROADIE / f), hexc) for name, f, hexc in ROADIE_BODIES]


def volume(v: np.ndarray, f: np.ndarray) -> float:
    t = v.astype(np.float64)[f]
    return float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6)


# --- 3MF writing ---------------------------------------------------------------------------

def f32(x: np.float32) -> str:
    return np.format_float_positional(x, unique=True, trim="-")


def mesh_element(parent, verts, faces):
    mesh = etree.SubElement(parent, f"{{{NS_CORE}}}mesh")
    ve = etree.SubElement(mesh, f"{{{NS_CORE}}}vertices")
    for x, y, z in verts:
        etree.SubElement(ve, f"{{{NS_CORE}}}vertex", x=f32(x), y=f32(y), z=f32(z))
    te = etree.SubElement(mesh, f"{{{NS_CORE}}}triangles")
    for a, b, c in faces:
        etree.SubElement(te, f"{{{NS_CORE}}}triangle", v1=str(a), v2=str(b), v3=str(c))


def model_xml(bodies, encoding: str) -> bytes:
    """encoding: A (per-object colorgroup), A_shared (one shared colorgroup, extra),
    B (assembly), C (one basematerials group, pid on the object, no colorgroup)."""
    model = etree.Element(f"{{{NS_CORE}}}model", nsmap={None: NS_CORE, "m": NS_M})
    model.set("unit", "millimeter")
    model.set("{http://www.w3.org/XML/1998/namespace}lang", "en-US")
    res = etree.SubElement(model, f"{{{NS_CORE}}}resources")
    next_id = 1
    props = []    # (pid, pindex) per body
    if encoding in ("A", "B"):
        for _, _, _, hexc in bodies:
            g = etree.SubElement(res, f"{{{NS_M}}}colorgroup", id=str(next_id))
            etree.SubElement(g, f"{{{NS_M}}}color", color=f"#{hexc}FF")
            props.append((next_id, 0))
            next_id += 1
    elif encoding == "A_shared":
        g = etree.SubElement(res, f"{{{NS_M}}}colorgroup", id=str(next_id))
        for i, (_, _, _, hexc) in enumerate(bodies):
            etree.SubElement(g, f"{{{NS_M}}}color", color=f"#{hexc}FF")
            props.append((next_id, i))
        next_id += 1
    elif encoding == "C":
        g = etree.SubElement(res, f"{{{NS_CORE}}}basematerials", id=str(next_id))
        for i, (name, _, _, hexc) in enumerate(bodies):
            etree.SubElement(g, f"{{{NS_CORE}}}base", name=name, displaycolor=f"#{hexc}FF")
            props.append((next_id, i))
        next_id += 1
    elif encoding == "D":
        # One mesh object holding every body as its own shell; one shared colorgroup; the
        # object's pid/pindex is the base colour and each triangle carries pid and p1.
        g = etree.SubElement(res, f"{{{NS_M}}}colorgroup", id="1")
        for _, _, _, hexc in bodies:
            etree.SubElement(g, f"{{{NS_M}}}color", color=f"#{hexc}FF")
        o = etree.SubElement(res, f"{{{NS_CORE}}}object", id="2", type="model",
                             name="model", pid="1", pindex="0")
        mesh = etree.SubElement(o, f"{{{NS_CORE}}}mesh")
        ve = etree.SubElement(mesh, f"{{{NS_CORE}}}vertices")
        te = etree.SubElement(mesh, f"{{{NS_CORE}}}triangles")
        offset = 0
        for i, (_, v, f, _) in enumerate(bodies):
            for x, y, z in v:
                etree.SubElement(ve, f"{{{NS_CORE}}}vertex", x=f32(x), y=f32(y), z=f32(z))
            for a, b, c in f:
                etree.SubElement(te, f"{{{NS_CORE}}}triangle", v1=str(a + offset),
                                 v2=str(b + offset), v3=str(c + offset), pid="1", p1=str(i))
            offset += len(v)
        build = etree.SubElement(model, f"{{{NS_CORE}}}build")
        etree.SubElement(build, f"{{{NS_CORE}}}item", objectid="2")
        return etree.tostring(model, xml_declaration=True, encoding="UTF-8")
    else:
        raise ValueError(encoding)
    obj_ids = []
    for (name, v, f, _), (pid, pindex) in zip(bodies, props, strict=True):
        o = etree.SubElement(res, f"{{{NS_CORE}}}object", id=str(next_id), type="model",
                             name=name, pid=str(pid), pindex=str(pindex))
        mesh_element(o, v, f)
        obj_ids.append(next_id)
        next_id += 1
    build = etree.SubElement(model, f"{{{NS_CORE}}}build")
    if encoding == "B":
        asm = etree.SubElement(res, f"{{{NS_CORE}}}object", id=str(next_id), type="model",
                               name="assembly")
        comps = etree.SubElement(asm, f"{{{NS_CORE}}}components")
        for oid in obj_ids:
            etree.SubElement(comps, f"{{{NS_CORE}}}component", objectid=str(oid))
        etree.SubElement(build, f"{{{NS_CORE}}}item", objectid=str(next_id))
    else:
        for oid in obj_ids:
            etree.SubElement(build, f"{{{NS_CORE}}}item", objectid=str(oid))
    return etree.tostring(model, xml_declaration=True, encoding="UTF-8")


def bambu_model_settings(bodies) -> bytes:
    """Metadata/model_settings.config for encoding B (Bambu/Orca project metadata, NOT
    part of 3MF core or Materials): one extruder per part of the assembly. Object ids are
    those model_xml(bodies, "B") writes: colorgroups 1..n, meshes n+1..2n, assembly 2n+1."""
    n = len(bodies)
    cfg = etree.Element("config")
    o = etree.SubElement(cfg, "object", id=str(2 * n + 1))
    etree.SubElement(o, "metadata", key="name", value="assembly")
    etree.SubElement(o, "metadata", key="extruder", value="1")
    for i, (name, _, _, _) in enumerate(bodies):
        p = etree.SubElement(o, "part", id=str(n + 1 + i), subtype="normal_part")
        etree.SubElement(p, "metadata", key="name", value=name)
        etree.SubElement(p, "metadata", key="extruder", value=str(i + 1))
    return etree.tostring(cfg, xml_declaration=True, encoding="UTF-8")


def write_3mf(path: Path, model: bytes, extra: tuple = ()) -> None:
    ct = (f'<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="{NS_CT}">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
          'relationships+xml"/><Default Extension="model" ContentType="application/'
          'vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>').encode()
    rels = (f'<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="{NS_REL}">'
            f'<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="{REL_3D}"/>'
            '</Relationships>').encode()
    with zipfile.ZipFile(path, "w") as z:
        for name, data in (("[Content_Types].xml", ct), ("_rels/.rels", rels),
                           ("3D/3dmodel.model", model), *extra):
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)


def lib3mf_check(path: Path, bodies) -> dict:
    import lib3mf
    w = lib3mf.get_wrapper()
    model = w.CreateModel()
    reader = model.QueryReader("3mf")
    reader.SetStrictModeActive(True)
    reader.ReadFromFile(str(path))
    warnings = [reader.GetWarning(i) for i in range(reader.GetWarningCount())]
    unit = model.GetUnit()
    unit = f"{unit} ({lib3mf.ModelUnit(unit).name})"
    meshes, comps = [], 0
    it = model.GetObjects()
    while it.MoveNext():
        o = it.GetCurrentObject()
        if o.IsMeshObject():
            mo = model.GetMeshObjectByID(o.GetResourceID())
            rid, prop, has = mo.GetObjectLevelProperty()
            vs = np.array([[c for c in mo.GetVertex(i).Coordinates]
                           for i in range(mo.GetVertexCount())], dtype=np.float32)
            meshes.append({"name": mo.GetName(), "vertices": mo.GetVertexCount(),
                           "triangles": mo.GetTriangleCount(),
                           "manifold_oriented": mo.IsManifoldAndOriented(),
                           "object_property": {"has": bool(has), "resource_id": rid,
                                               "lib3mf_property_id": prop},
                           "_v": vs})
        elif o.IsComponentsObject():
            comps += 1
    items = 0
    bi = model.GetBuildItems()
    while bi.MoveNext():
        items += 1
    exact = []
    if len(meshes) == 1 and len(bodies) > 1:     # encoding D: all shells in one object
        allv = np.concatenate([v for _, v, _, _ in bodies])
        ntri = sum(len(f) for _, _, f, _ in bodies)
        m = meshes[0]
        exact.append(bool(np.array_equal(m.pop("_v"), allv) and m["triangles"] == ntri))
        return {"unit": str(unit), "mesh_objects": meshes, "components_objects": comps,
                "build_items": items, "warnings": warnings, "vertices_exact": exact}
    for m, (name, v, f, _) in zip(meshes, bodies, strict=True):
        exact.append(bool(m["name"] == name and np.array_equal(m.pop("_v"), v)
                          and m["triangles"] == len(f)))
    return {"unit": str(unit), "mesh_objects": meshes, "components_objects": comps,
            "build_items": items, "warnings": warnings, "vertices_exact": exact}


def hide(text: str, out: Path) -> str:
    """Replace this machine's paths with placeholders, so the record holds none."""
    for p, name in ((str(out), "<out>"), (str(REPO), "<repo>"),
                    (str(Path.home()), "<home>")):
        text = text.replace(p, name).replace(p.replace("\\", "/"), name)
    return text


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


ENCODINGS = ("A", "B", "C", "A_shared", "D", "B_msc")


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for fixture, bodies in (("synthetic", synthetic_bodies()), ("roadie", roadie_bodies())):
        summary[fixture] = {"bodies": [{"name": n, "vertices": len(v), "triangles": len(f),
                                        "volume_mm3": round(volume(v, f), 6),
                                        "min": v.min(0).tolist(), "max": v.max(0).tolist()}
                                       for n, v, f, _ in bodies], "files": {}}
        for enc in ENCODINGS:
            p = out / f"{fixture}-{enc}.3mf"
            if enc == "B_msc":
                write_3mf(p, model_xml(bodies, "B"),
                          (("Metadata/model_settings.config", bambu_model_settings(bodies)),))
            else:
                write_3mf(p, model_xml(bodies, enc))
            summary[fixture]["files"][enc] = {"file": p.name, "bytes": p.stat().st_size,
                                              "sha256": sha(p),
                                              "lib3mf": lib3mf_check(p, bodies)}
    # Probe: the synthetic inlay alone, as encoding A, to see whether a top-level object
    # that starts at z = 2.4 mm stays there.
    inlay = synthetic_bodies()[1:]
    p = out / "probe-inlay-only-A.3mf"
    write_3mf(p, model_xml(inlay, "A"))
    summary["probe"] = {"files": {"A": {"file": p.name, "bytes": p.stat().st_size,
                                        "sha256": sha(p), "lib3mf": lib3mf_check(p, inlay)}}}
    (out / "build.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


# --- OrcaSlicer ----------------------------------------------------------------------------

def gcode_facts(data: bytes) -> dict:
    """Tool changes, filament usage lines and per-object, per-tool extrusion from G-code."""
    text = data.decode("utf-8", errors="replace").splitlines()
    tool_lines, m620, m621 = {}, {}, {}
    header = [ln for ln in text[:400] if ln.startswith(";") and
              re.search(r"filament|layer|object|total|model", ln, re.IGNORECASE)]
    tail = [ln for ln in text[-2000:] if ln.startswith("; ") and re.search(
        r"^; (filament used|total filament|filament_colour|filament_settings_id|"
        r"total layers|filament cost|extruder_colour|default_filament|flush_volumes_matrix|"
        r"filament_type|wipe_tower|enable_prime_tower|filament_map|single_extruder)", ln)]
    tool, obj, relative = None, None, True
    per = {}            # (object, tool) -> extruded mm
    xy = {}             # object -> [minx, miny, maxx, maxy]
    pos = {"X": None, "Y": None, "E": 0.0}
    objects_seen = []
    labels = {}         # "unique label id" -> object name (Orca)
    ext = {}            # "object | tool" -> [minx, miny, maxx, maxy, minz, maxz] extruded
    z_by_object = {}    # object -> [first layer Z, last layer Z] it extrudes on
    layers = 0
    max_z = None
    cur_z = None
    for ln in text:
        s = ln.split(";", 1)[0].strip()
        c = ln.strip()
        # Both slicers write "; printing object NAME id:N copy M" (Orca also writes
        # "; start printing object, unique label id: K" right after, and the "stop" pair).
        mo = re.match(r"^; printing object (.*) id:\d+ copy \d+$", c)
        if mo:
            obj = mo.group(1)
            if obj not in objects_seen:
                objects_seen.append(obj)
            continue
        ml = re.match(r"^; start printing object, unique label id: (\d+)$", c)
        if ml:
            labels.setdefault(ml.group(1), obj)
            continue
        if c.startswith("; stop printing object") and "unique label id" not in c:
            obj = None
            continue
        if c.startswith((";LAYER_CHANGE", "; CHANGE_LAYER")):
            layers += 1
        mz0 = re.match(r"^;\s?Z_HEIGHT: ?([\d.]+)", c) or re.match(r"^;Z:([\d.]+)", c)
        if mz0:
            cur_z = float(mz0.group(1))
        mz = re.match(r"^;\s?Z_HEIGHT: ?([\d.]+)", c) or re.match(r"^;Z:([\d.]+)", c)
        if mz:
            max_z = max(max_z or 0.0, float(mz.group(1)))
        if not s:
            continue
        w = s.split()
        cmd = w[0]
        if re.fullmatch(r"T\d+", cmd):
            tool_lines[cmd] = tool_lines.get(cmd, 0) + 1
            if int(cmd[1:]) < 255:
                tool = cmd
            continue
        if cmd == "M620" and len(w) > 1:
            m620[w[1]] = m620.get(w[1], 0) + 1
        if cmd == "M621" and len(w) > 1:
            m621[w[1]] = m621.get(w[1], 0) + 1
        if cmd == "M82":
            relative = False
        elif cmd == "M83":
            relative = True
        elif cmd == "G92":
            for a in w[1:]:
                if a[0] == "E":
                    pos["E"] = float(a[1:])
        elif cmd in ("G0", "G1", "G2", "G3"):
            new = {a[0]: float(a[1:]) for a in w[1:] if a[0] in "XYZE" and len(a) > 1}
            if "E" in new:
                de = new["E"] if relative else new["E"] - pos["E"]
                if not relative:
                    pos["E"] = new["E"]
                moved = any(k in new and new[k] != pos[k] for k in ("X", "Y"))
                if de > 0 and moved:
                    key = (obj or "(no object)", tool)
                    per[key] = per.get(key, 0.0) + de
                    if obj is not None:
                        zr = z_by_object.setdefault(obj, [cur_z, cur_z])
                        zr[1] = cur_z
                        x, y = new.get("X", pos["X"]), new.get("Y", pos["Y"])
                        ek = f"{obj} | {tool}"
                        e = ext.setdefault(ek, [x, y, x, y, cur_z, cur_z])
                        e[:] = [min(e[0], x), min(e[1], y), max(e[2], x), max(e[3], y),
                                min(e[4], cur_z), max(e[5], cur_z)]
                        b = xy.setdefault(obj, [x, y, x, y])
                        b[:] = [min(b[0], x), min(b[1], y), max(b[2], x), max(b[3], y)]
            for k in ("X", "Y"):
                if k in new:
                    pos[k] = new[k]
    by_object = {}
    for (o, t), e in per.items():
        by_object.setdefault(o, {})[str(t)] = round(e, 2)
    return {"lines": len(text), "tool_commands": tool_lines, "M620": m620, "M621": m621,
            "header_lines": header[:40], "config_lines": tail,
            "layer_markers": layers, "max_z_marker": max_z,
            "objects_in_order": objects_seen, "label_ids": labels,
            "extrusion_layer_z_by_object": z_by_object,
            "extrusion_extent_by_object_and_tool": {k: [round(v, 3) for v in e]
                                                    for k, e in ext.items()},
            "extrusion_mm_by_object_and_tool": by_object,
            "extrusion_xy_by_object": {o: [round(v, 3) for v in b] for o, b in xy.items()}}


# Variants: extra CLI arguments, placed after --load-filaments, and which files they run on.
ORCA_VARIANTS = {
    "plain": ([], None),
    "arrange0": (["--arrange", "0"], None),
    "arrange0_noensure": (["--arrange", "0", "--ensure-on-bed=0"], r"(synthetic-A|probe-.*)"),
    "assemble": (["--assemble"], r".*-A"),
    "assemble_arrange0": (["--assemble", "--arrange", "0"], r".*-A"),
}


def orca(out: Path, variant: str = "plain", only: str | None = None) -> None:
    pin = slicer.load_pin()
    orc = slicer.locate(REPO / "artifacts/tools/orcaslicer-2.5.0", pin, full_tree=True)
    prof = {k: str(v) for k, v in orc.profiles.items()}
    fil = prof["filament"]
    extra, pattern = ORCA_VARIANTS[variant]
    results = {"slicer_verified": orc.verified, "variant": variant, "extra_args": extra,
               "runs": {}}
    files = sorted(out.glob("*.3mf"))
    for f in files:
        if (only or pattern) and not re.fullmatch(only or pattern, f.stem):
            continue
        work = out / "orca" / variant / f.stem
        if work.exists():
            import shutil
            shutil.rmtree(work)
        work.mkdir(parents=True)
        (work / "out").mkdir()
        log = work / "slicer.log"
        args = [str(orc.exe), str(f), "--load-settings", f"{prof['machine']};{prof['process']}",
                "--load-filaments", ";".join([fil] * 4), *extra, "--slice", "0",
                "--outputdir", str(work / "out"), "--export-statistics", "--debug", "3",
                "--logfile", str(log)]
        rc, timed_out, so, se = slicer.run_process(args, work, TIMEOUT_S)
        code = None if rc is None else slicer.decode_exit(rc, slicer.platform_key(), pin)
        g = work / "out" / slicer.GCODE_NAME
        st = work / "out" / slicer.STATS_NAME
        rec = {"args_template": [hide(a, out) for a in args],
               "exit": code, "timed_out": timed_out,
               "stderr_tail": hide(slicer.output_tail(se)[-1500:], out),
               "stdout_tail": hide(slicer.output_tail(so)[-1500:], out),
               "outputs": sorted(p.name for p in (work / "out").iterdir()),
               "gcode_bytes": g.stat().st_size if g.is_file() else None}
        if g.is_file():
            rec["gcode"] = gcode_facts(g.read_bytes())
        if st.is_file():
            raw = json.loads(st.read_bytes())
            raw.pop("layers", None)          # per-layer detail: large, not needed here
            rec["statistics"] = raw
        if log.is_file():
            lines = log.read_text("utf-8", errors="replace").splitlines()
            rec["log_lines"] = len(lines)
            rec["log_extract"] = [hide(ln, out)[-300:] for ln in lines if re.search(
                r"vendor|assemble|arrange|group colors|from stl|extruder|filament map|"
                r"color|warn|error|ensure|drop|translate", ln, re.IGNORECASE)][:80]
        results["runs"][f.stem] = rec
        print(f.stem, code and code["signed"], rec["gcode_bytes"])
        if "gcode" in rec:
            gf = rec["gcode"]
            print("   tools", gf["tool_commands"], "M620", gf["M620"])
            for o in gf["objects_in_order"]:
                print("   ", o, gf["extrusion_mm_by_object_and_tool"].get(o),
                      "xy", gf["extrusion_xy_by_object"].get(o),
                      "z", gf["extrusion_layer_z_by_object"].get(o))
            for k, e in gf["extrusion_extent_by_object_and_tool"].items():
                print("      extent", k, e)
            if "statistics" in rec:
                s = rec["statistics"]
                print("    stats objects", [(o["name"], o["volume"]) for o in s["objects"]],
                      "filaments", [(x["id"], x["model"]["volume"]) for x in
                                    s["summary"]["filaments"]],
                      "changes", s["summary"].get("filament_changes"))
        else:
            print("   stderr", rec["stderr_tail"][-400:], "log", rec.get("log_extract", [])[-5:])
    (out / f"orca-{variant.replace(':', '_')}.json").write_text(
        json.dumps(results, indent=1), encoding="utf-8")


# --- PrusaSlicer ---------------------------------------------------------------------------

def parse_info_multi(text: str) -> list[dict]:
    objs, cur = [], None
    for ln in text.splitlines():
        ln = ln.strip()
        if ln.startswith("[") and ln.endswith("]"):
            cur = {"header": ln}
            objs.append(cur)
        elif "=" in ln and cur is not None:
            k, _, v = ln.partition("=")
            cur[k.strip()] = v.strip()
    return objs


def prusa(out: Path) -> None:
    pin = portability.load_prusa_pin()
    pr = portability.locate_prusaslicer(REPO / "artifacts/tools/prusaslicer-2.9.7", pin)
    opin = slicer.load_pin()
    orc = slicer.locate(REPO / "artifacts/tools/orcaslicer-2.5.0", opin, full_tree=False)
    prof = {k: json.loads(Path(v).read_text("utf-8")) for k, v in orc.profiles.items()}
    settings = portability.explicit_settings(prof["machine"], prof["process"], prof["filament"])
    results = {"slicer_verified": pr.verified, "settings": settings, "runs": {}}
    for f in sorted(out.glob("*.3mf")):
        for mode, extra in (("default", []), ("dont-arrange", ["--dont-arrange"])):
            work = out / "prusa" / f"{f.stem}-{mode}"
            if work.exists():
                import shutil
                shutil.rmtree(work)
            work.mkdir(parents=True)
            rec = {}
            if mode == "default":
                rc, _to, so, se = slicer.run_process([str(pr.exe), "--info", str(f)], work,
                                                    TIMEOUT_S)
                rec["info"] = {"returncode": rc, "objects": parse_info_multi(
                    so.decode("utf-8", "replace")), "stderr_tail": se.decode(
                    "utf-8", "replace")[-800:]}
            gpath = work / "out.gcode"
            args = [str(pr.exe), "--export-gcode", str(f), "-o", str(gpath), *extra,
                    "--gcode-label-objects", "octoprint"]   # object comments, to read positions
            for opt, s in settings.items():
                args += [opt, s["value"]]
            rc, _to, so, se = slicer.run_process(args, work, TIMEOUT_S)
            rec["slice"] = {"args_template": [a.replace(str(REPO), "<repo>").replace(
                str(out), "<out>") for a in args], "returncode": rc,
                "stdout_tail": so.decode("utf-8", "replace")[-800:].replace(str(out), "<out>"),
                "stderr_tail": se.decode("utf-8", "replace")[-800:].replace(str(out), "<out>"),
                "gcode_bytes": gpath.stat().st_size if gpath.is_file() else None}
            if gpath.is_file():
                gf = gcode_facts(gpath.read_bytes())
                gf.pop("header_lines")
                rec["slice"]["gcode"] = gf
            results["runs"][f"{f.stem}-{mode}"] = rec
            print(f.stem, mode, rec.get("info", {}).get("returncode"),
                  rec["slice"]["returncode"], rec["slice"]["gcode_bytes"])
    (out / "prusa.json").write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    cmd, outdir = sys.argv[1], Path(sys.argv[2])
    if cmd == "build":
        build(outdir)
    elif cmd == "orca":
        orca(outdir, sys.argv[3] if len(sys.argv) > 3 else "plain",
             sys.argv[4] if len(sys.argv) > 4 else None)
    elif cmd == "prusa":
        prusa(outdir)
    else:
        raise SystemExit(f"unknown command {cmd}")

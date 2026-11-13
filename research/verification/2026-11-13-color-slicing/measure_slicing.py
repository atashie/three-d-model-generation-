"""Multicolor slicing experiment for plan docs/plans/2026-11-13-color-slicing.md, Task 2.

Builds the B_msc slicing input (one components object, one mesh part per AMS body, and
Metadata/model_settings.config giving each part extruder = palette index + 1) for the four
owner plans, face up and face down; slices each with the pinned OrcaSlicer 2.5.0 and the
fixed A1 profiles; and reads from each G-code the tool changes per layer, the start-code
load, the flush and prime-tower extrusion, the time and the filament per tool, and where
each tool extrudes, against the bodies.

Usage (from the repo root, Windows):
    uv run python research/verification/2026-11-13-color-slicing/measure_slicing.py build OUT
    uv run python <this file> orca OUT [VARIANT [STEM_REGEX]]
    uv run python <this file> analyse OUT [VARIANT]

VARIANT is plain (default), arrange0 or colours (see VARIANTS).

OUT is a work folder (the scratchpad). Small JSON summaries are copied into raw/ by hand.

Research code: not part of the package, not tested. OrcaSlicer is AGPL and is only run as a
subprocess. It reuses the step 3 script (research/verification/2026-11-12-color-3mf/
measure_import.py) by import.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import shapely

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "research/verification/2026-11-12-color-3mf"))

import measure_import as mi  # step 3's builders and helpers

from tdmg import printed, slicer

PLANS = ("roadie-tol30-60-drop-v3-f64", "roadie-tol30-60-keep-v4-f64",
         "oddie-60-merge-blues-v3-f64", "oddie-60-keep-merge-blues-greens-v4-f64")
RUNS = REPO / "artifacts/colored-runs"
FACES = ("up", "down")
TIMEOUT_S = 900
# Sample spacing along each extruded centreline for the placement distances (mm). Display
# only: it sets how finely the centreline is checked, not a threshold.
SAMPLE_MM = 0.1


# --- Bodies ---------------------------------------------------------------------------------

def plan_bodies(plan: str) -> list[tuple[str, np.ndarray, np.ndarray, str]]:
    """(name, vertices float32, faces, HEX) per body, in palette order (index 0 = base)."""
    pal = json.loads((RUNS / plan / "palette.json").read_text("utf-8"))
    out = []
    for pos, s in enumerate(sorted(pal["shells"], key=lambda s: s["index"])):
        if s["index"] != pos:
            raise ValueError(f"{plan}: palette indices are not 0..n-1")
        if (pos == 0) != (s["role"] == "base"):
            raise ValueError(f"{plan}: palette index 0 is not the base")
        v, f = mi.read_stl(RUNS / plan / f"{s['body']}.stl")
        if len(v) != s["vertices"][1] - s["vertices"][0] or \
                len(f) != s["triangles"][1] - s["triangles"][0]:
            raise ValueError(f"{plan}: {s['body']} counts differ from palette.json")
        out.append((f"{s['body']} {s['hex']}", v, f, s["hex"].lstrip("#").upper()))
    return out


def turn_over(bodies):
    """Face down: each body rotated 180 degrees about the y axis through the model's
    centre: x -> x0 + x1 - x, z -> T - z, y unchanged (a proper rotation: windings kept).

    Returns (bodies, exactness record). The rotated coordinates are computed in float64
    (exact: sums of a few float32 values of similar size) and cast to float32; the record
    says whether each float64 result is a float32 value (the cast is exact) and whether
    float32 arithmetic gives the same values.
    """
    allv = np.concatenate([v for _, v, _, _ in bodies])
    x0, x1 = allv[:, 0].min(), allv[:, 0].max()
    z0, t = allv[:, 2].min(), allv[:, 2].max()
    if z0 != 0:
        raise ValueError(f"the model's lowest z is {z0}, not 0")
    out, rec = [], {"x0": float(x0), "x1": float(x1), "T": float(t), "bodies": []}
    for name, v, f, hexc in bodies:
        v64 = v.astype(np.float64)
        r64 = np.column_stack([np.float64(x0) + np.float64(x1) - v64[:, 0], v64[:, 1],
                               np.float64(t) - v64[:, 2]])
        r32 = r64.astype(np.float32)
        r32_arith = np.column_stack([(x0 + x1) - v[:, 0], v[:, 1], t - v[:, 2]]).astype(
            np.float32)
        inexact = r32.astype(np.float64) != r64
        vol0, vol1 = mi.volume(v, f), mi.volume(r32, f)
        rec["bodies"].append({
            "name": name,
            "coords": int(r64.size),
            "inexact_float32_x": int(inexact[:, 0].sum()),
            "inexact_float32_z": int(inexact[:, 2].sum()),
            "max_cast_error_mm": float(np.abs(r32.astype(np.float64) - r64).max()),
            "float32_arith_differs": int((r32_arith != r32).sum()),
            "volume_mm3": vol0, "volume_turned_mm3": vol1,
            "z_range_turned": [float(r32[:, 2].min()), float(r32[:, 2].max())]})
        out.append((name, r32, f, hexc))
    return out, rec


def body_ranges(bodies) -> list[dict]:
    return [{"name": n, "min": v.min(0).astype(float).tolist(),
             "max": v.max(0).astype(float).tolist(), "volume_mm3": mi.volume(v, f)}
            for n, v, f, _ in bodies]


def faced(plan: str, face: str):
    bodies = plan_bodies(plan)
    return bodies if face == "up" else turn_over(bodies)[0]


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for plan in PLANS:
        up = plan_bodies(plan)
        down, exact = turn_over(up)
        summary[plan] = {"turn_over": exact}
        for face, bodies in (("up", up), ("down", down)):
            p = out / f"{plan}-{face}.3mf"
            # Encoding B_msc (step 3): bodies in palette order, so part i gets extruder
            # i + 1 = palette index + 1 and the base is extruder 1.
            msc = mi.bambu_model_settings(bodies)
            mi.write_3mf(p, mi.model_xml(bodies, "B"),
                         (("Metadata/model_settings.config", msc),))
            summary[plan][face] = {"file": p.name, "bytes": p.stat().st_size,
                                   "sha256": mi.sha(p), "bodies": body_ranges(bodies),
                                   "model_settings": msc.decode(),
                                   "lib3mf": mi.lib3mf_check(p, bodies)}
            print(plan, face, p.stat().st_size, summary[plan][face]["lib3mf"]["vertices_exact"])
        for b in exact["bodies"]:
            print("   ", b["name"], "inexact x/z", b["inexact_float32_x"], b["inexact_float32_z"],
                  "f32-arith differs", b["float32_arith_differs"],
                  "vol", round(b["volume_mm3"], 6), round(b["volume_turned_mm3"], 6),
                  "z", b["z_range_turned"])
    (out / "build.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


# --- OrcaSlicer -----------------------------------------------------------------------------

# Variants: extra CLI arguments, and whether each filament gets the plan's color.
# "plain" is step 3's run (the pinned filament profile four times, no extra argument).
# "colours" is an extra: four copies of the pinned filament profile, each with its
# filament_colour set to the plan's color (palette index order), to see whether the colors
# change the flush volumes and the tool order. The copies are not pinned profiles.
VARIANTS = {"plain": ([], False), "arrange0": (["--arrange", "0"], False),
            "colours": ([], True)}


def plan_of(stem: str) -> tuple[str, str]:
    plan, face = stem.rsplit("-", 1)
    if plan not in PLANS or face not in FACES:
        raise ValueError(stem)
    return plan, face


def coloured_filaments(out: Path, plan: str, filament: Path) -> list[str]:
    prof = json.loads(filament.read_text("utf-8"))
    pal = json.loads((RUNS / plan / "palette.json").read_text("utf-8"))
    folder = out / "filaments" / plan
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for s in sorted(pal["shells"], key=lambda s: s["index"]):
        p = folder / f"filament-{s['index']}.json"
        p.write_text(json.dumps({**prof, "filament_colour": [s["hex"].upper()]}, indent=1),
                     encoding="utf-8")
        paths.append(str(p))
    return paths


def orca(out: Path, variant: str = "plain", only: str | None = None) -> None:
    pin = slicer.load_pin()
    orc = slicer.locate(REPO / "artifacts/tools/orcaslicer-2.5.0", pin, full_tree=True)
    prof = {k: str(v) for k, v in orc.profiles.items()}
    extra, coloured = VARIANTS[variant]
    results = {"slicer_verified": orc.verified, "variant": variant, "extra_args": extra,
               "coloured_filaments": coloured, "runs": {}}
    for f in sorted(out.glob("*.3mf")):
        if only and not re.fullmatch(only, f.stem):
            continue
        plan, _face = plan_of(f.stem)
        n = len(json.loads((RUNS / plan / "palette.json").read_text("utf-8"))["shells"])
        fils = (coloured_filaments(out, plan, Path(prof["filament"])) if coloured
                else [prof["filament"]] * n)
        work = out / "orca" / variant / f.stem
        if work.exists():
            shutil.rmtree(work)
        (work / "out").mkdir(parents=True)
        log = work / "slicer.log"
        args = [str(orc.exe), str(f), "--load-settings", f"{prof['machine']};{prof['process']}",
                "--load-filaments", ";".join(fils), *extra, "--slice", "0",
                "--outputdir", str(work / "out"), "--export-statistics", "--debug", "3",
                "--logfile", str(log)]
        rc, timed_out, _so, se = slicer.run_process(args, work, TIMEOUT_S)
        code = None if rc is None else slicer.decode_exit(rc, slicer.platform_key(), pin)
        g = work / "out" / slicer.GCODE_NAME
        rec = {"args_template": [mi.hide(a, out) for a in args], "filaments": n,
               "exit": code, "timed_out": timed_out,
               "stderr_tail": mi.hide(slicer.output_tail(se)[-1500:], out),
               "outputs": sorted(p.name for p in (work / "out").iterdir()),
               "gcode_bytes": g.stat().st_size if g.is_file() else None,
               "gcode_sha256": mi.sha(g) if g.is_file() else None}
        if log.is_file():
            lines = log.read_text("utf-8", errors="replace").splitlines()
            rec["log_extract"] = [mi.hide(ln, out)[-300:] for ln in lines if re.search(
                r"vendor|arrange|group colors|collision|conflict|outside|warn|error",
                ln, re.IGNORECASE)][:60]
        results["runs"][f.stem] = rec
        print(f.stem, code and code["signed"], rec["gcode_bytes"])
    (out / f"orca-{variant}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")


# --- G-code reader --------------------------------------------------------------------------

MOVE = ("G0", "G1", "G2", "G3")
NUM = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)$")
# Comment markers this reader counts (all seen in this G-code, or in the change template).
MARKERS = ("CHANGE_LAYER", "FLUSH_START", "FLUSH_END", "WIPE_TOWER_START", "WIPE_TOWER_END",
           "CP TOOLCHANGE START", "CP TOOLCHANGE END", "CP EMPTY GRID START",
           "CP EMPTY GRID END", "WIPE_START", "WIPE_END", "WIPE", "SKIPPABLE_START",
           "SKIPPABLE_END", "EXECUTABLE_BLOCK_START", "EXECUTABLE_BLOCK_END",
           "MACHINE_START_GCODE_END", "MACHINE_END_GCODE_START", "filament start gcode",
           "filament end gcode")


def _words(code: str) -> dict[str, float]:
    out = {}
    for a in code.split()[1:]:
        if len(a) > 1 and a[0].isalpha() and NUM.match(a[1:]):
            out[a[0]] = float(a[1:])
    return out


def walk(text: str, plate: printed.Plate) -> dict:
    """One pass over an OrcaSlicer G-code (this profile; relative E, M83).

    Blocks: "start" is every line before the first "; CHANGE_LAYER"; "end" is every line
    from the first "; FEATURE: Custom" after that (the end code; the A1 end template sets
    no FEATURE of its own, Orca writes Custom before it); in between, "layer N" from the
    N-th "; CHANGE_LAYER". An extrusion is a G0-G3 move with E > 0 that changes X or Y
    (arcs: chord points from tdmg.printed._arc); an "E-only" move has E > 0 and no XY
    change. Every T<n> line is recorded with its block and the M620 pair it lies in.
    """
    lines = text.splitlines()
    tool = None
    feature = None
    block, layer = "start", 0
    layers = []                       # {"n", "z", "height"}
    x = y = None
    rel_xy, rel_e = False, None
    m620 = None                       # n of the open M620 S<n>A (or 255 for M620 S255)
    tc = None                         # the open CP TOOLCHANGE record
    flush_open = False
    markers = {}
    tools, m62x, changes = [], [], []
    segs = {}                         # layer n -> [(tool, feature, Segment)]
    xy_e, eonly = {}, {}
    width = None
    t1000 = []
    for i, raw in enumerate(lines, 1):
        c = raw.strip()
        if c.startswith(";"):
            tag = c[1:].strip()
            if tag in MARKERS:
                markers[tag] = markers.get(tag, 0) + 1
            if tag == "CHANGE_LAYER":
                if block == "end":
                    raise ValueError(f"line {i}: a layer after the end code began")
                layer += 1
                block = f"layer {layer}"
                layers.append({"n": layer, "z": None, "height": None, "line": i})
            elif tag.startswith("Z_HEIGHT:") and layers and layers[-1]["z"] is None:
                layers[-1]["z"] = float(tag.split(":", 1)[1])
            elif tag.startswith("LAYER_HEIGHT:") and layers and layers[-1]["height"] is None:
                layers[-1]["height"] = float(tag.split(":", 1)[1])
            elif tag.startswith("LINE_WIDTH:"):
                width = float(tag.split(":", 1)[1])
            elif tag.startswith("FEATURE:"):
                feature = tag.split(":", 1)[1].strip()
                if feature == "Custom" and layer > 0:
                    block = "end"
            elif tag == "CP TOOLCHANGE START":
                tc = {"line": i, "block": block, "from": tool, "to": None, "flush_e": 0.0,
                      "other_e_only": 0.0, "xy_e": 0.0, "flush_length_L": None,
                      "flush_blocks": 0}
            elif tag == "CP TOOLCHANGE END":
                if tc is None:
                    raise ValueError(f"line {i}: CP TOOLCHANGE END without START")
                changes.append(tc)
                tc = None
            elif tag == "FLUSH_START":
                flush_open = True
                if tc is not None:
                    tc["flush_blocks"] += 1
            elif tag == "FLUSH_END":
                flush_open = False
            continue
        code = c.split(";", 1)[0].strip()
        if not code:
            continue
        w = code.split()
        cmd = w[0]
        if cmd == "M620" and len(w) > 1:
            m62x.append({"line": i, "block": block, "code": code})
            mm = re.fullmatch(r"S(\d+)(A?)", w[1])
            if mm:
                m620 = int(mm.group(1))
        elif cmd == "M621" and len(w) > 1:
            m62x.append({"line": i, "block": block, "code": code})
            m620 = None
        elif cmd == "M620.10" and tc is not None:
            ww = _words(code)
            if ww.get("A") == 1 and "L" in ww:
                tc["flush_length_L"] = ww["L"]
        elif re.fullmatch(r"T\d+", cmd):
            n = int(cmd[1:])
            if n == 1000:             # A1 start code; not a filament (it is never < 255 use)
                t1000.append({"line": i, "block": block})
                continue
            tools.append({"line": i, "block": block, "T": n, "prev": tool,
                          "in_m620_for": m620, "in_toolchange": tc is not None})
            if n < 255:
                tool = n
                if tc is not None:
                    tc["to"] = n
            continue
        elif cmd == "M82":
            rel_e = False
        elif cmd == "M83":
            rel_e = True
        elif cmd == "G90":
            rel_xy = False
        elif cmd == "G91":
            rel_xy = True
        elif cmd == "G28" or cmd in printed.FIRMWARE_G_COMMANDS:
            x = y = None
        elif cmd in MOVE:
            ww = _words(code)
            if rel_xy:
                nx = None if x is None else x + ww.get("X", 0.0)
                ny = None if y is None else y + ww.get("Y", 0.0)
            else:
                nx, ny = ww.get("X", x), ww.get("Y", y)
            e = ww.get("E", 0.0)
            moved = (nx, ny) != (x, y)
            if e > 0 and rel_e is not True:
                raise ValueError(f"line {i}: E in absolute or unknown extrusion mode")
            if e > 0 and moved:
                lk = layer if block.startswith("layer") else block
                k = (tool, feature, lk)
                xy_e[k] = xy_e.get(k, 0.0) + e
                if tc is not None:
                    tc["xy_e"] += e
                if block.startswith("layer") and feature != "Custom":
                    if x is None or y is None or nx is None or ny is None:
                        raise ValueError(f"line {i}: an extrusion from an unknown position")
                    if cmd in ("G2", "G3"):
                        if "I" not in ww and "J" not in ww:
                            raise ValueError(f"line {i}: an arc without I/J")
                        pts, _len, _sw = printed._arc(x, y, nx, ny, ww, cmd == "G2", plate,
                                                      f"line {i}")
                    else:
                        pts = [(nx, ny)]
                    px, py = x, y
                    for qx, qy in pts:
                        if (qx, qy) != (px, py):
                            segs.setdefault(layer, []).append(
                                (tool, feature, printed.Segment(px, py, qx, qy, width,
                                                                feature)))
                        px, py = qx, qy
            elif e > 0:
                where = ("flush" if flush_open else "toolchange_other" if tc is not None
                         else block if block in ("start", "end") else "layers_other")
                k = (tool, where)
                eonly[k] = eonly.get(k, 0.0) + e
                if tc is not None:
                    tc["flush_e" if flush_open else "other_e_only"] += e
            x, y = nx, ny
    if tc is not None:
        raise ValueError("an open CP TOOLCHANGE at the end")
    return {"lines": len(lines), "markers": markers, "layers": layers, "tools": tools,
            "t1000": t1000, "m62x": m62x, "changes": changes, "segs": segs, "xy_e": xy_e,
            "eonly": eonly}


def header_values(text: str) -> dict:
    out = {}
    for ln in text.splitlines()[:30] + text.splitlines()[-40:]:
        m = re.match(r"^; model printing time: (.*); total estimated time: (.*)$", ln)
        if m:
            out["model_printing_time"], out["total_estimated_time"] = m.groups()
        for key in ("filament used [mm]", "filament used [cm3]", "filament used [g]",
                    "total layer number", "filament: ", "max_z_height"):
            if ln.startswith(f"; {key}"):
                out[key.rstrip(": ")] = ln.split("=", 1)[-1].split(":", 1)[-1].strip()
    for ln in text.splitlines():
        for key in ("flush_volumes_matrix", "flush_multiplier", "filament_colour",
                    "prime_volume", "wipe_tower_x", "wipe_tower_y", "prime_tower_width",
                    "enable_prime_tower", "flush_into_infill", "flush_into_objects",
                    "filament_prime_volume", "arc_fitting", "enable_arc_fitting"):
            if ln.startswith(f"; {key} = "):
                out.setdefault(key, ln.split("=", 1)[1].strip())
    return out


def to_seconds(t: str) -> int:
    total = 0
    for v, u in re.findall(r"(\d+)([dhms])", t):
        total += int(v) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[u]
    return total


# --- Expected sets and minimum changes --------------------------------------------------------

def expected_sets(layers, bodies) -> list[list[int]]:
    """Per layer, the bodies (palette index) whose z range holds the layer's mid-height."""
    zr = [(float(v[:, 2].min()), float(v[:, 2].max())) for _, v, _, _ in bodies]
    return [[i for i, (a, b) in enumerate(zr) if a < lay["z"] - lay["height"] / 2 < b]
            for lay in layers]


def min_changes(sets: list[list[int]], loaded: int) -> int:
    """The fewest tool changes that print every layer's set, starting from `loaded`
    (exact, by dynamic programming over the last tool of each layer)."""
    best = {loaded: 0}
    for s in sets:
        if not s:
            continue
        nxt = {}
        for p, cost in best.items():
            for last in s:
                if len(s) == 1:
                    c = cost + (0 if p == last else 1)
                elif p in s:
                    c = cost + len(s) - 1 if last != p else cost + len(s)
                else:
                    c = cost + len(s)
                nxt[last] = min(nxt.get(last, math.inf), c)
        best = nxt
    return min(best.values())


def decision4_count(sets, orders, loaded: int) -> int:
    """Plan Decision 4's formula on the actual order: sum over layers of (colors - 1),
    plus one where a layer does not start with the previous layer's last color (the start
    code's filament before layer 1)."""
    total, prev = 0, loaded
    for s, o in zip(sets, orders, strict=True):
        if not s:
            continue
        total += len(s) - 1
        if o and o[0] != prev:
            total += 1
        if o:
            prev = o[-1]
    return total


# --- Placement --------------------------------------------------------------------------------

def _trimesh(v, f):
    import trimesh
    return trimesh.Trimesh(v.astype(np.float64), f, process=False)


def _sample(segs) -> np.ndarray:
    out = []
    for s in segs:
        n = max(1, math.ceil(math.hypot(s.x1 - s.x0, s.y1 - s.y0) / SAMPLE_MM))
        t = np.linspace(0, 1, n + 1)
        out.append(np.column_stack([s.x0 + (s.x1 - s.x0) * t, s.y0 + (s.y1 - s.y0) * t]))
    return np.concatenate(out)


def placement(facts: dict, bodies, plate: printed.Plate) -> dict:
    """Where each tool's model extrusion lies, against the bodies, layer by layer.

    Body sections are cut at each layer's mid-height (tdmg.printed.model_section). Bed
    position: the shift that puts the model's bounding-box centre on the centre of the base
    tool's (T0) printed extent, fitted once from all layers; the record also gives the
    shift that tdmg.printed assumes for R1 (box centre on the plate centre). The fitted
    shift comes from the base only, so the inlays' positions relative to the base are
    still tested.
    """
    allv = np.concatenate([v for _, v, _, _ in bodies])
    lo, hi = allv.min(0).astype(np.float64), allv.max(0).astype(np.float64)
    centre = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
    base = [s for n in facts["segs"] for (t, f, s) in facts["segs"][n]
            if t == 0 and f in printed.MODEL_FEATURES]
    if not base:
        raise ValueError("no base extrusion")
    bx = [p for s in base for p in (s.x0, s.x1)]
    by = [p for s in base for p in (s.y0, s.y1)]
    fitted = ((min(bx) + max(bx)) / 2, (min(by) + max(by)) / 2)
    align = printed.Alignment(0, centre, fitted)
    meshes = [_trimesh(v, f) for _, v, f, _ in bodies]
    zr = [(float(v[:, 2].min()), float(v[:, 2].max())) for _, v, _, _ in bodies]
    per_layer = []
    for lay in facts["layers"]:
        mid = lay["z"] - lay["height"] / 2
        bed = [align.apply(printed.model_section(m, mid)) if a < mid < b
               else shapely.Polygon() for m, (a, b) in zip(meshes, zr, strict=True)]
        by_tool = {}
        for t, feat, s in facts["segs"].get(lay["n"], []):
            if feat in printed.MODEL_FEATURES:
                by_tool.setdefault(t, []).append(s)
        entry = {"n": lay["n"], "z": lay["z"], "mid_z": mid,
                 "bodies_present": [i for i, s in enumerate(bed) if not s.is_empty],
                 "tools": {}}
        for t, ss in sorted(by_tool.items(), key=lambda kv: (kv[0] is None, kv[0])):
            pts = _sample(ss)
            own = bed[t] if t is not None and 0 <= t < len(bed) else shapely.Polygon()
            d = printed.gaps(pts, own)
            fp = printed.footprint(ss)
            others = {}
            for j, sec in enumerate(bed):
                if j != t and not sec.is_empty:
                    shapely.prepare(sec)
                    k = int(shapely.contains_xy(sec, pts[:, 0], pts[:, 1]).sum())
                    if k:
                        others[str(j)] = k
            entry["tools"][str(t)] = {
                "segments": len(ss), "samples": len(pts),
                "max_centreline_outside_own_mm": float(d.max()),
                "samples_outside_own": int((d > 0).sum()),
                "samples_inside_other_bodies": others,
                "own_area_mm2": float(own.area),
                "own_covered_mm2": float(own.intersection(fp).area) if not own.is_empty
                else 0.0,
                "bead_outside_own_mm2": float(fp.difference(own).area),
                "widths": sorted({s.width for s in ss})}
        entry["bodies_without_their_tool"] = [i for i in entry["bodies_present"]
                                              if str(i) not in entry["tools"]]
        entry["tools_without_their_body"] = [t for t in entry["tools"]
                                             if t == "None" or int(t) not in
                                             entry["bodies_present"]]
        per_layer.append(entry)
    return {"model_bbox_centre": list(centre), "fitted_bed_centre": list(fitted),
            "plate_centre": list(plate.centre),
            "fitted_minus_plate_centre_mm": [fitted[0] - plate.centre[0],
                                             fitted[1] - plate.centre[1]],
            "layers": per_layer}


# --- Analysis -------------------------------------------------------------------------------

def analyse_one(gcode: Path, stats_path: Path, bodies, plate, diameter: float) -> dict:
    text = gcode.read_text("utf-8", errors="strict")
    facts = walk(text, plate)
    hdr = header_values(text)
    layers = facts["layers"]
    area = math.pi * diameter ** 2 / 4
    start_t = [t for t in facts["tools"] if t["block"] == "start"]
    layer_t = [t for t in facts["tools"] if t["block"].startswith("layer")]
    end_t = [t for t in facts["tools"] if t["block"] == "end"]
    # Order of tools per layer: the tool loaded at the layer's start, then each T in it.
    orders_all, orders_model = [], []
    for lay in layers:
        n = lay["n"]
        seq = []
        for t, feat, _s in facts["segs"].get(n, []):
            if feat in printed.MODEL_FEATURES and (not seq or seq[-1] != t):
                seq.append(t)
        orders_model.append(seq)
        seq2 = []
        for t, feat, _s in facts["segs"].get(n, []):
            if not seq2 or seq2[-1] != t:
                seq2.append(t)
        orders_all.append(seq2)
    sets = expected_sets(layers, bodies)
    loaded = start_t[-1]["T"] if start_t else None
    printed_sets = [sorted(set(o)) for o in orders_model]
    # Per tool, by feature: E on XY moves (mm and mm3), layers.
    per_tool = {}
    for (t, feat, lk), e in facts["xy_e"].items():
        d = per_tool.setdefault(str(t), {"xy_e_mm_by_feature": {}, "model_layers": set()})
        d["xy_e_mm_by_feature"][feat] = d["xy_e_mm_by_feature"].get(feat, 0.0) + e
        if feat in printed.MODEL_FEATURES and isinstance(lk, int):
            d["model_layers"].add(lk)
    for (t, where), e in facts["eonly"].items():
        d = per_tool.setdefault(str(t), {"xy_e_mm_by_feature": {}, "model_layers": set()})
        d.setdefault("e_only_mm", {})[where] = e
    for t, d in per_tool.items():
        d["model_layers"] = sorted(d["model_layers"])
        d["model_e_mm"] = sum(v for k, v in d["xy_e_mm_by_feature"].items()
                              if k in printed.MODEL_FEATURES)
        d["model_mm3"] = d["model_e_mm"] * area
        d["prime_tower_mm3"] = d["xy_e_mm_by_feature"].get("Prime tower", 0.0) * area
        d["flush_mm3"] = d.get("e_only_mm", {}).get("flush", 0.0) * area
        d["toolchange_other_mm3"] = d.get("e_only_mm", {}).get("toolchange_other", 0.0) * area
        d["total_e_mm"] = sum(d["xy_e_mm_by_feature"].values()) + sum(
            d.get("e_only_mm", {}).values())
        exts = [s for n in facts["segs"] for (tt, f, s) in facts["segs"][n]
                if str(tt) == t and f in printed.MODEL_FEATURES]
        if exts:
            d["model_xy_extent"] = [min(min(s.x0, s.x1) for s in exts),
                                    min(min(s.y0, s.y1) for s in exts),
                                    max(max(s.x0, s.x1) for s in exts),
                                    max(max(s.y0, s.y1) for s in exts)]
        pt = [s for n in facts["segs"] for (tt, f, s) in facts["segs"][n]
              if str(tt) == t and f == "Prime tower"]
        if pt:
            d["prime_tower_xy_extent"] = [min(min(s.x0, s.x1) for s in pt),
                                          min(min(s.y0, s.y1) for s in pt),
                                          max(max(s.x0, s.x1) for s in pt),
                                          max(max(s.y0, s.y1) for s in pt)]
    stats = json.loads(stats_path.read_text("utf-8")) if stats_path.is_file() else None
    st = None
    if stats:
        s = stats["summary"]
        st = {"time_s": s["time"], "prepare_time_s": s.get("prepare_time"),
              "layer_count": s["layer_count"], "filament_changes": s.get("filament_changes"),
              "volume_mm3": s["volume"], "weight_g": s["weight"],
              "filaments": [{"id": f["id"], "volume": f["volume"],
                             "model": f["model"]["volume"],
                             "prime_tower": f["prime_tower"]["volume"],
                             "flush": f["flush"]["volume"]} for f in s["filaments"]],
              "features_volume": {k: v["volume"] for k, v in s["features"].items()}}
    place = placement(facts, bodies, plate)
    changes = facts["changes"]
    return {
        "layers": [{"n": lay["n"], "z": lay["z"], "height": lay["height"]} for lay in layers],
        "markers": facts["markers"],
        "header": hdr,
        "time_s": {k: to_seconds(hdr[k]) for k in ("model_printing_time",
                                                   "total_estimated_time") if k in hdr},
        "start_tools": start_t, "t1000": facts["t1000"], "end_tools": end_t,
        "layer_tools": layer_t,
        "m62x": facts["m62x"],
        "loaded_by_start": loaded,
        "start_loads_filament_1": bool(start_t) and len(start_t) == 1 and loaded == 0
        and start_t[0]["in_m620_for"] == 0,
        "real_changes": len([t for t in layer_t if t["T"] < 255]),
        "changes_all_in_m620_pair": all(t["in_m620_for"] == t["T"] for t in layer_t),
        "changes_all_in_cp_toolchange": all(t["in_toolchange"] for t in layer_t),
        "end_unload": [t["T"] for t in end_t],
        "expected_sets": sets,
        "printed_model_sets": printed_sets,
        "sets_match": [sorted(a) == b for a, b in zip(sets, printed_sets, strict=True)],
        "orders_model": orders_model,
        "orders_all_features": orders_all,
        "minimum_changes": min_changes(sets, 0),
        "decision4_formula_on_actual_order": decision4_count(sets, orders_model, 0),
        "toolchange_blocks": [{k: (round(v, 5) if isinstance(v, float) else v)
                               for k, v in c.items()} for c in changes],
        "flush_mm3_total": sum(c["flush_e"] for c in changes) * area,
        "toolchange_other_e_only_mm3_total": sum(c["other_e_only"] for c in changes) * area,
        "prime_tower_mm3_total": sum(d["prime_tower_mm3"] for d in per_tool.values()),
        "per_tool": per_tool,
        "statistics": st,
        "placement": place,
    }


def placement_summary(place: dict) -> dict:
    out = {}
    for lay in place["layers"]:
        for t, d in lay["tools"].items():
            o = out.setdefault(t, {"layers": [], "max_centreline_outside_own_mm": 0.0,
                                   "samples_outside_own": 0, "samples": 0,
                                   "samples_inside_other_bodies": 0,
                                   "bead_outside_own_mm2": 0.0, "own_area_mm2": 0.0,
                                   "own_covered_mm2": 0.0})
            o["layers"].append(lay["n"])
            o["max_centreline_outside_own_mm"] = max(o["max_centreline_outside_own_mm"],
                                                     d["max_centreline_outside_own_mm"])
            o["samples_outside_own"] += d["samples_outside_own"]
            o["samples"] += d["samples"]
            o["samples_inside_other_bodies"] += sum(d["samples_inside_other_bodies"].values())
            o["bead_outside_own_mm2"] += d["bead_outside_own_mm2"]
            o["own_area_mm2"] += d["own_area_mm2"]
            o["own_covered_mm2"] += d["own_covered_mm2"]
    for o in out.values():
        o["own_covered_fraction"] = (o["own_covered_mm2"] / o["own_area_mm2"]
                                     if o["own_area_mm2"] else None)
    return {"by_tool": out,
            "bodies_without_their_tool": {lay["n"]: lay["bodies_without_their_tool"]
                                          for lay in place["layers"]
                                          if lay["bodies_without_their_tool"]},
            "tools_without_their_body": {lay["n"]: lay["tools_without_their_body"]
                                         for lay in place["layers"]
                                         if lay["tools_without_their_body"]}}


def analyse(out: Path, variant: str = "plain") -> None:
    pin = slicer.load_pin()
    orc = slicer.locate(REPO / "artifacts/tools/orcaslicer-2.5.0", pin, full_tree=False)
    machine = json.loads(Path(orc.profiles["machine"]).read_text("utf-8"))
    filament = json.loads(Path(orc.profiles["filament"]).read_text("utf-8"))
    plate = printed.plate_from_profile(machine)
    diameter = printed.flow_from_profile(filament).filament_diameter_mm
    runs = json.loads((out / f"orca-{variant}.json").read_text("utf-8"))["runs"]
    full, summary = {}, {}
    for stem, rec in sorted(runs.items()):
        plan, face = plan_of(stem)
        bodies = faced(plan, face)
        o = out / "orca" / variant / stem / "out"
        if not (o / slicer.GCODE_NAME).is_file():
            summary[stem] = {"exit": rec["exit"], "gcode": None}
            continue
        a = analyse_one(o / slicer.GCODE_NAME, o / slicer.STATS_NAME, bodies, plate, diameter)
        full[stem] = a
        ps = placement_summary(a["placement"])
        summary[stem] = {
            "exit": rec["exit"]["signed"] if rec["exit"] else None,
            "filaments_loaded": rec["filaments"],
            "layers": len(a["layers"]),
            "layer_z": [lay["z"] for lay in a["layers"]],
            "start_loads_filament_1": a["start_loads_filament_1"],
            "start_tools": [(t["T"], t["in_m620_for"]) for t in a["start_tools"]],
            "t1000_lines": len(a["t1000"]),
            "real_changes": a["real_changes"],
            "minimum_changes": a["minimum_changes"],
            "decision4_formula_on_actual_order": a["decision4_formula_on_actual_order"],
            "statistics_filament_changes": (a["statistics"] or {}).get("filament_changes"),
            "changes_all_in_m620_pair": a["changes_all_in_m620_pair"],
            "changes_all_in_cp_toolchange": a["changes_all_in_cp_toolchange"],
            "end_unload": a["end_unload"],
            "sets_match_all": all(a["sets_match"]),
            "orders_by_layer": {lay["n"]: o2 for lay, o2 in zip(a["layers"], a["orders_model"],
                                                                 strict=True)
                                if len(o2) > 1 or (o2 and o2 != [0])},
            "expected_sets_by_layer": {lay["n"]: s for lay, s in zip(a["layers"],
                                                                      a["expected_sets"],
                                                                      strict=True)
                                       if s != [0]},
            "toolchanges": [(c["from"], c["to"], c["block"], round(c["flush_e"], 4),
                             c["flush_length_L"], c["flush_blocks"],
                             round(c["other_e_only"], 4), round(c["xy_e"], 4))
                            for c in a["toolchange_blocks"]],
            "flush_mm3": round(a["flush_mm3_total"], 3),
            "toolchange_other_e_only_mm3": round(a["toolchange_other_e_only_mm3_total"], 3),
            "prime_tower_mm3": round(a["prime_tower_mm3_total"], 3),
            "time_s": a["time_s"], "header": a["header"],
            "per_tool": {t: {"model_mm3": round(d["model_mm3"], 3),
                             "prime_tower_mm3": round(d["prime_tower_mm3"], 3),
                             "flush_mm3": round(d["flush_mm3"], 3),
                             "toolchange_other_mm3": round(d["toolchange_other_mm3"], 3),
                             "total_e_mm": round(d["total_e_mm"], 3),
                             "model_layers": d["model_layers"],
                             "features_e_mm": {k: round(v, 3) for k, v in
                                               d["xy_e_mm_by_feature"].items()},
                             "e_only_mm": {k: round(v, 3) for k, v in
                                           d.get("e_only_mm", {}).items()},
                             "model_xy_extent": [round(v, 3) for v in
                                                 d.get("model_xy_extent", [])],
                             "prime_tower_xy_extent": [round(v, 3) for v in
                                                       d.get("prime_tower_xy_extent", [])]}
                         for t, d in sorted(a["per_tool"].items())},
            "statistics": a["statistics"],
            "placement": {"fitted_bed_centre": a["placement"]["fitted_bed_centre"],
                          "fitted_minus_plate_centre_mm":
                              a["placement"]["fitted_minus_plate_centre_mm"], **ps},
            "markers": a["markers"],
        }
        print(stem, json.dumps({k: summary[stem][k] for k in (
            "exit", "layers", "start_loads_filament_1", "real_changes", "minimum_changes",
            "decision4_formula_on_actual_order", "statistics_filament_changes",
            "sets_match_all", "orders_by_layer", "flush_mm3", "prime_tower_mm3", "time_s")}))
        for t, d in summary[stem]["placement"]["by_tool"].items():
            print("   T", t, "layers", d["layers"][0], "-", d["layers"][-1],
                  "max out", round(d["max_centreline_outside_own_mm"], 4),
                  "out samples", d["samples_outside_own"], "/", d["samples"],
                  "in others", d["samples_inside_other_bodies"],
                  "covered", d["own_covered_fraction"] and round(d["own_covered_fraction"], 4))
        print("   missing", summary[stem]["placement"]["bodies_without_their_tool"],
              "stray", summary[stem]["placement"]["tools_without_their_body"],
              "centre-plate", [round(v, 3) for v in
                               summary[stem]["placement"]["fitted_minus_plate_centre_mm"]])
    (out / f"analysis-{variant}.json").write_text(json.dumps(summary, indent=1, default=str),
                                                 encoding="utf-8")
    (out / f"analysis-{variant}-full.json").write_text(
        json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "placement"} | {
            "placement_layers": v["placement"]["layers"]} for k, v in full.items()},
            indent=1, default=str), encoding="utf-8")


# --- The amended rules (controller decisions after the stop) ---------------------------------

def check_rules(out: Path, variant: str) -> None:
    """Check the amended Decisions 2 and 4 on every run of a variant, from the full analysis.

    Decision 2: the start block loads exactly one filament (one T<n> below 255, T1000 aside,
    inside its M620 S<n>A pair), and it is the first tool that prints on layer 1 (model
    features; also checked over all features, the prime tower included).
    Decision 4: (a) each layer's set of tools printing model features equals the set of
    bodies on it; (b) on each layer each tool prints in one contiguous run; (c) the real
    change count equals sum(colors - 1) + the boundaries where a layer's first tool differs
    from the previous layer's last (layer 1 against the start-loaded tool); (d) the exact
    minimum, as information.
    """
    full = json.loads((out / f"analysis-{variant}-full.json").read_text("utf-8"))
    res = {}
    for stem, a in sorted(full.items()):
        orders, sets = a["orders_model"], a["expected_sets"]
        start = [t for t in a["start_tools"] if t["T"] < 255]
        loaded = start[0]["T"] if len(start) == 1 else None
        first_model = orders[0][0] if orders and orders[0] else None
        first_any = (a["orders_all_features"][0][0] if a["orders_all_features"]
                     and a["orders_all_features"][0] else None)
        d2 = (len(start) == 1 and start[0]["in_m620_for"] == loaded
              and loaded == first_model)
        sets_ok = all(sorted(set(o)) == s for o, s in zip(orders, sets, strict=True))
        contiguous = all(len(o) == len(set(o)) for o in orders)
        formula, prev = 0, loaded
        for o in orders:
            if not o:
                continue
            formula += len(o) - 1 + (1 if o[0] != prev else 0)
            prev = o[-1]
        res[stem] = {
            "start_tools": [(t["T"], t["in_m620_for"]) for t in start],
            "t1000_lines": len(a["t1000"]),
            "first_model_tool_layer1": first_model,
            "first_tool_any_feature_layer1": first_any,
            "d2_start_loads_one_filament_the_first_of_layer1": d2,
            "d4a_sets_equal_bodies": sets_ok,
            "d4b_contiguous_runs": contiguous,
            "d4c_formula": formula, "real_changes": a["real_changes"],
            "d4c_holds": formula == a["real_changes"],
            "d4d_exact_minimum_from_loaded": min_changes(sets, loaded),
            "d4d_exact_minimum_from_base": a["minimum_changes"],
            "d4d_exact_minimum_free_start": min(min_changes(sets, t) for t in sets[0]),
            "statistics_filament_changes": (a["statistics"] or {}).get("filament_changes")}
        r = res[stem]
        print(stem, r["start_tools"], "L1 first", first_model, first_any, "D2", d2, "a", sets_ok,
              "b", contiguous, "c", formula, a["real_changes"], "min", r[
                  "d4d_exact_minimum_from_loaded"], r["d4d_exact_minimum_free_start"],
              "stats", r["statistics_filament_changes"])
    (out / f"rules-{variant}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


def check_profiles(out: Path) -> None:
    """The derived filament profiles of the colours variant: sha256, and the parsed-JSON
    difference from the pinned filament profile (must be exactly filament_colour)."""
    pin = slicer.load_pin()
    orc = slicer.locate(REPO / "artifacts/tools/orcaslicer-2.5.0", pin, full_tree=False)
    pinned_path = Path(orc.profiles["filament"])
    pinned = json.loads(pinned_path.read_text("utf-8"))
    res = {"pinned": {"sha256": mi.sha(pinned_path),
                      "filament_colour": pinned.get("filament_colour", "(absent)")},
           "derived": {}}
    for plan in PLANS:
        pal = json.loads((RUNS / plan / "palette.json").read_text("utf-8"))
        hexes = {s["index"]: s["hex"].upper() for s in pal["shells"]}
        for p in sorted((out / "filaments" / plan).glob("filament-*.json")):
            d = json.loads(p.read_text("utf-8"))
            keys = sorted(set(d) | set(pinned))
            diff = [k for k in keys if d.get(k, "(absent)") != pinned.get(k, "(absent)")]
            idx = int(p.stem.split("-")[1])
            res["derived"][f"{plan}/{p.name}"] = {
                "sha256": mi.sha(p), "differing_keys": diff,
                "filament_colour": d.get("filament_colour"),
                "palette_hex": hexes[idx],
                "ok": diff == ["filament_colour"] and d["filament_colour"] == [hexes[idx]]}
            print(plan, p.name, res["derived"][f"{plan}/{p.name}"]["ok"], diff,
                  d.get("filament_colour"))
    (out / "profiles-colours.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    cmd, outdir = sys.argv[1], Path(sys.argv[2])
    if cmd == "build":
        build(outdir)
    elif cmd == "orca":
        orca(outdir, sys.argv[3] if len(sys.argv) > 3 else "plain",
             sys.argv[4] if len(sys.argv) > 4 else None)
    elif cmd == "analyse":
        analyse(outdir, sys.argv[3] if len(sys.argv) > 3 else "plain")
    elif cmd == "rules":
        check_rules(outdir, sys.argv[3] if len(sys.argv) > 3 else "plain")
    elif cmd == "profiles":
        check_profiles(outdir)
    else:
        raise SystemExit(f"unknown command {cmd}")

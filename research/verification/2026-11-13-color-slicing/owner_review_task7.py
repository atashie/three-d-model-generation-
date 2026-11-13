"""Task 7 review material: per-layer pictures of the owner slices' color layers, an overview
per plan, and a text summary of the F3 numbers and where the largest gaps are.

Usage (from the repo root, Windows, both slicers installed as in CLAUDE.md; run Task 6's
owner_slices_task6.py first so artifacts/slice-runs/color-<plan> exists):
    uv run python research/verification/2026-11-13-color-slicing/owner_review_task7.py

Reads, for each plan, artifacts/colored-runs/<plan> (the bodies, as tdmg slice reads them)
and artifacts/slice-runs/color-<plan> (slice.json and each face's G-code). Writes the PNGs
to artifacts/color-review/<plan>/ (git-ignored) and owner-review.txt beside this script.

Nothing here re-implements the reading or the measurement: the G-code is read with
tdmg.color_gcode.read_multicolor, the bodies with tdmg.color_slicing.read_colored and
ams_shells (face down: tdmg.orca_input.turn_over), and each layer is measured with
tdmg.printed's footprint, model_section, Alignment, edge_gaps and layer_metrics, with the
arguments tdmg.color_gcode._geometry and _placed use. Every per-layer value is compared
with the face's slice.json record before anything is drawn (the script stops on a
difference). The extra descriptions (uncovered patches, the thin-strip test, the
neighbouring body) are research measures for the review, not checks.

Research code: not part of the package. It imports two private helpers
(tdmg.color_gcode._mesh, tdmg.printed._polygons) read-only.
"""

from __future__ import annotations

import json
import math
import sys
import textwrap
from pathlib import Path

import numpy as np
import shapely
from PIL import Image, ImageChops, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "src"))

from tdmg.color_gcode import PLACEMENT_ANGLE, _mesh, layer_sets, read_multicolor, sorted_segments
from tdmg.color_slicing import allowed_counts, ams_shells, read_colored
from tdmg.orca_input import turn_over
from tdmg.printed import Alignment, _polygons, edge_gaps, footprint, layer_metrics, model_section
from tdmg.slicing import prepare

PLANS = ("roadie-tol30-60-drop-v3-f64", "roadie-tol30-60-keep-v4-f64",
         "oddie-60-merge-blues-v3-f64", "oddie-60-keep-merge-blues-greens-v4-f64")
ORCA = REPO / "artifacts/tools/orcaslicer-2.5.0"
PRUSA = REPO / "artifacts/tools/prusaslicer-2.9.7"
OUT = REPO / "artifacts/color-review"

# Display choices (not measurements).
PX_PER_MM = 10
MARGIN_MM = 3
BACKGROUND = (150, 150, 150)
TINT = 0.4                     # unprinted body: this share of its colour over the background
SPLIT_SEARCH_MM = 0.5          # printed parts closer than this are drawn as a split
PATCHES_LISTED = 3
FONT = "arial.ttf"

# Colour names: my description of each hex, not from the palette.
NAMES = {"#f60606": "red", "#451812": "dark brown", "#f5f5f5": "white",
         "#f0f10a": "yellow", "#25561b": "dark green", "#547e9d": "steel blue",
         "#48a835": "green", "#dd4f47": "coral red", "#0d100d": "near-black"}
# What each body is in the picture, by eye from the plan's top.png (the review's reading,
# not a measurement). Only the bodies told apart with confidence are named.
ROLES = {
    "roadie-tol30-60-keep-v4-f64": {1: "the kept outline band (all outlines of the bird)"},
    "oddie-60-keep-merge-blues-greens-v4-f64": {
        2: "the kept outline band and the leaf-vein lines"},
}

# The reviewer's reading of the images and the numbers above (2026-11-13). Not a check, and
# not computed: it was written after looking at the outputs of this script.
READING = """
== Reading (2026-11-13, from the images and the numbers above; an interpretation, not a check)
1. The silhouette's F3.printed_connectivity FAILs on every color layer of every run because
   neighbouring colors' beads meet edge to edge. The splits (cyan crosses) are 0.000-0.149 mm
   wide on the drop plans and Oddie merge, where every body is printed. In the bead model two
   colors side by side always leave such a hairline; this alone is not a missing part of the
   model. On the keep plans some splits are wider (up to 0.36-0.48 mm): there an outline strip
   between two colors is not printed (item 3).
2. Drop plans and Oddie merge: the per-color coverage FAILs are 0.201-0.359 mm, 0.001-0.084 mm
   over the allowance, at the model's outer edge or a shared edge where the body is narrower
   than one bead (tips and corners). On the color layers 1-14% of each larger body has no bead
   of its own tool (the bead model's unsquashed beads leave some); the small bodies (Roadie drop
   T3, 4.2 mm2; Oddie merge T3, 36 mm2) 8-39%. Face up and face down look alike.
3. Keep plans: the large gaps (Roadie keep T1 up to 7.59 mm, Oddie keep T2 up to 10.33 mm) are
   outline color the slicer does not print.
   - Face up: the thin lines of the outline color inside the picture (Roadie: the brown lines
     between belly, body and eye; Oddie: the leaf veins and the lines between colors) are not
     printed; the outer outline band is. 18-19% of Roadie's T1 and 28% of Oddie's T2 have no
     bead on the top layers.
   - Face down, layer 1 (the visible face): most of the outline color is not printed: 68% of
     Roadie's T1 (beads 195 mm long, against 778 mm on face-up layer 13) and 88% of Oddie's T2
     (77 mm against 721 mm). Layers 2 and 3 are like face up. The silhouette's coverage FAILs
     there (1.179 and 0.637 mm). OrcaSlicer prints layer 1 with 0.5 mm lines (0.42 mm above);
     that this is why the narrow outline is skipped is an inference, not tested.
4. Face up against face down: changes 9 on both except Roadie drop face down (10; minimum 9).
   Prime tower about 1,055 mm3 face up, 548-592 mm3 face down. Flush equal on Oddie merge,
   +100 mm3 face down on Roadie drop and +200 on Oddie keep, -27 on Roadie keep. Time within
   2 minutes (face up 1,873-2,124 s, face down 1,868-2,096 s).
"""

MAGENTA, CYAN, BLACK, WHITE =(255, 0, 255), (0, 230, 255), (0, 0, 0), (255, 255, 255)
BLUE = (0, 60, 255)
ZOOM_PX_PER_MM = 40            # the close-ups around each tool's largest gap
ZOOM_HALF_MM = 4
LEGEND_MIN_PX = 1100


def hex_rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def font(size: int):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


# --- Measuring (the gate's own functions, the gate's arguments) ----------------------------


def measure_face(plan: str, face: str, shells, setup, record: dict) -> dict:
    folder = REPO / "artifacts/slice-runs" / f"color-{plan}" / f"face-{face}"
    gpath = next(p for p in (folder / "plate_1.gcode", folder / "plate_1.gcode.failed")
                 if p.is_file())
    mc = read_multicolor(gpath.read_text("utf-8"), setup.plate, setup.flow)
    sets = layer_sets(mc.layers, shells)
    n = len(shells)
    meshes = [_mesh(s) for s in shells]
    allv = np.concatenate([np.asarray(m.vertices) for m in meshes])
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    centre = (float(lo[0] + hi[0]) / 2, float(lo[1] + hi[1]) / 2)
    alignment = Alignment(PLACEMENT_ANGLE, centre, setup.plate.centre)
    first = setup.tolerance_mm + setup.elephant_foot_mm
    layers = []
    for k, (lay, s) in enumerate(zip(mc.layers, sets, strict=True)):
        allowance = first if k == 0 else setup.tolerance_mm
        sections = [model_section(meshes[t], lay.mid_z) if t in s else shapely.Polygon()
                    for t in range(n)]
        nonempty = [g for g in sections if not g.is_empty]
        sil = shapely.union_all(nonempty) if nonempty else shapely.Polygon()
        everything = footprint([seg for segs in mc.model[k].values()
                                for seg in sorted_segments(segs)])
        sil_m = layer_metrics(sil, everything, alignment, allowance)
        tools = []
        for t in range(n):
            printed = footprint(mc.model[k].get(t, []))     # as _placed: not re-sorted
            m = layer_metrics(sections[t], printed, alignment, allowance)
            e = edge_gaps(sections[t], printed, alignment)
            over = e[1][e[2] > allowance] if e is not None else np.empty((0, 2))
            widths = [seg.width for seg in mc.model[k].get(t, [])]
            tools.append({"section": alignment.apply(sections[t]), "printed": printed,
                          "metrics": m, "gap_points": over, "gap_values":
                          e[2][e[2] > allowance] if e is not None else np.empty(0),
                          "bead_mm": float(np.median(widths)) if widths else None,
                          "length_mm": sum(math.hypot(g.x1 - g.x0, g.y1 - g.y0)
                                           for g in mc.model[k].get(t, []))})
        e = edge_gaps(sil, everything, alignment)
        sil_over = e[1][e[2] > allowance] if e is not None else np.empty((0, 2))
        layers.append({"n": k + 1, "z": lay.z, "allowance": allowance, "bodies": s,
                       "order": mc.orders[k], "silhouette": alignment.apply(sil),
                       "everything": everything, "sil_metrics": sil_m,
                       "sil_gap_points": sil_over, "tools": tools,
                       "splits": splits(everything) if len(s) > 1 else []})
    compare(plan, face, layers, record)
    return {"layers": layers, "gcode": gpath.name}


def splits(printed) -> list[tuple[float, float, float]]:
    """Where the printed union is split: for each pair of its parts closer than
    SPLIT_SEARCH_MM, the midpoint of their shortest line and its length (bed mm)."""
    parts = _polygons(printed)
    if len(parts) < 2:
        return []
    arr = np.array(parts, dtype=object)
    i, j = shapely.STRtree(arr).query(arr, predicate="dwithin", distance=SPLIT_SEARCH_MM)
    out = []
    for a, b in zip(i, j, strict=True):
        if a < b:
            line = shapely.shortest_line(arr[a], arr[b])
            mid = line.interpolate(0.5, normalized=True)
            out.append((mid.x, mid.y, line.length))
    return out


def close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def compare(plan: str, face: str, layers: list[dict], record: dict) -> None:
    """Stop unless every per-layer gap, overprint and part count equals slice.json's."""
    rec = record["faces"][face]["color"]
    bad = []
    for L, r in zip(layers, rec["silhouette"]["layers"], strict=True):
        m = L["sil_metrics"]
        if not (close(m["max_gap_mm"], r["max_gap_mm"]) and close(m["max_over_mm"],
                r["max_over_mm"]) and [m["parts_model"], m["parts_printed"]] == r["parts"]):
            bad.append(("silhouette", L["n"]))
    for t, tr in rec["tools"].items():
        for L, r in zip(layers, tr["layers"], strict=True):
            m = L["tools"][int(t)]["metrics"]
            if not (close(m["max_gap_mm"], r["max_gap_mm"]) and close(m["max_over_mm"],
                    r["max_over_mm"]) and [m["parts_model"], m["parts_printed"]] == r["parts"]
                    and [m["holes_model"], m["holes_printed"]] == r["holes"]):
                bad.append((f"T{t}", L["n"]))
    if bad:
        raise SystemExit(f"{plan} face {face}: differs from slice.json at {bad}")


# --- Describing a gap ----------------------------------------------------------------------


def describe(L: dict, t: int) -> dict:
    """Where tool t's largest edge gap on this layer lies, and the uncovered patches."""
    tool = L["tools"][t]
    m = tool["metrics"]
    p = shapely.Point(m["at_bed_mm"])
    body = tool["section"]
    w = tool["bead_mm"] or 0.42
    opened = body.buffer(-w / 2).buffer(w / 2)
    thin = opened.is_empty or opened.distance(p) > 0.05
    sil = L["silhouette"]
    neighbour = "the model's outer edge" if sil.boundary.distance(p) < 0.02 else None
    if neighbour is None:
        near = [(L["tools"][j]["section"].distance(p), j) for j in range(len(L["tools"]))
                if j != t and not L["tools"][j]["section"].is_empty]
        d, j = min(near) if near else (math.inf, None)
        neighbour = f"the edge shared with T{j}" if d < 0.02 else "not identified"
    uncovered = _polygons(body.difference(tool["printed"]))
    patches = []
    for g in sorted(uncovered, key=lambda g: -g.area)[:PATCHES_LISTED]:
        mic = shapely.maximum_inscribed_circle(g, tolerance=0.005)
        c = g.representative_point()
        patches.append({"area": g.area, "widest": 2 * mic.length, "at": (c.x, c.y)})
    return {"at": (p.x, p.y), "gap": m["max_gap_mm"], "thin": thin, "bead": w,
            "edge": neighbour, "patches": patches,
            "uncovered_total": sum(g.area for g in uncovered),
            "body_area": body.area}


# --- Drawing ---------------------------------------------------------------------------------


class Canvas:
    def __init__(self, bounds, mirror=False, ppm=PX_PER_MM, margin=MARGIN_MM, tick=10):
        x0, y0, x1, y1 = bounds
        self.ppm, self.tick = ppm, tick
        self.x0, self.y1 = x0 - margin, y1 + margin
        self.w = math.ceil((x1 - x0 + 2 * margin) * ppm)
        self.h = math.ceil((y1 - y0 + 2 * margin) * ppm)
        self.mirror = mirror
        self.img = Image.new("RGB", (self.w, self.h), BACKGROUND)
        self.draw = ImageDraw.Draw(self.img)

    def px(self, x, y):
        u = (x - self.x0) * self.ppm
        return (self.w - u if self.mirror else u, (self.y1 - y) * self.ppm)

    def ring(self, coords):
        return [self.px(x, y) for x, y in coords]

    def fill(self, geom, rgb):
        mask = Image.new("L", self.img.size, 0)
        for poly in _polygons(geom):
            one = Image.new("L", self.img.size, 0)
            d = ImageDraw.Draw(one)
            d.polygon(self.ring(poly.exterior.coords), fill=255)
            for hole in poly.interiors:
                d.polygon(self.ring(hole.coords), fill=0)
            mask = ImageChops.lighter(mask, one)
        self.img.paste(Image.new("RGB", self.img.size, rgb), (0, 0), mask)

    def outline(self, geom, rgb, width=1):
        for poly in _polygons(geom):
            for r in (poly.exterior, *poly.interiors):
                self.draw.line(self.ring(r.coords), fill=rgb, width=width)

    def dots(self, pts, rgb, r):
        for x, y in pts:
            u, v = self.px(x, y)
            self.draw.ellipse((u - r, v - r, u + r, v + r), fill=rgb)

    def rings(self, pts, rgb, r, width=1):
        for x, y in pts:
            u, v = self.px(x, y)
            self.draw.ellipse((u - r, v - r, u + r, v + r), outline=rgb, width=width)

    def crosses(self, pts, rgb, r):
        for x, y in pts:
            u, v = self.px(x, y)
            self.draw.line((u - r, v - r, u + r, v + r), fill=rgb, width=2)
            self.draw.line((u - r, v + r, u + r, v - r), fill=rgb, width=2)

    def label(self, x, y, text, rgb=BLACK):
        u, v = self.px(x, y)
        f = font(13)
        box = self.draw.textbbox((u + 9, v - 8), text, font=f)
        self.draw.rectangle(box, fill=WHITE)
        self.draw.text((u + 9, v - 8), text, fill=rgb, font=f)

    def ticks(self):
        f = font(11)
        step = self.tick
        x = math.ceil(self.x0 / step) * step
        while (x - self.x0) * self.ppm < self.w:
            u, _ = self.px(x, 0)
            self.draw.line((u, 0, u, 6), fill=BLACK)
            self.draw.text((u + 2, 6), f"x{x:g}", fill=BLACK, font=f)
            x += step
        y = math.floor(self.y1 / step) * step
        while (self.y1 - y) * self.ppm < self.h:
            _, v = self.px(0, y)
            self.draw.line((0, v, 6, v), fill=BLACK)
            self.draw.text((8, v - 6), f"y{y:g}", fill=BLACK, font=f)
            y -= step


def tinted(rgb):
    return tuple(int(TINT * c + (1 - TINT) * b) for c, b in zip(rgb, BACKGROUND, strict=True))


def render(L: dict, fmap: list[dict], bounds, mirror=False, labels=True,
           **canvas) -> Image.Image:
    c = Canvas(bounds, mirror, **canvas)
    for t, tool in enumerate(L["tools"]):
        c.fill(tool["section"], tinted(hex_rgb(fmap[t]["hex"])))
    for t, tool in enumerate(L["tools"]):
        c.fill(tool["printed"], hex_rgb(fmap[t]["hex"]))
    for tool in L["tools"]:
        c.outline(tool["section"], BLACK, 1)
    c.outline(L["silhouette"], BLACK, 2)
    c.dots(L["sil_gap_points"], BLUE, 2.5)
    for tool in L["tools"]:
        c.dots(tool["gap_points"], MAGENTA, 1.2)
    c.crosses([(x, y) for x, y, _ in L["splits"]], CYAN, 4)
    if labels:
        for t, tool in enumerate(L["tools"]):
            m = tool["metrics"]
            if m["max_gap_mm"] is not None and m["max_gap_mm"] > L["allowance"]:
                c.rings([m["at_bed_mm"]], BLACK, 9, 2)
                c.label(*m["at_bed_mm"], f"T{t} {m['max_gap_mm']:.2f} mm")
    c.ticks()
    return c.img


def legend(width: int, lines: list[str], fmap: list[dict]) -> Image.Image:
    f = font(14)
    width = max(width, LEGEND_MIN_PX)
    lines = [w for text in lines for w in textwrap.wrap(text, width // 8,
                                                         subsequent_indent="    ")]
    rows = len(fmap) + 4 + len(lines)
    img = Image.new("RGB", (width, 22 * rows + 10), WHITE)
    d = ImageDraw.Draw(img)
    y = 5
    for t, fm in enumerate(fmap):
        d.rectangle((8, y + 2, 24, y + 16), fill=hex_rgb(fm["hex"]), outline=BLACK)
        d.rectangle((28, y + 2, 44, y + 16), fill=tinted(hex_rgb(fm["hex"])), outline=BLACK)
        d.text((52, y), f"filament {fm['filament']} = T{t}  {fm['hex']}  "
               f"{NAMES.get(fm['hex'], '?')}  ({fm['role']})", fill=BLACK, font=f)
        y += 22
    d.text((8, y), "Left swatch: printed beads (the bead model the checks use). Right swatch: "
           "body section where no bead lies (unprinted).", fill=BLACK, font=f)
    y += 22
    d.ellipse((10, y + 5, 16, y + 11), fill=MAGENTA)
    d.text((24, y), "per-color F3.edge_coverage: body-edge samples farther than the "
           "allowance from that tool's beads (black ring: each tool's largest)",
           fill=BLACK, font=f)
    y += 22
    d.ellipse((8, y + 3, 18, y + 13), fill=BLUE)
    d.text((24, y), "silhouette F3.edge_coverage: model-outline samples farther than the "
           "allowance from any bead", fill=BLACK, font=f)
    y += 22
    d.line((9, y + 4, 17, y + 12), fill=CYAN, width=2)
    d.line((9, y + 12, 17, y + 4), fill=CYAN, width=2)
    d.text((24, y), f"silhouette F3.printed_connectivity: two printed parts closer than "
           f"{SPLIT_SEARCH_MM:g} mm (the union of all beads splits here)", fill=BLACK, font=f)
    y += 22
    for text in lines:
        d.text((8, y), text, fill=BLACK, font=f)
        y += 22
    return img


def zooms(L: dict, fmap: list[dict]) -> Image.Image | None:
    """Close-ups around each tool's largest edge gap over the allowance on this layer."""
    tiles = []
    for t, tool in enumerate(L["tools"]):
        m = tool["metrics"]
        if m["max_gap_mm"] is None or m["max_gap_mm"] <= L["allowance"]:
            continue
        x, y = m["at_bed_mm"]
        h = ZOOM_HALF_MM
        img = render(L, fmap, (x - h, y - h, x + h, y + h), labels=False,
                     ppm=ZOOM_PX_PER_MM, margin=0, tick=2)
        d = ImageDraw.Draw(img)
        c = img.width / 2
        d.ellipse((c - 12, c - 12, c + 12, c + 12), outline=BLACK, width=3)
        cap = Image.new("RGB", (img.width, 24), WHITE)
        ImageDraw.Draw(cap).text((4, 4), f"T{t} {m['max_gap_mm']:.2f} mm at "
                                 f"({x:.1f}, {y:.1f})", fill=BLACK,
                                 font=font(14))
        tiles.append(stack(cap, img))
    if not tiles:
        return None
    out = Image.new("RGB", (sum(i.width for i in tiles) + 10 * (len(tiles) - 1),
                            max(i.height for i in tiles)), WHITE)
    u = 0
    for i in tiles:
        out.paste(i, (u, 0))
        u += i.width + 10
    return out


def stack(*imgs) -> Image.Image:
    w = max(i.width for i in imgs)
    out = Image.new("RGB", (w, sum(i.height for i in imgs)), WHITE)
    y = 0
    for i in imgs:
        out.paste(i, (0, y))
        y += i.height
    return out


def layer_lines(plan, face, L) -> list[str]:
    m = L["sil_metrics"]
    split = [d for _, _, d in L["splits"]]
    out = [f"{plan}, face {face}, layer {L['n']} (z {L['z']:g} mm), print order "
           + " > ".join(f"T{t}" for t in L["order"]) + f"; allowance {L['allowance']:g} mm. "
           "Bed coordinates seen from above (mm).",
           f"Silhouette: {m['parts_printed']} printed part(s) for the model's "
           f"{m['parts_model']}; largest outline gap {m['max_gap_mm']:.3f} mm; splits drawn "
           f"{len(split)}" + (f", gap widths {min(split):.3f}-{max(split):.3f} mm"
                              if split else "") + "."]
    per = []
    for t, tool in enumerate(L["tools"]):
        tm = tool["metrics"]
        if tm["max_gap_mm"] is not None:
            per.append(f"T{t} {tm['max_gap_mm']:.3f} mm, parts {tm['parts_printed']}/"
                       f"{tm['parts_model']}, holes {tm['holes_printed']}/{tm['holes_model']}")
    out.append("Per tool (largest edge gap; printed/model parts and holes): " + "; ".join(per))
    return out


# --- The summary -------------------------------------------------------------------------------


def r3(v):
    return "-" if v is None else f"{v:.3f}"


def summary_lines(plan, record, faces) -> list[str]:
    fmap = record["filament_map"]
    out = [f"== {plan}", "   filaments: " + ", ".join(
        f"{f['filament']}=T{t} {f['hex']} {NAMES.get(f['hex'], '?')} ({f['role']})"
        for t, f in enumerate(fmap))]
    for t, role in ROLES.get(plan, {}).items():
        out.append(f"   T{t} is {role} (by eye from top.png)")
    for face in ("up", "down"):
        f = record["faces"][face]
        by = {c["id"]: c for c in f["checks"]}
        s = f["summary"]
        cc = by["F6.color_changes"]["measured"]
        fil = by["F6.color_filament"]["measured"]
        out.append(f"   -- face {face}: {f['verdict']} (G-code {faces[face]['gcode']})")
        out.append(f"      changes {s['changes']} (true minimum from the start load "
                   f"{cc['info_minimum_from_start_load']}, start load T{cc['start_load']}); "
                   f"flush {s['flush_mm3']:.1f} mm3; prime tower {s['prime_tower_mm3']:.1f} "
                   f"mm3; time {s['time_s']} s ({s['time_s'] / 60:.1f} min)")
        out.append("      filament per tool (header g / mm): " + "; ".join(
            f"T{t} {g} g / {mm} mm" for t, (g, mm) in enumerate(zip(
                fil["header_filament_used_g"], fil["header_filament_used_mm"], strict=True))))
        out.append("      required F3 (status, value, allowance):")
        for who, suffix in [("silhouette", "")] + [(f"T{t}", f".T{t}")
                                                   for t in range(len(fmap))]:
            conn = by["F3.printed_connectivity" + suffix]
            cov = by["F3.edge_coverage" + suffix]
            over = by["F3.edge_overprint" + suffix]
            cm = conn["measured"] or {}
            cv = cov["measured"] or {}
            ov = over["measured"] or {}
            ctext = ("PASS" if conn["status"] == "PASS" else
                     f"{conn['status']} {cm.get('layers_mismatched')} of {cm.get('layers')} "
                     f"layers (first z {cm.get('first_z')}: parts {cm.get('parts_printed')}/"
                     f"{cm.get('parts_model')}, holes {cm.get('holes_printed')}/"
                     f"{cm.get('holes_model')})")
            out.append(
                f"        {who:10s} connectivity {ctext}; coverage {cov['status']} "
                f"{r3(cv.get('max_gap_mm'))} mm vs {cv.get('allowance_mm')} at z "
                f"{cv.get('worst_z')} ({cv.get('layers_over')} layer(s) over); overprint "
                f"{over['status']} {r3(ov.get('max_over_mm'))} mm vs {ov.get('allowance_mm')}")
        out.append("      largest per-tool edge gaps (over the allowance), on the color layers:")
        layers = [L for L in faces[face]["layers"] if len(L["bodies"]) > 1]
        for t in range(len(fmap)):
            worst = max(layers, key=lambda L: L["tools"][t]["metrics"]["max_gap_mm"] or 0)
            m = worst["tools"][t]["metrics"]
            if m["max_gap_mm"] is None or m["max_gap_mm"] <= worst["allowance"]:
                continue
            d = describe(worst, t)
            role = ROLES.get(plan, {}).get(t, "not identified")
            out.append(
                f"        T{t} layer {worst['n']}: {d['gap']:.3f} mm at bed "
                f"({d['at'][0]:.2f}, {d['at'][1]:.2f}); on {d['edge']}; the body there is "
                + ("narrower than one bead" if d["thin"] else "at least one bead wide")
                + f" (bead {d['bead']:.2f} mm); part of the image: {role}")
            out.append(
                f"          unprinted body area this layer {d['uncovered_total']:.2f} of "
                f"{d['body_area']:.2f} mm2; largest unprinted patches: " + "; ".join(
                    f"{p['area']:.2f} mm2, widest {p['widest']:.2f} mm, at "
                    f"({p['at'][0]:.1f}, {p['at'][1]:.1f})" for p in d["patches"]))
        for L in layers:
            shares = []
            for t, tool in enumerate(L["tools"]):
                body = tool["section"]
                if body.is_empty:
                    continue
                gone = body.difference(tool["printed"]).area
                shares.append(f"T{t} {gone:.1f} of {body.area:.1f} mm2 "
                              f"({100 * gone / body.area:.0f}%), beads "
                              f"{tool['length_mm']:.0f} mm long")
            out.append(f"        layer {L['n']} body area no bead of its own tool covers "
                       "(bead model: the beads are not squashed, so some is normal), and the "
                       "tool's total bead length: "
                       + "; ".join(shares))
        for L in layers:
            sp = [d for _, _, d in L["splits"]]
            sm = L["sil_metrics"]
            out.append(f"        silhouette layer {L['n']}: printed parts {sm['parts_printed']}"
                       f" for {sm['parts_model']}; {len(sp)} split(s) under "
                       f"{SPLIT_SEARCH_MM:g} mm" + (f", widths {min(sp):.3f}-{max(sp):.3f} mm"
                                                     if sp else "")
                       + f"; largest outline gap {sm['max_gap_mm']:.3f} mm at bed "
                       f"({sm['at_bed_mm'][0]:.2f}, {sm['at_bed_mm'][1]:.2f})")
    return out


def main() -> None:
    ctx = prepare(ORCA, None, False, PRUSA)
    text = [("Task 7 review: the owner plans' color layers (tdmg slice records of Task 6, "
            "re-measured with the gate's functions; every per-layer value equals slice.json)."),
            ("Images: artifacts/color-review/<plan>/ (git-ignored). Script: "
            "owner_review_task7.py. Bed coordinates in mm, seen from above."),
            ("Allowance: 0.275 mm on layer 1, 0.2 mm above (acceptance.dimension.tolerance "
            "plus elefant_foot_compensation on layer 1).")]
    for plan in PLANS:
        record = json.loads((REPO / "artifacts/slice-runs" / f"color-{plan}" /
                             "slice.json").read_text("utf-8"))
        rec_in, _, files_in = read_colored(REPO / "artifacts/colored-runs" / plan)
        shells = ams_shells(rec_in, files_in)
        setup = ctx.setup(allowed_counts(shells, ctx.process))
        bodies = {"up": shells, "down": turn_over(shells)}
        fmap = record["filament_map"]
        dest = OUT / plan
        dest.mkdir(parents=True, exist_ok=True)
        faces = {}
        for face in ("up", "down"):
            faces[face] = measure_face(plan, face, bodies[face], setup, record)
            print(f"{plan} face {face}: measured, equal to slice.json")
        allsil = shapely.union_all([L["silhouette"] for f in faces.values()
                                    for L in f["layers"]])
        bounds = allsil.bounds
        for face in ("up", "down"):
            for L in faces[face]["layers"]:
                if len(L["bodies"]) < 2:
                    continue
                img = render(L, fmap, bounds)
                parts = [img, legend(img.width, layer_lines(plan, face, L), fmap)]
                z = zooms(L, fmap)
                if z is not None:
                    parts.append(z)
                out = stack(*parts)
                out.save(dest / f"face-{face}-layer-{L['n']:02d}.png")
        # Overview: the visible color layer of each face, face down mirrored left-right so
        # both read as the finished piece seen from its colored face.
        up = faces["up"]["layers"][-1]
        down = faces["down"]["layers"][0]
        a = render(up, fmap, bounds, labels=False)
        b = render(down, fmap, bounds, mirror=True, labels=False)
        title = Image.new("RGB", (a.width + b.width + 20, 30), WHITE)
        dt = ImageDraw.Draw(title)
        dt.text((8, 6), f"face up: layer {up['n']} (top)", fill=BLACK, font=font(16))
        dt.text((a.width + 28, 6), f"face down: layer {down['n']} (on the bed), mirrored "
                "left-right to read as seen from the colored face", fill=BLACK, font=font(16))
        pair = Image.new("RGB", (a.width + b.width + 20, max(a.height, b.height)), WHITE)
        pair.paste(a, (0, 0))
        pair.paste(b, (a.width + 20, 0))
        nums = []
        for face in ("up", "down"):
            f = record["faces"][face]
            s = f["summary"]
            bad = [c["id"] for c in f["checks"] if c["id"].startswith("F3.")
                   and c["id"] in f["required_checks"] and c["status"] != "PASS"]
            nums.append(f"face {face}: changes {s['changes']}, flush {s['flush_mm3']:.0f} mm3, "
                        f"prime tower {s['prime_tower_mm3']:.0f} mm3, time {s['time_s']} s "
                        f"({s['time_s'] / 60:.1f} min); {f['verdict']}")
            nums.append(f"   required F3 not PASS: {', '.join(bad) if bad else 'none'}")
        stack(title, pair, legend(pair.width, nums, fmap)).save(dest / "overview.png")
        text += [""] + summary_lines(plan, record, faces)
    text += ["", *READING.strip("\n").split("\n")]
    (HERE / "owner-review.txt").write_text("\n".join(text) + "\n", encoding="utf-8")
    print("\n".join(text))


if __name__ == "__main__":
    main()

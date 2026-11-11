"""Measure what survives `outlines: drop`, the holes and inlets of the mask, and the stroke
specks of `outlines: keep` (plan Task 7e-a).

Usage: uv run python research/verification/2026-11-11-color-palette/measure_wide_holes.py \
    OUT_DIR SELECTION_DIR [SELECTION_DIR ...]
OUT_DIR must not exist or be an empty directory. It receives wide-holes.txt (also printed)
and, per selection, four preview PNGs (see "Previews" below).

Each SELECTION_DIR is a tdmg select folder, read with tdmg.selection.read_selection(dir,
cutout=True). Settings: the defaults of `tdmg colors` (tdmg.color_config.
resolve_color_config with no flag and no file: extract 6, outline_color auto, outlines
drop, no merge), printer bambu-a1, width WIDTH_MM. The scale is tdmg.colors.mask_mm_per_px
and the limits tdmg.color.printable_limits_px, as tdmg colors uses them. The pipeline is
tdmg.color_plan.plan_colors, unchanged. No library code is changed.

Terms (on the image's pixel grid; mm = px x mm_per_px, mm2 = px x mm_per_px^2):
- family, core: plan.outline.family and .core. A member's wide pixels are its pixels that
  its own opening keeps (tdmg.color.open_mask(labels == f, limits.min_width_px)), as
  handle_outlines computes them; its thin pixels are the rest.
- W components ("wide remnants"): the 4-connected components of the union of all members'
  wide pixels. Under drop all of them take the core's color. Largest first.
- N components ("non-core wide"): the 4-connected components of the union of the NON-core
  members' wide pixels only. Each N lies inside one W; "in W" names it.
- outside: a pixel not in the mask, or the one-pixel frame beyond the image. exterior: the
  outside pixels 4-connected through outside pixels to the frame. A hole: an outside
  component not connected to the frame.
- ext / hole (y/n): some pixel of the component is 4-adjacent to an exterior / hole pixel.
- boundary: the 4-adjacent pixel pairs (p in the component, q not). Shares by q's label
  after the drop (plan.outlined: before merges and cleanup) as hex, "outside" for outside
  pixels. P = the pair count (the perimeter in pixel edges).
- compact = 4 pi A / P^2 (A = area in px). On the pixel grid a large disc and a square both
  tend to pi/4 = 0.785; a 1 x n line tends to 0.
- inscr: 2 x the largest scipy distance_transform_edt value on the component padded by one
  non-component pixel (distance between pixel centres to the nearest non-component pixel).
  A straight strip n px wide reads about n + 1 (1 px reads 2): a rough width of the widest
  disc, about 1 px above the true one.
- members: the component's pixel count per extracted color (hex).
- centroid (row, col) and bbox (rows r0-r1, cols c0-c1), inclusive, in image pixels.
- final (W): the share of the component's pixels whose final label (plan.cleaned, after
  cleanup) is the core's final color; "-" if the core has no final color.
- nearest (N): rule (b): each pixel takes the color of the nearest pixel of a non-family
  color in the extracted labels (tdmg.color.d2_nearest per color, exact squared distance,
  ties to the lowest index, as handle_outlines does for thin pixels); shares by hex.

Holes: the outside components not connected to the frame, with 4- and with 8-connectivity
of the outside. For each 4-connected hole: area, centroid, bbox, and boundary colors after
the drop and after cleanup.

Inlets (pockets): closed(w) = not open_mask(not mask, w) on the image padded by PAD_MM of
outside on every side (so the frame side stays open); E(w) = the outside pixels inside
scipy binary_fill_holes(closed(w)) that are not holes: what a closing of the mask at width
w, then a hole fill, would add. The pockets are the 4-connected components of E(W_MAX) with
at least limits.min_area_px pixels (flat.island.min_square_side, the cleanup's island
area); for each, the area of E(w) inside it at each w in WIDTHS_MM. A pocket behind a narrow
inlet jumps to nearly its full area at the inlet's width; an open wedge grows gradually.
NAMED_POINTS (my by-eye picks of the places the owner named) get the same curve: the
largest E(w) component within NAMED_RADIUS_PX of the point.

Strokes (keep): S = the union of the members' thin pixels (what stroke_band redraws). Its
8-connected components (a 1 px diagonal line is one stroke), largest first: area px and
mm2, extent = max(bbox height, width) px and mm, d_ext = the smallest distance between
pixel centres from the component to an exterior pixel, d_larger = the smallest distance to
a pixel of a strictly larger S component ("-" for none), centroid. Also S's stroke width:
2 x EDT (as inscr) at the pixels of tdmg.color_outline.stroke_ridge(S), median and p90.

Simulation of the proposed drop rules (addendum 7e-a; hypotheses under test, not rules):
thin family pixels and non-core wide pixels take the nearest non-family color; a W
component's core pixels keep the core color only if the component does not touch the
exterior and its inscr >= KEEP_INSCRIBED_MM, else they take the nearest non-family color;
then tdmg.color.clean_regions. Reported: the final palette and the core's final pixels and
components.

Previews (in OUT_DIR; derived from the owner's images, so OUT_DIR belongs under the
git-ignored artifacts/), each the subject's bounding box enlarged PREVIEW_SCALE x:
- <name>-wide.png: the colors after the drop; W outlined in cyan, labelled "Wn" (with
  "/Nm" when an N component is the same pixels); N components that differ from their W
  outlined in magenta.
- <name>-holes.png: the mask light grey, holes blue, E(W_MAX) orange, pockets labelled.
- <name>-strokes.png: S black on the mask light grey; components below the island area
  circled red and labelled.
- <name>-rules.png: the simulation's final colors.
"""
import hashlib
import math
import pathlib
import platform
import subprocess
import sys

import numpy as np
import scipy
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.spatial import cKDTree

from tdmg.color import (
    OUTSIDE,
    clean_regions,
    d2_nearest,
    from_labels,
    open_mask,
    printable_limits_px,
)
from tdmg.color_config import resolve_color_config
from tdmg.color_outline import stroke_ridge
from tdmg.color_plan import plan_colors
from tdmg.colors import mask_mm_per_px
from tdmg.profiles import load_printer
from tdmg.rules import load_rules
from tdmg.selection import read_selection

WIDTH_MM = 60.0          # the owner's flat models (tdmg colors --width-mm 60)
PRINTER = "bambu-a1"     # tdmg colors' default printer
# Closing widths for the inlet sweep (mm): a measurement grid, not a threshold. 0.4 is
# flat.sliver.opening_width; the grid goes to 2.0 mm to see where each place closes.
WIDTHS_MM = (0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.25, 1.5, 2.0)
W_MAX = WIDTHS_MM[-1]
PAD_MM = 3.0             # outside margin for the closing: above W_MAX, so it never binds
# My by-eye picks (row, col) of the places the owner named, per selection folder name.
NAMED_POINTS = {
    "roadie-tol30": (
        ("forehead-beak wedge (next to the eye)", (236, 507)),
        ("right foot: cuff-shoe wedge", (526, 627)),
        ("left foot: inside the cuff", (560, 330)),
    ),
}
NAMED_RADIUS_PX = 12     # search radius around a named point (a measurement window)
# The proposal under test in the simulation (the midpoint found in the first run of this
# script, recorded in the README addendum as a hypothesis from one image).
KEEP_INSCRIBED_MM = 1.25
PREVIEW_SCALE = 2
FOUR = ndimage.generate_binary_structure(2, 1)
EIGHT = ndimage.generate_binary_structure(2, 2)
# Preview colors only.
GREY = (215, 215, 215)
DARK = (90, 90, 90)
CYAN = (0, 200, 255)
MAGENTA = (255, 0, 255)
BLUE = (40, 90, 255)
ORANGE = (255, 140, 0)
RED = (230, 0, 0)


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def outside_parts(mask):
    """(exterior, (holes4 labels, count), (holes8 labels, count))."""
    bg = np.pad(~mask, 1, constant_values=True)
    out = []
    for st in (FOUR, EIGHT):
        lab, _ = ndimage.label(bg, structure=st)
        hole = (lab != lab[0, 0]) & bg
        hl, hn = ndimage.label(hole, structure=st)
        out.append((hl[1:-1, 1:-1], hn))
    lab4, _ = ndimage.label(bg, structure=FOUR)
    exterior = (lab4 == lab4[0, 0])[1:-1, 1:-1]
    return exterior, out[0], out[1]


def boundary_shares(comp, labels, hexes):
    """({name: share}, P): the 4-adjacent pairs (p in comp, q not), q named by its label's
    hex or 'outside' (OUTSIDE or beyond the image), and their count P."""
    lab = np.pad(labels, 1, constant_values=OUTSIDE)
    c = np.pad(comp, 1, constant_values=False)
    counts, total = {}, 0
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        # The pixels q not in comp whose neighbour q - (dy, dx) is in comp. The roll wraps
        # only the padding, which is never in comp.
        sel = np.roll(c, (dy, dx), axis=(0, 1)) & ~c
        qlab = lab[sel]
        total += int(sel.sum())
        for v in np.unique(qlab):
            key = "outside" if v == OUTSIDE else hexes[v]
            counts[key] = counts.get(key, 0) + int((qlab == v).sum())
    return {k: v / total for k, v in sorted(counts.items(), key=lambda kv: -kv[1])}, total


def fmt_shares(d, top=4):
    s = ", ".join(f"{k} {v:.0%}" for k, v in list(d.items())[:top])
    return s + (", ..." if len(d) > top else "")


def inscribed_px(comp):
    return 2.0 * float(ndimage.distance_transform_edt(np.pad(comp, 1)).max())


def adjacent(comp, region):
    grown = ndimage.binary_dilation(comp, structure=FOUR)
    return bool((grown & region & ~comp).any())


def nearest_nonfamily(labels, family, ty, tx):
    """The nearest non-family label of each (ty, tx): exact d2, ties to the lowest index."""
    best = np.full(len(ty), np.iinfo(np.int64).max, np.int64)
    best_c = np.full(len(ty), OUTSIDE, np.int64)
    for c in range(int(labels.max()) + 1):
        if c in family or not (labels == c).any():
            continue
        d2 = d2_nearest(labels == c, ty, tx)
        closer = d2 < best
        best = np.where(closer, d2, best)
        best_c = np.where(closer, c, best_c)
    return best_c


def components(region, structure):
    """(label array, label ids largest first; ties by label id)."""
    lab, n = ndimage.label(region, structure=structure)
    if n == 0:
        return lab, []
    sizes = np.bincount(lab.ravel(), minlength=n + 1)[1:]
    return lab, [int(i) + 1 for i in np.argsort(-sizes, kind="stable")]


def describe(comp):
    ys, xs = np.nonzero(comp)
    return {"area": len(ys), "cy": float(ys.mean()), "cx": float(xs.mean()),
            "bbox": (int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max()))}


def fmt_bbox(b):
    return f"{b[0]:3d}-{b[1]:3d},{b[2]:3d}-{b[3]:3d}"


def closing_enclosed(mask, w_px, pad):
    """E(w) before removing holes: the outside pixels inside the hole-filled closing."""
    bg = np.pad(~mask, pad, constant_values=True)
    closed = ~open_mask(bg, w_px)
    filled = ndimage.binary_fill_holes(closed, structure=FOUR)
    return (filled & bg)[pad:-pad, pad:-pad]


def crop_box(mask, margin=10):
    rows, cols = np.flatnonzero(mask.any(1)), np.flatnonzero(mask.any(0))
    h, w = mask.shape
    return (max(rows[0] - margin, 0), min(rows[-1] + margin + 1, h),
            max(cols[0] - margin, 0), min(cols[-1] + margin + 1, w))


def to_image(rgb, box):
    r0, r1, c0, c1 = box
    im = Image.fromarray(rgb[r0:r1, c0:c1])
    return im.resize((im.width * PREVIEW_SCALE, im.height * PREVIEW_SCALE), Image.NEAREST)


def edge_of(comp):
    return comp & ~ndimage.binary_erosion(comp, structure=FOUR, border_value=0)


def label_at(draw, box, cy, cx, text, fill):
    r0, _, c0, _ = box
    x, y = (cx - c0) * PREVIEW_SCALE + 8, (cy - r0) * PREVIEW_SCALE - 6
    draw.rectangle((x - 1, y - 1, x + 6 * len(text) + 1, y + 11), fill=(255, 255, 255))
    draw.text((x, y), text, fill=fill)


def paint(labels, rgb_palette, mask):
    rgb = np.full(mask.shape + (3,), DARK, np.uint8)
    rgb[mask] = rgb_palette[labels[mask]]
    return rgb


def main():
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    out = pathlib.Path(sys.argv[1]).resolve()
    sels = [pathlib.Path(a).resolve() for a in sys.argv[2:]]
    if out.exists() and not out.is_dir():
        sys.exit(f"refusing: {out} exists and is not a directory")
    if out.exists() and any(out.iterdir()):
        sys.exit(f"refusing: {out} is not empty")
    out.mkdir(parents=True, exist_ok=True)

    rules = load_rules()
    printer = load_printer(PRINTER)
    settings = resolve_color_config({}, None, rules, printer).settings
    try:
        commit = subprocess.run(["git", "describe", "--always", "--dirty"], capture_output=True,
                                text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    lines = [(f"measure_wide_holes.py sha256 {sha(__file__)} at git {commit}; python "
              f"{platform.python_version()}, numpy {np.__version__}, scipy {scipy.__version__}"),
             (f"width {WIDTH_MM} mm, printer {PRINTER}; settings: extract "
              f"{settings['extract']}, outline_color {settings['outline_color']}, outlines "
              f"{settings['outlines']}, merge {list(settings['merge'])}"),
             f"simulation: KEEP_INSCRIBED_MM {KEEP_INSCRIBED_MM}"]
    for sel_dir in sels:
        lines += measure(sel_dir, out, rules, printer, settings)
    text = "\n".join(lines) + "\n"
    (out / "wide-holes.txt").write_text(text, encoding="utf-8")
    print(text, end="")


def measure(sel_dir, out, rules, printer, settings):
    name = sel_dir.name
    sel = read_selection(sel_dir, cutout=True)
    mask = np.asarray(sel.mask, bool)
    mm = mask_mm_per_px(mask, WIDTH_MM)
    mm2 = mm * mm
    limits = printable_limits_px(mm, rules, printer)
    plan = plan_colors(sel.cutout_rgb, mask, settings, limits, rules)
    q, fam, core = plan.extracted, plan.outline.family, plan.outline.core
    after = plan.outlined
    box = crop_box(mask)
    L = ["", (f"== {name}: selection_id {sel.record['selection_id'][:16]}, cutout pixels "
              f"sha256 {sel.cutout_pixels_sha256[:16]}"),
         (f"   {int(mask.sum())} masked px; 1 px = {mm:.6f} mm, 1 px2 = {mm2:.6f} mm2; "
          f"opening {limits.opening_width_mm} mm = {limits.min_width_px:.3f} px; island "
          f"{limits.island_area_mm2:.4f} mm2 = {limits.min_area_px:.2f} px"),
         "   extracted: " + ", ".join(f"{i} {h} {q.shares[i]:.1%}" for i, h in enumerate(q.hex)),
         (f"   family {list(fam)} ({', '.join(q.hex[i] for i in fam)}), core {core} "
          f"({None if core is None else q.hex[core]}); final colors {list(plan.cleaned.hex)}")]
    exterior, (holes4, n4), (_holes8, n8) = outside_parts(mask)
    hole_any = holes4 > 0

    wide = np.zeros(mask.shape, bool)
    wide_nc = np.zeros(mask.shape, bool)
    thin = np.zeros(mask.shape, bool)
    for f in fam:
        m = q.labels == f
        k = open_mask(m, limits.min_width_px)
        wide |= m & k
        thin |= m & ~k
        if f != core:
            wide_nc |= m & k
    core_final = None if core is None else plan.final_index[core]

    # --- 1. wide remnants ---------------------------------------------------------------
    L += ["", (f"   1. wide remnants under drop: {int(wide.sum())} wide family px "
               f"({int(wide_nc.sum())} non-core)")]
    lab_w, order_w = components(wide, FOUR)
    rows_w = []
    if order_w:
        L.append("    id    area px  mm2    inscr px/mm  compact ext hole  centroid  bbox r,c"
                 "            members; boundary after drop; final")
    for n, li in enumerate(order_w, 1):
        comp = lab_w == li
        d = describe(comp)
        shares, per = boundary_shares(comp, after.labels, after.hex)
        ins = inscribed_px(comp)
        compact = 4 * math.pi * d["area"] / per ** 2
        mem = {q.hex[f]: int((comp & (q.labels == f)).sum()) for f in fam}
        fin = (None if core_final is None else
               float((plan.cleaned.labels[comp] == core_final).mean()))
        te, th = adjacent(comp, exterior), adjacent(comp, hole_any)
        rows_w.append({"id": f"W{n}", "comp": comp, **d, "ins": ins, "ext": te,
                       "core_px": int((comp & (q.labels == core)).sum())})
        L.append(f"   W{n:<3d} {d['area']:6d} {d['area'] * mm2:6.3f}  {ins:5.1f}/{ins * mm:4.2f}"
                 f"   {compact:5.3f}   {'y' if te else 'n'}   {'y' if th else 'n'}  "
                 f"{d['cy']:4.0f},{d['cx']:4.0f}  {fmt_bbox(d['bbox'])}  "
                 + ", ".join(f"{h} {v}" for h, v in mem.items() if v)
                 + f"; {fmt_shares(shares)}; {'-' if fin is None else f'{fin:.0%}'}")

    lab_n, order_n = components(wide_nc, FOUR)
    rows_n = []
    if order_n:
        L.append("   N (non-core wide) components:")
        L.append("    id    area px  mm2    inscr px/mm  compact ext hole  centroid  in W   "
                 "members; nearest (rule b)")
    for n, li in enumerate(order_n, 1):
        comp = lab_n == li
        d = describe(comp)
        _, per = boundary_shares(comp, after.labels, after.hex)
        ins = inscribed_px(comp)
        compact = 4 * math.pi * d["area"] / per ** 2
        mem = {q.hex[f]: int((comp & (q.labels == f)).sum()) for f in fam if f != core}
        w_of = next(r for r in rows_w if (r["comp"] & comp).any())
        same = bool((w_of["comp"] == comp).all())
        ty, tx = np.nonzero(comp)
        nb = nearest_nonfamily(q.labels, set(fam), ty, tx)
        near = dict(sorted(((q.hex[c], float((nb == c).mean())) for c in np.unique(nb)),
                           key=lambda kv: -kv[1]))
        te, th = adjacent(comp, exterior), adjacent(comp, hole_any)
        rows_n.append({"id": f"N{n}", "comp": comp, **d, "w": w_of["id"], "same": same})
        L.append(f"   N{n:<3d} {d['area']:6d} {d['area'] * mm2:6.3f}  {ins:5.1f}/{ins * mm:4.2f}"
                 f"   {compact:5.3f}   {'y' if te else 'n'}   {'y' if th else 'n'}  "
                 f"{d['cy']:4.0f},{d['cx']:4.0f}  {w_of['id'] + ('=' if same else '>'):5s} "
                 + ", ".join(f"{h} {v}" for h, v in mem.items() if v)
                 + f"; {fmt_shares(near)}")
    if order_n:
        L.append("   (in W: '=' the same pixels as that W, '>' a part of it)")

    # --- 2. holes and inlets ------------------------------------------------------------
    L += ["", f"   2. holes: {n4} with 4-connectivity of the outside, {n8} with 8-connectivity"]
    for h in range(1, n4 + 1):
        comp = holes4 == h
        d = describe(comp)
        s1, _ = boundary_shares(comp, after.labels, after.hex)
        s2, _ = boundary_shares(comp, plan.cleaned.labels, plan.cleaned.hex)
        L.append(f"   H{h:<3d} {d['area']:6d} px {d['area'] * mm2:7.3f} mm2  centroid "
                 f"{d['cy']:.0f},{d['cx']:.0f}  bbox {fmt_bbox(d['bbox'])}  after drop: "
                 f"{fmt_shares(s1)}; after cleanup: {fmt_shares(s2)}")
    pad = math.ceil(PAD_MM / mm) + 2
    enclosed = {w: closing_enclosed(mask, w / mm, pad) & ~hole_any for w in WIDTHS_MM}
    lab_p, order_p = components(enclosed[W_MAX], FOUR)
    pockets = [lab_p == li for li in order_p if (lab_p == li).sum() >= limits.min_area_px]
    L.append(f"   inlets: pockets = 4-components of E({W_MAX} mm) with >= "
             f"{limits.min_area_px:.1f} px: {len(pockets)} ({len(order_p) - len(pockets)} "
             "smaller not listed). Area of E(w) inside each, px, at w (mm):")
    L.append("    id    centroid  " + " ".join(f"{w:>5}" for w in WIDTHS_MM)
             + "   boundary after drop")
    rows_p = []
    for n, comp in enumerate(pockets, 1):
        d = describe(comp)
        s1, _ = boundary_shares(comp, after.labels, after.hex)
        rows_p.append({"id": f"P{n}", **d})
        L.append(f"   P{n:<3d} {d['cy']:4.0f},{d['cx']:4.0f}  "
                 + " ".join(f"{int((enclosed[w] & comp).sum()):5d}" for w in WIDTHS_MM)
                 + f"   {fmt_shares(s1)}")
    for label, (r, c) in NAMED_POINTS.get(name, ()):
        where = ("mask" if mask[r, c] else "hole" if hole_any[r, c] else "exterior")
        fin = plan.cleaned.labels[r, c]
        areas = []
        for w in WIDTHS_MM:
            lab, _ = ndimage.label(enclosed[w], structure=FOUR)
            win = lab[max(r - NAMED_RADIUS_PX, 0):r + NAMED_RADIUS_PX + 1,
                      max(c - NAMED_RADIUS_PX, 0):c + NAMED_RADIUS_PX + 1]
            ids = [i for i in np.unique(win) if i]
            areas.append(max((int((lab == i).sum()) for i in ids), default=0))
        L.append(f"   named (by eye, mine) {label} at {r},{c}: the point is {where}"
                 f"{'' if fin == OUTSIDE else ', final color ' + plan.cleaned.hex[fin]}; "
                 f"largest E(w) component within {NAMED_RADIUS_PX} px, px: "
                 + " ".join(str(a) for a in areas))

    # --- 3. stroke specks (keep) -----------------------------------------------------------
    lab_s, order_s = components(thin, EIGHT)
    L += ["", (f"   3. strokes S (family thin px, {int(thin.sum())} px): {len(order_s)} "
               "8-connected components")]
    if thin.any():
        sw = 2.0 * ndimage.distance_transform_edt(np.pad(thin, 1))[1:-1, 1:-1][
            stroke_ridge(thin)]
        L.append(f"   stroke width (2 x EDT of S on tdmg.color_outline.stroke_ridge(S)): median "
                 f"{np.median(sw):.1f} px = {np.median(sw) * mm:.2f} mm, p90 "
                 f"{np.percentile(sw, 90):.1f} px = {np.percentile(sw, 90) * mm:.2f} mm")
    rows_s = []
    if order_s:
        ey, ex = np.nonzero(np.pad(exterior, 1, constant_values=True))
        ext_tree = cKDTree(np.stack([ey - 1, ex - 1], 1))
        pts_of = [np.argwhere(lab_s == li) for li in order_s]
        sizes = [len(p) for p in pts_of]
        L.append("    id    area px   mm2   extent px/mm  d_ext px/mm  d_larger px/mm  centroid")
        for n, pts in enumerate(pts_of):
            d = describe(lab_s == order_s[n])
            b = d["bbox"]
            ext = max(b[1] - b[0] + 1, b[3] - b[2] + 1)
            de = float(ext_tree.query(pts)[0].min())
            larger = [pts_of[i] for i in range(n) if sizes[i] > sizes[n]]
            dl = (float(cKDTree(np.concatenate(larger)).query(pts)[0].min())
                  if larger else None)
            rows_s.append({"id": f"S{n + 1}", **d})
            dl_s = "-" if dl is None else f"{dl:5.1f}/{dl * mm:4.2f}"
            L.append(f"   S{n + 1:<4d} {d['area']:6d} {d['area'] * mm2:6.3f}  "
                     f"{ext:4d}/{ext * mm:5.2f}  {de:5.1f}/{de * mm:4.2f}  {dl_s:>11s}  "
                     f"{d['cy']:4.0f},{d['cx']:4.0f}")

    # --- simulation of the proposed drop rules ---------------------------------------------
    labels = np.array(q.labels, np.int64)
    if fam:
        ins_min = KEEP_INSCRIBED_MM / mm
        keep_core = np.zeros(mask.shape, bool)
        for r in rows_w:
            if not r["ext"] and r["ins"] >= ins_min:
                keep_core |= r["comp"] & (q.labels == core)
        fam_px = np.isin(q.labels, fam)
        ty, tx = np.nonzero(fam_px & ~keep_core)
        labels[ty, tx] = nearest_nonfamily(q.labels, set(fam), ty, tx)
        labels[keep_core] = core
    sim = from_labels(labels, q.rgb, iterations=q.iterations, converged=q.converged,
                      n_requested=q.n_requested, n_distinct_colors=q.n_distinct_colors,
                      dropped=q.dropped)
    simc, _ = clean_regions(sim, limits)
    L += ["", (f"   simulation (thin and non-core wide -> nearest; core W kept iff not ext "
               f"and inscr >= {KEEP_INSCRIBED_MM} mm = {KEEP_INSCRIBED_MM / mm:.2f} px; then "
               f"clean_regions): final {list(simc.hex)}")]
    if core is not None and q.hex[core] in simc.hex:
        ci = simc.hex.index(q.hex[core])
        cl, cn = ndimage.label(simc.labels == ci, structure=FOUR)
        parts = [describe(cl == i) for i in range(1, cn + 1)]
        L.append(f"   core {q.hex[core]} final: {int((simc.labels == ci).sum())} px in {cn} "
                 "component(s): " + "; ".join(f"{p['area']} px at {p['cy']:.0f},{p['cx']:.0f}"
                                               for p in parts))
    elif core is not None:
        L.append(f"   core {q.hex[core]}: no final pixel")

    # --- previews ---------------------------------------------------------------------------
    rgb = paint(after.labels, after.rgb, mask)
    for r in rows_w:
        rgb[edge_of(r["comp"])] = CYAN
    for r in rows_n:
        if not r["same"]:
            rgb[edge_of(r["comp"])] = MAGENTA
    im = to_image(rgb, box)
    dr = ImageDraw.Draw(im)
    same_of = {r["w"]: r["id"] for r in rows_n if r["same"]}
    for r in rows_w:
        text = r["id"] + (f"/{same_of[r['id']]}" if r["id"] in same_of else "")
        label_at(dr, box, r["cy"], r["cx"], text, (0, 70, 140))
    for r in rows_n:
        if not r["same"]:
            label_at(dr, box, r["cy"] + 8, r["cx"], r["id"], (150, 0, 150))
    im.save(out / f"{name}-wide.png")

    rgb = np.full(mask.shape + (3,), (255, 255, 255), np.uint8)
    rgb[mask] = GREY
    rgb[enclosed[W_MAX]] = ORANGE
    rgb[hole_any] = BLUE
    im = to_image(rgb, box)
    dr = ImageDraw.Draw(im)
    for r in rows_p:
        label_at(dr, box, r["cy"], r["cx"], r["id"], (120, 60, 0))
    for label, (r, c) in NAMED_POINTS.get(name, ()):
        x, y = (c - box[2]) * PREVIEW_SCALE, (r - box[0]) * PREVIEW_SCALE
        dr.ellipse((x - 6, y - 6, x + 6, y + 6), outline=RED, width=2)
    im.save(out / f"{name}-holes.png")

    rgb = np.full(mask.shape + (3,), (255, 255, 255), np.uint8)
    rgb[mask] = GREY
    rgb[thin] = (0, 0, 0)
    im = to_image(rgb, box)
    dr = ImageDraw.Draw(im)
    for r in rows_s:
        if r["area"] < limits.min_area_px:
            x, y = (r["cx"] - box[2]) * PREVIEW_SCALE, (r["cy"] - box[0]) * PREVIEW_SCALE
            dr.ellipse((x - 12, y - 12, x + 12, y + 12), outline=RED, width=2)
            label_at(dr, box, r["cy"], r["cx"] + 5, r["id"], RED)
    im.save(out / f"{name}-strokes.png")

    to_image(paint(simc.labels, simc.rgb, mask), box).save(out / f"{name}-rules.png")
    return L


if __name__ == "__main__":
    main()

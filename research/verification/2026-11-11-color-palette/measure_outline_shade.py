"""Measure outline and shade indicators of the extracted colors (plan Task 7a).

Usage: uv run python research/verification/2026-11-11-color-palette/measure_outline_shade.py \
    OUT_DIR SELECTION_DIR [SELECTION_DIR ...]
OUT_DIR must not exist or be an empty directory. It receives outline-shade.txt (also
printed) and, per selection and N, a preview PNG: the cutout, the quantized subject, then
one panel per extracted color (that color's pixels in their color, the rest of the
subject light grey, the outside dark grey), each panel headed by its palette index and hex.

Each SELECTION_DIR is a tdmg select folder, read and verified with
tdmg.selection.read_selection(dir, cutout=True). The colors are tdmg.color.quantize at
N = 4, 5, 6, 7, unchanged, before any cleanup. The scale is tdmg.colors.mask_mm_per_px at
WIDTH_MM, and the opening width is tdmg.color.printable_limits_px (rules from
tdmg.rules.load_rules, printer bambu-a1), as tdmg colors uses them.

Per color (palette index i, in quantize's order):
- hex, L*, C* = sqrt(a*^2 + b*^2), h = atan2(b*, a*) in degrees [0, 360), area share;
- thin: share of its pixels NOT kept by tdmg.color.open_mask(color, min_width_px);
- border: share of its pixels with a 4-neighbour of another color, OUTSIDE, or beyond the
  image edge;
- band width: 2 x the Euclidean distance transform (scipy distance_transform_edt) of the
  color's mask padded by one non-color pixel, over its pixels: median and 90th percentile,
  in px and mm. A pixel next to a non-color pixel has distance 1, so a 1 px line reads 2 px:
  this is a rough stroke width, not an exact one;
- pieces: 4-connected components of the color.
Per pair (i, j): Delta E*76 of the palette colors, dL* = L*_j - L*_i, dh = the shortest
hue-angle difference in degrees (unstable when either C* is low, so both C* are shown),
and the shared boundary: the number of 4-adjacent pixel pairs with one pixel of each color.
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

from tdmg.color import OUTSIDE, open_mask, printable_limits_px, quantize
from tdmg.colors import mask_mm_per_px
from tdmg.profiles import load_printer
from tdmg.rules import load_rules
from tdmg.selection import read_selection

WIDTH_MM = 60.0  # the owner's flat models (tdmg flat/colors --width-mm 60)
NS = (4, 5, 6, 7)  # plan Task 7a asks for 4-6; 7 added to see if Oddie's lines split off
PRINTER = "bambu-a1"
# Preview colors only (no measurement uses them).
OTHER_GREY = (205, 205, 205)
OUTSIDE_GREY = (90, 90, 90)
HEAD_PX = 16
PER_ROW = 4


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def hue_deg(lab):
    return math.degrees(math.atan2(lab[2], lab[1])) % 360.0


def chroma(lab):
    return math.hypot(lab[1], lab[2])


def neighbour_pairs(labels):
    """Labels of each 4-adjacent pixel pair, with OUTSIDE beyond the image edge."""
    p = np.pad(labels, 1, constant_values=OUTSIDE)
    return [(p[:, :-1], p[:, 1:]), (p[:-1, :], p[1:, :])]


def per_color(q, limits):
    labels = q.labels
    padded = np.pad(labels, 1, constant_values=OUTSIDE)
    rows = []
    for i in range(len(q.hex)):
        m = labels == i
        n_px = int(m.sum())
        kept = open_mask(m, limits.min_width_px)
        thin = 1.0 - kept[m].sum() / n_px
        c = padded == i
        border = np.zeros_like(c)
        border[1:-1, 1:-1] = c[1:-1, 1:-1] & ~(c[:-2, 1:-1] & c[2:, 1:-1]
                                               & c[1:-1, :-2] & c[1:-1, 2:])
        border_share = border[1:-1, 1:-1][m].sum() / n_px
        dist = ndimage.distance_transform_edt(c)[1:-1, 1:-1][m]
        band = 2.0 * dist
        _, pieces = ndimage.label(m, structure=ndimage.generate_binary_structure(2, 1))
        lab = q.lab[i]
        rows.append({"i": i, "hex": q.hex[i], "L": lab[0], "C": chroma(lab),
                     "h": hue_deg(lab), "share": q.shares[i], "thin": thin,
                     "border": border_share, "band_med": float(np.median(band)),
                     "band_p90": float(np.percentile(band, 90)), "pieces": int(pieces),
                     "px": n_px})
    return rows


def pair_table(q):
    k = len(q.hex)
    shared = np.zeros((k, k), np.int64)
    for a, b in neighbour_pairs(q.labels):
        diff = (a != b) & (a >= 0) & (b >= 0)
        np.add.at(shared, (a[diff], b[diff]), 1)
    shared = shared + shared.T
    out = []
    for i in range(k):
        for j in range(i + 1, k):
            li, lj = q.lab[i], q.lab[j]
            dh = abs(hue_deg(li) - hue_deg(lj)) % 360.0
            dh = min(dh, 360.0 - dh)
            out.append({"i": i, "j": j, "dE": float(np.linalg.norm(li - lj)),
                        "dL": lj[0] - li[0], "dh": dh, "Ci": chroma(li), "Cj": chroma(lj),
                        "shared": int(shared[i, j])})
    return out


def preview(cut_rgb, mask, q):
    h, w = mask.shape
    panels = []
    full = np.full((h, w, 3), OUTSIDE_GREY, np.uint8)
    full[mask] = cut_rgb[mask]
    panels.append(("cutout", full))
    painted = np.full((h, w, 3), OUTSIDE_GREY, np.uint8)
    painted[mask] = q.rgb[q.labels[mask]]
    panels.append((f"quantized N={q.n_requested}", painted))
    for i, hx in enumerate(q.hex):
        p = np.full((h, w, 3), OUTSIDE_GREY, np.uint8)
        p[mask] = OTHER_GREY
        sel = q.labels == i
        p[sel] = q.rgb[i]
        panels.append((f"{i}: {hx} ({q.shares[i]:.1%})", p))
    rows = math.ceil(len(panels) / PER_ROW)
    sheet = Image.new("RGB", (PER_ROW * w, rows * (h + HEAD_PX)), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    for n, (title, arr) in enumerate(panels):
        x, y = (n % PER_ROW) * w, (n // PER_ROW) * (h + HEAD_PX)
        draw.text((x + 4, y + 2), title, fill=(0, 0, 0))
        sheet.paste(Image.fromarray(arr), (x, y + HEAD_PX))
    return sheet


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
    try:
        commit = subprocess.run(["git", "describe", "--always", "--dirty"], capture_output=True,
                                text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    lines = [(f"measure_outline_shade.py sha256 {sha(__file__)} at git {commit}; python "
             f"{platform.python_version()}, numpy {np.__version__}, scipy {scipy.__version__}"),
             f"width {WIDTH_MM} mm, printer {PRINTER}, N = {', '.join(map(str, NS))}"]
    for sel_dir in sels:
        sel = read_selection(sel_dir, cutout=True)
        mm = mask_mm_per_px(sel.mask, WIDTH_MM)
        limits = printable_limits_px(mm, rules, printer)
        lines += ["", (f"== {sel_dir.name}: selection_id {sel.record['selection_id'][:16]}, "
                  f"cutout pixels sha256 {sel.cutout_pixels_sha256[:16]}"),
                  (f"   {int(sel.mask.sum())} masked px, mm_per_px {mm:.6f}, opening width "
                  f"{limits.opening_width_mm} mm = {limits.min_width_px:.3f} px")]
        for n in NS:
            q = quantize(sel.cutout_rgb, sel.mask, n)
            lines += ["", (f"   N={n} ({len(q.hex)} colors, {q.iterations} iterations"
                      f"{'' if q.converged else ', NOT converged'})"),
                      ("    i  hex       L*     C*     h    share   thin  border  band_med px/mm"
                      "   band_p90 px/mm  pieces")]
            for r in per_color(q, limits):
                lines.append(
                    f"   {r['i']:2d}  {r['hex']}  {r['L']:5.1f}  {r['C']:5.1f}  {r['h']:5.1f}"
                    f"  {r['share']:6.1%}  {r['thin']:5.1%}  {r['border']:6.1%}"
                    f"  {r['band_med']:5.1f}/{r['band_med'] * mm:5.2f}"
                    f"   {r['band_p90']:5.1f}/{r['band_p90'] * mm:5.2f}  {r['pieces']:6d}")
            lines.append("    pair    dE76    dL*     dh    C*i    C*j  shared_px")
            for p in pair_table(q):
                lines.append(f"    {p['i']}-{p['j']}  {p['dE']:6.1f}  {p['dL']:6.1f}"
                             f"  {p['dh']:5.1f}  {p['Ci']:5.1f}  {p['Cj']:5.1f}"
                             f"  {p['shared']:9d}")
            preview(sel.cutout_rgb, sel.mask, q).save(out / f"{sel_dir.name}-n{n}.png")
    text = "\n".join(lines) + "\n"
    (out / "outline-shade.txt").write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()

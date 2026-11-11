"""Measure palette methods on subject selections: CIELAB k-means (two seedings), median cut.

Usage: uv run python research/verification/2026-11-11-color-palette/measure_palette.py \
    OUT_DIR SELECTION_DIR [SELECTION_DIR ...]
OUT_DIR must not exist or be an empty directory. It receives results.txt (also printed) and one preview
PNG per selection, N and method: the cutout, the palette-painted subject, and the painted
subject with the pieces below the island area shown in magenta.

Only pixels where mask.png is 255 count. All methods see the same masked pixels:
- kmeans: sRGB -> CIELAB (D65), farthest-point seeding from the most frequent color,
  Lloyd iterations in float64 weighted by pixel count, until no color changes cluster or
  MAX_ITER is reached.
- kmeans_w: the same, except each seed after the first maximises count * dmin^2 (dmin =
  CIELAB distance to the nearest chosen seed), ties to the lowest unique-color index.
  The unique colors come from np.unique, which sorts them, so the lowest index is the
  lowest packed 0xRRGGBB value (in both k-means seedings).
- mediancut: Pillow Image.quantize(colors=N, method=MEDIANCUT, dither=NONE) on a 1-row image
  of the masked pixels (median cut depends only on the color histogram).
Palettes are ordered by area descending, then L*, a*, b*. Each palette color is the rounded
sRGB hex code; Delta E*76 is measured to the CIELAB value of that hex code, both for each
pixel's assigned color and (nearest_*) for its nearest palette color; not_nearest% is the
share of pixels whose assigned color is not their nearest (ties count as nearest).
The island area is (flat.island.min_square_side x nozzle)^2 from rules/geometry-flat.yaml and
profiles/printers/bambu-a1.yaml, converted to pixels with mm_per_px = WIDTH_MM / (mask
bounding-box width in px), as tdmg flat scales the exact outline.
"""
import hashlib
import pathlib
import platform
import subprocess
import sys
import time

import cv2
import numpy as np
import PIL
from PIL import Image

from tdmg.profiles import load_printer
from tdmg.rules import load_rules

WIDTH_MM = 60.0  # the owner's flat models (tdmg flat --width-mm 60)
NS = (2, 3, 4)
MAX_ITER = 1000  # Lloyd iteration cap; the results record how many iterations each run used
EDGE_BAND_PX = 2.0  # diagnostic only: "edge pixels" are within this distance of the outside

# sRGB (IEC 61966-2-1) linear RGB -> XYZ matrix and D65 white, as in the standard formulas.
M_RGB2XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                      [0.2126729, 0.7151522, 0.0721750],
                      [0.0193339, 0.1191920, 0.9503041]])
M_XYZ2RGB = np.linalg.inv(M_RGB2XYZ)
WHITE = np.array([0.95047, 1.0, 1.08883])
D = 6.0 / 29.0


def srgb_to_lab(rgb8):
    c = np.asarray(rgb8, dtype=np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    t = (lin @ M_RGB2XYZ.T) / WHITE
    f = np.where(t > D ** 3, np.cbrt(t), t / (3 * D * D) + 4.0 / 29.0)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)


def lab_to_srgb8(lab):
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], axis=-1)
    t = np.where(f > D, f ** 3, 3 * D * D * (f - 4.0 / 29.0))
    lin = np.clip((t * WHITE) @ M_XYZ2RGB.T, 0.0, 1.0)
    c = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * lin ** (1 / 2.4) - 0.055)
    return np.clip(np.rint(c * 255), 0, 255).astype(np.uint8)


def kmeans_lab(px, n, weighted=False):
    """Return (labels, iterations, converged) for px (k, 3) uint8.

    labels are 0..n-1 per pixel, not yet ordered; iterations is the number of centroid
    updates; converged is False if MAX_ITER was reached.
    """
    packed = (px[:, 0].astype(np.uint32) << 16) | (px[:, 1].astype(np.uint32) << 8) | px[:, 2]
    uniq, inverse, counts = np.unique(packed, return_inverse=True, return_counts=True)
    ucol = np.stack([(uniq >> 16) & 255, (uniq >> 8) & 255, uniq & 255], axis=1)
    lab = srgb_to_lab(ucol)
    w = counts.astype(np.float64)
    seeds = [int(np.argmax(counts))]  # argmax returns the lowest index on ties
    dmin = np.linalg.norm(lab - lab[seeds[0]], axis=1)
    while len(seeds) < min(n, len(uniq)):
        # weighted: greedy argmax of count * dmin^2 (k-means++ D^2 weighting, no randomness)
        s = int(np.argmax(counts * dmin ** 2 if weighted else dmin))  # lowest index on ties
        seeds.append(s)
        dmin = np.minimum(dmin, np.linalg.norm(lab - lab[s], axis=1))
    cent = lab[seeds].copy()
    assign = None
    for it in range(1, MAX_ITER + 1):
        dist = np.linalg.norm(lab[:, None, :] - cent[None, :, :], axis=2)
        new = np.argmin(dist, axis=1)  # lowest cluster index on ties
        if assign is not None and np.array_equal(new, assign):
            return new[inverse], it - 1, True
        assign = new
        for k in range(len(cent)):
            sel = assign == k
            if sel.any():  # an empty cluster keeps its centroid
                cent[k] = (lab[sel] * w[sel, None]).sum(0) / w[sel].sum()
    return assign[inverse], MAX_ITER, False


def mediancut(px, n):
    strip = Image.fromarray(px.reshape(1, -1, 3), "RGB")
    q = strip.quantize(colors=n, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    return np.array(q).reshape(-1).astype(np.int64)


def order_and_palette(px, raw):
    """Relabel by area desc, then L*, a*, b* of the palette color; return labels and rgb8."""
    ids = np.unique(raw)
    cols = []
    for k in ids:
        mean_lab = srgb_to_lab(px[raw == k]).mean(0)  # cluster mean in CIELAB
        cols.append((int((raw == k).sum()), lab_to_srgb8(mean_lab)))
    rgb = np.array([c[1] for c in cols])
    lab = srgb_to_lab(rgb)
    order = sorted(range(len(ids)), key=lambda i: (-cols[i][0], *lab[i]))
    remap = np.empty(int(ids.max()) + 1, dtype=np.int64)
    for new, i in enumerate(order):
        remap[ids[i]] = new
    return remap[raw], rgb[order]


def run(method, px, n):
    t0 = time.perf_counter()
    if method in ("kmeans", "kmeans_w"):
        raw, iters, converged = kmeans_lab(px, n, weighted=method == "kmeans_w")
    else:
        raw, iters, converged = mediancut(px, n), None, None
    labels, rgb = order_and_palette(px, raw)
    return labels, rgb, time.perf_counter() - t0, iters, converged


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


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

    side = load_rules()["flat.island.min_square_side"].default
    nozzle = load_printer("bambu-a1").nozzle_diameter_mm
    island_mm2 = (side * nozzle) ** 2
    try:
        commit = subprocess.run(["git", "describe", "--always", "--dirty"], capture_output=True,
                                text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    script_sha = sha(__file__)
    lines = [(f"measure_palette.py sha256 {script_sha} at git {commit}; python {platform.python_version()}, "
             f"numpy {np.__version__}, pillow {PIL.__version__}, opencv {cv2.__version__}"),
             (f"flat.island.min_square_side = {side}, nozzle = {nozzle} mm -> island area "
             f"{island_mm2:.4f} mm^2; width {WIDTH_MM} mm; MAX_ITER {MAX_ITER}; "
             f"edge band {EDGE_BAND_PX} px")]

    # CIELAB check: fixed reference colors, the inverse, and OpenCV's float conversion.
    refs = np.array([[255, 255, 255], [0, 0, 0], [255, 0, 0], [0, 255, 0], [0, 0, 255]])
    lines.append("CIELAB of white, black, red, green, blue: " + "; ".join(
        f"{tuple(int(v) for v in r)} -> ({L:.4f}, {a:.4f}, {b:.4f})"
        for r, (L, a, b) in zip(refs, srgb_to_lab(refs))))
    allc = np.stack(np.meshgrid(*[np.arange(256)] * 3, indexing="ij"), -1).reshape(-1, 3)
    mine = srgb_to_lab(allc)
    rt = np.abs(lab_to_srgb8(mine).astype(int) - allc).max()
    cv = cv2.cvtColor((allc.reshape(1, -1, 3) / 255.0).astype(np.float32),
                      cv2.COLOR_RGB2Lab).reshape(-1, 3).astype(np.float64)
    lines.append(f"all 16,777,216 sRGB colors: round trip sRGB->Lab->sRGB max error {rt} "
                 f"levels; max |difference| from OpenCV float32 RGB2Lab: "
                 f"{np.abs(mine - cv).max(0).round(4).tolist()} (L*, a*, b*)")

    for sel in sels:
        mask = np.array(Image.open(sel / "mask.png"))
        cut = np.array(Image.open(sel / "cutout.png").convert("RGBA"))
        inside = mask == 255
        cols = np.where(inside.any(0))[0]
        mm_per_px = WIDTH_MM / (cols.max() - cols.min() + 1)
        island_px = island_mm2 / mm_per_px ** 2
        px = cut[inside][:, :3]
        lab_px = srgb_to_lab(px)
        packed = (px[:, 0].astype(np.uint32) << 16) | (px[:, 1].astype(np.uint32) << 8) | px[:, 2]
        dist_out = cv2.distanceTransform(inside.astype(np.uint8), cv2.DIST_L2, 5)[inside]
        edge = dist_out <= EDGE_BAND_PX
        lines += ["", (f"== {sel.name}: mask sha256 {sha(sel / 'mask.png')[:16]}, cutout sha256 "
                  f"{sha(sel / 'cutout.png')[:16]}"),
                  (f"   {inside.sum()} masked px, {len(np.unique(packed))} unique colors, "
                  f"mm_per_px {mm_per_px:.6f}, island area {island_px:.2f} px, "
                  f"edge-band px {edge.mean():.1%}"),
                  ("   method    N  dE_mean  dE_p95  pieces  small  small_px%  time_s(run1/run2)"
                  "  iters  identical  label_sha256[:16]  colors  nearest_mean  nearest_p95"
                  "  not_nearest%")]
        detail = []
        bg = np.full(cut.shape[:2] + (3,), 255, np.uint8)
        a = cut[..., 3:4].astype(np.float64) / 255
        orig = np.rint(cut[..., :3] * a + bg * (1 - a)).astype(np.uint8)
        for n in NS:
            for method in ("kmeans", "mediancut", "kmeans_w"):
                labels, rgb, t1, iters, conv = run(method, px, n)
                labels2, rgb2, t2, _, _ = run(method, px, n)
                lab_map = np.full(mask.shape, 255, np.uint8)
                lab_map[inside] = labels
                lab_map2 = np.full(mask.shape, 255, np.uint8)
                lab_map2[inside] = labels2
                h1 = hashlib.sha256(lab_map.tobytes()).hexdigest()
                h2 = hashlib.sha256(lab_map2.tobytes()).hexdigest()
                same = h1 == h2 and np.array_equal(rgb, rgb2)
                plab = srgb_to_lab(rgb)
                de = np.linalg.norm(lab_px - plab[labels], axis=1)
                de_all = np.linalg.norm(lab_px[:, None, :] - plab[None, :, :], axis=2)
                de_near = de_all.min(axis=1)
                not_nearest = (de > de_near).mean()
                pieces = small = small_px = 0
                small_map = np.zeros(mask.shape, bool)
                for k in range(len(rgb)):
                    cnt, comp, stats, _ = cv2.connectedComponentsWithStats(
                        (lab_map == k).astype(np.uint8), connectivity=4)
                    areas = stats[1:, cv2.CC_STAT_AREA]
                    tiny = np.where(areas < island_px)[0] + 1
                    pieces += cnt - 1
                    small += len(tiny)
                    small_px += int(areas[tiny - 1].sum())
                    small_map |= np.isin(comp, tiny)
                it_s = "-" if iters is None else f"{iters}{'' if conv else '(cap)'}"
                lines.append(f"   {method:9s} {n}  {de.mean():7.2f}  {np.percentile(de, 95):6.2f}"
                             f"  {pieces:6d}  {small:5d}  {small_px / inside.sum():8.2%}"
                             f"  {t1:.3f}/{t2:.3f}  {it_s:>5s}  {same!s:9s}  {h1[:16]}"
                             f"  {len(rgb):6d}{'' if len(rgb) == n else '!'}"
                             f"  {de_near.mean():12.2f}  {np.percentile(de_near, 95):11.2f}"
                             f"  {not_nearest:11.2%}"
                             f"{'  FEWER THAN N COLORS' if len(rgb) < n else ''}")
                parts = []
                for k, c in enumerate(rgb):
                    sel_k = labels == k
                    parts.append(f"#{c[0]:02x}{c[1]:02x}{c[2]:02x} {sel_k.mean():.1%} "
                                 f"(edge {edge[sel_k].mean():.0%})")
                detail.append(f"   {method:9s} {n}: " + ", ".join(parts))
                painted = bg.copy()
                painted[inside] = rgb[labels]
                marked = painted.copy()
                marked[small_map] = (255, 0, 255)
                Image.fromarray(np.hstack([orig, painted, marked])).save(
                    out / f"{sel.name}-n{n}-{method}.png")
        lines += ["   palettes (hex, area share, share of that color's px in the edge band):",
                  *detail]
    text = "\n".join(lines) + "\n"
    (out / "results.txt").write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()

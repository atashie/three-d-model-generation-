"""Palette of a masked image: deterministic, count-weighted k-means in CIELAB.

Standalone: it takes an RGB image, a mask and a number of colors, and knows nothing of
extrusion, thickness or printing. tdmg colors uses it (docs/plans/2026-11-11-color-palette.md,
Decision 3); the method was measured on the owner's images in
research/verification/2026-11-11-color-palette/ (kmeans_w in measure_palette.py), and
this module is a port of that method plus a final nearest reassignment.

Method (METHOD), `quantize(rgb, mask, n)`:
1. Only pixels where mask is True count. Their colors are packed as 0xRRGGBB and made
   unique with np.unique, which sorts them, so "the lowest index" below is the lowest
   packed value. Each unique color is weighted by its pixel count.
2. Each unique color goes to CIELAB (D65 white, float64; `srgb_to_lab`).
3. Seeds, without random numbers: the first is the most frequent color; each next one is
   the color with the largest count * dmin^2 (dmin: CIELAB distance to the nearest seed
   chosen so far). Ties go to the lowest index. There are min(n, unique colors) seeds.
4. Lloyd iterations: each unique color goes to its nearest centroid (ties to the lowest
   centroid index); each centroid becomes the count-weighted CIELAB mean of its colors;
   an empty cluster keeps its centroid. They stop when no color changes cluster, or at
   MAX_ITER (then `converged` is False).
5. Each centroid goes to sRGB and is rounded to 8 bits: the palette's hex codes.
6. Every masked pixel is then reassigned to its nearest rounded palette color in CIELAB
   (ties to the lowest index), so the labels, the preview and any Delta E agree with the
   hex codes. A palette color that gets no pixel is dropped and counted in `dropped`.
7. The palette is ordered by pixel count descending, then by the L*, a*, b* of the rounded
   color, and the labels are renumbered to match.

Differences from the Task 1 script, which tests/test_color.py checks against its
recorded label hashes: the script kept the Lloyd assignment (step 4) as the labels and
ordered by those areas; step 6 is new (it changes 3 to 141 pixels, 0.004% to 0.05%, of
the owner's images). The CIELAB constants now come from the W3C CSS Color 4 sample code
instead of the script's seven-decimal matrix and white; on the owner's images, at N = 2,
3 and 4, both give the same Task 1 label hashes, palettes and iteration counts (measured
2026-11-11 on the Windows PC). They move one near-tie pixel in step 6 (Roadie, N = 2).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

METHOD = "kmeans-lab-countweighted/1"

# Lloyd iteration cap: a numerical safety bound so a cycle cannot run forever, not a rule.
# Lloyd's method on a finite set cannot revisit a partition while the weighted squared
# error strictly falls, so it stops; the cap only guards against floating-point ties.
# On the owner's images it needed 3 to 14 iterations (Task 1 results.txt), far below it.
MAX_ITER = 1000

OUTSIDE = -1  # the label of pixels outside the mask

# --- CIELAB constants ---------------------------------------------------------------------
# Source: W3C, CSS Color Module Level 4, Candidate Recommendation Draft, 3 November 2026,
# https://www.w3.org/TR/2026/CRD-css-color-4-20261103/ (fetched 2026-11-11 from
# https://www.w3.org/TR/css-color-4/, HTML sha256
# b66ad2af540a7550fd34e0d95f8dce3f49b9d39e255fdfed56f0ec1de9c78000). Section 19,
# "Sample code for Color Conversions" (id "color-conversion-code"), which is not normative;
# section 10.2, "The Predefined sRGB Color Space: the sRGB keyword" (id "predefined-sRGB"),
# gives the same transfer function and "The whitepoint is D65."

# sRGB transfer function. Locator, section 19, function lin_sRGB:
#   "if (abs <= 0.04045) {" / "return val / 12.92;" /
#   "return sign * (Math.pow((abs + 0.055) / 1.055, 2.4));"
# and its inverse, function gam_sRGB:
#   "if (abs > 0.0031308) {" / "return sign * (1.055 * Math.pow(abs, 1/2.4) - 0.055);" /
#   "return 12.92 * val;"
SRGB_LIN_THRESHOLD = 0.04045
SRGB_GAM_THRESHOLD = 0.0031308
SRGB_SLOPE = 12.92
SRGB_OFFSET = 0.055
SRGB_GAMMA = 2.4

# Linear sRGB -> XYZ (D65, no chromatic adaptation). Locator, section 19, function
# lin_sRGB_to_XYZ: "[ 506752 / 1228815,  87881 / 245763,   12673 /   70218 ],"
# "[  87098 /  409605, 175762 / 245763,   12673 /  175545 ],"
# "[   7918 /  409605,  87881 / 737289, 1001167 / 1053270 ],"
# The inverse is this matrix inverted in float64 (the spec's XYZ_to_lin_sRGB gives the
# same matrix as rational numbers; its inverse is the one below to rounding).
M_RGB_TO_XYZ = np.array([
    [506752 / 1228815, 87881 / 245763, 12673 / 70218],
    [87098 / 409605, 175762 / 245763, 12673 / 175545],
    [7918 / 409605, 87881 / 737289, 1001167 / 1053270],
])
M_XYZ_TO_RGB = np.linalg.inv(M_RGB_TO_XYZ)

# D65 white. Locator, section 19:
#   "const D65 = [0.3127 / 0.3290, 1.00000, (1.0 - 0.3127 - 0.3290) / 0.3290];"
WHITE_D65 = np.array([0.3127 / 0.3290, 1.00000, (1.0 - 0.3127 - 0.3290) / 0.3290])

# CIELAB. Locator, section 19, function XYZ_to_Lab: "var ε = 216/24389;  // 6^3/29^3",
# "var κ = 24389/27;   // 29^3/3^3",
# "var f = xyz.map(value => value > ε ? Math.cbrt(value) : (κ * value + 16)/116);",
# "(116 * f[1]) - 16,", "500 * (f[0] - f[1]),", "200 * (f[1] - f[2])";
# and function Lab_to_XYZ for the inverse. The spec's Lab uses its D50 white (after a
# Bradford adaptation); here the same formulas use the D65 white above directly, the
# usual sRGB-D65 CIELAB, as Decision 3 and the Task 1 measurement did.
LAB_EPSILON = 216 / 24389
LAB_KAPPA = 24389 / 27


class ColorError(ValueError):
    """Bad input to tdmg.color."""


def srgb_to_lab(rgb8) -> np.ndarray:
    """8-bit sRGB (..., 3) to CIELAB (..., 3), D65 white, float64."""
    c = np.asarray(rgb8, dtype=np.float64) / 255.0
    lin = np.where(c <= SRGB_LIN_THRESHOLD, c / SRGB_SLOPE,
                   ((c + SRGB_OFFSET) / (1 + SRGB_OFFSET)) ** SRGB_GAMMA)
    xyz = (lin @ M_RGB_TO_XYZ.T) / WHITE_D65
    f = np.where(xyz > LAB_EPSILON, np.cbrt(xyz), (LAB_KAPPA * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)


def lab_to_srgb8(lab) -> np.ndarray:
    """CIELAB (..., 3), D65 white, to 8-bit sRGB (..., 3), clipped to the sRGB gamut."""
    lab = np.asarray(lab, dtype=np.float64)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = L / 116 + 16 / 116
    fx = fy + a / 500
    fz = fy - b / 200
    xyz = np.stack([
        np.where(fx ** 3 > LAB_EPSILON, fx ** 3, (116 * fx - 16) / LAB_KAPPA),
        np.where(L > LAB_KAPPA * LAB_EPSILON, fy ** 3, L / LAB_KAPPA),
        np.where(fz ** 3 > LAB_EPSILON, fz ** 3, (116 * fz - 16) / LAB_KAPPA),
    ], axis=-1)
    lin = np.clip((xyz * WHITE_D65) @ M_XYZ_TO_RGB.T, 0.0, 1.0)
    c = np.where(lin > SRGB_GAM_THRESHOLD,
                 (1 + SRGB_OFFSET) * lin ** (1 / SRGB_GAMMA) - SRGB_OFFSET, SRGB_SLOPE * lin)
    return np.clip(np.rint(c * 255), 0, 255).astype(np.uint8)


@dataclass(frozen=True)
class Quantized:
    """The result of `quantize`. Arrays are read-only. k is the number of palette colors.

    labels: (H, W) int32, the palette index of each masked pixel, OUTSIDE (-1) elsewhere.
    rgb: (k, 3) uint8 palette colors; hex: the same as "#rrggbb"; lab: (k, 3) float64,
      the CIELAB of the rounded colors. counts: masked pixels per color; shares: counts
      over all masked pixels. Ordered by count descending, then L*, a*, b*.
    iterations: Lloyd centroid updates; converged: False if MAX_ITER was reached.
    n_requested: n as given; n_distinct_colors: unique colors among the masked pixels
      (when below n, the palette has at most that many colors); dropped: palette colors
      left with no pixel after the final reassignment, and removed.
    """

    labels: np.ndarray
    rgb: np.ndarray
    hex: tuple[str, ...]
    lab: np.ndarray
    counts: tuple[int, ...]
    shares: tuple[float, ...]
    iterations: int
    converged: bool
    n_requested: int
    n_distinct_colors: int
    dropped: int


def _unique_colors(px: np.ndarray):
    """(k, 3) uint8 pixels -> (sorted packed uniques, inverse, counts, CIELAB of uniques)."""
    packed = ((px[:, 0].astype(np.uint32) << 16) | (px[:, 1].astype(np.uint32) << 8)
              | px[:, 2].astype(np.uint32))
    uniq, inverse, counts = np.unique(packed, return_inverse=True, return_counts=True)
    ucol = np.stack([(uniq >> 16) & 255, (uniq >> 8) & 255, uniq & 255], axis=1)
    return uniq, inverse.reshape(-1), counts, srgb_to_lab(ucol.astype(np.uint8))


def _seed(lab: np.ndarray, counts: np.ndarray, n: int) -> list[int]:
    """Indices of min(n, len(lab)) seeds: most frequent, then greedy count * dmin^2."""
    seeds = [int(np.argmax(counts))]  # argmax returns the lowest index on ties
    dmin = np.linalg.norm(lab - lab[seeds[0]], axis=1)
    while len(seeds) < min(n, len(lab)):
        s = int(np.argmax(counts * dmin ** 2))  # lowest index on ties
        seeds.append(s)
        dmin = np.minimum(dmin, np.linalg.norm(lab - lab[s], axis=1))
    return seeds


def _kmeans(lab: np.ndarray, counts: np.ndarray, n: int):
    """Weighted Lloyd iterations from `_seed`. Returns (centroids, assignment of each
    unique color, centroid updates, converged)."""
    w = counts.astype(np.float64)
    cent = lab[_seed(lab, counts, n)].copy()
    assign = None
    for it in range(1, MAX_ITER + 1):
        dist = np.linalg.norm(lab[:, None, :] - cent[None, :, :], axis=2)
        new = np.argmin(dist, axis=1)  # lowest centroid index on ties
        if assign is not None and np.array_equal(new, assign):
            return cent, new, it - 1, True
        assign = new
        for k in range(len(cent)):
            sel = assign == k
            if sel.any():  # an empty cluster keeps its centroid
                cent[k] = (lab[sel] * w[sel, None]).sum(0) / w[sel].sum()
    return cent, assign, MAX_ITER, False


def _finish(lab: np.ndarray, counts: np.ndarray, inverse: np.ndarray, cent: np.ndarray):
    """Round the centroids, reassign to the nearest rounded color, drop empty ones, order.

    Returns (labels of each pixel, rgb (k, 3) uint8, counts (k,), number dropped).
    """
    rgb = lab_to_srgb8(cent)
    plab = srgb_to_lab(rgb)
    dist = np.linalg.norm(lab[:, None, :] - plab[None, :, :], axis=2)
    nearest = np.argmin(dist, axis=1)  # per unique color; lowest index on ties
    sizes = np.bincount(nearest, weights=counts, minlength=len(rgb)).astype(np.int64)
    kept = [k for k in range(len(rgb)) if sizes[k] > 0]
    order = sorted(kept, key=lambda k: (-int(sizes[k]), *plab[k].tolist()))
    remap = np.full(len(rgb), OUTSIDE, np.int64)
    remap[order] = np.arange(len(order))
    return remap[nearest][inverse], rgb[order], sizes[order], len(rgb) - len(kept)


def _readonly(a: np.ndarray) -> np.ndarray:
    a.flags.writeable = False
    return a


def quantize(rgb: np.ndarray, mask: np.ndarray, n: int) -> Quantized:
    """Palette of at most n colors for the pixels of `rgb` where `mask` is True.

    rgb: (H, W, 3) uint8 sRGB. mask: (H, W) bool. n: int >= 1. See METHOD in the module
    docstring. Raises ColorError on bad input or an empty mask.
    """
    rgb = np.asarray(rgb)
    mask = np.asarray(mask)
    if isinstance(n, bool) or not isinstance(n, (int, np.integer)) or n < 1:
        raise ColorError(f"n must be an integer >= 1, got {n!r}")
    if rgb.dtype != np.uint8:
        raise ColorError(f"rgb must be uint8, got {rgb.dtype}")
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ColorError(f"rgb must have shape (H, W, 3), got {rgb.shape}")
    if mask.dtype != np.bool_ or mask.shape != rgb.shape[:2]:
        raise ColorError(f"mask must be bool with shape {rgb.shape[:2]}, "
                         f"got {mask.dtype} {mask.shape}")
    if not mask.any():
        raise ColorError("mask selects no pixel")
    _, inverse, counts, lab = _unique_colors(rgb[mask])
    cent, _, iterations, converged = _kmeans(lab, counts, int(n))
    px_labels, pal, sizes, dropped = _finish(lab, counts, inverse, cent)
    labels = np.full(mask.shape, OUTSIDE, np.int32)
    labels[mask] = px_labels
    total = int(mask.sum())
    return Quantized(
        labels=_readonly(labels),
        rgb=_readonly(pal),
        hex=tuple("#" + "".join(f"{int(v):02x}" for v in c) for c in pal),
        lab=_readonly(srgb_to_lab(pal)),
        counts=tuple(int(s) for s in sizes),
        shares=tuple(int(s) / total for s in sizes),
        iterations=iterations,
        converged=converged,
        n_requested=int(n),
        n_distinct_colors=len(counts),
        dropped=dropped,
    )

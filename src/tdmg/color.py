"""Palette of a masked image: deterministic, count-weighted k-means in CIELAB.

Standalone: it takes an RGB image, a mask and a number of colors, and knows nothing of
extrusion or thickness (the cleanup's printing limits come in as pixel sizes, see below).
tdmg colors uses it (docs/plans/2026-11-11-color-palette.md,
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

Round trip: sRGB -> CIELAB -> sRGB returns all 16,777,216 8-bit colors exactly (checked
2026-11-11 on the Windows PC; the tests check a 52^3 grid).

Region cleanup (CLEANUP_METHOD), `clean_regions(q, limits)` (Decision 4): see its
docstring. It moves labels only, never palette colors. Its limits are the R1 rules'
printing sizes, converted to pixels by `printable_limits_px`.

Extraction steps (plan Task 7b): `handle_outlines` is the seam for the outline family
(Task 7b does no outline handling; Task 7c fills it in), `apply_merges` applies the owner's
explicit (from, into) merges, and `index_map` matches palette indices before and after a
step by color. Like the cleanup, they move labels only, never palette colors.

Platform: every result above, and the owner-image fixtures in tests/test_color.py, were
measured on the Windows PC only. The fixtures have not yet been run on the M5 Mac, so
cross-platform parity is unverified. To reduce the risk, the color conversions use
explicit elementwise sums (_mat3) rather than a BLAS matrix product, and the distances
use np.linalg.norm one centroid at a time; neither calls BLAS. Both matrices are the
spec's rational numbers, so no LAPACK inverse is computed either.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

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
# The inverse, XYZ -> linear sRGB, is the spec's own rational matrix (no LAPACK inverse,
# so it does not depend on the platform). Locator, section 19, function XYZ_to_lin_sRGB:
# "[   12831 /   3959,    -329 /    214, -1974 /   3959 ],"
# "[ -851781 / 878810, 1648619 / 878810, 36519 / 878810 ],"
# "[     705 /  12673,   -2585 /  12673,   705 /    667 ],"
M_RGB_TO_XYZ = np.array([
    [506752 / 1228815, 87881 / 245763, 12673 / 70218],
    [87098 / 409605, 175762 / 245763, 12673 / 175545],
    [7918 / 409605, 87881 / 737289, 1001167 / 1053270],
])
M_XYZ_TO_RGB = np.array([
    [12831 / 3959, -329 / 214, -1974 / 3959],
    [-851781 / 878810, 1648619 / 878810, 36519 / 878810],
    [705 / 12673, -2585 / 12673, 705 / 667],
])

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


def _mat3(m: np.ndarray, v: np.ndarray) -> np.ndarray:
    """m (3, 3) applied to the last axis of v (..., 3), as explicit elementwise products and
    sums in a fixed order, (v0 m_i0 + v1 m_i1) + v2 m_i2. No BLAS call is involved, so the
    result does not depend on the BLAS build or its use of FMA or vector kernels."""
    return np.stack([(v[..., 0] * m[i, 0] + v[..., 1] * m[i, 1]) + v[..., 2] * m[i, 2]
                     for i in range(3)], axis=-1)


def srgb_to_lab(rgb8) -> np.ndarray:
    """8-bit sRGB (..., 3) to CIELAB (..., 3), D65 white, float64."""
    c = np.asarray(rgb8, dtype=np.float64) / 255.0
    lin = np.where(c <= SRGB_LIN_THRESHOLD, c / SRGB_SLOPE,
                   ((c + SRGB_OFFSET) / (1 + SRGB_OFFSET)) ** SRGB_GAMMA)
    xyz = _mat3(M_RGB_TO_XYZ, lin) / WHITE_D65
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
    lin = np.clip(_mat3(M_XYZ_TO_RGB, xyz * WHITE_D65), 0.0, 1.0)
    c = np.where(lin > SRGB_GAM_THRESHOLD,
                 (1 + SRGB_OFFSET) * lin ** (1 / SRGB_GAMMA) - SRGB_OFFSET, SRGB_SLOPE * lin)
    return np.clip(np.rint(c * 255), 0, 255).astype(np.uint8)


@dataclass(frozen=True, eq=False)
class Quantized:
    """The result of `quantize` or `from_labels`. Arrays are read-only. k is the number of
    palette colors. eq=False: instances compare by identity (numpy arrays have no single
    truth value, so a generated __eq__ would fail).

    labels: int32, the shape of the image (or of the labels given to from_labels), the
      palette index of each pixel, OUTSIDE (-1) outside the mask.
    rgb: (k, 3) uint8 palette colors; hex: tuple of k str, "#rrggbb"; lab: (k, 3) float64,
      the CIELAB of the rounded colors.
    counts: tuple of k int, pixels per color; shares: tuple of k float, counts over all
      labelled pixels.
    Order: always count descending, then L*, a*, b* ascending; from_labels re-sorts after
      every step that changes labels, and palette index i means this order.
    iterations: int, Lloyd centroid updates; converged: bool, False if MAX_ITER was reached.
    n_requested: int, n as given; n_distinct_colors: int, unique colors among the masked
      pixels (when below n, the palette has at most that many colors); dropped: int,
      palette colors left with no pixel and removed (by the final reassignment, or by any
      later step that passes its own count to from_labels).
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
    """(m, 3) uint8 pixels -> (sorted packed uniques, inverse, counts, CIELAB of uniques)."""
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


def _nearest(lab: np.ndarray, cent: np.ndarray, dist: np.ndarray | None = None) -> np.ndarray:
    """Index of the nearest of cent (k, 3) for each of lab (m, 3); ties to the lowest index.

    The distances go one centroid at a time into a (m, k) float64 array (dist, reused if
    given), so the largest temporary is (m, 3), not (m, k, 3). Each column is the same
    np.linalg.norm over the 3 components as the broadcast form computed.
    """
    if dist is None:
        dist = np.empty((len(lab), len(cent)), np.float64)
    for j in range(len(cent)):
        dist[:, j] = np.linalg.norm(lab - cent[j], axis=1)
    return np.argmin(dist, axis=1)


def _kmeans(lab: np.ndarray, counts: np.ndarray, n: int):
    """Weighted Lloyd iterations from `_seed`. Returns (centroids, assignment of each
    unique color, centroid updates, converged)."""
    w = counts.astype(np.float64)
    cent = lab[_seed(lab, counts, n)].copy()
    assign = None
    dist = np.empty((len(lab), len(cent)), np.float64)
    for it in range(1, MAX_ITER + 1):
        new = _nearest(lab, cent, dist)  # lowest centroid index on ties
        if assign is not None and np.array_equal(new, assign):
            return cent, new, it - 1, True
        assign = new
        for k in range(len(cent)):
            sel = assign == k
            if sel.any():  # an empty cluster keeps its centroid
                cent[k] = (lab[sel] * w[sel, None]).sum(0) / w[sel].sum()
    return cent, assign, MAX_ITER, False


def _readonly(a: np.ndarray) -> np.ndarray:
    a.flags.writeable = False
    return a


def from_labels(labels, rgb, *, iterations: int, converged: bool, n_requested: int,
                n_distinct_colors: int, dropped: int = 0) -> Quantized:
    """Build a Quantized from a label map and its palette, in the canonical order.

    labels: an integer array of any shape, each value an index into rgb or OUTSIDE (-1).
    rgb: (m, 3) uint8 palette colors. Palette entries that no pixel uses are removed and
    added to `dropped`. The rest are ordered by pixel count descending, then by the L*,
    a*, b* of the color ascending, and the labels are renumbered to match (OUTSIDE stays
    -1). This order is the final one after any step: a later step that changes labels
    (such as the region cleanup) calls this again, so the palette is re-sorted by its new
    areas, and a numeric palette index (such as the config's `base`) refers to that final
    order, which is what the preview shows. The other keywords are copied into the result.
    Raises ColorError on a bad palette, a label out of range, or no labelled pixel.
    """
    labels = np.asarray(labels)
    rgb = np.asarray(rgb)
    if rgb.dtype != np.uint8 or rgb.ndim != 2 or rgb.shape[1] != 3:
        raise ColorError(f"rgb must be uint8 with shape (m, 3), got {rgb.dtype} {rgb.shape}")
    if not np.issubdtype(labels.dtype, np.integer):
        raise ColorError(f"labels must be an integer array, got {labels.dtype}")
    if labels.size and (labels.min() < OUTSIDE or labels.max() >= len(rgb)):
        raise ColorError(f"every label must be {OUTSIDE} or an index below {len(rgb)}, "
                         f"got {labels.min()}..{labels.max()}")
    inside = labels != OUTSIDE
    total = int(inside.sum())
    if total == 0:
        raise ColorError("labels mark no pixel")
    sizes = np.bincount(labels[inside].astype(np.int64), minlength=len(rgb))  # exact ints
    plab = srgb_to_lab(rgb)
    kept = [k for k in range(len(rgb)) if sizes[k] > 0]
    order = sorted(kept, key=lambda k: (-int(sizes[k]), *plab[k].tolist()))
    remap = np.full(len(rgb), OUTSIDE, np.int64)
    remap[order] = np.arange(len(order))
    out = np.full(labels.shape, OUTSIDE, np.int32)
    out[inside] = remap[labels[inside]]
    pal = rgb[order].copy()
    return Quantized(
        labels=_readonly(out),
        rgb=_readonly(pal),
        hex=tuple("#" + "".join(f"{int(v):02x}" for v in c) for c in pal),
        lab=_readonly(plab[order].copy()),
        counts=tuple(int(sizes[k]) for k in order),
        shares=tuple(int(sizes[k]) / total for k in order),
        iterations=int(iterations),
        converged=bool(converged),
        n_requested=int(n_requested),
        n_distinct_colors=int(n_distinct_colors),
        dropped=int(dropped) + len(rgb) - len(kept),
    )


def quantize(rgb: np.ndarray, mask: np.ndarray, n: int) -> Quantized:
    """Palette of at most n colors for the pixels of `rgb` where `mask` is True.

    rgb: (H, W, 3) uint8 sRGB. mask: (H, W) bool. n: int >= 1 (a Python or numpy
    integer; bool and float are refused). See METHOD in the module docstring. The result
    is built by from_labels, so its order is count descending, then L*, a*, b*, and a
    palette index means that order. Raises ColorError on bad input or an empty mask.

    Cost, measured on the Windows PC on 2026-11-11 (time.perf_counter; peak traced by
    tracemalloc, which counts numpy's allocations) for a 4000 x 4000 uniform random-noise
    image (10,313,015 unique colors), n = 4, 40 iterations. Before the distances were
    computed one centroid at a time: 76.6 s, peak 3476 MiB. After: 78.8 s, peak 1940 MiB,
    with the same palette and labels (SHA-256 of the int32 label map 4c9aa069f06d4e33...).
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
    n = int(n)
    _, inverse, counts, lab = _unique_colors(rgb[mask])
    cent, _, iterations, converged = _kmeans(lab, counts, n)
    pal = lab_to_srgb8(cent)
    labels = np.full(mask.shape, OUTSIDE, np.int32)
    labels[mask] = _nearest(lab, srgb_to_lab(pal))[inverse]  # lowest index on ties
    return from_labels(labels, pal, iterations=iterations, converged=converged,
                       n_requested=n, n_distinct_colors=len(counts))


# --- Cleanup to printable regions (Decision 4) ---------------------------------------------

CLEANUP_METHOD = "lattice-opening-nearest-then-boundary-merge/1"

# The R1 rules the limits come from (the same ids as tdmg.flat; a test checks they agree).
OPENING_RULE = "flat.sliver.opening_width"
ISLAND_RULE = "flat.island.min_square_side"
# The units the conversion below assumes; printable_limits_px refuses rules in others.
RULE_UNITS = {OPENING_RULE: "mm", ISLAND_RULE: "x_nozzle"}

# Pass cap. This is a numerical safety bound on a loop, kept here and not in rules/: it is
# not a print threshold and has no physical meaning; it only stops clean_regions from
# running forever, and `cap_hit` records if it was reached. No proof bounds the number of
# passes: a merge can shrink a color, and the sampled opening (open_mask) is not
# idempotent (opening its own result can remove more pixels: a 30 x 30 square at w = 4 px
# loses 12, 12, 16, 20 ... pixels on repeated openings), so neither step alone gives a
# monotone quantity. In clean_regions that repeated erosion is contained, because a thin
# pixel whose own color's non-thin pixels are as near as any keeps its color (a 30 x 30
# block inside another color stops after 2 passes, 4 corner pixels moved). A pass can
# also move labels and move them back: thin pixels given a color whose nearest non-thin
# pixels they do not touch 4-connectedly (a diagonal contact, or across a gap of another
# color) form a small piece of that color, which the merge step returns. So the stop test
# is that a whole pass leaves the labels as they were (a fixed point of the pass), not
# that neither step moved anything. Observed on the owner's images (N = 4, 60 mm wide,
# 2026-11-11, Windows PC; tests/test_color_cleanup.py prints the log): 5 passes for
# Roadie and 4 for Oddie, far below the cap.
MAX_CLEAN_PASSES = 100

_FOUR = ndimage.generate_binary_structure(2, 1)  # 4-connectivity: no diagonal neighbours


def _finite_positive(name: str, value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ColorError(f"{name} must be a number, got {value!r}")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ColorError(f"{name} must be a finite number above 0, got {value}")
    return value


@dataclass(frozen=True)
class Limits:
    """The printable limits in pixels, and where they came from.

    min_width_px: the opening width, flat.sliver.opening_width (mm) / mm_per_px.
    min_area_px: the island area, (flat.island.min_square_side x nozzle_diameter_mm)^2
      (mm^2) / mm_per_px^2.
    The other fields record the inputs: the scale, the two values in mm and mm^2, the
    printer profile's nozzle diameter and the two rule ids. Raises ColorError unless every
    number is finite and above 0.
    """

    min_width_px: float
    min_area_px: float
    mm_per_px: float
    opening_width_mm: float
    island_area_mm2: float
    nozzle_diameter_mm: float
    opening_rule: str
    island_rule: str

    def __post_init__(self):
        for name in ("min_width_px", "min_area_px", "mm_per_px", "opening_width_mm",
                     "island_area_mm2", "nozzle_diameter_mm"):
            object.__setattr__(self, name, _finite_positive(name, getattr(self, name)))


def printable_limits_px(mm_per_px, rules, printer) -> Limits:
    """The cleanup limits in pixels at mm_per_px (mm per image pixel; tdmg flat's scale is
    width_mm / mask bbox width in px).

    rules: the dict from tdmg.rules.load_rules(); printer: a tdmg.profiles.PrinterProfile.
    The island area is (min_square_side x nozzle_diameter_mm)^2, as tdmg.flat computes
    it. Raises ColorError unless mm_per_px is a finite number above 0, and if either
    rule is not in the unit the conversion assumes (RULE_UNITS: mm, and nozzle widths).
    """
    mm_per_px = _finite_positive("mm_per_px", mm_per_px)
    for rule_id, unit in RULE_UNITS.items():
        if rules[rule_id].unit != unit:
            raise ColorError(f"{rule_id} must be in {unit!r} for this conversion, "
                             f"got {rules[rule_id].unit!r}")
    opening_mm = float(rules[OPENING_RULE].default)
    nozzle = float(printer.nozzle_diameter_mm)
    island_mm2 = (float(rules[ISLAND_RULE].default) * nozzle) ** 2
    return Limits(min_width_px=opening_mm / mm_per_px, min_area_px=island_mm2 / mm_per_px ** 2,
                  mm_per_px=mm_per_px, opening_width_mm=opening_mm, island_area_mm2=island_mm2,
                  nozzle_diameter_mm=nozzle, opening_rule=OPENING_RULE, island_rule=ISLAND_RULE)


@dataclass(frozen=True)
class CleanupLog:
    """What clean_regions did. Colors are named by hex code, since palette indices change
    when the palette is re-sorted.

    passes: passes run, counting the last one, which changed nothing unless cap_hit.
    cap_hit: True if MAX_CLEAN_PASSES passes ran and the last still changed labels (the
      result is then not a fixed point).
    thin_pixels_reassigned: thin pixels whose label the thin step changed, summed over the
      passes that changed the labels (an event count: a pixel moved in two passes counts
      twice; the last, unchanging pass is not included).
    thin_pixels_left: thin pixels of the last pass that end it with their own color: those
      whose nearest non-thin pixel has their own color (spurs, corners with no other color
      nearer), and the thin_returned ones.
    thin_returned: pixels the thin step of the last pass moved and its merge step moved
      back (see MAX_CLEAN_PASSES).
    no_core: True if some pass found no non-thin labelled pixel at all; its thin step then
      left the labels unchanged.
    pieces_merged: merges, summed over the passes that changed the labels (a piece that is
      itself the result of an earlier merge counts again when it merges).
    pixels_changed: pixels whose final color differs from their input color (net).
    moved: ((from_hex, to_hex, pixels), ...), the net changes from input color to final
      color, ordered by pixels descending, then from_hex, then to_hex. The pixels sum to
      pixels_changed.
    dropped_hex: input colors that no pixel has after cleanup, in the input palette order.
    kept_pieces, kept_area_px: pieces below min_area_px in the last pass with no color
      neighbour (only OUTSIDE or the image edge around them), kept as they are; removing
      them is R1 geometry's job.
    limits: the Limits used.
    """

    passes: int
    cap_hit: bool
    thin_pixels_reassigned: int
    thin_pixels_left: int
    thin_returned: int
    no_core: bool
    pieces_merged: int
    pixels_changed: int
    moved: tuple[tuple[str, str, int], ...]
    dropped_hex: tuple[str, ...]
    kept_pieces: int
    kept_area_px: int
    limits: Limits


# The half-pixel lattice of candidate disk centres, as (dy, dx) positions within a pixel
# (pixel (i, j) is the square [j, j+1] x [i, i+1], x right, y down): its centre, the
# midpoints of its top and left edges, and its top-left corner. Together, over all pixels,
# they are every point whose coordinates are multiples of 1/2.
_LATTICE = ((0.5, 0.5), (0.0, 0.5), (0.5, 0.0), (0.0, 0.0))


def _opening_offsets(r: float):
    """For each lattice type (dy, dx) in _LATTICE: (erosion offsets, dilation offsets).

    Erosion offsets: the pixel offsets (di, dj) whose closed square comes within r of the
    candidate point (its distance is <= r); the candidate is a centre only if all of them
    are inside the region. Dilation offsets: the anchor offsets (di, dj) whose candidate
    point lies within r of a pixel's centre. Every coordinate is a multiple of 1/2, so the
    squared distances are exact in float64 and compared with r * r exactly.
    """
    rr = r * r
    m = math.ceil(r) + 1
    rng = range(-m, m + 1)
    out = []
    for v, u in _LATTICE:
        ero, dil = [], []
        for di in rng:
            for dj in rng:
                ddx = max(dj - u, 0.0, u - (dj + 1))
                ddy = max(di - v, 0.0, v - (di + 1))
                if ddx * ddx + ddy * ddy <= rr:
                    ero.append((di, dj))
                if (dj + u - 0.5) ** 2 + (di + v - 0.5) ** 2 <= rr:
                    dil.append((di, dj))
        out.append((ero, dil))
    return out, m


def open_mask(mask: np.ndarray, width_px: float) -> np.ndarray:
    """The pixels of mask (bool (H, W)) that survive an opening of width width_px.

    Reference: R1's opening, shapely buffer(-w/2).buffer(+w/2) of the union of the mask's
    pixel squares (beyond the image is outside), which removes every straight strip of
    width <= w and keeps one wider than w. Here r = w / 2, f(c) is the exact Euclidean
    distance from a point c to the complement of that union, and a pixel is kept iff its
    centre lies within r (<=) of a candidate centre c with f(c) > r (strict), where the
    candidates are the half-pixel lattice (_LATTICE: every point whose x and y are
    multiples of 1/2). That is: an erosion of the pixel squares by r sampled at the
    lattice, then a dilation by r sampled at the pixel centres.

    Exactness and error bound. Let O(m) be the set of pixels whose centre is within r - m
    of some point c (anywhere) with f(c) > r + m; O(0) is the exact pixel-centre sample of
    the reference opening. The result K satisfies O(sqrt(2)/4) within K within O(0): it
    only errs toward removal, and only for pixels kept by centres whose margin is below
    sqrt(2)/4 = 0.354 px, the lattice's covering radius (f is 1-Lipschitz, and every
    point is within sqrt(2)/4 of a lattice point). For an axis-aligned straight strip of n
    px it is exact: the strip's midline (n/2) is on the lattice, so the strip is removed
    iff n/2 <= r, i.e. n <= w; and if n > w, each pixel across it has a lattice point in
    (r, r + 1/2] from the near edge, or the midline, within r of its centre, so the whole
    width is kept (away from the strip's ends, which round). A non-integer w is used as
    is, not rounded: w = 3.993 removes a 3 px strip and keeps a 4 px one; w = 4 removes
    4 px and keeps 5 px. For every other shape (45 degree and other staircase edges,
    curves, corners) only the bound above is claimed; the tests check it by brute force on
    45 degree bands and random blobs.

    Raises ColorError unless mask is 2-D and width_px is a finite number above 0.

    Implementation: in-place AND (erosion) and OR (dilation) of shifted array windows over
    the offsets of _opening_offsets, on the mask's bounding box padded by m + 1 False
    pixels. Cost O(box pixels x offsets); there are about pi r^2 erosion offsets and
    pi r^2 dilation offsets per lattice type, 4 types. Measured on the Windows PC
    (2026-11-11, best of 3, all four of Roadie's color masks at N = 4, 792 x 836 px):
    0.009 s at w = 4, 0.082 s at w = 13.2, 0.18 s at w = 20. Alternatives measured on the
    same masks, identical results, not used: the same offsets as scipy footprints
    (binary_erosion and binary_dilation on the padded box) took 0.037 s at w = 4 and
    0.25 s at w = 13.2; an exact two-EDT form on the half-pixel grid (O(pixels) at any w)
    took about 0.23 s at every w from 2 to 20, so it would only pay above w of about 20.
    The tests compare this function with the footprint form on random masks.

    Not idempotent: the union of the kept pixels' squares is not itself open (a kept pixel
    near the boundary has parts outside every disk), so opening the result again can
    remove more pixels. See MAX_CLEAN_PASSES for how clean_regions contains this.
    """
    mask = np.asarray(mask)
    if mask.ndim != 2:
        raise ColorError(f"mask must be 2-D, got shape {mask.shape}")
    width_px = _finite_positive("width_px", width_px)
    mask = mask.astype(bool, copy=False)
    keep = np.zeros(mask.shape, bool)
    rows, cols = np.flatnonzero(mask.any(1)), np.flatnonzero(mask.any(0))
    if rows.size == 0:
        return keep
    offsets, m = _opening_offsets(width_px / 2)
    pad = m + 1
    i0, i1, j0, j1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    sub = np.pad(mask[i0:i1, j0:j1], pad, constant_values=False)
    hh, ww = sub.shape

    def window(di, dj):
        """Slices (target, source) with target[i, j] paired with source[i + di, j + dj]."""
        ys, ye = max(0, -di), min(hh, hh - di)
        xs, xe = max(0, -dj), min(ww, ww - dj)
        return ((slice(ys, ye), slice(xs, xe)),
                (slice(ys + di, ye + di), slice(xs + dj, xe + dj)))

    # In place, with no array allocated per offset. The pixels left out of a window lie in
    # the pad (|di|, |dj| <= m < pad), where sub, and so centres, are False: for the AND
    # they are already False, and for the OR their shifted value is False (beyond the
    # array). So this equals combining with fully shifted arrays.
    out = np.zeros_like(sub)
    for ero, dil in offsets:
        centres = sub.copy()
        for di, dj in ero:
            t, src = window(di, dj)
            centres[t] &= sub[src]
        if not centres.any():
            continue
        for di, dj in dil:
            t, src = window(di, dj)
            out[t] |= centres[src]
    keep[i0:i1, j0:j1] = (out & sub)[pad:-pad, pad:-pad]
    return keep


def _thin_step(labels: np.ndarray, limits: Limits,
               cache: dict | None = None) -> tuple[int, np.ndarray, bool]:
    """One thin step on labels (int32 (H, W), changed in place).

    For each color c, its non-thin pixels are open_mask(labels == c, min_width_px), the
    pixel sample of R1's opening of width min_width_px (pixels beyond the image edge
    count as not c). Every other labelled pixel is thin. It takes the color of the
    nearest non-thin labelled pixel of any color, by Euclidean distance. OUTSIDE pixels are never
    non-thin, so they neither assign nor get assigned. If no non-thin labelled pixel
    exists, nothing changes.

    Ties are broken here, not by scipy. For each color, scipy.ndimage.distance_transform_edt
    (return_indices) on the complement of its non-thin set gives a nearest pixel, and the
    squared distance to it is recomputed as an exact integer. Which of several equally
    near pixels EDT returns is deterministic for a scipy build but not specified by scipy;
    the squared distance to the color does not depend on that choice. A thin pixel takes
    the color at the least squared distance; on a tie, its own color if that is among the
    nearest, else the lowest palette index. So the result does not depend on EDT's tie
    choice, and a mirror-symmetric input gives a mirror-symmetric result.

    cache: optional dict, color -> (its mask, its core) from an earlier call with the same
    limits; a color whose mask is unchanged reuses its core (open_mask is a function of
    the mask alone), so the result is the same with or without it.

    Returns (labels changed, the thin mask, no_core).
    """
    inside = labels != OUTSIDE
    cores = []
    for c in np.unique(labels[inside]):          # ascending palette index
        mask_c = labels == c
        hit = cache.get(int(c)) if cache is not None else None
        if hit is not None and np.array_equal(hit[0], mask_c):
            core_c = hit[1]
        else:
            core_c = open_mask(mask_c, limits.min_width_px)
            if cache is not None:
                cache[int(c)] = (mask_c, core_c)
        if core_c.any():
            cores.append((int(c), core_c))
    core = np.zeros(labels.shape, bool)
    for _, core_c in cores:
        core |= core_c
    thin = inside & ~core
    if not thin.any():
        return 0, thin, False
    if not cores:
        return 0, thin, True
    ty, tx = np.nonzero(thin)
    own = labels[ty, tx].astype(np.int64)
    far = np.iinfo(np.int64).max
    best = np.full(len(ty), far, np.int64)
    best_c = own.copy()
    own_d2 = np.full(len(ty), far, np.int64)
    for c, core_c in cores:
        iy, ix = ndimage.distance_transform_edt(~core_c, return_distances=False,
                                                return_indices=True)
        d2 = ((iy[ty, tx].astype(np.int64) - ty) ** 2
              + (ix[ty, tx].astype(np.int64) - tx) ** 2)
        closer = d2 < best                       # strict: the lowest index wins a tie
        best = np.where(closer, d2, best)
        best_c = np.where(closer, c, best_c)
        own_d2 = np.where(own == c, d2, own_d2)
    new = np.where(own_d2 == best, own, best_c)
    n = int((new != own).sum())
    labels[ty, tx] = new
    return n, thin, False


def _merge_step(labels: np.ndarray, min_area: float, k: int) -> tuple[int, int, int, int]:
    """Merge small pieces in labels (int32 (H, W), values OUTSIDE or below k, changed in
    place), one at a time.

    A piece is a 4-connected set of pixels of one color. While a piece of area below
    min_area that has a color neighbour exists, the first by (area, lowest flat pixel
    index) is merged into the color it shares the most 4-neighbour pixel edges with
    (OUTSIDE excluded), ties to the lowest palette index. A piece with no color neighbour
    is kept: its 4-neighbours are all OUTSIDE or beyond the edge, which no merge changes,
    so it never gets one.

    The piece list is updated incrementally rather than recomputed after each merge, with
    the same result: when piece P of color c merges into color d, the new piece of d is P
    together with every piece of d that touches P (they connect through P; nothing else
    joins them), and every other piece is unchanged, since P was a whole piece of c and
    no other pixel changed color. A union-find over the initial pieces records this, with
    each root's area and lowest flat index; a heap keyed by (area, lowest index) gives the
    next piece, stale entries skipped. Keys are unique, since pieces never share a pixel.
    The chosen piece's neighbours are read from the current labels, so they are exact.

    Returns (pieces merged, pixels changed, pieces kept, their total area).
    """
    h, w = labels.shape
    flat = labels.reshape(-1)          # a view: writes go to labels
    pid = np.full(flat.size, -1, np.int64)
    area: list[int] = []
    first: list[int] = []
    colour: list[int] = []
    pixels: dict[int, np.ndarray] = {}  # flat indices, for small roots only
    for c in range(k):
        pieces, n = ndimage.label(labels == c, structure=_FOUR)
        if n == 0:
            continue
        pf = pieces.reshape(-1)
        idx = np.flatnonzero(pf)       # ascending
        ids = pf[idx].astype(np.int64) - 1
        base = len(area)
        pid[idx] = ids + base
        counts = np.bincount(ids, minlength=n)
        _, first_at = np.unique(ids, return_index=True)   # idx ascending: the lowest index
        area.extend(counts.tolist())
        first.extend(idx[first_at].tolist())
        colour.extend([c] * n)
        small = np.flatnonzero(counts < min_area)
        if small.size:
            order = np.argsort(ids, kind="stable")      # within a piece, still ascending
            starts = np.concatenate([[0], np.cumsum(counts)])
            for j in small.tolist():                    # Python loops over small pieces only
                pixels[base + j] = idx[order[starts[j]:starts[j + 1]]]
    parent = list(range(len(area)))

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    heap = [(area[r], first[r], r) for r in pixels]
    heapq.heapify(heap)
    merged = changed = kept = kept_area = 0
    while heap:
        a, f, r = heapq.heappop(heap)
        if parent[r] != r or r not in pixels or area[r] != a:
            continue                    # stale
        px = pixels.pop(r)
        c = colour[r]
        y, x = np.divmod(px, w)
        nb = np.concatenate([px[y > 0] - w, px[y < h - 1] + w,
                             px[x > 0] - 1, px[x < w - 1] + 1])
        nl = flat[nb]
        sel = (nl != OUTSIDE) & (nl != c)
        if not sel.any():
            kept += 1
            kept_area += a
            continue
        d = int(np.argmax(np.bincount(nl[sel], minlength=k)))   # lowest index on ties
        joined = sorted({find(int(p)) for p in pid[nb[nl == d]]})
        flat[px] = d
        merged += 1
        changed += len(px)
        new_area = a + sum(area[j] for j in joined)
        new_first = min([f] + [first[j] for j in joined])
        for j in joined:
            parent[j] = r
        area[r], first[r], colour[r] = new_area, new_first, d
        if new_area < min_area:         # every part was small, so each has its pixels
            pixels[r] = np.concatenate([px] + [pixels.pop(j) for j in joined])
            heapq.heappush(heap, (new_area, new_first, r))
        else:
            for j in joined:
                pixels.pop(j, None)
    return merged, changed, kept, kept_area


def clean_regions(q: Quantized, limits: Limits) -> tuple[Quantized, CleanupLog]:
    """Clean q's label map to printable regions (Decision 4), deterministically.

    Each pass runs two steps. Passes repeat until a pass leaves the labels as they were
    (a fixed point), or for at most MAX_CLEAN_PASSES:
    a. Thin parts (_thin_step): per color, the pixels that an opening of width
       min_width_px removes (open_mask) are thin; each takes the color of the nearest
       non-thin labelled pixel of any color (ties: own color, then lowest index). A thin
       spur whose nearest non-thin pixel has its own color therefore keeps it.
    b. Small pieces (_merge_step): 4-connected pieces of one color with area below
       min_area_px are merged one at a time, smallest first (then lowest flat pixel
       index), each into the color it shares the longest 4-neighbour boundary with
       (OUTSIDE excluded), ties to the lowest palette index of q. A piece with no color
       neighbour is kept and reported.
    The palette colors are not changed; only labels move. The result is built by
    from_labels from the new labels and q.rgb, so a color left with no pixel is dropped
    (and counted in dropped) and the palette is re-sorted by its final areas. q's
    iterations, converged, n_requested and n_distinct_colors are passed through.

    What is guaranteed (unless cap_hit): the result is a fixed point of a whole pass, so
    no piece below min_area_px has a color neighbour, and one more thin step followed by a
    merge step changes no label. It does not guarantee that no pixel is thin: thin pixels
    can remain where their own color is nearest (convex corners and staircase edges at the
    outline, spurs into the outside) or where the merge step returns them; they are
    counted in thin_pixels_left and thin_returned. Step 2 geometry applies R1's polygon
    opening to each region anyway.

    Cost per pass, for an H x W map with k colors and opening width w px: the thin step
    runs open_mask on each color whose mask changed since the last pass (O(HW w^2)
    each; an unchanged color reuses its earlier result) and one exact EDT per color
    (O(HW) each); the merge step labels each color (O(HW)) and then works only on the
    small pieces (a heap and a union-find; each merge reads the piece's own pixels). The
    number of passes is not bounded except by MAX_CLEAN_PASSES. Measured on the Windows
    PC (2026-11-11, best of 3; N = 4, 60 mm): Roadie (792 x 836, w = 3.99 px, 5 passes)
    0.36 s; Oddie (1013 x 1024, w = 5.35 px, 4 passes) 0.69 s; a 2000 x 2000 synthetic map
    (a smoothed random image quantized to 4 colors inside a disk of radius 990 px; 60 mm
    wide, so w = 13.2 px; 10 passes) 27.9 s, of which most is open_mask and the EDTs.
    The previous version (git f641506) gave the same labels in 0.36 s, 0.69 s and 87.1 s.
    """
    if not isinstance(q, Quantized):
        raise ColorError(f"q must be a Quantized, got {type(q).__name__}")
    if not isinstance(limits, Limits):
        raise ColorError(f"limits must be a Limits, got {type(limits).__name__}")
    if q.labels.ndim != 2:
        raise ColorError(f"clean_regions needs a 2-D label map, got shape {q.labels.shape}")
    k = len(q.hex)
    labels = np.array(q.labels, np.int32)       # a writable copy
    thin_total = merged_total = kept = kept_area = thin_left = returned = passes = 0
    no_core = False
    cap_hit = True
    cache: dict = {}
    for passes in range(1, MAX_CLEAN_PASSES + 1):
        start = labels.copy()
        n_thin, thin, nc = _thin_step(labels, limits, cache)
        n_merged, _, kept, kept_area = _merge_step(labels, limits.min_area_px, k)
        no_core |= nc
        thin_left = int((thin & (labels == start)).sum())
        if np.array_equal(labels, start):       # a fixed point of the whole pass
            returned, cap_hit = n_thin, False
            break
        thin_total += n_thin
        merged_total += n_merged
    out = from_labels(labels, q.rgb, iterations=q.iterations, converged=q.converged,
                      n_requested=q.n_requested, n_distinct_colors=q.n_distinct_colors,
                      dropped=q.dropped)
    inside = q.labels != OUTSIDE
    before = q.labels[inside].astype(np.int64)
    after = labels[inside].astype(np.int64)
    diff = before != after
    pair = np.bincount(before[diff] * k + after[diff], minlength=k * k)
    moved = sorted(((q.hex[i // k], q.hex[i % k], int(pair[i])) for i in np.flatnonzero(pair)),
                   key=lambda t: (-t[2], t[0], t[1]))
    final = np.bincount(after, minlength=k)
    log = CleanupLog(
        passes=passes, cap_hit=cap_hit, thin_pixels_reassigned=thin_total,
        thin_pixels_left=thin_left, thin_returned=returned, no_core=no_core,
        pieces_merged=merged_total,
        pixels_changed=int(diff.sum()), moved=tuple(moved),
        dropped_hex=tuple(q.hex[i] for i in range(k) if final[i] == 0),
        kept_pieces=kept, kept_area_px=kept_area, limits=limits)
    return out, log


def changed_mask(before: Quantized, after: Quantized) -> np.ndarray:
    """Bool (H, W): the pixels whose color differs between before and after (such as the
    input and output of clean_regions). Colors are compared by hex code, since after's
    palette may be re-sorted; OUTSIDE pixels are never changed. Raises ColorError unless
    both are Quantized with the same label shape and the same OUTSIDE pixels.
    """
    if not isinstance(before, Quantized) or not isinstance(after, Quantized):
        raise ColorError("changed_mask needs two Quantized results")
    if before.labels.shape != after.labels.shape:
        raise ColorError(f"label shapes differ: {before.labels.shape} and "
                         f"{after.labels.shape}")
    outside = before.labels == OUTSIDE
    if not np.array_equal(outside, after.labels == OUTSIDE):
        raise ColorError("the two label maps have different OUTSIDE pixels")
    hb = np.array(list(before.hex) + [""], dtype=object)
    ha = np.array(list(after.hex) + [""], dtype=object)
    a = hb[np.where(outside, len(before.hex), before.labels)]
    b = ha[np.where(outside, len(after.hex), after.labels)]
    return a != b


# --- Extraction: outline handling and the owner's merges (plan Task 7b) --------------------

# Task 7b only: the outline handling is a seam that Task 7c fills in. This method name says
# that no outline handling is done, so a plan made before 7c can never share an id with
# one made after it.
OUTLINE_METHOD = "outline-not-implemented/0"
OUTLINE_PLACEHOLDER_NOTE = ("outline detection is not implemented yet (plan Task 7c): auto "
                            "finds no outline family, so the outline colors stay as "
                            "ordinary colors")


def index_map(before: Quantized, after: Quantized) -> tuple[int | None, ...]:
    """For each palette index of before, its index in after, or None if after lacks it.

    Matched by the palette color (rgb), which steps such as merges and clean_regions keep
    unchanged while they move labels and re-sort the palette. Raises ColorError if before's
    palette has a color twice (quantize never gives that: a repeated rounded color gets no
    pixel in the nearest reassignment, so it is dropped).
    """
    if not isinstance(before, Quantized) or not isinstance(after, Quantized):
        raise ColorError("index_map needs two Quantized results")
    if len(set(before.hex)) != len(before.hex):
        raise ColorError("the palette has a color twice, so indices cannot be matched by color")
    where = {h: i for i, h in enumerate(after.hex)}
    return tuple(where.get(h) for h in before.hex)


def merge_problem(merges) -> str | None:
    """What is wrong with a list of (from, into) index pairs, or None.

    Only the pairs' structure: from != into, each from at most once, and no into that is
    also a from (no chains). Whether the indices exist is the caller's check.
    """
    froms = [a for a, _ in merges]
    for a, b in merges:
        if a == b:
            return f"[{a}, {b}] merges a color into itself"
    for a in froms:
        if froms.count(a) > 1:
            return f"color {a} is merged more than once"
    for a, b in merges:
        if b in froms:
            return (f"[{a}, {b}] merges into color {b}, which is itself merged away (no "
                    "chains: merge each color straight into its final color)")
    return None


def apply_merges(q: Quantized, merges) -> Quantized:
    """The owner's explicit merges: every pixel of each `from` color takes the `into` color.

    merges: a sequence of (from, into) pairs of q's palette indices (ints, not bool). The
    pairs must pass merge_problem (no self-merge, each from once, no chains), so the
    result does not depend on their order. The palette colors are not changed: the `into`
    color keeps its rgb, and each `from` color is left with no pixel, so from_labels
    removes it (and counts it in `dropped`) and re-sorts the palette by the new areas.
    index_map(q, result) gives each color's new index (None for the merged-away ones). q's
    iterations, converged, n_requested and n_distinct_colors are passed through. With no
    pairs the labels are unchanged (the result is still a new Quantized).
    Raises ColorError on a bad pair.
    """
    if not isinstance(q, Quantized):
        raise ColorError(f"q must be a Quantized, got {type(q).__name__}")
    k = len(q.hex)
    pairs = []
    for pair in merges:
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                or not all(isinstance(i, (int, np.integer)) and not isinstance(i, bool)
                           for i in pair)):
            raise ColorError(f"a merge is a pair of color indices (from, into), got {pair!r}")
        a, b = (int(i) for i in pair)
        if not (0 <= a < k and 0 <= b < k):
            raise ColorError(f"merge {[a, b]}: indices must be 0 to {k - 1}")
        pairs.append((a, b))
    problem = merge_problem(pairs)
    if problem:
        raise ColorError(f"merge: {problem}")
    remap = np.arange(k, dtype=np.int64)
    for a, b in pairs:
        remap[a] = b
    inside = q.labels != OUTSIDE
    labels = np.full(q.labels.shape, OUTSIDE, np.int64)
    labels[inside] = remap[q.labels[inside]]
    return from_labels(labels, q.rgb, iterations=q.iterations, converged=q.converged,
                       n_requested=q.n_requested, n_distinct_colors=q.n_distinct_colors,
                       dropped=q.dropped)


@dataclass(frozen=True)
class OutlineResult:
    """What handle_outlines did.

    family: the outline family, as extraction indices (q's indices), ascending.
    found_by: "none" (outline_color none), "auto" (detection) or "config" (a list).
    method: OUTLINE_METHOD. note: a sentence for the record and the CLI, or None.
    """

    family: tuple[int, ...]
    found_by: str
    method: str
    note: str | None


def _detect_outline_family_placeholder(q: Quantized) -> tuple[int, ...]:
    """PLACEHOLDER for plan Task 7c, which replaces it with the thinness rule
    (color.outline.thin_share). Until then `auto` finds no outline family."""
    return ()


def handle_outlines(q: Quantized, *, outline_color, outlines: str
                    ) -> tuple[Quantized, OutlineResult]:
    """The outline step between quantize and the merges: the seam Task 7c fills in.

    q: the extracted colors (quantize's result). outline_color: "auto", "none" or a list of
    extraction indices; outlines: "drop" or "keep". Returns the colors after outline
    handling and an OutlineResult.

    Task 7b: no outline handling is implemented. "none" and "auto" (through
    _detect_outline_family_placeholder, which finds nothing) return q itself with an empty
    family; an explicit list is refused with ColorError, because acting on it is Task 7c.
    """
    if outlines not in ("drop", "keep"):
        raise ColorError(f"outlines must be drop or keep, got {outlines!r}")
    if outline_color == "none":
        return q, OutlineResult(family=(), found_by="none", method=OUTLINE_METHOD, note=None)
    if outline_color == "auto":
        family = _detect_outline_family_placeholder(q)
        return q, OutlineResult(family=family, found_by="auto", method=OUTLINE_METHOD,
                                note=OUTLINE_PLACEHOLDER_NOTE)
    raise ColorError("outline_color as a list of indices is not implemented yet (plan Task "
                     "7c); use auto or none")

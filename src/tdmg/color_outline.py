"""The outline family and the shade-pair flags of `tdmg colors`
(docs/plans/2026-11-11-color-palette.md, Task 7c). Pure functions on tdmg.color's Quantized,
with no I/O.

- detect_outline_family: the colors that are mostly thin lines (the thinness rule).
- handle_outlines: drops the family (thin strokes take the nearest other color, wide areas
  the darkest member's color) and, under `keep`, returns the band that redraws the
  drawing's own lines at one width (stroke_band), which tdmg.color_plan paints after the
  merges (paint_band).
- shade_pairs: flags likely shade pairs (no labels change; reported, never applied).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from tdmg.color import (
    OUTSIDE,
    ColorError,
    Limits,
    Quantized,
    d2_nearest,
    from_labels,
    open_mask,
)

# --- The outline family: detection, drop and keep (plan Task 7c) ---------------------------

# /2: `keep` redraws the drawing's own lines (the ridge of the family's thin strokes) at
# width W after the merges; /1 drew bands along color borders before the merges.
OUTLINE_METHOD = "outline-thin-share/2"
THIN_SHARE_RULE = "color.outline.thin_share"
KEEP_WIDTH_RULE = "color.outline.keep_width"
SHADE_METHOD = "shade-hue-chroma/1"
SHADE_HUE_RULE = "color.shade.max_hue_diff_deg"
SHADE_CHROMA_RULE = "color.shade.min_chroma"
# The units the code assumes; rule_value refuses a rule in another one.
OUTLINE_RULE_UNITS = {THIN_SHARE_RULE: "fraction", KEEP_WIDTH_RULE: "mm",
                      SHADE_HUE_RULE: "deg", SHADE_CHROMA_RULE: "cielab_chroma"}
KEEP_NO_EFFECT_NOTE = ("outlines: keep has no effect: no outline color (outline_color is "
                       "none, or auto found none)")

# The 8 neighbour offsets (dy, dx) of the ridge test.
_EIGHT = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def rule_value(rules, rule_id: str) -> float:
    """A Task 7c rule's default as a float, after checking that it is in the unit the code
    uses (OUTLINE_RULE_UNITS). Raises ColorError if it is missing, in another unit, or not
    finite."""
    if rule_id not in rules:
        raise ColorError(f"rule {rule_id} is not in the rules registry")
    rule = rules[rule_id]
    if rule.unit != OUTLINE_RULE_UNITS[rule_id]:
        raise ColorError(f"{rule_id} must be in {OUTLINE_RULE_UNITS[rule_id]!r}, got "
                         f"{rule.unit!r}")
    value = float(rule.default)
    if not math.isfinite(value):
        raise ColorError(f"{rule_id} must be finite, got {value}")
    return value


def _opened(q: Quantized, limits: Limits) -> tuple[tuple[float, ...], list[np.ndarray]]:
    """Each color's thinness and the pixels its own opening keeps (open_mask of its mask
    at limits.min_width_px)."""
    thin, kept = [], []
    for c in range(len(q.hex)):
        m = q.labels == c
        k = open_mask(m, limits.min_width_px)
        kept.append(k)
        n = int(m.sum())
        thin.append(1.0 - int(k[m].sum()) / n if n else 0.0)
    return tuple(thin), kept


def _check_thin_share(thin_share) -> float:
    if (isinstance(thin_share, bool) or not isinstance(thin_share, (int, float, np.floating))
            or not 0.0 <= float(thin_share) <= 1.0):
        raise ColorError(f"thin_share must be a number from 0 to 1, got {thin_share!r}")
    return float(thin_share)


def _family_by_thinness(thin, thin_share: float) -> tuple[int, ...]:
    """The indices whose thinness is above thin_share (strict), ascending."""
    return tuple(i for i, t in enumerate(thin) if t > thin_share)


def detect_outline_family(q: Quantized, limits: Limits, thin_share: float
                          ) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """The outline family by the thinness rule (color.outline.thin_share), and every
    color's thinness.

    A color's thinness is the share of its pixels that its own opening does not keep:
    1 - |open_mask(labels == c, limits.min_width_px) and (labels == c)| / |labels == c|,
    the opening of R1 (flat.sliver.opening_width) at the plan's scale. The family is every
    color with thinness > thin_share (strict), ascending. Measured in Task 7a on the
    owner's images: outline-family colors 66-100%, other colors at most 10%. Raises
    ColorError unless thin_share is a number from 0 to 1.
    """
    t = _check_thin_share(thin_share)
    thin, _ = _opened(q, limits)
    return _family_by_thinness(thin, t), thin


def stroke_ridge(strokes: np.ndarray) -> np.ndarray:
    """The centre line of the drawn strokes (bool, the shape of strokes): their ridge.

    strokes: bool (H, W), the pixels the artist drew as lines. For each stroke pixel p,
    d2(p) is the exact squared Euclidean distance between pixel centres from p to the
    nearest pixel that is not a stroke pixel, counting the one-pixel frame beyond the image
    as not a stroke (d2_nearest on the padded complement). p is on the ridge when
    d2(p) >= d2(q) for each of its 8 neighbours q that is a stroke pixel (a local maximum;
    ties all count, so a stroke 2 px wide has a ridge 2 px wide, one 3 px wide a ridge
    1 px wide). An isolated stroke pixel is on the ridge.
    """
    strokes = np.asarray(strokes, bool)
    ridge = np.zeros(strokes.shape, bool)
    if not strokes.any():
        return ridge
    h, w = strokes.shape
    ty, tx = np.nonzero(strokes)
    d2 = np.full((h + 2, w + 2), -1, np.int64)        # -1: not a stroke pixel
    d2[ty + 1, tx + 1] = d2_nearest(~np.pad(strokes, 1, constant_values=False), ty + 1, tx + 1)
    here = d2[ty + 1, tx + 1]
    ok = np.ones(len(ty), bool)
    for dy, dx in _EIGHT:
        ok &= here >= d2[ty + 1 + dy, tx + 1 + dx]
    ridge[ty[ok], tx[ok]] = True
    return ridge


def stroke_band(strokes: np.ndarray, inside: np.ndarray, width_px: float) -> np.ndarray:
    """The kept outline band (bool, the shape of inside): `outlines: keep`.

    strokes: bool (H, W), the outline family's thin pixels (the lines as drawn, before the
    drop). inside: bool (H, W), the labelled pixels. width_px: the band width W in pixels.

    The drawn lines' centre line is found at half-pixel resolution: each stroke pixel is
    split into 2 x 2 half pixels and stroke_ridge is taken on that grid. A straight stroke
    of any width s is 2s half pixels across, so its ridge is the two half pixels at its
    middle, a quarter pixel either side of the true centre line. Distances are Euclidean,
    from pixel centres to ridge half-pixel centres, computed exactly in quarter-pixel
    integer units (a KD-tree finds the nearest ridge point; its squared distance is then
    recomputed as an integer). An inside pixel is in the band when
    - its centre is within W/2 - 1/4 of a ridge point: on a straight stroke these are the
      pixel centres within W/2 of the drawn line's centre, so the band is floor(W) or
      floor(W) + 1 px across (within one pixel of W) and centred on the drawn line,
      whatever the drawn width; or
    - d_out - 1/2 <= W, where d_out is the distance between pixel centres to the nearest
      pixel that is not inside (an OUTSIDE pixel or the one-pixel frame beyond the image):
      the pixels whose centre is within W of the outer edge, inside it (floor(W + 1/2) px
      on a straight edge). Holes (OUTSIDE pixels inside the subject) count as outside.
    Where lines meet or curve, the same rule is applied; the width there is not claimed to
    be exactly W.
    """
    inside = np.asarray(inside, bool)
    band = np.zeros(inside.shape, bool)
    if not inside.any():
        return band
    ty, tx = np.nonzero(inside)
    strokes = np.asarray(strokes, bool) & inside
    ridge = stroke_ridge(np.repeat(np.repeat(strokes, 2, axis=0), 2, axis=1))
    ry, rx = np.nonzero(ridge)
    if len(ry):
        pts = np.stack([2 * ry + 1, 2 * rx + 1], axis=1).astype(np.int64)  # quarter px
        centres = np.stack([4 * ty + 2, 4 * tx + 2], axis=1).astype(np.int64)
        r = 2.0 * width_px - 1.0                 # W/2 - 1/4 px, in quarter pixels
        dist, idx = cKDTree(pts).query(centres, distance_upper_bound=r + 1.0)
        near = np.isfinite(dist)
        d2 = np.zeros(len(ty), np.int64)
        d2[near] = ((pts[idx[near]] - centres[near]) ** 2).sum(axis=1)
        sel = near & (d2 <= r * r)
        band[ty[sel], tx[sel]] = True
    padded = np.pad(inside, 1, constant_values=False)
    sel = d2_nearest(~padded, ty + 1, tx + 1) <= (width_px + 0.5) ** 2
    band[ty[sel], tx[sel]] = True
    return band


@dataclass(frozen=True, eq=False)
class OutlineResult:
    """What handle_outlines did. eq=False: band is an array.

    family: the outline family, as extraction indices (q's indices), ascending.
    core: the darkest family member (lowest L*, ties to the lowest index), or None when
      the family is empty. Its color is the one the family's wide areas (and the kept
      band) take.
    thinness: every extracted color's thinness (detect_outline_family), reported whatever
      outline_color is.
    found_by: "none" (outline_color none), "auto" (detection) or "config" (a list).
    method: OUTLINE_METHOD.
    remap: for each extraction index, its index in the returned colors, or None if the
      outline handling removed it (only family members are ever removed).
    thresholds: ((rule id, value), ...) for the rules that decided the result: the thin
      share under auto, and the keep width under keep with a family.
    keep_width_mm, keep_width_px: the band width W under keep with a family, else None.
    band: under keep with a family, the read-only bool mask of the band (stroke_band), which
      tdmg.color_plan paints in core_rgb after the merges; else None.
    core_rgb: the core's color (uint8 (3,)), or None.
    notes: sentences for the record and the CLI (possibly none).
    """

    family: tuple[int, ...]
    core: int | None
    thinness: tuple[float, ...]
    found_by: str
    method: str
    remap: tuple[int | None, ...]
    thresholds: tuple[tuple[str, float], ...]
    keep_width_mm: float | None
    keep_width_px: float | None
    band: np.ndarray | None
    core_rgb: np.ndarray | None
    notes: tuple[str, ...]


def _family_from_list(outline_color, k: int) -> tuple[int, ...]:
    if not isinstance(outline_color, (list, tuple)) or not outline_color:
        raise ColorError(f"outline_color must be auto, none or a non-empty list of "
                         f"extraction indices, got {outline_color!r}")
    for i in outline_color:
        if isinstance(i, bool) or not isinstance(i, (int, np.integer)):
            raise ColorError(f"outline_color must list extraction indices, got {i!r}")
        if not 0 <= int(i) < k:
            raise ColorError(f"outline_color {int(i)} is not an index of the {k} extracted "
                             "colors")
    if len({int(i) for i in outline_color}) != len(outline_color):
        raise ColorError("outline_color lists an index more than once")
    return tuple(sorted(int(i) for i in outline_color))


def outline_core(family, lab) -> int | None:
    """The darkest family member: the lowest L* (lab[i][0]), ties to the lowest index; None
    for an empty family."""
    return min(family, key=lambda i: (float(lab[i][0]), i)) if family else None


def handle_outlines(q: Quantized, *, outline_color, outlines: str, limits: Limits,
                    rules) -> tuple[Quantized, OutlineResult]:
    """The outline step between quantize and the merges (plan Task 7c).

    q: the extracted colors (quantize's result). outline_color: "auto", "none" or a list of
    extraction indices; outlines: "drop" or "keep"; limits: printable_limits_px at the
    plan's scale; rules: the registry (the thin share is read under auto, the keep width
    under keep with a family). Returns the colors after the drop and an OutlineResult.

    1. The family: none -> empty; auto -> the thinness rule (color.outline.thin_share);
       a list -> those indices (refused unless each is an index of q, once). Every color's
       thinness is computed either way (once).
    2. With an empty family nothing changes: q itself is returned with the identity remap
       (under keep, a note says it has no effect).
    3. The core is outline_core: the family member with the lowest L* (ties: lowest
       index).
    4. Drop (always). For each family member f, its thin pixels are its pixels that its OWN
       opening does not keep (open_mask(labels == f, min_width_px)); each member
       separately, since a fringe tone and the line core are each thin even where together
       they are wide. Each thin pixel takes the color of the nearest pixel of a non-family
       color (exact squared distance between pixel centres; ties to the lowest index of q,
       as in the cleanup's thin step). The family's other pixels (kept by their member's
       opening: wide areas such as a pupil) take the core's color. Refused if every color
       is in the family.
    5. Keep: the band that redraws the drawing's lines, stroke_band(the family's thin
       pixels, the labelled pixels, W) with W = color.outline.keep_width /
       limits.mm_per_px, is returned in the OutlineResult, not painted here:
       tdmg.color_plan paints it (paint_band) after the owner's merges, so a merge never
       leaves band pixels inside the merged color. The keep width must exceed the
       cleanup's opening width (flat.sliver.opening_width), or cleanup would remove the
       band.
    The palette colors are not changed; the result is built by from_labels from the new
    labels and q.rgb, so family members left with no pixel are removed (remap None).
    """
    if not isinstance(q, Quantized):
        raise ColorError(f"q must be a Quantized, got {type(q).__name__}")
    if outlines not in ("drop", "keep"):
        raise ColorError(f"outlines must be drop or keep, got {outlines!r}")
    if not isinstance(limits, Limits):
        raise ColorError(f"limits must be a Limits, got {type(limits).__name__}")
    k = len(q.hex)
    if isinstance(outline_color, str) and outline_color not in ("auto", "none"):
        raise ColorError(f"outline_color must be auto, none or a non-empty list of "
                         f"extraction indices, got {outline_color!r}")
    thin, kept = _opened(q, limits)
    thresholds: list[tuple[str, float]] = []
    if outline_color == "none":
        family, found_by = (), "none"
    elif outline_color == "auto":
        t = _check_thin_share(rule_value(rules, THIN_SHARE_RULE))
        family, found_by = _family_by_thinness(thin, t), "auto"
        thresholds.append((THIN_SHARE_RULE, t))
    else:
        family, found_by = _family_from_list(outline_color, k), "config"
    identity = tuple(range(k))
    if not family:
        notes = (KEEP_NO_EFFECT_NOTE,) if outlines == "keep" else ()
        return q, OutlineResult(family=(), core=None, thinness=thin, found_by=found_by,
                                method=OUTLINE_METHOD, remap=identity,
                                thresholds=tuple(thresholds), keep_width_mm=None,
                                keep_width_px=None, band=None, core_rgb=None, notes=notes)
    if len(family) == k:
        raise ColorError("every extracted color is in the outline family, so no color is "
                         "left for its pixels; set outline_color to none or a shorter list")
    core = outline_core(family, q.lab)
    width_mm = width_px = None
    if outlines == "keep":
        width_mm = rule_value(rules, KEEP_WIDTH_RULE)
        if not width_mm > limits.opening_width_mm:
            raise ColorError(f"{KEEP_WIDTH_RULE} ({width_mm} mm) must be wider than "
                             f"{limits.opening_rule} ({limits.opening_width_mm} mm), or "
                             "cleanup removes the band")
        width_px = width_mm / limits.mm_per_px
        thresholds.append((KEEP_WIDTH_RULE, width_mm))

    labels = np.array(q.labels, np.int64)
    thin_px = np.zeros(labels.shape, bool)
    wide_px = np.zeros(labels.shape, bool)
    for f in family:
        m = q.labels == f
        thin_px |= m & ~kept[f]
        wide_px |= m & kept[f]
    ty, tx = np.nonzero(thin_px)
    best = np.full(len(ty), np.iinfo(np.int64).max, np.int64)
    best_c = np.full(len(ty), OUTSIDE, np.int64)
    for c in range(k):                           # ascending: the lowest index wins a tie
        if c in family:
            continue
        d2 = d2_nearest(q.labels == c, ty, tx)
        closer = d2 < best
        best = np.where(closer, d2, best)
        best_c = np.where(closer, c, best_c)
    labels[ty, tx] = best_c
    labels[wide_px] = core
    hx = q.hex[core]
    notes = [(f"outlines: drop: {len(ty)} thin pixel(s) of the outline family took the "
              f"nearest other color; {int(wide_px.sum())} wide pixel(s) took the core "
              f"{hx}")]
    band = None
    if outlines == "keep":
        band = stroke_band(thin_px, q.labels != OUTSIDE, width_px)
        band.flags.writeable = False
        notes.append(f"outlines: keep: a {width_mm} mm ({width_px:.2f} px) band in the "
                     f"core {hx} redraws the drawn lines and the outer edge, painted after "
                     f"the merges ({int(band.sum())} px)")
    out = from_labels(labels, q.rgb, iterations=q.iterations, converged=q.converged,
                      n_requested=q.n_requested, n_distinct_colors=q.n_distinct_colors,
                      dropped=q.dropped)
    core_rgb = np.array(q.rgb[core])
    core_rgb.flags.writeable = False
    return out, OutlineResult(family=family, core=core, thinness=thin, found_by=found_by,
                              method=OUTLINE_METHOD, remap=out.remap,
                              thresholds=tuple(thresholds), keep_width_mm=width_mm,
                              keep_width_px=width_px, band=band, core_rgb=core_rgb,
                              notes=tuple(notes))


def paint_band(q: Quantized, band: np.ndarray, core_rgb) -> tuple[Quantized, int]:
    """q with the band's labelled pixels in the core's color: the last step of `keep`,
    after the merges. Returns (the result, the index in q.rgb + [core_rgb] that the core's
    color has before from_labels re-sorts: an existing palette entry with the same rgb, else
    the appended one). The result's remap has one entry per row of that extended palette.
    """
    rgb = np.asarray(q.rgb)
    core_rgb = np.asarray(core_rgb, np.uint8)
    same = np.flatnonzero((rgb == core_rgb).all(axis=1))
    if same.size:
        ci, pal = int(same[0]), rgb
    else:
        ci, pal = len(rgb), np.vstack([rgb, core_rgb[None]])
    labels = np.array(q.labels, np.int64)
    labels[np.asarray(band, bool) & (labels != OUTSIDE)] = ci
    out = from_labels(labels, pal, iterations=q.iterations, converged=q.converged,
                      n_requested=q.n_requested, n_distinct_colors=q.n_distinct_colors,
                      dropped=q.dropped - (len(pal) - len(rgb)))
    return out, ci


# --- Shade pairs (plan Task 7c): flagged for the owner, never applied ----------------------

@dataclass(frozen=True)
class ShadePair:
    """A likely shade pair: extraction indices i < j, their hex codes, the shorter hue
    difference dh_deg (degrees), their CIELAB chromas, and dl = L*_j - L*_i. merge is the
    suggested (from, into): the later index (no larger extracted area) into the earlier."""

    i: int
    j: int
    hex_i: str
    hex_j: str
    dh_deg: float
    chroma_i: float
    chroma_j: float
    dl: float

    @property
    def merge(self) -> tuple[int, int]:
        return (self.j, self.i)


def shade_pairs(lab, hexes, candidates, max_hue_diff_deg: float, min_chroma: float
                ) -> tuple[ShadePair, ...]:
    """Pairs of candidate colors that look like two shades of one color (SHADE_METHOD). It
    only flags pairs (no labels change); the owner decides on merges.

    lab: per extraction index, (L*, a*, b*) floats; hexes: per extraction index;
    candidates: the extraction indices to compare (tdmg.color_plan passes the colors left
    after the outline step and the merges, without the core). Computed with Python floats
    (math), so the result can be recomputed from the record's Lab values:
    C* = hypot(a*, b*); h = degrees(atan2(b*, a*)) mod 360; dh is the shorter way round,
    min(|h_i - h_j|, 360 - |h_i - h_j|). A pair (i < j) is flagged when
    dh < max_hue_diff_deg and both C* > min_chroma (all strict). Ordered by (i, j).
    """
    cand = sorted({int(c) for c in candidates})
    info = {}
    for c in cand:
        L, a, b = (float(v) for v in lab[c])
        info[c] = (L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360.0)
    out = []
    for n, i in enumerate(cand):
        for j in cand[n + 1:]:
            li, ci, hi = info[i]
            lj, cj, hj = info[j]
            d = abs(hi - hj)
            dh = min(d, 360.0 - d)
            if dh < max_hue_diff_deg and ci > min_chroma and cj > min_chroma:
                out.append(ShadePair(i=i, j=j, hex_i=hexes[i], hex_j=hexes[j], dh_deg=dh,
                                     chroma_i=ci, chroma_j=cj, dl=lj - li))
    return tuple(out)

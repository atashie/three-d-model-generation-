"""The outline family and the shade-pair flags of `tdmg colors`
(docs/plans/2026-11-11-color-palette.md, Task 7c). Pure functions on tdmg.color's Quantized,
with no I/O.

- detect_outline_family: the colors that are mostly thin lines (the thinness rule).
- handle_outlines: drops the family (thin strokes and shading tones take the nearest other
  color; only the core's wide areas several strokes wide, such as a pupil, keep the
  darkest member's color: wide_core_components) and, under `keep`, returns the band that
  redraws the drawing's own lines at one width (stroke_band, without the stroke specks),
  which tdmg.color_plan paints after the merges (paint_band).
- shade_pairs: flags likely shade pairs (no labels change; reported, never applied).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage
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

# /3 (Task 7e-b): the drop sends the non-core members' wide pixels (shading tones) to the
# nearest non-family color and keeps a core wide area only if it is at least
# color.outline.keep_area_width_ratio strokes wide; `keep` leaves out stroke specks below
# the island area, and its width comes from the outline_width_mm setting.
# /2: `keep` redraws the drawing's own lines (the ridge of the family's thin strokes) at
# width W after the merges; /1 drew bands along color borders before the merges.
OUTLINE_METHOD = "outline-thin-share/3"
THIN_SHARE_RULE = "color.outline.thin_share"
KEEP_WIDTH_RULE = "color.outline.keep_width"
KEEP_RATIO_RULE = "color.outline.keep_area_width_ratio"
SHADE_METHOD = "shade-hue-chroma/1"
SHADE_HUE_RULE = "color.shade.max_hue_diff_deg"
SHADE_CHROMA_RULE = "color.shade.min_chroma"
# The units the code assumes; rule_value refuses a rule in another one.
OUTLINE_RULE_UNITS = {THIN_SHARE_RULE: "fraction", KEEP_WIDTH_RULE: "mm",
                      KEEP_RATIO_RULE: "ratio", SHADE_HUE_RULE: "deg",
                      SHADE_CHROMA_RULE: "cielab_chroma"}
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


# The percentile of the ridge widths taken as the family's stroke width (stroke_width_px).
# Part of the definition of color.outline.keep_area_width_ratio: the statistic the 7e-a
# record measured (p90), not a separate threshold.
STROKE_WIDTH_PERCENTILE = 90


def _d2_to_outside(region: np.ndarray, ty: np.ndarray, tx: np.ndarray) -> np.ndarray:
    """For pixels (ty, tx) of region (bool (H, W)): the exact squared distance between
    pixel centres to the nearest pixel not in region, the one-pixel frame beyond the image
    counting as not in it (int64)."""
    return d2_nearest(~np.pad(np.asarray(region, bool), 1, constant_values=False),
                      ty + 1, tx + 1)


def stroke_width_px(strokes: np.ndarray) -> float | None:
    """The width of the drawn strokes in pixels, or None when there is no stroke pixel.

    strokes: bool (H, W), the outline family's thin pixels (S). For each pixel p of
    stroke_ridge(strokes): 2 x d(p), where d(p) is the Euclidean distance between pixel
    centres from p to the nearest pixel that is not a stroke pixel (the frame beyond the
    image counts as not a stroke). The result is numpy's percentile (its default, linear
    interpolation) STROKE_WIDTH_PERCENTILE of those values, the measure of the 7e-a
    record. A straight stroke n px wide reads n (n even: its two middle pixels are n/2
    from the nearest non-stroke centre) or n + 1 (n odd).
    """
    strokes = np.asarray(strokes, bool)
    ry, rx = np.nonzero(stroke_ridge(strokes))
    if not len(ry):
        return None
    widths = 2.0 * np.sqrt(_d2_to_outside(strokes, ry, rx).astype(np.float64))
    return float(np.percentile(widths, STROKE_WIDTH_PERCENTILE))


def inscribed_width_px(component: np.ndarray) -> float:
    """2 x the largest Euclidean distance between pixel centres from a pixel of component
    (bool (H, W), at least one True) to the nearest pixel not in it (the frame beyond the
    image counts as not in it): the 7e-a record's "inscr". A straight strip n px wide reads
    n or n + 1 (1 px reads 2), about the width of the widest disc inside, up to 1 px over.
    Computed on the component's bounding box padded by one pixel, which gives the same
    distances: a pixel beyond that box is no nearer than the pad pixel found by clamping
    its coordinates to the box."""
    ys, xs = np.nonzero(component)
    y0, x0 = int(ys.min()), int(xs.min())
    crop = np.asarray(component, bool)[y0:int(ys.max()) + 1, x0:int(xs.max()) + 1]
    return 2.0 * math.sqrt(int(_d2_to_outside(crop, ys - y0, xs - x0).max()))


@dataclass(frozen=True)
class WideComponent:
    """One 4-connected component of the core's wide pixels (wide_core_components).

    area_px: its pixel count. inscribed_px: inscribed_width_px. centroid: (row, column),
    the mean of its pixels' indices, to find it in the image. kept: whether it keeps the
    core's color (keeps_wide_area)."""

    area_px: int
    inscribed_px: float
    centroid: tuple[float, float]
    kept: bool


def keeps_wide_area(inscribed_px: float, stroke_px: float | None, ratio: float) -> bool:
    """The rule color.outline.keep_area_width_ratio: inscribed_px >= ratio x stroke_px,
    and never when the family has no stroke (stroke_px None)."""
    return stroke_px is not None and inscribed_px >= ratio * stroke_px


def wide_core_components(core_wide: np.ndarray, stroke_px: float | None, ratio: float
                         ) -> tuple[tuple[WideComponent, ...], np.ndarray]:
    """The 4-connected components of core_wide (bool (H, W): the core's pixels that its
    own opening keeps), largest first (ties: the one whose first pixel in row-major order
    comes first), each judged by keeps_wide_area(its inscribed width, stroke_px, ratio).
    Returns them and the bool mask of the kept components' pixels.

    Each component is measured on its own bounding box (inscribed_width_px pads that box
    with one outside pixel, which gives the same distances as the whole image, the frame
    beyond the image still counting as outside), so the work grows with the components'
    sizes, not with their number times the image."""
    core_wide = np.asarray(core_wide, bool)
    keep = np.zeros(core_wide.shape, bool)
    lab, n = ndimage.label(core_wide, structure=ndimage.generate_binary_structure(2, 1))
    if not n:
        return (), keep
    areas = np.bincount(lab.ravel(), minlength=n + 1)
    objects = ndimage.find_objects(lab)
    comps = []
    for li in sorted(range(1, n + 1), key=lambda i: (-int(areas[i]), i)):
        box = objects[li - 1]
        crop = lab[box] == li
        ys, xs = np.nonzero(crop)
        ins = inscribed_width_px(crop)
        kept = keeps_wide_area(ins, stroke_px, ratio)
        if kept:
            keep[box] |= crop
        comps.append(WideComponent(
            area_px=int(areas[li]), inscribed_px=ins,
            centroid=(float((ys + box[0].start).mean()), float((xs + box[1].start).mean())),
            kept=kept))
    return tuple(comps), keep


def stroke_specks(strokes: np.ndarray, min_area_px: float) -> tuple[np.ndarray, int]:
    """The stroke specks: the 8-connected components of strokes (bool (H, W)) with fewer
    than min_area_px pixels (strict), which are isolated specks, not drawn lines. Returns
    the bool mask of their pixels and their count. handle_outlines passes the cleanup's
    island area (Limits.min_area_px, from flat.island.min_square_side), so no new number
    is needed (7e-a: specks 0.221 mm2 or less, real strokes 2.35 mm2 or more, against an
    island area of 0.64 mm2)."""
    strokes = np.asarray(strokes, bool)
    lab, n = ndimage.label(strokes, structure=ndimage.generate_binary_structure(2, 2))
    if not n:
        return np.zeros(strokes.shape, bool), 0
    small = np.bincount(lab.ravel(), minlength=n + 1) < min_area_px
    small[0] = False
    return small[lab], int(small.sum())


def stroke_band(strokes: np.ndarray, inside: np.ndarray, width_px: float) -> np.ndarray:
    """The kept outline band (bool, the shape of inside): `outlines: keep`.

    strokes: bool (H, W), the outline family's thin pixels (the lines as drawn, before the
    drop); handle_outlines removes the stroke specks (stroke_specks) first, so they are
    not redrawn. inside: bool (H, W), the labelled pixels. width_px: the band width W in
    pixels.

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
    be exactly W. Strokes are taken as drawn, so a 1 px fringe tone of the family on one
    side of a line widens it on that side and moves the centre line about 0.5 px toward
    it (inside the "within one pixel" above). A speck left in strokes would also be
    redrawn, as a disc about W across; handle_outlines leaves specks out.
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
      the family is empty. Its color is the one the kept wide areas (and the kept band)
      take.
    thinness: every extracted color's thinness (detect_outline_family), reported whatever
      outline_color is.
    found_by: "none" (outline_color none), "auto" (detection) or "config" (a list).
    method: OUTLINE_METHOD.
    remap: for each extraction index, its index in the returned colors, or None if the
      outline handling removed it (only family members are ever removed).
    thresholds: ((rule id, value), ...) for the rules that decided the result: the thin
      share under auto, and the wide-area ratio (color.outline.keep_area_width_ratio)
      with a family. The band width is a setting (outline_width_mm), not listed here.
    stroke_width_px: the family's stroke width (stroke_width_px of its thin pixels), or
      None (no family, or no thin pixel).
    wide_components: the core's wide areas (wide_core_components), each with whether it
      kept the core's color; () without a family.
    keep_width_mm, keep_width_px: the band width W under keep with a family, else None.
    specks: under keep with a family, (count, pixels) of the stroke specks left out of the
      band (stroke_specks); else None.
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
    stroke_width_px: float | None
    wide_components: tuple[WideComponent, ...]
    keep_width_mm: float | None
    keep_width_px: float | None
    specks: tuple[int, int] | None
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


def check_outline_width(width_mm, opening_width_mm: float, opening_rule: str) -> float:
    """width_mm (the band width, outline_width_mm) as a float: a finite number (not a bool)
    wider than the cleanup's opening (opening_width_mm, from opening_rule), since cleanup
    removes strips at or below that width and would remove the band. Raises ColorError."""
    if (isinstance(width_mm, bool) or not isinstance(width_mm, (int, float, np.floating))
            or not math.isfinite(float(width_mm))):
        raise ColorError(f"outline_width_mm must be a finite number of mm, got {width_mm!r}")
    if not float(width_mm) > opening_width_mm:
        raise ColorError(f"outline_width_mm ({float(width_mm)} mm) must be wider than "
                         f"{opening_rule} ({opening_width_mm} mm): cleanup removes strips "
                         "at or below that width, so it would remove the band")
    return float(width_mm)


def _nearest_non_family(q: Quantized, family, ty: np.ndarray, tx: np.ndarray) -> np.ndarray:
    """For pixels (ty, tx): the index of q's nearest non-family color (exact squared
    distance between pixel centres; ties to the lowest index of q, as in the cleanup's
    thin step)."""
    best = np.full(len(ty), np.iinfo(np.int64).max, np.int64)
    best_c = np.full(len(ty), OUTSIDE, np.int64)
    for c in range(len(q.hex)):                  # ascending: the lowest index wins a tie
        if c in family:
            continue
        d2 = d2_nearest(q.labels == c, ty, tx)
        closer = d2 < best
        best = np.where(closer, d2, best)
        best_c = np.where(closer, c, best_c)
    return best_c


def _select_family(q: Quantized, outline_color, thin, rules
                   ) -> tuple[tuple[int, ...], str, list[tuple[str, float]]]:
    """Step 1 of handle_outlines: the family, how it was found, and the thin share used
    (as a threshold) under auto."""
    if outline_color == "none":
        return (), "none", []
    if outline_color == "auto":
        t = _check_thin_share(rule_value(rules, THIN_SHARE_RULE))
        return _family_by_thinness(thin, t), "auto", [(THIN_SHARE_RULE, t)]
    return _family_from_list(outline_color, len(q.hex)), "config", []


@dataclass(frozen=True, eq=False)
class _Dropped:
    """Step 4 of handle_outlines: the labels after the drop and what it measured."""

    labels: np.ndarray
    strokes: np.ndarray
    stroke_px: float | None
    comps: tuple[WideComponent, ...]
    note: str


def _drop(q: Quantized, family, core: int, kept, ratio: float) -> _Dropped:
    """Step 4 of handle_outlines (see its docstring): strokes, shading tones and the core's
    narrow wide areas take the nearest non-family color; the core keeps the wide areas
    that pass keeps_wide_area."""
    labels = np.array(q.labels, np.int64)
    strokes = np.zeros(labels.shape, bool)
    shading = np.zeros(labels.shape, bool)               # non-core members' wide pixels
    for f in family:
        m = q.labels == f
        strokes |= m & ~kept[f]
        if f != core:
            shading |= m & kept[f]
    core_wide = (q.labels == core) & kept[core]
    stroke_px = stroke_width_px(strokes)
    comps, keep_core = wide_core_components(core_wide, stroke_px, ratio)
    replaced = strokes | shading | (core_wide & ~keep_core)
    ty, tx = np.nonzero(replaced)
    labels[ty, tx] = _nearest_non_family(q, family, ty, tx)
    n_kept = sum(c.kept for c in comps)
    width_text = "none" if stroke_px is None else f"{stroke_px:.2f} px"
    note = (f"outlines: drop: {int(strokes.sum())} thin pixel(s) and "
            f"{int(shading.sum())} wide pixel(s) of the other members took the nearest "
            f"non-family color; of the core's {len(comps)} wide area(s), {n_kept} at "
            f"least {ratio:g} x the stroke width ({width_text}) kept the core "
            f"{q.hex[core]} ({int(keep_core.sum())} px), the rest took the nearest "
            "non-family color")
    return _Dropped(labels=labels, strokes=strokes, stroke_px=stroke_px, comps=comps,
                    note=note)


def _keep_band(q: Quantized, strokes: np.ndarray, core: int, limits: Limits,
               width_mm: float, width_px: float) -> tuple[np.ndarray, tuple[int, int], str]:
    """Step 5 of handle_outlines: the read-only band (stroke_band of the strokes without
    their specks), the specks' (count, pixels) and the note."""
    speck_px, n_specks = stroke_specks(strokes, limits.min_area_px)
    specks = (n_specks, int(speck_px.sum()))
    band = stroke_band(strokes & ~speck_px, q.labels != OUTSIDE, width_px)
    band.flags.writeable = False
    note = (f"outlines: keep: a {width_mm:g} mm ({width_px:.2f} px) band in the "
            f"core {q.hex[core]} redraws the drawn lines and the outer edge, painted after "
            f"the merges ({int(band.sum())} px); {n_specks} stroke speck(s) below "
            f"the island area ({specks[1]} px) are not drawn")
    return band, specks, note


def handle_outlines(q: Quantized, *, outline_color, outlines: str, limits: Limits,
                    rules, width_mm=None) -> tuple[Quantized, OutlineResult]:
    """The outline step between quantize and the merges (plan Tasks 7c and 7e-b).

    q: the extracted colors (quantize's result). outline_color: "auto", "none" or a list of
    extraction indices; outlines: "drop" or "keep"; limits: printable_limits_px at the
    plan's scale; rules: the registry (the thin share is read under auto, the wide-area
    ratio with a family). width_mm: the band width under keep (the outline_width_mm
    setting); None takes the rule color.outline.keep_width. Returns the colors after the
    drop and an OutlineResult.

    1. The family: none -> empty; auto -> the thinness rule (color.outline.thin_share);
       a list -> those indices (refused unless each is an index of q, once). Every color's
       thinness is computed either way (once).
    2. With an empty family nothing changes: q itself is returned with the identity remap
       (under keep, a note says it has no effect).
    3. The core is outline_core: the family member with the lowest L* (ties: lowest
       index).
    4. Drop (always, under keep too). For each family member f, its thin pixels are its
       pixels that its OWN opening does not keep (open_mask(labels == f, min_width_px));
       each member separately, since a fringe tone and the line core are each thin even
       where together they are wide. S is the union of the members' thin pixels (the
       drawn strokes) and its stroke width is stroke_width_px(S). The wide pixels (kept
       by their member's opening):
       - of a member other than the core (a shading tone): they are replaced, like thin
         pixels;
       - of the core: per 4-connected component (wide_core_components), kept in the
         core's color only if its inscribed width is at least
         color.outline.keep_area_width_ratio x the stroke width (a pupil, not a line's
         widened tip); with no stroke, none is kept. The others are replaced.
       Each replaced pixel takes the color of the nearest pixel of a non-family color
       (exact squared distance between pixel centres; ties to the lowest index of q).
       Refused if every color is in the family.
    5. Keep: the band that redraws the drawing's lines, stroke_band(S without its specks,
       the labelled pixels, W) with W = width_mm / limits.mm_per_px, is returned in the
       OutlineResult, not painted here: tdmg.color_plan paints it (paint_band) after the
       owner's merges, so a merge never leaves band pixels inside the merged color. The
       specks are S's 8-connected components below the island area (stroke_specks with
       limits.min_area_px); their pixels were replaced in step 4 like the other thin
       pixels and are simply not redrawn. W must exceed the cleanup's opening width
       (flat.sliver.opening_width, check_outline_width), or cleanup would remove the band.
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
    family, found_by, thresholds = _select_family(q, outline_color, thin, rules)   # 1
    if not family:                                                                  # 2
        notes = (KEEP_NO_EFFECT_NOTE,) if outlines == "keep" else ()
        return q, OutlineResult(family=(), core=None, thinness=thin, found_by=found_by,
                                method=OUTLINE_METHOD, remap=tuple(range(k)),
                                thresholds=tuple(thresholds), stroke_width_px=None,
                                wide_components=(), keep_width_mm=None, keep_width_px=None,
                                specks=None, band=None, core_rgb=None, notes=notes)
    if len(family) == k:
        raise ColorError("every extracted color is in the outline family, so no color is "
                         "left for its pixels; set outline_color to none or a shorter list")
    core = outline_core(family, q.lab)                                              # 3
    ratio = rule_value(rules, KEEP_RATIO_RULE)
    if ratio < 0:
        raise ColorError(f"{KEEP_RATIO_RULE} must be 0 or more, got {ratio}")
    thresholds.append((KEEP_RATIO_RULE, ratio))
    width_px = None
    if outlines == "keep":
        width_mm = check_outline_width(rule_value(rules, KEEP_WIDTH_RULE) if width_mm is None
                                       else width_mm, limits.opening_width_mm,
                                       limits.opening_rule)
        width_px = width_mm / limits.mm_per_px
    else:
        width_mm = None
    dropped = _drop(q, family, core, kept, ratio)                                   # 4
    notes = [dropped.note]
    band = specks = None
    if outlines == "keep":                                                          # 5
        band, specks, note = _keep_band(q, dropped.strokes, core, limits, width_mm, width_px)
        notes.append(note)
    out = from_labels(dropped.labels, q.rgb, iterations=q.iterations,
                      converged=q.converged, n_requested=q.n_requested,
                      n_distinct_colors=q.n_distinct_colors, dropped=q.dropped)
    core_rgb = np.array(q.rgb[core])
    core_rgb.flags.writeable = False
    return out, OutlineResult(family=family, core=core, thinness=thin, found_by=found_by,
                              method=OUTLINE_METHOD, remap=out.remap,
                              thresholds=tuple(thresholds), stroke_width_px=dropped.stroke_px,
                              wide_components=dropped.comps, keep_width_mm=width_mm,
                              keep_width_px=width_px, specks=specks, band=band,
                              core_rgb=core_rgb, notes=tuple(notes))


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

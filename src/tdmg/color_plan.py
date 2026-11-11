"""The pure color pipeline of `tdmg colors` (docs/plans/2026-11-11-color-palette.md,
Tasks 7b and 7c): from the cutout's pixels and the resolved settings to the final palette,
with no I/O. tdmg.colors reads the selection, calls plan_colors, then writes the record and
the preview.

plan_colors runs, in order:
1. quantize(cutout RGB, mask, extract): the extracted colors. Their indices (largest area
   first) are the extraction indices that outline_color and merge use.
2. check_extraction_indices against the real number of extracted colors (an image with
   fewer distinct colors gives fewer than `extract`), before the outline step reads any
   index.
3. handle_outlines (tdmg.color_outline): the outline family (auto: the thinness rule;
   none; or a list) is dropped; under `keep` it also returns the band that redraws the
   drawing's lines.
4. check_extraction_indices again, now with the family and its core (a merge may go into
   the core, never from a family member); then apply_merges.
5. shade_pairs among the colors left after steps 3 and 4, without the core: flagged for the
   owner, never applied (no labels change).
6. Under `keep` (decided 2026-11-11): paint_band paints the band in the core's color, after
   the merges, so no band is left inside a merged color.
7. clean_regions: the final palette.
Each step's result carries an explicit old -> new index array (Quantized.remap, and
OutlineResult.remap for step 3); they are composed to give each extracted color its fate
and final index. Under keep, the core takes its final index through the band step even when
the drop left it no pixel. Colors (hex) are only a cross-check: every final palette entry must be
the final index of at least one extracted color with the same hex.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from tdmg.color import (
    CleanupLog,
    ColorError,
    Limits,
    Quantized,
    apply_merges,
    clean_regions,
    quantize,
)
from tdmg.color_config import ColorConfigError, check_extraction_indices
from tdmg.color_outline import (
    SHADE_CHROMA_RULE,
    SHADE_HUE_RULE,
    OutlineResult,
    ShadePair,
    handle_outlines,
    paint_band,
    rule_value,
    shade_pairs,
)
from tdmg.rules import Rule

# What became of an extracted color: still in the final palette; merged by the owner into
# another; removed by the outline handling (an outline-family member); removed by the
# region cleanup. The outline core, when it keeps wide areas, follows the same remaps as any
# other color, so its fate is final (or cleanup).
FATES = ("final", "merged", "outline", "cleanup")


@dataclass(frozen=True, eq=False)
class ColorPlan:
    """Every stage of plan_colors, and each extracted color's fate.

    extracted: quantize's result. outlined, outline: handle_outlines' result. merges: the
    (from, into) pairs by extraction index, as given. merged: after apply_merges.
    banded: after paint_band under keep with a family, else merged itself.
    shade_pairs: the flagged pairs (extraction indices), with the two thresholds used,
    shade_rules ((rule id, value), ...). cleaned, log: clean_regions' result, the final
    palette. fate and final_index: one entry per extraction index; final_index is set
    exactly when the fate is "final".
    """

    extracted: Quantized
    outlined: Quantized
    outline: OutlineResult
    merges: tuple[tuple[int, int], ...]
    merged: Quantized
    banded: Quantized
    shade_pairs: tuple[ShadePair, ...]
    shade_rules: tuple[tuple[str, float], ...]
    cleaned: Quantized
    log: CleanupLog
    fate: tuple[str, ...]
    final_index: tuple[int | None, ...]


def shade_candidates(n: int, outline_remap, core, merges) -> list[int]:
    """The extraction indices compared for shade pairs: kept by the outline step, not the
    core, and not merged away."""
    froms = {a for a, _ in merges}
    return [i for i in range(n)
            if outline_remap[i] is not None and i != core and i not in froms]


def plan_colors(cutout_rgb, mask, settings: Mapping, limits: Limits,
                rules: dict[str, Rule]) -> ColorPlan:
    """The pipeline in the module docstring. settings: the resolved settings
    (tdmg.color_config); extract, outline_color, outlines and merge are read here. limits:
    printable_limits_px at the plan's scale. rules: the registry; the outline rules are read
    by handle_outlines, the two shade rules here. Raises ColorError (bad input) or
    ColorConfigError (an index the extraction does not have, a merge from the outline
    family or into a member other than the core, or into a core the outline step left
    with no pixel).
    """
    extracted = quantize(cutout_rgb, mask, settings["extract"])
    n = len(extracted.hex)
    outline_color, merge = settings["outline_color"], settings["merge"]
    check_extraction_indices(outline_color, merge, n)
    outlined, outline = handle_outlines(extracted, outline_color=outline_color,
                                        outlines=settings["outlines"], limits=limits,
                                        rules=rules)
    check_extraction_indices(outline_color, merge, n, outline.family, outline.core)
    merges = tuple((int(a), int(b)) for a, b in merge)
    for a, b in merges:
        if b == outline.core and outline.remap[b] is None:
            raise ColorConfigError(
                f"merge [{a}, {b}]: color {b}, the outline core, has no pixel left after the "
                "outline handling (it has no wide area); merge into another color")
    merged = apply_merges(outlined, _translate(merges, outline.remap))
    hue, chroma = rule_value(rules, SHADE_HUE_RULE), rule_value(rules, SHADE_CHROMA_RULE)
    pairs = shade_pairs(extracted.lab.tolist(), extracted.hex,
                        shade_candidates(n, outline.remap, outline.core, merges), hue, chroma)
    banded, band_core = merged, None
    if outline.band is not None:
        banded, ci = paint_band(merged, outline.band, outline.core_rgb)
        band_core = banded.remap[ci]
    cleaned, log = clean_regions(banded, limits)

    def final_of(b):
        return None if b is None else cleaned.remap[b]

    into = dict(merges)
    fate, final = [], []
    for i in range(n):
        r = outline.remap[i]
        if i in into:
            fate.append("merged")
            final.append(None)
            continue
        if i == outline.core and band_core is not None:
            j = final_of(band_core)            # the band's color is the core's
        elif r is None:
            # A guard: the outline step only ever removes family members.
            if i not in outline.family:
                raise ColorError(f"extracted color {i} was removed by the outline handling "
                                 "but is not in the outline family")
            fate.append("outline")
            final.append(None)
            continue
        else:
            j = merged.remap[r]
            if j is not None and banded is not merged:
                j = banded.remap[j]
            j = final_of(j)
        fate.append("final" if j is not None else "cleanup")
        final.append(j)
    for k, h in enumerate(cleaned.hex):
        if not any(f == k and extracted.hex[i] == h for i, f in enumerate(final)):
            raise ColorError(f"final color {k} ({h}) is not the final index of an extracted "
                             "color with the same color")
    return ColorPlan(extracted=extracted, outlined=outlined, outline=outline, merges=merges,
                     merged=merged, banded=banded, shade_pairs=pairs,
                     shade_rules=((SHADE_HUE_RULE, hue), (SHADE_CHROMA_RULE, chroma)),
                     cleaned=cleaned, log=log, fate=tuple(fate), final_index=tuple(final))


def _translate(merges, remap) -> list[tuple[int, int]]:
    """Merge pairs from extraction indices to the indices after the outline step.

    A guard: a merge's from is never in the outline family and its into is outside it or
    the core (check_extraction_indices), the outline step only removes family members, and
    plan_colors refuses a merge into a removed core first; so a None here means a bug in
    that step.
    """
    out = []
    for a, b in merges:
        if remap[a] is None or remap[b] is None:
            raise ColorError(f"merge [{a}, {b}]: the outline handling removed color "
                             f"{a if remap[a] is None else b}")
        out.append((remap[a], remap[b]))
    return out

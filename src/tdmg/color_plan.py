"""The pure color pipeline of `tdmg colors` (docs/plans/2026-11-11-color-palette.md,
Task 7b): from the cutout's pixels and the resolved settings to the final palette, with
no I/O. tdmg.colors reads the selection, calls plan_colors, then writes the record and
the preview.

plan_colors runs, in order:
1. quantize(cutout RGB, mask, extract): the extracted colors. Their indices (largest area
   first) are the extraction indices that outline_color and merge use.
2. check_extraction_indices against the real number of extracted colors (an image with
   fewer distinct colors gives fewer than `extract`), before the outline step reads any
   index.
3. handle_outlines: the outline family and its handling (Task 7b: a seam that does
   nothing; Task 7c fills it in, and adds the shade-pair flags here).
4. check_extraction_indices again, now with the family; then apply_merges.
5. clean_regions: the final palette.
Each step's result carries an explicit old -> new index array (Quantized.remap, and
OutlineResult.remap for step 3); they are composed to give each extracted color its fate
and final index. Colors (hex) are only a cross-check: every final palette entry must be
the final index of at least one extracted color with the same hex.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from tdmg.color import (
    CleanupLog,
    ColorError,
    Limits,
    OutlineResult,
    Quantized,
    apply_merges,
    clean_regions,
    handle_outlines,
    quantize,
)
from tdmg.color_config import check_extraction_indices
from tdmg.rules import Rule

# What became of an extracted color: still in the final palette; merged by the owner into
# another; part of the outline family (Task 7c); removed by the region cleanup.
FATES = ("final", "merged", "outline", "cleanup")


@dataclass(frozen=True, eq=False)
class ColorPlan:
    """Every stage of plan_colors, and each extracted color's fate.

    extracted: quantize's result. outlined, outline: handle_outlines' result. merges: the
    (from, into) pairs by extraction index, as given. merged: after apply_merges. cleaned,
    log: clean_regions' result, the final palette. fate and final_index: one entry per
    extraction index; final_index is set exactly when the fate is "final".
    """

    extracted: Quantized
    outlined: Quantized
    outline: OutlineResult
    merges: tuple[tuple[int, int], ...]
    merged: Quantized
    cleaned: Quantized
    log: CleanupLog
    fate: tuple[str, ...]
    final_index: tuple[int | None, ...]


def plan_colors(cutout_rgb, mask, settings: Mapping, limits: Limits,
                rules: dict[str, Rule]) -> ColorPlan:
    """The pipeline in the module docstring. settings: the resolved settings
    (tdmg.color_config); extract, outline_color, outlines and merge are read here. limits:
    printable_limits_px at the plan's scale. rules: the registry; Task 7c reads the outline
    and shade rules from it (Task 7b uses none). Raises ColorError (bad input, an outline
    list until Task 7c) or ColorConfigError (an index the extraction does not have).
    """
    extracted = quantize(cutout_rgb, mask, settings["extract"])
    n = len(extracted.hex)
    outline_color, merge = settings["outline_color"], settings["merge"]
    check_extraction_indices(outline_color, merge, n)
    outlined, outline = handle_outlines(extracted, outline_color=outline_color,
                                        outlines=settings["outlines"])
    check_extraction_indices(outline_color, merge, n, outline.family)
    merges = tuple((int(a), int(b)) for a, b in merge)
    merged = apply_merges(outlined, _translate(merges, outline.remap))
    cleaned, log = clean_regions(merged, limits)

    into = dict(merges)
    fate, final = [], []
    for i in range(n):
        if i in outline.family:
            fate.append("outline")
            final.append(None)
        elif i in into:
            fate.append("merged")
            final.append(None)
        else:
            # A guard: a color outside the family that the outline step removed. Task 7b
            # removes none; Task 7c must give such a color its own fate if it can happen.
            if outline.remap[i] is None:
                raise ColorError(f"extracted color {i} was removed by the outline handling "
                                 "but is not in the outline family")
            j = merged.remap[outline.remap[i]]
            j = None if j is None else cleaned.remap[j]
            fate.append("final" if j is not None else "cleanup")
            final.append(j)
    for k, h in enumerate(cleaned.hex):
        if not any(f == k and extracted.hex[i] == h for i, f in enumerate(final)):
            raise ColorError(f"final color {k} ({h}) is not the final index of an extracted "
                             "color with the same color")
    return ColorPlan(extracted=extracted, outlined=outlined, outline=outline, merges=merges,
                     merged=merged, cleaned=cleaned, log=log, fate=tuple(fate),
                     final_index=tuple(final))


def _translate(merges, remap) -> list[tuple[int, int]]:
    """Merge pairs from extraction indices to the indices after the outline step.

    A guard: merges never touch the outline family (check_extraction_indices), and the
    outline step only removes family colors, so a None here means a bug in that step.
    """
    out = []
    for a, b in merges:
        if remap[a] is None or remap[b] is None:
            raise ColorError(f"merge [{a}, {b}]: the outline handling removed color "
                             f"{a if remap[a] is None else b}")
        out.append((remap[a], remap[b]))
    return out

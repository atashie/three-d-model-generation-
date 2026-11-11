"""`tdmg colors`: the color plan of a selected subject, for review
(docs/plans/2026-11-11-color-palette.md, Decisions 1, 2, 6, 7 and 8; Tasks 6, 7b and 7c).

make_colors reads a verified tdmg select folder (tdmg.selection.read_selection, with the
cutout), resolves the settings (tdmg.color_config: flags, then the config file, then the
defaults), and then:

1. mm_per_px = width_mm / the mask's exact bounding-box width in pixels (mask_mm_per_px),
   and printable_limits_px at that scale.
2. tdmg.color_plan.plan_colors, the pure pipeline: quantize to `extract` colors (the
   extraction indices that outline_color and merge use), the outline step (the family
   found by the thinness rule or named in the config, dropped or redrawn as one band),
   the owner's merges, the shade-pair flags (reported, never applied), and clean_regions,
   which gives the final palette, re-sorted by final area. It also gives each extracted
   color's fate and final index.
3. The base color: `auto` is index 0 (the largest area after cleanup); a number must be an
   index of the final palette (check_base), ready or not.
4. Ready: the plan is ready when the final palette has at most `colors` colors. When it
   has more, every output is still written, with ready false and the reason (which lists
   the flagged shade pairs as merges to consider), so the owner can choose merges from
   the preview; verify_colors refuses such a plan.
5. smooth_labels(cleaned labels, the edges preset's sigma, supersample): the fine map, used
   here for the preview only. Design step 2 (geometry) recomputes it from labels.png and
   the recorded sigma.

It writes labels.png, regions.png and colors.json (the record, last) into a new or empty
folder, through tdmg.records.write_outputs. Everything is computed and encoded in memory
first, so a refused input writes nothing. No gate checks run here.

tdmg.color, tdmg.color_plan and tdmg.smoothing stay free of I/O; this module does the
reading and writing, the record and the preview.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import math
import numbers
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import scipy
from PIL import Image, ImageDraw, ImageFont
from pydantic import ValidationError

from tdmg import __version__
from tdmg.color import (
    CLEANUP_METHOD,
    ISLAND_RULE,
    KEEP_WIDTH_RULE,
    METHOD,
    OPENING_RULE,
    OUTSIDE,
    SHADE_CHROMA_RULE,
    SHADE_HUE_RULE,
    SHADE_METHOD,
    THIN_SHARE_RULE,
    ColorError,
    changed_mask,
    outline_core,
    printable_limits_px,
    shade_pairs,
    srgb_to_lab,
)
from tdmg.color_config import (
    FURRY_RULE,
    KEYS,
    SMOOTH_RULE,
    ColorConfig,
    ColorConfigError,
    check_base,
    check_extraction_indices,
    edge_sigma_px,
    palette_cap,
    resolve_color_config,
)
from tdmg.color_plan import FATES, plan_colors
from tdmg.profiles import PrinterProfile
from tdmg.records import (
    RecordError,
    canonical_json,
    check_output_dir,
    environment,
    png_bytes,
    record_text,
    write_outputs,
)
from tdmg.selection import SelectionError, checker, pixels_sha256, read_selection
from tdmg.smoothing import (
    LABELS_METHOD,
    SUPERSAMPLE,
    SmoothingError,
    _sigma_or_zero,
    _supersample,
    smooth_labels,
)

# colors-2 (Tasks 7b and 7c, unreleased): extraction at `extract`, the outline step, the
# owner's merges, the shade-pair flags and the ready flag. tdmg.colors/2 adds the
# extraction, outline, merges, shade_pairs and ready fields.
COLORS_ALGORITHM_VERSION = "colors-2"
RECORD_SCHEMA = "tdmg.colors/2"
RECORD_NAME = "colors.json"
OUTPUT_FILES = ("labels.png", "regions.png")
LABELS_OUTSIDE = 255   # labels.png value outside the mask; palette indices are below it
REVIEW = "Open regions.png to check the colors before building geometry."

# --- regions.png layout. Display only: none of these is a threshold. ---------------------
# Each image pixel is shown as PREVIEW_SCALE x PREVIEW_SCALE screen pixels. 2 is enough to
# see whether an edge is smooth or furry on the owner's ~800-1000-px images (the smoothed
# edge is drawn from the 4x fine map). The preview is 2 * PREVIEW_SCALE * W wide and
# PREVIEW_SCALE * (H + ROW_PX * strip rows) tall, where the strip has the legend rows, one
# row per final color, a heading, one row per extracted color and the merge hint, and a
# last row when the plan is not ready (_regions_image).
PREVIEW_SCALE = 2
CHANGED_DASH_PX = 3                       # dash length of the cleanup outline
CHANGED_DASH = ((0, 0, 0), (255, 255, 255))   # black and white, visible on any color
STRIP_BACKGROUND = (255, 255, 255)
STRIP_TEXT = (0, 0, 0)
# The swatch strip is drawn at 1x, then enlarged by PREVIEW_SCALE like the panels.
ROW_PX = 14                               # one text line per row
SWATCH_PX = 10
MARGIN_PX = 4
TEXT_X_PX = MARGIN_PX + SWATCH_PX + 6
LEGEND = ("left: cutout. right: final colors with the {edges} edges. "
          "black/white dashes: changed by cleanup")
OUTER_OUTLINE = "outer outline: image pixels (smoothed when the model is built)"
FINAL_HEADING = "final colors (base uses these indices):"
EXTRACTED_HEADING = ("extracted colors ({n}): outline_color and merge in the config file use "
                     "these indices")
MERGE_HINT = ("to merge two colors, add merge: [[from, into]] to the config file (extraction "
              "indices); shade pairs are only flagged, never merged for you")


def legend_rows(edges: str) -> list[str]:
    """The legend lines above the swatches in regions.png, ending with the final palette's
    heading."""
    return [LEGEND.format(edges=edges), OUTER_OUTLINE, FINAL_HEADING]


def not_ready_line(reason: str) -> str:
    """The last line of regions.png's strip when the plan is not ready."""
    return f"NOT READY: {reason}"


class ColorsError(ValueError):
    """The selection cannot be made into a color plan as asked. Nothing is written."""


def mask_mm_per_px(mask: np.ndarray, width_mm: float) -> float:
    """width_mm over the mask's exact bounding-box width in pixels.

    The width is (last column with a True pixel) - (first one) + 1: the extent of the
    exact pixel-cell outline (tdmg.flat.mask_outline), so this equals the scale_mm_per_px
    that tdmg.flat.to_model gives for the exact outline (tests/test_colors.py checks it).
    tdmg flat with smoothing on takes the smoothed outline's extent instead, which can
    differ by a fraction of a pixel.
    """
    cols = np.flatnonzero(np.asarray(mask).any(axis=0))
    if len(cols) == 0:
        raise ColorsError("the selection's mask is empty")
    return width_mm / float(cols[-1] - cols[0] + 1)


def colors_identity(*, methods: dict, selection_id: str, cutout_pixels_sha256: str,
                    mask_pixels_sha256: str, settings: dict, width_mm: float, printer: str,
                    nozzle_diameter_mm: float, rules: dict, supersample: int) -> dict:
    """The identity of a color plan: the dict that colors_id hashes, stored in colors.json.

    methods: the algorithm versions (colors, quantize, outline, cleanup, labels). settings:
    the resolved values of every key (colors, extract, edges, base, outlines,
    outline_color, merge), not their sources: the same values from a flag, a file or a
    default give the same plan. The extraction default's rule is therefore not hashed
    separately; its value is settings.extract. printer: the profile id (as flat_identity's params
    hold it). rules: {rule id: registry value} for every rule used: the two cleanup rules
    (the island rule's own min_square_side, not the derived area) and the edges preset's
    rule, if any. The edges sigma is hashed only there; `exact` has no rule and sigma 0
    by definition. supersample: the fine map's factor. The environment is never part of it.
    """
    return {"methods": dict(methods), "selection_id": selection_id,
            "cutout_pixels_sha256": cutout_pixels_sha256,
            "mask_pixels_sha256": mask_pixels_sha256, "settings": dict(settings),
            "width_mm": width_mm, "printer": printer,
            "nozzle_diameter_mm": nozzle_diameter_mm, "rules": dict(rules),
            "supersample": supersample}


def colors_id(identity: dict) -> str:
    """SHA-256 of the canonical JSON of identity (colors_identity's dict). Raises
    ColorsError if it cannot be encoded (NaN or infinity, or text UTF-8 cannot encode)."""
    try:
        return hashlib.sha256(canonical_json(identity)).hexdigest()
    except ValueError as e:              # includes UnicodeEncodeError
        raise ColorsError(f"the colors identity cannot be hashed: {e}") from None


def _width(width_mm) -> float:
    if isinstance(width_mm, bool) or not isinstance(width_mm, numbers.Real):
        raise ColorsError(f"width_mm must be a number, got {width_mm!r}")
    value = float(width_mm)
    if not math.isfinite(value) or value <= 0:
        raise ColorsError(f"width_mm must be a finite number above 0, got {value}")
    return value


def _json_plain(obj):
    """A JSON round trip: tuples become lists and dataclasses must already be dicts."""
    return json.loads(canonical_json(obj))


# --- regions.png --------------------------------------------------------------------------

def _row_box(row: int, height_px: int) -> tuple[int, int, int, int]:
    s = PREVIEW_SCALE
    top = s * height_px + s * (ROW_PX * row + (ROW_PX - SWATCH_PX) // 2)
    left = s * MARGIN_PX
    return top, left, top + s * SWATCH_PX, left + s * SWATCH_PX


def swatch_box(index: int, height_px: int) -> tuple[int, int, int, int]:
    """(top, left, bottom, right) of final palette entry index's swatch in regions.png, for
    an image height_px tall. The strip starts with the legend rows (legend_rows); entry i
    is the row after them plus i."""
    return _row_box(index + len(legend_rows("")), height_px)


def extracted_swatch_box(index: int, height_px: int, n_final: int
                         ) -> tuple[int, int, int, int]:
    """The same for extracted color index: after the legend, the n_final final colors and
    the extraction heading (EXTRACTED_HEADING)."""
    return _row_box(len(legend_rows("")) + n_final + 1 + index, height_px)


def _enlarge(a: np.ndarray, s: int) -> np.ndarray:
    return np.repeat(np.repeat(a, s, axis=0), s, axis=1)


def _fine_to_preview(fine: np.ndarray, h: int, w: int, s: int) -> np.ndarray:
    """The fine map sampled at the preview's pixel centres, by nearest fine pixel.

    Preview pixel (row a, column b) has its centre at ((b + 0.5) / P, (a + 0.5) / P) in
    image pixels (P = PREVIEW_SCALE); the fine pixel that contains it is
    floor((a + 0.5) s / P). A centre on a fine-pixel boundary (s = 4, P = 2: every one)
    takes the fine pixel below and to the right of it.
    """
    p = PREVIEW_SCALE
    rows = np.floor((np.arange(h * p) + 0.5) * s / p).astype(np.int64)
    cols = np.floor((np.arange(w * p) + 0.5) * s / p).astype(np.int64)
    return fine[np.ix_(rows, cols)]


def _inner_edge(region: np.ndarray) -> np.ndarray:
    """Pixels of region with a 4-neighbour outside it (or on the image border)."""
    padded = np.pad(region, 1, constant_values=False)
    core = (padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:])
    return region & ~core


def _strip(rows: list[tuple[tuple[int, int, int] | None, str]], width: int) -> np.ndarray:
    """The swatch strip at 1x: one ROW_PX row per entry, a swatch (or none) and its text.

    Text uses Pillow's built-in bitmap font (ImageFont.load_default_imagefont, Pillow
    10.1 or later), which has no anti-aliasing and no FreeType dependency, so the pixels
    are expected to be the same on every platform with the same Pillow version; that is
    not yet compared across machines. The record's regions_pixels_sha256 (decoded pixels)
    and outputs["regions.png"] (file bytes) let a pixel difference be told apart from an
    encoding difference. Text wider than the strip is cut off.
    """
    im = Image.new("RGB", (width, ROW_PX * len(rows)), STRIP_BACKGROUND)
    draw = ImageDraw.Draw(im)
    font = ImageFont.load_default_imagefont()
    for i, (rgb, text) in enumerate(rows):
        top = ROW_PX * i
        x = MARGIN_PX
        if rgb is not None:
            y = top + (ROW_PX - SWATCH_PX) // 2
            draw.rectangle((MARGIN_PX, y, MARGIN_PX + SWATCH_PX - 1, y + SWATCH_PX - 1),
                           fill=tuple(int(v) for v in rgb))
            x = TEXT_X_PX
        draw.text((x, top + 1), text, fill=STRIP_TEXT, font=font)
    return np.asarray(im)


def _regions_image(cutout_rgb: np.ndarray, mask: np.ndarray, palette: list[dict],
                   fine: np.ndarray, supersample: int, changed: np.ndarray,
                   edges: str, vanished: set[int], extracted: list[dict],
                   outline: dict, shade: list[dict],
                   not_ready_reason: str | None) -> np.ndarray:
    """The review preview: two panels side by side, then the swatch strip.

    fine is smooth_labels' fine map at supersample s (its shape is (H s, W s)); vanished
    holds the palette indices that smoothing removed.

    Left: the cutout, PREVIEW_SCALE x nearest, on tdmg select's preview checkerboard
    outside the mask. Right: the final palette colors from the smoothed fine map
    (_fine_to_preview), inside the mask only (the image mask, enlarged by nearest; the R1
    outline is smoothed in design step 2 (geometry), not here), on the same checkerboard.
    Pixels whose color cleanup changed (changed_mask) are outlined on the right: the inner
    edge of the changed region, enlarged, drawn in black and white dashes of
    CHANGED_DASH_PX along the diagonals, so it shows on any color. Below: the legend rows
    (legend_rows; they say that the outer outline is the image's pixel outline, smoothed in
    design step 2, and end with the final palette's heading), then one row per final
    palette entry with its swatch, index, hex code, area share, and whether it is the base
    or vanished in smoothing. Then, separated by a heading row (EXTRACTED_HEADING), one row
    per extracted color (the extraction record's palette): its swatch, extraction index,
    hex code, share of the extraction, its fate and flags (extracted_text, from the
    record's outline block and shade pairs), then the merge hint (MERGE_HINT). When the
    plan is not ready, a last row gives the reason (not_ready_line).
    """
    h, w = mask.shape
    p = PREVIEW_SCALE
    big_mask = _enlarge(mask, p)
    board = checker(h * p, w * p)[..., None].repeat(3, axis=2)
    left = np.where(big_mask[..., None], _enlarge(cutout_rgb, p), board)
    pal = np.array([e["rgb"] for e in palette], np.uint8)
    right = np.where(big_mask[..., None], pal[_fine_to_preview(fine, h, w, supersample)],
                     board)
    edge = _inner_edge(_enlarge(changed, p))
    yy, xx = np.nonzero(edge)
    dash = ((yy + xx) // CHANGED_DASH_PX) % 2
    right[yy, xx] = np.array(CHANGED_DASH, np.uint8)[dash]
    panels = np.concatenate([left, right], axis=1).astype(np.uint8)
    rows = [(None, line) for line in legend_rows(edges)]
    for e in palette:
        notes = (["base"] if e["base"] else []) + (
            ["vanished in smoothing"] if e["index"] in vanished else [])
        rows.append((e["rgb"], f"{e['index']}  {e['hex']}  {e['share']:6.1%}  "
                               + "  ".join(notes)))
    rows.append((None, EXTRACTED_HEADING.format(n=len(extracted))))
    for e in extracted:
        rows.append((e["rgb"], f"{e['index']}  {e['hex']}  {e['share']:6.1%}  "
                               + extracted_text(e, outline, shade)))
    rows.append((None, MERGE_HINT))
    if not_ready_reason is not None:
        rows.append((None, not_ready_line(not_ready_reason)))
    strip = _enlarge(_strip(rows, 2 * w), p)
    return np.concatenate([panels, strip], axis=0)


def extracted_fate(e: dict) -> str:
    """What became of an extracted color (its record entry's fate), for the preview and
    the CLI."""
    return {"final": f"final {e['final_index']}", "merged": f"merged into {e['merged_into']}",
            "outline": "outline color", "cleanup": "dropped by cleanup"}[e["fate"]]


def extracted_text(e: dict, outline: dict, shade: list[dict]) -> str:
    """An extracted color's fate and flags, for the preview and the CLI: outline-family
    members say so, with their thinness (the core: "outline core, kept as final i" when its
    wide areas remain), and a color in a flagged shade pair names its partners."""
    i = e["index"]
    if i in outline["family"]:
        thin = f"thin {outline['thinness'][i]:.0%}"
        if i != outline["core"]:
            text = f"outline ({thin})"
        elif e["fate"] == "final":
            text = f"outline core ({thin}), kept as final {e['final_index']}"
        elif e["fate"] == "outline":
            text = f"outline core ({thin}), no wide area left"
        else:
            text = f"outline core ({thin}), {extracted_fate(e)}"
    else:
        text = extracted_fate(e)
    partners = sorted(p["j"] if p["i"] == i else p["i"] for p in shade if i in (p["i"], p["j"]))
    if partners:
        text += "; shade pair with " + ", ".join(str(k) for k in partners)
    return text


def shade_pair_records(pairs) -> list[dict]:
    """The record's shade_pairs entries (tdmg.color.ShadePair, by extraction index)."""
    return [{"i": p.i, "hex_i": p.hex_i, "j": p.j, "hex_j": p.hex_j, "dh_deg": p.dh_deg,
             "chroma_i": p.chroma_i, "chroma_j": p.chroma_j, "dl": p.dl,
             "merge": list(p.merge)} for p in pairs]


# --- make_colors ------------------------------------------------------------------------

def make_colors(selection_dir, out_dir, *, width_mm, flags: dict, config_path,
                rules: dict, printer: PrinterProfile, supersample: int = SUPERSAMPLE) -> dict:
    """Write labels.png, regions.png and colors.json from a tdmg select folder; return the
    record. See the module docstring for the steps.

    flags: any of tdmg.color_config.KEYS (the CLI gives colors, extract, edges, base and
    outlines), None for "not given". config_path: a YAML file or None. rules: the registry
    (tdmg.rules.load_rules()); printer: the printer profile (its palette cap and nozzle).
    supersample: the factor of smooth_labels' fine map, an int >= 1
    (tdmg.smoothing.SUPERSAMPLE by default; it is part of the identity). width_mm must be a
    finite number above 0.

    A plan with more final colors than `colors` is still written, with ready false and
    not_ready_reason; the caller decides what to do (the CLI exits 1).

    Raises ColorsError for any refused input, setting, selection or output folder, with
    nothing written. An OSError while writing can leave a folder without colors.json,
    which is incomplete and must not be used. The output file hashes are integrity hashes,
    valid within this environment only (PNG bytes depend on the Pillow and zlib versions).
    """
    try:
        return _make_colors(Path(selection_dir), out_dir, _width(width_mm), flags,
                            config_path, rules, printer, supersample)
    except (SelectionError, ColorConfigError, ColorError, SmoothingError, RecordError) as e:
        raise ColorsError(str(e)) from None


def _make_colors(selection_dir, out_dir, width_mm, flags, config_path, rules, printer,
                 supersample) -> dict:
    resolved = resolve_color_config(flags, config_path, rules, printer)
    settings = resolved.settings
    sigma, edge_rule = edge_sigma_px(settings["edges"], rules)
    sel = read_selection(selection_dir, cutout=True)
    create_folder = check_output_dir(out_dir)

    mm_per_px = mask_mm_per_px(sel.mask, width_mm)
    limits = printable_limits_px(mm_per_px, rules, printer)
    plan = plan_colors(sel.cutout_rgb, sel.mask, settings, limits, rules)
    extracted, outline, merges = plan.extracted, plan.outline, plan.merges
    merged, cleaned, log = plan.merged, plan.cleaned, plan.log
    n_ext = len(extracted.hex)
    k = len(cleaned.hex)
    if k >= LABELS_OUTSIDE:     # extract is capped below it (tdmg.color_config.MAX_EXTRACT)
        raise ColorsError(f"{k} colors do not fit an 8-bit labels.png with "
                          f"{LABELS_OUTSIDE} outside")
    check_base(settings["base"], k)
    base_index = 0 if settings["base"] == "auto" else settings["base"]
    ready = k <= settings["colors"]
    reason = None if ready else not_ready_reason(
        k, settings["colors"], len(merges), palette_cap(printer),
        outline=bool(outline.family),
        suggestions=[(p.j, p.i, p.hex_j, p.hex_i) for p in plan.shade_pairs])
    smoothed = smooth_labels(cleaned.labels, sigma, supersample)
    vanished = set(smoothed.vanished)
    into = dict(merges)
    core = outline.core
    outline_record = {
        "outlines": settings["outlines"],
        "outline_color": _json_plain(settings["outline_color"]),
        "found_by": outline.found_by, "family": list(outline.family),
        "family_hex": [extracted.hex[i] for i in outline.family],
        "core": core, "core_hex": None if core is None else extracted.hex[core],
        "thinness": list(outline.thinness),
        "thresholds": dict(outline.thresholds),
        "keep_width": (None if outline.keep_width_mm is None else
                       {"mm": outline.keep_width_mm, "px": outline.keep_width_px}),
        "method": outline.method, "notes": list(outline.notes)}
    shade_record = shade_pair_records(plan.shade_pairs)
    extraction_palette = [
        {"index": i, "hex": extracted.hex[i], "rgb": extracted.rgb[i].tolist(),
         "lab": extracted.lab[i].tolist(), "share": extracted.shares[i],
         "count": extracted.counts[i], "fate": plan.fate[i],
         "final_index": plan.final_index[i], "merged_into": into.get(i)}
        for i in range(n_ext)]

    labels8 = np.where(cleaned.labels == OUTSIDE, LABELS_OUTSIDE,
                       cleaned.labels).astype(np.uint8)
    palette = [{"index": i, "hex": cleaned.hex[i], "rgb": cleaned.rgb[i].tolist(),
                "lab": cleaned.lab[i].tolist(), "share": cleaned.shares[i],
                "count": cleaned.counts[i], "base": i == base_index} for i in range(k)]
    regions = _regions_image(sel.cutout_rgb, sel.mask, palette, smoothed.fine,
                             smoothed.supersample, changed_mask(merged, cleaned),
                             settings["edges"], vanished, extraction_palette, outline_record,
                             shade_record, reason)
    files = {"labels.png": png_bytes(labels8), "regions.png": png_bytes(regions)}

    methods = {"colors": COLORS_ALGORITHM_VERSION, "quantize": METHOD,
               "outline": outline.method, "shade": SHADE_METHOD, "cleanup": CLEANUP_METHOD,
               "labels": LABELS_METHOD}
    used_rules = {limits.opening_rule: float(rules[limits.opening_rule].default),
                  limits.island_rule: float(rules[limits.island_rule].default)}
    if edge_rule is not None:
        used_rules[edge_rule] = sigma
    # The outline and shade rules that decided this plan (outline.thresholds holds the
    # first two when they were used).
    used_rules.update(dict(outline.thresholds))
    used_rules.update(dict(plan.shade_rules))
    record_settings = resolved.as_record()
    limits_record = _json_plain(dataclasses.asdict(limits))
    identity = colors_identity(
        methods=methods, selection_id=sel.record["selection_id"],
        cutout_pixels_sha256=sel.cutout_pixels_sha256,
        mask_pixels_sha256=sel.record["mask_pixels_sha256"],
        settings=record_settings["settings"], width_mm=width_mm, printer=printer.id,
        nozzle_diameter_mm=limits.nozzle_diameter_mm, rules=used_rules,
        supersample=smoothed.supersample)
    record = {
        "schema": RECORD_SCHEMA, "tdmg_version": __version__,
        "algorithm": COLORS_ALGORITHM_VERSION,
        "colors_id": colors_id(identity), "identity": identity,
        "input": {"selection_id": sel.record["selection_id"],
                  "selection_json_sha256": sel.record_sha256,
                  "cutout_pixels_sha256": sel.cutout_pixels_sha256,
                  "mask_pixels_sha256": sel.record["mask_pixels_sha256"],
                  "width_px": int(sel.mask.shape[1]), "height_px": int(sel.mask.shape[0])},
        "settings": record_settings,
        "width_mm": width_mm, "mm_per_px": mm_per_px, "printer": printer.id,
        "limits": limits_record,
        "palette": palette, "base_index": base_index,
        "ready": ready, "not_ready_reason": reason,
        # The extracted colors, by extraction index (the indices outline_color and merge
        # use). fate, followed through the steps' index arrays: final (final_index is its
        # index in the final palette; this includes the outline core when its wide areas
        # remain), merged (merged_into: the extraction index it went to), outline (an
        # outline-family member that the outline handling removed) or cleanup (cleanup
        # removed it); final_index is null unless the fate is final.
        "extraction": {"extract": settings["extract"], "n_extracted": n_ext,
                       "palette": extraction_palette},
        # The outline step: the family (extraction indices and hexes), its core (the
        # darkest member, which keeps the wide areas and draws the kept band), every
        # extracted color's thinness, the thresholds used (rule id: value) and the kept
        # band's width.
        "outline": outline_record,
        "merges": [{"from": a, "from_hex": extracted.hex[a], "into": b,
                    "into_hex": extracted.hex[b]} for a, b in merges],
        # Likely shade pairs among the colors left after the outline step and the merges
        # (the core excluded), by extraction index; flagged for the owner, never applied.
        # merge: the suggested [from, into].
        "shade_pairs": shade_record,
        # The extraction (quantize at extract colors). dropped: palette colors the final
        # nearest reassignment left empty.
        "quantize": {"iterations": extracted.iterations, "converged": extracted.converged,
                     "n_requested": extracted.n_requested,
                     "n_distinct_colors": extracted.n_distinct_colors,
                     "dropped": extracted.dropped, "palette_hex": list(extracted.hex)},
        # The log's limits are the top-level "limits"; they are not repeated here.
        "cleanup": {k: v for k, v in _json_plain(dataclasses.asdict(log)).items()
                    if k != "limits"},
        "smoothing": {"sigma_px": sigma, "edge_rule": edge_rule,
                      "supersample": smoothed.supersample,  # method: methods.labels
                      "vanished": [{"index": i, "hex": cleaned.hex[i]}
                                   for i in smoothed.vanished]},
        "methods": methods,
        "preview": {"scale": PREVIEW_SCALE,
                    "right_panel": "final colors from the fine map, nearest fine pixel to "
                                   "each preview pixel centre; image mask outside",
                    "outer_outline": OUTER_OUTLINE,
                    "changed_outline": "inner edge of the pixels cleanup changed, black and "
                                       "white dashes"},
        "outputs": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        # Decoded pixels, so a pixel difference can be told from a PNG encoding difference.
        "regions_pixels_sha256": pixels_sha256(regions),
        "environment": {**environment(), "scipy": scipy.__version__},
        "review": REVIEW,
    }
    try:
        data = record_text(record)
    except ValueError as e:
        raise ColorsError(f"the record cannot be stored as strict JSON: {e}") from None
    write_outputs(out_dir, files, RECORD_NAME, data, create_folder=create_folder)
    return json.loads(data)


def not_ready_reason(n_final: int, colors: int, n_merges: int, cap: int, *,
                     outline: bool = False, suggestions=()) -> str:
    """Why a plan is not ready, for the record, the preview and the CLI.

    cap: the printer's palette cap (tdmg.color_config.palette_cap). Raising colors is
    suggested only when colors is below it; at the cap, merges are the only way. outline:
    whether an outline family was handled (named among the steps). suggestions: the
    flagged shade pairs as (from, into, from_hex, into_hex) merges, by extraction index;
    each is listed as "consider merge: [[from, into]] (#from into #into)".
    """
    steps = (["outline handling"] if outline else []) + (
        [f"{n_merges} merge(s)"] if n_merges else []) + ["cleanup"]
    after = steps[0] if len(steps) == 1 else ", ".join(steps[:-1]) + " and " + steps[-1]
    limit = f"{colors} (the printer's palette)" if colors >= cap else f"{colors}"
    advice = ("add merge pairs (by extraction index, from regions.png) to the config file"
              + ("" if colors >= cap else f", or raise colors up to the printer's palette "
                                          f"({cap})"))
    flagged = "; ".join(f"consider merge: [[{a}, {b}]] ({ha} into {hb})"
                        for a, b, ha, hb in suggestions)
    if flagged:
        flagged = "; flagged shade pairs: " + flagged
    return (f"{n_final} colors remain after {after}, but colors allows at most {limit}; "
            f"{advice}{flagged}")


# --- verify_colors: reading a colors folder back (design step 2, geometry) ---------------

EDGE_RULES = {"smooth": SMOOTH_RULE, "furry": FURRY_RULE, "exact": None}
SETTING_KEYS = KEYS


@dataclass(frozen=True, eq=False)
class VerifiedColors:
    """A tdmg colors folder, read and checked by verify_colors. labels is read-only.

    record: colors.json as parsed. labels: (H, W) int32, the palette index per pixel and
    OUTSIDE (-1) outside the mask, as smooth_labels takes it. palette: the record's palette
    entries. settings: the resolved settings (every key of tdmg.color_config.KEYS).
    base_index: the base color's index. sigma_px and supersample: what smooth_labels needs
    to recompute the fine map. width_mm and mm_per_px: the scale the cleanup used.
    """

    record: dict
    labels: np.ndarray
    palette: list
    settings: dict
    base_index: int
    sigma_px: float
    supersample: int
    width_mm: float
    mm_per_px: float


def verify_colors(colors_dir, selection_dir, *, check_preview: bool = True) -> VerifiedColors:
    """Read a tdmg colors folder and check it against its selection, or raise ColorsError.
    Nothing is written.

    selection_dir is required, not optional: the tie between labels.png and the
    selection's mask (labels exactly inside it) is what lets design step 2 (geometry) clip
    the colors to the
    R1 outline, so a caller cannot skip it by leaving an argument out.

    Checks, in order:
    1. colors.json is UTF-8 JSON with schema RECORD_SCHEMA and an identity block;
       colors_id is colors_id(identity). The plan is ready: ready is true (a plan written
       with ready false is refused with its reason).
    2. The identity's values have valid types: settings as ColorConfig takes them (colors
       an int, extract an int 2..MAX_EXTRACT, edges a preset, base auto or a non-bool int,
       outlines drop or keep, outline_color auto, none or a list, merge a list of valid
       pairs), supersample an int >= 1, width_mm finite and above 0, the rules exactly the
       two cleanup rules, the edges preset's rule (none for exact), the two shade rules,
       the thin share when outline_color is auto, and the keep width when outlines is keep
       and the family is not empty; each a finite number, and the sigma finite and >= 0.
       As when resolving: extract >= colors, and check_extraction_indices against
       extraction.n_extracted (an int 1..extract), outline.family (sorted, distinct indices
       below it) and outline.core.
    3. The record fields that repeat the identity equal it: input hashes, settings,
       width_mm, printer, methods (and algorithm), limits (rule ids, nozzle, opening width,
       island area), smoothing (supersample, edge_rule, sigma_px), the extraction count
       (extraction.extract, quantize.n_requested), outline (outlines, outline_color,
       method, thresholds) and the merges' pairs.
    4. The palette: indices 0..k-1; each hex is the "#rrggbb" of its rgb (ints 0..255);
       counts do not increase; base_index and the base flags agree with settings.base;
       k is at most settings.colors (as ready says). The extraction palette: indices
       0..n-1; its hex codes are quantize.palette_hex and each is the "#rrggbb" of its rgb;
       each lab is srgb_to_lab of its rgb, exactly. The outline: found_by matches
       outline_color (auto, none, or config for a list); the family is the list (config),
       empty (none), or exactly the indices whose recorded thinness is above the thin
       share (auto); thinness has one number from 0 to 1 per extracted color; family_hex
       is the family's colors; the core is outline_core of the family on the recorded Lab
       (the darkest member), with its hex; keep_width is set exactly when the keep width
       rule is used. The merges' from_hex and into_hex are the extraction's colors. Each
       merged_into is the merge setting's; each fate is one of FATES, with final exactly
       when final_index is set, merged exactly when merged_into is set, outline only for
       an index in outline.family (and always for a family member other than the core),
       and cleanup only for a hex in cleanup.dropped_hex; each final_index is a final
       palette index with the same hex; and every final palette entry is the final_index
       of at least one extraction entry with the same hex. The shade pairs are what
       tdmg.color.shade_pairs gives again on the recorded Lab, for the colors whose fate
       is final or cleanup other than the core, with the identity's two shade rules.
    5. The outputs are exactly labels.png and regions.png, and each file's SHA-256 is the
       record's. With check_preview (the default), regions.png is decoded and its pixels
       must hash to regions_pixels_sha256; design step 2 passes False and skips the decode.
    6. labels.png is 8-bit grey of the recorded size; every value is 255 or a palette
       index; each index's pixel count is its palette count, and each share is that count
       over the labelled pixels (the same division make_colors used).
    7. mm_per_px is mask_mm_per_px(labelled pixels, width_mm), and it equals the record's
       mm_per_px and limits.mm_per_px exactly; limits.min_width_px and min_area_px equal
       the arithmetic of tdmg.color.printable_limits_px on the identity's rule values,
       nozzle and that scale (the same float operations, so equality is exact); so does
       outline.keep_width.px, as the keep width over that scale.
    8. The selection (read_selection, with the cutout): its selection_id, mask and cutout
       pixel hashes are the identity's, and labels.png is 255 exactly outside its mask.

    What it cannot check: other record fields (such as the cleanup log, the final
    palette's Lab values and the thinness values themselves) are as the record says; only a
    rerun of make_colors reproduces them.
    OSError (an unreadable file) propagates; the CLI maps it to exit 2, as for colors.
    """
    colors_dir = Path(colors_dir)
    path = colors_dir / RECORD_NAME
    if not path.is_file():
        raise ColorsError(f"{path} not found; give a tdmg colors output folder")
    try:
        record = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ColorsError(f"{path} is not valid JSON: {e}") from None
    if not isinstance(record, dict) or record.get("schema") != RECORD_SCHEMA:
        raise ColorsError(f"{path} is not a {RECORD_SCHEMA} record")
    if not isinstance(record.get("identity"), dict):
        raise ColorsError(f"{path} has no identity block")
    try:
        return _verify(colors_dir, record, selection_dir, check_preview)
    except (KeyError, TypeError, AttributeError, IndexError) as e:
        raise ColorsError(f"{path} is missing or has an invalid field: {e!r}") from None
    except ArithmeticError as e:          # OverflowError, ZeroDivisionError ...
        raise ColorsError(f"{path} has values that cannot be computed with: {e}") from None


def _inconsistent(field: str) -> ColorsError:
    return ColorsError(f"colors.json is inconsistent: {field} does not match the identity")


def _identity_values(ident: dict, family) -> tuple[dict, float, int, float, str | None]:
    """Check the identity's types; return its settings, width, supersample, sigma and the
    edges rule id. family: the record's outline family (whether the keep width is used)."""
    settings = ident["settings"]
    if not isinstance(settings, dict) or set(settings) != set(SETTING_KEYS):
        raise ColorsError(f"identity.settings must hold exactly {', '.join(SETTING_KEYS)}")
    try:
        ColorConfig.model_validate(settings)
    except ValidationError as e:
        err = e.errors()[0]
        raise ColorsError(f"identity.settings.{err['loc'][0]} is invalid: {err['msg']} "
                          f"(got {err['input']!r})") from None
    width = _width(ident["width_mm"])
    try:
        supersample = _supersample(ident["supersample"])
    except SmoothingError as e:
        raise ColorsError(f"identity.{e}") from None
    edge_rule = EDGE_RULES[settings["edges"]]
    rules = ident["rules"]
    want = ({OPENING_RULE, ISLAND_RULE, SHADE_HUE_RULE, SHADE_CHROMA_RULE}
            | ({edge_rule} if edge_rule else set())
            | ({THIN_SHARE_RULE} if settings["outline_color"] == "auto" else set())
            | ({KEEP_WIDTH_RULE} if settings["outlines"] == "keep" and family else set()))
    if not isinstance(rules, dict) or set(rules) != want:
        raise ColorsError(f"identity.rules must hold exactly {', '.join(sorted(want))}")
    for rule_id, value in rules.items():
        if (isinstance(value, bool) or not isinstance(value, numbers.Real)
                or not math.isfinite(value)):
            raise ColorsError(f"identity.rules[{rule_id!r}] must be a finite number, "
                              f"got {value!r}")
    try:
        sigma = _sigma_or_zero(0.0 if edge_rule is None else rules[edge_rule])
    except SmoothingError as e:
        raise ColorsError(f"identity.rules: {e}") from None
    return settings, width, supersample, sigma, edge_rule


def _verify(colors_dir: Path, record: dict, selection_dir, check_preview: bool
            ) -> VerifiedColors:
    ident = record["identity"]
    if colors_id(ident) != record["colors_id"]:
        raise ColorsError("colors.json is inconsistent: colors_id does not match its identity")
    if record["ready"] is not True:
        if record["ready"] is False:
            raise ColorsError("this color plan is not ready, so it cannot be built: "
                              f"{record['not_ready_reason']}")
        raise ColorsError("colors.json is inconsistent: ready must be true or false")
    if record["not_ready_reason"] is not None:
        raise ColorsError("colors.json is inconsistent: ready is true but there is a "
                          "not_ready_reason")
    outline = record["outline"]
    settings, width_mm, supersample, sigma, edge_rule = _identity_values(ident,
                                                                         outline["family"])
    _check_extraction_settings(settings, record["extraction"]["n_extracted"],
                               outline["family"], outline["core"])
    inp, sm, lim = record["input"], record["smoothing"], record["limits"]
    rules = ident["rules"]
    nozzle = ident["nozzle_diameter_mm"]
    opening_mm = float(rules[OPENING_RULE])
    island_mm2 = (float(rules[ISLAND_RULE]) * nozzle) ** 2   # as printable_limits_px
    duplicates = {
        "input.selection_id": (inp["selection_id"], ident["selection_id"]),
        "input.cutout_pixels_sha256": (inp["cutout_pixels_sha256"],
                                       ident["cutout_pixels_sha256"]),
        "input.mask_pixels_sha256": (inp["mask_pixels_sha256"], ident["mask_pixels_sha256"]),
        "settings.settings": (record["settings"]["settings"], settings),
        "width_mm": (record["width_mm"], width_mm),
        "printer": (record["printer"], ident["printer"]),
        "methods": (record["methods"], ident["methods"]),
        "algorithm": (record["algorithm"], ident["methods"]["colors"]),
        "limits.opening_rule": (lim["opening_rule"], OPENING_RULE),
        "limits.island_rule": (lim["island_rule"], ISLAND_RULE),
        "limits.nozzle_diameter_mm": (lim["nozzle_diameter_mm"], nozzle),
        "limits.opening_width_mm": (lim["opening_width_mm"], opening_mm),
        "limits.island_area_mm2": (lim["island_area_mm2"], island_mm2),
        "smoothing.supersample": (sm["supersample"], supersample),
        "smoothing.edge_rule": (sm["edge_rule"], edge_rule),
        "smoothing.sigma_px": (sm["sigma_px"], sigma),
        "extraction.extract": (record["extraction"]["extract"], settings["extract"]),
        "quantize.n_requested": (record["quantize"]["n_requested"], settings["extract"]),
        "outline.outlines": (record["outline"]["outlines"], settings["outlines"]),
        "outline.outline_color": (record["outline"]["outline_color"],
                                  settings["outline_color"]),
        "outline.method": (record["outline"]["method"], ident["methods"]["outline"]),
        "outline.thresholds": (record["outline"]["thresholds"],
                               {r: ident["rules"][r] for r in (THIN_SHARE_RULE, KEEP_WIDTH_RULE)
                                if r in ident["rules"]}),
        "merges": ([[m["from"], m["into"]] for m in record["merges"]], settings["merge"]),
    }
    for field, (got, want) in duplicates.items():
        if got != want:
            raise _inconsistent(field)
    palette = record["palette"]
    k = len(palette)
    base_index = _check_palette(palette, record["base_index"], settings["base"])
    if k > settings["colors"]:
        raise ColorsError(f"colors.json is inconsistent: ready is true but the palette has "
                          f"{k} colors, more than colors {settings['colors']}")
    _check_extraction(record, settings, palette)
    _check_outline(record, settings, rules)
    _check_shade_pairs(record, rules)
    data = _verified_outputs(colors_dir, record, check_preview)
    labels8 = _decode(data["labels.png"], "labels.png", "L")
    if labels8.shape != (inp["height_px"], inp["width_px"]):
        raise ColorsError(f"labels.png is {labels8.shape[1]}x{labels8.shape[0]}, not the "
                          f"recorded {inp['width_px']}x{inp['height_px']}")
    inside = labels8 != LABELS_OUTSIDE
    if (labels8[inside] >= k).any():
        raise ColorsError(f"labels.png has values other than {LABELS_OUTSIDE} and the "
                          f"palette indices 0..{k - 1}")
    counts = np.bincount(labels8[inside], minlength=k).tolist()
    if counts != [p["count"] for p in palette]:
        raise ColorsError("labels.png's pixel counts do not match the palette's counts")
    total = int(inside.sum())
    if [p["share"] for p in palette] != [c / total for c in counts]:
        raise ColorsError("the palette's shares are not its counts over the labelled pixels")
    mm_per_px = mask_mm_per_px(inside, width_mm)
    for field, got, want in (
            ("mm_per_px", record["mm_per_px"], mm_per_px),
            ("limits.mm_per_px", lim["mm_per_px"], mm_per_px),
            ("limits.min_width_px", lim["min_width_px"], opening_mm / mm_per_px),
            ("limits.min_area_px", lim["min_area_px"], island_mm2 / mm_per_px ** 2),
            *((("outline.keep_width.px", outline["keep_width"]["px"],
                outline["keep_width"]["mm"] / mm_per_px),)
              if outline["keep_width"] is not None else ())):
        if got != want:
            raise ColorsError(f"colors.json is inconsistent: {field} is not what width_mm, "
                              "the rules and labels.png give")
    _check_selection(selection_dir, ident, inside)
    labels = np.where(inside, labels8.astype(np.int32), OUTSIDE).astype(np.int32)
    labels.flags.writeable = False
    return VerifiedColors(record=record, labels=labels, palette=palette,
                          settings=dict(settings), base_index=base_index, sigma_px=sigma,
                          supersample=supersample, width_mm=width_mm, mm_per_px=mm_per_px)


def _check_palette(palette: list, base_index, base) -> int:
    """Indices 0..k-1, hex = rgb, counts not increasing, base flags agree; the base index."""
    k = len(palette)
    if [p["index"] for p in palette] != list(range(k)):
        raise ColorsError("colors.json is inconsistent: palette indices are not 0..k-1")
    for p in palette:
        rgb = p["rgb"]
        if (not isinstance(rgb, list) or len(rgb) != 3
                or not all(type(v) is int and 0 <= v <= 255 for v in rgb)):
            raise ColorsError(f"palette entry {p['index']}: rgb must be three ints 0..255")
        if p["hex"] != "#" + "".join(f"{v:02x}" for v in rgb):
            raise ColorsError(f"palette entry {p['index']}: hex {p['hex']!r} is not its rgb")
    counts = [p["count"] for p in palette]
    if counts != sorted(counts, reverse=True):
        raise ColorsError("colors.json is inconsistent: palette counts increase")
    want = 0 if base == "auto" else base
    if base_index != want or [p["base"] for p in palette] != [i == want for i in range(k)]:
        raise ColorsError("colors.json is inconsistent: base_index and the palette's base "
                          "flags do not match settings.base")
    return want


def _check_extraction_settings(settings: dict, n_extracted, family, core) -> None:
    """extract >= colors, and the setting indices against the recorded extraction size,
    outline family and core, as make_colors checked them (tdmg.color_config)."""
    if settings["extract"] < settings["colors"]:
        raise ColorsError(f"identity.settings: extract {settings['extract']} is below colors "
                          f"{settings['colors']}")
    if (isinstance(n_extracted, bool) or not isinstance(n_extracted, int)
            or not 1 <= n_extracted <= settings["extract"]):
        raise ColorsError("colors.json is inconsistent: extraction.n_extracted must be an "
                          "int from 1 to extract")
    if (not isinstance(family, list) or family != sorted(set(family))
            or not all(type(i) is int and 0 <= i < n_extracted for i in family)):
        raise ColorsError("colors.json is inconsistent: outline.family must be sorted, "
                          "distinct extraction indices")
    if core is not None and core not in family:
        raise ColorsError("colors.json is inconsistent: outline.core is not in outline.family")
    try:
        check_extraction_indices(settings["outline_color"], settings["merge"], n_extracted,
                                 family, core)
    except ColorConfigError as e:
        raise ColorsError(f"identity.settings: {e}") from None


def _check_extraction(record: dict, settings: dict, palette: list) -> None:
    """The extraction palette agrees with quantize, the outline and merge settings, the
    cleanup and the final palette."""
    ext = record["extraction"]["palette"]
    outline = record["outline"]
    oc = settings["outline_color"]
    want_found_by = oc if oc in ("auto", "none") else "config"
    if outline["found_by"] != want_found_by:
        raise _inconsistent("outline.found_by")
    if isinstance(oc, list) and sorted(oc) != outline["family"]:
        raise ColorsError("colors.json is inconsistent: outline.family is not the "
                          "outline_color list")
    if oc == "none" and outline["family"] != []:
        raise ColorsError("colors.json is inconsistent: outline.family is not empty but "
                          "outline_color is none")
    if [e["index"] for e in ext] != list(range(len(ext))) or (
            record["extraction"]["n_extracted"] != len(ext)):
        raise ColorsError("colors.json is inconsistent: extraction indices are not 0..n-1")
    if [e["hex"] for e in ext] != record["quantize"]["palette_hex"]:
        raise ColorsError("colors.json is inconsistent: the extraction palette is not "
                          "quantize.palette_hex")
    hexes = [e["hex"] for e in ext]
    for e in ext:
        rgb = e["rgb"]
        if (not isinstance(rgb, list) or len(rgb) != 3
                or not all(type(v) is int and 0 <= v <= 255 for v in rgb)
                or e["hex"] != "#" + "".join(f"{v:02x}" for v in rgb)):
            raise ColorsError(f"colors.json is inconsistent: extraction entry {e['index']}'s "
                              "rgb is not three ints 0..255 with its hex")
        if e["lab"] != srgb_to_lab(np.array([rgb], np.uint8))[0].tolist():
            raise ColorsError(f"colors.json is inconsistent: extraction entry {e['index']}'s "
                              "lab is not the CIELAB of its rgb")
    for m in record["merges"]:
        for end in ("from", "into"):
            if m[f"{end}_hex"] != hexes[m[end]]:
                raise ColorsError(f"colors.json is inconsistent: the merges' {end}_hex is not "
                                  "the extraction's color")
    into = {a: b for a, b in settings["merge"]}
    dropped = set(record["cleanup"]["dropped_hex"])
    for e in ext:
        i, fate, f = e["index"], e["fate"], e["final_index"]
        if e["merged_into"] != into.get(i):
            raise ColorsError(f"colors.json is inconsistent: extraction entry {i}'s "
                              "merged_into is not the merge setting's")
        why = None
        if fate not in FATES:
            why = f"the fates are {', '.join(FATES)}"
        elif (fate == "final") != (f is not None):
            why = "final_index is not set" if fate == "final" else "it has a final_index"
        elif (fate == "merged") != (e["merged_into"] is not None):
            why = "merged_into is not set" if fate == "merged" else "merged_into is set"
        elif fate == "outline" and i not in outline["family"]:
            why = "it is not in outline.family"
        elif fate != "outline" and i in outline["family"] and i != outline["core"]:
            why = "it is an outline-family member other than the core"
        elif fate == "cleanup" and e["hex"] not in dropped:
            why = "its hex is not in cleanup.dropped_hex"
        if why:
            raise ColorsError(f"colors.json is inconsistent: extraction entry {i} has fate "
                              f"{fate!r} but {why}")
        if f is not None and (isinstance(f, bool) or not isinstance(f, int)
                              or not 0 <= f < len(palette) or palette[f]["hex"] != e["hex"]):
            raise ColorsError(f"colors.json is inconsistent: extraction entry {i}'s "
                              "final_index is not the final palette entry with its color")
    for k, p in enumerate(palette):
        if not any(e["final_index"] == k and e["hex"] == p["hex"] for e in ext):
            raise ColorsError(f"colors.json is inconsistent: final color {k} ({p['hex']}) is "
                              "not the final_index of an extraction entry with the same hex")


def _check_outline(record: dict, settings: dict, rules: dict) -> None:
    """The outline block: thinness, the auto family, family_hex, the core and keep_width."""
    outline = record["outline"]
    ext = record["extraction"]["palette"]
    family = outline["family"]
    thin = outline["thinness"]
    if not isinstance(thin, list) or len(thin) != len(ext) or not all(
            not isinstance(t, bool) and isinstance(t, numbers.Real) and 0 <= t <= 1
            for t in thin):
        raise ColorsError("colors.json is inconsistent: outline.thinness must hold one "
                          "number from 0 to 1 per extracted color")
    if outline["found_by"] == "auto":
        t = rules[THIN_SHARE_RULE]
        if family != [i for i, v in enumerate(thin) if v > t]:
            raise ColorsError("colors.json is inconsistent: outline.family is not the colors "
                              f"whose thinness is above {THIN_SHARE_RULE} ({t})")
    if outline["family_hex"] != [ext[i]["hex"] for i in family]:
        raise _inconsistent("outline.family_hex")
    core = outline_core(family, [e["lab"] for e in ext])
    if outline["core"] != core:
        raise ColorsError("colors.json is inconsistent: outline.core is not the darkest "
                          "family member")
    if outline["core_hex"] != (None if core is None else ext[core]["hex"]):
        raise _inconsistent("outline.core_hex")
    keep = KEEP_WIDTH_RULE in rules
    kw = outline["keep_width"]
    if (kw is None) == keep or (keep and (set(kw) != {"mm", "px"}
                                          or kw["mm"] != rules[KEEP_WIDTH_RULE])):
        raise _inconsistent("outline.keep_width")


def _check_shade_pairs(record: dict, rules: dict) -> None:
    """The shade pairs are recomputed from the extraction palette's Lab (checked to be the
    CIELAB of its rgb) and the identity's shade rules."""
    ext = record["extraction"]["palette"]
    core = record["outline"]["core"]
    candidates = [e["index"] for e in ext
                  if e["fate"] in ("final", "cleanup") and e["index"] != core]
    want = shade_pair_records(shade_pairs([e["lab"] for e in ext], [e["hex"] for e in ext],
                                          candidates, rules[SHADE_HUE_RULE],
                                          rules[SHADE_CHROMA_RULE]))
    if record["shade_pairs"] != _json_plain(want):
        raise ColorsError("colors.json is inconsistent: shade_pairs are not the pairs the "
                          "extraction palette and the shade rules give")


def _verified_outputs(colors_dir: Path, record: dict, check_preview: bool) -> dict[str, bytes]:
    outputs = record["outputs"]
    if not isinstance(outputs, dict) or set(outputs) != set(OUTPUT_FILES):
        raise ColorsError(f"colors.json outputs must be exactly {', '.join(OUTPUT_FILES)}")
    data = {}
    for name in OUTPUT_FILES:
        path = colors_dir / name
        if not path.is_file():
            raise ColorsError(f"{path} not found")
        data[name] = path.read_bytes()
        if hashlib.sha256(data[name]).hexdigest() != outputs[name]:
            raise ColorsError(f"{name} does not match colors.json")
    if check_preview and pixels_sha256(_decode(data["regions.png"], "regions.png", "RGB")) != (
            record["regions_pixels_sha256"]):
        raise ColorsError("regions.png's pixels do not match regions_pixels_sha256")
    return data


def _decode(data: bytes, name: str, mode: str) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.mode != mode:
                raise ColorsError(f"{name} has mode {im.mode}, not {mode}")
            return np.asarray(im).copy()
    except (OSError, Image.DecompressionBombError) as e:
        raise ColorsError(f"{name} is not a readable image: {e}") from None


def _check_selection(selection_dir, ident: dict, inside: np.ndarray) -> None:
    try:
        sel = read_selection(selection_dir, cutout=True)
    except SelectionError as e:
        raise ColorsError(str(e)) from None
    if (sel.record["selection_id"], sel.record["mask_pixels_sha256"],
            sel.cutout_pixels_sha256) != (ident["selection_id"], ident["mask_pixels_sha256"],
                                          ident["cutout_pixels_sha256"]):
        raise ColorsError("this color plan was made from another selection (selection_id, "
                          "mask or cutout differ)")
    if inside.shape != sel.mask.shape or not np.array_equal(inside, sel.mask):
        raise ColorsError("labels.png labels pixels outside the selection's mask, or leaves "
                          "pixels inside it unlabelled")

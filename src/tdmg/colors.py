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

tdmg.color, tdmg.color_outline, tdmg.color_plan and tdmg.smoothing stay free of I/O; this
module does the reading and writing, the record and the preview; tdmg.colors_verify reads
a folder back (verify_colors).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import numbers
from pathlib import Path

import numpy as np
import scipy
import shapely
from PIL import Image, ImageDraw, ImageFont

from tdmg import __version__
from tdmg.color import (
    CLEANUP_METHOD,
    METHOD,
    OUTSIDE,
    ColorError,
    changed_mask,
    printable_limits_px,
)
from tdmg.color_config import (
    SMOOTH_RULE,
    ColorConfigError,
    check_base,
    edge_sigma_px,
    palette_cap,
    resolve_color_config,
)
from tdmg.color_outline import SHADE_METHOD
from tdmg.color_plan import plan_colors
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
from tdmg.selection import CHECKER_CELL_PX, SelectionError, pixels_sha256, read_selection
from tdmg.smoothing import (
    LABELS_METHOD,
    SUPERSAMPLE,
    SmoothingError,
    check_supersample,
    smooth_labels,
    smooth_outline,
)

# colors-2 (Tasks 7b and 7c, unreleased): extraction at `extract`, the outline step, the
# owner's merges, the shade-pair flags and the ready flag. tdmg.colors/2 adds the
# extraction, outline, merges, shade_pairs and ready fields; tdmg.colors/3 (Task 7e-b)
# adds the outline_width_mm setting and the outline block's stroke_width_px,
# wide_components and specks_not_drawn (the changed outline step is methods.outline);
# tdmg.colors/4 (Task 8 review) adds the extraction fate "band".
COLORS_ALGORITHM_VERSION = "colors-2"
RECORD_SCHEMA = "tdmg.colors/4"
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
OUTER_OUTLINE = ("outer outline: smoothed as the model will be built. grey checker: "
                 "background, not part of the model")
BASE_HINT = ("base: auto = the largest color (index 0); set base: N in the config file to "
             "choose another")
# The background behind the subject (Task 7e-b): a checker of two mid greys. The owner read
# white areas (cuffs, eye white) on tdmg select's light-grey checker (200/235) as empty
# spots; the 7e-a record found no hole there. Mid greys (L* about 47 and 60) are far from
# white and black, carry no hue (the owner's images have blue-grey tones, so a blue-grey
# background could be confused with them), and the checker pattern marks them as
# background. Display only, not a threshold.
BACKGROUND_SHADES = (112, 144)
FINAL_HEADING = "final colors (base uses these indices):"
EXTRACTED_HEADING = ("extracted colors ({n}): outline_color and merge in the config file use "
                     "these indices")
FLAGGED = "; flagged shade pairs: "   # where not_ready_reason lists the flagged pairs
MERGE_HINT = ("to merge two colors, add merge: [[from, into]] to the config file (extraction "
              "indices); shade pairs are only flagged, never merged for you")


def legend_rows(edges: str) -> list[str]:
    """The legend lines above the swatches in regions.png, ending with the final palette's
    heading."""
    return [LEGEND.format(edges=edges), OUTER_OUTLINE, BASE_HINT, FINAL_HEADING]


def background(h: int, w: int) -> np.ndarray:
    """H x W x 3 uint8: the preview's background, a checker of BACKGROUND_SHADES in cells
    of tdmg select's CHECKER_CELL_PX; the top-left cell uses BACKGROUND_SHADES[1]."""
    rows = (np.arange(h) // CHECKER_CELL_PX % 2).astype(bool)
    cols = (np.arange(w) // CHECKER_CELL_PX % 2).astype(bool)
    cell = rows[:, None] ^ cols[None, :]
    grey = np.where(cell, np.uint8(BACKGROUND_SHADES[0]), np.uint8(BACKGROUND_SHADES[1]))
    return grey[..., None].repeat(3, axis=2)


def outline_preview_mask(mask: np.ndarray, sigma_px: float) -> np.ndarray:
    """(H P, W P) bool, P = PREVIEW_SCALE: the preview pixels whose centre lies inside
    the R1-smoothed outer outline, smooth_outline(mask, sigma_px) (tdmg.smoothing; tdmg
    flat builds its outline with it at flat.smooth.sigma_px), in its pixel-cell
    coordinates. Preview pixel (row a, column b) has its centre at ((b + 0.5) / P,
    (a + 0.5) / P) in image pixels; shapely's contains_xy (exact; a centre on the outline
    counts as outside) decides. A straight axis-aligned edge stays on its cell edge under
    the blur, and no centre lies on a cell edge, so along such an edge this is exactly the
    enlarged mask.

    It matches tdmg flat only at flat's default smooth_px (the same rule) and only before
    flat's clean (tests/test_colors.py ties it to flat.rasterise of the uncleaned to_model
    output). Not shown: that clean (tdmg.flat.clean), which removes features narrower
    than the opening width, also rounds every convex corner to radius opening/2 and drops
    islands below the island area. Measured on the owner's images at 60 mm (Windows PC,
    2026-11-11, an inline check, not committed), it changes 20 image pixels on Roadie (16
    removed, 4 added) and 10 on Oddie, out of about 75,000 and 298,000."""
    h, w = mask.shape
    p = PREVIEW_SCALE
    region = smooth_outline(mask, sigma_px)
    out = np.zeros((h * p, w * p), bool)
    minx, miny, maxx, maxy = region.bounds
    c0, c1 = max(math.floor(minx * p) - 1, 0), min(math.ceil(maxx * p) + 1, w * p)
    r0, r1 = max(math.floor(miny * p) - 1, 0), min(math.ceil(maxy * p) + 1, h * p)
    if c0 >= c1 or r0 >= r1:
        return out
    shapely.prepare(region)
    xs = (np.arange(c0, c1) + 0.5) / p
    ys = (np.arange(r0, r1) + 0.5) / p
    out[r0:r1, c0:c1] = shapely.contains_xy(region, xs[None, :], ys[:, None])
    return out


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
    outline_color, merge, outline_width_mm), not their sources: the same values from a
    flag, a file or a default give the same plan. outline_width_mm is in it under drop
    too, where it is unused: a documented choice, so the identity is always every
    resolved setting. The rules that only give a setting's default
    (color.extract.default_count, color.outline.keep_width) are therefore not hashed
    separately; their values are settings.extract and settings.outline_width_mm.
    printer: the profile id (as flat_identity's params hold it). rules: {rule id: registry
    value} for every rule used: the two cleanup rules (the island rule's own
    min_square_side, not the derived area), the edges preset's rule, if any, the outline
    rules that decided the plan (the thin share under auto, the
    wide-area ratio with a family) and the two shade rules. The preview's outer outline
    (flat.smooth.sigma_px) is display only and not part of it. The edges sigma is hashed
    only there; `exact` has no rule and sigma 0 by definition. supersample: the fine map's
    factor. The environment is never part of it.
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


def check_width_mm(width_mm) -> float:
    if isinstance(width_mm, bool) or not isinstance(width_mm, numbers.Real):
        raise ColorsError(f"width_mm must be a number, got {width_mm!r}")
    value = float(width_mm)
    if not math.isfinite(value) or value <= 0:
        raise ColorsError(f"width_mm must be a finite number above 0, got {value}")
    return value


def json_plain(obj):
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
    encoding difference. The rows after the last swatch row (the merge hint, the flagged
    pairs, the not-ready reason) are wrapped (wrap_text) so that none is wider than the
    strip. The rows up to the last swatch are not: wrapping them would move the swatches
    that swatch_box and extracted_swatch_box locate, so their text is cut off where it is
    wider than the strip (on the owner's images it fits).
    """
    font = ImageFont.load_default_imagefont()
    last = max((i for i, (rgb, _) in enumerate(rows) if rgb is not None), default=-1)
    lines: list[tuple[tuple[int, int, int] | None, str]] = []
    for n, (rgb, text) in enumerate(rows):
        if rgb is None and n > last:
            lines.extend((None, t) for t in wrap_text(text, width - 2 * MARGIN_PX, font))
        else:
            lines.append((rgb, text))
    rows = lines
    im = Image.new("RGB", (width, ROW_PX * len(rows)), STRIP_BACKGROUND)
    draw = ImageDraw.Draw(im)
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


def wrap_text(text: str, width_px: int, font=None) -> list[str]:
    """text as lines no wider than width_px in the strip's font (Pillow's built-in bitmap
    font unless given), split at spaces; a word wider than the line is split by
    characters. Continuation lines are indented by two spaces."""
    font = font or ImageFont.load_default_imagefont()
    out, line = [], ""
    for word in text.split(" "):
        cand = word if not line else f"{line} {word}"
        if font.getlength(cand) <= width_px:
            line = cand
            continue
        if line:
            out.append(line)
        line = "  " + word if out or line else word
        while font.getlength(line) > width_px and len(line) > 3:
            cut = len(line)
            while cut > 3 and font.getlength(line[:cut]) > width_px:
                cut -= 1
            out.append(line[:cut])
            line = "  " + line[cut:]
    out.append(line)
    return out


def _regions_image(cutout_rgb: np.ndarray, mask: np.ndarray, palette: list[dict],
                   fine: np.ndarray, supersample: int, changed: np.ndarray,
                   edges: str, vanished: set[int], extracted: list[dict],
                   outline: dict, shade: list[dict],
                   not_ready_reason: str | None, outer: np.ndarray) -> np.ndarray:
    """The review preview: two panels side by side, then the swatch strip.

    fine is smooth_labels' fine map at supersample s (its shape is (H s, W s)); vanished
    holds the palette indices that smoothing removed. outer: outline_preview_mask, the
    preview pixels inside the R1-smoothed outer outline.

    Left: the cutout, PREVIEW_SCALE x nearest, on the preview background (background(),
    a mid-grey checker) outside the mask. Right: the final palette colors from the
    smoothed fine map (_fine_to_preview) inside the smoothed outer outline (outer), on the
    same background outside it: so subject pixels outside the smoothed outline show as
    background, and background pixels inside it show the fine map's color there (the
    nearest labelled pixel's color, as smooth_labels fills OUTSIDE).
    Pixels whose color cleanup changed (changed_mask) are outlined on the right: the inner
    edge of the changed region, enlarged, drawn in black and white dashes of
    CHANGED_DASH_PX along the diagonals, so it shows on any color. Below: the legend rows
    (legend_rows; they say that the outer outline is smoothed as the model will be built,
    what the background is and how to choose the base, and end with the final palette's
    heading), then one row per final
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
    board = background(h * p, w * p)
    left = np.where(big_mask[..., None], _enlarge(cutout_rgb, p), board)
    pal = np.array([e["rgb"] for e in palette], np.uint8)
    right = np.where(outer[..., None], pal[_fine_to_preview(fine, h, w, supersample)],
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
                               + extracted_text(e, outline, shade, extracted)))
    rows.append((None, MERGE_HINT))
    for line in shade_pair_lines(shade):
        rows.append((None, line))
    if not_ready_reason is not None:
        # The flagged pairs have their own rows above; the reason's list of them is not
        # repeated here (the record and the CLI keep the whole reason).
        rows.append((None, not_ready_line(not_ready_reason.split(FLAGGED)[0])))
    strip = _enlarge(_strip(rows, 2 * w), p)
    return np.concatenate([panels, strip], axis=0)


def extracted_fate(e: dict) -> str:
    """What became of an extracted color (its record entry's fate), for the preview and
    the CLI."""
    return {"final": f"final {e['final_index']}", "merged": f"merged into {e['merged_into']}",
            "outline": "outline color", "band": "covered by the kept outline",
            "cleanup": "dropped by cleanup"}[e["fate"]]


def shade_pair_lines(shade: list[dict]) -> list[str]:
    """One preview row per flagged shade pair, with the merge to consider."""
    return [f"shade pair (flagged, never merged for you): {p['i']} {p['hex_i']} and "
            f"{p['j']} {p['hex_j']}; consider merge: [{p['merge']}]" for p in shade]


def extracted_text(e: dict, outline: dict, shade: list[dict], extracted: list[dict]) -> str:
    """An extracted color's fate and flags, for the preview and the CLI: outline-family
    members say so, with their thinness (the core: "outline core, kept as final i" when it
    is in the final palette), a merge into a color that cleanup then removed says so, and a
    color in a flagged shade pair names its partners. extracted: the record's extraction
    palette (for the merges' targets)."""
    i = e["index"]
    if i in outline["family"]:
        thin = f"thin {outline['thinness'][i]:.1%}"
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
        if e["fate"] == "merged" and extracted[e["merged_into"]]["fate"] == "cleanup":
            text += " (then removed by cleanup)"
    partners = sorted(p["j"] if p["i"] == i else p["i"] for p in shade if i in (p["i"], p["j"]))
    if partners:
        text += "; shade pair with " + ", ".join(str(k) for k in partners)
    return text


def shade_pair_records(pairs) -> list[dict]:
    """The record's shade_pairs entries (tdmg.color_outline.ShadePair, by extraction index)."""
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
        return _make_colors(Path(selection_dir), out_dir, check_width_mm(width_mm), flags,
                            config_path, rules, printer, supersample)
    except (SelectionError, ColorConfigError, ColorError, SmoothingError, RecordError) as e:
        raise ColorsError(str(e)) from None


def _make_colors(selection_dir, out_dir, width_mm, flags, config_path, rules, printer,
                 supersample) -> dict:
    resolved = resolve_color_config(flags, config_path, rules, printer)
    edge_sigma_px(resolved.settings["edges"], rules)    # refuse a bad preset before reading
    sel = read_selection(selection_dir, cutout=True)
    create_folder = check_output_dir(out_dir)
    record, files, _ = build_colors(sel, width_mm, resolved.settings, resolved.as_record(),
                                    rules, printer, supersample, render=True)
    try:
        data = record_text(record)
    except ValueError as e:
        raise ColorsError(f"the record cannot be stored as strict JSON: {e}") from None
    write_outputs(out_dir, files, RECORD_NAME, data, create_folder=create_folder)
    return json.loads(data)


# The record fields that build_colors(render=False) sets to None, because they depend on
# the fine map (an OpenCV blur, not shown to be bit-identical across machines), on the PNG
# encoder or on the software versions. verify_colors compares every other field of a
# rebuilt record with the stored one. Dotted names are nested fields.
UNRENDERED_FIELDS = ("tdmg_version", "environment", "outputs", "regions_pixels_sha256",
                     "smoothing.vanished")


def build_colors(sel, width_mm: float, settings, record_settings: dict, rules: dict,
                 printer: PrinterProfile, supersample: int, *, render: bool
                 ) -> tuple[dict, dict, np.ndarray]:
    """A plan's record, output files and labels.png pixels (uint8, LABELS_OUTSIDE outside
    the mask), in memory; nothing is read or written.

    sel: a read_selection result with the cutout. settings: the resolved settings;
    record_settings: their record form (settings, sources, config_sha256), stored as given.
    render: True makes the fine map, labels.png and regions.png (make_colors). False
    (verify_colors' rebuild) skips them: files is empty and the UNRENDERED_FIELDS are
    None. Raises what plan_colors and the checks below raise.
    """
    sigma, edge_rule = edge_sigma_px(settings["edges"], rules)
    supersample = check_supersample(supersample)
    mm_per_px = mask_mm_per_px(sel.mask, width_mm)
    limits = printable_limits_px(mm_per_px, rules, printer)
    plan = plan_colors(sel.cutout_rgb, sel.mask, settings, limits, rules)
    extracted, outline, merges = plan.extracted, plan.outline, plan.merges
    cleaned, log = plan.cleaned, plan.log
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
    smoothed = smooth_labels(cleaned.labels, sigma, supersample) if render else None
    into = dict(merges)
    core = outline.core
    outline_record = {
        "outlines": settings["outlines"],
        "outline_color": json_plain(settings["outline_color"]),
        "found_by": outline.found_by, "family": list(outline.family),
        "family_hex": [extracted.hex[i] for i in outline.family],
        "core": core, "core_hex": None if core is None else extracted.hex[core],
        "thinness": list(outline.thinness),
        "thresholds": dict(outline.thresholds),
        "stroke_width_px": outline.stroke_width_px,
        "wide_components": [{"area_px": c.area_px, "inscribed_px": c.inscribed_px,
                             "centroid": list(c.centroid), "kept": c.kept}
                            for c in outline.wide_components],
        "keep_width": (None if outline.keep_width_mm is None else
                       {"mm": outline.keep_width_mm, "px": outline.keep_width_px}),
        "specks_not_drawn": (None if outline.specks is None else
                             {"count": outline.specks[0], "px": outline.specks[1]}),
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
    # The preview's outer outline is R1's smoothed one (Task 7e-b); display only, so its
    # sigma is recorded under "preview", not in the identity.
    outer_sigma = float(rules[SMOOTH_RULE].default)
    files, regions = {}, None
    if render:
        regions = _regions_image(sel.cutout_rgb, sel.mask, palette, smoothed.fine,
                                 smoothed.supersample, changed_mask(plan.banded, cleaned),
                                 settings["edges"], set(smoothed.vanished),
                                 extraction_palette, outline_record, shade_record, reason,
                                 outline_preview_mask(sel.mask, outer_sigma))
        files = {"labels.png": png_bytes(labels8), "regions.png": png_bytes(regions)}

    methods = {"colors": COLORS_ALGORITHM_VERSION, "quantize": METHOD,
               "outline": outline.method, "shade": SHADE_METHOD, "cleanup": CLEANUP_METHOD,
               "labels": LABELS_METHOD}
    used_rules = {limits.opening_rule: float(rules[limits.opening_rule].default),
                  limits.island_rule: float(rules[limits.island_rule].default)}
    if edge_rule is not None:
        used_rules[edge_rule] = sigma
    # The outline and shade rules that decided this plan (outline.thresholds holds the
    # thin share and the wide-area ratio when they were used).
    used_rules.update(dict(outline.thresholds))
    used_rules.update(dict(plan.shade_rules))
    limits_record = json_plain(dataclasses.asdict(limits))
    identity = colors_identity(
        methods=methods, selection_id=sel.record["selection_id"],
        cutout_pixels_sha256=sel.cutout_pixels_sha256,
        mask_pixels_sha256=sel.record["mask_pixels_sha256"],
        settings=record_settings["settings"], width_mm=width_mm, printer=printer.id,
        nozzle_diameter_mm=limits.nozzle_diameter_mm, rules=used_rules,
        supersample=supersample)
    record = {
        "schema": RECORD_SCHEMA, "tdmg_version": __version__ if render else None,
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
        # outline-family member that the outline handling removed), band (the kept
        # outline band painted over all of it) or cleanup (cleanup removed it);
        # final_index is null unless the fate is final.
        "extraction": {"extract": settings["extract"], "n_extracted": n_ext,
                       "palette": extraction_palette},
        # The outline step: the family (extraction indices and hexes), its core (the
        # darkest member, which keeps the wide areas that pass the ratio rule and draws
        # the kept band), every extracted color's thinness, the thresholds used (rule id:
        # value), the family's stroke width, the core's wide areas (area, inscribed width,
        # centroid, kept), the kept band's width and the stroke specks it left out.
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
        "cleanup": {k: v for k, v in json_plain(dataclasses.asdict(log)).items()
                    if k != "limits"},
        "smoothing": {"sigma_px": sigma, "edge_rule": edge_rule,
                      "supersample": supersample,  # method: methods.labels
                      "vanished": None if not render else [
                          {"index": i, "hex": cleaned.hex[i]} for i in smoothed.vanished]},
        "methods": methods,
        "preview": {"scale": PREVIEW_SCALE,
                    "right_panel": "final colors from the fine map, nearest fine pixel to "
                                   "each preview pixel centre, inside the smoothed outer "
                                   "outline; background outside it",
                    "outer_outline": OUTER_OUTLINE,
                    "outer_outline_smoothing": {"rule": SMOOTH_RULE, "sigma_px": outer_sigma},
                    "background": {"checker_shades": list(BACKGROUND_SHADES),
                                   "cell_px": CHECKER_CELL_PX},
                    "changed_outline": "inner edge of the pixels cleanup changed, black and "
                                       "white dashes"},
        "outputs": ({name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
                    if render else None),
        # Decoded pixels, so a pixel difference can be told from a PNG encoding difference.
        "regions_pixels_sha256": pixels_sha256(regions) if render else None,
        "environment": {**environment(), "scipy": scipy.__version__} if render else None,
        "review": REVIEW,
    }
    return record, files, labels8


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
        flagged = FLAGGED + flagged
    return (f"{n_final} colors remain after {after}, but colors allows at most {limit}; "
            f"{advice}{flagged}")


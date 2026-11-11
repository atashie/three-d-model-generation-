"""`tdmg colors`: the color plan of a selected subject, for review
(docs/plans/2026-11-11-color-palette.md, Decisions 1, 2, 6, 7 and 8; Task 6).

make_colors reads a verified tdmg select folder (tdmg.selection.read_selection, with the
cutout), resolves the settings (tdmg.color_config: flags, then the config file, then the
defaults), and runs the pure functions of tdmg.color and tdmg.smoothing in this order:

1. quantize(cutout RGB, mask, colors): the palette and the image-resolution label map.
2. mm_per_px = width_mm / the mask's exact bounding-box width in pixels (mask_mm_per_px),
   and printable_limits_px at that scale.
3. clean_regions: the label map cleaned to printable regions; the palette is re-sorted by
   final area.
4. The base color: `auto` is index 0 (the largest area after cleanup); a number must be an
   index of the final palette (check_base).
5. smooth_labels(cleaned labels, the edges preset's sigma, supersample): the fine map, used
   here for the preview only. Step 2 recomputes it from labels.png and the recorded sigma.

It writes labels.png, regions.png and colors.json (the record, last) into a new or empty
folder, through tdmg.records.write_outputs. Everything is computed and encoded in memory
first, so a refused input writes nothing. No gate checks run here.

tdmg.color and tdmg.smoothing stay free of I/O; this module does the reading and writing.
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
from PIL import Image, ImageDraw, ImageFont

from tdmg import __version__
from tdmg.color import (
    CLEANUP_METHOD,
    METHOD,
    OUTSIDE,
    ColorError,
    changed_mask,
    clean_regions,
    printable_limits_px,
    quantize,
)
from tdmg.color_config import ColorConfigError, check_base, edge_sigma_px, resolve_color_config
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
from tdmg.selection import SelectionError, _checker, read_selection
from tdmg.smoothing import LABELS_METHOD, SUPERSAMPLE, SmoothingError, smooth_labels

COLORS_ALGORITHM_VERSION = "colors-1"
RECORD_SCHEMA = "tdmg.colors/1"
RECORD_NAME = "colors.json"
OUTPUT_FILES = ("labels.png", "regions.png")
LABELS_OUTSIDE = 255   # labels.png value outside the mask; palette indices are below it
REVIEW = "Open regions.png to check the colors before building geometry."

# --- regions.png layout. Display only: none of these is a threshold. ---------------------
# Each image pixel is shown as PREVIEW_SCALE x PREVIEW_SCALE screen pixels. 2 is enough to
# see whether an edge is smooth or furry on the owner's ~800-1000-px images (the smoothed
# edge is drawn from the 4x fine map). The preview is 2 * PREVIEW_SCALE * W wide and
# PREVIEW_SCALE * (H + ROW_PX * (legend rows + palette size)) tall: Roadie (836 x 792)
# gives 3344 x 1752 px with 4 colors, Oddie (1024 x 1013) 4096 x 2194.
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


def legend_rows(edges: str) -> list[str]:
    """The legend lines above the swatches in regions.png."""
    return [LEGEND.format(edges=edges), OUTER_OUTLINE]


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
                    mask_pixels_sha256: str, settings: dict, width_mm: float, rules: dict,
                    sigma_px: float, nozzle_diameter_mm: float, supersample: int) -> str:
    """colors_id: SHA-256 of the canonical JSON of these fields.

    methods: the algorithm versions (colors, quantize, cleanup, labels). settings: the
    resolved values (colors, edges, base), not their sources: the same values from a flag
    or from a file give the same plan. rules: {rule id: value} for every rule used (the two
    cleanup rules and the edges rule, if any). The environment is never part of it.
    Raises ValueError for NaN or infinity.
    """
    identity = {"methods": methods, "selection_id": selection_id,
                "cutout_pixels_sha256": cutout_pixels_sha256,
                "mask_pixels_sha256": mask_pixels_sha256, "settings": settings,
                "width_mm": width_mm, "rules": rules, "sigma_px": sigma_px,
                "nozzle_diameter_mm": nozzle_diameter_mm, "supersample": supersample}
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def _width(width_mm) -> float:
    if isinstance(width_mm, bool) or not isinstance(width_mm, numbers.Real):
        raise ColorsError(f"width_mm must be a number, got {width_mm!r}")
    value = float(width_mm)
    if not math.isfinite(value) or value <= 0:
        raise ColorsError(f"width_mm must be a finite number above 0, got {value}")
    return value


def _plain(obj):
    """A JSON round trip: tuples become lists and dataclasses must already be dicts."""
    return json.loads(canonical_json(obj))


# --- regions.png --------------------------------------------------------------------------

def swatch_box(index: int, height_px: int) -> tuple[int, int, int, int]:
    """(top, left, bottom, right) of palette entry index's swatch in regions.png, for an
    image height_px tall. The strip starts with the legend rows (legend_rows); entry i is
    the row after them plus i."""
    s = PREVIEW_SCALE
    row = index + len(legend_rows(""))
    top = s * height_px + s * (ROW_PX * row + (ROW_PX - SWATCH_PX) // 2)
    left = s * MARGIN_PX
    return top, left, top + s * SWATCH_PX, left + s * SWATCH_PX


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

    Text uses Pillow's built-in bitmap font (ImageFont.load_default_imagefont), which has
    no anti-aliasing and no FreeType dependency, so the pixels are the same on every
    platform with this Pillow version. Text wider than the strip is cut off.
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
                   edges: str, vanished: set[int]) -> np.ndarray:
    """The review preview: two panels side by side, then the swatch strip.

    Left: the cutout, PREVIEW_SCALE x nearest, on tdmg select's preview checkerboard
    outside the mask. Right: the final palette colors from the smoothed fine map
    (_fine_to_preview), inside the mask only (the image mask, enlarged by nearest; the R1
    outline is smoothed in step 2, not here), on the same checkerboard. Pixels whose color
    cleanup changed (changed_mask) are outlined on the right: the inner edge of the
    changed region, enlarged, drawn in black and white dashes of CHANGED_DASH_PX along the
    diagonals, so it shows on any color. Below: the legend rows (legend_rows, which say
    that the outer outline is the image's pixel outline, smoothed in step 2), and one row per palette entry
    with its swatch, index, hex code, area share, and whether it is the base or vanished in
    smoothing.
    """
    h, w = mask.shape
    p = PREVIEW_SCALE
    big_mask = _enlarge(mask, p)
    checker = _checker(h * p, w * p)[..., None].repeat(3, axis=2)
    left = np.where(big_mask[..., None], _enlarge(cutout_rgb, p), checker)
    pal = np.array([e["rgb"] for e in palette], np.uint8)
    right = np.where(big_mask[..., None], pal[_fine_to_preview(fine, h, w, supersample)],
                     checker)
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
    strip = _enlarge(_strip(rows, 2 * w), p)
    return np.concatenate([panels, strip], axis=0)


# --- make_colors ------------------------------------------------------------------------

def make_colors(selection_dir, out_dir, *, width_mm, flags: dict, config_path,
                rules: dict, printer: PrinterProfile, supersample: int = SUPERSAMPLE) -> dict:
    """Write labels.png, regions.png and colors.json from a tdmg select folder; return the
    record. See the module docstring for the steps.

    flags: {"colors", "edges", "base"}, None for "not given". config_path: a YAML file or
    None. rules: the registry (tdmg.rules.load_rules()); printer: the printer profile (its
    palette cap and nozzle). supersample: the fine map's factor (tdmg.smoothing.SUPERSAMPLE
    by default; it enters colors_id). width_mm must be a finite number above 0.

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
    q = quantize(sel.cutout_rgb, sel.mask, settings["colors"])
    cleaned, log = clean_regions(q, limits)
    k = len(cleaned.hex)
    check_base(settings["base"], k)
    base_index = 0 if settings["base"] == "auto" else settings["base"]
    smoothed = smooth_labels(cleaned.labels, sigma, supersample)
    vanished = set(smoothed.vanished)

    if k >= LABELS_OUTSIDE:     # the config caps colors at the profile's slots (4 for the A1)
        raise ColorsError(f"{k} colors do not fit an 8-bit labels.png with "
                          f"{LABELS_OUTSIDE} outside")
    labels8 = np.where(cleaned.labels == OUTSIDE, LABELS_OUTSIDE,
                       cleaned.labels).astype(np.uint8)
    palette = [{"index": i, "hex": cleaned.hex[i], "rgb": cleaned.rgb[i].tolist(),
                "lab": cleaned.lab[i].tolist(), "share": cleaned.shares[i],
                "count": cleaned.counts[i], "base": i == base_index} for i in range(k)]
    regions = _regions_image(sel.cutout_rgb, sel.mask, palette, smoothed.fine,
                             smoothed.supersample, changed_mask(q, cleaned),
                             settings["edges"], vanished)
    files = {"labels.png": png_bytes(labels8), "regions.png": png_bytes(regions)}

    methods = {"colors": COLORS_ALGORITHM_VERSION, "quantize": METHOD,
               "cleanup": CLEANUP_METHOD, "labels": LABELS_METHOD}
    used_rules = {limits.opening_rule: float(rules[limits.opening_rule].default),
                  limits.island_rule: float(rules[limits.island_rule].default)}
    if edge_rule is not None:
        used_rules[edge_rule] = sigma
    record_settings = resolved.as_record()
    limits_record = _plain(dataclasses.asdict(limits))
    record = {
        "schema": RECORD_SCHEMA, "tdmg_version": __version__,
        "algorithm": COLORS_ALGORITHM_VERSION,
        "colors_id": colors_identity(
            methods=methods, selection_id=sel.record["selection_id"],
            cutout_pixels_sha256=sel.cutout_pixels_sha256,
            mask_pixels_sha256=sel.record["mask_pixels_sha256"],
            settings=record_settings["settings"], width_mm=width_mm, rules=used_rules,
            sigma_px=sigma, nozzle_diameter_mm=limits.nozzle_diameter_mm,
            supersample=smoothed.supersample),
        "input": {"selection_id": sel.record["selection_id"],
                  "selection_json_sha256": sel.record_sha256,
                  "cutout_pixels_sha256": sel.cutout_pixels_sha256,
                  "mask_pixels_sha256": sel.record["mask_pixels_sha256"],
                  "width_px": int(sel.mask.shape[1]), "height_px": int(sel.mask.shape[0])},
        "settings": record_settings,
        "width_mm": width_mm, "mm_per_px": mm_per_px, "printer": printer.id,
        "limits": limits_record,
        "palette": palette, "base_index": base_index,
        # Before cleanup. dropped: palette colors the final nearest reassignment left empty.
        "quantize": {"iterations": q.iterations, "converged": q.converged,
                     "n_requested": q.n_requested, "n_distinct_colors": q.n_distinct_colors,
                     "dropped": q.dropped, "palette_hex": list(q.hex)},
        # The log's limits are the top-level "limits"; they are not repeated here.
        "cleanup": {k: v for k, v in _plain(dataclasses.asdict(log)).items()
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
        "environment": {**environment(), "scipy": scipy.__version__},
        "review": REVIEW,
    }
    try:
        data = record_text(record)
    except ValueError as e:
        raise ColorsError(f"the record cannot be stored as strict JSON: {e}") from None
    write_outputs(out_dir, files, RECORD_NAME, data, create_folder=create_folder)
    return json.loads(data)

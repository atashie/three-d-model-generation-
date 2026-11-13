"""Colored flat geometry from a verified color plan: `tdmg flat --colors` (R2 step 2).

docs/plans/2026-11-12-color-geometry.md, Decisions 1, 2, 9 and 10 and Task 6.
make_colored_flat chains the pure steps and writes their outputs in make_flat's style:

1. Input (Decision 1): smoothing cannot be changed (the reviewed preview drew the outline
   at flat.smooth.sigma_px); the thickness must exceed color.skin.depth_mm; then
   verify_colors(colors_dir, selection_dir, check_preview=False); the width and the
   printer default to the plan's and must equal them if given.
2. S (Decision 2): tdmg.flat.silhouette, the outline step make_flat calls, at the plan's
   width with flat.smooth.sigma_px, here intersected with the image box.
3. Regions, cells and bodies: smooth_labels with the plan's sigma and supersample,
   color_regions, color_cells, ams_bodies and ams_checks; glue_geometry and glue_checks,
   except for a plan that drew a kept outline band (outlines: keep with an outline
   family; Decision 8, owner decision at the Task 7 review: a kept outline is
   unrealistic to glue on, and a plan does not mark which outline-color pixels are the
   redrawn band), where the glue route is not built. A keep plan with no family
   (outline_color none, or auto finding none) drew no band and builds glue as usual.
4. Checks (Decision 9): every per-body, per-plate and assembly check of ams_checks and
   glue_checks, F3.thin_regions per body of both routes (information, UNKNOWN, as in tdmg
   flat) and F6.slicer UNKNOWN per route, so the verdict here is always NOT CERTIFIED.
5. Outputs (Decision 10): the gated STL bytes, top.png, parts.png and colored.json, the
   record last (tdmg.records.write_outputs). A refused input writes nothing; a FAIL still
   writes the files for review.
6. The multicolor 3MF (docs/plans/2026-11-12-color-3mf.md, Decisions 1 to 5): model.3mf,
   tdmg.threemf's encoding D built from exactly the gated AMS meshes, gated by
   F2.export_3mf_matches_bodies (an AMS assembly check), and palette.json, which says what
   each shell is.

This module is separate from tdmg.flat because the color modules import tdmg.flat.
"""

from __future__ import annotations

import hashlib
import json
import math
import zlib
from importlib.metadata import version as package_version
from pathlib import Path

import numpy as np
import scipy
import shapely
from PIL import Image, ImageDraw, ImageFont

from tdmg import __version__
from tdmg.checks import F1_CHECK_IDS, CheckResult, verdict
from tdmg.color_checks import ColorCheckError, ams_checks, export_3mf_check, glue_checks
from tdmg.color_config import ColorConfigError, palette_cap
from tdmg.color_geometry import ColorGeometryError, ams_bodies, color_cells, color_regions
from tdmg.color_glue import glue_geometry
from tdmg.colors import (
    MARGIN_PX,
    PREVIEW_SCALE,
    ROW_PX,
    STRIP_BACKGROUND,
    STRIP_TEXT,
    SWATCH_PX,
    TEXT_X_PX,
    ColorsError,
    background,
    enlarge,
    swatch_strip,
    wrap_text,
)
from tdmg.colors_verify import verify_colors
from tdmg.flat import (
    SMOOTH_RULE,
    FlatError,
    cleaning_params,
    flat_environment,
    mesh_summary,
    read_flat_selection,
    silhouette,
    slicer_check,
    thin_region_check,
)
from tdmg.profiles import load_printer
from tdmg.records import (
    RecordError,
    canonical_json,
    check_output_dir,
    png_bytes,
    record_text,
    write_outputs,
)
from tdmg.rules import load_rules
from tdmg.selection import SelectionError
from tdmg.smoothing import SmoothingError, smooth_labels
from tdmg.threemf import ENCODING as THREEMF_ENCODING
from tdmg.threemf import OBJECT_NAME as THREEMF_OBJECT
from tdmg.threemf import Shell, ThreeMFError, palette_manifest, write_multishell_3mf

RECORD_SCHEMA = "tdmg.colorflat/1"
RECORD_NAME = "colored.json"
# colorflat-2 (2026-11-12, Codex review 3): glue pieces are eroded until they clear their
# region by the clearance, and pocket walls are grown to clear the pieces, so glue outputs
# differ from colorflat-1 (never pushed with results; the owner-plan runs were re-made).
# colorflat-3 (2026-11-12, R2 step 3): the AMS output adds model.3mf and palette.json, the
# record a model_3mf section, and the AMS assembly F2.export_3mf_matches_bodies (a new
# required check). The STL, PNG and glue bytes are those of colorflat-2.
ALGORITHM = "colorflat-3"
MODEL_3MF = "model.3mf"
PALETTE_NAME = "palette.json"
MODEL_3MF_NOTE = (
    "Encoding D of docs/plans/2026-11-12-color-3mf.md (Decision 1): every AMS body is its "
    "own closed shell of one object, with its own vertices, so the 3MF manifold rule holds "
    "per shell by vertex index. The shells touch along their shared walls, which the 3MF "
    "core covers only as a self-intersection warning (rule "
    "format.3mf.self_intersection_is_warning). The colors are standard Materials colors; "
    "palette.json is the guarantee of what each shell is. No slicer project settings.")
SKIN_RULE = "color.skin.depth_mm"
CLEARANCE_RULE = "color.glue.clearance_mm"
MIN_SIDE_RULE = "color.glue.min_piece_side_mm"
ROUTES = ("ams", "glue")
# Every check this command produces. F3.thin_regions and F6.slicer are always UNKNOWN
# here, so the verdict is always NOT CERTIFIED (Decision 9); step 4 slices.
COLORED_REQUIRED_CHECKS = F1_CHECK_IDS | {
    "F2.export_matches_geometry", "F2.export_3mf_matches_bodies", "F2.fits_build_volume",
    "F3.thin_regions", "F4.color_partition", "F4.filaments", "F4.glue_partition",
    "F4.glue_fit", "F5.triangles", "F6.slicer"}
# The checks only the glue route produces. Without a glue route (a drawn outline band)
# they are not required; every other check still is, from the AMS route alone.
GLUE_ONLY_CHECKS = frozenset({"F4.glue_partition", "F4.glue_fit"})
GLUE_NOT_BUILT = ("the plan keeps the outline (outlines: keep with an outline family, so "
                  "an outline band is drawn), and a kept outline is unrealistic to glue on "
                  "(owner decision, Task 7 review); for a glue print, use a plan made with "
                  "outlines: drop (tdmg colors --outlines drop)")
# parts.png and top.png display only, not thresholds: a piece number is drawn in STRIP_TEXT
# on a STRIP_BACKGROUND box with LABEL_PAD_PX of padding (at 1x, then enlarged like the
# strip), and the number boxes and this module's swatches get a BORDER_PX frame in
# STRIP_TEXT at preview scale, so that a white piece or a white swatch stays visible.
LABEL_PAD_PX = 1
BORDER_PX = 1
TOP_NOTE = ("top.png: the AMS model's top skin ({skin} mm deep), drawn from its cells at "
            "the pixel centres; compare it with the plan's regions.png. Grey checker: not "
            "part of the model.")
PARTS_NOTE = ("parts.png: the glue model. Pockets ({skin} mm deep) are drawn in their "
              "color on the base color; each number is one glue piece, {skin} mm thick and "
              "{clearance} mm smaller than its pocket on every side, printed where it sits "
              "in the model.")
REVIEW_TOP = ("Open top.png and compare it with the plan's regions.png: the colors should "
              "match. ")
REVIEW_PARTS = ("Open parts.png: check the folds and leftovers and that the pieces are a "
                "size you can handle. ")
REVIEW_3MF = ("model.3mf holds the AMS bodies as one object with one shell per color, in "
              "place; open it in your slicer and give each color a filament (palette.json "
              "lists the colors; the file names colors, not AMS slots). ")
REVIEW_END = ("The verdict stays NOT CERTIFIED: F3.thin_regions and F6.slicer are UNKNOWN "
              "until the bodies are sliced (step 4 of the color design); tdmg slice does "
              "not read this folder yet.")
REVIEW = REVIEW_TOP + REVIEW_PARTS + REVIEW_3MF + REVIEW_END
REVIEW_NO_GLUE = REVIEW_TOP + "The glue version was not built: " + GLUE_NOT_BUILT + ". " \
    + REVIEW_3MF + REVIEW_END


class ColoredFlatError(FlatError):
    """The plan cannot be made into colored flat geometry as asked. Nothing is written."""


def _number(name: str, value) -> float:
    if isinstance(value, bool):
        raise ColoredFlatError(f"{name} must be a number, got {value!r}")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ColoredFlatError(f"{name} must be a number, got {value!r}") from None
    if not math.isfinite(value) or value <= 0:
        raise ColoredFlatError(f"{name} must be a finite number above 0, got {value}")
    return value


def colorflat_identity(*, colors_id: str, selection_id: str, mask_pixels_sha256: str,
                       params: dict) -> dict:
    """The identity colorflat_id hashes: the algorithm, the plan, the selection and the
    params. The environment is never part of it."""
    return {"algorithm": ALGORITHM, "colors_id": colors_id, "selection_id": selection_id,
            "mask_pixels_sha256": mask_pixels_sha256, "params": params}


def colorflat_id(identity: dict) -> str:
    """SHA-256 of the canonical JSON of identity (colorflat_identity's dict)."""
    try:
        return hashlib.sha256(canonical_json(identity)).hexdigest()
    except ValueError as e:
        raise ColoredFlatError(f"the identity cannot be hashed: {e}") from None


def body_file(route: str, index: int, hex_code: str, base_index: int) -> str:
    """The STL name of a body (Decision 10): <route>-base.stl, or
    <route>-color-<i>-<rrggbb>.stl with the final palette index and hex (no '#')."""
    if index == base_index:
        return f"{route}-base.stl"
    return f"{route}-color-{index}-{hex_code.lstrip('#').lower()}.stl"


# --- previews --------------------------------------------------------------------------


def paint_cells(cells, labels, colors: dict, transform: dict, shape) -> np.ndarray:
    """(H P, W P, 3) uint8, P = PREVIEW_SCALE: colors' background(), with each label's
    cells painted in colors[label] at the preview pixel centres.

    Preview pixel (row a, column b) has its centre at ((b + 0.5) / P, (a + 0.5) / P) in
    image pixels, mapped to model mm by to_model's transform as tdmg.flat.rasterise does.
    The test is shapely.intersects_xy (exact), so a centre on a boundary is inside. With
    P = 2 and supersample 4, many centres lie on the fine map's edges in exact arithmetic;
    after the transform and the storage grid such a centre can fall on either side or on
    the edge, and on an edge the lowest label wins (labels are painted from the highest
    down). Outside every cell the background shows.
    """
    h, w = shape
    p = PREVIEW_SCALE
    image = background(h * p, w * p)
    s, x0, y1 = transform["scale_mm_per_px"], transform["x0_px"], transform["y1_px"]
    for label in sorted(set(labels), reverse=True):
        region = shapely.union_all([c for c, k in zip(cells, labels, strict=True)
                                    if k == label])
        minx, miny, maxx, maxy = region.bounds
        # The region's bounding box in preview pixels, widened by one pixel each way so
        # that rounding in the transform cannot drop an edge pixel (as flat.rasterise).
        c0 = max(math.floor((minx / s + x0) * p) - 1, 0)
        c1 = min(math.ceil((maxx / s + x0) * p) + 1, w * p)
        r0 = max(math.floor((y1 - maxy / s) * p) - 1, 0)
        r1 = min(math.ceil((y1 - miny / s) * p) + 1, h * p)
        if c0 >= c1 or r0 >= r1:
            continue
        x_mm = ((np.arange(c0, c1) + 0.5) / p - x0) * s
        y_mm = (y1 - (np.arange(r0, r1) + 0.5) / p) * s
        shapely.prepare(region)
        hit = shapely.intersects_xy(region, x_mm[None, :], y_mm[:, None])
        image[r0:r1, c0:c1][hit] = colors[label]
    return image


def to_preview_px(point_mm, transform: dict) -> tuple[float, float]:
    """(column, row) in preview pixels of a model point (x_mm, y_mm)."""
    s, x0, y1 = transform["scale_mm_per_px"], transform["x0_px"], transform["y1_px"]
    x, y = point_mm
    return (x / s + x0) * PREVIEW_SCALE, (y1 - y / s) * PREVIEW_SCALE


def number_label(text: str) -> np.ndarray:
    """The piece number as an (h, w, 3) uint8 box at preview scale: STRIP_TEXT on
    STRIP_BACKGROUND in colors' bitmap font, drawn at 1x and enlarged by PREVIEW_SCALE,
    framed by BORDER_PX of STRIP_TEXT."""
    font = ImageFont.load_default_imagefont()
    left, top, right, bottom = font.getbbox(text)
    im = Image.new("RGB", (right - left + 2 * LABEL_PAD_PX, bottom - top + 2 * LABEL_PAD_PX),
                   STRIP_BACKGROUND)
    ImageDraw.Draw(im).text((LABEL_PAD_PX - left, LABEL_PAD_PX - top), text,
                            fill=STRIP_TEXT, font=font)
    return _framed(enlarge(np.asarray(im), PREVIEW_SCALE))


def _framed(box: np.ndarray) -> np.ndarray:
    """box with a BORDER_PX frame in STRIP_TEXT (a copy)."""
    out = box.copy()
    b = BORDER_PX
    out[:b], out[-b:], out[:, :b], out[:, -b:] = STRIP_TEXT, STRIP_TEXT, STRIP_TEXT, STRIP_TEXT
    return out


def _placed(row: dict, transform: dict) -> tuple[np.ndarray, int, int]:
    """A piece's number box and its unclipped top-left corner in preview pixels."""
    box = number_label(str(row["number"]))
    col, r = to_preview_px(row["point_on_surface"], transform)
    return box, math.floor(r) - box.shape[0] // 2, math.floor(col) - box.shape[1] // 2


def label_boxes(pieces: list[dict], transform: dict, shape) -> list[tuple]:
    """Per piece row (glue report's pieces), (number, top, left, bottom, right): where
    parts.png draws its number box, centred on its point_on_surface and clipped to the
    image (H P x W P)."""
    h, w = shape[0] * PREVIEW_SCALE, shape[1] * PREVIEW_SCALE
    out = []
    for row in pieces:
        box, top, left = _placed(row, transform)
        out.append((row["number"], max(top, 0), max(left, 0),
                    min(top + box.shape[0], h), min(left + box.shape[1], w)))
    return out


def _draw_numbers(image: np.ndarray, pieces: list[dict], transform: dict, shape) -> None:
    boxes = label_boxes(pieces, transform, shape)
    for row, (_, top, left, bottom, right) in zip(pieces, boxes, strict=True):
        if top < bottom and left < right:
            box, t0, l0 = _placed(row, transform)
            image[top:bottom, left:right] = box[top - t0:bottom - t0, left - l0:right - l0]


def _swatch_rows(rgb, text: str, width: int) -> list[tuple]:
    """A swatch row wrapped by hand (swatch_strip does not wrap rows up to its last
    swatch): the first line has the swatch, the rest none. swatch_strip starts a row
    without a swatch at MARGIN_PX, so the continuation lines are indented by spaces to
    about TEXT_X_PX, under the first line's text."""
    font = ImageFont.load_default_imagefont()
    lines = wrap_text(text, width - TEXT_X_PX - MARGIN_PX, font)
    indent = " " * round((TEXT_X_PX - MARGIN_PX) / font.getlength(" "))
    return [(rgb, lines[0])] + [(None, indent + line.lstrip()) for line in lines[1:]]


def _with_strip(image: np.ndarray, rows: list[tuple], width_px: int) -> np.ndarray:
    """image over colors' swatch_strip of rows, enlarged by PREVIEW_SCALE, with a
    BORDER_PX frame on each swatch. swatch_strip keeps every row up to its last swatch
    as one line (only the rows after it are wrapped), so row i's swatch is where
    swatch_strip draws it: top ROW_PX i + (ROW_PX - SWATCH_PX) // 2, left MARGIN_PX."""
    strip = enlarge(swatch_strip(rows, width_px), PREVIEW_SCALE)
    p = PREVIEW_SCALE
    for i, (rgb, _) in enumerate(rows):
        if rgb is not None:
            top = p * (ROW_PX * i + (ROW_PX - SWATCH_PX) // 2)
            left = p * MARGIN_PX
            box = (slice(top, top + p * SWATCH_PX), slice(left, left + p * SWATCH_PX))
            strip[box] = _framed(strip[box])
    return np.concatenate([image, strip], axis=0)


def _rgb(palette: list) -> dict:
    return {p["index"]: tuple(int(v) for v in p["rgb"]) for p in palette}


def top_image(cells, palette: list, transform: dict, shape, bodies: list[dict],
              skin_mm: float) -> np.ndarray:
    """top.png: the AMS cells in palette colors (paint_cells) over a legend strip with,
    per AMS body, its swatch, index, hex, top area and file."""
    w = shape[1]
    image = paint_cells(list(cells.cells), list(cells.labels), _rgb(palette), transform,
                        shape)
    rgb = _rgb(palette)
    rows = []
    for b in bodies:
        role = " (base)" if b["role"] == "base" else ""
        rows += _swatch_rows(rgb[b["index"]], f"{b['index']} {b['hex']} "
                             f"{b['top_area_mm2']:.1f} mm^2 {b['file']}{role}", w)
    rows.append((None, TOP_NOTE.format(skin=f"{skin_mm:g}")))
    return _with_strip(image, rows, w)


def _folds_line(folds: list[dict]) -> str:
    if not folds:
        return "folds: none"
    groups: dict[tuple, list] = {}
    for f in folds:
        into = f"base {f['into']}" if f["into_base"] else f"color {f['into']}"
        groups.setdefault((f["label"], into), []).append(f["region_area_mm2"])
    parts = [f"color {label} -> {into}: {len(a)} ({sum(a):.2f} mm^2)"
             for (label, into), a in sorted(groups.items(), key=lambda g: (g[0][0], g[0][1]))]
    return (f"folds (no piece of at least the min-piece area; each into the neighbour with "
            f"the longest shared boundary): {len(folds)} regions; " + "; ".join(parts))


def _leftover_line(report: dict) -> str:
    rows = [r for r in report["leftover"] if r["leftover_mm2"] > 0]
    if not rows:
        return "leftover to the base: none"
    return (f"leftover to the base (glue model only): {report['leftover_mm2']:.2f} mm^2; "
            + ", ".join(f"color {r['index']} {r['leftover_mm2']:.2f} mm^2" for r in rows))


def parts_image(glue, palette: list, transform: dict, shape, *, skin_mm: float,
                clearance_mm: float, inlays) -> np.ndarray:
    """parts.png: the glue layout (the rebuilt cells: the base color everywhere in S,
    pockets in their color), each piece's number at its point_on_surface, and below it
    the pieces per color (inlays: the AMS inlay colors; one with no piece is listed as
    folded), the folds, the leftovers and the review note."""
    w = shape[1]
    rgb = _rgb(palette)
    image = paint_cells(list(glue.cells.cells), list(glue.cells.labels), rgb, transform,
                        shape)
    report = glue.report
    _draw_numbers(image, report["pieces"], transform, shape)
    hex_of = {p["index"]: p["hex"] for p in palette}
    base = glue.base_index
    rows = _swatch_rows(rgb[base], f"base {base} {hex_of[base]}: "
                        f"{body_file('glue', base, hex_of[base], base)}", w)
    for index in sorted(set(inlays) | {c["index"] for c in report["colors"]}):
        numbers = [p["number"] for p in report["pieces"] if p["index"] == index]
        pieces = (f"pieces {', '.join(str(n) for n in numbers)}" if numbers
                  else "no pieces (all folded)")
        rows += _swatch_rows(rgb[index], f"color {index} {hex_of[index]}: {pieces}", w)
    rows.append((None, _folds_line(report["folds"])))
    rows.append((None, _leftover_line(report)))
    rows.append((None, PARTS_NOTE.format(skin=f"{skin_mm:g}", clearance=f"{clearance_mm:g}")))
    return _with_strip(image, rows, w)


# --- the command -----------------------------------------------------------------------


def _dicts(checks: list[CheckResult]) -> list[dict]:
    return [c.as_dict() for c in checks]


def colored_environment() -> dict:
    """tdmg flat's environment plus scipy (smooth_labels' distance transform), lxml (the
    3MF's XML), lib3mf (the 3MF's reader in the gate) and zlib_python: the zlib that
    Python's zlib module links (zlib.ZLIB_RUNTIME_VERSION), which zipfile deflates
    model.3mf with. It can differ from "zlib", the one Pillow links for the PNGs (on the
    PC, 2026-11-12: 1.3.1 against 1.3.1.zlib-ng). model.3mf's bytes also depend on
    CPython's zipfile, recorded as python."""
    return {**flat_environment(), "scipy": scipy.__version__,
            "lxml": package_version("lxml"), "lib3mf": package_version("lib3mf"),
            "zlib_python": zlib.ZLIB_RUNTIME_VERSION}


def make_colored_flat(selection_dir, colors_dir, out_dir, *, thickness_mm, width_mm=None,
                      printer=None, smooth_px=None) -> dict:
    """Make the AMS and glue bodies, model.3mf and palette.json (the AMS bodies as one
    multicolor 3MF, built from exactly the gated meshes), top.png, parts.png and
    colored.json from a verified color plan and its selection. Returns the record as
    written (JSON types). For a plan that drew a kept outline band, the glue route is
    not built (no glue-*.stl, no parts.png). The test is the verified plan's
    outline.keep_width: verify_colors pins it to be set exactly under outlines: keep
    with a non-empty outline family, and null
    otherwise (so a keep plan with no family builds glue as usual). Then the
    record's glue section is {"built": false, "reason", "report": null} ({"built": true,
    "reason": null, "report": glue_geometry's report} otherwise), a warning says why, and
    the verdict's required set leaves out GLUE_ONLY_CHECKS (record: required_checks).

    Refused with FlatError before anything is written (ColoredFlatError, a FlatError,
    unless noted): any smooth_px (the reviewed preview drew the outline at
    flat.smooth.sigma_px); thickness_mm not a number above color.skin.depth_mm; an out_dir
    that check_output_dir refuses; a plan that verify_colors refuses (changed,
    inconsistent, not ready, another selection, rule values that differ from the
    registry); width_mm given and not exactly the plan's width_mm; printer given and not
    the plan's printer; a printer with no multi-material unit; a selection that
    tdmg.flat.read_flat_selection refuses and a silhouette that tdmg.flat.silhouette
    refuses (plain FlatError); and a refusal of the geometry steps (ColorGeometryError,
    ColorCheckError, SmoothingError). The checks that need no plan come first; the
    printer's palette cap needs the plan's printer, so it comes after verify_colors. An
    I/O failure while writing can leave a folder without colored.json, which must not be
    used.

    colorflat_id is the SHA-256 of colorflat_identity: the algorithm, the plan's
    colors_id, the selection's id and mask hash, and the params (width, thickness,
    printer, every rule value used with its rule, the plan's supersample and labels
    sigma, and the storage grid G, which the geometry derives). Check thresholds and the
    environment are not part of it. The output hashes are integrity hashes for this
    environment only.
    """
    rules = load_rules()
    thickness = _number("thickness_mm", thickness_mm)
    if smooth_px is not None:
        raise ColoredFlatError(
            f"--smooth-px cannot be used with --colors: the plan's preview was reviewed "
            f"with the outline smoothed by rule {SMOOTH_RULE}, so the model uses it too")
    width = None if width_mm is None else _number("width_mm", width_mm)
    skin = float(rules[SKIN_RULE].default)
    if thickness <= skin:
        raise ColoredFlatError(
            f"thickness_mm ({thickness:g}) must be above the skin depth {skin:g} mm (rule "
            f"{SKIN_RULE}), so that there is base material under every inlay")
    try:
        create_folder = check_output_dir(out_dir)
    except RecordError as e:
        raise ColoredFlatError(str(e)) from None
    try:
        plan = verify_colors(colors_dir, selection_dir, check_preview=False, rules=rules)
    except (ColorsError, SelectionError) as e:
        raise ColoredFlatError(str(e)) from None
    if width is not None and width != plan.width_mm:
        raise ColoredFlatError(
            f"width_mm {width!r} differs from the plan's width_mm {plan.width_mm!r}: the "
            f"plan's cleanup used its width; leave --width-mm out, or re-run tdmg colors "
            f"with --width-mm {width!r}")
    plan_printer = plan.record["identity"]["printer"]
    if printer is not None and printer != plan_printer:
        raise ColoredFlatError(
            f"printer {printer!r} differs from the plan's printer {plan_printer!r}: the "
            f"plan's cleanup used that printer's nozzle; leave --printer out, or re-run "
            f"tdmg colors for {printer!r}")
    profile = load_printer(plan_printer)
    try:
        cap = palette_cap(profile)
    except ColorConfigError as e:
        raise ColoredFlatError(str(e)) from None
    selection, mask = read_flat_selection(Path(selection_dir))

    clearance = float(rules[CLEARANCE_RULE].default)
    side = float(rules[MIN_SIDE_RULE].default)
    opening_param, island_param = cleaning_params(rules, profile)
    opening, island = opening_param["value"], island_param["value"]
    sigma = float(rules[SMOOTH_RULE].default)
    # A band was drawn exactly when keep_width is set (verify_colors: keep with a family).
    build_glue = plan.record["outline"]["keep_width"] is None
    try:
        _, transform, parts, cleaning = silhouette(mask, plan.width_mm, sigma, opening,
                                                   island, image_box=True)
        region = shapely.union_all(parts)
        fine = smooth_labels(plan.labels, plan.sigma_px, plan.supersample).fine
        regions = color_regions(fine, plan.supersample, transform, region,
                                n_colors=len(plan.palette), base_index=plan.base_index,
                                thin_width_mm=opening)
        cells = color_cells(regions, region, plan.base_index)
        ams = ams_bodies(cells, thickness_mm=thickness, skin_mm=skin)
        ams_result = ams_checks(ams, cells, thickness,
                                colors=plan.record["identity"]["settings"]["colors"],
                                palette_cap=cap, printer=profile, rules=rules)
        if build_glue:
            glue = glue_geometry(cells, thickness_mm=thickness, skin_mm=skin,
                                 clearance_mm=clearance, min_piece_side_mm=side,
                                 opening_mm=opening, min_island_mm2=island)
            glue_result = glue_checks(glue, printer=profile, rules=rules)
    except (ColorGeometryError, ColorCheckError, SmoothingError) as e:
        raise ColoredFlatError(f"the colored geometry was refused: {e}") from None

    hex_of = {p["index"]: p["hex"] for p in plan.palette}
    base = plan.base_index
    files: dict[str, bytes] = {}
    body_rows = []
    routes = [("ams", ams, ams_result)]
    if build_glue:
        routes.append(("glue", glue.bodies, glue_result))
    for route, bodies, result in routes:
        for body in bodies:
            name = body_file(route, body.index, hex_of[body.index], base)
            data = result["stl"][body.name]
            files[name] = data
            checks = list(result["bodies"][body.name])
            if route == "glue":
                checks += result["plates"][body.name]
            checks.append(thin_region_check(list(body.parts), rules))
            summary = mesh_summary(result["meshes"][body.name])
            role = ("base" if body.index == base else
                    "inlay" if route == "ams" else "pieces")
            row = {"name": name.removesuffix(".stl"), "file": name, "route": route,
                   "role": role, "index": body.index, "hex": hex_of[body.index],
                   "triangles": summary["triangles"], "bodies": summary["bodies"],
                   "volume_mm3": summary["volume_mm3"],
                   "extents_mm": summary["extents_mm"],
                   "footprint_area_mm2": float(sum(q.area for q in body.parts)),
                   "checks": _dicts(checks)}
            if route == "ams":
                row["top_area_mm2"] = float(sum(c.area for c in cells.of(body.index)))
            body_rows.append(row)
    # model.3mf: the gated AMS meshes (ams_checks' "meshes", the written STL bytes parsed
    # back and merged exactly), base first, then inlays by index (ams_checks' order).
    ams_rows = [b for b in body_rows if b["route"] == "ams"]
    shells = [Shell(row["name"], row["role"], body.index, row["hex"],
                    ams_result["meshes"][body.name].vertices,
                    ams_result["meshes"][body.name].faces)
              for body, row in zip(ams, ams_rows, strict=True)]
    try:
        model_3mf = write_multishell_3mf(shells)
    except ThreeMFError as e:
        raise ColoredFlatError(f"model.3mf cannot be written: {e}") from None
    files[MODEL_3MF] = model_3mf
    assembly = {"ams": ams_result["assembly"] + [export_3mf_check(model_3mf, shells),
                                                 slicer_check()],
                "glue": glue_result["assembly"] + [slicer_check()] if build_glue else []}
    required = COLORED_REQUIRED_CHECKS if build_glue else \
        COLORED_REQUIRED_CHECKS - GLUE_ONLY_CHECKS
    all_checks = [CheckResult(**c) for b in body_rows for c in b["checks"]]
    all_checks += [c for route in ROUTES for c in assembly[route]]

    shape = mask.shape
    files["top.png"] = png_bytes(top_image(cells, plan.palette, transform, shape,
                                           ams_rows, skin))
    inlays = sorted(set(cells.labels) - {base})
    warnings = list(regions.warnings)
    if build_glue:
        files["parts.png"] = png_bytes(parts_image(glue, plan.palette, transform, shape,
                                                   skin_mm=skin, clearance_mm=clearance,
                                                   inlays=inlays))
        glued = {c["index"] for c in glue.report["colors"]}
        for c in sorted(set(inlays) - glued):
            warnings.append(f"color {c} {hex_of[c]} has no glue piece: all of its regions "
                            f"are too small for a piece (rule {MIN_SIDE_RULE}) and were "
                            "folded, so the glue model does not use it")
        glue_section = {"built": True, "reason": None, "report": glue.report}
    else:
        warnings.append(f"glue version not built: {GLUE_NOT_BUILT}")
        glue_section = {"built": False, "reason": GLUE_NOT_BUILT, "report": None}

    params = {
        "width_mm": plan.width_mm, "thickness_mm": thickness, "printer": profile.id,
        "skin_mm": {"value": skin, "rule": SKIN_RULE},
        "clearance_mm": {"value": clearance, "rule": CLEARANCE_RULE},
        "min_piece_side_mm": {"value": side, "rule": MIN_SIDE_RULE},
        "opening_mm": opening_param, "min_island_mm2": island_param,
        "smoothing": {"sigma_px": {"value": sigma, "rule": SMOOTH_RULE}},
        "supersample": plan.supersample,
        "labels_sigma_px": {"value": plan.sigma_px,
                            "rule": plan.record["smoothing"]["edge_rule"]},
        "grid_mm": cells.grid_mm,
    }
    identity = colorflat_identity(colors_id=plan.record["colors_id"],
                                  selection_id=selection["selection_id"],
                                  mask_pixels_sha256=selection["mask_pixels_sha256"],
                                  params=params)
    flat_id = colorflat_id(identity)
    files[PALETTE_NAME] = palette_manifest(
        shells, model_3mf, colorflat_id=flat_id,
        top_area_mm2=[r["top_area_mm2"] for r in ams_rows],
        volume_mm3=[r["volume_mm3"] for r in ams_rows])
    record = {
        "schema": RECORD_SCHEMA, "tdmg_version": __version__, "algorithm": ALGORITHM,
        "colorflat_id": flat_id, "identity": identity,
        "palette": [{"index": p["index"], "hex": p["hex"], "rgb": p["rgb"],
                     "base": p["index"] == base} for p in plan.palette],
        "base_index": base, "transform": transform, "cleaning": cleaning,
        "regions": regions.report, "cells": cells.report, "glue": glue_section,
        "bodies": body_rows,
        "model_3mf": {"file": MODEL_3MF, "palette": PALETTE_NAME,
                      "encoding": THREEMF_ENCODING, "object_name": THREEMF_OBJECT,
                      "shells": [s.name for s in shells], "note": MODEL_3MF_NOTE},
        "assembly": {route: _dicts(assembly[route]) for route in ROUTES},
        "warnings": warnings,
        "required_checks": sorted(required),
        "verdict": verdict(all_checks, required),
        "outputs": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        "environment": colored_environment(),
        "review": REVIEW if build_glue else REVIEW_NO_GLUE,
    }
    try:
        data = record_text(record)
    except ValueError as e:
        raise ColoredFlatError(f"the record cannot be stored as strict JSON: {e}") from None
    try:
        write_outputs(out_dir, files, RECORD_NAME, data, create_folder=create_folder)
    except RecordError as e:
        raise ColoredFlatError(str(e)) from None
    return json.loads(data)

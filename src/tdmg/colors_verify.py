"""verify_colors: read a `tdmg colors` folder back and check it
(docs/plans/2026-11-11-color-palette.md, Decision 8; Tasks 7b and 7c). Split out of
tdmg.colors, which writes the folder. Import verify_colors and VerifiedColors from this
module: tdmg.colors does not re-export them (this module imports tdmg.colors, so a
re-export there would be circular).
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import numbers
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from pydantic import ValidationError

from tdmg.color import (
    CLEANUP_METHOD,
    ISLAND_RULE,
    METHOD,
    OPENING_RULE,
    OUTSIDE,
    ColorError,
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
    check_outline_width_setting,
    palette_cap,
)
from tdmg.color_outline import (
    KEEP_RATIO_RULE,
    OUTLINE_METHOD,
    SHADE_CHROMA_RULE,
    SHADE_HUE_RULE,
    SHADE_METHOD,
    THIN_SHARE_RULE,
    keeps_wide_area,
    outline_core,
    shade_pairs,
)
from tdmg.color_plan import FATES
from tdmg.colors import (
    COLORS_ALGORITHM_VERSION,
    LABELS_OUTSIDE,
    OUTPUT_FILES,
    RECORD_NAME,
    RECORD_SCHEMA,
    UNRENDERED_FIELDS,
    ColorsError,
    build_colors,
    check_width_mm,
    colors_id,
    json_plain,
    mask_mm_per_px,
    shade_pair_records,
)
from tdmg.profiles import PrinterProfile, load_printer, printer_ids
from tdmg.rules import load_rules
from tdmg.selection import SelectionError, pixels_sha256, read_selection
from tdmg.smoothing import LABELS_METHOD, SmoothingError, check_supersample, sigma_or_zero

# --- verify_colors: reading a colors folder back (design step 2, geometry) ---------------

EDGE_RULES = {"smooth": SMOOTH_RULE, "furry": FURRY_RULE, "exact": None}
SETTING_KEYS = KEYS
# The only methods this code implements. A record naming another version (older or newer)
# is refused: the rebuild below, and design step 2's fine map, would silently use these.
SUPPORTED_METHODS = {"colors": COLORS_ALGORITHM_VERSION, "quantize": METHOD,
                     "outline": OUTLINE_METHOD, "shade": SHADE_METHOD,
                     "cleanup": CLEANUP_METHOD, "labels": LABELS_METHOD}


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


def verify_colors(colors_dir, selection_dir, *, check_preview: bool = True,
                  rules: dict | None = None) -> VerifiedColors:
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
       the thin share when outline_color is auto, and the wide-area ratio
       (color.outline.keep_area_width_ratio) when the family is not empty; each a finite
       number, and the sigma finite and >= 0. settings.outline_width_mm is wider than the
       identity's opening width (flat.sliver.opening_width).
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
       each lab is srgb_to_lab of its rgb, to LAB_ABS_TOL per component. The outline:
       found_by matches outline_color (auto, none, or config for a list); the family is
       the list (config), empty (none), or exactly the indices whose recorded thinness is
       above the thin share (auto); thinness has one number from 0 to 1 per extracted
       color; family_hex is the family's colors; the core is outline_core of the family on
       the recorded Lab (the darkest member), with its hex; keep_width and
       specks_not_drawn are set exactly under keep with a family, keep_width.mm being
       settings.outline_width_mm. Without a family, stroke_width_px is null and
       wide_components empty; each wide component has an int area of at least 1, a finite
       inscribed width, a centroid of two finite numbers and a bool kept, which is true
       exactly when the ratio rule (keeps_wide_area) says so on its recorded inscribed
       width and the recorded stroke width; they are ordered largest first. The merges'
       from_hex and into_hex are the extraction's colors. Each merged_into is the merge
       setting's; each fate is one of FATES, with final exactly when final_index is set,
       merged exactly when merged_into is set, outline only for an index in
       outline.family (and always for a family member other than the core), band only
       for a color outside the family under outlines keep with a family, and cleanup
       only for a hex in cleanup.dropped_hex; each final_index is a final palette index
       with the same hex; and every final palette entry is the final_index of at least
       one extraction entry with the same hex. The shade pairs are what
       tdmg.color_outline.shade_pairs gives again on the recorded Lab (its numbers to
       LAB_ABS_TOL), for the colors whose fate is final, band or cleanup other than the core,
       with the identity's two shade rules.
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
    9. The rebuild: tdmg.colors.build_colors(render=False) runs the plan again on the
       selection with the identity's settings, printer and rule values (the registry's
       rules, given or tdmg.rules.load_rules(), with their values replaced by the
       identity's). labels.png's pixels must equal the rebuilt labels, and the record must
       equal the rebuilt one in every field except UNRENDERED_FIELDS and settings (whose
       sources and config hash cannot be rebuilt; settings.settings is checked in 3).
       So a labels.png or record changed by hand, with its hashes updated, is refused.
    The printer (checked first, with 2) is the profile the identity names, a known profile
    id; its nozzle must be the identity's, and settings.colors at most its palette cap.
    Settings must not be null, and the identity's methods must be SUPPORTED_METHODS.

    What it cannot check: the UNRENDERED_FIELDS are as the record says, and regions.png is
    only hashed, not redrawn. The rebuild proves that the plan follows from the recorded
    inputs with this code on this machine; a plan made on a machine whose results differ is
    refused (the owner-image results are measured on the Windows PC only).
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
        return _verify(colors_dir, record, selection_dir, check_preview,
                       load_rules() if rules is None else rules)
    except (KeyError, TypeError, AttributeError, IndexError) as e:
        raise ColorsError(f"{path} is missing or has an invalid field: {e!r}") from None
    except ArithmeticError as e:          # OverflowError, ZeroDivisionError ...
        raise ColorsError(f"{path} has values that cannot be computed with: {e}") from None


def _inconsistent(field: str) -> ColorsError:
    return ColorsError(f"colors.json is inconsistent: {field} does not match the identity")


def _identity_printer(ident: dict) -> PrinterProfile:
    """The profile the identity names, with the identity's nozzle."""
    pid = ident["printer"]
    if not isinstance(pid, str) or pid not in printer_ids():
        raise ColorsError(f"identity.printer {pid!r} is not a known printer profile")
    printer = load_printer(pid)
    if float(printer.nozzle_diameter_mm) != ident["nozzle_diameter_mm"]:
        raise ColorsError(f"identity.nozzle_diameter_mm {ident['nozzle_diameter_mm']!r} is "
                          f"not the {pid} profile's nozzle ({printer.nozzle_diameter_mm})")
    return printer


def _identity_values(ident: dict, family, printer: PrinterProfile
                     ) -> tuple[dict, float, int, float, str | None]:
    """Check the identity's types; return its settings, width, supersample, sigma and the
    edges rule id. family: the record's outline family (whether the keep width is used).
    printer: the identity's profile (settings.colors must be within its palette cap)."""
    settings = ident["settings"]
    if not isinstance(settings, dict) or set(settings) != set(SETTING_KEYS):
        raise ColorsError(f"identity.settings must hold exactly {', '.join(SETTING_KEYS)}")
    nulls = [key for key, value in settings.items() if value is None]
    if nulls:
        raise ColorsError(f"identity.settings.{nulls[0]} is null; a resolved setting always "
                          "has a value")
    if ident["methods"] != SUPPORTED_METHODS:
        raise ColorsError("identity.methods are not the methods this version implements "
                          f"({SUPPORTED_METHODS}); remake the plan with this version")
    try:
        ColorConfig.model_validate(settings, context={"cap": palette_cap(printer)})
    except ValidationError as e:
        err = e.errors()[0]
        raise ColorsError(f"identity.settings.{err['loc'][0]} is invalid: {err['msg']} "
                          f"(got {err['input']!r})") from None
    width = check_width_mm(ident["width_mm"])
    try:
        supersample = check_supersample(ident["supersample"])
    except SmoothingError as e:
        raise ColorsError(f"identity.{e}") from None
    edge_rule = EDGE_RULES[settings["edges"]]
    rules = ident["rules"]
    want = ({OPENING_RULE, ISLAND_RULE, SHADE_HUE_RULE, SHADE_CHROMA_RULE}
            | ({edge_rule} if edge_rule else set())
            | ({THIN_SHARE_RULE} if settings["outline_color"] == "auto" else set())
            | ({KEEP_RATIO_RULE} if family else set()))
    if not isinstance(rules, dict) or set(rules) != want:
        raise ColorsError(f"identity.rules must hold exactly {', '.join(sorted(want))}")
    for rule_id, value in rules.items():
        if (isinstance(value, bool) or not isinstance(value, numbers.Real)
                or not math.isfinite(value)):
            raise ColorsError(f"identity.rules[{rule_id!r}] must be a finite number, "
                              f"got {value!r}")
    try:
        sigma = sigma_or_zero(0.0 if edge_rule is None else rules[edge_rule])
    except SmoothingError as e:
        raise ColorsError(f"identity.rules: {e}") from None
    try:
        check_outline_width_setting(settings["outline_width_mm"], rules)
    except ColorConfigError as e:
        raise ColorsError(f"identity.settings: {e}") from None
    return settings, width, supersample, sigma, edge_rule


def _verify(colors_dir: Path, record: dict, selection_dir, check_preview: bool,
            registry: dict) -> VerifiedColors:
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
    printer = _identity_printer(ident)
    settings, width_mm, supersample, sigma, edge_rule = _identity_values(
        ident, outline["family"], printer)
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
                               {r: ident["rules"][r] for r in (THIN_SHARE_RULE, KEEP_RATIO_RULE)
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
    _check_extraction_palette(record)
    _check_fates(record, settings, palette)
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
    sel = _check_selection(selection_dir, ident, inside)
    _check_rebuild(record, labels8, sel, settings, width_mm, supersample, printer,
                   registry)
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
    try:
        check_base(base, k)
    except ColorConfigError as e:
        raise ColorsError(f"colors.json is inconsistent: settings.{e}") from None
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


# The recorded Lab of an extracted color must be the CIELAB of its rgb to within this, per
# component. Not a print threshold: srgb_to_lab uses float powers and cube roots, whose last
# bits may differ between C libraries, so a record written on another machine may differ in
# the last digits. 1e-9 is far below anything that matters (Lab values are of order 1-100,
# and the shade rules' gaps are degrees and whole chroma units) and far above float64
# rounding at that size (about 1e-14).
LAB_ABS_TOL = 1e-9


def _check_extraction_palette(record: dict) -> None:
    """The extraction palette: indices 0..n-1, hex codes = quantize.palette_hex, each hex
    the rgb's, each lab the CIELAB of its rgb (to LAB_ABS_TOL), and the merges' hexes."""
    ext = record["extraction"]["palette"]
    if [e["index"] for e in ext] != list(range(len(ext))) or (
            record["extraction"]["n_extracted"] != len(ext)):
        raise ColorsError("colors.json is inconsistent: extraction indices are not 0..n-1")
    if [e["hex"] for e in ext] != record["quantize"]["palette_hex"]:
        raise ColorsError("colors.json is inconsistent: the extraction palette is not "
                          "quantize.palette_hex")
    for e in ext:
        rgb, lab = e["rgb"], e["lab"]
        if (not isinstance(rgb, list) or len(rgb) != 3
                or not all(type(v) is int and 0 <= v <= 255 for v in rgb)
                or e["hex"] != "#" + "".join(f"{v:02x}" for v in rgb)):
            raise ColorsError(f"colors.json is inconsistent: extraction entry {e['index']}'s "
                              "rgb is not three ints 0..255 with its hex")
        want = srgb_to_lab(np.array([rgb], np.uint8))[0].tolist()
        if (not isinstance(lab, list) or len(lab) != 3
                or not all(not isinstance(v, bool) and isinstance(v, numbers.Real)
                           and math.isclose(v, w, rel_tol=0.0, abs_tol=LAB_ABS_TOL)
                           for v, w in zip(lab, want, strict=True))):
            raise ColorsError(f"colors.json is inconsistent: extraction entry {e['index']}'s "
                              "lab is not the CIELAB of its rgb")
    hexes = [e["hex"] for e in ext]
    for m in record["merges"]:
        for end in ("from", "into"):
            if m[f"{end}_hex"] != hexes[m[end]]:
                raise ColorsError(f"colors.json is inconsistent: the merges' {end}_hex is not "
                                  "the extraction's color")


def _check_outline(record: dict, settings: dict, rules: dict) -> None:
    """The outline block: found_by and the family against outline_color, thinness, the
    auto family, family_hex, the core (the darkest member), keep_width, specks_not_drawn,
    stroke_width_px and the wide components' kept flags."""
    outline = record["outline"]
    ext = record["extraction"]["palette"]
    family = outline["family"]
    oc = settings["outline_color"]
    if outline["found_by"] != (oc if oc in ("auto", "none") else "config"):
        raise _inconsistent("outline.found_by")
    if isinstance(oc, list) and sorted(oc) != family:
        raise ColorsError("colors.json is inconsistent: outline.family is not the "
                          "outline_color list")
    if oc == "none" and family != []:
        raise ColorsError("colors.json is inconsistent: outline.family is not empty but "
                          "outline_color is none")
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
    keep = settings["outlines"] == "keep" and bool(family)
    kw = outline["keep_width"]
    if (kw is None) == keep or (keep and (set(kw) != {"mm", "px"}
                                          or kw["mm"] != settings["outline_width_mm"])):
        raise _inconsistent("outline.keep_width")
    sp = outline["specks_not_drawn"]
    if (sp is None) == keep or (keep and (
            set(sp) != {"count", "px"}
            or not all(type(sp[k]) is int and sp[k] >= 0 for k in ("count", "px"))
            or (sp["count"] == 0) != (sp["px"] == 0))):
        raise ColorsError("colors.json is inconsistent: outline.specks_not_drawn must be a "
                          "count and a pixel total under keep with a family, else null")
    _check_wide_components(outline, rules)


def _check_wide_components(outline: dict, rules: dict) -> None:
    """stroke_width_px and wide_components: empty without a family; otherwise each kept
    flag is the ratio rule's decision on the recorded widths, largest first."""
    sw, comps = outline["stroke_width_px"], outline["wide_components"]
    if sw is not None and (isinstance(sw, bool) or not isinstance(sw, numbers.Real)
                           or not math.isfinite(sw) or sw < 0):
        raise ColorsError("colors.json is inconsistent: outline.stroke_width_px must be null "
                          "or a finite number of at least 0")
    if not isinstance(comps, list):
        raise ColorsError("colors.json is inconsistent: outline.wide_components must be a list")
    if not outline["family"]:
        if sw is not None or comps:
            raise ColorsError("colors.json is inconsistent: with no outline family there is "
                              "no stroke width and no wide component")
        return
    def finite(v) -> bool:
        return not isinstance(v, bool) and isinstance(v, numbers.Real) and math.isfinite(v)

    ratio = rules[KEEP_RATIO_RULE]
    areas = []
    for n, c in enumerate(comps):
        ins, cen = c.get("inscribed_px"), c.get("centroid")
        if (set(c) != {"area_px", "inscribed_px", "centroid", "kept"}
                or type(c["area_px"]) is not int or c["area_px"] < 1
                or not finite(ins) or type(c["kept"]) is not bool
                or not isinstance(cen, list) or len(cen) != 2
                or not all(finite(v) for v in cen)):
            raise ColorsError(f"colors.json is inconsistent: outline.wide_components[{n}] "
                              "must hold area_px, inscribed_px, centroid and kept")
        if c["kept"] != keeps_wide_area(ins, sw, ratio):
            raise ColorsError(f"colors.json is inconsistent: outline.wide_components[{n}].kept "
                              f"is not what {KEEP_RATIO_RULE} gives on its widths")
        areas.append(c["area_px"])
    if areas != sorted(areas, reverse=True):
        raise ColorsError("colors.json is inconsistent: outline.wide_components are not "
                          "largest first")


def _check_fates(record: dict, settings: dict, palette: list) -> None:
    """Each extracted color's merged_into, fate and final_index, and every final color's
    source."""
    ext = record["extraction"]["palette"]
    outline = record["outline"]
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
        elif fate == "band" and (settings["outlines"] != "keep" or not outline["family"]
                                 or i in outline["family"]):
            why = ("only a color outside the outline family, under outlines: keep, can be "
                   "covered by the kept band")
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


def _check_shade_pairs(record: dict, rules: dict) -> None:
    """The shade pairs are recomputed from the extraction palette's Lab (checked to be the
    CIELAB of its rgb) and the identity's shade rules."""
    ext = record["extraction"]["palette"]
    core = record["outline"]["core"]
    candidates = [e["index"] for e in ext
                  if e["fate"] in ("final", "band", "cleanup") and e["index"] != core]
    want = shade_pair_records(shade_pairs([e["lab"] for e in ext], [e["hex"] for e in ext],
                                          candidates, rules[SHADE_HUE_RULE],
                                          rules[SHADE_CHROMA_RULE]))
    got, want = record["shade_pairs"], json_plain(want)
    floats = ("dh_deg", "chroma_i", "chroma_j", "dl")

    def same(a: dict, b: dict) -> bool:
        # The pair, hexes and merge exactly; the numbers to LAB_ABS_TOL, as math's atan2
        # and hypot may differ in the last bits between C libraries.
        return (set(a) == set(b)
                and all(a[k] == b[k] for k in b if k not in floats)
                and all(not isinstance(a[k], bool) and isinstance(a[k], numbers.Real)
                        and math.isclose(a[k], b[k], rel_tol=0.0, abs_tol=LAB_ABS_TOL)
                        for k in floats))
    if (not isinstance(got, list) or len(got) != len(want)
            or not all(isinstance(a, dict) and same(a, b) for a, b in zip(got, want,
                                                                          strict=True))):
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


def _check_selection(selection_dir, ident: dict, inside: np.ndarray):
    """The selection the identity names, read with its cutout; labels exactly in its mask."""
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
    return sel


def _without(record: dict, fields) -> dict:
    """A copy of record with the dotted fields removed (a missing one is ignored)."""
    out = json.loads(json.dumps(record))
    for field in fields:
        *parents, last = field.split(".")
        node = out
        for key in parents:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, dict):
            node.pop(last, None)
    return out


def _check_rebuild(record: dict, labels8: np.ndarray, sel, settings: dict, width_mm: float,
                   supersample: int, printer: PrinterProfile, registry: dict) -> None:
    """Check 9 of verify_colors: the plan rebuilt from the identity equals the record."""
    ident_rules = record["identity"]["rules"]
    unknown = sorted(set(ident_rules) - set(registry))
    if unknown:
        raise ColorsError(f"identity.rules name rules the registry does not have: {unknown}")
    rules = {**registry, **{rid: registry[rid].model_copy(update={"default": value})
                            for rid, value in ident_rules.items()}}
    try:
        rebuilt, _, rebuilt_labels = build_colors(sel, width_mm, settings, record["settings"],
                                                  rules, printer, supersample, render=False)
    except (ColorConfigError, ColorError, ColorsError, SmoothingError) as e:
        raise ColorsError(f"the plan cannot be rebuilt from its identity: {e}") from None
    if not np.array_equal(rebuilt_labels, labels8):
        n = int((rebuilt_labels != labels8).sum())
        raise ColorsError(f"labels.png differs from the plan rebuilt from its identity in {n} "
                          "pixels (changed by hand, or made by a version or machine whose "
                          "results differ)")
    skip = (*UNRENDERED_FIELDS, "settings")
    where = _first_difference(_without(record, skip),
                              _without(json.loads(json.dumps(rebuilt)), skip), "")
    if where is not None:
        raise ColorsError("colors.json differs from the plan rebuilt from its identity at "
                          f"{where or 'the top level'}")


def _first_difference(got, want, path: str) -> str | None:
    """The path of the first difference between two JSON values, or None. A float may
    differ from the other number by LAB_ABS_TOL (last-digit differences of float
    functions between C libraries, as for the Lab check); everything else, ints, bools
    and strings included, must be equal."""
    if isinstance(got, dict) and isinstance(want, dict):
        if set(got) != set(want):
            return f"{path} (keys)"
        for key in sorted(got):
            where = _first_difference(got[key], want[key], f"{path}.{key}" if path else key)
            if where is not None:
                return where
        return None
    if isinstance(got, list) and isinstance(want, list):
        if len(got) != len(want):
            return f"{path} (length)"
        for i, (a, b) in enumerate(zip(got, want, strict=True)):
            where = _first_difference(a, b, f"{path}[{i}]")
            if where is not None:
                return where
        return None
    if (isinstance(got, float) or isinstance(want, float)) and not (
            isinstance(got, bool) or isinstance(want, bool)):
        same = (isinstance(got, numbers.Real) and isinstance(want, numbers.Real)
                and math.isclose(got, want, rel_tol=0.0, abs_tol=LAB_ABS_TOL))
        return None if same else path
    return None if type(got) is type(want) and got == want else path

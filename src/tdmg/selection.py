"""S0 intake and S1 subject selection (docs/plans/2026-11-10-subject-selection.md).

Deterministic: the same image and controls give the same mask, byte for byte, within one
pinned environment. Code does not interpret language. The user's instructions are stored
verbatim and reported as not machine-interpreted. Only explicit controls change the mask.

Coordinates are pixel (x, y): origin at the top-left pixel, x right, y down, after EXIF
orientation. A --remove-at region grows through 4-connected neighbours, so it cannot leak
through a diagonal gap. Foreground pieces use 8-connectivity and holes 4-connectivity,
the standard dual pair.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from pydantic_core import PydanticCustomError

from tdmg import __version__
from tdmg.records import (
    RecordError,
    canonical_json,
    check_output_dir,
    environment,
    png_bytes,
    record_text,
    write_outputs,
)
from tdmg.rules import load_rules

ORIENTATION_TAG = 0x0112   # EXIF Orientation; 1 means "as stored"
TRANSPOSING_ORIENTATIONS = range(2, 9)   # ImageOps.exif_transpose leaves other values untouched
# Pillow's convert("RGBA") clips these to 8 bits instead of rescaling, so they are refused.
# Every 16-bit mode name starts with this prefix (I;16, I;16B, I;16L, I;16N).
UNSUPPORTED_MODES = frozenset({"I", "F"})
UNSUPPORTED_MODE_PREFIX = "I;16"

ALGORITHM_VERSION = "selection-1"
ALPHA_RULE = "perception.alpha.min_opaque"
TOLERANCE_RULE = "perception.flood.color_tolerance"
RECORD_SCHEMA = "tdmg.selection/1"
# Preview display only; these are not thresholds.
CHECKER_CELL_PX = 8
CHECKER_SHADES = (200, 235)
REMOVED_TINT = np.array([255, 0, 255], np.uint16)
RECORD_FIELDS = ("controls", "steps", "result", "interpretation")
NOT_BINARY = "mask must contain only 0 and 255 (black = drop, white = keep)"
NOT_INTERPRETED = ("instructions recorded verbatim but not machine-interpreted; "
                   "no control or mask applied them")

Point = tuple[StrictInt, StrictInt]


class SelectionError(ValueError):
    """A control or input cannot be applied as given. Nothing is written."""


@dataclass(frozen=True)
class Intake:
    rgba: np.ndarray          # H x W x 4 uint8, after EXIF orientation
    file_sha256: str
    pixels_sha256: str
    exif_transposed: bool
    source_name: str

    def __post_init__(self):
        rgba = self.rgba.copy()          # read-only and unshared, so pixels_sha256 stays true
        rgba.flags.writeable = False
        object.__setattr__(self, "rgba", rgba)


def pixels_sha256(arr: np.ndarray) -> str:
    """Hash of shape and pixel bytes, independent of file encoding.

    The pixels are what Pillow decodes and converts to RGBA, with no colour management, so
    embedded ICC profiles are ignored and CMYK uses Pillow's conversion formula.
    """
    a = np.ascontiguousarray(arr)
    return hashlib.sha256(repr((a.shape, str(a.dtype))).encode() + a.tobytes()).hexdigest()


def _open_checked(path: Path, data: bytes) -> Image.Image:
    """Open and decode an image Pillow reads faithfully as 8-bit: one frame, no 16-bit or
    float, and complete pixel data."""
    try:
        im = Image.open(io.BytesIO(data))
    except UnidentifiedImageError as e:
        raise SelectionError(f"{path.name} is not a readable image") from e
    except Image.DecompressionBombError as e:
        raise SelectionError(f"{path.name} is larger than Pillow's safety limit "
                             f"({2 * Image.MAX_IMAGE_PIXELS} pixels)") from e
    try:
        if im.mode in UNSUPPORTED_MODES or im.mode.startswith(UNSUPPORTED_MODE_PREFIX):
            raise SelectionError(f"{path.name} has mode {im.mode}: 16-bit and floating-point "
                                 "images are not supported; export as 8-bit")
        n_frames = getattr(im, "n_frames", 1)
        if n_frames > 1:
            raise SelectionError(f"{path.name} has {n_frames} frames; export the frame you "
                                 "want as a single image")
        try:
            im.load()
        except OSError as e:          # e.g. "image file is truncated"
            raise SelectionError(f"{path.name} is not a readable image: {e}") from e
    except SelectionError:
        im.close()
        raise
    return im


def load_image(path: str | Path) -> Intake:
    path = Path(path)
    data = path.read_bytes()
    with _open_checked(path, data) as im:
        orientation = im.getexif().get(ORIENTATION_TAG, 1)
        oriented = ImageOps.exif_transpose(im)
        rgba = np.asarray(oriented.convert("RGBA")).copy()
    return Intake(rgba=rgba, file_sha256=hashlib.sha256(data).hexdigest(),
                  pixels_sha256=pixels_sha256(rgba),
                  exif_transposed=orientation in TRANSPOSING_ORIENTATIONS,
                  source_name=path.name)


class SelectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instructions: str | None = None
    alpha_min: StrictInt | None = None           # range checked against the rule in _pick
    color_tolerance: float | None = Field(default=None, allow_inf_nan=False)
    remove_at: tuple[Point, ...] = ()
    keep_at: tuple[Point, ...] = ()

    @field_validator("color_tolerance", mode="before")
    @classmethod
    def _no_bool_tolerance(cls, v):
        if isinstance(v, bool):
            raise PydanticCustomError("bool_tolerance",
                                      "color_tolerance must be a number, not a boolean")
        return v


@dataclass(frozen=True)
class Selection:
    mask: np.ndarray                     # H x W bool, read-only
    controls: dict
    steps: list[dict]
    result: dict
    interpretation: dict
    input_pixels_sha256: str             # the intake this selection was made from
    # JSON text of the record fields, taken at construction. write_selection uses only this,
    # so editing the dicts afterwards cannot change the selection_id or the record.
    _snapshot: str = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        mask = self.mask.copy()          # never freeze or share the caller's array
        mask.flags.writeable = False
        object.__setattr__(self, "mask", mask)
        for name in RECORD_FIELDS:       # own copies, unshared
            object.__setattr__(self, name, copy.deepcopy(getattr(self, name)))
        # Text, not bytes: encoding errors (e.g. a lone surrogate) surface in write_selection.
        object.__setattr__(self, "_snapshot", json.dumps(
            {name: getattr(self, name) for name in RECORD_FIELDS}, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False, allow_nan=False))

    def snapshot(self) -> dict:
        """Fresh copies of controls, steps, result and interpretation as constructed."""
        return json.loads(self._snapshot)


def _interpretation(spec: SelectionSpec) -> dict:
    return {"text": spec.instructions, "machine_interpreted": False}


def _pick(rules: dict, field: str, value, rule_id: str, cast) -> dict:
    """The explicit value, or the rule's default, checked against the rule's range."""
    if value is not None:
        chosen = {"value": cast(value), "rule": None}
    else:
        chosen = {"value": cast(rules[rule_id].default), "rule": rule_id}
    v = chosen["value"]
    lo, hi = rules[rule_id].range
    if not math.isfinite(v) or not lo <= v <= hi:
        raise SelectionError(f"{field} {v:g} is outside {rule_id} range [{lo:g}, {hi:g}]")
    return chosen


def _resolve(spec: SelectionSpec) -> dict:
    """Controls that select_subject uses. color_tolerance appears only with remove_at seeds."""
    if spec.color_tolerance is not None and not spec.remove_at:
        raise SelectionError("color_tolerance has no effect without remove_at")
    rules = load_rules()
    controls = {"alpha_min": _pick(rules, "alpha_min", spec.alpha_min, ALPHA_RULE, int)}
    if spec.remove_at:
        controls["color_tolerance"] = _pick(rules, "color_tolerance", spec.color_tolerance,
                                            TOLERANCE_RULE, float)
    controls["remove_at"] = [list(p) for p in spec.remove_at]
    controls["keep_at"] = [list(p) for p in spec.keep_at]
    return controls


def _selected_point(mask: np.ndarray, p: Point, what: str) -> tuple[int, int]:
    x, y = p
    h, w = mask.shape
    if not (0 <= x < w and 0 <= y < h):
        raise SelectionError(f"{what} point {x},{y} is outside the {w}x{h} image")
    if not mask[y, x]:
        raise SelectionError(f"{what} point {x},{y} is not in the current selection "
                             "(transparent, or already removed)")
    return x, y


def _piece_areas(mask: np.ndarray) -> list[int]:
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return sorted((int(a) for a in stats[1:, cv2.CC_STAT_AREA]), reverse=True)


def _hole_areas(mask: np.ndarray) -> list[int]:
    n, lab = cv2.connectedComponents((~mask).astype(np.uint8), connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist())
    counts = np.bincount(lab.ravel(), minlength=n)
    return sorted((int(counts[i]) for i in range(1, n) if i not in border), reverse=True)


def _result(mask: np.ndarray, warnings: list[str]) -> dict:
    warnings = list(warnings)
    pieces = _piece_areas(mask)
    if not pieces:
        status = "empty"
        warnings.append("nothing selected")
    elif len(pieces) == 1:
        status = "one_piece"
    else:
        status = "multiple_pieces"
        warnings.append(f"{len(pieces)} separate pieces; choose with --keep-at, or expect "
                        "separate bodies downstream")
    return {"status": status, "selected_px": int(mask.sum()), "pieces_px": pieces,
            "holes_px": _hole_areas(mask), "warnings": warnings}


def select_subject(intake: Intake, spec: SelectionSpec) -> Selection:
    controls = _resolve(spec)
    controls["source"] = "controls"
    rgb = intake.rgba[..., :3].astype(np.int32)
    mask = intake.rgba[..., 3] >= controls["alpha_min"]["value"]
    steps = [{"op": "alpha", "selected_px": int(mask.sum())}]
    if spec.remove_at:
        tol2 = controls["color_tolerance"]["value"] ** 2
    for p in spec.remove_at:
        x, y = _selected_point(mask, p, "remove_at")
        seed = rgb[y, x]
        near = mask & (((rgb - seed) ** 2).sum(axis=-1) <= tol2)
        _, lab = cv2.connectedComponents(near.astype(np.uint8), connectivity=4)
        region = lab == lab[y, x]
        mask &= ~region
        steps.append({"op": "remove_at", "point": [x, y], "seed_rgb": seed.tolist(),
                      "removed_px": int(region.sum())})
    if spec.keep_at:
        if len(set(spec.keep_at)) != len(spec.keep_at):
            dup = next(p for i, p in enumerate(spec.keep_at) if p in spec.keep_at[:i])
            raise SelectionError(f"duplicate keep_at point {dup[0]},{dup[1]}")
        n, lab = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
        labels = sorted({int(lab[y, x]) for x, y in
                         (_selected_point(mask, p, "keep_at") for p in spec.keep_at)})
        mask = np.isin(lab, labels)
        steps.append({"op": "keep_at", "points": [list(p) for p in spec.keep_at],
                      "pieces_before": n - 1, "pieces_kept": len(labels),
                      "selected_px": int(mask.sum())})
    warnings = []
    if spec.instructions and not (spec.remove_at or spec.keep_at):
        warnings.append(NOT_INTERPRETED)
    return Selection(mask=mask, controls=controls, steps=steps,
                     result=_result(mask, warnings), interpretation=_interpretation(spec),
                     input_pixels_sha256=intake.pixels_sha256)


def load_mask(path: str | Path, shape: tuple[int, int]) -> np.ndarray:
    """A corrected mask: 8-bit or 1-bit, only 0 and 255, same size as the oriented image.

    The mask is read as stored. A mask with an EXIF Orientation of 2-8 is refused, because
    it is ambiguous whether it was drawn on the stored or the displayed image.
    """
    path = Path(path)
    with _open_checked(path, path.read_bytes()) as im:
        if im.getexif().get(ORIENTATION_TAG, 1) in TRANSPOSING_ORIENTATIONS:
            raise SelectionError("mask has an EXIF rotation tag; save it without one so it "
                                 "matches the image's displayed orientation")
        if im.has_transparency_data and (np.asarray(im.convert("RGBA"))[..., 3] != 255).any():
            raise SelectionError("mask has transparent pixels; use an opaque black/white image")
        arr = _mask_values(im)
    if arr.shape != tuple(shape):
        raise SelectionError(f"mask size {arr.shape[1]}x{arr.shape[0]} does not match image "
                             f"size {shape[1]}x{shape[0]}")
    if not np.isin(arr, (0, 255)).all():
        raise SelectionError(NOT_BINARY)
    return arr == 255


def _mask_values(im: Image.Image) -> np.ndarray:
    """One grey value per pixel, read from the decoded channels without rounding.

    Colour pixels must have equal channels; (0, 0, 4) is not black. Transparency has been
    refused already, so any alpha channel is all 255 and is ignored.
    """
    if im.mode in ("1", "L"):
        return np.asarray(im.convert("L"))            # "1" maps exactly to 0 and 255
    if im.mode == "LA":
        return np.asarray(im)[..., 0]
    if im.mode in ("RGB", "RGBA", "P", "PA"):
        rgb = np.asarray(im if im.mode in ("RGB", "RGBA") else im.convert("RGB"))[..., :3]
        if not ((rgb[..., 0] == rgb[..., 1]) & (rgb[..., 1] == rgb[..., 2])).all():
            raise SelectionError(NOT_BINARY)
        return rgb[..., 0]
    raise SelectionError(f"mask has mode {im.mode}; save it as a black/white PNG "
                         "(mode 1, L, P, RGB or RGBA)")


def select_from_mask(intake: Intake, mask: np.ndarray, spec: SelectionSpec) -> Selection:
    if spec.remove_at or spec.keep_at:
        raise SelectionError("use either --mask or --remove-at/--keep-at, not both")
    if spec.color_tolerance is not None:
        raise SelectionError("--tolerance has no effect with --mask")
    shape = intake.rgba.shape[:2]
    if mask.dtype != np.bool_ or mask.shape != shape:
        raise SelectionError(f"mask must be a {shape[1]}x{shape[0]} boolean array; got "
                             f"shape {mask.shape} and dtype {mask.dtype}")
    controls = {"alpha_min": _pick(load_rules(), "alpha_min", spec.alpha_min, ALPHA_RULE, int),
                "source": "user_mask", "user_mask_sha256": pixels_sha256(mask)}
    warnings = []
    transparent = int((mask & (intake.rgba[..., 3] < controls["alpha_min"]["value"])).sum())
    if transparent:
        warnings.append(f"{transparent} selected pixels are transparent in the image")
    return Selection(mask=mask, controls=controls,
                     steps=[{"op": "user_mask", "selected_px": int(mask.sum())}],
                     result=_result(mask, warnings), interpretation=_interpretation(spec),
                     input_pixels_sha256=intake.pixels_sha256)


def _checker(h: int, w: int) -> np.ndarray:
    """H x W uint8 checkerboard; the top-left cell uses CHECKER_SHADES[1]."""
    rows = (np.arange(h) // CHECKER_CELL_PX % 2).astype(bool)
    cols = (np.arange(w) // CHECKER_CELL_PX % 2).astype(bool)
    cell = rows[:, None] ^ cols[None, :]
    return np.where(cell, np.uint8(CHECKER_SHADES[0]), np.uint8(CHECKER_SHADES[1]))


def _preview(rgba: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Left: the original composited over a checkerboard. Right: the result.

    On the right, kept pixels are shown opaque in their original colour, as in cutout.png.
    Removed pixels that are visible (alpha > 0) are the left-hand colour blended 50/50 with
    magenta, whatever their alpha. Transparent pixels show the checkerboard. Integer
    arithmetic only, rounded half up.
    """
    h, w = mask.shape
    out = np.empty((h, 2 * w, 3), np.uint8)
    left, right = out[:, :w], out[:, w:]
    bg = _checker(h, w)[..., None]
    a = rgba[..., 3:4].astype(np.uint16)
    # At most 255 * 255 + 127 = 65152, so uint16 does not overflow.
    np.floor_divide(rgba[..., :3] * a + bg * (255 - a) + 127, 255, out=left, casting="unsafe")
    right[...] = bg
    right[mask] = rgba[..., :3][mask]
    removed = ~mask & (rgba[..., 3] > 0)
    right[removed] = (left[removed] + REMOVED_TINT + 1) // 2
    return out


def selection_identity(algorithm: str, input_pixels_sha256: str, controls: dict,
                       instructions: str | None) -> str:
    """selection_id: SHA-256 of the canonical JSON of these four fields.

    The one definition, used by write_selection and by stages that verify a selection.
    Raises ValueError for NaN in the controls and UnicodeEncodeError (a ValueError) for
    text that UTF-8 cannot encode.
    """
    identity = {"algorithm": algorithm, "input_pixels_sha256": input_pixels_sha256,
                "controls": controls, "instructions": instructions}
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def write_selection(intake: Intake, sel: Selection, out_dir: str | Path) -> dict:
    """Write mask.png, cutout.png, preview.png and selection.json into a new or empty folder.

    Everything is built and encoded in memory first, so a refused selection writes nothing.
    The PNGs are then written, and selection.json last, by tdmg.records.write_outputs. The
    folder as a whole is not atomic: a folder without selection.json is incomplete and must
    not be used. The record holds no absolute paths and no timestamps.
    """
    try:
        create_folder = check_output_dir(out_dir)
    except RecordError as e:
        raise SelectionError(str(e)) from None
    if sel.input_pixels_sha256 != intake.pixels_sha256:
        raise SelectionError("this selection was made from a different image than the one "
                             "given; select again from this image")
    mask8 = np.where(sel.mask, 255, 0).astype(np.uint8)
    cutout = np.where(sel.mask[..., None], intake.rgba, 0).astype(np.uint8)
    cutout[..., 3] = mask8
    pngs = {"mask.png": png_bytes(mask8), "cutout.png": png_bytes(cutout),
            "preview.png": png_bytes(_preview(intake.rgba, sel.mask))}
    h, w = sel.mask.shape
    # Provenance is deliberately part of the identity: a value given explicitly and the same
    # value taken from the rule default ({"rule": None} vs {"rule": id}) give different ids.
    # In mask mode the controls carry user_mask_sha256, so the mask is part of the id too.
    # Built from the construction-time snapshot, never from the live dicts.
    snap, for_id = sel.snapshot(), sel.snapshot()    # two independent copies
    try:
        record = {
            "schema": RECORD_SCHEMA, "tdmg_version": __version__,
            "algorithm": ALGORITHM_VERSION,
            "selection_id": selection_identity(ALGORITHM_VERSION, intake.pixels_sha256,
                                               for_id["controls"],
                                               for_id["interpretation"]["text"]),
            "input": {"name": intake.source_name, "file_sha256": intake.file_sha256,
                      "pixels_sha256": intake.pixels_sha256, "width": w, "height": h,
                      "exif_transposed": intake.exif_transposed},
            # Fresh copies, so editing the returned record cannot change the Selection.
            **snap,
            # The cache keys are selection_id and mask_pixels_sha256. The output file hashes
            # are integrity hashes, valid within this environment only: PNG bytes depend on
            # the Pillow and zlib versions. The environment is not part of selection_id.
            "mask_pixels_sha256": pixels_sha256(sel.mask),
            "outputs": {name: hashlib.sha256(data).hexdigest() for name, data in pngs.items()},
            "environment": environment(),
            "review": "Open preview.png and confirm the subject before generating geometry.",
        }
        data = record_text(record)
    except UnicodeEncodeError as e:
        raise SelectionError(f"instructions or input name cannot be stored as UTF-8: "
                             f"{e.reason} at position {e.start}") from None
    try:
        write_outputs(out_dir, pngs, "selection.json", data, create_folder=create_folder)
    except RecordError as e:
        raise SelectionError(str(e)) from None
    return record


# --- Reading a selection folder back (tdmg flat, tdmg colors) ------------------------

HEX64 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, eq=False)
class VerifiedSelection:
    """A tdmg select output folder, read and checked by read_selection. Arrays read-only.

    record: selection.json as parsed. record_sha256: SHA-256 of its bytes as stored.
    mask: H x W bool, from mask.png, whose pixel hash matches the record.
    cutout_rgb: H x W x 3 uint8, the RGB of cutout.png (black outside the mask), and
    cutout_pixels_sha256: pixels_sha256 of the decoded H x W x 4 RGBA; both None unless
    read_selection was asked for the cutout.
    """

    record: dict
    record_sha256: str
    mask: np.ndarray
    cutout_rgb: np.ndarray | None = None
    cutout_pixels_sha256: str | None = None


def _is_hex64(value) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def read_selection(selection_dir: str | Path, *, cutout: bool = False) -> VerifiedSelection:
    """Read a tdmg select folder and verify it, or raise SelectionError. Nothing is written.

    Checks: selection.json is UTF-8 JSON with schema RECORD_SCHEMA; the fields that identify
    the selection are present and selection_id matches them (recomputed by
    selection_identity); mask.png is a valid mask of the recorded size whose pixel hash is
    mask_pixels_sha256. With cutout=True, also: the SHA-256 of cutout.png's bytes equals
    outputs["cutout.png"], and the decoded image is RGBA of the image size whose alpha is
    the mask (255 inside, 0 outside).

    What it cannot check: selection_id does not cover the outputs block, so a cutout.png
    edited together with its hash in selection.json passes (except for its alpha). Stages
    that use the cutout record its pixel hash, so their records say exactly what they used.
    """
    selection_dir = Path(selection_dir)
    record_path = selection_dir / "selection.json"
    if not record_path.is_file():
        raise SelectionError(f"{record_path} not found; give a tdmg select output folder")
    raw = record_path.read_bytes()
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise SelectionError(f"{record_path} is not valid JSON: {e}") from None
    if not isinstance(record, dict) or record.get("schema") != RECORD_SCHEMA:
        raise SelectionError(f"{record_path} is not a {RECORD_SCHEMA} record")
    _check_provenance(record, record_path)
    w, h = record["input"]["width"], record["input"]["height"]
    mask_path = selection_dir / "mask.png"
    if not mask_path.is_file():
        raise SelectionError(f"{mask_path} not found")
    try:
        mask = load_mask(mask_path, (h, w))
    except SelectionError as e:
        raise SelectionError(f"mask.png cannot be used: {e}") from None
    if pixels_sha256(mask) != record["mask_pixels_sha256"]:
        raise SelectionError("mask.png does not match selection.json")
    mask.flags.writeable = False
    rgb = digest = None
    if cutout:
        rgb, digest = _read_cutout(selection_dir, record, record_path, mask)
    return VerifiedSelection(record=record, record_sha256=hashlib.sha256(raw).hexdigest(),
                             mask=mask, cutout_rgb=rgb, cutout_pixels_sha256=digest)


def _read_cutout(selection_dir: Path, record: dict, record_path: Path,
                 mask: np.ndarray) -> tuple[np.ndarray, str]:
    outputs = record.get("outputs")
    expected = outputs.get("cutout.png") if isinstance(outputs, dict) else None
    if not _is_hex64(expected):
        raise SelectionError(f"{record_path} is missing or has invalid: outputs.cutout.png")
    path = selection_dir / "cutout.png"
    if not path.is_file():
        raise SelectionError(f"{path} not found")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise SelectionError("cutout.png does not match selection.json")
    with _open_checked(path, data) as im:
        if im.mode != "RGBA":
            raise SelectionError(f"cutout.png has mode {im.mode}, not RGBA")
        rgba = np.asarray(im).copy()
    if rgba.shape[:2] != mask.shape:
        raise SelectionError(f"cutout.png size {rgba.shape[1]}x{rgba.shape[0]} does not "
                             f"match the mask's {mask.shape[1]}x{mask.shape[0]}")
    if not np.array_equal(rgba[..., 3], np.where(mask, 255, 0)):
        raise SelectionError("cutout.png's transparency does not match mask.png")
    rgb = np.ascontiguousarray(rgba[..., :3])
    rgb.flags.writeable = False
    return rgb, pixels_sha256(rgba)


def _check_provenance(record: dict, record_path: Path) -> None:
    """The fields that identify the selection are present, and selection_id matches them.

    The id is recomputed with selection_identity, the definition write_selection uses, so
    an edited control, instruction or input hash with the old id is refused.
    """
    size = record.get("input")
    if not isinstance(size, dict):
        raise SelectionError(f"{record_path} has no input block")
    if not all(type(size.get(k)) is int and size[k] > 0 for k in ("width", "height")):
        raise SelectionError(f"{record_path} has no valid input width and height")
    interpretation = record.get("interpretation")
    fields = {"algorithm": isinstance(record.get("algorithm"), str),
              "controls": isinstance(record.get("controls"), dict),
              "input.pixels_sha256": _is_hex64(size.get("pixels_sha256")),
              "interpretation.text": isinstance(interpretation, dict)
              and "text" in interpretation
              and isinstance(interpretation["text"], (str, type(None))),
              "mask_pixels_sha256": _is_hex64(record.get("mask_pixels_sha256")),
              "selection_id": _is_hex64(record.get("selection_id"))}
    bad = [name for name, ok in fields.items() if not ok]
    if bad:
        raise SelectionError(f"{record_path} is missing or has invalid: {', '.join(bad)}")
    try:
        recomputed = selection_identity(record["algorithm"], size["pixels_sha256"],
                                        record["controls"], interpretation["text"])
    except ValueError as e:          # NaN in the controls, or text UTF-8 cannot encode
        raise SelectionError(f"selection.json is inconsistent: its identity cannot be "
                             f"recomputed ({e})") from None
    if recomputed != record["selection_id"]:
        raise SelectionError("selection.json is inconsistent: selection_id does not match "
                             "its algorithm, input pixels, controls and instructions")

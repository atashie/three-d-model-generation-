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
import os
import platform
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import PIL
from PIL import Image, ImageOps, UnidentifiedImageError, features
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from pydantic_core import PydanticCustomError

from tdmg import __version__
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


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _png_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")    # mode inferred: L, RGB or RGBA
    return buf.getvalue()


def _environment() -> dict:
    return {"python": platform.python_version(), "numpy": np.__version__,
            "pillow": PIL.__version__, "opencv": cv2.__version__,
            "zlib": features.version("zlib")}


def write_selection(intake: Intake, sel: Selection, out_dir: str | Path) -> dict:
    """Write mask.png, cutout.png, preview.png and selection.json into a new or empty folder.

    Everything is built and encoded in memory first, so a refused selection writes nothing.
    The PNGs are then written, and selection.json last, through a temporary name and an
    atomic rename. The folder as a whole is not atomic: a folder without selection.json is
    incomplete and must not be used. The record holds no absolute paths and no timestamps.
    """
    out = Path(out_dir)
    create_folder = not out.exists()
    if out.exists() and not out.is_dir():
        raise SelectionError(f"output path {out} is a file, not a folder; choose a new one")
    if out.exists() and any(out.iterdir()):
        raise SelectionError(f"output folder {out} is not empty; choose a new one")
    if sel.input_pixels_sha256 != intake.pixels_sha256:
        raise SelectionError("this selection was made from a different image than the one "
                             "given; select again from this image")
    mask8 = np.where(sel.mask, 255, 0).astype(np.uint8)
    cutout = np.where(sel.mask[..., None], intake.rgba, 0).astype(np.uint8)
    cutout[..., 3] = mask8
    pngs = {"mask.png": _png_bytes(mask8), "cutout.png": _png_bytes(cutout),
            "preview.png": _png_bytes(_preview(intake.rgba, sel.mask))}
    h, w = sel.mask.shape
    # Provenance is deliberately part of the identity: a value given explicitly and the same
    # value taken from the rule default ({"rule": None} vs {"rule": id}) give different ids.
    # In mask mode the controls carry user_mask_sha256, so the mask is part of the id too.
    # Built from the construction-time snapshot, never from the live dicts.
    snap, for_id = sel.snapshot(), sel.snapshot()    # two independent copies
    identity = {"algorithm": ALGORITHM_VERSION, "input_pixels_sha256": intake.pixels_sha256,
                "controls": for_id["controls"],
                "instructions": for_id["interpretation"]["text"]}
    try:
        record = {
            "schema": RECORD_SCHEMA, "tdmg_version": __version__,
            "algorithm": ALGORITHM_VERSION,
            "selection_id": hashlib.sha256(_canonical(identity)).hexdigest(),
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
            "environment": _environment(),
            "review": "Open preview.png and confirm the subject before generating geometry.",
        }
        text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False,
                          allow_nan=False) + "\n"
        data = text.encode("utf-8")      # bytes, so Windows cannot turn "\n" into "\r\n"
    except UnicodeEncodeError as e:
        raise SelectionError(f"instructions or input name cannot be stored as UTF-8: "
                             f"{e.reason} at position {e.start}") from None
    busy = f"another run is writing to {out}; choose a new folder"
    if create_folder:
        # Decided at the check above: a folder that has appeared since is another run's.
        try:
            out.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            if out.is_dir():
                raise SelectionError(busy) from None
            raise                        # e.g. a parent is a file: a plain OS error
    try:
        # Exclusive create: a second writer fails at its first PNG instead of overwriting.
        for name, png in pngs.items():
            with open(out / name, "xb") as f:
                f.write(png)
    except FileExistsError:
        raise SelectionError(busy) from None
    with tempfile.NamedTemporaryFile(dir=out, delete=False, prefix=".selection-",
                                     suffix=".tmp") as f:
        f.write(data)
    # os.replace overwrites on Windows too, but two writers cannot both get here: the second
    # one has already failed on its first "xb" PNG above.
    os.replace(f.name, out / "selection.json")
    return record

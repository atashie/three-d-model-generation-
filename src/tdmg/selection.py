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

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from tdmg.rules import load_rules

ORIENTATION_TAG = 0x0112   # EXIF Orientation; 1 means "as stored"
TRANSPOSING_ORIENTATIONS = range(2, 9)   # ImageOps.exif_transpose leaves other values untouched
# Pillow's convert("RGBA") clips these to 8 bits instead of rescaling, so they are refused.
UNSUPPORTED_MODES = frozenset({"I;16", "I;16B", "I;16L", "I", "F"})

ALGORITHM_VERSION = "selection-1"
ALPHA_RULE = "perception.alpha.min_opaque"
TOLERANCE_RULE = "perception.flood.color_tolerance"
NOT_INTERPRETED = ("instructions recorded verbatim but not machine-interpreted; "
                   "no control or mask applied them")

Point = tuple[int, int]


class SelectionError(ValueError):
    """A control or input cannot be applied as given. Nothing is written."""


@dataclass(frozen=True)
class Intake:
    rgba: np.ndarray          # H x W x 4 uint8, after EXIF orientation
    file_sha256: str
    pixels_sha256: str
    exif_transposed: bool
    source_name: str


def pixels_sha256(arr: np.ndarray) -> str:
    """Hash of shape and pixel bytes, independent of file encoding.

    The pixels are what Pillow decodes and converts to RGBA, with no colour management, so
    embedded ICC profiles are ignored and CMYK uses Pillow's conversion formula.
    """
    a = np.ascontiguousarray(arr)
    return hashlib.sha256(repr((a.shape, str(a.dtype))).encode() + a.tobytes()).hexdigest()


def load_image(path: str | Path) -> Intake:
    path = Path(path)
    data = path.read_bytes()
    try:
        im = Image.open(io.BytesIO(data))
    except UnidentifiedImageError as e:
        raise SelectionError(f"{path.name} is not a readable image") from e
    with im:
        if im.mode in UNSUPPORTED_MODES or im.mode.startswith("I;16"):
            raise SelectionError(f"{path.name} has mode {im.mode}: 16-bit and floating-point "
                                 "images are not supported; export as 8-bit")
        n_frames = getattr(im, "n_frames", 1)
        if n_frames > 1:
            raise SelectionError(f"{path.name} has {n_frames} frames; export the frame you "
                                 "want as a single image")
        im.load()
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
    alpha_min: int | None = Field(default=None, ge=1, le=255)
    color_tolerance: float | None = Field(default=None, ge=0)
    remove_at: tuple[Point, ...] = ()
    keep_at: tuple[Point, ...] = ()


@dataclass
class Selection:
    mask: np.ndarray                     # H x W bool
    controls: dict
    steps: list[dict]
    result: dict
    interpretation: dict


def _resolve(spec: SelectionSpec) -> dict:
    rules = load_rules()

    def pick(value, rule_id, cast):
        if value is not None:
            return {"value": cast(value), "rule": None}
        return {"value": cast(rules[rule_id].default), "rule": rule_id}

    return {"alpha_min": pick(spec.alpha_min, ALPHA_RULE, int),
            "color_tolerance": pick(spec.color_tolerance, TOLERANCE_RULE, float),
            "remove_at": [list(p) for p in spec.remove_at],
            "keep_at": [list(p) for p in spec.keep_at]}


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
    pieces = _piece_areas(mask)
    if not pieces:
        status = "empty"
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
        n, lab = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
        labels = sorted({int(lab[y, x]) for x, y in
                         (_selected_point(mask, p, "keep_at") for p in spec.keep_at)})
        mask = np.isin(lab, labels)
        steps.append({"op": "keep_at", "points": controls["keep_at"], "pieces_before": n - 1,
                      "pieces_kept": len(labels), "selected_px": int(mask.sum())})
    warnings = []
    if spec.instructions and not (spec.remove_at or spec.keep_at):
        warnings.append(NOT_INTERPRETED)
    return Selection(mask=mask, controls=controls, steps=steps,
                     result=_result(mask, warnings),
                     interpretation={"text": spec.instructions, "machine_interpreted": False})

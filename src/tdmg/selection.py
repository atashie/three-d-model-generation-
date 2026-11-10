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

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

ORIENTATION_TAG = 0x0112   # EXIF Orientation; 1 means "as stored"
TRANSPOSING_ORIENTATIONS = range(2, 9)   # ImageOps.exif_transpose leaves other values untouched
# Pillow's convert("RGBA") clips these to 8 bits instead of rescaling, so they are refused.
UNSUPPORTED_MODES = frozenset({"I;16", "I;16B", "I;16L", "I", "F"})


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

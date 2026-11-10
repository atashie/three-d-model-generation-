"""Shared helpers for writing a stage's outputs and its record (selection.json and later).

A stage encodes everything in memory first, so a refused run writes nothing. It then writes
its files into a new or empty folder with exclusive creates, and its record last, through a
temporary name and an atomic rename. The folder as a whole is not atomic: a folder without
the record is incomplete and must not be used.
"""

from __future__ import annotations

import io
import json
import os
import platform
import tempfile
from pathlib import Path

import cv2
import numpy as np
import PIL
from PIL import Image, features


class RecordError(ValueError):
    """The outputs cannot be written as asked. Nothing of ours is written."""


def canonical_json(obj) -> bytes:
    """Compact, key-sorted UTF-8 JSON; NaN and infinity are refused."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def png_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")    # mode inferred: L, RGB or RGBA
    return buf.getvalue()


def environment() -> dict:
    return {"python": platform.python_version(), "numpy": np.__version__,
            "pillow": PIL.__version__, "opencv": cv2.__version__,
            "zlib": features.version("zlib")}


def check_output_dir(out_dir: str | Path) -> bool:
    """Refuse a file or a non-empty folder. True if the folder must be created.

    A caller that encodes its outputs after this check passes the result to write_outputs,
    so a folder or file that appears in the meantime is detected as another run's.
    """
    out = Path(out_dir)
    if out.exists() and not out.is_dir():
        raise RecordError(f"output path {out} is a file, not a folder; choose a new one")
    if out.exists() and any(out.iterdir()):
        raise RecordError(f"output folder {out} is not empty; choose a new one")
    return not out.exists()


def write_outputs(out_dir: str | Path, files: dict[str, bytes], record_name: str,
                  record_bytes: bytes, *, create_folder: bool | None = None) -> None:
    """Write each file with an exclusive create, then the record through os.replace.

    create_folder is check_output_dir's result; when None, the check runs here.
    """
    out = Path(out_dir)
    if create_folder is None:
        create_folder = check_output_dir(out)
    busy = f"another run is writing to {out}; choose a new folder"
    if create_folder:
        # Decided at the check: a folder that has appeared since is another run's.
        try:
            out.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            if out.is_dir():
                raise RecordError(busy) from None
            raise                        # e.g. a parent is a file: a plain OS error
    try:
        # Exclusive create: a second writer fails at its first file instead of overwriting.
        for name, data in files.items():
            with open(out / name, "xb") as f:
                f.write(data)
    except FileExistsError:
        raise RecordError(busy) from None
    with tempfile.NamedTemporaryFile(dir=out, delete=False, prefix=f".{Path(record_name).stem}-",
                                     suffix=".tmp") as f:
        f.write(record_bytes)
    # os.replace overwrites on Windows too, but two writers cannot both get here: the second
    # one has already failed on its first "xb" file above.
    os.replace(f.name, out / record_name)

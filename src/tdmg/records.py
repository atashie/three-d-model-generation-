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
from PIL import Image, features
from PIL import __version__ as pillow_version


class RecordError(ValueError):
    """The outputs cannot be written as asked. Nothing of ours is written."""


def canonical_json(obj) -> bytes:
    """Compact, key-sorted UTF-8 JSON; NaN and infinity are refused."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def record_text(record: dict) -> bytes:
    """Indented, key-sorted JSON with one trailing newline, as UTF-8 bytes.

    Bytes, so Windows cannot turn "\\n" into "\\r\\n". NaN and infinity raise ValueError; text
    that UTF-8 cannot encode (a lone surrogate) raises UnicodeEncodeError for the caller to
    report in its own terms.
    """
    text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False,
                      allow_nan=False) + "\n"
    return text.encode("utf-8")


def png_bytes(arr: np.ndarray) -> bytes:
    """PNG of a uint8 array: H x W (L), H x W x 3 (RGB) or H x W x 4 (RGBA).

    The pixels are exact, but the bytes depend on the Pillow and zlib versions.
    """
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")    # mode inferred: L, RGB or RGBA
    return buf.getvalue()


def environment() -> dict:
    """Library versions, recorded for provenance. Never part of an id."""
    return {"python": platform.python_version(), "numpy": np.__version__,
            "pillow": pillow_version, "opencv": cv2.__version__,
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

    Names are checked before anything touches the disk: each must be a plain file name.
    create_folder is check_output_dir's result. A caller that runs check_output_dir before
    its expensive encoding fails fast and passes the result here; when None, the check runs
    here. create_folder=False for a folder that does not exist fails at the first write.
    """
    for name in (*files, record_name):
        if name in ("", ".", "..") or "/" in name or "\\" in name or Path(name).name != name:
            raise RecordError(f"output name {name!r} is not a plain file name")
    if record_name in files:
        raise RecordError(f"record name {record_name!r} is also one of the output files")
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
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=out, delete=False, suffix=".tmp",
                                         prefix=f".{Path(record_name).stem}-") as f:
            tmp = f.name
            f.write(record_bytes)        # closing flushes, so a full disk can fail there too
        # os.replace overwrites on Windows too, but two writers cannot both get here: the
        # second one has already failed on its first "xb" file above.
        os.replace(tmp, out / record_name)
    except BaseException:
        if tmp is not None:
            Path(tmp).unlink(missing_ok=True)   # no stray .tmp; the folder stays incomplete
        raise

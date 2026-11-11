"""PrusaSlicer 2.9.7 as a pinned, hash-verified subprocess for F6.portability.

docs/plans/2026-11-11-portability-check.md. The pin file
`profiles/slicers/prusaslicer-2.9.7.yaml` records the release, the SHA-256 hashes of the
zip, the console exe, PrusaSlicer.dll and the whole app folder, and how exit codes are
read. Its values come from research/verification/2026-11-11-prusaslicer-windows/.

PrusaSlicer is AGPL-3.0. This module only runs it as a separate program; no PrusaSlicer
code or profile file is part of this repo.

PrusaSlicer is located only from --prusaslicer-dir or $TDMG_PRUSASLICER_DIR, never by
searching the system, so an unpinned PrusaSlicer is never used by accident. When neither
is given, locate_prusaslicer returns None and F6.portability stays UNKNOWN.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from tdmg.paths import PROFILES_DIR
from tdmg.slicer import (
    AppTree,
    PinnedFile,
    Release,
    SlicerError,
    _Model,
    verify_app,
    verify_tree,
)

PRUSA_PIN_ID = "prusaslicer-2.9.7"
PRUSA_ENV_VAR = "TDMG_PRUSASLICER_DIR"
PRUSA_SETUP_SCRIPT = "scripts/setup_prusaslicer.py"
SETUP_HINT = (f"pass --prusaslicer-dir DIR or set {PRUSA_ENV_VAR}; install it with "
              f"`uv run python {PRUSA_SETUP_SCRIPT} --dest DIR`")


class PrusaDecoding(_Model):
    error_exit: int      # the code every measured error exited with
    status: Literal["measured", "assumed"]
    source: str


class PrusaPin(_Model):
    """The pinned PrusaSlicer. Unlike the OrcaSlicer pin it has no profiles (no vendor
    profile is used) and no exit-code table (errors exit 1, measured)."""
    id: str
    name: str
    version: str
    tag: str
    licence: str
    record: str
    release: Release
    exe: PinnedFile
    libraries: list[PinnedFile] = Field(min_length=1)
    app_tree: AppTree
    decoding: dict[Literal["windows"], PrusaDecoding]

    @model_validator(mode="after")
    def _check(self) -> PrusaPin:
        prefix = self.app_tree.folder + "/"
        if not all(f.path.startswith(prefix) for f in (self.exe, *self.libraries)):
            raise ValueError(f"{self.id}: the exe and libraries must be inside {prefix}")
        return self


def load_prusa_pin(pin_id: str = PRUSA_PIN_ID, profiles_dir: Path = PROFILES_DIR) -> PrusaPin:
    path = profiles_dir / "slicers" / f"{pin_id}.yaml"
    return PrusaPin.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def verify_prusa_install(prusa_dir: str | Path, pin: PrusaPin,
                         full_tree: bool = False) -> dict:
    """Check the exe and PrusaSlicer.dll, and with full_tree every file under app/.

    Returns {exe_sha256, libraries: {path: sha256}}, plus app_tree: {files, sha256} when
    full_tree. Raises SlicerError, naming the setup script.
    """
    found = verify_app(prusa_dir, pin, PRUSA_SETUP_SCRIPT)
    if full_tree:
        found["app_tree"] = verify_tree(prusa_dir, pin, PRUSA_SETUP_SCRIPT)
    return found


@dataclass(frozen=True)
class PrusaSlicer:
    """A verified PrusaSlicer install: the console exe and the hashes checked."""
    root: Path
    exe: Path
    verified: dict
    pin: PrusaPin


def locate_prusaslicer(prusa_dir: str | Path | None, pin: PrusaPin | None = None,
                       full_tree: bool = True) -> PrusaSlicer | None:
    """The install in prusa_dir, else in $TDMG_PRUSASLICER_DIR, verified against the pin.

    None when neither is given: PrusaSlicer is optional, and F6.portability is then
    UNKNOWN. A folder that is given but missing or unverified raises SlicerError, as for
    OrcaSlicer. full_tree (the default) hashes every file of the app folder.
    """
    pin = pin or load_prusa_pin()
    folder = prusa_dir if prusa_dir is not None else os.environ.get(PRUSA_ENV_VAR)
    if not folder:
        return None
    root = Path(folder).resolve()
    if not root.is_dir():
        raise SlicerError(f"PrusaSlicer folder {root} is not a folder; install one with "
                          f"`uv run python {PRUSA_SETUP_SCRIPT} --dest DIR`")
    verified = verify_prusa_install(root, pin, full_tree=full_tree)
    return PrusaSlicer(root, root / pin.exe.path, verified, pin)

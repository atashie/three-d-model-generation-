"""OrcaSlicer as a pinned, hash-verified subprocess (docs/plans/2026-11-10-slicer-check.md).

The pin file `profiles/slicers/orcaslicer-2.5.0.yaml` records the release, the SHA-256
hashes of the zip, the exe, the upstream profile files and the flattened profiles, and the
exit-code table. Its values come from research/verification/2026-11-10-orcaslicer-windows/.

OrcaSlicer is AGPL-3.0. This module only runs it as a separate program; no OrcaSlicer code
or profile file is part of this repo.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from tdmg.paths import PROFILES_DIR

PIN_ID = "orcaslicer-2.5.0"
PROFILE_KINDS = ("machine", "process", "filament")
_CHUNK = 1 << 20

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class SlicerError(ValueError):
    """The slicer cannot be used as asked: missing, changed, or misconfigured."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Release(_Model):
    platform: Literal["windows-x64"]
    asset: str
    url: str
    sha256: Sha256


class Exe(_Model):
    path: str = Field(description="Relative to the slicer folder")
    sha256: Sha256


class FlatProfile(_Model):
    file: str
    preset: str
    chain: list[str] = Field(min_length=1, description="Inheritance chain, root first")
    sha256: Sha256

    @model_validator(mode="after")
    def _leaf_last(self) -> FlatProfile:
        if self.chain[-1] != self.preset:
            raise ValueError(f"{self.file}: the chain must end with the preset {self.preset!r}")
        return self


class Profiles(_Model):
    folder: str = Field(description="Relative to the slicer folder")
    source_base: str
    vendor: str
    drop_keys: list[str]
    flat: dict[Literal["machine", "process", "filament"], FlatProfile]
    upstream_sha256: dict[str, Sha256] = Field(min_length=1)

    @model_validator(mode="after")
    def _all_kinds(self) -> Profiles:
        if set(self.flat) != set(PROFILE_KINDS):
            raise ValueError(f"flat profiles must be exactly {PROFILE_KINDS}")
        return self


class Decoding(_Model):
    rule: Literal["unsigned32", "low8"]
    status: Literal["measured", "assumed"]
    source: str


class SlicerPin(_Model):
    id: str
    name: str
    version: str
    tag: str
    licence: str
    record: str
    release: Release
    exe: Exe
    profiles: Profiles
    decoding: dict[Literal["windows", "posix"], Decoding]
    exit_codes_source: str
    exit_codes: dict[int, str]

    @model_validator(mode="after")
    def _check(self) -> SlicerPin:
        if set(self.decoding) != {"windows", "posix"}:
            raise ValueError(f"{self.id}: decoding needs both 'windows' and 'posix'")
        if self.exit_codes.get(0) != "CLI_SUCCESS":
            raise ValueError(f"{self.id}: exit code 0 must be CLI_SUCCESS")
        return self


def load_pin(pin_id: str = PIN_ID, profiles_dir: Path = PROFILES_DIR) -> SlicerPin:
    path = profiles_dir / "slicers" / f"{pin_id}.yaml"
    return SlicerPin.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _verified(path: Path, expected: str) -> str:
    if not path.is_file():
        raise SlicerError(f"{path} is missing; run scripts/setup_orcaslicer.py")
    actual = sha256_file(path)
    if actual != expected:
        raise SlicerError(f"{path} has sha256 {actual}, which does not match the pin "
                          f"({expected}); reinstall with scripts/setup_orcaslicer.py")
    return actual


def verify_install(slicer_dir: str | Path, pin: SlicerPin) -> dict:
    """Check the exe and the three flattened profiles against the pin. Raises SlicerError.

    Returns the verified hashes: {exe_sha256, profiles: {kind: {name, file, sha256}}}.
    """
    root = Path(slicer_dir)
    exe = _verified(root / pin.exe.path, pin.exe.sha256)
    profiles = {}
    for kind in PROFILE_KINDS:
        p = pin.profiles.flat[kind]
        profiles[kind] = {"name": p.preset, "file": p.file,
                          "sha256": _verified(root / pin.profiles.folder / p.file, p.sha256)}
    return {"exe_sha256": exe, "profiles": profiles}

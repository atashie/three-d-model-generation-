"""Printer and filament profiles: hardware facts the pipeline must respect.

Facts carry their sources. Calibration results are added to the printer profile after
test prints; each one is bound to the conditions it was measured under.
"""

from __future__ import annotations

import math
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from tdmg.paths import PROFILES_DIR


class ProfileSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    access: str = Field(description="How the fact was read, e.g. 'fetched' or 'search snippet'")
    accessed: str
    facts: list[str]


class FeederUnit(BaseModel):
    """One multi-material unit the printer can use. Facts only; files never name a unit."""
    model_config = ConfigDict(extra="forbid")
    name: str
    slots: int | None = Field(default=None, ge=1, description="None if not verified")
    connection: str
    cannot_feed: list[str] = Field(default_factory=list,
                                   description="Materials this unit must not feed; use an external spool")
    spool_width_mm: tuple[float, float] | None = None
    spool_inner_diameter_mm: tuple[float, float] | None = None
    source: str


class MultiMaterial(BaseModel):
    """Multi-material capability, kept independent of which unit is attached.

    Print files name colors (and optionally materials), never AMS units or slots.
    `default_max_filaments` caps a job's palette unless the job raises it.
    """
    model_config = ConfigDict(extra="forbid")
    default_max_filaments: int = Field(ge=1)
    units: list[FeederUnit] = Field(min_length=1)


class PrinterProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    build_volume_mm: tuple[float, float, float]
    nozzle_diameter_mm: float = Field(gt=0)
    nozzle_options_mm: list[float]
    nozzle_material: str
    multi_material: MultiMaterial | None = None
    materials_recommended: list[str]
    materials_not_recommended: list[str] = Field(default_factory=list)
    sources: list[ProfileSource] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    calibration: dict[str, dict] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> PrinterProfile:
        if not all(math.isfinite(v) and v > 0 for v in self.build_volume_mm):
            raise ValueError(f"{self.id}: build volume must be positive and finite")
        if self.nozzle_diameter_mm not in self.nozzle_options_mm:
            raise ValueError(f"{self.id}: nozzle {self.nozzle_diameter_mm} is not in nozzle_options_mm")
        if self.multi_material:
            known = [u.slots for u in self.multi_material.units if u.slots is not None]
            if known and self.multi_material.default_max_filaments > min(known):
                raise ValueError(f"{self.id}: default palette exceeds the smallest unit's slot count")
        return self


def load_printer(profile_id: str, profiles_dir: Path = PROFILES_DIR) -> PrinterProfile:
    path = profiles_dir / "printers" / f"{profile_id}.yaml"
    return PrinterProfile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def printer_ids(profiles_dir: Path = PROFILES_DIR) -> list[str]:
    return sorted(p.stem for p in (profiles_dir / "printers").glob("*.yaml"))

"""Printer and filament profiles: hardware facts the pipeline must respect.

Facts carry their sources. Calibration results are added to the printer profile after
test prints; each one is bound to the conditions it was measured under.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from tdmg.paths import PROFILES_DIR


class ProfileSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    access: str = Field(description="How the fact was read, e.g. 'fetched' or 'search snippet'")
    accessed: str
    facts: list[str]


class MultiMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit: str
    slots: int = Field(ge=1)
    max_filaments: int = Field(ge=1)
    confirmed: bool = Field(description="False until the owner confirms which unit is attached")


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


def load_printer(profile_id: str, profiles_dir: Path = PROFILES_DIR) -> PrinterProfile:
    path = profiles_dir / "printers" / f"{profile_id}.yaml"
    return PrinterProfile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def printer_ids(profiles_dir: Path = PROFILES_DIR) -> list[str]:
    return sorted(p.stem for p in (profiles_dir / "printers").glob("*.yaml"))

"""Rules registry: every design number the pipeline uses, with its evidence.

Each rule records three separate things (docs/PLAN.md section 7):
  kind        what sort of claim it is (format requirement, tool limit, physical rule, our guess)
  provenance  where each piece of evidence comes from
  validation  whether anyone has shown that it works

Every evidence item points at a file in this repo plus an exact `locator` string that
must appear in that file. tests/test_rules.py enforces that the text exists. It cannot
prove the text supports the value: that is a reviewer's job when a rule changes.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from tdmg.paths import REPO_ROOT, RULES_DIR
from tdmg.recipes import ATTRIBUTE_LABELS

Kind = Literal["normative", "tool_limit", "empirical", "hypothesis"]
Provenance = Literal["primary", "secondary", "unverified"]
# measured: software behaviour measured (no print). source-tested: the source printed it.
Validation = Literal["untested", "measured", "source-tested", "peer-reviewed", "calibrated"]
RULE_ID = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
UNITS = {"mm", "mm2", "deg", "px", "x_nozzle", "triangles", "bool", "alpha8", "rgb8_distance",
         "count", "fraction", "ratio", "cielab_chroma",
         "s"}
ATTRIBUTE_KEYS = {"geometry": "G", "articulation": "A", "color": "C", "assembly": "L"}


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str = Field(description="Repo-relative path of the file that records the evidence")
    locator: str = Field(min_length=12, description="Exact text that must appear in `ref`")
    provenance: Provenance
    validation: Validation
    claim: str
    source_url: str | None = None


class Calibration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test: str
    bound_to: list[str]


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Kind
    summary: str
    unit: str
    default: float | int | bool
    range: tuple[float, float] | None = None
    measured_as: str | None = None
    applies_to: dict[str, list[str]] | Literal["all"] = "all"
    conditions: dict[str, float | str] = Field(default_factory=dict)
    scales_with_model: bool | None = None
    evidence: list[Evidence] = Field(min_length=1)
    calibration: Calibration | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Rule:
        if not RULE_ID.match(self.id):
            raise ValueError(f"rule id {self.id!r} must be dotted lower_snake segments")
        if self.unit not in UNITS:
            raise ValueError(f"{self.id}: unknown unit {self.unit!r}; add it to UNITS deliberately")
        if (self.unit == "bool") != isinstance(self.default, bool):
            raise ValueError(f"{self.id}: unit 'bool' and a boolean default go together")
        numbers = [] if isinstance(self.default, bool) else [float(self.default)]
        numbers += list(self.range or ())
        if not all(math.isfinite(x) for x in numbers):
            raise ValueError(f"{self.id}: default and range must be finite numbers")
        if self.applies_to != "all":
            for key, values in self.applies_to.items():
                prefix = ATTRIBUTE_KEYS.get(key)
                bad = [v for v in values if prefix is None or not v.startswith(prefix)
                       or v not in ATTRIBUTE_LABELS]
                if prefix is None or bad:
                    raise ValueError(f"{self.id}: applies_to {key}: {values} is not a known attribute")
        for ev in self.evidence:
            if not ev.locator.strip() or ev.ref.startswith(("/", "..")) or "/../" in ev.ref:
                raise ValueError(f"{self.id}: evidence needs a repo-relative ref and a real locator")
        if any(e.validation == "calibrated" for e in self.evidence) and self.calibration is None:
            raise ValueError(f"{self.id}: 'calibrated' evidence needs a calibration block")
        if self.range is not None:
            lo, hi = self.range
            if lo > hi:
                raise ValueError(f"{self.id}: range {self.range} is reversed")
            numeric = isinstance(self.default, (int, float)) and not isinstance(self.default, bool)
            if numeric and not lo <= self.default <= hi:
                raise ValueError(f"{self.id}: default {self.default} outside range {self.range}")
        if self.kind == "normative" and not any(e.provenance == "primary" for e in self.evidence):
            raise ValueError(f"{self.id}: a normative rule needs at least one primary source")
        if self.calibration is not None and self.kind != "empirical":
            raise ValueError(f"{self.id}: only empirical rules can be calibrated")
        return self

    @property
    def best_provenance(self) -> Provenance:
        order = ["primary", "secondary", "unverified"]
        return min((e.provenance for e in self.evidence), key=order.index)

    @property
    def best_validation(self) -> Validation:
        order = ["calibrated", "peer-reviewed", "source-tested", "measured", "untested"]
        return min((e.validation for e in self.evidence), key=order.index)


def load_rules(rules_dir: Path = RULES_DIR) -> dict[str, Rule]:
    """Load every rules/*.yaml file. Rule ids must be unique across files.

    Raises if no rule files are found: an empty registry would let every check pass silently.
    """
    if not sorted(rules_dir.glob("*.yaml")):
        raise FileNotFoundError(f"no rule files found in {rules_dir}")
    rules: dict[str, Rule] = {}
    for path in sorted(rules_dir.glob("*.yaml")):
        for raw in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            rule = Rule.model_validate(raw)
            if rule.id in rules:
                raise ValueError(f"duplicate rule id {rule.id!r} in {path.name}")
            rules[rule.id] = rule
    return rules


def rule_files(rules_dir: Path = RULES_DIR) -> dict[str, list[Rule]]:
    """Rules grouped by the file they live in, for documentation."""
    out: dict[str, list[Rule]] = {}
    for path in sorted(rules_dir.glob("*.yaml")):
        out[path.stem] = [Rule.model_validate(r) for r in yaml.safe_load(path.read_text()) or []]
    return out


def locator_found(evidence: Evidence, repo_root: Path | None = REPO_ROOT) -> bool:
    """True if the locator text appears in the cited file. Needs a source checkout."""
    if repo_root is None:
        raise RuntimeError("citations can only be checked from a source checkout")
    path = repo_root / evidence.ref
    return path.is_file() and evidence.locator in path.read_text(encoding="utf-8")

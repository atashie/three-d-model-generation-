"""Rules registry: every design number the pipeline uses, with its evidence.

Each rule records three separate things (docs/PLAN.md section 7):
  kind        what sort of claim it is (format requirement, tool limit, physical rule, our guess)
  provenance  where each piece of evidence comes from
  validation  whether anyone has shown that it works

Every evidence item points at a file in this repo plus an exact `locator` string that
must appear in that file. tests/test_rules.py enforces this, so a citation cannot drift.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from tdmg.paths import REPO_ROOT, RULES_DIR

Kind = Literal["normative", "tool_limit", "empirical", "hypothesis"]
Provenance = Literal["primary", "secondary", "unverified"]
Validation = Literal["untested", "source-tested", "peer-reviewed", "calibrated"]
RULE_ID = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str = Field(description="Repo-relative path of the file that records the evidence")
    locator: str = Field(description="Exact text that must appear in `ref`")
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
        order = ["calibrated", "peer-reviewed", "source-tested", "untested"]
        return min((e.validation for e in self.evidence), key=order.index)


def load_rules(rules_dir: Path = RULES_DIR) -> dict[str, Rule]:
    """Load every rules/*.yaml file. Rule ids must be unique across files."""
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


def locator_found(evidence: Evidence, repo_root: Path = REPO_ROOT) -> bool:
    path = repo_root / evidence.ref
    return path.is_file() and evidence.locator in path.read_text(encoding="utf-8")

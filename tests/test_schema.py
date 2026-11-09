"""The rule and profile schemas reject values that would make checks meaningless."""

import math

import pytest
from pydantic import ValidationError

from tdmg.profiles import PrinterProfile, load_printer
from tdmg.rules import Rule, load_rules

EV = {"ref": "README.md", "locator": "Turn an image into a file", "provenance": "primary",
      "validation": "untested", "claim": "x"}
BASE = {"id": "fdm.test.value", "kind": "empirical", "summary": "s", "unit": "mm", "default": 1.0,
        "evidence": [EV]}


def make(**overrides):
    return Rule.model_validate({**BASE, **overrides})


def test_base_rule_is_valid():
    make()


@pytest.mark.parametrize("overrides", [
    {"default": math.nan},
    {"default": math.inf},
    {"default": True},                                   # boolean with unit mm
    {"unit": "furlongs"},
    {"applies_to": {"geometry": ["G99"]}},
    {"applies_to": {"colour": ["C1"]}},
    {"default": 5.0, "range": [1.0, 2.0]},
    {"range": [2.0, 1.0]},
    {"evidence": []},
    {"evidence": [{**EV, "locator": "   "}]},
    {"evidence": [{**EV, "locator": "short"}]},
    {"evidence": [{**EV, "ref": "/etc/passwd"}]},
    {"evidence": [{**EV, "ref": "../outside.md"}]},
    {"evidence": [{**EV, "validation": "calibrated"}]},  # calibrated without a calibration block
    {"kind": "normative", "unit": "bool", "default": True,
     "evidence": [{**EV, "provenance": "secondary"}]},   # normative needs a primary source
    {"id": "Bad ID"},
])
def test_bad_rules_are_rejected(overrides):
    with pytest.raises(ValidationError):
        make(**overrides)


def test_empty_rules_dir_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_rules(tmp_path)


@pytest.mark.parametrize("change", [
    {"build_volume_mm": (-1, 256, 256)},
    {"build_volume_mm": (256, 256, math.inf)},
    {"nozzle_diameter_mm": 0.5},                         # not in nozzle_options_mm
])
def test_bad_printer_profiles_are_rejected(change):
    data = load_printer("bambu-a1").model_dump()
    with pytest.raises(ValidationError):
        PrinterProfile.model_validate({**data, **change})


def test_a1_ams_lite_restrictions_are_recorded():
    mm = load_printer("bambu-a1").multi_material
    assert {"TPU", "PVA"} <= set(mm.cannot_feed)

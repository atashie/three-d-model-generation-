"""The rules registry must load, and every citation must point at text that really exists."""

import pytest

from tdmg.paths import REPO_ROOT
from tdmg.rules import load_rules, locator_found

RULES = load_rules()


def test_registry_loads_and_is_not_empty():
    assert len(RULES) >= 15


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_every_evidence_locator_exists_in_its_file(rule_id):
    for ev in RULES[rule_id].evidence:
        assert (REPO_ROOT / ev.ref).is_file(), f"{rule_id}: missing file {ev.ref}"
        assert locator_found(ev), f"{rule_id}: locator not found in {ev.ref}: {ev.locator!r}"


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_hypotheses_are_not_presented_as_validated(rule_id):
    r = RULES[rule_id]
    if r.kind == "hypothesis":
        assert all(e.validation == "untested" for e in r.evidence), rule_id


def test_selection_rules_exist_with_their_units_and_defaults():
    # Defaults pinned so a silent change is caught; the evidence README backs these values.
    alpha = RULES["perception.alpha.min_opaque"]
    tol = RULES["perception.flood.color_tolerance"]
    assert (alpha.unit, alpha.default, alpha.range) == ("alpha8", 128, (1, 255))
    assert (tol.unit, tol.default, tol.range) == ("rgb8_distance", 30, (0, 441.7))


def test_clearance_rules_never_scale_with_the_model():
    for r in RULES.values():
        if ".clearance" in r.id or r.id.startswith("joint."):
            assert r.scales_with_model is False, r.id


def test_smoothing_rule_exists_with_its_unit_and_default():
    rule = RULES["flat.smooth.sigma_px"]
    assert (rule.unit, rule.default, rule.kind) == ("px", 2.5, "hypothesis")


def test_slicer_timeout_rule_exists_with_its_unit_and_default():
    rule = RULES["slicer.orca.timeout_s"]
    assert (rule.unit, rule.default, rule.kind) == ("s", 300, "hypothesis")
    assert rule.best_validation == "untested"

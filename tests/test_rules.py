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


def test_prusaslicer_timeout_rule_exists_with_its_unit_and_default():
    rule = RULES["slicer.prusa.timeout_s"]
    assert (rule.unit, rule.default, rule.kind) == ("s", 300, "hypothesis")
    assert rule.best_validation == "untested"
    assert [e.ref for e in rule.evidence] == [
        "research/verification/2026-11-11-prusaslicer-windows/README.md"]


def test_furry_edge_rule_exists_with_its_unit_and_default():
    rule = RULES["color.edges.furry_sigma_px"]
    assert (rule.unit, rule.default, rule.kind) == ("px", 1.0, "hypothesis")
    assert rule.best_validation == "untested"
    assert rule.best_provenance == "unverified"


# The extraction, outline and shade rules (color-palette plan Task 7b), from the Task 7a
# measurements on two owner images: each a hypothesis, untested.
@pytest.mark.parametrize("rule_id, unit, default, provenance", [
    ("color.extract.default_count", "count", 6, "primary"),
    ("color.outline.thin_share", "fraction", 0.38, "primary"),
    ("color.shade.max_hue_diff_deg", "deg", 5.5, "primary"),
    ("color.shade.min_chroma", "cielab_chroma", 8.5, "primary"),
    ("color.outline.keep_width", "mm", 0.5, "primary"),
    ("color.outline.keep_area_width_ratio", "ratio", 2.0, "primary"),
])
def test_extraction_outline_and_shade_rules(rule_id, unit, default, provenance):
    rule = RULES[rule_id]
    assert (rule.unit, rule.default, rule.kind) == (unit, default, "hypothesis")
    assert rule.best_validation == "untested"
    assert rule.best_provenance == provenance
    assert all(e.ref.startswith(("research/verification/2026-11-11-color-palette/",
                                 "docs/plans/2026-11-11-color-palette.md"))
               for e in rule.evidence)


def test_extract_default_is_an_integer_count():
    assert type(RULES["color.extract.default_count"].default) is int


def test_kept_outline_is_wider_than_the_cleanup_opening():
    # Cleanup removes strips at or below the opening width (plan Task 4), so a kept outline
    # band at or below it would be removed again.
    keep, opening = RULES["color.outline.keep_width"], RULES["flat.sliver.opening_width"]
    assert keep.unit == opening.unit == "mm"
    assert keep.default > opening.default
    assert keep.scales_with_model is False

"""tdmg.color_config: the color settings, their precedence and their refusals (plan Decision 6),
and the edge presets (Decision 5)."""

import copy
import hashlib

import pytest
import yaml

from tdmg.color_config import (
    KEYS,
    MIN_COLORS,
    ColorConfig,
    ColorConfigError,
    ResolvedColorConfig,
    check_base,
    check_extraction_indices,
    edge_sigma_px,
    merge_problem,
    palette_cap,
    resolve_color_config,
)
from tdmg.paths import PROFILES_DIR
from tdmg.profiles import PrinterProfile, load_printer
from tdmg.rules import load_rules

RULES = load_rules()
A1 = load_printer("bambu-a1")
NO_FLAGS = {"colors": None, "edges": None, "base": None}
# The Task 7b and 7e-b keys at their defaults (settings as resolved, as recorded, and their
# sources).
NEW = {"extract": 6, "outlines": "drop", "outline_color": "auto", "merge": (),
       "outline_width_mm": 0.5}
NEW_PLAIN = {**NEW, "merge": []}
NEW_SOURCES = {"extract": "rule", "outlines": "default", "outline_color": "default",
               "merge": "default", "outline_width_mm": "rule"}


def _resolve(flags=None, path=None, printer=A1):
    return resolve_color_config({**NO_FLAGS, **(flags or {})}, path, RULES, printer)


def _config(tmp_path, text, name="color.yaml"):
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))    # bytes: write_text would add CR on Windows
    return path


def _printer_with_slots(slots: int) -> PrinterProfile:
    raw = yaml.safe_load((PROFILES_DIR / "printers" / "bambu-a1.yaml").read_text(encoding="utf-8"))
    raw = copy.deepcopy(raw)
    mm = raw["multi_material"]
    mm["default_max_filaments"] = slots
    next(u for u in mm["units"] if u["name"] == mm["default_basis"])["slots"] = slots
    return PrinterProfile.model_validate(raw)


# ---- defaults and the cap ------------------------------------------------------------------

def test_defaults_without_flags_or_file():
    r = _resolve()
    assert r.settings == {**NEW, "colors": 4, "edges": "smooth", "base": "auto"}
    assert r.sources == {**NEW_SOURCES, "colors": "profile", "edges": "default", "base": "default"}
    assert r.config_sha256 is None


def test_cap_is_read_from_the_profile_not_hard_coded():
    assert palette_cap(A1) == A1.multi_material.default_max_filaments == 4
    three = _printer_with_slots(3)
    assert palette_cap(three) == 3
    assert _resolve(printer=three).settings["colors"] == 3
    with pytest.raises(ColorConfigError, match="colors"):
        _resolve({"colors": 4}, printer=three)
    six = _printer_with_slots(6)
    assert _resolve({"colors": 6}, printer=six).settings["colors"] == 6


def test_a_printer_without_multi_material_is_refused():
    raw = A1.model_dump()
    raw["multi_material"] = None
    with pytest.raises(ColorConfigError, match="multi-material"):
        _resolve(printer=PrinterProfile.model_validate(raw))


def test_minimum_is_two():
    assert MIN_COLORS == 2
    assert _resolve({"colors": 2}).settings["colors"] == 2


# ---- precedence and the record fields ------------------------------------------------------

def test_file_overrides_defaults_and_its_hash_is_recorded(tmp_path):
    text = "colors: 3\nedges: furry\n"
    path = _config(tmp_path, text)
    r = _resolve(path=path)
    assert r.settings == {**NEW, "colors": 3, "edges": "furry", "base": "auto"}
    assert r.sources == {**NEW_SOURCES, "colors": "config", "edges": "config", "base": "default"}
    assert r.config_sha256 == hashlib.sha256(text.encode()).hexdigest()


def test_flags_override_the_file(tmp_path):
    path = _config(tmp_path, "colors: 3\nedges: furry\nbase: 1\n")
    r = _resolve({"colors": 2, "base": "auto"}, path)
    assert r.settings == {**NEW, "colors": 2, "edges": "furry", "base": "auto"}
    assert r.sources == {**NEW_SOURCES, "colors": "flag", "edges": "config", "base": "flag"}
    assert r.config_sha256 is not None


def test_flags_override_defaults():
    r = _resolve({"edges": "exact", "base": 0})
    assert r.settings == {**NEW, "colors": 4, "edges": "exact", "base": 0}
    assert r.sources == {**NEW_SOURCES, "colors": "profile", "edges": "flag", "base": "flag"}


def test_empty_file_means_no_settings_but_is_still_hashed(tmp_path):
    path = _config(tmp_path, "# nothing set\n")
    r = _resolve(path=path)
    assert r.settings == {**NEW, "colors": 4, "edges": "smooth", "base": "auto"}
    assert r.sources == {**NEW_SOURCES, "colors": "profile", "edges": "default", "base": "default"}
    assert r.config_sha256 == hashlib.sha256(b"# nothing set\n").hexdigest()


# ---- refusals ------------------------------------------------------------------------------

@pytest.mark.parametrize("text, key", [
    ("colours: 3\n", "colours"),
    ("min_glue_piece: auto\n", "min_glue_piece"),   # a later step's key, not yet accepted
    ("face: up\n", "face"),                         # a later step's key, not yet accepted
    ("colors: 1\n", "colors"),
    ("colors: 5\n", "colors"),
    ("colors: true\n", "colors"),
    ("colors: 3.0\n", "colors"),
    ("colors: '3'\n", "colors"),
    ("edges: hairy\n", "edges"),
    ("edges: 1\n", "edges"),
    ("base: -1\n", "base"),
    ("base: largest\n", "base"),
    ("base: true\n", "base"),
])
def test_bad_file_values_are_refused_naming_the_key(tmp_path, text, key):
    with pytest.raises(ColorConfigError, match=key):
        _resolve(path=_config(tmp_path, text))


@pytest.mark.parametrize("flags, key", [
    ({"colors": 1}, "colors"), ({"colors": 5}, "colors"), ({"colors": True}, "colors"),
    ({"colors": 3.0}, "colors"), ({"colors": "3"}, "colors"),
    ({"edges": "hairy"}, "edges"), ({"base": -1}, "base"),
])
def test_bad_flag_values_are_refused_naming_the_key(flags, key):
    with pytest.raises(ColorConfigError, match=key):
        _resolve(flags)


def test_a_bad_file_value_is_refused_even_when_a_flag_overrides_it(tmp_path):
    with pytest.raises(ColorConfigError, match="colors"):
        _resolve({"colors": 3}, _config(tmp_path, "colors: 9\n"))


def test_unknown_flag_names_are_refused():
    with pytest.raises(ColorConfigError, match="face"):
        resolve_color_config({**NO_FLAGS, "face": "up"}, None, RULES, A1)


@pytest.mark.parametrize("text", ["- colors\n- 3\n", "4\n", "smooth\n", "[1, 2]\n"])
def test_non_mapping_yaml_is_refused(tmp_path, text):
    with pytest.raises(ColorConfigError, match="mapping"):
        _resolve(path=_config(tmp_path, text))


def test_duplicate_keys_are_refused(tmp_path):
    with pytest.raises(ColorConfigError, match="colors"):
        _resolve(path=_config(tmp_path, "colors: 2\ncolors: 4\n"))


def test_invalid_yaml_is_refused(tmp_path):
    with pytest.raises(ColorConfigError, match="YAML"):
        _resolve(path=_config(tmp_path, "colors: [2\n"))


def test_non_utf8_file_is_refused(tmp_path):
    path = tmp_path / "color.yaml"
    path.write_bytes(b"edges: \xff\n")
    with pytest.raises(ColorConfigError, match="UTF-8"):
        _resolve(path=path)


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(ColorConfigError, match="cannot read"):
        _resolve(path=tmp_path / "absent.yaml")


def test_a_directory_is_refused(tmp_path):
    with pytest.raises(ColorConfigError, match="cannot read"):
        _resolve(path=tmp_path)


# ---- base against the palette --------------------------------------------------------------

def test_base_auto_is_always_valid():
    check_base("auto", 2)


@pytest.mark.parametrize("base", [0, 1, 2])
def test_base_in_range_is_valid(base):
    check_base(base, 3)


@pytest.mark.parametrize("base", [3, 7])
def test_base_out_of_range_is_refused(base):
    with pytest.raises(ColorConfigError, match="base"):
        check_base(base, 3)


# ---- edge presets --------------------------------------------------------------------------

def test_smooth_is_the_outline_smoothing_rule():
    sigma, rule = edge_sigma_px("smooth", RULES)
    assert rule == "flat.smooth.sigma_px"
    assert sigma == RULES["flat.smooth.sigma_px"].default == 2.5


def test_furry_is_its_own_rule():
    sigma, rule = edge_sigma_px("furry", RULES)
    assert rule == "color.edges.furry_sigma_px"
    assert sigma == RULES["color.edges.furry_sigma_px"].default == 1.0


def test_exact_is_no_blur_and_needs_no_rule():
    assert edge_sigma_px("exact", RULES) == (0.0, None)


def test_unknown_preset_is_refused():
    with pytest.raises(ColorConfigError, match="edges"):
        edge_sigma_px("hairy", RULES)


def test_a_complex_key_is_refused(tmp_path):
    with pytest.raises(ColorConfigError, match="plain name"):
        _resolve(path=_config(tmp_path, "? [a]\n: 1\n"))


def test_a_merge_key_is_refused_with_a_clear_message(tmp_path):
    with pytest.raises(ColorConfigError, match="merge keys"):
        _resolve(path=_config(tmp_path, "<<: {colors: 3}\nedges: smooth\n"))


@pytest.mark.parametrize("text, key", [
    ("colors: ~\n", "colors"), ("edges: null\n", "edges"), ("base: null\n", "base"),
    ("colors:\n", "colors"),
])
def test_an_explicit_null_in_the_file_is_refused(tmp_path, text, key):
    with pytest.raises(ColorConfigError, match=f"{key}.*null"):
        _resolve(path=_config(tmp_path, text))


def test_none_in_the_flags_still_means_not_given():
    assert _resolve({"colors": None, "edges": None, "base": None}).sources["colors"] == "profile"


def test_a_utf8_bom_is_accepted_and_hashed_as_written(tmp_path):
    path = tmp_path / "color.yaml"
    data = b"\xef\xbb\xbfcolors: 3\n"
    path.write_bytes(data)
    r = _resolve(path=path)
    assert r.settings["colors"] == 3 and r.sources["colors"] == "config"
    assert r.config_sha256 == hashlib.sha256(data).hexdigest()


# ---- review additions ----------------------------------------------------------------------

def test_base_from_the_file_is_recorded_as_config(tmp_path):
    r = _resolve(path=_config(tmp_path, "base: 2\n"))
    assert (r.settings["base"], r.sources["base"]) == (2, "config")


@pytest.mark.parametrize("flags, path_text", [
    ({"base": 4}, None), ({"colors": 2, "base": 2}, None), (None, "colors: 3\nbase: 3\n"),
    ({"colors": 2}, "base: 3\n"),
])
def test_base_at_or_above_colors_is_refused_when_resolving(tmp_path, flags, path_text):
    path = _config(tmp_path, path_text) if path_text else None
    with pytest.raises(ColorConfigError, match="base .* is not a color index"):
        _resolve(flags, path)


def test_colors_1_from_flags_gives_the_range_message():
    with pytest.raises(ColorConfigError, match="colors: must be between 2 and 4"):
        _resolve({"colors": 1})


def test_a_profile_cap_below_the_minimum_is_refused():
    with pytest.raises(ColorConfigError, match="at least 2"):
        palette_cap(_printer_with_slots(1))


def test_a_quoted_merge_key_is_an_ordinary_unknown_key(tmp_path):
    with pytest.raises(ColorConfigError, match="unknown key '<<'"):
        _resolve(path=_config(tmp_path, "'<<': 3\n"))


def test_anchors_and_aliases_are_accepted(tmp_path):
    assert _resolve(path=_config(tmp_path, "colors: &n 3\n")).settings["colors"] == 3
    # The alias resolves to 3, which is then refused as a base for a 3-color palette.
    with pytest.raises(ColorConfigError, match="base 3"):
        _resolve(path=_config(tmp_path, "colors: &n 3\nbase: *n\n"))


def test_resolved_config_is_immutable_and_gives_plain_dicts_for_the_record(tmp_path):
    r = _resolve(path=_config(tmp_path, "edges: furry\n"))
    with pytest.raises(TypeError):
        r.settings["colors"] = 2
    with pytest.raises(TypeError):
        r.sources["colors"] = "flag"
    rec = r.as_record()
    assert rec == {"settings": {**NEW_PLAIN, "colors": 4, "edges": "furry", "base": "auto"},
                   "sources": {**NEW_SOURCES, "colors": "profile", "edges": "config",
                               "base": "default"},
                   "config_sha256": r.config_sha256}
    assert type(rec["settings"]) is dict and type(rec["sources"]) is dict
    rec["settings"]["colors"] = 2           # a copy: the resolved config is unchanged
    assert r.settings["colors"] == 4


def test_resolved_config_copies_its_inputs():
    settings = {"colors": 3, "edges": "smooth", "base": "auto"}
    r = ResolvedColorConfig(settings=settings, sources={k: "flag" for k in KEYS},
                            config_sha256=None)
    settings["colors"] = 2
    assert r.settings["colors"] == 3


def test_keys_come_from_the_model():
    assert KEYS == tuple(ColorConfig.model_fields) == (
        "colors", "extract", "edges", "base", "outlines", "outline_color", "merge",
        "outline_width_mm")


def test_a_missing_rule_is_a_clear_error():
    rules = {k: v for k, v in RULES.items() if k != "color.edges.furry_sigma_px"}
    with pytest.raises(ColorConfigError, match="color.edges.furry_sigma_px"):
        edge_sigma_px("furry", rules)


# ---- Task 7b: extract, outlines, outline_color, merge --------------------------------------

def test_extract_defaults_to_its_rule():
    r = _resolve()
    assert r.settings["extract"] == RULES["color.extract.default_count"].default == 6
    assert r.sources["extract"] == "rule"


def test_extract_default_follows_the_rule_value():
    rules = copy.deepcopy(RULES)
    rid = "color.extract.default_count"
    rules[rid] = rules[rid].model_copy(update={"default": 5})
    assert resolve_color_config(NO_FLAGS, None, rules, A1).settings["extract"] == 5


def test_a_missing_extract_rule_is_a_clear_error():
    rules = {k: v for k, v in RULES.items() if k != "color.extract.default_count"}
    with pytest.raises(ColorConfigError, match="color.extract.default_count"):
        resolve_color_config(NO_FLAGS, None, rules, A1)
    # Given explicitly, the rule is not needed.
    assert resolve_color_config({"extract": 4}, None, rules, A1).settings["extract"] == 4


def test_a_bad_extract_rule_value_is_refused():
    rules = copy.deepcopy(RULES)
    rid = "color.extract.default_count"
    rules[rid] = rules[rid].model_copy(update={"default": 6.0})
    with pytest.raises(ColorConfigError, match="rule color.extract.default_count: extract"):
        resolve_color_config(NO_FLAGS, None, rules, A1)


def test_new_keys_precedence_flag_over_file_over_default(tmp_path):
    path = _config(tmp_path, "extract: 7\noutlines: keep\noutline_color: none\n"
                             "merge: [[5, 1], [6, 1]]\noutline_width_mm: 0.5\n")
    r = _resolve(path=path)
    assert (r.settings["extract"], r.settings["outlines"], r.settings["outline_color"],
            r.settings["merge"], r.settings["outline_width_mm"]) == (
        7, "keep", "none", ((5, 1), (6, 1)), 0.5)
    assert {k: r.sources[k] for k in NEW} == {k: "config" for k in NEW}
    r = _resolve({"extract": 8, "outlines": "drop"}, path)
    assert (r.settings["extract"], r.settings["outlines"]) == (8, "drop")
    assert (r.sources["extract"], r.sources["outlines"], r.sources["merge"]) == (
        "flag", "flag", "config")


def test_new_keys_are_recorded_as_plain_lists(tmp_path):
    r = _resolve(path=_config(tmp_path, "outline_color: [4, 2]\nmerge: [[3, 0]]\n"))
    assert r.settings["outline_color"] == (4, 2)            # order kept, frozen
    rec = r.as_record()["settings"]
    assert rec["outline_color"] == [4, 2] and rec["merge"] == [[3, 0]]
    assert type(rec["merge"][0]) is list
    rec["merge"][0][0] = 9                                  # a copy
    assert r.settings["merge"] == ((3, 0),)


PAIRS = r"merge must be a list of \[from, into\] pairs"
NON_EMPTY = "outline_color must be auto, none or a non-empty list"


@pytest.mark.parametrize("text, message", [
    ("extract: 1\n", "extract: must be between 2 and 254"),
    ("extract: 255\n", "extract: must be between 2 and 254"),
    ("extract: true\n", "extract"),
    ("extract: 6.0\n", "extract"),
    ("extract: '6'\n", "extract"),
    ("outlines: none\n", "outlines"),
    ("outlines: true\n", "outlines"),
    ("outline_color: 3\n", NON_EMPTY),
    ("outline_color: []\n", NON_EMPTY),
    ("outline_color: [-1]\n", NON_EMPTY),
    ("outline_color: [true]\n", NON_EMPTY),
    ("outline_color: [1.0]\n", NON_EMPTY),
    ("outline_color: [2, 2]\n", "outline_color: lists an index more than once"),
    ("outline_color: black\n", NON_EMPTY),
    ("merge: 3\n", PAIRS),
    ("merge: [3, 1]\n", PAIRS),
    ("merge: [[3]]\n", PAIRS),
    ("merge: [[3, 1, 0]]\n", PAIRS),
    ("merge: [[3, -1]]\n", PAIRS),
    ("merge: [[3, true]]\n", PAIRS),
    ("merge: [[3, 3]]\n", "merges a color into itself"),
    ("merge: [[3, 1], [3, 2]]\n", "color 3 is merged more than once"),
    ("merge: [[3, 1], [1, 0]]\n", "no chains"),
    ("merge: {3: 1}\n", PAIRS),
])
def test_bad_new_key_values_are_refused(tmp_path, text, message):
    with pytest.raises(ColorConfigError, match=message):
        _resolve(path=_config(tmp_path, text))


@pytest.mark.parametrize("flags, message", [
    ({"extract": 1}, "extract"), ({"extract": True}, "extract"),
    ({"outlines": "maybe"}, "outlines"),
])
def test_bad_new_flags_are_refused(flags, message):
    with pytest.raises(ColorConfigError, match=message):
        _resolve(flags)


@pytest.mark.parametrize("flags, text", [
    ({"extract": 3}, None),                   # colors defaults to the cap, 4
    ({"extract": 2, "colors": 3}, None),
    (None, "extract: 3\n"),
    ({"extract": 3}, "colors: 4\n"),
])
def test_extract_below_colors_is_refused(tmp_path, flags, text):
    path = _config(tmp_path, text) if text else None
    with pytest.raises(ColorConfigError, match=r"extract \d is below colors \d"):
        _resolve(flags, path)


def test_extract_equal_to_colors_is_accepted():
    assert _resolve({"extract": 4}).settings["extract"] == 4
    assert _resolve({"extract": 3, "colors": 3}).settings["colors"] == 3


@pytest.mark.parametrize("text, message", [
    ("outline_color: [6]\n", "outline_color 6 is not an extraction index"),
    ("merge: [[6, 0]]\n", r"merge \[6, 0\]: 6 is not an extraction index"),
    ("merge: [[0, 9]]\n", r"merge \[0, 9\]: 9 is not an extraction index"),
    ("outline_color: [4]\nmerge: [[4, 0]]\n", "color 4 is in the outline family"),
])
def test_indices_are_checked_against_extract_when_resolving(tmp_path, text, message):
    with pytest.raises(ColorConfigError, match=message):
        _resolve(path=_config(tmp_path, text))          # extract 6: indices 0..5


def test_check_extraction_indices_after_quantize():
    # The image gave 4 colors although extract was 6.
    check_extraction_indices("auto", [[3, 0]], 4)
    with pytest.raises(ColorConfigError, match="the extraction has 4 colors"):
        check_extraction_indices("auto", [[4, 0]], 4)
    with pytest.raises(ColorConfigError, match="outline_color 5"):
        check_extraction_indices([5], [], 4)
    # A family found by detection (auto) is protected the same way.
    with pytest.raises(ColorConfigError, match="color 2 is in the outline family"):
        check_extraction_indices("auto", [[2, 0]], 4, family=(2,))
    check_extraction_indices("none", [[1, 0]], 4)
    with pytest.raises(ColorConfigError, match="no chains"):
        check_extraction_indices("auto", [(1, 0), (2, 1)], 4)


def test_merge_into_the_outline_core_is_allowed_from_a_member_refused(tmp_path):
    # Decided 2026-11-11 (plan Task 7c): into may be the kept core; from never a member.
    # When resolving, the core is not known yet, so an into in the list is not refused.
    r = _resolve(path=_config(tmp_path, "outline_color: [4]\nmerge: [[1, 4]]\n"))
    assert r.settings["merge"] == ((1, 4),)
    check_extraction_indices([4], [[1, 4]], 6, family=(4,), core=4)
    check_extraction_indices("auto", [[1, 3]], 6, family=(3, 4), core=3)
    with pytest.raises(ColorConfigError, match=r"merge \[1, 4\]: color 4 is in the outline "
                                               r"family but is not its core \(3\)"):
        check_extraction_indices("auto", [[1, 4]], 6, family=(3, 4), core=3)
    with pytest.raises(ColorConfigError, match="color 3 is in the outline family, which"):
        check_extraction_indices("auto", [[3, 1]], 6, family=(3, 4), core=3)
    with pytest.raises(ColorConfigError, match="color 4 is in the outline family, which"):
        check_extraction_indices([4], [[4, 1]], 6)


def test_merge_problem_is_none_for_good_pairs():
    assert merge_problem([]) is None
    assert merge_problem([(3, 0), (4, 0), (5, 1)]) is None   # two into one is fine


def test_outline_color_and_merge_are_accepted_from_any_source():
    # The CLI has no flags for them (config file only), but the resolver takes any source.
    r = _resolve({"outline_color": "none", "merge": [[5, 0]]})
    assert r.sources["outline_color"] == "flag" and r.settings["merge"] == ((5, 0),)


def test_extract_default_is_at_least_colors():
    # extract defaults to max(rule default, colors): a printer with more slots than the
    # rule's 6 still resolves by default, and the source stays "rule".
    eight = _printer_with_slots(8)
    r = _resolve(printer=eight)
    assert (r.settings["colors"], r.settings["extract"], r.sources["extract"]) == (8, 8, "rule")
    r = _resolve({"colors": 7}, printer=eight)
    assert r.settings["extract"] == 7
    assert _resolve({"colors": 3}, printer=eight).settings["extract"] == 6
    with pytest.raises(ColorConfigError, match="extract 6 is below colors 8"):
        _resolve({"extract": 6}, printer=eight)        # given explicitly: never raised


# ---- Task 7e-b: outline_width_mm -----------------------------------------------------------

def test_outline_width_defaults_to_the_keep_width_rule():
    r = _resolve()
    assert r.settings["outline_width_mm"] == RULES["color.outline.keep_width"].default == 0.5
    assert r.sources["outline_width_mm"] == "rule"
    rules = copy.deepcopy(RULES)
    rid = "color.outline.keep_width"
    rules[rid] = rules[rid].model_copy(update={"default": 0.7})
    assert resolve_color_config(NO_FLAGS, None, rules, A1).settings["outline_width_mm"] == 0.7


@pytest.mark.parametrize("text, value", [("1", 1.0), ("0.5", 0.5), ("0.41", 0.41)])
def test_outline_width_from_the_file_is_a_float(tmp_path, text, value):
    r = _resolve(path=_config(tmp_path, f"outline_width_mm: {text}\n"))
    assert r.settings["outline_width_mm"] == value
    assert type(r.settings["outline_width_mm"]) is float
    assert r.sources["outline_width_mm"] == "config"


@pytest.mark.parametrize("text, message", [
    ("0.4", (r"outline_width_mm \(0.4 mm\) must be wider than flat.sliver.opening_width "
             r"\(0.4 mm\): cleanup removes strips at or below that width")),
    ("0.3", "must be wider than flat.sliver.opening_width"),
    ("0", "outline_width_mm must be a finite number of mm above 0"),
    ("-1", "outline_width_mm must be a finite number of mm above 0"),
    (".inf", "outline_width_mm must be a finite number of mm above 0"),
    (".nan", "outline_width_mm must be a finite number of mm above 0"),
    ("true", "outline_width_mm must be a finite number of mm above 0"),
    ("'0.5'", "outline_width_mm must be a finite number of mm above 0"),
    ("[0.5]", "outline_width_mm must be a finite number of mm above 0"),
])
def test_a_bad_outline_width_is_refused_with_an_explanation(tmp_path, text, message):
    with pytest.raises(ColorConfigError, match=message):
        _resolve(path=_config(tmp_path, f"outline_width_mm: {text}\n"))


def test_an_outline_width_rule_at_the_opening_or_in_another_unit_is_refused():
    rid = "color.outline.keep_width"
    rules = copy.deepcopy(RULES)
    rules[rid] = rules[rid].model_copy(update={"default": 0.4})
    with pytest.raises(ColorConfigError, match="must be wider than"):
        resolve_color_config(NO_FLAGS, None, rules, A1)
    rules[rid] = rules[rid].model_copy(update={"default": 0.45, "unit": "px"})
    with pytest.raises(ColorConfigError, match="must be in 'mm'"):
        resolve_color_config(NO_FLAGS, None, rules, A1)
    # Given explicitly, the rule is not needed.
    rules = {k: v for k, v in RULES.items() if k != rid}
    r = resolve_color_config({"outline_width_mm": 0.5}, None, rules, A1)
    assert r.settings["outline_width_mm"] == 0.5


@pytest.mark.parametrize("text", ["null\n", "~\n", "--- null\n", "# a comment\nnull\n"])
def test_a_file_that_is_an_explicit_null_is_refused(tmp_path, text):
    # Only an empty or comment-only file means "no settings" (Codex review, Task 8).
    with pytest.raises(ColorConfigError, match="must be a mapping.*not null"):
        _resolve(path=_config(tmp_path, text))


def test_a_comment_only_file_still_means_no_settings(tmp_path):
    assert _resolve(path=_config(tmp_path, "# nothing set\n")).sources["edges"] == "default"

"""tdmg.color_config: the color settings, their precedence and their refusals (plan Decision 6),
and the edge presets (Decision 5)."""

import copy
import hashlib

import pytest
import yaml

from tdmg.color_config import (
    MIN_COLORS,
    ColorConfigError,
    check_base,
    edge_sigma_px,
    palette_cap,
    resolve_color_config,
)
from tdmg.paths import PROFILES_DIR
from tdmg.profiles import PrinterProfile, load_printer
from tdmg.rules import load_rules

RULES = load_rules()
A1 = load_printer("bambu-a1")
NO_FLAGS = {"colors": None, "edges": None, "base": None}


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
    assert r.settings == {"colors": 4, "edges": "smooth", "base": "auto"}
    assert r.sources == {"colors": "profile", "edges": "default", "base": "default"}
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
    assert r.settings == {"colors": 3, "edges": "furry", "base": "auto"}
    assert r.sources == {"colors": "config", "edges": "config", "base": "default"}
    assert r.config_sha256 == hashlib.sha256(text.encode()).hexdigest()


def test_flags_override_the_file(tmp_path):
    path = _config(tmp_path, "colors: 3\nedges: furry\nbase: 1\n")
    r = _resolve({"colors": 2, "base": "auto"}, path)
    assert r.settings == {"colors": 2, "edges": "furry", "base": "auto"}
    assert r.sources == {"colors": "flag", "edges": "config", "base": "flag"}
    assert r.config_sha256 is not None


def test_flags_override_defaults():
    r = _resolve({"edges": "exact", "base": 0})
    assert r.settings == {"colors": 4, "edges": "exact", "base": 0}
    assert r.sources == {"colors": "profile", "edges": "flag", "base": "flag"}


def test_empty_file_means_no_settings_but_is_still_hashed(tmp_path):
    path = _config(tmp_path, "# nothing set\n")
    r = _resolve(path=path)
    assert r.settings == {"colors": 4, "edges": "smooth", "base": "auto"}
    assert r.sources == {"colors": "profile", "edges": "default", "base": "default"}
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
    with pytest.raises(ColorConfigError, match="key"):
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

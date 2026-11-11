"""Color settings for `tdmg colors` (docs/plans/2026-11-11-color-palette.md, Decisions 5 and 6,
and Task 7b).

Settings come from three places, in this order of precedence: command-line flags, then the
config file, then the defaults. Each source is validated in full, so a bad value in the file
is refused even when a flag overrides it. The resolved settings, the source of each one and
the config file's SHA-256 are returned for the record.

The config file is YAML, read with a yaml.SafeLoader subclass (safe types only). It must
be a mapping of known keys to valid values; anything else is refused with a message naming
the key. The loader also refuses duplicate keys (yaml.safe_load would silently keep the
last one), non-scalar keys and merge keys (<<); null values are refused after loading.
An empty file (or one holding only comments) means "no settings": every key takes its
default, and the file's hash is still recorded. Keys for later steps (min_glue_piece, face)
are refused as unknown until those steps add them.

The keys (Task 7b added extract, outlines, outline_color and merge):
- colors: the most colors the final palette may have, 2 to the printer's palette cap
  (default: the cap). More may remain; the plan is then written but not ready.
- extract: how many colors quantize extracts, 2 to MAX_EXTRACT and at least colors
  (default: max(the rule color.extract.default_count, colors), source "rule"; a value
  given in a flag or the file is never raised, it is refused if below colors).
- edges: smooth, furry or exact (default smooth).
- base: auto or an index into the final palette (default auto).
- outlines: drop or keep (default drop): what happens to the outline family.
- outline_color: auto, none, or a non-empty list of distinct extraction indices (default
  auto): the outline family.
- merge: a list of [from, into] pairs of extraction indices (default: none). Each `from`
  color's pixels take the `into` color. A `from` appears once, never equals its `into`,
  and is never also an `into` (no chains). A `from` is never in the outline family; an
  `into` may be the family's core (its darkest color), but no other member.
Extraction indices are the order quantize gives (largest area first), which the preview
shows. The checks that need the extracted palette (an index below the number of colors the
image gave, no merge from the outline family) are in check_extraction_indices; it runs
against `extract` when resolving, after quantize, and after the outline step.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator

from tdmg.color import merge_problem
from tdmg.profiles import PrinterProfile
from tdmg.rules import Rule

# One color is R1 (tdmg flat), not a multicolor print, so a palette has at least two.
MIN_COLORS = 2
# A format limit, not a print threshold: labels.png is 8-bit with 255 meaning "outside", and
# tdmg.colors refuses a palette of 255 or more colors, so at most 254 can be stored.
MAX_EXTRACT = 254
DEFAULTS = {"edges": "smooth", "base": "auto", "outlines": "drop", "outline_color": "auto",
            "merge": ()}
PROFILE_DEFAULT = "colors"                         # defaults to the profile's palette cap
EXTRACT_RULE = "color.extract.default_count"
RULE_DEFAULTS = {"extract": EXTRACT_RULE}          # defaults to the rule's value
SMOOTH_RULE = "flat.smooth.sigma_px"
FURRY_RULE = "color.edges.furry_sigma_px"

Edges = Literal["smooth", "furry", "exact"]
Index = Annotated[StrictInt, Field(ge=0)]
Base = Literal["auto"] | Index
Outlines = Literal["drop", "keep"]
OutlineColor = Literal["auto", "none"] | Annotated[list[Index], Field(min_length=1)]
MergePair = Annotated[list[Index], Field(min_length=2, max_length=2)]
Source = Literal["flag", "config", "profile", "rule", "default"]


class ColorConfigError(ValueError):
    """A color setting or config file cannot be used as given. Nothing is written."""


class ColorConfig(BaseModel):
    """One source's settings; None means "not given here". Validate with context={"cap": n}."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    colors: StrictInt | None = None
    extract: StrictInt | None = None
    edges: Edges | None = None
    base: Base | None = None
    outlines: Outlines | None = None
    outline_color: OutlineColor | None = None
    merge: list[MergePair] | None = None

    @field_validator("colors")
    @classmethod
    def _within_cap(cls, v, info):
        cap = (info.context or {}).get("cap")
        if v is not None and cap is not None and not MIN_COLORS <= v <= cap:
            raise ValueError(f"must be between {MIN_COLORS} and {cap} (the printer's palette "
                             "cap)")
        return v

    @field_validator("extract")
    @classmethod
    def _extract_range(cls, v):
        if v is not None and not MIN_COLORS <= v <= MAX_EXTRACT:
            raise ValueError(f"must be between {MIN_COLORS} and {MAX_EXTRACT}")
        return v

    @field_validator("outline_color")
    @classmethod
    def _distinct(cls, v):
        if isinstance(v, list) and len(set(v)) != len(v):
            raise ValueError("lists an index more than once")
        return v

    @field_validator("merge")
    @classmethod
    def _merge_pairs(cls, v):
        problem = None if v is None else merge_problem(v)
        if problem:
            raise ValueError(problem)
        return v


KEYS = tuple(ColorConfig.model_fields)
# Every key needs exactly one default, so a key added to ColorConfig without one fails at
# import.
_DEFAULTED = [*DEFAULTS, PROFILE_DEFAULT, *RULE_DEFAULTS]
if sorted(_DEFAULTED) != sorted(KEYS):
    raise RuntimeError(f"color defaults {_DEFAULTED} do not match the ColorConfig keys "
                       f"{list(KEYS)}")


def _frozen(v):
    return tuple(_frozen(x) for x in v) if isinstance(v, (list, tuple)) else v


def _plain(v):
    return [_plain(x) for x in v] if isinstance(v, (list, tuple)) else v


@dataclass(frozen=True)
class ResolvedColorConfig:
    """The settings used, the source of each, and the config file's hash. Read-only.

    settings holds every key of KEYS. Lists (outline_color when a list, and merge) are
    stored as tuples, so nothing inside can be changed either; as_record turns them back
    into lists, as JSON stores them.
    """
    settings: Mapping[str, str | int | tuple]
    sources: Mapping[str, Source]
    config_sha256: str | None

    def __post_init__(self):
        object.__setattr__(self, "settings", MappingProxyType(
            {k: _frozen(v) for k, v in self.settings.items()}))
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))

    def as_record(self) -> dict:
        """Plain, independent dicts and lists for the record (canonical_json cannot take a
        proxy)."""
        return {"settings": {k: _plain(v) for k, v in self.settings.items()},
                "sources": dict(self.sources), "config_sha256": self.config_sha256}


def palette_cap(printer: PrinterProfile) -> int:
    """The most colors a job may use: the profile's default palette.

    The profile caps it at its basis unit's verified slot count (AMS lite, 4 slots, for the
    A1); see tdmg.profiles.MultiMaterial.
    """
    mm = printer.multi_material
    if mm is None:
        raise ColorConfigError(f"printer {printer.id} has no multi-material unit, so it "
                               "cannot print more than one color")
    if mm.default_max_filaments < MIN_COLORS:
        raise ColorConfigError(f"printer {printer.id} allows {mm.default_max_filaments} "
                               f"filament(s); a multicolor print needs at least {MIN_COLORS}")
    return mm.default_max_filaments


def _validate(data: dict, cap: int, where: str) -> ColorConfig:
    try:
        return ColorConfig.model_validate(data, context={"cap": cap})
    except ValidationError as e:
        problems = {}           # one message per key; a union field reports each branch
        for err in e.errors():
            key = str(err["loc"][0]) if err["loc"] else "?"
            given = data.get(key) if isinstance(data, dict) else None
            if err["type"] == "extra_forbidden":
                msg = f"unknown key {key!r} (known keys: {', '.join(KEYS)})"
            elif err["type"] == "value_error":        # our own validator's message, unprefixed
                msg = f"{key}: {err['ctx']['error']} (got {err['input']!r})"
            elif key == "base":
                msg = f"base must be auto or a color index, 0 or more (got {err['input']!r})"
            elif key == "outline_color":
                msg = ("outline_color must be auto, none or a non-empty list of distinct "
                       f"extraction indices, each 0 or more (got {given!r})")
            elif key == "merge":
                msg = ("merge must be a list of [from, into] pairs of extraction indices, "
                       f"each 0 or more (got {given!r})")
            else:
                msg = f"{key}: {err['msg']} (got {err['input']!r})"
            problems.setdefault(key, msg)
        raise ColorConfigError(f"{where}: " + "; ".join(problems.values())) from None


class _UniqueKeyLoader(yaml.SafeLoader):
    """yaml.SafeLoader that refuses repeated keys, non-scalar keys and merge keys (<<)."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise ColorConfigError("merge keys (<<) are not supported; write each "
                                       "setting out")
            if not isinstance(key_node, yaml.ScalarNode):
                raise ColorConfigError("a key must be a plain name, not a list or mapping")
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise ColorConfigError(f"duplicate key {key!r}")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def read_config(path: str | Path) -> tuple[dict, str]:
    """The file's settings as a plain mapping, and the SHA-256 of its bytes as stored.

    The file must be UTF-8; a leading UTF-8 byte-order mark is accepted (and hashed, since
    the hash is of the bytes). A null value (`colors: ~`, `edges: null`, or `base:` with
    nothing after it) is refused: in the file, a key is either set or left out. Anchors and
    aliases (&name, *name) are accepted: they only repeat a value, which is then validated
    like any other.
    """
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as e:
        raise ColorConfigError(f"cannot read config file {path}: {e.strerror or e}") from None
    where = f"config file {path.name}"
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ColorConfigError(f"{where} is not UTF-8 text") from None
    try:
        # A SafeLoader subclass: safe types only, and duplicate, merge (<<) and non-scalar
        # keys refused.
        raw = yaml.load(text, Loader=_UniqueKeyLoader)
    except ColorConfigError as e:
        raise ColorConfigError(f"{where}: {e}") from None
    except yaml.YAMLError as e:
        raise ColorConfigError(f"{where} is not valid YAML: {e}") from None
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ColorConfigError(f"{where} must be a mapping of settings (key: value), "
                               f"not {type(raw).__name__}")
    bad = [k for k in raw if not isinstance(k, str)]
    if bad:
        raise ColorConfigError(f"{where}: unknown key {bad[0]!r} (known keys: {', '.join(KEYS)})")
    nulls = [k for k, v in raw.items() if v is None]
    if nulls:
        raise ColorConfigError(f"{where}: {nulls[0]} is null; give it a value or leave the "
                               "key out")
    return raw, hashlib.sha256(data).hexdigest()


def resolve_color_config(flags: dict, config_path: str | Path | None, rules: dict[str, Rule],
                         printer: PrinterProfile) -> ResolvedColorConfig:
    """Flags (None = not given), then the config file, then the defaults.

    The default for colors is the printer's palette cap, and for extract the larger of the
    rule color.extract.default_count and colors. `rules` also lets the resolved edges
    preset be checked against the registry here (see edge_sigma_px). Then, on the resolved
    values: base must
    be below colors (check_base), extract at least colors, and the indices in outline_color
    and merge below extract and not overlapping (check_extraction_indices).
    """
    cap = palette_cap(printer)
    given = {k: v for k, v in flags.items() if v is not None}
    from_flags = _validate(given, cap, "command-line flags")
    from_file, sha = ColorConfig(), None
    if config_path is not None:
        raw, sha = read_config(config_path)
        from_file = _validate(raw, cap, f"config file {Path(config_path).name}")
    settings, sources = {}, {}
    for key in KEYS:
        if getattr(from_flags, key) is not None:
            settings[key], sources[key] = getattr(from_flags, key), "flag"
        elif getattr(from_file, key) is not None:
            settings[key], sources[key] = getattr(from_file, key), "config"
        elif key == PROFILE_DEFAULT:
            settings[key], sources[key] = cap, "profile"
        elif key in RULE_DEFAULTS:
            # extract: at least colors, so the default never conflicts with it.
            value = max(_rule_default(key, rules, cap), settings["colors"])
            settings[key], sources[key] = value, "rule"
        else:
            settings[key], sources[key] = DEFAULTS[key], "default"
    # Cleanup only shrinks the palette, so a base at or above colors can never be valid in a
    # ready plan. check_base is applied again to the final palette.
    check_base(settings["base"], settings["colors"])
    if settings["extract"] < settings["colors"]:
        raise ColorConfigError(
            f"extract {settings['extract']} is below colors {settings['colors']}: extraction "
            "must give at least as many colors as the final palette may have; raise extract "
            "or lower colors")
    check_extraction_indices(settings["outline_color"], settings["merge"],
                             settings["extract"])
    edge_sigma_px(settings["edges"], rules)
    return ResolvedColorConfig(settings=settings, sources=sources, config_sha256=sha)


def _rule_default(key: str, rules: dict[str, Rule], cap: int):
    """The default of `key` from its rule, validated like a setting."""
    rule_id = RULE_DEFAULTS[key]
    if rule_id not in rules:
        raise ColorConfigError(f"the default for {key} needs rule {rule_id}, which is not in "
                               "the rules registry")
    return getattr(_validate({key: rules[rule_id].default}, cap, f"rule {rule_id}"), key)


def check_extraction_indices(outline_color, merge, n_extracted: int,
                             family=None, core=None) -> None:
    """Refuse extraction indices the extraction does not have, and merges that touch the
    outline family.

    n_extracted: the number of extracted colors; after quantize it can be below `extract`,
    when the image has fewer distinct colors. family: the outline family's extraction
    indices, or None before the outline step has found it; core: its kept core (the
    darkest member, tdmg.color.outline_core), None when the family is empty. merge's own
    structure (merge_problem) is checked again here, for direct callers.

    A merge's `from` must be outside the family (and outside an explicit outline_color
    list, which is always part of it). Its `into` may be the core (decided 2026-11-11, plan
    Task 7c: a color can be merged into the outline's darkest color, which stays in wide
    areas) but no other family member. Before the outline step (family None) the core is
    not known yet, so an `into` in an explicit list is checked only on the second call.
    """
    def which() -> str:
        return (f"the extraction has {n_extracted} colors (indices 0 to {n_extracted - 1}); "
                "choose indices from the preview's extracted colors")
    known = family is not None
    family = set(family or ())
    listed = set()
    if isinstance(outline_color, (list, tuple)):
        bad = [i for i in outline_color if not 0 <= i < n_extracted]
        if bad:
            raise ColorConfigError(f"outline_color {bad[0]} is not an extraction index: "
                                   + which())
        listed = set(outline_color)
    merges = [tuple(p) for p in merge]
    problem = merge_problem(merges)
    if problem:
        raise ColorConfigError(f"merge: {problem}")
    for a, b in merges:
        for i in (a, b):
            if not 0 <= i < n_extracted:
                raise ColorConfigError(f"merge [{a}, {b}]: {i} is not an extraction index: "
                                       + which())
        if a in family | listed:
            raise ColorConfigError(
                f"merge [{a}, {b}]: color {a} is in the outline family, which the outline "
                "handling replaces; merge only colors outside it")
        if known and b in family | listed and b != core:
            raise ColorConfigError(
                f"merge [{a}, {b}]: color {b} is in the outline family but is not its core"
                + ("" if core is None else f" ({core})")
                + "; merge into a color outside the family or into the core")


def check_base(base: str | int, n_colors: int) -> None:
    """Refuse a base index that is not in the final palette (it may shrink in cleanup)."""
    if base == "auto":
        return
    if isinstance(base, bool) or not isinstance(base, int) or not 0 <= base < n_colors:
        raise ColorConfigError(f"base {base!r} is not a color index of a {n_colors}-color "
                               f"palette (0 to {n_colors - 1}); choose one from the preview or "
                               "use auto")


def edge_sigma_px(edges: str, rules: dict[str, Rule]) -> tuple[float, str | None]:
    """The Gaussian sigma (image pixels) for an edges preset, and the rule it comes from.

    smooth reuses the outline-smoothing rule; exact is no blur by definition, so no rule.
    """
    # Values from a config or flag are already checked by the Edges Literal; this check
    # guards direct callers.
    if edges == "exact":
        return 0.0, None
    rule_id = {"smooth": SMOOTH_RULE, "furry": FURRY_RULE}.get(edges)
    if rule_id is None:
        raise ColorConfigError(f"edges {edges!r} is not a preset (smooth, furry or exact)")
    if rule_id not in rules:
        raise ColorConfigError(f"edges {edges!r} needs rule {rule_id}, which is not in the "
                               "rules registry")
    return float(rules[rule_id].default), rule_id

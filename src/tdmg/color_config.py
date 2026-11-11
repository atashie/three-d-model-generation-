"""Color settings for `tdmg colors` (docs/plans/2026-11-11-color-palette.md, Decisions 5 and 6).

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

from tdmg.profiles import PrinterProfile
from tdmg.rules import Rule

# One color is R1 (tdmg flat), not a multicolor print, so a palette has at least two.
MIN_COLORS = 2
DEFAULTS = {"edges": "smooth", "base": "auto"}
PROFILE_DEFAULT = "colors"                         # defaults to the profile's palette cap
SMOOTH_RULE = "flat.smooth.sigma_px"
FURRY_RULE = "color.edges.furry_sigma_px"

Edges = Literal["smooth", "furry", "exact"]
Base = Literal["auto"] | Annotated[StrictInt, Field(ge=0)]
Source = Literal["flag", "config", "profile", "default"]


class ColorConfigError(ValueError):
    """A color setting or config file cannot be used as given. Nothing is written."""


class ColorConfig(BaseModel):
    """One source's settings; None means "not given here". Validate with context={"cap": n}."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    colors: StrictInt | None = None
    edges: Edges | None = None
    base: Base | None = None

    @field_validator("colors")
    @classmethod
    def _within_cap(cls, v, info):
        cap = (info.context or {}).get("cap")
        if v is not None and cap is not None and not MIN_COLORS <= v <= cap:
            raise ValueError(f"must be between {MIN_COLORS} and {cap} (the printer's palette "
                             "cap)")
        return v


KEYS = tuple(ColorConfig.model_fields)
# Every key needs a default, so a key added to ColorConfig without one fails at import.
if set(DEFAULTS) | {PROFILE_DEFAULT} != set(KEYS) or PROFILE_DEFAULT in DEFAULTS:
    raise RuntimeError(f"color defaults {sorted(DEFAULTS)} + {PROFILE_DEFAULT!r} do not "
                       f"match the ColorConfig keys {list(KEYS)}")


@dataclass(frozen=True)
class ResolvedColorConfig:
    """The settings used, the source of each, and the config file's hash. Read-only."""
    settings: Mapping[str, str | int]       # colors, edges, base
    sources: Mapping[str, Source]
    config_sha256: str | None

    def __post_init__(self):
        object.__setattr__(self, "settings", MappingProxyType(dict(self.settings)))
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))

    def as_record(self) -> dict:
        """Plain, independent dicts for the record (canonical_json cannot take a proxy)."""
        return {"settings": dict(self.settings), "sources": dict(self.sources),
                "config_sha256": self.config_sha256}


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
            if err["type"] == "extra_forbidden":
                msg = f"unknown key {key!r} (known keys: {', '.join(KEYS)})"
            elif key == "base":
                msg = f"base must be auto or a color index, 0 or more (got {err['input']!r})"
            elif err["type"] == "value_error":        # our own validator's message, unprefixed
                msg = f"{key}: {err['ctx']['error']} (got {err['input']!r})"
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

    The default for colors is the printer's palette cap. `rules` is taken so that the
    resolved edges preset is checked against the registry here (see edge_sigma_px).
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
        else:
            settings[key], sources[key] = DEFAULTS[key], "default"
    # Cleanup only shrinks the palette, so a base at or above colors can never be valid.
    # check_base is applied again to the final palette.
    check_base(settings["base"], settings["colors"])
    edge_sigma_px(settings["edges"], rules)
    return ResolvedColorConfig(settings=settings, sources=sources, config_sha256=sha)


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

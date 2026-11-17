"""Jobs: one print's working folder, `jobs/<name>/`, and its spec, `job.yaml`
(docs/plans/2026-11-16-restructure-design.md sections 3 and 4; plan Task 6).

`job.yaml` (schema tdmg.job/1) holds:
- `name`, `class` (an output class, tdmg.recipes.CLASSES) and `recipe` (the recipe the class
  resolved to);
- `source`: the image `file` (a path inside the job folder, `source/<name>`), its `sha256`,
  the owner-corrected selection `mask` (null, or `file` and `sha256`), and `origin` (photo,
  drawing, generated or unknown). For `generated` it also holds GENERATED_FIELDS, each a
  string, `unknown` when the owner does not know it. Only the mask may change after
  `job new` (set_mask, for a mask corrected after the selection preview); the rest of
  `source` is fixed;
- `stages`: every stage of the recipe with all of its parameters (STAGE_FIELDS);
- `confirmations`: a list, empty until `tdmg job confirm` exists (plan Task 8);
- `revision`: 1 when made, bumped by every change (save_job).

A stage parameter maps one to one onto the stage command's option of the same name (the
CLI's snake_case spelling; for `colors`, the keys of tdmg.color_config). The value null
means "not given": the command's own default applies, exactly as when the option is left
out. A job must not spell out a default: the selection record's selection_id tells a
value given from the same value taken from a rule default, and colors.json records each
setting's source (flag, config, rule or default) beside the setting, though colors_id
hashes the values only. A REQUIRED parameter has no default: null means "not set yet",
and the stage cannot run until it is set (unset_required). A parameter the command takes
as a float is a float in the job: an integer written by hand (60) is read as 60.0, since
the records hash 60 and 60.0 differently.

Slicer folders are not parameters: they are absolute paths on one machine, so they come
from `tdmg job run`'s options or the environment when a stage runs (tdmg.job_runner), not
from job.yaml.

Reading is strict: unknown and missing keys, wrong types, YAML anchors, aliases, merge
keys, duplicate keys and explicit tags (!!str) are refused, and every path must be
relative to the job folder (forward slashes, no `..`, no drive letter). Only plain decimal
numbers are numbers, only true/false are booleans and only null/~/nothing is null: YAML
1.1's other forms (1:30, 010, 0x1f, 1_000, yes, on, dates) are text, which a number,
boolean or null field then refuses. Writing is canonical (dump_job): the same
content always gives the same bytes (with the PyYAML version pinned in uv.lock), and the
file is written through tdmg.records (exclusive creates for a new job, an atomic rename for
job.yaml).
"""

from __future__ import annotations

import copy
import hashlib
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

import yaml
from pydantic import ValidationError

from tdmg import paths
from tdmg.color_config import KEYS as COLOR_KEYS
from tdmg.color_config import ColorConfig
from tdmg.color_slicing import FACE_CHOICES
from tdmg.colored_flat import _number as colored_flat_size
from tdmg.colors import check_width_mm as colors_width
from tdmg.flat import _require_positive as flat_size
from tdmg.flat import _smooth_value as flat_smooth
from tdmg.recipes import CLASSES, recipe, resolve
from tdmg.records import RecordError, replace_file, write_outputs
from tdmg.selection import SelectionError, load_image, load_mask

SCHEMA = "tdmg.job/1"
JOB_FILE = "job.yaml"
SOURCE_DIR = "source"
NAME_MAX = 63           # the plan's pattern: one leading character and up to 62 more
NAME_PATTERN = re.compile(rf"[a-z0-9][a-z0-9-]{{0,{NAME_MAX - 1}}}")
NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")
# Device names Windows reserves in any case and with any extension (CON, con.txt, ...).
WINDOWS_RESERVED = frozenset({"con", "prn", "aux", "nul",
                              *(f"com{i}" for i in range(1, 10)),
                              *(f"lpt{i}" for i in range(1, 10))})
# A source file keeps its own name when it is a plain portable one; otherwise job new
# refuses it and says how to rename it. 128 characters is a format choice, not a print
# limit: below every common file system's 255-character name limit, and short enough that
# <name>/source/<file> (at most 63 + 8 + 128 = 199 characters) leaves about 60 for the
# jobs folder's own path inside Windows' classic 260-character path limit.
SOURCE_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
ORIGINS = ("photo", "drawing", "generated", "unknown")
DEFAULT_ORIGIN = "unknown"
UNKNOWN = "unknown"
# What the owner knows of a generated image (design section 3): the prompt, the generator
# and its version, its settings, the reference inputs, the candidate chosen, later edits.
GENERATED_FIELDS = ("prompt", "generator", "version", "settings", "references", "chosen",
                    "edits")
TOP_KEYS = ("schema", "name", "class", "recipe", "source", "stages", "confirmations",
            "revision")
SOURCE_KEYS = ("file", "sha256", "mask", "origin")
MASK_KEYS = ("file", "sha256")
HEX64 = re.compile(r"[0-9a-f]{64}")
# PyYAML folds long lines at this width; wide enough that no value is folded.
YAML_WIDTH = 1_000_000


class JobError(ValueError):
    """A job cannot be made, read or written as asked. Nothing of ours is written."""


# --- names and paths -------------------------------------------------------------------

def name_problem(name) -> str | None:
    """Why `name` cannot name a job, or None. Lowercase ASCII letters, digits and hyphens,
    starting with a letter or digit, at most NAME_MAX characters, not a Windows device
    name."""
    if not isinstance(name, str):
        return f"a job name must be text, not {type(name).__name__}"
    if not name:
        return "a job name cannot be empty"
    if len(name) > NAME_MAX:
        return f"job name is {len(name)} characters long; the most is {NAME_MAX}"
    if NAME_PATTERN.fullmatch(name) is None:
        bad = sorted({c for c in name if c not in NAME_CHARS})
        if bad and all(c.isascii() and c.isupper() for c in bad):
            return (f"job name {name!a} has uppercase letters; use lowercase letters, "
                    "digits and hyphens")
        if bad:
            return (f"job name {name!a} holds {', '.join(map(ascii, bad))}; use only "
                    "lowercase letters a-z, digits 0-9 and hyphens")
        return f"job name {name!a} starts with a hyphen; start with a letter or digit"
    if name in WINDOWS_RESERVED:
        return f"job name {name!a} is a device name Windows reserves; choose another"
    return None


def check_name(name) -> str:
    problem = name_problem(name)
    if problem:
        raise JobError(problem)
    return name


def source_name_problem(name: str) -> str | None:
    """Why a file name cannot be kept in source/, or None."""
    if SOURCE_NAME_PATTERN.fullmatch(name) is None:
        return (f"file name {name!a} is not a plain portable name; copy or rename the file "
                "to one of letters, digits, '.', '_' and '-' (starting with a letter or "
                "digit, at most 128 characters)")
    if name.endswith("."):
        return f"file name {name!a} ends with a dot, which Windows drops"
    if name.split(".")[0].lower() in WINDOWS_RESERVED:
        return f"file name {name!a} is a device name Windows reserves; rename the file"
    return None


def path_problem(value) -> str | None:
    """Why `value` is not a path relative to the job folder, or None. Forward slashes only;
    no absolute path, drive letter, `.` or `..` part, empty part or Windows device name."""
    if not isinstance(value, str):
        return f"must be a path (text), not {type(value).__name__}"
    if not value:
        return "must be a path, not empty text"
    if "\\" in value:
        return f"{value!a} holds a backslash; use forward slashes"
    if ":" in value:
        return f"{value!a} holds ':' (a drive letter or stream); give a relative path"
    if value.startswith("/"):
        return f"{value!a} is absolute; give a path relative to the job folder"
    if any(ord(c) < 32 or c == "\x7f" for c in value):
        return f"{value!a} holds a control character"
    for part in value.split("/"):
        if part in ("", ".", ".."):
            return f"{value!a} has an empty, '.' or '..' part; give a plain relative path"
        if part.split(".")[0].lower() in WINDOWS_RESERVED:
            return f"{value!a} has {part!a}, a device name Windows reserves"
    return None


def _source_file_problem(value) -> str | None:
    problem = path_problem(value)
    if problem:
        return problem
    parts = value.split("/")
    if len(parts) != 2 or parts[0] != SOURCE_DIR:
        return f"{value!a} must be {SOURCE_DIR}/<file name>"
    return source_name_problem(parts[1])


# --- value types -------------------------------------------------------------------------

Check = Callable[[object], str | None]   # a problem with the value, or None


def _text(v) -> str | None:
    if not isinstance(v, str):
        return f"must be text, not {type(v).__name__}"
    try:
        v.encode("utf-8")
    except UnicodeEncodeError as e:
        return f"cannot be stored as UTF-8 ({e.reason} at position {e.start})"
    return None


def _number(v) -> str | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return f"must be a number, not {type(v).__name__}"
    try:
        finite = math.isfinite(v)
    except OverflowError:            # an integer too large for a float
        return "is too large a number"
    if not finite:
        return f"must be a finite number, not {v}"
    return None


def _integer(v) -> str | None:
    if isinstance(v, bool) or not isinstance(v, int):
        return f"must be an integer, not {type(v).__name__}"
    return None


def _boolean(v) -> str | None:
    return None if isinstance(v, bool) else f"must be true or false, not {type(v).__name__}"


def _points(v) -> str | None:
    if not isinstance(v, list):
        return f"must be a list of [x, y] pixel points, not {type(v).__name__}"
    for i, p in enumerate(v):
        if (not isinstance(p, list) or len(p) != 2
                or any(_integer(c) for c in p)):
            return f"item {i} must be [x, y], two integers"
    return None


def _choice(options) -> Check:
    def check(v) -> str | None:
        if v not in options or not isinstance(v, str):
            return f"must be one of {', '.join(options)}, not {v!a}"
        return None
    return check


def _nullable(check: Check) -> Check:
    def nullable(v) -> str | None:
        return None if v is None else check(v)
    return nullable


def _color_key(key: str) -> Check:
    """One tdmg.color_config key, checked by its own model (types and the checks that need
    no image or printer)."""
    def check(v) -> str | None:
        if v is None:
            return None
        try:
            ColorConfig.model_validate({key: v})
        except ValidationError as e:
            return e.errors()[0]["msg"]
        return None
    return check


class Field:
    """A stage parameter: its type check; whether it has no default (required); its
    default; whether the command takes it as a float (`real`: an integer is read as a
    float, as the command line would pass it); and `limit`, the stage's own range check
    (raises ValueError), run where a value is set (check_limits), not on every read."""

    def __init__(self, check: Check, *, required: bool = False, default=None,
                 real: bool = False, limit: Callable[[object], object] | None = None):
        # null is allowed where it means "not given" (default None) or "not set yet"
        # (required); a parameter with another default must hold a value.
        self.check = _nullable(check) if required or default is None else check
        self.required = required
        self.default = default
        self.real = real
        self.limit = limit


def _real(**kw) -> Field:
    return Field(_number, real=True, **kw)


def _named(check, name: str):
    """A stage check that takes (name, value), as one that takes the value."""
    return lambda v: check(name, v)


# Each stage's parameters, named as the stage command's options (CLI snake_case; for
# colors, tdmg.color_config.KEYS), with the command's default when it is not None. A
# parameter whose default is None is written as null (not given). Not listed: options that
# hold machine paths (--slicer-dir, --prusaslicer-dir, --out and the input folders, which
# the job runner supplies), --config (colors' file keys are parameters here) and flat's
# --smooth-px under --colors (the stage refuses any value).
REAL_COLOR_KEYS = ("outline_width_mm",)    # tdmg.color_config's float key
STAGE_FIELDS: dict[str, dict[str, Field]] = {
    "select": {                                   # tdmg select
        "instructions": Field(_text),
        "remove_at": Field(_points, default=[]),
        "keep_at": Field(_points, default=[]),
        "tolerance": _real(),
        "alpha_min": Field(_integer),
        "mask": Field(_source_file_problem),
    },
    "flat": {                                     # tdmg flat (no --colors)
        "width_mm": _real(required=True, limit=_named(flat_size, "width_mm")),
        "thickness_mm": _real(required=True, limit=_named(flat_size, "thickness_mm")),
        "printer": Field(_text),
        "smooth_px": _real(limit=flat_smooth),
    },
    "colors": {                                   # tdmg colors, with its config keys
        "width_mm": _real(required=True, limit=colors_width),
        **{key: Field(_color_key(key), real=key in REAL_COLOR_KEYS) for key in COLOR_KEYS},
    },
    "colored_flat": {                             # tdmg flat --colors
        "thickness_mm": _real(required=True,
                              limit=_named(colored_flat_size, "thickness_mm")),
        "width_mm": _real(limit=_named(colored_flat_size, "width_mm")),
        "printer": Field(_text),
    },
    "slice": {                                    # tdmg slice
        "timeout_s": _real(),
        "skip_tree_check": Field(_boolean, default=False),
        "face": Field(_choice(tuple(FACE_CHOICES))),
    },
}
# tdmg slice refuses --face for a single-color folder, so a single-color recipe's slice
# stage has no face. A recipe is multicolor when it has a colors stage.
SINGLE_COLOR_SLICE_SKIPS = ("face",)


def stage_fields(recipe_id: str, stage: str) -> dict[str, Field]:
    fields = dict(STAGE_FIELDS[stage])
    if stage == "slice" and "colors" not in recipe(recipe_id).stages:
        for key in SINGLE_COLOR_SLICE_SKIPS:
            del fields[key]
    return fields


def default_stages(recipe_id: str) -> dict[str, dict]:
    """Every stage of the recipe with every parameter at the stage command's default."""
    r = recipe(recipe_id)
    missing = [s for s in r.stages if s not in STAGE_FIELDS]
    if missing:
        raise JobError(f"recipe {r.id} has stages with no job parameters yet: "
                       f"{', '.join(missing)}")
    return {stage: {key: copy.deepcopy(f.default)
                    for key, f in stage_fields(recipe_id, stage).items()}
            for stage in r.stages}


def required_stage(recipe_id: str, key: str) -> str | None:
    """The first stage of the recipe in which `key` is required, or None."""
    for stage in recipe(recipe_id).stages:
        field = stage_fields(recipe_id, stage).get(key)
        if field is not None and field.required:
            return stage
    return None


def check_limits(job: dict) -> None:
    """Run each set parameter's stage range check (Field.limit), so a value the stage
    would refuse (a width of 0) is refused when it is set, not only when the stage runs."""
    for stage in recipe(job["recipe"]).stages:
        for key, f in stage_fields(job["recipe"], stage).items():
            value = job["stages"][stage][key]
            if f.limit is not None and value is not None:
                try:
                    f.limit(value)
                except ValueError as e:
                    raise JobError(f"stages.{stage}.{key}: {e}") from None


def unset_required(job: dict) -> list[str]:
    """'stage.key' for every required parameter still null, in stage order."""
    out = []
    for stage in recipe(job["recipe"]).stages:
        for key, f in stage_fields(job["recipe"], stage).items():
            if f.required and job["stages"][stage][key] is None:
                out.append(f"{stage}.{key}")
    return out


# --- validation --------------------------------------------------------------------------

def _keys(where: str, value, keys: tuple[str, ...]) -> None:
    if not isinstance(value, dict):
        raise JobError(f"{where} must be a mapping, not {type(value).__name__}")
    unknown = [k for k in value if k not in keys]
    if unknown:
        raise JobError(f"{where}: unknown key {unknown[0]!a} (known: {', '.join(keys)})")
    missing = [k for k in keys if k not in value]
    if missing:
        raise JobError(f"{where}: missing key {missing[0]!a}")


def _field(where: str, value, check: Check) -> None:
    problem = check(value)
    if problem:
        raise JobError(f"{where} {problem}")


def _sha256(v) -> str | None:
    if not isinstance(v, str) or HEX64.fullmatch(v) is None:
        return "must be a SHA-256 (64 lowercase hex digits)"
    return None


def _generated_value(v) -> str | None:
    problem = _text(v)
    if problem:
        return problem
    if not v:
        return f"cannot be empty; write {UNKNOWN} when it is not known"
    return None


def validate_job(job) -> dict:
    """A copy of the job if it follows tdmg.job/1 exactly, with every integer in a float
    parameter (Field.real) made a float; JobError naming the first problem."""
    _keys("job", job, TOP_KEYS)
    job = copy.deepcopy(job)
    if job["schema"] != SCHEMA:
        raise JobError(f"job schema is {job['schema']!a}; this tdmg reads {SCHEMA}")
    problem = name_problem(job["name"])
    if problem:
        raise JobError(f"name: {problem}")
    cls = job["class"]
    if not isinstance(cls, str) or cls not in CLASSES:
        raise JobError(f"class {cls!a} is not an output class "
                       f"(known: {', '.join(CLASSES)})")
    rid = job["recipe"]
    if not isinstance(rid, str) or rid not in CLASSES[cls]:
        raise JobError(f"recipe {rid!a} is not in class {cls} "
                       f"({', '.join(CLASSES[cls])})")
    _validate_source(job["source"])
    _validate_stages(rid, job["stages"], job["source"])
    conf = job["confirmations"]
    if not isinstance(conf, list):
        raise JobError(f"confirmations must be a list, not {type(conf).__name__}")
    if conf:
        # tdmg.job/1 defines no confirmation entry yet (plan Task 8 adds tdmg job confirm).
        raise JobError("confirmations must be empty: this tdmg cannot record or read "
                       "confirmations yet")
    rev = job["revision"]
    if _integer(rev) or rev < 1:
        raise JobError(f"revision must be an integer of at least 1, not {rev!a}")
    return job


def _validate_source(source) -> None:
    if not isinstance(source, dict):
        raise JobError(f"source must be a mapping, not {type(source).__name__}")
    # Keys first (unknown, then missing), then values.
    unknown = [k for k in source if k not in SOURCE_KEYS + GENERATED_FIELDS]
    if unknown:
        raise JobError(f"source: unknown key {unknown[0]!a} "
                       f"(known: {', '.join(SOURCE_KEYS + GENERATED_FIELDS)})")
    missing = [k for k in SOURCE_KEYS if k not in source]
    if missing:
        raise JobError(f"source: missing key {missing[0]!a}")
    origin = source["origin"]
    _field("source.origin", origin, _choice(ORIGINS))
    if origin != "generated":
        extra = [k for k in GENERATED_FIELDS if k in source]
        if extra:
            raise JobError(f"source.{extra[0]} is for origin generated only "
                           f"(origin is {origin})")
    _keys("source", source, SOURCE_KEYS + (GENERATED_FIELDS if origin == "generated"
                                          else ()))
    _field("source.file", source["file"], _source_file_problem)
    _field("source.sha256", source["sha256"], _sha256)
    mask = source["mask"]
    if mask is not None:
        _keys("source.mask", mask, MASK_KEYS)
        _field("source.mask.file", mask["file"], _source_file_problem)
        _field("source.mask.sha256", mask["sha256"], _sha256)
        if mask["file"].lower() == source["file"].lower():
            raise JobError("source.mask.file must differ from source.file")
    if origin == "generated":
        for k in GENERATED_FIELDS:
            _field(f"source.{k}", source[k], _generated_value)


def _validate_stages(rid: str, stages, source: dict) -> None:
    order = recipe(rid).stages
    _keys("stages", stages, order)
    for stage in order:
        fields = stage_fields(rid, stage)
        _keys(f"stages.{stage}", stages[stage], tuple(fields))
        for key, f in fields.items():
            value = stages[stage][key]
            _field(f"stages.{stage}.{key}", value, f.check)
            if f.real and isinstance(value, int) and not isinstance(value, bool):
                stages[stage][key] = float(value)     # as the command line passes it
    select = stages.get("select")
    if select is not None:
        mask_file = None if source["mask"] is None else source["mask"]["file"]
        if select["mask"] != mask_file:
            raise JobError(f"stages.select.mask is {select['mask']!a}, but source.mask.file "
                           f"is {mask_file!a}; they must be the same")


# --- canonical YAML ----------------------------------------------------------------------

class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses anchors, aliases, explicit tags, merge keys, non-scalar and
    repeated keys, and that resolves only plain forms: decimal integers, decimal floats
    with a point, true/false and null/~/nothing. Every other plain scalar is text."""

    yaml_implicit_resolvers: ClassVar[dict] = {}    # filled below, replacing SafeLoader's

    def compose_node(self, parent, index):
        event = self.peek_event()
        if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
            raise JobError("anchors and aliases (&name, *name) are not allowed; write each "
                           "value out")
        if getattr(event, "tag", None) is not None:
            raise JobError(f"explicit tags ({event.tag}) are not allowed; write the value "
                           "plainly")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise JobError("merge keys (<<) are not allowed; write each value out")
            if not isinstance(key_node, yaml.ScalarNode):
                raise JobError("a key must be a plain name, not a list or mapping")
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise JobError(f"duplicate key {key!a}")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


# A subset of SafeLoader's resolvers, so whatever SafeDumper writes unquoted reads back the
# same: SafeDumper quotes any text that SafeLoader would resolve to something else.
for _tag, _pattern, _first in (
        ("bool", r"true|false", "tf"),
        ("int", r"-?(?:0|[1-9][0-9]*)", "-0123456789"),
        # The exponent's sign is required, as in SafeLoader's float pattern: SafeDumper
        # writes "1.0e5" (text) unquoted, and real floats as "1.0e+20" or "1.0e-05".
        ("float", r"-?(?:0|[1-9][0-9]*)\.[0-9]+(?:[eE][-+][0-9]+)?", "-0123456789"),
        ("null", r"~|null|", ["~", "n", ""]),
        ("merge", r"<<", "<")):
    _StrictLoader.add_implicit_resolver(f"tag:yaml.org,2002:{_tag}",
                                        re.compile(rf"^(?:{_pattern})$"), list(_first))


class _Dumper(yaml.SafeDumper):
    """SafeDumper that never writes anchors or aliases (a value used twice is written
    twice)."""

    def ignore_aliases(self, data):
        return True


def _yaml(job: dict) -> bytes:
    # Sorted keys, block style, ASCII only (non-ASCII is escaped, so no YAML line-break
    # character is ever written raw), "\n" line ends, and no folding.
    return yaml.dump(job, Dumper=_Dumper, sort_keys=True, default_flow_style=False,
                     allow_unicode=False, width=YAML_WIDTH, indent=2,
                     line_break="\n").encode("ascii")


def parse_job(data: bytes) -> dict:
    """A job from job.yaml's bytes, validated (validate_job)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise JobError(f"{JOB_FILE} is not UTF-8 text") from None
    try:
        job = yaml.load(text, Loader=_StrictLoader)
    except yaml.YAMLError as e:
        raise JobError(f"{JOB_FILE} is not valid YAML: {e}") from None
    return validate_job(job)


def dump_job(job: dict) -> bytes:
    """job.yaml's canonical bytes: the same content always gives the same bytes. Validated
    first (validate_job, so an integer in a float parameter is written as a float), and
    checked to read back as the same content and the same bytes."""
    job = validate_job(job)
    data = _yaml(job)
    back = parse_job(data)
    if back != job or _yaml(back) != data:
        raise JobError("job.yaml would not read back as written; this is a bug in tdmg.jobs")
    return data


# --- folders ------------------------------------------------------------------------------

def default_jobs_dir() -> Path:
    """The checkout's jobs/ folder. Outside a source checkout (an installed wheel) there is
    no default, and --jobs-dir must be given."""
    if paths.REPO_ROOT is None:
        raise JobError("tdmg is not running from a source checkout, so there is no default "
                       "jobs folder; give --jobs-dir")
    return paths.REPO_ROOT / "jobs"


def job_dir(jobs_dir: str | Path, name: str) -> Path:
    return Path(jobs_dir) / check_name(name)


def load_job(folder: str | Path) -> dict:
    """The job in folder/job.yaml, validated, with its name equal to the folder's."""
    folder = Path(folder)
    try:
        data = (folder / JOB_FILE).read_bytes()
    except FileNotFoundError:
        raise JobError(f"{folder} has no {JOB_FILE}: not a job, or an incomplete one"
                       ) from None
    try:
        job = parse_job(data)
    except JobError as e:
        raise JobError(f"{folder / JOB_FILE}: {e}") from None
    if job["name"] != folder.name:
        raise JobError(f"{folder / JOB_FILE} names the job {job['name']!a}, but its folder "
                       f"is {folder.name!a}")
    return job


def check_source(folder: str | Path, job: dict) -> None:
    """Refuse a source file (image or mask) that is missing or whose SHA-256 differs from
    job.yaml's."""
    folder = Path(folder)
    entries = [job["source"]] + ([job["source"]["mask"]] if job["source"]["mask"] else [])
    for entry in entries:
        path = folder / entry["file"]
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            raise JobError(f"source file {entry['file']} is missing from {folder}") from None
        if digest != entry["sha256"]:
            raise JobError(f"source file {entry['file']} has changed: its SHA-256 is "
                           f"{digest}, job.yaml says {entry['sha256']}")


# Fixed for the job's life: a different image, origin or class is a new job. Within
# source, only the mask may change (set_mask).
FIXED_KEYS = ("schema", "name", "class", "recipe", "source")
CHANGEABLE_SOURCE_KEYS = ("mask",)


def _fixed(job: dict, key: str):
    value = job.get(key)
    if key == "source" and isinstance(value, dict):
        return {k: v for k, v in value.items() if k not in CHANGEABLE_SOURCE_KEYS}
    return value


def check_not_linked(folder: str | Path) -> None:
    """Refuse a job folder, or its source/ folder, that is a symlink or a junction: a job
    writes only inside its own folder, never through a link to somewhere else."""
    folder = Path(folder)
    for path in (folder, folder / SOURCE_DIR):
        if path.is_symlink() or path.is_junction():
            raise JobError(f"{path} is a link (symlink or junction); a job folder and its "
                           f"{SOURCE_DIR}/ must be plain folders")


def _check_mask_file(folder: Path, job: dict) -> None:
    """The job's mask file, if any, is a black/white image of the source image's size
    (tdmg select's load_mask), as set_mask checks before it copies one in."""
    entry = job["source"]["mask"]
    if entry is None:
        return
    try:
        intake = load_image(folder / job["source"]["file"])
        load_mask(folder / entry["file"], intake.rgba.shape[:2])
    except SelectionError as e:
        raise JobError(f"{entry['file']}: {e}") from None


def save_job(folder: str | Path, job: dict) -> dict:
    """Write a changed job over folder/job.yaml, with the revision bumped; return it.

    `job` must carry the revision on disk (it was read and changed in memory), or the
    change is refused as made against an older version. Name, class, recipe and source are
    fixed, except source.mask. A changed mask is checked here whoever made the change (so
    set_mask is not the only safe way): its file must be in the folder with that SHA-256
    and be a black/white image of the source image's size. Each set parameter must pass
    the stage's own range check (check_limits). A job folder or source/ that is a link is
    refused (check_not_linked). A job equal to the one on disk is not written and keeps
    its revision."""
    folder = Path(folder)
    check_not_linked(folder)
    current = load_job(folder)
    job = validate_job(job)
    if job["revision"] != current["revision"]:
        raise JobError(f"job {current['name']} is at revision {current['revision']}, not "
                       f"{job['revision']!a}; read it again and redo the change")
    changed = [k for k in FIXED_KEYS if _fixed(job, k) != _fixed(current, k)]
    if changed:
        raise JobError(f"a job's {', '.join(changed)} cannot change; make a new job")
    if job == current:
        return current
    check_limits(job)
    if job["source"]["mask"] != current["source"]["mask"]:
        check_source(folder, job)
        _check_mask_file(folder, job)
    new = copy.deepcopy(job)
    new["revision"] = current["revision"] + 1
    data = dump_job(new)
    try:
        replace_file(folder, JOB_FILE, data)
    except RecordError as e:
        raise JobError(str(e)) from None
    return new


def _read_checked(path: Path, what: str) -> bytes:
    if not path.exists():
        raise JobError(f"{what} {path} does not exist")
    if not path.is_file():
        raise JobError(f"{what} {path} is not a file")
    return path.read_bytes()


def _read_mask(mask: Path, shape: tuple[int, int], image_name: str) -> tuple[bytes, str]:
    """The mask file's bytes and SHA-256, if it is a black/white image of `shape` with a
    plain name other than the image's."""
    data = _read_checked(mask, "mask")
    problem = source_name_problem(mask.name)
    if problem:
        raise JobError(f"mask {problem}")
    if mask.name.lower() == image_name.lower():
        raise JobError(f"the mask and the image are both named {image_name!a}; rename "
                       "one of them")
    try:
        load_mask(mask, shape)
    except SelectionError as e:
        raise JobError(f"mask: {e}") from None
    digest = hashlib.sha256(data).hexdigest()
    if hashlib.sha256(mask.read_bytes()).hexdigest() != digest:
        raise JobError(f"mask {mask} changed while it was read; try again")
    return data, digest


def _mask_destination(source_dir: Path, name: str, digest: str) -> tuple[str, bool]:
    """(file name in source/, whether it must be written). A file already there is never
    overwritten: an earlier mask may be covered by a confirmation. The mask's own name is
    used if it is free or already holds these bytes; else <stem>-<12 hex of its SHA-256>
    <suffix>; if that holds other bytes too, refused. Names are compared ignoring case, as
    Windows and macOS do."""
    present = {p.name.lower(): p for p in source_dir.iterdir()} if source_dir.is_dir() else {}
    stem, dot, suffix = name.rpartition(".")
    hashed = f"{stem}-{digest[:12]}.{suffix}" if dot else f"{name}-{digest[:12]}"
    for candidate in (name, hashed):
        problem = source_name_problem(candidate)
        if problem:
            raise JobError(f"mask {problem}")
        existing = present.get(candidate.lower())
        if existing is None:
            return candidate, True
        if existing.name == candidate and existing.is_file() and \
                hashlib.sha256(existing.read_bytes()).hexdigest() == digest:
            return candidate, False
    raise JobError(f"source/ already holds other files named {name!a} and {hashed!a}; "
                   "rename the mask")


def set_mask(folder: str | Path, mask: str | Path | None) -> dict:
    """Give the job an owner-corrected selection mask (or none, with None); return the job.

    The mask must be a black/white image of the source image's size (tdmg select's
    load_mask). It is copied into source/ (_mask_destination: earlier masks are kept,
    never overwritten), then source.mask and stages.select.mask are set and the revision
    bumped (save_job). The image, origin and generated fields do not change."""
    folder = Path(folder)
    check_not_linked(folder)
    job = load_job(folder)
    check_source(folder, job)
    if "select" not in job["stages"]:
        raise JobError(f"recipe {job['recipe']} has no select stage to use a mask")
    entry = None
    copy_to = None
    if mask is not None:
        image = folder / job["source"]["file"]
        try:
            intake = load_image(image)
        except SelectionError as e:
            raise JobError(f"source image: {e}") from None
        mask = Path(mask)
        data, digest = _read_mask(mask, intake.rgba.shape[:2], image.name)
        name, write = _mask_destination(folder / SOURCE_DIR, mask.name, digest)
        entry = {"file": f"{SOURCE_DIR}/{name}", "sha256": digest}
        copy_to = (folder / SOURCE_DIR / name, data) if write else None
    new = copy.deepcopy(job)
    new["source"]["mask"] = entry
    new["stages"]["select"]["mask"] = None if entry is None else entry["file"]
    validate_job(new)                       # refuse before copying anything
    if copy_to is not None:
        path, data = copy_to
        try:
            with open(path, "xb") as f:     # exclusive: never replaces a file
                f.write(data)
        except FileExistsError:
            raise JobError(f"{path} appeared while the mask was being set; try again"
                           ) from None
    return save_job(folder, new)


def new_job(jobs_dir: str | Path, name: str, output_class: str, image: str | Path, *,
            colors: bool = False, mask: str | Path | None = None,
            origin: str = DEFAULT_ORIGIN, generated: dict[str, str] | None = None,
            width_mm: float | None = None, thickness_mm: float | None = None) -> dict:
    """Make jobs_dir/name/ with the image (and mask) in source/ and job.yaml last; return
    the job.

    Refused, with nothing written: a bad name; an existing jobs_dir/name (a job, an
    incomplete job folder, a file, a link or junction); a class that resolve() refuses; an
    image that is missing or that tdmg select cannot read; a mask that is not a black/white
    image of the image's size; a source file name that is not plain (source_name_problem);
    generated fields for an origin other than generated; a width or thickness the stage
    would refuse (check_limits). width_mm and thickness_mm set the stage parameters that
    require them (required_stage), as floats; left out, they stay null (not set yet).
    Generated fields not given are "unknown"."""
    name = check_name(name)
    folder = Path(jobs_dir) / name
    if folder.is_symlink() or folder.is_junction():
        raise JobError(f"{folder} is a link (symlink or junction), not a job; remove it and "
                       "try again")
    if folder.is_dir() and not (folder / JOB_FILE).exists():
        raise JobError(f"incomplete job folder {folder} (no {JOB_FILE}); delete it and try "
                       "again")
    if folder.exists():
        raise JobError(f"job {name} already exists ({folder}); choose another name")
    try:
        r = resolve(output_class, colors)
    except ValueError as e:
        raise JobError(str(e)) from None
    if origin not in ORIGINS:
        raise JobError(f"origin must be one of {', '.join(ORIGINS)}, not {origin!a}")
    generated = dict(generated or {})
    unknown_fields = [k for k in generated if k not in GENERATED_FIELDS]
    if unknown_fields:
        raise JobError(f"unknown generated field {unknown_fields[0]!a}")
    given = [k for k, v in generated.items() if v is not None]
    if origin != "generated" and given:
        raise JobError(f"{given[0]} is for origin generated only (origin is {origin})")

    image = Path(image)
    data = _read_checked(image, "image")
    problem = source_name_problem(image.name)
    if problem:
        raise JobError(f"image {problem}")
    try:
        intake = load_image(image)
    except SelectionError as e:
        raise JobError(f"image: {e}") from None
    if intake.file_sha256 != hashlib.sha256(data).hexdigest():
        raise JobError(f"image {image} changed while it was read; try again")
    files = {f"{SOURCE_DIR}/{image.name}": data}
    source = {"file": f"{SOURCE_DIR}/{image.name}", "sha256": intake.file_sha256,
              "mask": None, "origin": origin}
    if mask is not None:
        mask = Path(mask)
        mdata, mdigest = _read_mask(mask, intake.rgba.shape[:2], image.name)
        files[f"{SOURCE_DIR}/{mask.name}"] = mdata
        source["mask"] = {"file": f"{SOURCE_DIR}/{mask.name}", "sha256": mdigest}
    if origin == "generated":
        for k in GENERATED_FIELDS:
            source[k] = UNKNOWN if generated.get(k) is None else generated[k]

    stages = default_stages(r.id)
    if "select" in stages:
        stages["select"]["mask"] = None if source["mask"] is None else source["mask"]["file"]
    for key, value in (("width_mm", width_mm), ("thickness_mm", thickness_mm)):
        if value is None:
            continue
        stage = required_stage(r.id, key)
        if stage is None:
            raise JobError(f"recipe {r.id} has no stage that needs {key}")
        problem = _number(value)
        if problem:
            raise JobError(f"{key} {problem}")
        # A float, as tdmg flat and tdmg colors receive it from the command line: the
        # records hash the number as JSON, where 60 and 60.0 differ.
        stages[stage][key] = float(value)
    job = validate_job({"schema": SCHEMA, "name": name, "class": output_class,
                        "recipe": r.id, "source": source, "stages": stages,
                        "confirmations": [], "revision": 1})
    check_limits(job)
    record = dump_job(job)
    try:
        write_outputs(folder, files, JOB_FILE, record, create_folder=True, subfolders=True)
    except RecordError as e:
        raise JobError(str(e)) from None
    except FileExistsError:
        raise JobError(f"cannot create {folder}: something is already there (a file, or a "
                       "broken link or junction); remove it and try again") from None
    return job

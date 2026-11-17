"""tdmg.jobs and `tdmg job new` (restructure plan Task 6)."""

import copy
import hashlib
import inspect
import re

import pytest
import yaml
from PIL import Image
from typer.testing import CliRunner

from tdmg import cli, jobs, paths
from tdmg.cli import app
from tdmg.color_config import KEYS as COLOR_KEYS
from tdmg.colored_flat import make_colored_flat
from tdmg.colors import make_colors
from tdmg.jobs import (
    GENERATED_FIELDS,
    JOB_FILE,
    STAGE_FIELDS,
    JobError,
    check_source,
    default_stages,
    dump_job,
    load_job,
    name_problem,
    new_job,
    parse_job,
    path_problem,
    save_job,
    unset_required,
    validate_job,
)
from tdmg.recipes import CLASSES, RECIPES

runner = CliRunner(env={"NO_COLOR": "1", "FORCE_COLOR": None, "COLUMNS": "200"})
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Output without escape codes, box-drawing characters or line breaks (as test_cli)."""
    text = ANSI.sub("", text)
    text = "".join(" " if 0x2500 <= ord(c) <= 0x257F else c for c in text)
    return " ".join(text.split())


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "in" / "roadie.png"
    path.parent.mkdir()
    Image.new("RGBA", (20, 10), (200, 30, 30, 255)).save(path)
    return path


@pytest.fixture
def mask(tmp_path):
    path = tmp_path / "in" / "mask.png"
    path.parent.mkdir(exist_ok=True)
    Image.new("L", (20, 10), 255).save(path)
    return path


def _jobs(tmp_path):
    return tmp_path / "jobs"


# --- names -----------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["a", "0", "roadie-drop", "strip-2026-11-16", "a-", "com0",
                                  "con1", "x" * 63])
def test_good_names(name):
    assert name_problem(name) is None


@pytest.mark.parametrize(("name", "reason"), [
    ("", "cannot be empty"),
    ("..", "holds '.'"),
    (".", "holds '.'"),
    ("a/b", "holds '/'"),
    ("a\\b", "holds '\\\\'"),
    ("C:x", "holds ':'"),
    ("CON", "uppercase"),
    ("Roadie", "uppercase"),
    ("con", "Windows reserves"),
    ("nul", "Windows reserves"),
    ("aux", "Windows reserves"),
    ("prn", "Windows reserves"),
    ("com1", "Windows reserves"),
    ("lpt9", "Windows reserves"),
    ("-a", "starts with a hyphen"),
    ("a_b", "holds '_'"),
    ("a b", "holds ' '"),
    ("a\n", "holds '\\n'"),
    ("caf\u00e9", "holds '\\xe9'"),
    ("x" * 64, "the most is 63"),
])
def test_bad_names_are_refused_with_a_reason(name, reason):
    problem = name_problem(name)
    assert problem is not None and reason in problem


def test_a_name_must_be_text():
    assert "must be text" in name_problem(3)


@pytest.mark.parametrize(("value", "reason"), [
    ("/abs/x.png", "absolute"),
    ("C:/x.png", "':'"),
    ("c:x.png", "':'"),
    ("source\\x.png", "backslash"),
    ("source/../x.png", "'..'"),
    ("../x.png", "'..'"),
    ("./x.png", "'.'"),
    ("source//x.png", "empty"),
    ("source/con.png", "Windows reserves"),
    ("source/x\tz.png", "control character"),
    ("", "not empty"),
    (3, "not int"),
])
def test_bad_paths(value, reason):
    assert reason in path_problem(value)


def test_good_path():
    assert path_problem("source/roadie.png") is None


# --- job new -----------------------------------------------------------------------------

def test_new_single_color_job(tmp_path, image):
    job = new_job(_jobs(tmp_path), "roadie", "flat-icon", image)
    folder = _jobs(tmp_path) / "roadie"
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")) == [
        "job.yaml", "source", "source/roadie.png"]
    assert (folder / "source" / "roadie.png").read_bytes() == image.read_bytes()
    assert job["recipe"] == "R1" and job["class"] == "flat-icon"
    assert job["revision"] == 1 and job["confirmations"] == []
    assert job["source"] == {"file": "source/roadie.png", "mask": None, "origin": "unknown",
                             "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}
    assert list(job["stages"]) == ["select", "flat", "slice"]
    assert "face" not in job["stages"]["slice"]      # tdmg slice refuses --face for R1
    assert unset_required(job) == ["flat.width_mm", "flat.thickness_mm"]
    assert load_job(folder) == job


def test_new_multicolor_job_places_width_and_thickness(tmp_path, image):
    job = new_job(_jobs(tmp_path), "roadie-drop", "flat-icon", image, colors=True,
                  width_mm=60, thickness_mm=3.0)
    assert job["recipe"] == "R2"
    assert list(job["stages"]) == ["select", "colors", "colored_flat", "slice"]
    assert job["stages"]["colors"]["width_mm"] == 60
    assert job["stages"]["colored_flat"]["thickness_mm"] == 3.0
    assert job["stages"]["colored_flat"]["width_mm"] is None    # the plan's width
    assert job["stages"]["slice"]["face"] is None               # tdmg slice's default
    assert unset_required(job) == []


def test_r1_width_and_thickness_go_to_flat(tmp_path, image):
    job = new_job(_jobs(tmp_path), "r", "flat-icon", image, width_mm=60.0, thickness_mm=3.0)
    assert job["stages"]["flat"]["width_mm"] == 60.0
    assert job["stages"]["flat"]["thickness_mm"] == 3.0
    assert unset_required(job) == []


def test_the_mask_is_part_of_the_source(tmp_path, image, mask):
    job = new_job(_jobs(tmp_path), "r", "flat-icon", image, mask=mask)
    assert job["source"]["mask"] == {
        "file": "source/mask.png", "sha256": hashlib.sha256(mask.read_bytes()).hexdigest()}
    assert job["stages"]["select"]["mask"] == "source/mask.png"
    assert (_jobs(tmp_path) / "r" / "source" / "mask.png").read_bytes() == mask.read_bytes()
    check_source(_jobs(tmp_path) / "r", job)


def test_generated_origin_fields_default_to_unknown(tmp_path, image):
    job = new_job(_jobs(tmp_path), "g", "flat-icon", image, origin="generated",
                  generated={"prompt": "a red bird on a disc", "generator": "Gemini"})
    src = job["source"]
    assert src["prompt"] == "a red bird on a disc" and src["generator"] == "Gemini"
    for field in ("version", "settings", "references", "chosen", "edits"):
        assert src[field] == "unknown"
    assert set(src) == {"file", "sha256", "mask", "origin", *GENERATED_FIELDS}


@pytest.mark.parametrize("origin", ["photo", "drawing", "unknown"])
def test_other_origins_have_no_generated_fields(tmp_path, image, origin):
    job = new_job(_jobs(tmp_path), "o", "flat-icon", image, origin=origin)
    assert set(job["source"]) == {"file", "sha256", "mask", "origin"}
    with pytest.raises(JobError, match="for origin generated only"):
        new_job(_jobs(tmp_path), "o2", "flat-icon", image, origin=origin,
                generated={"prompt": "x"})


def test_generated_field_cannot_be_empty(tmp_path, image):
    with pytest.raises(JobError, match="write unknown"):
        new_job(_jobs(tmp_path), "g", "flat-icon", image, origin="generated",
                generated={"prompt": ""})
    assert not _jobs(tmp_path).exists()


def test_unknown_origin_is_refused(tmp_path, image):
    with pytest.raises(JobError, match="origin must be one of"):
        new_job(_jobs(tmp_path), "g", "flat-icon", image, origin="scan")


def _refused(tmp_path, match, *args, **kwargs):
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(JobError, match=match):
        new_job(*args, **kwargs)
    assert sorted(tmp_path.rglob("*")) == before        # nothing written


def test_refuses_an_existing_job(tmp_path, image):
    new_job(_jobs(tmp_path), "r", "flat-icon", image)
    data = (_jobs(tmp_path) / "r" / JOB_FILE).read_bytes()
    _refused(tmp_path, "already exists", _jobs(tmp_path), "r", "flat-icon", image,
             colors=True)
    assert (_jobs(tmp_path) / "r" / JOB_FILE).read_bytes() == data


def test_refuses_an_existing_file_of_that_name(tmp_path, image):
    _jobs(tmp_path).mkdir()
    (_jobs(tmp_path) / "r").write_text("x")
    _refused(tmp_path, "already exists", _jobs(tmp_path), "r", "flat-icon", image)


@pytest.mark.parametrize("name", ["..", "a/b", "CON", "con", "Roadie", "x" * 64])
def test_refuses_bad_names(tmp_path, image, name):
    _refused(tmp_path, "job name", _jobs(tmp_path), name, "flat-icon", image)


@pytest.mark.parametrize(("cls", "colors", "match"), [
    ("figurine", False, "figurine' is planned"),
    ("flexi", True, "flexi' is planned"),
    ("statue", False, "unknown output class"),
])
def test_refuses_a_class_not_ready(tmp_path, image, cls, colors, match):
    _refused(tmp_path, match, _jobs(tmp_path), "r", cls, image, colors=colors)


def test_refuses_a_missing_image(tmp_path):
    _refused(tmp_path, "does not exist", _jobs(tmp_path), "r", "flat-icon",
             tmp_path / "nope.png")


def test_refuses_a_folder_as_image(tmp_path):
    (tmp_path / "d.png").mkdir()
    _refused(tmp_path, "is not a file", _jobs(tmp_path), "r", "flat-icon", tmp_path / "d.png")


def test_refuses_a_file_that_is_not_an_image(tmp_path):
    bad = tmp_path / "notes.png"
    bad.write_text("not an image")
    _refused(tmp_path, "not a readable image", _jobs(tmp_path), "r", "flat-icon", bad)


def test_refuses_an_image_name_that_is_not_plain(tmp_path, image):
    spaced = tmp_path / "IMG 1234.png"
    spaced.write_bytes(image.read_bytes())
    _refused(tmp_path, "not a plain portable name", _jobs(tmp_path), "r", "flat-icon", spaced)


def test_refuses_a_mask_of_another_size(tmp_path, image):
    small = tmp_path / "small.png"
    Image.new("L", (5, 5), 255).save(small)
    _refused(tmp_path, "mask: mask size", _jobs(tmp_path), "r", "flat-icon", image, mask=small)


def test_refuses_a_mask_that_is_not_black_and_white(tmp_path, image):
    grey = tmp_path / "grey.png"
    Image.new("L", (20, 10), 128).save(grey)
    _refused(tmp_path, "only 0 and 255", _jobs(tmp_path), "r", "flat-icon", image, mask=grey)


def test_refuses_a_mask_with_the_image_name(tmp_path, image):
    other = tmp_path / "ROADIE.png"
    Image.new("L", (20, 10), 255).save(other)
    _refused(tmp_path, "both named", _jobs(tmp_path), "r", "flat-icon", image, mask=other)


# --- canonical YAML, round trip and byte identity ---------------------------------------

def test_same_inputs_give_the_same_bytes(tmp_path, image, mask):
    kw = {"colors": True, "mask": mask, "origin": "generated",
          "generated": {"prompt": "bird"}, "width_mm": 60.0}
    new_job(tmp_path / "a", "r", "flat-icon", image, **kw)
    new_job(tmp_path / "b", "r", "flat-icon", image, **kw)
    data = (tmp_path / "a" / "r" / JOB_FILE).read_bytes()
    assert data == (tmp_path / "b" / "r" / JOB_FILE).read_bytes()
    assert dump_job(parse_job(data)) == data        # a rewrite gives the same bytes
    assert data.isascii() and b"\r" not in data
    assert data.startswith(b"class: flat-icon\nconfirmations: []\n")


@pytest.mark.parametrize("text", [
    "unknown", "yes", "no", "null", "~", "1.0", "2026-11-16", " lead", "trail ", "a\nb",
    "a\r\nb", "x\x85y", "x\u2028y", "tab\tx", "caf\u00e9 \u65e5\u672c", "#c", "a: b", "- x",
    "'q'", '"d"', "\ufeffbom", "x" * 300 + " y" * 200, "\x00", "\x1b[0m", "<<", "&a", "*a",
])
def test_awkward_text_round_trips(tmp_path, image, text):
    job = new_job(_jobs(tmp_path), "g", "flat-icon", image, origin="generated",
                  generated={"prompt": text, "edits": text})
    data = (_jobs(tmp_path) / "g" / JOB_FILE).read_bytes()
    back = load_job(_jobs(tmp_path) / "g")
    assert back == job and back["source"]["prompt"] == text
    assert dump_job(back) == data


def test_text_that_utf8_cannot_store_is_refused(tmp_path, image):
    _refused(tmp_path, "UTF-8", _jobs(tmp_path), "g", "flat-icon", image, origin="generated",
             generated={"prompt": "bad \ud800"})


def test_sizes_are_written_as_floats_and_numbers_keep_their_type(tmp_path, image):
    # As the CLI passes them: the stage records hash 60 and 60.0 differently.
    new_job(_jobs(tmp_path), "r", "flat-icon", image, width_mm=60, thickness_mm=3)
    job = load_job(_jobs(tmp_path) / "r")
    assert type(job["stages"]["flat"]["width_mm"]) is float
    assert b"width_mm: 60.0\n" in (_jobs(tmp_path) / "r" / JOB_FILE).read_bytes()
    # A hand-edited integer is read back as an integer, not changed.
    job["stages"]["flat"]["width_mm"] = 60
    assert type(parse_job(dump_job(job))["stages"]["flat"]["width_mm"]) is int


# --- save_job and the revision ----------------------------------------------------------

def test_save_bumps_the_revision_and_is_byte_stable(tmp_path, image):
    folder = _jobs(tmp_path) / "r"
    job = new_job(_jobs(tmp_path), "r", "flat-icon", image)
    changed = copy.deepcopy(job)
    changed["stages"]["flat"]["width_mm"] = 60.0
    saved = save_job(folder, changed)
    assert saved["revision"] == 2 and load_job(folder) == saved
    data = (folder / JOB_FILE).read_bytes()
    assert save_job(folder, copy.deepcopy(saved)) == saved      # no change: no bump
    assert (folder / JOB_FILE).read_bytes() == data
    assert sorted(p.name for p in folder.iterdir()) == ["job.yaml", "source"]   # no .tmp


def test_save_refuses_an_old_revision(tmp_path, image):
    folder = _jobs(tmp_path) / "r"
    job = new_job(_jobs(tmp_path), "r", "flat-icon", image)
    first = copy.deepcopy(job)
    first["stages"]["flat"]["width_mm"] = 60.0
    save_job(folder, first)
    stale = copy.deepcopy(job)
    stale["stages"]["flat"]["width_mm"] = 50.0
    with pytest.raises(JobError, match="at revision 2, not 1"):
        save_job(folder, stale)


@pytest.mark.parametrize(("key", "value"), [("class", "figurine"), ("recipe", "R2"),
                                            ("name", "other")])
def test_save_refuses_fixed_changes(tmp_path, image, key, value):
    job = new_job(_jobs(tmp_path), "r", "flat-icon", image)
    job[key] = value
    with pytest.raises(JobError):
        save_job(_jobs(tmp_path) / "r", job)


def test_save_refuses_a_source_change(tmp_path, image):
    job = new_job(_jobs(tmp_path), "r", "flat-icon", image)
    job["source"]["origin"] = "photo"
    with pytest.raises(JobError, match="source cannot change"):
        save_job(_jobs(tmp_path) / "r", job)


def test_save_refuses_an_invalid_change(tmp_path, image):
    folder = _jobs(tmp_path) / "r"
    job = new_job(_jobs(tmp_path), "r", "flat-icon", image)
    data = (folder / JOB_FILE).read_bytes()
    job["stages"]["flat"]["width_mm"] = "60"
    with pytest.raises(JobError, match="must be a number"):
        save_job(folder, job)
    assert (folder / JOB_FILE).read_bytes() == data


def test_check_source_finds_a_changed_or_missing_file(tmp_path, image):
    folder = _jobs(tmp_path) / "r"
    job = new_job(_jobs(tmp_path), "r", "flat-icon", image)
    (folder / "source" / "roadie.png").write_bytes(b"other")
    with pytest.raises(JobError, match="has changed"):
        check_source(folder, job)
    (folder / "source" / "roadie.png").unlink()
    with pytest.raises(JobError, match="is missing"):
        check_source(folder, job)


# --- strict reading ----------------------------------------------------------------------

@pytest.fixture
def base(tmp_path, image):
    return new_job(_jobs(tmp_path), "r", "flat-icon", image, colors=True)


def _set(job, path, value):
    job = copy.deepcopy(job)
    *parents, last = path.split(".")
    node = job
    for key in parents:
        node = node[key]
    node[last] = value
    return job


def _drop(job, path):
    job = copy.deepcopy(job)
    *parents, last = path.split(".")
    node = job
    for key in parents:
        node = node[key]
    del node[last]
    return job


@pytest.mark.parametrize(("path", "value", "match"), [
    ("extra", 1, "unknown key 'extra'"),
    ("schema", "tdmg.job/2", "this tdmg reads tdmg.job/1"),
    ("name", "Roadie", "uppercase"),
    ("class", "statue", "not an output class"),
    ("recipe", "R1x", "not in class"),
    ("recipe", "R4", "not in class"),
    ("revision", 0, "at least 1"),
    ("revision", "1", "revision must be"),
    ("revision", True, "revision must be"),
    ("confirmations", {}, "must be a list"),
    ("confirmations", [{"subject": "print"}], "cannot record or read"),
    ("source", [], "source must be a mapping"),
    ("source.extra", 1, "unknown key 'extra'"),
    ("source.prompt", "x", "for origin generated only"),
    ("source.origin", "scan", "must be one of"),
    ("source.file", "/abs/roadie.png", "absolute"),
    ("source.file", "C:/roadie.png", "':'"),
    ("source.file", "source\\roadie.png", "backslash"),
    ("source.file", "source/../roadie.png", "'..'"),
    ("source.file", "other/roadie.png", "must be source/<file name>"),
    ("source.file", "source/a/roadie.png", "must be source/<file name>"),
    ("source.sha256", "ABC", "SHA-256"),
    ("source.mask", {"file": "source/m.png"}, "missing key 'sha256'"),
    ("stages.extra", {}, "unknown key 'extra'"),
    ("stages.colors.extra", 1, "unknown key 'extra'"),
    ("stages.colors.width_mm", "60", "must be a number"),
    ("stages.colors.width_mm", True, "must be a number"),
    ("stages.colors.width_mm", float("nan"), "finite"),
    ("stages.colors.colors", 2.0, "valid integer"),
    ("stages.colors.edges", "fuzzy", "smooth"),
    ("stages.colors.merge", [[1, 1]], "merge"),
    ("stages.select.remove_at", [[1, 2, 3]], "two integers"),
    ("stages.select.remove_at", None, "must be a list"),
    ("stages.select.alpha_min", 1.5, "must be an integer"),
    ("stages.select.instructions", 5, "must be text"),
    ("stages.select.mask", "source/mask.png", "must be the same"),
    ("stages.slice.face", "sideways", "must be one of"),
    ("stages.slice.skip_tree_check", None, "true or false"),
    ("stages.slice.skip_tree_check", "no", "true or false"),
])
def test_strict_validation(base, path, value, match):
    with pytest.raises(JobError, match=re.escape(match)):
        validate_job(_set(base, path, value))


@pytest.mark.parametrize("path", ["schema", "revision", "source.sha256", "source.mask",
                                  "stages.slice", "stages.colors.merge",
                                  "stages.select.mask"])
def test_missing_keys_are_refused(base, path):
    with pytest.raises(JobError, match="missing key"):
        validate_job(_drop(base, path))


def test_generated_job_needs_every_generated_field(tmp_path, image):
    job = new_job(_jobs(tmp_path), "g", "flat-icon", image, origin="generated")
    with pytest.raises(JobError, match="missing key 'edits'"):
        validate_job(_drop(job, "source.edits"))


def test_single_color_slice_has_no_face(tmp_path, image):
    job = new_job(_jobs(tmp_path), "s", "flat-icon", image)
    with pytest.raises(JobError, match="unknown key 'face'"):
        validate_job(_set(job, "stages.slice.face", None))


def _write(tmp_path, text):
    folder = tmp_path / "hand" / "r"
    folder.mkdir(parents=True)
    (folder / JOB_FILE).write_bytes(text.encode("utf-8"))
    return folder


@pytest.mark.parametrize(("edit", "match"), [
    (lambda t: t.replace("revision: 1", "revision: 1\nrevision: 2"), "duplicate key"),
    (lambda t: t.replace("  colored_flat:\n", "  colored_flat: &a\n").replace(
        "  slice:\n", "  slice: *a\n  x:\n"), "anchors and aliases"),
    (lambda t: t.replace("confirmations: []", "confirmations: &x []"), "anchors and aliases"),
    (lambda t: t.replace("stages:\n", "stages:\n  <<: {}\n"), "merge keys"),
    (lambda t: t.replace("revision: 1", "? [a]\n: 1"), "plain name"),
    (lambda t: t.replace("revision: 1", "revision: !!python/int 1"), "not valid YAML"),
    (lambda t: t + "---\n" + t, "not valid YAML"),
    (lambda t: t.replace("skip_tree_check: false", "skip_tree_check: 2026-11-16"),
     "true or false"),
    (lambda t: t.replace("name: r", "name: other"), "but its folder is 'r'"),
])
def test_hand_edits_are_read_strictly(tmp_path, base, edit, match):
    folder = _write(tmp_path, edit(dump_job(base).decode()))
    with pytest.raises(JobError, match=re.escape(match)):
        load_job(folder)


def test_a_hand_edit_in_another_layout_is_accepted(tmp_path, base):
    # Strict about content, not layout: flow style and other key order read the same.
    text = yaml.safe_dump(base, sort_keys=False, default_flow_style=True)
    assert load_job(_write(tmp_path, text)) == base


def test_not_utf8_is_refused(tmp_path):
    folder = tmp_path / "r"
    folder.mkdir()
    (folder / JOB_FILE).write_bytes(b"name: \xff\n")
    with pytest.raises(JobError, match="not UTF-8"):
        load_job(folder)


def test_a_folder_without_job_yaml(tmp_path):
    with pytest.raises(JobError, match="no job.yaml"):
        load_job(tmp_path)


# --- the stage parameters are the stage commands' options, at their defaults --------------

def _defaults(fn, skip=()):
    return {name: p.default for name, p in inspect.signature(fn).parameters.items()
            if name not in skip}


def test_select_parameters_are_tdmg_selects_options():
    cli_opts = _defaults(cli.select, skip=("image", "out"))
    assert set(STAGE_FIELDS["select"]) == set(cli_opts)
    stages = default_stages("R1")["select"]
    for key, default in cli_opts.items():
        expected = [] if key in ("remove_at", "keep_at") else default
        assert default is None and stages[key] == expected


def test_flat_parameters_are_tdmg_flats_options():
    cli_opts = _defaults(cli.flat, skip=("ctx", "selection", "out", "colors_dir"))
    assert set(STAGE_FIELDS["flat"]) == set(cli_opts)
    stages = default_stages("R1")["flat"]
    for key, default in cli_opts.items():
        assert stages[key] is None
        # width_mm and thickness_mm have no default: required (CLI: required options).
        assert STAGE_FIELDS["flat"][key].required == (key in ("width_mm", "thickness_mm"))
        assert default is None or default is inspect.Parameter.empty


def test_colors_parameters_are_make_colors_flags():
    assert set(STAGE_FIELDS["colors"]) == {"width_mm", *COLOR_KEYS}
    assert inspect.signature(make_colors).parameters["width_mm"].default is \
        inspect.Parameter.empty
    assert STAGE_FIELDS["colors"]["width_mm"].required
    assert all(v is None for k, v in default_stages("R2")["colors"].items())


def test_colored_flat_parameters_are_make_colored_flats_options():
    opts = _defaults(make_colored_flat, skip=("selection_dir", "colors_dir", "out_dir",
                                              "smooth_px"))
    assert set(STAGE_FIELDS["colored_flat"]) == set(opts)
    stages = default_stages("R2")["colored_flat"]
    for key, default in opts.items():
        assert stages[key] is None
        assert STAGE_FIELDS["colored_flat"][key].required == (default is
                                                               inspect.Parameter.empty)


def test_slice_parameters_are_tdmg_slices_options():
    opts = _defaults(cli.slice_, skip=("flat_dir", "out", "slicer_dir", "prusaslicer_dir"))
    assert set(STAGE_FIELDS["slice"]) == set(opts)
    assert default_stages("R2")["slice"] == opts
    assert default_stages("R1")["slice"] == {k: v for k, v in opts.items() if k != "face"}


def test_every_usable_recipes_stages_have_parameters():
    for r in RECIPES:
        if r.stages:
            assert set(default_stages(r.id)) == set(r.stages)


def test_no_required_parameter_has_a_default():
    for fields in STAGE_FIELDS.values():
        for f in fields.values():
            assert not (f.required and f.default is not None)


# --- the jobs folder ----------------------------------------------------------------------

def test_default_jobs_dir_in_a_checkout(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "REPO_ROOT", tmp_path)
    assert jobs.default_jobs_dir() == tmp_path / "jobs"


def test_no_default_jobs_dir_outside_a_checkout(monkeypatch):
    monkeypatch.setattr(paths, "REPO_ROOT", None)
    with pytest.raises(JobError, match="give --jobs-dir"):
        jobs.default_jobs_dir()


# --- the CLI ----------------------------------------------------------------------------

def _new(tmp_path, *args):
    return runner.invoke(app, ["job", "new", *args, "--jobs-dir", str(_jobs(tmp_path))],
                         prog_name="tdmg")


def test_cli_job_new(tmp_path, image, mask):
    r = _new(tmp_path, "roadie-drop", "--class", "flat-icon", "--colors", "--image",
             str(image), "--mask", str(mask), "--origin", "generated", "--prompt", "a bird",
             "--generator", "Gemini", "--generator-version", "3", "--settings", "s",
             "--references", "none", "--chosen", "2 of 4", "--edits", "none",
             "--width-mm", "60")
    assert r.exit_code == 0, r.output
    folder = _jobs(tmp_path) / "roadie-drop"
    job = load_job(folder)
    assert job == new_job(tmp_path / "api", "roadie-drop", "flat-icon", image, colors=True,
                          mask=mask, origin="generated", width_mm=60.0,
                          generated={"prompt": "a bird", "generator": "Gemini",
                                     "version": "3", "settings": "s", "references": "none",
                                     "chosen": "2 of 4", "edits": "none"})
    assert (folder / JOB_FILE).read_bytes() == \
        (tmp_path / "api" / "roadie-drop" / JOB_FILE).read_bytes()
    assert r.stdout.splitlines() == [
        "job roadie-drop: class flat-icon, recipe R2 (Flat multicolor)",
        "stages: select, colors, colored_flat, slice",
        "source: source/roadie.png (origin generated)",
        "mask: source/mask.png",
        "not set yet (needed before those stages run): colored_flat.thickness_mm",
        f"wrote {folder / JOB_FILE}",
    ]


@pytest.mark.parametrize(("args", "match"), [
    (["..", "--class", "flat-icon"], "error: job name '..' holds '.'"),
    (["a/b", "--class", "flat-icon"], "holds '/'"),
    (["CON", "--class", "flat-icon"], "uppercase"),
    (["r", "--class", "figurine"], "error: output class 'figurine' is planned"),
    (["r", "--class", "flat-icon", "--prompt", "x"], "prompt is for origin generated only"),
    (["r", "--class", "flat-icon", "--origin", "scan"], "origin must be one of"),
])
def test_cli_refusals(tmp_path, image, args, match):
    r = _new(tmp_path, *args, "--image", str(image))
    assert r.exit_code == 2
    assert match in _plain(r.stderr)
    assert not _jobs(tmp_path).exists()


def test_cli_refuses_an_existing_job(tmp_path, image):
    assert _new(tmp_path, "r", "--class", "flat-icon", "--image", str(image)).exit_code == 0
    r = _new(tmp_path, "r", "--class", "flat-icon", "--image", str(image))
    assert r.exit_code == 2 and "already exists" in _plain(r.stderr)


def test_cli_refuses_a_missing_image(tmp_path):
    r = _new(tmp_path, "r", "--class", "flat-icon", "--image", str(tmp_path / "x.png"))
    assert r.exit_code == 2 and "does not exist" in _plain(r.stderr)


def test_cli_needs_jobs_dir_outside_a_checkout(tmp_path, image, monkeypatch):
    monkeypatch.setattr(paths, "REPO_ROOT", None)
    r = runner.invoke(app, ["job", "new", "r", "--class", "flat-icon", "--image", str(image)])
    assert r.exit_code == 2 and "give --jobs-dir" in _plain(r.stderr)


def test_cli_job_new_help():
    text = _plain(runner.invoke(app, ["job", "new", "--help"], prog_name="tdmg").output)
    for option in ("--class", "--image", "--colors", "--mask", "--origin", "--prompt",
                   "--generator", "--generator-version", "--settings", "--references",
                   "--chosen", "--edits", "--width-mm", "--thickness-mm", "--jobs-dir"):
        assert option in text
    assert "photo, drawing, generated, unknown" in text
    assert ", ".join(CLASSES) in text
    assert text.isascii()
    assert "job run" not in text

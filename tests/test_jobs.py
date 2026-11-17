"""tdmg.jobs and `tdmg job new` (restructure plan Task 6)."""

import copy
import hashlib
import inspect
import re
import subprocess
import sys

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
    set_mask,
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


def test_refuses_an_incomplete_job_folder(tmp_path, image):
    (_jobs(tmp_path) / "r" / "source").mkdir(parents=True)
    _refused(tmp_path, re.escape("(no job.yaml); delete it and try again"),
             _jobs(tmp_path), "r", "flat-icon", image)


def test_refuses_a_symlink(tmp_path, image):
    _jobs(tmp_path).mkdir()
    try:
        (_jobs(tmp_path) / "r").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    except OSError:
        pytest.skip("this account cannot create symlinks")
    _refused(tmp_path, "is a link", _jobs(tmp_path), "r", "flat-icon", image)


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")
@pytest.mark.parametrize("broken", [False, True])
def test_refuses_a_junction(tmp_path, image, broken):
    target = tmp_path / "target"
    target.mkdir()
    _jobs(tmp_path).mkdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(_jobs(tmp_path) / "r"), str(target)],
                   check=True, capture_output=True)
    if broken:
        target.rmdir()
    _refused(tmp_path, "is a link", _jobs(tmp_path), "r", "flat-icon", image)


def test_a_broken_entry_at_mkdir_gives_a_clear_message(tmp_path, image, monkeypatch):
    def fail(*a, **k):
        raise FileExistsError(17, "exists")
    monkeypatch.setattr(jobs, "write_outputs", fail)
    with pytest.raises(JobError, match="something is already there"):
        new_job(_jobs(tmp_path), "r", "flat-icon", image)


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
    # Floats in YAML 1.1 need a signed exponent, so the dumper writes these unquoted.
    "1.0e5", "0.0e0", "1e5", "-2.5E10", "1.0e+5", "60", "60.0", "true",
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


def test_sizes_are_written_as_floats(tmp_path, image):
    # As the CLI passes them: the stage records hash 60 and 60.0 differently.
    new_job(_jobs(tmp_path), "r", "flat-icon", image, width_mm=60, thickness_mm=3)
    job = load_job(_jobs(tmp_path) / "r")
    assert type(job["stages"]["flat"]["width_mm"]) is float
    assert b"width_mm: 60.0\n" in (_jobs(tmp_path) / "r" / JOB_FILE).read_bytes()


REAL_PARAMS = [("select", "tolerance"), ("colors", "width_mm"),
               ("colors", "outline_width_mm"), ("colored_flat", "thickness_mm"),
               ("colored_flat", "width_mm"), ("slice", "timeout_s")]


@pytest.mark.parametrize(("stage", "key"), REAL_PARAMS)
def test_a_hand_written_integer_in_a_float_parameter_is_read_as_a_float(base, stage, key):
    text = dump_job(base).decode()
    start = text.index(f"  {stage}:\n")
    line = text.index(f"    {key}: null\n", start)
    edited = text[:line] + f"    {key}: 7\n" + text[line + len(f"    {key}: null\n"):]
    job = parse_job(edited.encode())
    value = job["stages"][stage][key]
    assert value == 7.0 and type(value) is float
    assert f"    {key}: 7.0\n" in dump_job(job).decode()


def test_float_parameters_are_the_cli_float_options():
    # Every option the stage commands take as a float (and colors' float key) is real.
    want = {("flat", "width_mm"), ("flat", "thickness_mm"), ("flat", "smooth_px"),
            *REAL_PARAMS}
    real = {(stage, key) for stage, fields in STAGE_FIELDS.items()
            for key, f in fields.items() if f.real}
    assert real == want
    for fn, stage in ((cli.select, "select"), (cli.flat, "flat"), (cli.slice_, "slice")):
        for name, param in inspect.signature(fn).parameters.items():
            if name in STAGE_FIELDS[stage]:
                floaty = param.annotation.__origin__ in (float, float | None)
                assert STAGE_FIELDS[stage][name].real == floaty, (stage, name)


def test_integer_parameters_stay_integers(base):
    job = validate_job(_set(base, "stages.select.alpha_min", 200))
    assert type(job["stages"]["select"]["alpha_min"]) is int


def test_a_huge_integer_is_refused_not_raised(base):
    with pytest.raises(JobError, match="too large"):
        validate_job(_set(base, "stages.colors.width_mm", 10 ** 400))


def test_a_huge_size_at_job_new_is_refused(tmp_path, image):
    _refused(tmp_path, "too large", _jobs(tmp_path), "r", "flat-icon", image,
             width_mm=10 ** 400)


@pytest.mark.parametrize(("colors", "kw", "match"), [
    (False, {"width_mm": 0}, "stages.flat.width_mm: width_mm must be a finite number above 0"),
    (False, {"thickness_mm": -3}, "stages.flat.thickness_mm: thickness_mm must be"),
    (True, {"width_mm": -1}, "stages.colors.width_mm: width_mm must be a finite number"),
    (True, {"thickness_mm": 0}, "stages.colored_flat.thickness_mm: thickness_mm must be"),
    (False, {"width_mm": float("inf")}, "finite"),
])
def test_job_new_refuses_sizes_the_stage_would_refuse(tmp_path, image, colors, kw, match):
    _refused(tmp_path, re.escape(match), _jobs(tmp_path), "r", "flat-icon", image,
             colors=colors, **kw)


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


@pytest.mark.parametrize(("key", "value"), [("origin", "photo"), ("file", "source/x.png"),
                                            ("sha256", "0" * 64)])
def test_save_refuses_a_source_change(tmp_path, image, key, value):
    job = new_job(_jobs(tmp_path), "r", "flat-icon", image)
    job["source"][key] = value
    with pytest.raises(JobError, match="source cannot change"):
        save_job(_jobs(tmp_path) / "r", job)


def test_save_refuses_a_generated_field_change(tmp_path, image):
    job = new_job(_jobs(tmp_path), "r", "flat-icon", image, origin="generated")
    job["source"]["prompt"] = "something else"
    with pytest.raises(JobError, match="source cannot change"):
        save_job(_jobs(tmp_path) / "r", job)


def test_real_floats_still_round_trip_as_numbers(base):
    for value in (1e-05, 1e20, 5e-324, 0.1 + 0.2, -0.0, 123456789012345678.0):
        job = parse_job(dump_job(_set(base, "stages.colored_flat.width_mm", value)))
        assert job["stages"]["colored_flat"]["width_mm"] == value


@pytest.mark.parametrize(("path", "value", "match"), [
    ("stages.colored_flat.width_mm", 0.0, "width_mm must be a finite number above 0"),
    ("stages.colored_flat.thickness_mm", -1.0, "thickness_mm must be a finite number"),
    ("stages.colors.width_mm", 0.0, "width_mm must be a finite number above 0"),
])
def test_save_runs_the_stage_limits(tmp_path, base, path, value, match):
    folder = _jobs(tmp_path) / "r"
    data = (folder / JOB_FILE).read_bytes()
    with pytest.raises(JobError, match=re.escape(match)):
        save_job(folder, _set(base, path, value))
    assert (folder / JOB_FILE).read_bytes() == data


def test_save_runs_flats_smooth_px_limit(tmp_path, image):
    folder = _jobs(tmp_path) / "s"
    job = new_job(_jobs(tmp_path), "s", "flat-icon", image)
    with pytest.raises(JobError, match="smooth_px must be 0"):
        save_job(folder, _set(job, "stages.flat.smooth_px", -1.0))
    assert save_job(folder, _set(job, "stages.flat.smooth_px", 0.0))["revision"] == 2


def test_save_refuses_a_mask_that_is_not_a_mask_of_the_image(tmp_path, image):
    # A mask change made without set_mask: the file is there with its hash, but it is not
    # a black/white image of the source image's size.
    folder = _jobs(tmp_path) / "r"
    job = new_job(_jobs(tmp_path), "r", "flat-icon", image)
    small = folder / "source" / "small.png"
    Image.new("L", (5, 5), 255).save(small)
    job["source"]["mask"] = {"file": "source/small.png",
                             "sha256": hashlib.sha256(small.read_bytes()).hexdigest()}
    job["stages"]["select"]["mask"] = "source/small.png"
    with pytest.raises(JobError, match="mask size"):
        save_job(folder, job)


def test_save_accepts_a_good_mask_placed_by_hand(tmp_path, image, mask):
    folder = _jobs(tmp_path) / "r"
    job = new_job(_jobs(tmp_path), "r", "flat-icon", image)
    placed = folder / "source" / "hand.png"
    placed.write_bytes(mask.read_bytes())
    job["source"]["mask"] = {"file": "source/hand.png",
                             "sha256": hashlib.sha256(placed.read_bytes()).hexdigest()}
    job["stages"]["select"]["mask"] = "source/hand.png"
    assert save_job(folder, job)["revision"] == 2


def _junction(link, target):
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True,
                   capture_output=True)


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")
def test_set_mask_and_save_refuse_a_junction_source_folder(tmp_path, image, mask):
    folder = _jobs(tmp_path) / "r"
    job = new_job(_jobs(tmp_path), "r", "flat-icon", image)
    real = tmp_path / "real-source"
    (folder / "source").rename(real)
    _junction(folder / "source", real)
    with pytest.raises(JobError, match="is a link"):
        set_mask(folder, mask)
    with pytest.raises(JobError, match="is a link"):
        save_job(folder, _set(job, "stages.flat.width_mm", 60.0))
    assert sorted(p.name for p in real.iterdir()) == ["roadie.png"]


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")
def test_set_mask_and_save_refuse_a_junction_job_folder(tmp_path, image, mask):
    job = new_job(tmp_path / "elsewhere", "r", "flat-icon", image)
    _jobs(tmp_path).mkdir()
    _junction(_jobs(tmp_path) / "r", tmp_path / "elsewhere" / "r")
    with pytest.raises(JobError, match="is a link"):
        set_mask(_jobs(tmp_path) / "r", mask)
    with pytest.raises(JobError, match="is a link"):
        save_job(_jobs(tmp_path) / "r", _set(job, "stages.flat.width_mm", 60.0))


def test_save_refuses_a_mask_whose_file_is_not_there(tmp_path, image):
    job = new_job(_jobs(tmp_path), "r", "flat-icon", image)
    job["source"]["mask"] = {"file": "source/mask.png", "sha256": "0" * 64}
    job["stages"]["select"]["mask"] = "source/mask.png"
    with pytest.raises(JobError, match="is missing"):
        save_job(_jobs(tmp_path) / "r", job)


# --- set_mask --------------------------------------------------------------------------

def _mask_file(tmp_path, name, value=255, size=(20, 10)):
    path = tmp_path / "masks" / name
    path.parent.mkdir(exist_ok=True)
    im = Image.new("L", size, 0)
    im.paste(value, (0, 0, 10, 10))
    im.save(path)
    return path


def test_set_mask_after_job_new(tmp_path, image):
    folder = _jobs(tmp_path) / "r"
    new_job(_jobs(tmp_path), "r", "flat-icon", image, colors=True, origin="generated",
            generated={"prompt": "p"})
    before = load_job(folder)
    m = _mask_file(tmp_path, "mask.png")
    job = set_mask(folder, m)
    digest = hashlib.sha256(m.read_bytes()).hexdigest()
    assert job["revision"] == 2
    assert job["source"]["mask"] == {"file": "source/mask.png", "sha256": digest}
    assert job["stages"]["select"]["mask"] == "source/mask.png"
    for key in ("file", "sha256", "origin", *GENERATED_FIELDS):
        assert job["source"][key] == before["source"][key]
    assert load_job(folder) == job
    check_source(folder, job)


def test_set_mask_keeps_earlier_masks_and_never_overwrites(tmp_path, image, mask):
    folder = _jobs(tmp_path) / "r"
    new_job(_jobs(tmp_path), "r", "flat-icon", image, mask=mask)
    first = (folder / "source" / "mask.png").read_bytes()
    corrected = _mask_file(tmp_path, "mask.png", value=0)       # same name, other pixels
    job = set_mask(folder, corrected)
    digest = hashlib.sha256(corrected.read_bytes()).hexdigest()
    assert job["source"]["mask"]["file"] == f"source/mask-{digest[:12]}.png"
    assert (folder / "source" / "mask.png").read_bytes() == first     # kept as it was
    assert (folder / job["source"]["mask"]["file"]).read_bytes() == corrected.read_bytes()
    # The first mask again: its file is reused, not copied.
    again = set_mask(folder, mask)
    assert again["source"]["mask"]["file"] == "source/mask.png" and again["revision"] == 3
    assert sorted(p.name for p in (folder / "source").iterdir()) == [
        "mask-" + digest[:12] + ".png", "mask.png", "roadie.png"]


def test_set_mask_none_removes_it_but_keeps_the_file(tmp_path, image, mask):
    folder = _jobs(tmp_path) / "r"
    new_job(_jobs(tmp_path), "r", "flat-icon", image, mask=mask)
    job = set_mask(folder, None)
    assert job["source"]["mask"] is None and job["stages"]["select"]["mask"] is None
    assert (folder / "source" / "mask.png").exists()


def test_set_the_same_mask_twice_changes_nothing(tmp_path, image, mask):
    folder = _jobs(tmp_path) / "r"
    new_job(_jobs(tmp_path), "r", "flat-icon", image, mask=mask)
    data = (folder / JOB_FILE).read_bytes()
    assert set_mask(folder, mask)["revision"] == 1
    assert (folder / JOB_FILE).read_bytes() == data


@pytest.mark.parametrize(("make", "match"), [
    (lambda t: _mask_file(t, "small.png", size=(5, 5)), "mask size"),
    (lambda t: _mask_file(t, "grey.png", value=128), "only 0 and 255"),
    (lambda t: _mask_file(t, "ROADIE.png"), "both named"),
    (lambda t: _mask_file(t, "con.png"), "Windows reserves"),
    (lambda t: t / "nope.png", "does not exist"),
])
def test_set_mask_refusals_change_nothing(tmp_path, image, make, match):
    folder = _jobs(tmp_path) / "r"
    new_job(_jobs(tmp_path), "r", "flat-icon", image)
    before = sorted(p.relative_to(folder) for p in folder.rglob("*"))
    data = (folder / JOB_FILE).read_bytes()
    with pytest.raises(JobError, match=match):
        set_mask(folder, make(tmp_path))
    assert sorted(p.relative_to(folder) for p in folder.rglob("*")) == before
    assert (folder / JOB_FILE).read_bytes() == data


def test_set_mask_refuses_when_the_image_changed(tmp_path, image, mask):
    folder = _jobs(tmp_path) / "r"
    new_job(_jobs(tmp_path), "r", "flat-icon", image)
    (folder / "source" / "roadie.png").write_bytes(b"other")
    with pytest.raises(JobError, match="has changed"):
        set_mask(folder, mask)


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


def test_source_missing_keys_come_before_values(base):
    broken = _drop(_set(base, "source.sha256", "bad"), "source.origin")
    with pytest.raises(JobError, match="source: missing key 'origin'"):
        validate_job(broken)
    with pytest.raises(JobError, match="source: unknown key 'colour'"):
        validate_job(_set(_drop(base, "source.file"), "source.colour", 1))


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
    (lambda t: t.replace("revision: 1", "revision: !!python/int 1"), "explicit tags"),
    (lambda t: t.replace("revision: 1", "revision: !!int 1"), "explicit tags"),
    (lambda t: t.replace("name: r", "name: !!str r"), "explicit tags"),
    (lambda t: t.replace("stages:\n", "stages: !!map\n"), "explicit tags"),
    (lambda t: t.replace("confirmations: []", "confirmations: !foo []"), "explicit tags"),
    # YAML 1.1 forms that SafeLoader would read as numbers or booleans are text here.
    (lambda t: t.replace("revision: 1", "revision: 0:01"), "revision must be"),
    (lambda t: t.replace("revision: 1", "revision: 01"), "revision must be"),
    (lambda t: t.replace("revision: 1", "revision: 0x1"), "revision must be"),
    (lambda t: t.replace("revision: 1", "revision: 0o1"), "revision must be"),
    (lambda t: t.replace("revision: 1", "revision: 0b1"), "revision must be"),
    (lambda t: t.replace("revision: 1", "revision: 1_0"), "revision must be"),
    (lambda t: t.replace("revision: 1", "revision: +1"), "revision must be"),
    (lambda t: t.replace("    width_mm: null", "    width_mm: 1:30", 1), "must be a number"),
    (lambda t: t.replace("    width_mm: null", "    width_mm: 010", 1), "must be a number"),
    (lambda t: t.replace("    width_mm: null", "    width_mm: 1_000.0", 1), "must be a number"),
    (lambda t: t.replace("    width_mm: null", "    width_mm: 60.", 1), "must be a number"),
    (lambda t: t.replace("    width_mm: null", "    width_mm: 6e1", 1), "must be a number"),
    (lambda t: t.replace("    width_mm: null", "    width_mm: 6.0e1", 1), "must be a number"),
    (lambda t: t.replace("    width_mm: null", "    width_mm: .inf", 1), "must be a number"),
    (lambda t: t.replace("skip_tree_check: false", "skip_tree_check: no"), "true or false"),
    (lambda t: t.replace("skip_tree_check: false", "skip_tree_check: False"),
     "true or false"),
    (lambda t: t.replace("skip_tree_check: false", "skip_tree_check: off"), "true or false"),
    (lambda t: t.replace("    face: null", "    face: Null"), "must be one of"),
    (lambda t: t + "---\n" + t, "not valid YAML"),
    (lambda t: t.replace("skip_tree_check: false", "skip_tree_check: 2026-11-16"),
     "true or false"),
    (lambda t: t.replace("name: r", "name: other"), "but its folder is 'r'"),
])
def test_hand_edits_are_read_strictly(tmp_path, base, edit, match):
    folder = _write(tmp_path, edit(dump_job(base).decode()))
    with pytest.raises(JobError, match=re.escape(match)):
        load_job(folder)


def test_yaml_11_forms_in_text_stay_text(tmp_path, image):
    job = new_job(_jobs(tmp_path), "g", "flat-icon", image, origin="generated")
    text = dump_job(job).decode().replace("prompt: unknown", "prompt: 1:30").replace(
        "edits: unknown", "edits: yes")
    back = parse_job(text.encode())
    assert back["source"]["prompt"] == "1:30" and back["source"]["edits"] == "yes"


@pytest.mark.parametrize("text", ["60.0", "-0.5", "0.1", "1.0e+20", "1.0e-05", "5.0e-324",
                                  "1.5E+3"])
def test_plain_decimal_floats_are_numbers(base, text):
    data = dump_job(base).decode().replace("    width_mm: null", f"    width_mm: {text}", 1)
    assert parse_job(data.encode())["stages"]["colored_flat"]["width_mm"] == float(text)


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

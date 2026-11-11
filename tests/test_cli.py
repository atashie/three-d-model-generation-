import json
import re

import numpy as np
import pytest
from PIL import Image
from selection_fixtures import roadie_like
from typer.testing import CliRunner

import tdmg.flat
from tdmg import __version__
from tdmg.cli import app
from tdmg.rules import load_rules
from tdmg.selection import SelectionError

# Under GITHUB_ACTIONS, Rich styles usage errors with escape codes and a box even when
# NO_COLOR is set; that split usage-error text and failed CI on 2026-11-10 (run
# 42834453852). Wide output plus _plain() makes the assertions environment-independent.
runner = CliRunner(env={"NO_COLOR": "1", "FORCE_COLOR": None, "COLUMNS": "200"})
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Output without escape codes, box-drawing characters or line breaks."""
    text = ANSI.sub("", text)
    text = "".join(" " if 0x2500 <= ord(c) <= 0x257F else c for c in text)
    return " ".join(text.split())


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0 and __version__ in result.output


def test_rules_lists_every_rule():
    from tdmg.rules import load_rules

    result = runner.invoke(app, ["rules"])
    assert result.exit_code == 0
    for rule_id in load_rules():
        assert rule_id in result.output


def test_recipes_and_printers():
    assert "R1" in runner.invoke(app, ["recipes"]).output
    out = runner.invoke(app, ["printers"]).output
    assert "bambu-a1" in out and "up to 4 filaments" in out


def _img(tmp_path, rgba, name="in.png"):
    p = tmp_path / name
    Image.fromarray(rgba).save(p)
    return p


def test_select_writes_a_reviewable_selection(tmp_path):
    img = _img(tmp_path, roadie_like(), "roadie_like.png")
    out = tmp_path / "sel"
    result = runner.invoke(app, ["select", str(img), "--out", str(out),
                                 "--instructions", "Use only the bird.",
                                 "--remove-at", "30,100", "--keep-at", "100,80"])
    assert result.exit_code == 0, result.output
    assert "one_piece" in result.output and "preview.png" in result.output
    rec = json.loads((out / "selection.json").read_text(encoding="utf-8"))
    assert rec["selection_id"] in result.output
    assert rec["input"]["name"] == "roadie_like.png"
    assert rec["interpretation"]["text"] == "Use only the bird."
    with Image.open(out / "mask.png") as im:
        assert np.asarray(im).max() == 255


def test_select_reports_os_errors_without_a_traceback(tmp_path):
    img = _img(tmp_path, roadie_like())
    (tmp_path / "file.txt").write_text("not a folder")
    out = tmp_path / "file.txt" / "sel"
    r = runner.invoke(app, ["select", str(img), "--out", str(out)])
    assert r.exit_code == 2, r.output
    assert r.stderr.startswith("error: ") and "file.txt" in r.stderr
    assert "another run" not in r.stderr
    assert "Traceback" not in r.output and isinstance(r.exception, SystemExit)


def test_select_rejects_bad_points(tmp_path):
    img = _img(tmp_path, np.zeros((4, 4, 4), np.uint8), "e.png")
    bad = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "o"),
                              "--remove-at", "a,b"])
    assert bad.exit_code == 2 and "--remove-at expects X,Y" in _plain(bad.output)
    assert not (tmp_path / "o").exists()
    three = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "o1"),
                                "--keep-at", "1,2,3"])
    assert three.exit_code == 2 and "--keep-at expects X,Y" in _plain(three.output)
    off = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "o2"),
                              "--keep-at", "9,9"])
    assert off.exit_code == 2 and "outside" in off.output
    assert not (tmp_path / "o2").exists()


def test_select_rejects_out_of_range_alpha(tmp_path):
    img = _img(tmp_path, np.zeros((4, 4, 4), np.uint8), "e.png")
    r = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "o"), "--alpha-min", "0"])
    assert r.exit_code == 2 and "alpha_min" in r.output
    assert not (tmp_path / "o").exists()


def test_select_rejects_tolerance_without_remove_at(tmp_path):
    img = _img(tmp_path, roadie_like())
    r = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "o"),
                            "--tolerance", "20"])
    assert r.exit_code == 2 and "color_tolerance" in r.output
    assert not (tmp_path / "o").exists()


def test_select_rejects_an_unreadable_image(tmp_path):
    img = tmp_path / "notes.png"
    img.write_text("not an image")
    r = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "o")])
    assert r.exit_code == 2 and "not a readable image" in r.output
    assert "Traceback" not in r.output and not isinstance(r.exception, SelectionError)


def test_select_refuses_a_non_empty_out_folder(tmp_path):
    img = _img(tmp_path, roadie_like())
    (tmp_path / "o").mkdir()
    (tmp_path / "o" / "keep.txt").write_text("mine")
    r = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "o")])
    assert r.exit_code == 2 and "not empty" in r.output
    assert [p.name for p in (tmp_path / "o").iterdir()] == ["keep.txt"]


def test_select_mask_round_trip(tmp_path):
    img = _img(tmp_path, roadie_like())
    first = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "a"),
                                "--remove-at", "30,100", "--keep-at", "100,80"])
    assert first.exit_code == 0, first.output
    again = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "b"),
                                "--mask", str(tmp_path / "a" / "mask.png")])
    assert again.exit_code == 0, again.output
    a = json.loads((tmp_path / "a" / "selection.json").read_text(encoding="utf-8"))
    b = json.loads((tmp_path / "b" / "selection.json").read_text(encoding="utf-8"))
    assert b["mask_pixels_sha256"] == a["mask_pixels_sha256"]
    assert b["controls"]["source"] == "user_mask" and a["controls"]["source"] == "controls"
    assert b["selection_id"] != a["selection_id"]


def test_select_mask_refuses_points(tmp_path):
    img = _img(tmp_path, roadie_like())
    first = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "a")])
    assert first.exit_code == 0, first.output
    r = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "b"),
                            "--mask", str(tmp_path / "a" / "mask.png"), "--keep-at", "100,80"])
    assert r.exit_code == 2 and "not both" in r.output


def test_select_rejects_a_non_finite_tolerance(tmp_path):
    img = _img(tmp_path, roadie_like())
    r = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "o"),
                            "--remove-at", "30,100", "--tolerance", "nan"])
    assert r.exit_code == 2 and "color_tolerance" in r.output and "finite" in r.output
    assert not (tmp_path / "o").exists()


def test_select_refuses_an_oversized_image(tmp_path, monkeypatch):
    img = _img(tmp_path, roadie_like())
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    r = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "o")])
    assert r.exit_code == 2 and "safety limit" in r.stderr
    assert isinstance(r.exception, SystemExit) and not (tmp_path / "o").exists()


# --- tdmg flat ---------------------------------------------------------------------


def _selection(tmp_path):
    img = _img(tmp_path, roadie_like(), "roadie_like.png")
    sel = tmp_path / "sel"
    r = runner.invoke(app, ["select", str(img), "--out", str(sel), "--remove-at", "30,100",
                            "--keep-at", "100,80"])
    assert r.exit_code == 0, r.output
    return sel


def _flat(sel, out, *extra):
    return runner.invoke(app, ["flat", str(sel), "--width-mm", "60", "--thickness-mm", "3",
                               "--out", str(out), *extra])


def test_flat_writes_outputs_and_reports_the_verdict(tmp_path):
    out = tmp_path / "flat"
    r = _flat(_selection(tmp_path), out)
    assert r.exit_code == 0, r.output
    record = json.loads((out / "flat.json").read_bytes())
    assert sorted(p.name for p in out.iterdir()) == ["flat.json", "model.stl", "outline.png"]
    text = r.stdout
    assert "verdict NOT CERTIFIED" in text
    f3 = next(c for c in record["checks"] if c["id"] == "F3.thin_regions")
    measured = f3["measured"]
    assert (f"F3.thin_regions UNKNOWN - measured area_mm2={measured['area_mm2']:.4g}, "
            f"min_width_mm=0.9, pieces={measured['pieces']}; threshold 0.9: "
            "tapered tips always appear") in text
    assert ("F6.slicer UNKNOWN: not measured here: tdmg slice runs the pinned slicer and "
            "the F6 checks") in text
    assert "F1." not in text                        # passing checks are not listed
    x, y, z = record["mesh"]["extents_mm"]
    assert f"{x:.2f} x {y:.2f} x {z:.2f} mm" in text
    assert f"{record['mesh']['triangles']} triangles, 1 body" in text
    assert f"flat_id {record['flat_id']}" in text
    assert str(out / "model.stl") in text
    assert (f"{out / 'outline.png'} - open outline.png to check what smoothing and cleaning "
            "changed") in text
    assert f"wrote {out / 'flat.json'}" in text
    smoothing, scale = record["smoothing"], record["transform"]["scale_mm_per_px"]
    moved = smoothing["hausdorff_lower_bound_px"] * scale
    removed = smoothing["removed_area_px2"] * scale ** 2
    added = smoothing["added_area_px2"] * scale ** 2
    assert (f"smoothing sigma 2.5 px (rule flat.smooth.sigma_px): outline changed by at "
            f"least {moved:.3g} mm (sampled; boundary-to-region), area -{removed:.3g}/"
            f"+{added:.3g} mm^2\n") in text
    assert record["warnings"] == [] and r.stderr == ""


def test_flat_without_width_is_a_usage_error(tmp_path):
    r = runner.invoke(app, ["flat", str(_selection(tmp_path)), "--thickness-mm", "3",
                            "--out", str(tmp_path / "flat")])
    assert r.exit_code == 2
    assert "Missing option '--width-mm'" in _plain(r.output)
    assert not (tmp_path / "flat").exists()


def test_flat_zero_thickness_exits_2_and_writes_nothing(tmp_path):
    sel = _selection(tmp_path)
    r = runner.invoke(app, ["flat", str(sel), "--width-mm", "60", "--thickness-mm", "0",
                            "--out", str(tmp_path / "flat")])
    assert r.exit_code == 2, r.output
    assert r.stderr.startswith("error: thickness_mm")
    assert "Traceback" not in r.output and isinstance(r.exception, SystemExit)
    assert not (tmp_path / "flat").exists()


def test_flat_on_a_non_selection_folder_exits_2(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    r = _flat(other, tmp_path / "flat")
    assert r.exit_code == 2, r.output
    assert r.stderr.startswith("error: ") and "selection.json" in r.stderr
    assert not (tmp_path / "flat").exists()


def test_flat_exits_1_when_a_check_fails_but_still_writes(tmp_path, monkeypatch):
    sel = _selection(tmp_path)
    rules = load_rules()
    rule_id = "slicer.orca.max_triangles_per_plate"
    rules[rule_id] = rules[rule_id].model_copy(update={"default": 4})
    # make_flat calls load_rules through tdmg.flat's module-level import, so patching
    # the name in tdmg.flat changes the rules it sees (tdmg.rules is untouched).
    monkeypatch.setattr("tdmg.flat.load_rules", lambda: rules)
    out = tmp_path / "flat"
    r = _flat(sel, out)
    assert r.exit_code == 1, r.output
    triangles = json.loads((out / "flat.json").read_bytes())["mesh"]["triangles"]
    assert f"  F5.triangles FAIL - measured {triangles}; threshold 4\n" in r.stdout
    assert sorted(p.name for p in out.iterdir()) == ["flat.json", "model.stl", "outline.png"]


def test_flat_reports_os_errors_without_a_traceback(tmp_path):
    sel = _selection(tmp_path)
    (tmp_path / "file.txt").write_text("not a folder")
    r = _flat(sel, tmp_path / "file.txt" / "flat")
    assert r.exit_code == 2, r.output
    assert r.stderr.startswith("error: ") and "file.txt" in r.stderr
    assert "Traceback" not in r.output and isinstance(r.exception, SystemExit)


def test_flat_help_documents_exit_codes():
    text = _plain(runner.invoke(app, ["flat", "--help"], prog_name="tdmg").output)
    for option in ("--width-mm", "--thickness-mm", "--out", "--printer", "--smooth-px"):
        assert option in text
    assert ("Gaussian smoothing of the outline in image pixels; default from rule "
            "flat.smooth.sigma_px; 0 keeps the exact pixel outline") in text
    # Typer 0.28 puts braces round a required argument's metavar, as for select's {image}.
    assert "Usage: tdmg flat [OPTIONS] {SELECTION_DIR}" in text
    assert EXIT_LINES[-1] == ("Exit 0 does not mean the part is certified; read verdict in "
                              "flat.json.")
    assert " ".join(EXIT_LINES) in text


EXIT_LINES = (
    "Exit codes:",
    "0 files written, and no check FAILed (UNKNOWN checks allowed)",
    "1 files written, and at least one check FAILed",
    "2 input or usage error: nothing is written; or an I/O failure",
    "while writing, which can leave a folder without flat.json:",
    "such a folder is incomplete and must not be used",
    "Exit 0 does not mean the part is certified; read verdict in flat.json.",
)


def test_flat_help_keeps_the_exit_code_list_intact_at_80_columns():
    # Each exit-code line must come out as one rendered line, not re-wrapped or joined.
    narrow = CliRunner(env={"NO_COLOR": "1", "FORCE_COLOR": None, "COLUMNS": "80"})
    lines = [" ".join(ANSI.sub("", line).split())
             for line in narrow.invoke(app, ["flat", "--help"]).output.splitlines()]
    start = lines.index(EXIT_LINES[0])
    assert lines[start:start + len(EXIT_LINES)] == list(EXIT_LINES)


def test_flat_exits_1_when_the_export_differs_from_the_geometry(tmp_path, monkeypatch):
    sel = _selection(tmp_path)
    encode = tdmg.flat._encode_stl
    monkeypatch.setattr(tdmg.flat, "_encode_stl", lambda mesh: encode(
        mesh.copy().apply_scale(0.1)))
    out = tmp_path / "flat"
    r = _flat(sel, out)
    assert r.exit_code == 1, r.output
    assert "F2.export_matches_geometry FAIL" in r.stdout
    assert sorted(p.name for p in out.iterdir()) == ["flat.json", "model.stl", "outline.png"]


def test_flat_smooth_px_0_turns_smoothing_off(tmp_path):
    out = tmp_path / "flat"
    r = _flat(_selection(tmp_path), out, "--smooth-px", "0")
    assert r.exit_code == 0, r.output
    record = json.loads((out / "flat.json").read_bytes())
    assert record["smoothing"]["applied"] is False
    assert "smoothing off\n" in r.stdout


def test_flat_explicit_smooth_px_is_used(tmp_path):
    out = tmp_path / "flat"
    r = _flat(_selection(tmp_path), out, "--smooth-px", "1.5")
    assert r.exit_code == 0, r.output
    record = json.loads((out / "flat.json").read_bytes())
    assert record["smoothing"]["sigma_px"] == {"value": 1.5, "rule": None}
    assert ("smoothing sigma 1.5 px (set by --smooth-px): outline changed by at least "
            in r.stdout)


@pytest.mark.parametrize("value", ["-1", "nan", "inf"])
def test_flat_bad_smooth_px_exits_2_and_writes_nothing(tmp_path, value):
    out = tmp_path / "flat"
    r = _flat(_selection(tmp_path), out, "--smooth-px", value)
    assert r.exit_code == 2, r.output
    assert r.stderr.startswith("error: smooth_px")
    assert "Traceback" not in r.output and isinstance(r.exception, SystemExit)
    assert not out.exists()


def test_flat_prints_smoothing_warnings_to_stderr_and_still_exits_0(tmp_path):
    rgba = np.zeros((70, 60, 4), np.uint8)
    rgba[10:50, 10:50] = (230, 20, 20, 255)
    rgba[60:63, 15:45] = (230, 20, 20, 255)     # a 3 px stroke that smoothing removes
    img = _img(tmp_path, rgba, "stroke.png")
    sel = tmp_path / "sel"
    r = runner.invoke(app, ["select", str(img), "--out", str(sel), "--keep-at", "20,20",
                            "--keep-at", "20,61"])
    assert r.exit_code == 0, r.output
    out = tmp_path / "flat"
    r = runner.invoke(app, ["flat", str(sel), "--width-mm", "20", "--thickness-mm", "2",
                            "--out", str(out)])
    assert r.exit_code == 0, r.output
    record = json.loads((out / "flat.json").read_bytes())
    assert len(record["warnings"]) == 1                 # the stroke disappeared
    assert r.stderr == "".join(f"warning: {w}\n" for w in record["warnings"])


# --- tdmg colors ----------------------------------------------------------------------

def _colors(sel, out, *extra):
    return runner.invoke(app, ["colors", str(sel), "--width-mm", "60", "--out", str(out),
                               *extra])


def test_colors_writes_outputs_and_prints_the_palette(tmp_path):
    out = tmp_path / "colors"
    r = _colors(_selection(tmp_path), out)
    assert r.exit_code == 0, r.output
    assert sorted(p.name for p in out.iterdir()) == ["colors.json", "labels.png",
                                                    "regions.png"]
    rec = json.loads((out / "colors.json").read_bytes())
    text = _plain(r.stdout)
    n = len(rec["palette"])
    assert f"palette: {n} colors (at most 4), edges smooth" in text
    assert f"extracted: {n} colors (asked 6)" in text
    for e in rec["extraction"]["palette"]:
        assert (f"{e['index']} {e['hex']} {e['share']:6.1%}  final {e['final_index']}"
                in r.stdout)
    assert "NOT READY" not in text
    for p in rec["palette"]:
        line = f"{p['index']} {p['hex']} {p['share']:6.1%}"
        assert " ".join(line.split()) + (" base" if p["base"] else "") in text
    assert f"colors_id {rec['colors_id']}" in text
    assert f"wrote {out / 'labels.png'}" in text
    assert (f"wrote {out / 'regions.png'} - open regions.png to check the colors before "
            "building geometry") in text
    assert f"wrote {out / 'colors.json'}" in text
    assert r.stderr == ""


def test_colors_flags_and_config(tmp_path):
    sel = _selection(tmp_path)
    cfg = tmp_path / "c.yaml"
    cfg.write_bytes(b"colors: 3\nedges: furry\noutlines: keep\noutline_color: none\n"
                    b"merge: [[2, 0]]\n")
    out = tmp_path / "colors"
    r = _colors(sel, out, "--config", str(cfg), "--colors", "2", "--base", "auto",
                "--extract", "3", "--outlines", "drop")
    assert r.exit_code == 0, r.output
    rec = json.loads((out / "colors.json").read_bytes())
    assert rec["settings"]["settings"] == {
        "colors": 2, "extract": 3, "edges": "furry", "base": "auto", "outlines": "drop",
        "outline_color": "none", "merge": [[2, 0]]}
    assert rec["settings"]["sources"] == {
        "colors": "flag", "extract": "flag", "edges": "config", "base": "flag",
        "outlines": "flag", "outline_color": "config", "merge": "config"}
    m = rec["merges"][0]
    assert f"merged: 2 {m['from_hex']} into 0 {m['into_hex']}" in _plain(r.stdout)
    assert "edges furry" in _plain(r.stdout)


def test_colors_numeric_base(tmp_path):
    out = tmp_path / "colors"
    r = _colors(_selection(tmp_path), out, "--colors", "2", "--extract", "2", "--base", "1")
    assert r.exit_code == 0, r.output
    assert json.loads((out / "colors.json").read_bytes())["base_index"] == 1


@pytest.mark.parametrize("extra, message", [
    (("--colors", "9"), "colors: must be between 2 and 4"),
    (("--edges", "fuzzy"), "edges"),
    (("--base", "7"), "base 7 is not a color index"),
    (("--config", "missing.yaml"), "cannot read config file"),
    (("--extract", "3"), "extract 3 is below colors 4"),
    (("--extract", "1"), "extract: must be between 2 and 254"),
    (("--outlines", "hide"), "outlines"),
])
def test_colors_bad_settings_exit_2_and_write_nothing(tmp_path, extra, message):
    out = tmp_path / "colors"
    r = _colors(_selection(tmp_path), out, *extra)
    assert r.exit_code == 2, r.output
    assert r.stderr.startswith("error: ") and message in _plain(r.stderr)
    assert "Traceback" not in r.output and isinstance(r.exception, SystemExit)
    assert not out.exists()


def test_colors_bad_base_text_is_a_usage_error(tmp_path):
    r = _colors(_selection(tmp_path), tmp_path / "colors", "--base", "red")
    assert r.exit_code == 2
    assert "--base expects auto or a color index, got 'red'" in _plain(r.output)
    assert not (tmp_path / "colors").exists()


def _not_a_selection(sel, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    return other


def _bad_mask(sel, tmp_path):
    (sel / "mask.png").write_bytes((sel / "preview.png").read_bytes())
    return sel


@pytest.mark.parametrize("make_input, width, message", [
    (lambda sel, tmp_path: sel, "0", "error: width_mm"),
    (lambda sel, tmp_path: sel, "nan", "error: width_mm"),
    (_not_a_selection, "60", "selection.json"),
    (_bad_mask, "60", "mask.png"),
])
def test_colors_bad_width_or_input_exits_2_and_writes_nothing(tmp_path, make_input, width,
                                                              message):
    source = make_input(_selection(tmp_path), tmp_path)
    out = tmp_path / "colors"
    r = runner.invoke(app, ["colors", str(source), "--width-mm", width, "--out", str(out)])
    assert r.exit_code == 2, r.output
    assert r.stderr.startswith("error: ") and message in r.stderr
    assert "Traceback" not in r.output and isinstance(r.exception, SystemExit)
    assert not out.exists()


def test_colors_refuses_a_non_empty_out_folder(tmp_path):
    out = tmp_path / "colors"
    out.mkdir()
    (out / "x.txt").write_text("x")
    r = _colors(_selection(tmp_path), out)
    assert r.exit_code == 2 and "not empty" in r.stderr
    assert sorted(p.name for p in out.iterdir()) == ["x.txt"]


def test_colors_reports_os_errors_without_a_traceback(tmp_path):
    sel = _selection(tmp_path)
    (tmp_path / "file.txt").write_text("not a folder")
    r = _colors(sel, tmp_path / "file.txt" / "colors")
    assert r.exit_code == 2, r.output
    assert r.stderr.startswith("error: ") and "file.txt" in r.stderr
    assert "Traceback" not in r.output and isinstance(r.exception, SystemExit)


def test_colors_help(tmp_path):
    text = _plain(runner.invoke(app, ["colors", "--help"], prog_name="tdmg").output)
    for option in ("--width-mm", "--out", "--colors", "--extract", "--edges", "--base",
                   "--outlines", "--config"):
        assert option in text
    assert "--outline-color" not in text and "--merge" not in text   # config file only
    assert "outline_color and merge (by extraction index) are set in this file only" in text
    assert "Usage: tdmg colors [OPTIONS] {SELECTION_DIR}" in text
    assert "1 files written, but the plan is not ready" in text


def test_colors_without_width_is_a_usage_error(tmp_path):
    r = runner.invoke(app, ["colors", str(_selection(tmp_path)), "--out",
                            str(tmp_path / "colors")])
    assert r.exit_code == 2
    assert "Missing option '--width-mm'" in _plain(r.output)


def test_colors_not_ready_writes_the_files_and_exits_1(tmp_path):
    # The test selection has 3 distinct colors; at most 2 are allowed and nothing is merged.
    out = tmp_path / "colors"
    sel = _selection(tmp_path)
    r = _colors(sel, out, "--colors", "2")
    assert r.exit_code == 1, r.output
    assert sorted(p.name for p in out.iterdir()) == ["colors.json", "labels.png",
                                                    "regions.png"]
    rec = json.loads((out / "colors.json").read_bytes())
    assert rec["ready"] is False
    assert f"NOT READY: {rec['not_ready_reason']}" in r.stdout
    assert "this plan cannot be built" in r.stdout
    assert "Traceback" not in r.output and isinstance(r.exception, SystemExit)
    # With one merge it is ready.
    cfg = tmp_path / "merge.yaml"
    cfg.write_bytes(b"merge: [[2, 0]]\n")
    r = _colors(sel, tmp_path / "merged", "--colors", "2", "--config", str(cfg))
    assert r.exit_code == 0, r.output
    assert "NOT READY" not in r.stdout

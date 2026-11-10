import json

import numpy as np
from PIL import Image
from selection_fixtures import roadie_like
from typer.testing import CliRunner

from tdmg import __version__
from tdmg.cli import app
from tdmg.selection import SelectionError

runner = CliRunner()


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
    assert bad.exit_code == 2 and "--remove-at expects X,Y" in bad.output
    assert not (tmp_path / "o").exists()
    three = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "o1"),
                                "--keep-at", "1,2,3"])
    assert three.exit_code == 2 and "--keep-at expects X,Y" in three.output
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

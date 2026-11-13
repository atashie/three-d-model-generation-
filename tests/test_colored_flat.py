"""tdmg.colored_flat.make_colored_flat and `tdmg flat --colors`
(docs/plans/2026-11-12-color-geometry.md, Decisions 1, 2, 9, 10 and Task 6)."""

import hashlib
import inspect
import io
import json
import re
import shutil
import zipfile

import numpy as np
import pytest
import shapely
import trimesh
from lxml import etree
from PIL import Image
from selection_fixtures import roadie_like
from typer.testing import CliRunner

import tdmg.colored_flat as cf
from tdmg.checks import CheckResult, merge_exact
from tdmg.cli import app
from tdmg.colored_flat import (
    BORDER_PX,
    COLORED_REQUIRED_CHECKS,
    GLUE_ONLY_CHECKS,
    RECORD_NAME,
    ColoredFlatError,
    body_file,
    colorflat_id,
    colorflat_identity,
    label_boxes,
    make_colored_flat,
    number_label,
    paint_cells,
)
from tdmg.colors import (
    MARGIN_PX,
    PREVIEW_SCALE,
    ROW_PX,
    STRIP_BACKGROUND,
    STRIP_TEXT,
    SWATCH_PX,
    background,
    make_colors,
)
from tdmg.flat import FlatError
from tdmg.profiles import load_printer
from tdmg.rules import load_rules
from tdmg.selection import (
    Intake,
    SelectionSpec,
    pixels_sha256,
    read_selection,
    select_subject,
    write_selection,
)

RULES = load_rules()
A1 = load_printer("bambu-a1")
SKIN = RULES["color.skin.depth_mm"].default
NO_FLAGS = {"colors": None, "edges": None, "base": None}
P = PREVIEW_SCALE
runner = CliRunner(env={"NO_COLOR": "1", "FORCE_COLOR": None, "COLUMNS": "200"})
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Output without escape codes, box-drawing characters or line breaks (test_cli)."""
    text = ANSI.sub("", text)
    text = "".join(" " if 0x2500 <= ord(c) <= 0x257F else c for c in text)
    return " ".join(text.split())


def write_sel(folder, rgba=None, spec=None):
    rgba = roadie_like() if rgba is None else rgba
    intake = Intake(rgba, "f" * 64, pixels_sha256(rgba), False, "x.png")
    write_selection(intake, select_subject(intake, spec or SelectionSpec()), folder)
    return folder


def write_plan(sel, out, **flags):
    return make_colors(sel, out, width_mm=60.0, flags={**NO_FLAGS, **flags},
                       config_path=None, rules=RULES, printer=A1)


def five_stripes() -> np.ndarray:
    """Five flat colors in vertical stripes (tests/test_colors.py): with --colors 4 and
    exact edges the plan is not ready."""
    rgba = np.zeros((80, 120, 4), np.uint8)
    x = 10
    for rgb, width in [((200, 30, 30), 30), ((30, 30, 200), 25), ((30, 200, 30), 20),
                       ((240, 240, 240), 15), ((20, 20, 20), 10)]:
        rgba[10:70, x:x + width] = (*rgb, 255)
        x += width
    return rgba


@pytest.fixture(scope="module")
def plan(tmp_path_factory):
    root = tmp_path_factory.mktemp("plan")
    sel = write_sel(root / "sel")
    rec = write_plan(sel, root / "colors")
    assert rec["ready"] is True
    return sel, root / "colors", rec


@pytest.fixture(scope="module")
def made(plan, tmp_path_factory):
    """One run, with the gated STL bytes and the glue geometry captured on the way."""
    sel, colors, _ = plan
    captured = {}

    def capture(name, fn):
        def wrapped(*a, **kw):
            result = fn(*a, **kw)
            captured[name] = result
            return result
        return wrapped

    out = tmp_path_factory.mktemp("made") / "out"
    with pytest.MonkeyPatch.context() as mp:
        for name in ("ams_checks", "glue_checks", "glue_geometry", "color_cells"):
            mp.setattr(cf, name, capture(name, getattr(cf, name)))
        rec = make_colored_flat(sel, colors, out, thickness_mm=3.0)
    return rec, out, captured, sel


# --- refusals ------------------------------------------------------------------------


def _tampered(colors, tmp_path):
    d = tmp_path / "tampered"
    shutil.copytree(colors, d)
    record = json.loads((d / "colors.json").read_bytes())
    record["identity"]["width_mm"] = 61.0
    (d / "colors.json").write_bytes(json.dumps(record).encode())
    return d


@pytest.mark.parametrize("case, message", [
    ("tampered", "colors_id"),
    ("other_selection", "was made from another selection"),
    ("width", "width_mm 59.0 differs from the plan's width_mm 60.0"),
    ("width_close", "width_mm 60.0000001 differs from the plan's width_mm 60.0"),
    ("printer", "differs from the plan's printer 'bambu-a1'"),
    ("smooth", "--smooth-px cannot be used with --colors"),
    ("smooth_default", "--smooth-px cannot be used with --colors"),
    ("thin", rf"thickness_mm \({SKIN:g}\) must be above the skin depth {SKIN:g} mm"),
    ("thinner", r"thickness_mm \(0.5\) must be above the skin depth"),
    ("zero", "thickness_mm must be a finite number above 0"),
])
def test_refusals_write_nothing(plan, tmp_path, case, message):
    sel, colors, _ = plan
    kw = {"thickness_mm": 3.0}
    if case == "tampered":
        colors = _tampered(colors, tmp_path)
    elif case == "other_selection":
        sel = write_sel(tmp_path / "other",
                        spec=SelectionSpec(instructions="", keep_at=((100, 100),)))
    elif case == "width":
        kw["width_mm"] = 59.0
    elif case == "width_close":
        kw["width_mm"] = 60.0000001
    elif case == "printer":
        kw["printer"] = "another-printer"
    elif case == "smooth":
        kw["smooth_px"] = 0
    elif case == "smooth_default":
        kw["smooth_px"] = RULES["flat.smooth.sigma_px"].default
    elif case == "thin":
        kw["thickness_mm"] = SKIN
    elif case == "thinner":
        kw["thickness_mm"] = SKIN - 0.1
    elif case == "zero":
        kw["thickness_mm"] = 0
    out = tmp_path / "out"
    with pytest.raises(ColoredFlatError, match=message):
        make_colored_flat(sel, colors, out, **kw)
    assert not out.exists()
    assert issubclass(ColoredFlatError, FlatError)


def test_checks_that_need_no_plan_come_before_verify_colors(plan, tmp_path):
    sel, colors, _ = plan
    tampered = _tampered(colors, tmp_path)
    with pytest.raises(ColoredFlatError, match="must be above the skin depth"):
        make_colored_flat(sel, tampered, tmp_path / "a", thickness_mm=SKIN)
    with pytest.raises(ColoredFlatError, match="--smooth-px cannot be used"):
        make_colored_flat(sel, tampered, tmp_path / "a", thickness_mm=3.0, smooth_px=1)
    out = tmp_path / "busy"
    out.mkdir()
    (out / "x.txt").write_text("mine")
    with pytest.raises(ColoredFlatError, match="is not empty"):
        make_colored_flat(sel, tampered, out, thickness_mm=3.0)


def test_a_not_ready_plan_is_refused(tmp_path):
    sel = write_sel(tmp_path / "sel5", five_stripes())
    rec = write_plan(sel, tmp_path / "colors", extract=5, colors=4, edges="exact")
    assert rec["ready"] is False
    with pytest.raises(ColoredFlatError, match="not ready"):
        make_colored_flat(sel, tmp_path / "colors", tmp_path / "out", thickness_mm=3.0)
    assert not (tmp_path / "out").exists()


def test_a_non_empty_output_folder_is_refused(plan, tmp_path):
    sel, colors, _ = plan
    out = tmp_path / "out"
    out.mkdir()
    (out / "x.txt").write_text("mine")
    with pytest.raises(ColoredFlatError, match="is not empty"):
        make_colored_flat(sel, colors, out, thickness_mm=3.0)
    assert [p.name for p in out.iterdir()] == ["x.txt"]


def test_the_plans_own_width_and_printer_are_accepted(plan, made, tmp_path):
    sel, colors, _ = plan
    rec = make_colored_flat(sel, colors, tmp_path / "out", thickness_mm=3.0, width_mm=60.0,
                            printer="bambu-a1")
    assert rec["colorflat_id"] == made[0]["colorflat_id"]


# --- outputs and record --------------------------------------------------------------


def test_files_and_their_hashes(made):
    rec, out = made[:2]
    names = sorted(p.name for p in out.iterdir())
    assert names == sorted([*rec["outputs"], RECORD_NAME])
    for name, digest in rec["outputs"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == digest
    assert json.loads((out / RECORD_NAME).read_bytes()) == rec
    palette = {p["index"]: p["hex"][1:] for p in rec["palette"]}
    base = rec["base_index"]
    inlays = sorted(set(range(len(palette))) - {base})
    expected_ams = ["ams-base.stl"] + [f"ams-color-{i}-{palette[i]}.stl" for i in inlays
                                       if any(b["index"] == i and b["route"] == "ams"
                                              for b in rec["bodies"])]
    glued = [c["index"] for c in rec["glue"]["report"]["colors"]]
    expected_glue = ["glue-base.stl"] + [f"glue-color-{i}-{palette[i]}.stl" for i in glued]
    # The record is key-sorted JSON, so outputs come back sorted by name.
    assert list(rec["outputs"]) == sorted(expected_ams + expected_glue
                                          + ["top.png", "parts.png", "model.3mf",
                                             "palette.json"])
    assert len(expected_ams) >= 3 and len(expected_glue) >= 2    # the fixture has inlays
    assert [b["file"] for b in rec["bodies"]] == expected_ams + expected_glue


def test_written_stl_bytes_are_exactly_the_gated_ones(made):
    rec, out, captured = made[:3]
    for route, key in (("ams", "ams_checks"), ("glue", "glue_checks")):
        stl = captured[key]["stl"]
        rows = [b for b in rec["bodies"] if b["route"] == route]
        assert len(rows) == len(stl)
        for row in rows:
            name = "base" if row["role"] == "base" else f"color-{row['index']}"
            assert (out / row["file"]).read_bytes() == stl[name]
            mesh = merge_exact(trimesh.load(io.BytesIO(stl[name]), file_type="stl",
                                            process=False))
            assert row["triangles"] == len(mesh.faces)


def test_record_identity_and_params(made):
    rec = made[0]
    assert rec["schema"] == "tdmg.colorflat/1" and rec["algorithm"] == "colorflat-3"
    ident = rec["identity"]
    assert set(ident) == {"algorithm", "colors_id", "selection_id", "mask_pixels_sha256",
                          "params"}
    assert rec["colorflat_id"] == colorflat_id(ident)
    p = ident["params"]
    assert p["width_mm"] == 60.0 and p["thickness_mm"] == 3.0 and p["printer"] == "bambu-a1"
    for key, rule in (("skin_mm", "color.skin.depth_mm"),
                      ("clearance_mm", "color.glue.clearance_mm"),
                      ("min_piece_side_mm", "color.glue.min_piece_side_mm"),
                      ("opening_mm", "flat.sliver.opening_width")):
        assert p[key] == {"value": RULES[rule].default, "rule": rule}
    assert p["min_island_mm2"]["value"] == (RULES["flat.island.min_square_side"].default
                                            * A1.nozzle_diameter_mm) ** 2
    assert p["smoothing"] == {"sigma_px": {"value": RULES["flat.smooth.sigma_px"].default,
                                           "rule": "flat.smooth.sigma_px"}}
    assert p["supersample"] == 4 and p["grid_mm"] == rec["cells"]["grid_mm"]
    assert p["labels_sigma_px"]["rule"] == "flat.smooth.sigma_px"


def test_colorflat_id_changes_with_each_identity_input():
    params = {"width_mm": 60.0, "thickness_mm": 3.0, "printer": "bambu-a1",
              "skin_mm": {"value": 0.6, "rule": "r"}, "grid_mm": 2.0 ** -18}
    base = {"colors_id": "a" * 64, "selection_id": "b" * 64,
            "mask_pixels_sha256": "c" * 64, "params": params}
    ids = {colorflat_id(colorflat_identity(**base))}
    for key in ("colors_id", "selection_id", "mask_pixels_sha256"):
        ids.add(colorflat_id(colorflat_identity(**{**base, key: "d" * 64})))
    for key, value in (("width_mm", 61.0), ("thickness_mm", 2.0), ("printer", "x"),
                       ("skin_mm", {"value": 0.8, "rule": "r"}), ("grid_mm", 2.0 ** -17)):
        ids.add(colorflat_id(colorflat_identity(**{**base,
                                                   "params": {**params, key: value}})))
    assert len(ids) == 9
    with pytest.raises(ColoredFlatError, match="cannot be hashed"):
        colorflat_id(colorflat_identity(**{**base, "params": {"x": float("nan")}}))


def test_repeat_runs_are_byte_identical_and_the_environment_is_not_in_the_id(
        plan, made, tmp_path, monkeypatch):
    sel, colors, _ = plan
    rec, out = made[:2]
    again = tmp_path / "again"
    make_colored_flat(sel, colors, again, thickness_mm=3.0)
    for name in [*rec["outputs"], RECORD_NAME]:
        assert (again / name).read_bytes() == (out / name).read_bytes(), name
    monkeypatch.setattr(cf, "colored_environment", lambda: {"python": "0.0"})
    other = make_colored_flat(sel, colors, tmp_path / "env", thickness_mm=3.0)
    assert other["environment"] == {"python": "0.0"}
    assert other["colorflat_id"] == rec["colorflat_id"]
    monkeypatch.undo()
    thicker = make_colored_flat(sel, colors, tmp_path / "thick", thickness_mm=4.0)
    assert thicker["colorflat_id"] != rec["colorflat_id"]


def test_verdict_is_not_certified_with_f6_unknown(made):
    rec = made[0]
    assert rec["verdict"] == "NOT CERTIFIED"
    ids = {c["id"] for b in rec["bodies"] for c in b["checks"]}
    ids |= {c["id"] for cs in rec["assembly"].values() for c in cs}
    assert ids == COLORED_REQUIRED_CHECKS
    for route in ("ams", "glue"):
        f6 = [c for c in rec["assembly"][route] if c["id"] == "F6.slicer"]
        assert [c["status"] for c in f6] == ["UNKNOWN"]
    for b in rec["bodies"]:
        thin = [c for c in b["checks"] if c["id"] == "F3.thin_regions"]
        assert [c["status"] for c in thin] == ["UNKNOWN"], b["name"]
        assert all(c["status"] == "PASS" for c in b["checks"]
                   if c["id"] != "F3.thin_regions"), b["name"]
    for route, cs in rec["assembly"].items():
        assert all(c["status"] == "PASS" for c in cs if c["id"] != "F6.slicer"), route
    assert all(CheckResult(**c) for b in rec["bodies"] for c in b["checks"])


# --- previews ------------------------------------------------------------------------


def _png(path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def _preview_px(point, transform):
    s, x0, y1 = transform["scale_mm_per_px"], transform["x0_px"], transform["y1_px"]
    return int((y1 - point[1] / s) * P), int((point[0] / s + x0) * P)


def _centre_mm(row, col, transform):
    s, x0, y1 = transform["scale_mm_per_px"], transform["x0_px"], transform["y1_px"]
    return ((col + 0.5) / P - x0) * s, (y1 - (row + 0.5) / P) * s


def test_top_png_matches_the_cells_at_probe_pixels(made):
    rec, out, captured = made[:3]
    cells = captured["color_cells"]
    top = _png(out / "top.png")
    h, w = read_selection(made[3]).mask.shape
    assert top.shape[1] == w * P and top.shape[0] > h * P
    rgb = {p["index"]: tuple(p["rgb"]) for p in rec["palette"]}
    transform = rec["transform"]
    probed = 0
    for label in sorted(set(cells.labels)):
        cell = max(cells.of(label), key=lambda c: c.area)
        inner = cell.buffer(-0.5)
        point = shapely.point_on_surface(inner if not inner.is_empty else cell)
        row, col = _preview_px((point.x, point.y), transform)
        assert cell.contains(shapely.Point(_centre_mm(row, col, transform)))
        assert tuple(top[row, col]) == rgb[label], label
        probed += 1
    assert probed >= 3
    assert (top[:4, :4] == background(h * P, w * P)[:4, :4]).all()     # outside S


def test_parts_png_has_a_number_box_per_piece(made):
    rec, out, captured = made[:3]
    glue = captured["glue_geometry"]
    parts = _png(out / "parts.png")
    h, w = read_selection(made[3]).mask.shape
    assert parts.shape[1] == w * P and parts.shape[0] > h * P
    rgb = {p["index"]: tuple(p["rgb"]) for p in rec["palette"]}
    layout = paint_cells(list(glue.cells.cells), list(glue.cells.labels), rgb,
                         rec["transform"], (h, w))
    boxes = label_boxes(rec["glue"]["report"]["pieces"], rec["transform"], (h, w))
    assert len(boxes) == len(rec["glue"]["report"]["pieces"]) >= 2
    covered = np.zeros((h * P, w * P), bool)
    for number, top, left, bottom, right in boxes:
        # One number per piece: no two boxes overlap (on this fixture), and each box is
        # exactly that piece's number label.
        assert not covered[top:bottom, left:right].any()
        label = number_label(str(number))
        assert (bottom - top, right - left) == label.shape[:2]      # not clipped here
        assert (parts[top:bottom, left:right] == label).all()
        covered[top:bottom, left:right] = True
    image = parts[:h * P]
    assert (image[~covered] == layout[~covered]).all()


def test_number_labels_and_swatches_are_framed(made):
    label = number_label("12")
    assert (label[0] == STRIP_TEXT).all() and (label[:, -1] == STRIP_TEXT).all()
    assert (label == STRIP_BACKGROUND).all(axis=2).any()
    rec, out = made[:2]
    h = read_selection(made[3]).mask.shape[0]
    top = _png(out / "top.png")
    base = next(b for b in rec["bodies"] if b["file"] == "ams-base.stl")
    y = h * P + P * ((ROW_PX - SWATCH_PX) // 2)          # the first legend row's swatch
    x = P * MARGIN_PX
    assert tuple(top[y, x]) == STRIP_TEXT
    assert tuple(top[y + P * SWATCH_PX - BORDER_PX, x + P * SWATCH_PX - BORDER_PX]) \
        == STRIP_TEXT
    middle = (y + P * SWATCH_PX // 2, x + P * SWATCH_PX // 2)
    assert tuple(top[middle]) == tuple(next(p["rgb"] for p in rec["palette"]
                                            if p["index"] == base["index"]))


# --- CLI -----------------------------------------------------------------------------


def _cli(sel, colors, out, *extra):
    return runner.invoke(app, ["flat", str(sel), "--colors", str(colors), "--thickness-mm",
                               "3", "--out", str(out), *extra])


def test_cli_writes_and_reports(plan, made, tmp_path):
    sel, colors, _ = plan
    out = tmp_path / "out"
    r = _cli(sel, colors, out)
    assert r.exit_code == 0, r.output
    rec = json.loads((out / RECORD_NAME).read_bytes())
    text = r.stdout
    lines = text.splitlines()
    assert lines[0] == "verdict NOT CERTIFIED"
    assert "  ams: F6.slicer UNKNOWN: not measured here" in text
    assert "  glue: F6.slicer UNKNOWN: not measured here" in text
    assert "  ams-base: F3.thin_regions UNKNOWN - measured area_mm2=" in text
    for b in rec["bodies"]:
        assert f"{b['name']}: color {b['index']} {b['hex']} ({b['role']}), " \
               f"{b['triangles']} triangles" in text
    assert f"colorflat_id {rec['colorflat_id']}" in lines
    assert rec["colorflat_id"] == made[0]["colorflat_id"]
    for name in [*rec["outputs"], RECORD_NAME]:
        assert f"wrote {out / name}" in lines
    assert lines[-1] == ("open top.png and parts.png; then open model.3mf in your slicer "
                         "and give each color a filament (palette.json)")
    assert all(line.startswith("warning: ") for line in r.stderr.splitlines())


@pytest.mark.parametrize("extra, message", [
    (["--smooth-px", "2.5"], "error: --smooth-px cannot be used with --colors"),
    (["--width-mm", "59"], "error: width_mm 59.0 differs from the plan's width_mm 60.0"),
    (["--printer", "x"], "error: printer 'x' differs from the plan's printer"),
])
def test_cli_refusals_exit_2(plan, tmp_path, extra, message):
    sel, colors, _ = plan
    r = _cli(sel, colors, tmp_path / "out", *extra)
    assert r.exit_code == 2, r.output
    assert _plain(r.stderr).startswith(message)
    assert "Traceback" not in r.output and not (tmp_path / "out").exists()


def test_cli_exits_1_when_a_check_fails_but_still_writes(plan, tmp_path, monkeypatch):
    sel, colors, _ = plan
    rules = load_rules()
    rule_id = "slicer.orca.max_triangles_per_plate"
    rules[rule_id] = rules[rule_id].model_copy(update={"default": 4})
    monkeypatch.setattr(cf, "load_rules", lambda: rules)
    out = tmp_path / "out"
    r = _cli(sel, colors, out)
    assert r.exit_code == 1, r.output
    assert "  ams: F5.triangles FAIL - measured " in r.stdout
    assert "glue-base: F5.triangles FAIL" in r.stdout
    assert (out / RECORD_NAME).exists() and (out / "top.png").exists()


def test_cli_flat_help_mentions_colors_and_keeps_lines_short():
    text = _plain(runner.invoke(app, ["flat", "--help"], prog_name="tdmg").output)
    assert "--colors" in text and "colored.json" in text and "model.3mf" in text
    # Rich keeps the line breaks of every paragraph after the first, so those lines must
    # be under 76 characters (as tests/test_cli.py checks for the exit codes).
    from tdmg.cli import flat
    lines = inspect.cleandoc(flat.__doc__).splitlines()[1:]
    assert any("--colors" in line for line in lines)
    assert all(len(line) < 76 for line in lines)


def test_slice_takes_a_colored_folder(made, tmp_path, monkeypatch):
    """tdmg slice sends a colored folder to tdmg.color_slicing (tests/test_color_slice.py);
    without a slicer it is refused as any slice is, with nothing written."""
    monkeypatch.delenv("TDMG_ORCASLICER_DIR", raising=False)
    out = made[1]
    r = runner.invoke(app, ["slice", str(out), "--out", str(tmp_path / "s")])
    assert r.exit_code == 2, r.output
    assert "no slicer folder" in _plain(r.stderr)
    assert not (tmp_path / "s").exists()


# --- review additions ----------------------------------------------------------------


def test_body_file_names():
    assert body_file("ams", 0, "#AbCdEf", 0) == "ams-base.stl"
    assert body_file("ams", 2, "#AbCdEf", 0) == "ams-color-2-abcdef.stl"
    assert body_file("glue", 0, "#123456", 1) == "glue-color-0-123456.stl"
    assert body_file("glue", 1, "#123456", 1) == "glue-base.stl"


def test_a_plan_with_base_1(plan, tmp_path):
    sel = plan[0]
    rec_plan = write_plan(sel, tmp_path / "colors", base=1)
    assert rec_plan["ready"] is True and rec_plan["base_index"] == 1
    rec = make_colored_flat(sel, tmp_path / "colors", tmp_path / "out", thickness_mm=3.0)
    hex_of = {p["index"]: p["hex"][1:] for p in rec["palette"]}
    base_rows = [b for b in rec["bodies"] if b["role"] == "base"]
    assert [(b["file"], b["index"]) for b in base_rows] == [("ams-base.stl", 1),
                                                            ("glue-base.stl", 1)]
    assert "ams-color-0-" + hex_of[0] + ".stl" in rec["outputs"]
    assert not any(f"color-1-{hex_of[1]}" in name for name in rec["outputs"])


def test_glue_rows_have_their_footprint_area(made):
    rec = made[0]
    pieces = {}
    for row in rec["glue"]["report"]["pieces"]:
        pieces[row["index"]] = pieces.get(row["index"], 0.0) + row["area_mm2"]
    for b in rec["bodies"]:
        if b["route"] == "glue" and b["role"] == "pieces":
            assert b["footprint_area_mm2"] == pytest.approx(pieces[b["index"]], rel=1e-12)
        if b["role"] == "base":
            assert b["footprint_area_mm2"] == pytest.approx(
                rec["regions"]["silhouette_area_mm2"], rel=1e-6)
        if b["role"] == "inlay":
            assert b["footprint_area_mm2"] == b["top_area_mm2"]


def _rules_with(**values):
    rules = load_rules()
    for rule_id, value in values.items():
        rules[rule_id] = rules[rule_id].model_copy(update={"default": value})
    return rules


def test_a_color_with_no_glue_piece_is_reported(plan, made, tmp_path, monkeypatch):
    sel, colors, _ = plan
    largest = {}
    for row in made[0]["glue"]["report"]["pieces"]:
        largest[row["index"]] = max(largest.get(row["index"], 0.0), row["area_mm2"])
    (small, a1), (_, a2) = sorted(largest.items(), key=lambda kv: kv[1])[:2]
    side = ((a1 + a2) / 2) ** 0.5              # folds the smallest color only
    rules = _rules_with(**{"color.glue.min_piece_side_mm": side})
    monkeypatch.setattr(cf, "load_rules", lambda: rules)
    out = tmp_path / "out"
    rec = make_colored_flat(sel, colors, out, thickness_mm=3.0)
    hex_ = next(p["hex"] for p in rec["palette"] if p["index"] == small)
    assert not any(b["route"] == "glue" and b["index"] == small for b in rec["bodies"])
    assert any(b["route"] == "ams" and b["index"] == small for b in rec["bodies"])
    assert any(w.startswith(f"color {small} {hex_} has no glue piece")
               for w in rec["warnings"])
    assert all(p["index"] != small for p in rec["glue"]["report"]["pieces"])


@pytest.mark.parametrize("rule_id, value, param", [
    ("color.glue.clearance_mm", 0.25, "clearance_mm"),
    ("color.glue.min_piece_side_mm", 1.5, "min_piece_side_mm"),
    ("flat.sliver.opening_width", 0.3, "opening_mm"),
    ("flat.island.min_square_side", 1.5, "min_island_mm2"),
    ("flat.smooth.sigma_px", 2.0, "smoothing"),
])
def test_colorflat_id_moves_with_each_rule_value(plan, made, tmp_path, monkeypatch, rule_id,
                                                 value, param):
    """Each rule value used reaches the identity through make_colored_flat. The plan was
    made under the registry's values, and verify_colors refuses a plan whose cleanup
    rules differ from the rules it is given, so verify_colors gets the registry here
    while the rest of the run gets the changed value."""
    sel, colors, _ = plan
    rules = _rules_with(**{rule_id: value})
    monkeypatch.setattr(cf, "load_rules", lambda: rules)
    real = cf.verify_colors
    monkeypatch.setattr(cf, "verify_colors",
                        lambda *a, rules=None, **kw: real(*a, rules=None, **kw))
    rec = make_colored_flat(sel, colors, tmp_path / "out", thickness_mm=3.0)
    before, after = made[0]["identity"]["params"], rec["identity"]["params"]
    assert after[param] != before[param]
    assert rec["colorflat_id"] != made[0]["colorflat_id"]
    assert rec["colorflat_id"] == colorflat_id(rec["identity"])


def test_cli_reports_an_os_error_while_writing_with_exit_2(plan, tmp_path, monkeypatch):
    sel, colors, _ = plan

    def full_disk(*a, **kw):
        raise OSError(28, "No space left on device", str(tmp_path / "out" / "x.stl"))

    monkeypatch.setattr(cf, "write_outputs", full_disk)
    r = _cli(sel, colors, tmp_path / "out")
    assert r.exit_code == 2, r.output
    assert r.stderr.startswith("error: No space left on device")
    assert "Traceback" not in r.output


# --- owner decision (Task 7 review): no glue route for a plan with outlines: keep ----------


@pytest.fixture(scope="module")
def keep(plan, tmp_path_factory):
    sel = plan[0]
    root = tmp_path_factory.mktemp("keep")
    rec_plan = write_plan(sel, root / "colors", outlines="keep")
    assert rec_plan["ready"] is True
    assert rec_plan["identity"]["settings"]["outlines"] == "keep"
    out = root / "out"
    return make_colored_flat(sel, root / "colors", out, thickness_mm=3.0), out, root


def test_record_says_the_glue_route_was_built(made):
    glue = made[0]["glue"]
    assert set(glue) == {"built", "reason", "report"}
    assert glue["built"] is True and glue["reason"] is None and glue["report"]["pieces"]
    assert made[0]["required_checks"] == sorted(COLORED_REQUIRED_CHECKS)


def test_outlines_keep_builds_no_glue_route(keep):
    rec, out, _ = keep
    names = sorted(p.name for p in out.iterdir())
    assert names == sorted([*rec["outputs"], RECORD_NAME])
    assert all(n.startswith("ams-") for n in rec["outputs"] if n.endswith(".stl"))
    assert "ams-base.stl" in names and "top.png" in names
    assert "parts.png" not in names and not any(n.startswith("glue-") for n in names)
    glue = rec["glue"]
    assert set(glue) == {"built", "reason", "report"}
    assert glue["built"] is False and glue["report"] is None
    assert "outlines: keep" in glue["reason"]
    assert all(b["route"] == "ams" for b in rec["bodies"])
    assert rec["assembly"]["glue"] == []
    assert any(w.startswith("glue version not built:") and "outlines: drop" in w
               for w in rec["warnings"])
    assert rec["required_checks"] == sorted(COLORED_REQUIRED_CHECKS - GLUE_ONLY_CHECKS)
    ids = {c["id"] for b in rec["bodies"] for c in b["checks"]}
    ids |= {c["id"] for cs in rec["assembly"].values() for c in cs}
    assert ids == COLORED_REQUIRED_CHECKS - GLUE_ONLY_CHECKS
    assert rec["verdict"] == "NOT CERTIFIED"
    assert "parts.png" not in rec["review"]


def test_cli_outlines_keep_says_why_and_opens_top_png_only(plan, keep, tmp_path):
    sel = plan[0]
    out = tmp_path / "out"
    r = _cli(sel, keep[2] / "colors", out)
    assert r.exit_code == 0, r.output
    lines = r.stdout.splitlines()
    assert any(line.startswith("glue: not built - the plan keeps the outline (outlines: "
                               "keep with an outline family") for line in lines)
    assert lines[-1] == ("open top.png; then open model.3mf in your slicer and give each "
                         "color a filament (palette.json)")
    assert (out / "model.3mf").exists() and (out / "palette.json").exists()
    assert not (out / "parts.png").exists()
    assert "warning: glue version not built:" in r.stderr


def test_keep_with_no_outline_family_still_builds_the_glue_route(plan, keep, tmp_path):
    """Only a drawn band skips the glue route: keep with outline_color none has no family
    (keep_width null, KEEP_NO_EFFECT_NOTE), so the glue route is built as usual."""
    sel = plan[0]
    rec_plan = write_plan(sel, tmp_path / "colors", outlines="keep", outline_color="none")
    assert rec_plan["ready"] is True
    assert rec_plan["outline"]["family"] == [] and rec_plan["outline"]["keep_width"] is None
    rec = make_colored_flat(sel, tmp_path / "colors", tmp_path / "out", thickness_mm=3.0)
    assert rec["glue"]["built"] is True and rec["glue"]["report"]["pieces"]
    assert "parts.png" in rec["outputs"] and "glue-base.stl" in rec["outputs"]
    assert rec["required_checks"] == sorted(COLORED_REQUIRED_CHECKS)
    assert not any(w.startswith("glue version not built") for w in rec["warnings"])
    # The keep fixture's plan did draw a band: that is what skipped its glue route.
    keep_plan = json.loads((keep[2] / "colors" / "colors.json").read_bytes())
    assert keep_plan["outline"]["family"] and keep_plan["outline"]["keep_width"] is not None


# --- model.3mf and palette.json (docs/plans/2026-11-12-color-3mf.md, Task 4) -----------


def test_model_3mf_is_built_from_exactly_the_gated_meshes(made):
    rec, out, captured = made[:3]
    meshes = captured["ams_checks"]["meshes"]
    ams = [b for b in rec["bodies"] if b["route"] == "ams"]
    names = ["base" if b["role"] == "base" else f"color-{b['index']}" for b in ams]
    with zipfile.ZipFile(out / "model.3mf") as z:
        root = etree.fromstring(z.read("3D/3dmodel.model"))
    q = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
    v = np.array([[np.float32(e.get(k)) for k in "xyz"] for e in root.iter(f"{q}vertex")])
    f = np.array([[int(e.get(k)) for k in ("v1", "v2", "v3")]
                  for e in root.iter(f"{q}triangle")])
    want_v = np.vstack([np.asarray(meshes[n].vertices, np.float32) for n in names])
    offsets = np.cumsum([0] + [len(meshes[n].vertices) for n in names[:-1]])
    want_f = np.vstack([np.asarray(meshes[n].faces) + o
                        for n, o in zip(names, offsets, strict=True)])
    assert np.array_equal(v, want_v) and np.array_equal(f, want_f)
    assert rec["model_3mf"]["shells"] == [b["name"] for b in ams]
    assert rec["model_3mf"]["file"] == "model.3mf"
    assert "format.3mf.self_intersection_is_warning" in rec["model_3mf"]["note"]


def test_the_3mf_check_is_an_ams_assembly_check_and_required(made, keep):
    for rec in (made[0], keep[0]):
        ids = [c["id"] for c in rec["assembly"]["ams"]]
        assert ids == ["F4.color_partition", "F4.filaments", "F2.fits_build_volume",
                       "F5.triangles", "F2.export_3mf_matches_bodies", "F6.slicer"]
        check = rec["assembly"]["ams"][4]
        assert check["status"] == "PASS", check["measured"]
        assert [s["name"] for s in check["measured"]["shells"]] == rec["model_3mf"]["shells"]
        assert "F2.export_3mf_matches_bodies" in rec["required_checks"]
        assert not any(c["id"] == "F2.export_3mf_matches_bodies"
                       for c in rec["assembly"]["glue"])


def test_palette_json_matches_the_record_and_the_3mf(made):
    rec, out = made[:2]
    palette = json.loads((out / "palette.json").read_bytes())
    model = (out / "model.3mf").read_bytes()
    assert palette["model_3mf_sha256"] == hashlib.sha256(model).hexdigest()
    assert palette["colorflat_id"] == rec["colorflat_id"]
    ams = [b for b in rec["bodies"] if b["route"] == "ams"]
    assert [s["body"] for s in palette["shells"]] == [b["name"] for b in ams]
    t0 = 0
    for s, b in zip(palette["shells"], ams, strict=True):
        assert (s["role"], s["index"], s["hex"]) == (b["role"], b["index"], b["hex"])
        assert s["top_area_mm2"] == b["top_area_mm2"] and s["volume_mm3"] == b["volume_mm3"]
        assert s["triangles"] == [t0, t0 + b["triangles"]]
        t0 += b["triangles"]
    assert "slot" not in json.dumps(palette["shells"])


def test_a_3mf_that_drops_a_shell_fails_the_run_and_still_writes(plan, tmp_path,
                                                                 monkeypatch):
    sel, colors, _ = plan
    real = cf.write_multishell_3mf
    monkeypatch.setattr(cf, "write_multishell_3mf", lambda shells: real(shells[:-1]))
    out = tmp_path / "out"
    r = _cli(sel, colors, out)
    assert r.exit_code == 1, r.output
    assert "  ams: F2.export_3mf_matches_bodies FAIL" in r.stdout
    rec = json.loads((out / RECORD_NAME).read_bytes())
    assert rec["verdict"] == "NOT CERTIFIED" and (out / "model.3mf").exists()


def test_environment_records_the_zlib_that_deflates_model_3mf(made):
    """zipfile deflates with Python's zlib, which can differ from Pillow's ("zlib")."""
    import zlib
    env = made[0]["environment"]
    assert env["zlib_python"] == zlib.ZLIB_RUNTIME_VERSION
    assert {"zlib", "python", "lxml", "lib3mf"} <= set(env)

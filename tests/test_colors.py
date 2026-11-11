"""tdmg.colors.make_colors and the shared selection reader
(docs/plans/2026-11-11-color-palette.md, Decisions 1, 2, 6, 7 and Task 6)."""

import copy
import hashlib
import json
import math
import time

import numpy as np
import pytest
from PIL import Image
from selection_fixtures import roadie_like

import tdmg.colors
from tdmg.color import CLEANUP_METHOD, METHOD, OUTSIDE, clean_regions, printable_limits_px, quantize
from tdmg.colors import (
    COLORS_ALGORITHM_VERSION,
    LABELS_OUTSIDE,
    OUTER_OUTLINE,
    OUTPUT_FILES,
    PREVIEW_SCALE,
    RECORD_SCHEMA,
    ColorsError,
    colors_identity,
    make_colors,
    mask_mm_per_px,
    swatch_box,
)
from tdmg.flat import mask_outline, to_model
from tdmg.profiles import load_printer
from tdmg.rules import load_rules
from tdmg.selection import (
    Intake,
    SelectionError,
    SelectionSpec,
    pixels_sha256,
    read_selection,
    select_subject,
    write_selection,
)
from tdmg.smoothing import LABELS_METHOD, SUPERSAMPLE

RULES = load_rules()
A1 = load_printer("bambu-a1")
NO_FLAGS = {"colors": None, "edges": None, "base": None}
TOP_KEYS = {"schema", "tdmg_version", "algorithm", "colors_id", "input", "settings",
            "width_mm", "mm_per_px", "printer", "limits", "palette", "base_index",
            "quantize", "cleanup", "smoothing", "methods", "preview", "outputs",
            "environment", "review"}


def write_sel(folder, rgba=None, spec=None):
    rgba = roadie_like() if rgba is None else rgba
    intake = Intake(rgba, "f" * 64, pixels_sha256(rgba), False, "x.png")
    write_selection(intake, select_subject(intake, spec or SelectionSpec()), folder)
    return folder


def run(sel, out, *, width_mm=60.0, flags=None, config_path=None, rules=RULES, printer=A1,
        **kw):
    return make_colors(sel, out, width_mm=width_mm, flags={**NO_FLAGS, **(flags or {})},
                       config_path=config_path, rules=rules, printer=printer, **kw)


@pytest.fixture(scope="module")
def sel(tmp_path_factory):
    return write_sel(tmp_path_factory.mktemp("sel") / "roadie")


@pytest.fixture(scope="module")
def done(sel, tmp_path_factory):
    out = tmp_path_factory.mktemp("colors") / "out"
    return run(sel, out), out


# --- the shared selection reader ------------------------------------------------------

def test_read_selection_returns_the_verified_record_mask_and_cutout(sel):
    v = read_selection(sel, cutout=True)
    rgba = np.array(Image.open(sel / "cutout.png"))
    assert v.record == json.loads((sel / "selection.json").read_bytes())
    assert v.record_sha256 == hashlib.sha256((sel / "selection.json").read_bytes()).hexdigest()
    assert v.mask.dtype == np.bool_ and (v.mask == (rgba[..., 3] == 255)).all()
    assert (v.cutout_rgb == rgba[..., :3]).all()
    assert v.cutout_pixels_sha256 == pixels_sha256(rgba)
    assert not v.mask.flags.writeable and not v.cutout_rgb.flags.writeable


def test_read_selection_without_cutout_does_not_read_it(sel, tmp_path):
    import shutil
    d = shutil.copytree(sel, tmp_path / "sel")
    (d / "cutout.png").unlink()
    v = read_selection(d)
    assert v.cutout_rgb is None and v.cutout_pixels_sha256 is None
    with pytest.raises(SelectionError, match="cutout.png not found"):
        read_selection(d, cutout=True)


def _copy(sel, tmp_path):
    import shutil
    return shutil.copytree(sel, tmp_path / "sel")


def test_tampered_cutout_is_refused(sel, tmp_path):
    d = _copy(sel, tmp_path)
    rgba = np.array(Image.open(d / "cutout.png"))
    rgba[100, 100, :3] = (1, 2, 3)
    Image.fromarray(rgba).save(d / "cutout.png")
    with pytest.raises(SelectionError, match="cutout.png does not match selection.json"):
        read_selection(d, cutout=True)
    with pytest.raises(ColorsError, match="cutout.png does not match selection.json"):
        run(d, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_cutout_whose_alpha_differs_from_the_mask_is_refused(sel, tmp_path):
    # The record's outputs hash is edited to match, so only the alpha check can catch it.
    d = _copy(sel, tmp_path)
    rgba = np.array(Image.open(d / "cutout.png"))
    rgba[0, 0, 3] = 255 - rgba[0, 0, 3]
    Image.fromarray(rgba).save(d / "cutout.png")
    rec = json.loads((d / "selection.json").read_bytes())
    rec["outputs"]["cutout.png"] = hashlib.sha256((d / "cutout.png").read_bytes()).hexdigest()
    (d / "selection.json").write_bytes(json.dumps(rec).encode())
    with pytest.raises(SelectionError, match="cutout.png's transparency does not match"):
        read_selection(d, cutout=True)


def test_tampered_mask_is_refused(sel, tmp_path):
    d = _copy(sel, tmp_path)
    m = np.array(Image.open(d / "mask.png"))
    m[0, 0] = 255 - m[0, 0]
    Image.fromarray(m).save(d / "mask.png")
    with pytest.raises(ColorsError, match="mask.png does not match selection.json"):
        run(d, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_edited_record_is_refused(sel, tmp_path):
    d = _copy(sel, tmp_path)
    rec = json.loads((d / "selection.json").read_bytes())
    rec["controls"]["alpha_min"]["value"] = 200
    (d / "selection.json").write_bytes(json.dumps(rec).encode())
    with pytest.raises(ColorsError, match="selection_id does not match"):
        run(d, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_record_without_a_cutout_hash_is_refused(sel, tmp_path):
    d = _copy(sel, tmp_path)
    rec = json.loads((d / "selection.json").read_bytes())
    del rec["outputs"]["cutout.png"]
    (d / "selection.json").write_bytes(json.dumps(rec).encode())
    with pytest.raises(SelectionError, match="outputs.cutout.png"):
        read_selection(d, cutout=True)
    read_selection(d)          # flat's path does not need it


def test_not_a_selection_folder_is_refused(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(ColorsError, match="selection.json"):
        run(tmp_path / "empty", tmp_path / "out")


# --- the record -----------------------------------------------------------------------

def test_outputs_and_record_schema(done, sel):
    rec, out = done
    assert sorted(p.name for p in out.iterdir()) == sorted([*OUTPUT_FILES, "colors.json"])
    assert json.loads((out / "colors.json").read_bytes()) == rec
    assert set(rec) == TOP_KEYS
    assert rec["schema"] == RECORD_SCHEMA == "tdmg.colors/1"
    assert rec["algorithm"] == COLORS_ALGORITHM_VERSION == "colors-1"
    for name in OUTPUT_FILES:
        assert rec["outputs"][name] == hashlib.sha256((out / name).read_bytes()).hexdigest()
    assert set(rec["outputs"]) == set(OUTPUT_FILES)
    v = read_selection(sel, cutout=True)
    assert rec["input"] == {
        "selection_id": v.record["selection_id"], "selection_json_sha256": v.record_sha256,
        "cutout_pixels_sha256": v.cutout_pixels_sha256,
        "mask_pixels_sha256": v.record["mask_pixels_sha256"],
        "width_px": v.mask.shape[1], "height_px": v.mask.shape[0]}
    assert rec["settings"] == {"settings": {"colors": 4, "edges": "smooth", "base": "auto"},
                               "sources": {"colors": "profile", "edges": "default",
                                           "base": "default"},
                               "config_sha256": None}
    assert rec["width_mm"] == 60.0
    assert rec["printer"] == "bambu-a1"
    assert set(rec["limits"]) == {"min_width_px", "min_area_px", "mm_per_px",
                                  "opening_width_mm", "island_area_mm2",
                                  "nozzle_diameter_mm", "opening_rule", "island_rule"}
    assert rec["limits"]["opening_rule"] == "flat.sliver.opening_width"
    assert rec["limits"]["mm_per_px"] == rec["mm_per_px"]
    assert rec["methods"] == {"colors": "colors-1", "quantize": METHOD,
                              "cleanup": CLEANUP_METHOD, "labels": LABELS_METHOD}
    assert set(rec["quantize"]) == {"iterations", "converged", "n_requested",
                                    "n_distinct_colors", "dropped", "palette_hex"}
    assert set(rec["cleanup"]) == {"passes", "cap_hit", "thin_pixels_reassigned",
                                   "thin_pixels_left", "thin_returned", "no_core",
                                   "pieces_merged", "pixels_changed", "moved", "dropped_hex",
                                   "kept_pieces", "kept_area_px"}
    assert rec["smoothing"] == {"sigma_px": 2.5, "edge_rule": "flat.smooth.sigma_px",
                                "supersample": SUPERSAMPLE,
                                "vanished": []}
    assert rec["base_index"] == 0
    pal = rec["palette"]
    assert [p["index"] for p in pal] == list(range(len(pal)))
    assert [p["base"] for p in pal] == [True] + [False] * (len(pal) - 1)
    assert set(pal[0]) == {"index", "hex", "rgb", "lab", "share", "count", "base"}
    assert math.isclose(sum(p["share"] for p in pal), 1.0)
    assert sum(p["count"] for p in pal) == int(v.mask.sum())
    counts = [p["count"] for p in pal]
    assert counts == sorted(counts, reverse=True)
    assert "python" in rec["environment"] and "scipy" in rec["environment"]
    assert "regions.png" in rec["review"]
    assert rec["preview"]["outer_outline"] == OUTER_OUTLINE


def test_preview_says_the_outer_outline_is_smoothed_later():
    assert OUTER_OUTLINE == "outer outline: image pixels (smoothed when the model is built)"
    assert OUTER_OUTLINE in tdmg.colors.legend_rows("smooth")


def test_the_record_matches_the_library_functions(done, sel):
    rec, out = done
    v = read_selection(sel, cutout=True)
    q = quantize(v.cutout_rgb, v.mask, 4)
    cleaned, log = clean_regions(q, printable_limits_px(rec["mm_per_px"], RULES, A1))
    assert [p["hex"] for p in rec["palette"]] == list(cleaned.hex)
    assert rec["quantize"]["palette_hex"] == list(q.hex)
    assert rec["cleanup"]["pixels_changed"] == log.pixels_changed
    assert rec["cleanup"]["moved"] == [list(m) for m in log.moved]
    labels = np.array(Image.open(out / "labels.png"))
    assert labels.dtype == np.uint8 and labels.shape == v.mask.shape
    want = np.where(cleaned.labels == OUTSIDE, LABELS_OUTSIDE, cleaned.labels)
    assert (labels == want).all()
    assert ((labels == LABELS_OUTSIDE) == ~v.mask).all()


def test_mm_per_px_is_flats_exact_outline_scale(sel):
    v = read_selection(sel)
    _, transform = to_model(mask_outline(v.mask), 60.0)
    assert mask_mm_per_px(v.mask, 60.0) == transform["scale_mm_per_px"]
    m = np.zeros((5, 9), bool)
    m[1, 2] = m[3, 6] = True
    assert mask_mm_per_px(m, 10.0) == 10.0 / 5


@pytest.mark.parametrize("width", [0, -1, math.nan, math.inf, True, "60"])
def test_bad_width_is_refused(sel, tmp_path, width):
    with pytest.raises(ColorsError, match="width_mm"):
        run(sel, tmp_path / "out", width_mm=width)
    assert not (tmp_path / "out").exists()


def test_existing_non_empty_out_is_refused(sel, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "x.txt").write_text("x")
    with pytest.raises(ColorsError, match="not empty"):
        run(sel, out)
    assert sorted(p.name for p in out.iterdir()) == ["x.txt"]


def test_empty_out_folder_is_used(sel, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    run(sel, out)
    assert (out / "colors.json").is_file()


# --- colors_id ------------------------------------------------------------------------

def _id(sel, tmp_path, name, **kw):
    return run(sel, tmp_path / name, **kw)["colors_id"]


def test_colors_id_is_reproducible_and_recomputable(done, sel, tmp_path):
    rec, _ = done
    assert _id(sel, tmp_path, "again") == rec["colors_id"]
    assert len(rec["colors_id"]) == 64


def test_colors_id_changes_with_each_identity_input(done, sel, tmp_path):
    base = done[0]["colors_id"]
    rules = copy.deepcopy(RULES)
    rid = "flat.sliver.opening_width"
    rules[rid] = rules[rid].model_copy(update={"default": 0.5})
    sigma_rules = copy.deepcopy(RULES)
    sid = "flat.smooth.sigma_px"
    sigma_rules[sid] = sigma_rules[sid].model_copy(update={"default": 2.0})
    other_sel = write_sel(tmp_path / "other",
                          spec=SelectionSpec(instructions="", keep_at=((100, 100),)))
    ids = {
        "colors": _id(sel, tmp_path, "c3", flags={"colors": 3}),
        "edges": _id(sel, tmp_path, "furry", flags={"edges": "furry"}),
        "base": _id(sel, tmp_path, "b1", flags={"base": 1}),
        "width": _id(sel, tmp_path, "w50", width_mm=50.0),
        "selection": _id(other_sel, tmp_path, "osel"),
        "rule": _id(sel, tmp_path, "rule", rules=rules),
        "sigma rule": _id(sel, tmp_path, "sigma", rules=sigma_rules),
        "supersample": _id(sel, tmp_path, "s2", supersample=2),
    }
    assert base not in ids.values()
    assert len(set(ids.values())) == len(ids), ids


def test_colors_id_ignores_the_environment_and_setting_sources(done, sel, tmp_path,
                                                               monkeypatch):
    rec = done[0]
    # The same values from a flag instead of the profile/default give the same plan.
    same = run(sel, tmp_path / "flags", flags={"colors": 4, "edges": "smooth", "base": "auto"})
    assert same["colors_id"] == rec["colors_id"]
    assert same["settings"]["sources"] != rec["settings"]["sources"]
    monkeypatch.setattr(tdmg.colors, "environment", lambda: {"python": "0.0"})
    env = run(sel, tmp_path / "env")
    assert env["environment"] != rec["environment"]
    assert env["colors_id"] == rec["colors_id"]


def test_colors_identity_is_the_documented_hash(done):
    rec = done[0]
    lim = rec["limits"]
    rid = colors_identity(
        methods=rec["methods"], selection_id=rec["input"]["selection_id"],
        cutout_pixels_sha256=rec["input"]["cutout_pixels_sha256"],
        mask_pixels_sha256=rec["input"]["mask_pixels_sha256"],
        settings=rec["settings"]["settings"], width_mm=rec["width_mm"],
        rules={lim["opening_rule"]: 0.4, lim["island_rule"]: 2.0,
               "flat.smooth.sigma_px": 2.5},
        sigma_px=2.5, nozzle_diameter_mm=lim["nozzle_diameter_mm"],
        supersample=rec["smoothing"]["supersample"])
    assert rid == rec["colors_id"]


# --- settings -------------------------------------------------------------------------

def test_config_file_and_flag_precedence_end_to_end(sel, tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_bytes(b"colors: 3\nedges: furry\n")
    rec = run(sel, tmp_path / "a", config_path=cfg)
    assert rec["settings"]["settings"] == {"colors": 3, "edges": "furry", "base": "auto"}
    assert rec["settings"]["sources"] == {"colors": "config", "edges": "config",
                                          "base": "default"}
    assert rec["settings"]["config_sha256"] == hashlib.sha256(cfg.read_bytes()).hexdigest()
    assert rec["quantize"]["n_requested"] == 3
    assert rec["smoothing"]["sigma_px"] == 1.0
    assert rec["smoothing"]["edge_rule"] == "color.edges.furry_sigma_px"
    rec = run(sel, tmp_path / "b", config_path=cfg, flags={"colors": 2})
    assert rec["settings"]["settings"]["colors"] == 2
    assert rec["settings"]["sources"]["colors"] == "flag"
    assert rec["settings"]["sources"]["edges"] == "config"
    assert rec["quantize"]["n_requested"] == 2


def test_bad_config_is_refused(sel, tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_bytes(b"colours: 3\n")
    with pytest.raises(ColorsError, match="unknown key 'colours'"):
        run(sel, tmp_path / "out", config_path=cfg)
    assert not (tmp_path / "out").exists()


def test_exact_edges_have_no_rule(sel, tmp_path):
    rec = run(sel, tmp_path / "out", flags={"edges": "exact"})
    assert rec["smoothing"]["sigma_px"] == 0.0 and rec["smoothing"]["edge_rule"] is None


def test_numeric_base_is_marked(sel, tmp_path):
    rec = run(sel, tmp_path / "out", flags={"base": 1})
    assert rec["base_index"] == 1
    assert [p["base"] for p in rec["palette"]][:2] == [False, True]


def test_base_out_of_range_after_cleanup_is_refused(tmp_path):
    # Two colors: a large square and a speck below the island area, which cleanup merges.
    # At 5 mm over 50 px (0.1 mm/px) the island area is 64 px and the opening 4 px.
    rgba = np.zeros((60, 60, 4), np.uint8)
    rgba[5:55, 5:55] = (200, 30, 30, 255)
    rgba[30, 30] = (30, 30, 200, 255)
    sel = write_sel(tmp_path / "sel", rgba)
    rec = run(sel, tmp_path / "ok", width_mm=5.0, flags={"colors": 2})
    assert len(rec["palette"]) == 1 and rec["cleanup"]["dropped_hex"]
    with pytest.raises(ColorsError, match=r"base 1 is not a color index of a 1-color palette"):
        run(sel, tmp_path / "out", width_mm=5.0, flags={"colors": 2, "base": 1})
    assert not (tmp_path / "out").exists()


def test_fewer_distinct_colors_than_requested(tmp_path):
    rgba = np.zeros((40, 40, 4), np.uint8)
    rgba[5:35, 5:20] = (200, 30, 30, 255)
    rgba[5:35, 20:35] = (30, 30, 200, 255)
    rec = run(write_sel(tmp_path / "sel", rgba), tmp_path / "out")
    assert rec["quantize"]["n_distinct_colors"] == 2
    assert rec["quantize"]["n_requested"] == 4
    assert len(rec["palette"]) == 2


# --- the preview ----------------------------------------------------------------------

def test_regions_png_size_swatches_and_determinism(done, sel, tmp_path):
    rec, out = done
    img = np.array(Image.open(out / "regions.png"))
    h, w = rec["input"]["height_px"], rec["input"]["width_px"]
    assert img.dtype == np.uint8 and img.shape[2] == 3
    assert img.shape[1] == 2 * PREVIEW_SCALE * w
    assert img.shape[0] > PREVIEW_SCALE * h
    for p in rec["palette"]:
        top, left, bottom, right = swatch_box(p["index"], h)
        assert (img[top:bottom, left:right] == p["rgb"]).all(), p
    # Every palette color appears in the right panel; the left panel is the cutout.
    right = img[:PREVIEW_SCALE * h, PREVIEW_SCALE * w:]
    for p in rec["palette"]:
        assert (right == p["rgb"]).all(axis=-1).any(), p["hex"]
    cutout = np.array(Image.open(sel / "cutout.png"))
    left = img[:PREVIEW_SCALE * h, :PREVIEW_SCALE * w]
    big = np.repeat(np.repeat(cutout, PREVIEW_SCALE, 0), PREVIEW_SCALE, 1)
    inside = big[..., 3] == 255
    assert (left[inside] == big[..., :3][inside]).all()
    again = tmp_path / "again"
    run(sel, again)
    for name in OUTPUT_FILES:
        assert (again / name).read_bytes() == (out / name).read_bytes()


def test_changed_pixels_are_outlined(tmp_path):
    # A 1-px line of blue across a red square: cleanup reassigns it (opening 4 px at
    # 0.1 mm/px), so it is outlined.
    rgba = np.zeros((60, 60, 4), np.uint8)
    rgba[5:55, 5:55] = (200, 30, 30, 255)
    rgba[30, 10:50] = (30, 30, 200, 255)
    out = tmp_path / "out"
    rec = run(write_sel(tmp_path / "sel", rgba), out, width_mm=5.0,
              flags={"colors": 2, "edges": "exact"})
    assert rec["cleanup"]["pixels_changed"] == 40
    img = np.array(Image.open(out / "regions.png"))
    s = PREVIEW_SCALE
    band = img[30 * s:31 * s, 60 * s + 10 * s:60 * s + 50 * s]
    colors = {tuple(c) for c in band.reshape(-1, 3)}
    assert colors <= {(0, 0, 0), (255, 255, 255)} and len(colors) == 2
    plain = img[20 * s:21 * s, 60 * s + 10 * s:60 * s + 50 * s]
    assert (plain == rec["palette"][0]["rgb"]).all()


def test_supersample_one_and_three_work(sel, tmp_path):
    for s in (1, 3):
        rec = run(sel, tmp_path / f"s{s}", supersample=s)
        assert rec["smoothing"]["supersample"] == s


# --- the owner's images ---------------------------------------------------------------

# The cleaned palettes at N = 4, 60 mm, from the comment above OWNER_SHARES_TOL in
# tests/test_smooth_labels.py (measured on the Windows PC, 2026-11-11).
OWNER_PALETTE = {"roadie-tol30": ["#ed0707", "#ededed", "#eeef0a", "#5c271b"],
                 "oddie": ["#234c1a", "#4c708b", "#48a835", "#dc4f47"]}


@pytest.mark.parametrize("name", ["roadie-tol30", "oddie"])
def test_owner_images(name, owner_selection, tmp_path):
    from conftest import SELECTIONS
    from test_color_cleanup import OWNER_CLEANUP
    from test_smooth_labels import OWNER_FINE_SHA

    from tdmg.smoothing import smooth_labels

    owner_selection(name)                     # skips if absent, fails if not the Task 1 files
    out = tmp_path / name
    t0 = time.perf_counter()
    rec = run(SELECTIONS / name, out, flags={"colors": 4, "edges": "smooth"})
    dt = time.perf_counter() - t0
    labels = np.array(Image.open(out / "labels.png")).astype(np.int32)
    labels[labels == LABELS_OUTSIDE] = OUTSIDE
    digest = hashlib.sha256(labels.tobytes()).hexdigest()[:16]
    log = rec["cleanup"]
    assert (log["passes"], log["pixels_changed"], digest) == OWNER_CLEANUP[name]
    assert rec["smoothing"]["vanished"] == []
    # labels.png and the recorded sigma reproduce the pinned fine map (Decision 7).
    fine = smooth_labels(labels, rec["smoothing"]["sigma_px"],
                         rec["smoothing"]["supersample"]).fine
    assert hashlib.sha256(np.ascontiguousarray(fine).tobytes()).hexdigest()[:16] == (
        OWNER_FINE_SHA[name])
    assert [p["hex"] for p in rec["palette"]] == OWNER_PALETTE[name]
    shares = [f"{p['share']:.1%}" for p in rec["palette"]]
    print(f"\n{name}: make_colors {dt:.2f} s; palette {OWNER_PALETTE[name]} shares "
          f"{shares}; colors_id {rec['colors_id']}")

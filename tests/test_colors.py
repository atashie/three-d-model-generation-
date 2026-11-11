"""tdmg.colors.make_colors and the shared selection reader
(docs/plans/2026-11-11-color-palette.md, Decisions 1, 2, 6, 7 and Task 6)."""

import copy
import dataclasses
import hashlib
import json
import math
import shutil
import time

import numpy as np
import pytest
from PIL import Image
from selection_fixtures import roadie_like

import tdmg.color_plan
import tdmg.colors
from tdmg.color import (
    CLEANUP_METHOD,
    KEEP_NO_EFFECT_NOTE,
    METHOD,
    OUTLINE_METHOD,
    OUTLINE_PLACEHOLDER_NOTE,
    OUTSIDE,
    clean_regions,
    printable_limits_px,
    quantize,
)
from tdmg.colors import (
    COLORS_ALGORITHM_VERSION,
    LABELS_OUTSIDE,
    OUTER_OUTLINE,
    OUTPUT_FILES,
    PREVIEW_SCALE,
    RECORD_SCHEMA,
    ROW_PX,
    ColorsError,
    VerifiedColors,
    colors_id,
    colors_identity,
    extracted_swatch_box,
    make_colors,
    mask_mm_per_px,
    not_ready_reason,
    swatch_box,
    verify_colors,
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
TOP_KEYS = {"schema", "tdmg_version", "algorithm", "colors_id", "identity", "input",
            "settings", "regions_pixels_sha256",
            "width_mm", "mm_per_px", "printer", "limits", "palette", "base_index",
            "quantize", "cleanup", "smoothing", "methods", "preview", "outputs",
            "environment", "review",
            "ready", "not_ready_reason", "extraction", "outline", "merges"}
# The settings at their defaults, as recorded, and their sources.
DEFAULT_SETTINGS = {"colors": 4, "extract": 6, "edges": "smooth", "base": "auto",
                    "outlines": "drop", "outline_color": "auto", "merge": []}
DEFAULT_SOURCES = {"colors": "profile", "extract": "rule", "edges": "default",
                   "base": "default", "outlines": "default", "outline_color": "default",
                   "merge": "default"}


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
    d = _copy(sel, tmp_path)
    (d / "cutout.png").unlink()
    v = read_selection(d)
    assert v.cutout_rgb is None and v.cutout_pixels_sha256 is None
    with pytest.raises(SelectionError, match="cutout.png not found"):
        read_selection(d, cutout=True)


def _copy(src, tmp_path, name="sel"):
    return shutil.copytree(src, tmp_path / name)


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
    assert rec["schema"] == RECORD_SCHEMA == "tdmg.colors/2"
    assert rec["algorithm"] == COLORS_ALGORITHM_VERSION == "colors-2"
    for name in OUTPUT_FILES:
        assert rec["outputs"][name] == hashlib.sha256((out / name).read_bytes()).hexdigest()
    assert set(rec["outputs"]) == set(OUTPUT_FILES)
    regions = np.array(Image.open(out / "regions.png"))
    assert rec["regions_pixels_sha256"] == pixels_sha256(regions)
    v = read_selection(sel, cutout=True)
    assert rec["input"] == {
        "selection_id": v.record["selection_id"], "selection_json_sha256": v.record_sha256,
        "cutout_pixels_sha256": v.cutout_pixels_sha256,
        "mask_pixels_sha256": v.record["mask_pixels_sha256"],
        "width_px": v.mask.shape[1], "height_px": v.mask.shape[0]}
    assert rec["settings"] == {"settings": DEFAULT_SETTINGS, "sources": DEFAULT_SOURCES,
                               "config_sha256": None}
    assert rec["width_mm"] == 60.0
    assert rec["printer"] == "bambu-a1"
    assert set(rec["limits"]) == {"min_width_px", "min_area_px", "mm_per_px",
                                  "opening_width_mm", "island_area_mm2",
                                  "nozzle_diameter_mm", "opening_rule", "island_rule"}
    assert rec["limits"]["opening_rule"] == "flat.sliver.opening_width"
    assert rec["limits"]["mm_per_px"] == rec["mm_per_px"]
    assert rec["methods"] == {"colors": "colors-2", "quantize": METHOD,
                              "outline": OUTLINE_METHOD, "cleanup": CLEANUP_METHOD,
                              "labels": LABELS_METHOD}
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
    q = quantize(v.cutout_rgb, v.mask, 6)
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

def _id(sel, tmp_path, name, monkeypatch=None, **kw):
    if monkeypatch is None:
        return run(sel, tmp_path / name, **kw)["colors_id"]
    # A different outline method (as Task 7c will bring) changes the id.
    real = tdmg.color_plan.handle_outlines

    def other(q, **k):
        out, res = real(q, **k)
        return out, dataclasses.replace(res, method="outline-other/1")
    with monkeypatch.context() as m:
        m.setattr(tdmg.color_plan, "handle_outlines", other)
        return run(sel, tmp_path / name, **kw)["colors_id"]


def test_colors_id_is_reproducible_and_recomputable(done, sel, tmp_path):
    rec, _ = done
    assert _id(sel, tmp_path, "again") == rec["colors_id"]
    assert len(rec["colors_id"]) == 64


def test_colors_id_changes_with_each_identity_input(done, sel, tmp_path, monkeypatch):
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
        "extract": _id(sel, tmp_path, "e5", flags={"extract": 5}),
        "outlines": _id(sel, tmp_path, "keep", flags={"outlines": "keep"}),
        "outline_color": _id(sel, tmp_path, "none", flags={"outline_color": "none"}),
        "merge": _id(sel, tmp_path, "m", flags={"merge": [[3, 0]]}),
        "outline method": _id(sel, tmp_path, "om", monkeypatch=monkeypatch),
    }
    assert base not in ids.values()
    assert len(set(ids.values())) == len(ids), ids


def test_colors_id_ignores_the_environment_and_setting_sources(done, sel, tmp_path,
                                                               monkeypatch):
    rec = done[0]
    # The same values from a flag instead of the profile/default give the same plan.
    same = run(sel, tmp_path / "flags", flags={"colors": 4, "edges": "smooth", "base": "auto",
                                               "extract": 6, "outlines": "drop",
                                               "outline_color": "auto", "merge": []})
    assert same["colors_id"] == rec["colors_id"]
    assert same["settings"]["sources"] != rec["settings"]["sources"]
    monkeypatch.setattr(tdmg.colors, "environment", lambda: {"python": "0.0"})
    env = run(sel, tmp_path / "env")
    assert env["environment"] != rec["environment"]
    assert env["colors_id"] == rec["colors_id"]


def test_colors_id_is_the_hash_of_the_stored_identity(done):
    rec = done[0]
    ident = rec["identity"]
    assert colors_id(ident) == rec["colors_id"]
    assert rec["colors_id"] == hashlib.sha256(json.dumps(
        ident, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    # Built from explicit inputs; the duplicated record fields agree with it.
    assert ident == colors_identity(
        methods=rec["methods"], selection_id=rec["input"]["selection_id"],
        cutout_pixels_sha256=rec["input"]["cutout_pixels_sha256"],
        mask_pixels_sha256=rec["input"]["mask_pixels_sha256"],
        settings=rec["settings"]["settings"], width_mm=rec["width_mm"],
        printer=rec["printer"], nozzle_diameter_mm=rec["limits"]["nozzle_diameter_mm"],
        rules=ident["rules"], supersample=rec["smoothing"]["supersample"])
    assert set(ident) == {"methods", "selection_id", "cutout_pixels_sha256",
                          "mask_pixels_sha256", "settings", "width_mm", "printer",
                          "nozzle_diameter_mm", "rules", "supersample"}
    # One value per rule used, from the registry: both cleanup rules (the island rule's
    # own value, not the derived area) and the edges rule. Sigma is hashed only here.
    lim, sm = rec["limits"], rec["smoothing"]
    assert ident["rules"] == {
        lim["opening_rule"]: RULES[lim["opening_rule"]].default,
        lim["island_rule"]: RULES[lim["island_rule"]].default,
        sm["edge_rule"]: RULES[sm["edge_rule"]].default}
    assert ident["rules"][sm["edge_rule"]] == sm["sigma_px"]


def test_colors_id_refuses_nan():
    with pytest.raises(ColorsError, match="identity"):
        colors_id({"width_mm": math.nan})


# --- verify_colors --------------------------------------------------------------------

def test_verify_colors_accepts_a_good_folder(done, sel):
    rec, out = done
    labels8 = np.array(Image.open(out / "labels.png"))
    for check_preview in (True, False):
        v = verify_colors(out, sel, check_preview=check_preview)
        assert isinstance(v, VerifiedColors)
        assert v.record == rec
        assert v.palette == rec["palette"] and v.settings == rec["settings"]["settings"]
        assert v.sigma_px == rec["smoothing"]["sigma_px"]
        assert v.supersample == rec["smoothing"]["supersample"]
        assert v.width_mm == rec["width_mm"] and v.base_index == rec["base_index"]
        assert v.mm_per_px == rec["mm_per_px"]
        assert v.labels.dtype == np.int32 and not v.labels.flags.writeable
        want = np.where(labels8 == LABELS_OUTSIDE, OUTSIDE, labels8.astype(np.int32))
        assert (v.labels == want).all()


def test_verify_colors_requires_the_selection():
    with pytest.raises(TypeError):
        verify_colors("somewhere")       # the selection is a required argument


def _edit_record(d, change):
    rec = json.loads((d / "colors.json").read_bytes())
    change(rec)
    (d / "colors.json").write_bytes(json.dumps(rec).encode())


def _swap_counts(r):
    p = r["palette"]
    p[0]["count"], p[1]["count"] = p[1]["count"], p[0]["count"]


@pytest.mark.parametrize("change, message", [
    (lambda r: r.update(width_mm=50.0), "width_mm does not match the identity"),
    (lambda r: r["settings"]["settings"].update(colors=3), "settings.settings"),
    (lambda r: r["input"].update(selection_id="0" * 64), "input.selection_id"),
    (lambda r: r.update(printer="other"), "printer"),
    (lambda r: r["smoothing"].update(sigma_px=1.0), "smoothing.sigma_px"),
    (lambda r: r["smoothing"].update(supersample=2), "smoothing.supersample"),
    (lambda r: r["smoothing"].update(edge_rule="color.edges.furry_sigma_px"),
     "smoothing.edge_rule"),
    (lambda r: r["methods"].update(quantize="x"), "methods"),
    (lambda r: r["limits"].update(opening_width_mm=0.5), "limits.opening_width_mm"),
    (lambda r: r["limits"].update(island_area_mm2=1.0), "limits.island_area_mm2"),
    (lambda r: r["limits"].update(island_rule="x"), "limits.island_rule"),
    (lambda r: r["limits"].update(mm_per_px=0.3), "limits.mm_per_px is not"),
    (lambda r: r.update(mm_per_px=0.3), "mm_per_px is not"),
    (lambda r: r["limits"].update(min_width_px=1.0), "limits.min_width_px is not"),
    (lambda r: r["limits"].update(min_area_px=1.0), "limits.min_area_px is not"),
    (lambda r: r["identity"].update(width_mm=50.0), "colors_id does not match"),
    (lambda r: r["identity"]["rules"].update({"flat.sliver.opening_width": 0.5}),
     "colors_id does not match"),
    (lambda r: r.pop("identity"), "identity"),
    (lambda r: r.update(schema="tdmg.colors/1"), "not a tdmg.colors/2 record"),
    (lambda r: r["palette"].pop(), "final_index is not the final palette entry"),
    (lambda r: r["palette"][1].update(index=5), "palette indices are not 0..k-1"),
    (lambda r: r["palette"][0].update(hex="#000000"), "is not its rgb"),
    (lambda r: r["palette"][0].update(rgb=[256, 0, 0]), "three ints 0..255"),
    (lambda r: r["palette"][0].update(rgb=[1.0, 0, 0]), "three ints 0..255"),
    (lambda r: r["palette"][-1].update(count=r["palette"][-1]["count"] - 1), "pixel counts"),
    (_swap_counts, "palette counts increase"),
    (lambda r: r["palette"][0].update(share=0.5), "shares are not its counts"),
    (lambda r: r.update(base_index=1), "base_index and the palette's base flags"),
    (lambda r: [p.update(base=p["index"] == 1) for p in r["palette"]],
     "base_index and the palette's base flags"),
    (lambda r: r.update(regions_pixels_sha256="0" * 64),
     "regions.png's pixels do not match"),
    (lambda r: r["outputs"].update({"extra.png": "0" * 64}), "outputs must be exactly"),
    (lambda r: r["outputs"].pop("regions.png"), "outputs must be exactly"),
])
def test_verify_colors_refuses_an_edited_record(done, sel, tmp_path, change, message):
    d = _copy(done[1], tmp_path, "colors")
    _edit_record(d, change)
    with pytest.raises(ColorsError, match=message):
        verify_colors(d, sel)


def _edit_identity(change):
    """An identity edit with colors_id recomputed, so only the type checks can catch it."""
    def edit(r):
        change(r["identity"])
        r["colors_id"] = colors_id(r["identity"])
    return edit


@pytest.mark.parametrize("change, message", [
    (lambda i: i.update(supersample="4"), "supersample must be an integer"),
    (lambda i: i.update(supersample=True), "supersample must be an integer"),
    (lambda i: i.update(supersample=0), "supersample must be at least 1"),
    (lambda i: i.update(width_mm=-1.0), "width_mm must be a finite number above 0"),
    (lambda i: i.update(width_mm=True), "width_mm must be a number"),
    (lambda i: i["rules"].update({"flat.smooth.sigma_px": -1.0}),
     "sigma_px must be a finite number of at least 0"),
    (lambda i: i["rules"].update({"flat.smooth.sigma_px": "2.5"}), "must be a finite number"),
    (lambda i: i["rules"].pop("flat.smooth.sigma_px"), "identity.rules must hold exactly"),
    (lambda i: i["settings"].update(base=True), "identity.settings.base"),
    (lambda i: i["settings"].update(base="first"), "identity.settings.base"),
    (lambda i: i["settings"].update(edges="fuzzy"), "identity.settings.edges"),
    (lambda i: i["settings"].pop("base"), "identity.settings must hold exactly"),
])
def test_verify_colors_checks_identity_types(done, sel, tmp_path, change, message):
    d = _copy(done[1], tmp_path, "colors")
    _edit_record(d, _edit_identity(change))
    with pytest.raises(ColorsError, match=message):
        verify_colors(d, sel)


def test_verify_colors_refuses_an_identity_that_cannot_be_hashed(done, sel, tmp_path):
    d = _copy(done[1], tmp_path, "colors")
    rec = json.loads((d / "colors.json").read_bytes())
    rec["identity"]["width_mm"] = math.inf
    (d / "colors.json").write_text(json.dumps(rec))     # json writes Infinity
    with pytest.raises(ColorsError, match="identity cannot be hashed"):
        verify_colors(d, sel)


def test_verify_colors_maps_arithmetic_errors(done, sel, tmp_path):
    # A huge nozzle overflows the island area (a float ** 2): ColorsError, not a crash.
    d = _copy(done[1], tmp_path, "colors")
    _edit_record(d, _edit_identity(lambda i: i.update(nozzle_diameter_mm=1e300)))
    with pytest.raises(ColorsError, match="cannot be computed"):
        verify_colors(d, sel)


def test_verify_colors_check_preview_false_skips_the_decode_only(done, sel, tmp_path):
    d = _copy(done[1], tmp_path, "colors")
    _edit_record(d, lambda r: r.update(regions_pixels_sha256="0" * 64))
    verify_colors(d, sel, check_preview=False)
    with pytest.raises(ColorsError, match="regions_pixels_sha256"):
        verify_colors(d, sel)
    data = bytearray((d / "regions.png").read_bytes())
    data[-20] ^= 1
    (d / "regions.png").write_bytes(bytes(data))
    with pytest.raises(ColorsError, match="regions.png does not match colors.json"):
        verify_colors(d, sel, check_preview=False)


def test_verify_colors_refuses_tampered_images(done, sel, tmp_path):
    d = _copy(done[1], tmp_path, "labels")
    labels = np.array(Image.open(d / "labels.png"))
    labels[tuple(np.argwhere(labels == LABELS_OUTSIDE)[0])] = 0
    Image.fromarray(labels).save(d / "labels.png")
    with pytest.raises(ColorsError, match="labels.png does not match colors.json"):
        verify_colors(d, sel)
    d = _copy(done[1], tmp_path, "regions")
    data = bytearray((d / "regions.png").read_bytes())
    data[-20] ^= 1
    (d / "regions.png").write_bytes(bytes(data))
    with pytest.raises(ColorsError, match="regions.png does not match colors.json"):
        verify_colors(d, sel)
    d = _copy(done[1], tmp_path, "gone")
    (d / "labels.png").unlink()
    with pytest.raises(ColorsError, match="labels.png not found"):
        verify_colors(d, sel)


def _rewrite_labels(d, change):
    """Edit labels.png and update its hash in colors.json, so only deeper checks catch it."""
    labels = np.array(Image.open(d / "labels.png"))
    change(labels)
    Image.fromarray(labels).save(d / "labels.png")
    digest = hashlib.sha256((d / "labels.png").read_bytes()).hexdigest()
    _edit_record(d, lambda r: r["outputs"].update({"labels.png": digest}))


def test_verify_colors_refuses_labels_out_of_range_even_with_a_matching_hash(done, sel,
                                                                            tmp_path):
    d = _copy(done[1], tmp_path, "colors")
    _rewrite_labels(d, lambda a: a.__setitem__(tuple(np.argwhere(a == 0)[0]), 7))
    with pytest.raises(ColorsError, match="labels.png has values other than"):
        verify_colors(d, sel)


def test_verify_colors_refuses_another_selection(done, tmp_path):
    other = write_sel(tmp_path / "other",
                      spec=SelectionSpec(instructions="", keep_at=((100, 100),)))
    with pytest.raises(ColorsError, match="was made from another selection"):
        verify_colors(done[1], other)


def test_verify_colors_refuses_labels_outside_the_selection_mask(done, sel, tmp_path):
    # labels.png, its hash, the counts and the shares are made consistent, and the scale is
    # kept (the pixel is inside the mask's columns), but it labels a pixel outside the mask.
    d = _copy(done[1], tmp_path, "colors")
    labels = np.array(Image.open(d / "labels.png"))
    cols = np.flatnonzero((labels != LABELS_OUTSIDE).any(axis=0))
    outside = np.argwhere(labels == LABELS_OUTSIDE)
    y, x = next(p for p in outside if cols[0] <= p[1] <= cols[-1])
    _rewrite_labels(d, lambda a: a.__setitem__((y, x), 0))

    def recount(r):
        r["palette"][0]["count"] += 1
        total = sum(p["count"] for p in r["palette"])
        for p in r["palette"]:
            p["share"] = p["count"] / total
    _edit_record(d, recount)
    with pytest.raises(ColorsError, match="outside the selection's mask"):
        verify_colors(d, sel)


# --- settings -------------------------------------------------------------------------

def test_config_file_and_flag_precedence_end_to_end(sel, tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_bytes(b"colors: 3\nedges: furry\n")
    rec = run(sel, tmp_path / "a", config_path=cfg)
    assert rec["settings"]["settings"] == {**DEFAULT_SETTINGS, "colors": 3, "edges": "furry"}
    assert rec["settings"]["sources"] == {**DEFAULT_SOURCES, "colors": "config",
                                          "edges": "config"}
    assert rec["settings"]["config_sha256"] == hashlib.sha256(cfg.read_bytes()).hexdigest()
    assert rec["quantize"]["n_requested"] == 6          # extract, not colors
    assert rec["smoothing"]["sigma_px"] == 1.0
    assert rec["smoothing"]["edge_rule"] == "color.edges.furry_sigma_px"
    rec = run(sel, tmp_path / "b", config_path=cfg, flags={"colors": 2})
    assert rec["settings"]["settings"]["colors"] == 2
    assert rec["settings"]["sources"]["colors"] == "flag"
    assert rec["settings"]["sources"]["edges"] == "config"
    assert rec["quantize"]["n_requested"] == 6


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
    assert rec["quantize"]["n_requested"] == 6
    assert len(rec["palette"]) == 2


# --- the preview ----------------------------------------------------------------------

def test_regions_png_size_swatches_and_same_process_repeat(done, sel, tmp_path):
    # "Repeat" means two runs in one process and environment give the same bytes; it is
    # not a comparison across machines.
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
# tests/test_smooth_labels.py (measured on the Windows PC, 2026-11-11). Since Task 7b the
# default extraction is 6 (test_owner_images_at_the_default_extraction); this test sets
# extract 4, the setting of the owner's first review, and still gives the Task 6 pins.
OWNER_PALETTE = {"roadie-tol30": ["#ed0707", "#ededed", "#eeef0a", "#5c271b"],
                 "oddie": ["#234c1a", "#4c708b", "#48a835", "#dc4f47"]}


@pytest.mark.parametrize("name", ["roadie-tol30", "oddie"])
def test_owner_images(name, owner_selection, tmp_path):
    from conftest import SELECTIONS
    from test_color_cleanup import OWNER_CLEANUP
    from test_smooth_labels import OWNER_FINE_SHA, PARITY

    from tdmg.smoothing import smooth_labels

    owner_selection(name)                     # skips if absent, fails if not the Task 1 files
    out = tmp_path / name
    t0 = time.perf_counter()
    rec = run(SELECTIONS / name, out, flags={"colors": 4, "extract": 4, "edges": "smooth"})
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
        OWNER_FINE_SHA[name]), PARITY
    assert [p["hex"] for p in rec["palette"]] == OWNER_PALETTE[name]
    shares = [f"{p['share']:.1%}" for p in rec["palette"]]
    print(f"\n{name}: make_colors {dt:.2f} s; palette {OWNER_PALETTE[name]} shares "
          f"{shares}; colors_id {rec['colors_id']}")


# --- Task 7b: extraction, merges, the outline seam and the ready flag -------------------

STRIPES = [((200, 30, 30), 30), ((30, 30, 200), 25), ((30, 200, 30), 20),
           ((240, 240, 240), 15), ((20, 20, 20), 10)]


def five_stripes() -> np.ndarray:
    """Five well-separated flat colors in vertical stripes of distinct widths (largest
    first), wide enough to survive cleanup at 60 mm."""
    rgba = np.zeros((80, 120, 4), np.uint8)
    x = 10
    for rgb, width in STRIPES:
        rgba[10:70, x:x + width] = (*rgb, 255)
        x += width
    return rgba


@pytest.fixture(scope="module")
def sel5(tmp_path_factory):
    return write_sel(tmp_path_factory.mktemp("sel5") / "five", five_stripes())


@pytest.fixture(scope="module")
def not_ready(sel5, tmp_path_factory):
    out = tmp_path_factory.mktemp("nr") / "out"
    return run(sel5, out, flags={"extract": 5, "colors": 4, "edges": "exact"}), out


def test_record_extraction_outline_merges_and_ready(done):
    rec = done[0]
    assert rec["ready"] is True and rec["not_ready_reason"] is None
    ext = rec["extraction"]
    assert set(ext) == {"extract", "n_extracted", "palette"}
    assert ext["extract"] == 6 and ext["n_extracted"] == len(ext["palette"]) == 4
    assert [e["hex"] for e in ext["palette"]] == rec["quantize"]["palette_hex"]
    assert set(ext["palette"][0]) == {"index", "hex", "rgb", "lab", "share", "count",
                                      "fate", "final_index", "merged_into"}
    for e in ext["palette"]:
        assert e["merged_into"] is None and e["fate"] == "final"
        assert rec["palette"][e["final_index"]]["hex"] == e["hex"]
    assert rec["outline"] == {"outlines": "drop", "outline_color": "auto", "found_by": "auto",
                              "family": [], "method": OUTLINE_METHOD,
                              "notes": [OUTLINE_PLACEHOLDER_NOTE]}
    assert rec["merges"] == []
    assert rec["identity"]["settings"] == DEFAULT_SETTINGS


def test_not_ready_plan_is_written_and_says_why(not_ready, sel5):
    rec, out = not_ready
    assert sorted(p.name for p in out.iterdir()) == sorted([*OUTPUT_FILES, "colors.json"])
    assert rec["ready"] is False
    assert len(rec["palette"]) == 5
    assert rec["not_ready_reason"] == not_ready_reason(5, 4, 0, 4)
    assert rec["not_ready_reason"].startswith(
        "5 colors remain after cleanup, but colors allows at most 4")
    assert [e["final_index"] for e in rec["extraction"]["palette"]] == [0, 1, 2, 3, 4]
    with pytest.raises(ColorsError, match="this color plan is not ready, so it cannot be "
                                          "built: 5 colors remain"):
        verify_colors(out, sel5)


def test_one_merge_makes_it_ready(not_ready, sel5, tmp_path):
    ext = not_ready[0]["extraction"]["palette"]
    cfg = tmp_path / "m.yaml"
    cfg.write_bytes(b"merge: [[4, 3]]\n")            # black stripe into the grey-white one
    out = tmp_path / "out"
    rec = run(sel5, out, flags={"extract": 5, "colors": 4, "edges": "exact"},
              config_path=cfg)
    assert rec["ready"] is True and rec["not_ready_reason"] is None
    assert len(rec["palette"]) == 4
    assert rec["merges"] == [{"from": 4, "from_hex": ext[4]["hex"], "into": 3,
                              "into_hex": ext[3]["hex"]}]
    got = rec["extraction"]["palette"]
    assert (got[4]["fate"], got[4]["final_index"], got[4]["merged_into"]) == (
        "merged", None, 3)
    assert rec["palette"][got[3]["final_index"]]["count"] == ext[3]["count"] + ext[4]["count"]
    labels = np.array(Image.open(out / "labels.png"))
    assert (labels[10:70, 100:110] == got[3]["final_index"]).all()   # the black stripe
    verify_colors(out, sel5)
    assert rec["colors_id"] != not_ready[0]["colors_id"]


def test_base_is_checked_against_the_final_palette_ready_or_not(sel5, tmp_path):
    rec = run(sel5, tmp_path / "ok", flags={"extract": 5, "colors": 4, "base": 3})
    assert rec["ready"] is False and rec["base_index"] == 3
    # Three merges leave 2 final colors, so base 3 (below colors 4) is refused.
    with pytest.raises(ColorsError, match="base 3 is not a color index of a 2-color palette"):
        run(sel5, tmp_path / "refused", flags={"extract": 5, "colors": 4, "base": 3,
                                               "merge": [[2, 0], [3, 0], [4, 1]]})
    assert not (tmp_path / "refused").exists()


def test_not_ready_preview_lists_extracted_colors_and_the_reason(not_ready):
    rec, out = not_ready
    img = np.array(Image.open(out / "regions.png"))
    h = rec["input"]["height_px"]
    k = len(rec["palette"])
    for e in rec["extraction"]["palette"]:
        top, left, bottom, right = extracted_swatch_box(e["index"], h, k)
        assert (img[top:bottom, left:right] == e["rgb"]).all(), e
    for p in rec["palette"]:
        top, left, bottom, right = swatch_box(p["index"], h)
        assert (img[top:bottom, left:right] == p["rgb"]).all(), p
    # Rows: legend (3), final colors, the extraction heading, extracted colors, not ready.
    rows = len(tdmg.colors.legend_rows("")) + k + 1 + len(rec["extraction"]["palette"]) + 1
    assert img.shape[0] == PREVIEW_SCALE * (h + ROW_PX * rows)


def test_ready_preview_has_no_reason_row(done):
    rec, out = done
    img = np.array(Image.open(out / "regions.png"))
    h = rec["input"]["height_px"]
    rows = (len(tdmg.colors.legend_rows("")) + len(rec["palette"]) + 1
            + len(rec["extraction"]["palette"]))
    assert img.shape[0] == PREVIEW_SCALE * (h + ROW_PX * rows)


def test_merge_index_beyond_the_extraction_is_refused(sel, tmp_path):
    # The test selection has 4 distinct colors, so extract 6 gives indices 0..3 only.
    with pytest.raises(ColorsError, match=r"merge \[5, 0\]: 5 is not an extraction index: "
                                          "the extraction has 4 colors"):
        run(sel, tmp_path / "out", flags={"merge": [[5, 0]]})
    assert not (tmp_path / "out").exists()


def test_an_explicit_outline_list_is_refused_until_task_7c(sel, tmp_path):
    with pytest.raises(ColorsError, match="not implemented yet"):
        run(sel, tmp_path / "out", flags={"outline_color": [3]})
    assert not (tmp_path / "out").exists()


def test_outline_none_and_keep_are_recorded(sel, tmp_path):
    rec = run(sel, tmp_path / "out", flags={"outline_color": "none", "outlines": "keep"})
    assert rec["outline"] == {"outlines": "keep", "outline_color": "none", "found_by": "none",
                              "family": [], "method": OUTLINE_METHOD,
                              "notes": [KEEP_NO_EFFECT_NOTE]}
    rec = run(sel, tmp_path / "auto", flags={"outlines": "keep"})
    assert rec["outline"]["notes"] == [OUTLINE_PLACEHOLDER_NOTE, KEEP_NO_EFFECT_NOTE]


def _set_ready(r):
    r["ready"], r["not_ready_reason"] = True, None


@pytest.mark.parametrize("change, message", [
    (lambda r: r["extraction"].update(extract=5), "extraction.extract"),
    (lambda r: r["quantize"].update(n_requested=5), "quantize.n_requested"),
    (lambda r: r["outline"].update(outlines="keep"), "outline.outlines"),
    (lambda r: r["outline"].update(outline_color="none"), "outline.outline_color"),
    (lambda r: r["outline"].update(method="x"), "outline.method"),
    (lambda r: r["merges"].append({"from": 3, "from_hex": "#000000", "into": 0,
                                   "into_hex": "#000000"}), "merges"),
    (lambda r: r.update(ready="yes"), "ready must be true or false"),
    (lambda r: r.update(not_ready_reason="x"), "ready is true but there is a"),
    (lambda r: r["extraction"].update(n_extracted=3), "extraction indices are not 0..n-1"),
    (lambda r: r["extraction"]["palette"][1].update(index=7),
     "extraction indices are not 0..n-1"),
    (lambda r: r["extraction"]["palette"][0].update(hex="#000000"),
     "not quantize.palette_hex"),
    (lambda r: r["extraction"]["palette"][1].update(merged_into=0),
     "merged_into is not the merge setting's"),
    (lambda r: r["extraction"]["palette"][1].update(final_index=0),
     "final_index is not the final palette entry"),
    (lambda r: r["extraction"]["palette"][1].update(final_index=True),
     "final_index is not the final palette entry"),
    (lambda r: r.pop("extraction"), "missing or has an invalid field"),
    (lambda r: r["extraction"]["palette"][1].update(fate="merged", final_index=None),
     "fate 'merged' but merged_into is not set"),
    (lambda r: r["extraction"]["palette"][1].update(fate="cleanup"),
     "fate 'cleanup'"),
    (lambda r: r["extraction"]["palette"][1].update(fate="outline", final_index=None),
     "fate 'outline' but it is not in outline.family"),
    (lambda r: r["extraction"]["palette"][1].update(fate="gone"), "fate 'gone'"),
    (lambda r: r["extraction"]["palette"][1].update(fate="final", final_index=None),
     "fate 'final' but final_index is not set"),
    (lambda r: r["outline"].update(family=[9]), "outline.family"),
    (lambda r: r["outline"].update(family=[1, 1]), "outline.family"),
    (lambda r: r["outline"].update(family=[2, 1]), "outline.family"),
    (lambda r: r["outline"].update(found_by="config"), "outline.found_by"),
])
def test_verify_colors_refuses_edited_extraction_fields(done, sel, tmp_path, change, message):
    d = _copy(done[1], tmp_path, "colors")
    _edit_record(d, change)
    with pytest.raises(ColorsError, match=message):
        verify_colors(d, sel)


def _two_final_colors_share_one_extraction(r):
    # Final entry 1 is no longer any extraction entry's final index (entry 1 now says 0).
    e = r["extraction"]["palette"][1]
    e["final_index"], e["hex"] = 0, r["palette"][0]["hex"]
    r["quantize"]["palette_hex"][1] = e["hex"]


def test_verify_colors_requires_every_final_color_to_come_from_an_extracted_one(
        done, sel, tmp_path):
    d = _copy(done[1], tmp_path, "colors")
    _edit_record(d, _two_final_colors_share_one_extraction)
    with pytest.raises(ColorsError, match="final color 1 .* is not the final_index of an "
                                          "extraction entry"):
        verify_colors(d, sel)


def test_verify_colors_checks_merge_hexes_and_cleanup_fates(sel5, tmp_path):
    cfg = tmp_path / "m.yaml"
    cfg.write_bytes(b"merge: [[4, 3]]\n")
    out = tmp_path / "out"
    run(sel5, out, flags={"extract": 5, "colors": 4, "edges": "exact"}, config_path=cfg)
    verify_colors(out, sel5)
    for change, message in (
            (lambda r: r["merges"][0].update(from_hex="#000001"), "merges' from_hex"),
            (lambda r: r["merges"][0].update(into_hex="#000001"), "merges' into_hex"),
            (lambda r: r["extraction"]["palette"][4].update(fate="final"),
             "fate 'final' but final_index is not set"),
            (lambda r: r["extraction"]["palette"][4].update(fate="cleanup"),
             "merged_into is set")):
        d = _copy(out, tmp_path, f"c{abs(hash(message))}")
        _edit_record(d, change)
        with pytest.raises(ColorsError, match=message):
            verify_colors(d, sel5)


def test_verify_colors_refuses_a_not_ready_plan_marked_ready(not_ready, sel5, tmp_path):
    d = _copy(not_ready[1], tmp_path, "colors")
    _edit_record(d, _set_ready)
    with pytest.raises(ColorsError, match="ready is true but the palette has 5 colors, more "
                                          "than colors 4"):
        verify_colors(d, sel5)


@pytest.mark.parametrize("change, message", [
    (lambda i: i["settings"].update(extract=1), "identity.settings.extract"),
    (lambda i: i["settings"].update(extract=True), "identity.settings.extract"),
    (lambda i: i["settings"].update(outlines="hide"), "identity.settings.outlines"),
    (lambda i: i["settings"].update(outline_color=[]), "identity.settings.outline_color"),
    (lambda i: i["settings"].update(merge=[[1, 1]]), "identity.settings.merge"),
    (lambda i: i["settings"].pop("extract"), "identity.settings must hold exactly"),
    (lambda i: i["settings"].update(extract=3), "extract 3 is below colors 4"),
    (lambda i: i["settings"].update(merge=[[7, 0]]), "7 is not an extraction index"),
    (lambda i: i["settings"].update(outline_color=[9]), "outline_color 9"),
])
def test_verify_colors_checks_the_new_identity_types(done, sel, tmp_path, change, message):
    d = _copy(done[1], tmp_path, "colors")
    _edit_record(d, _edit_identity(change))
    with pytest.raises(ColorsError, match=message):
        verify_colors(d, sel)


# The owner's images at the defaults (extract 6, colors 4, smooth, outline_color auto with
# Task 7b's placeholder, no merges), 60 mm. Measured on the Windows PC, 2026-11-11. The
# extracted palettes equal the N = 6 rows of the Task 7a record (outline-shade.txt). Without
# outline handling, cleanup removes Oddie's black lines (#0d100d) but keeps Roadie's three
# outline colors, so neither plan is ready.
OWNER_DEFAULT = {
    "roadie-tol30": {
        "extracted": ["#f60606", "#f5f5f5", "#960a0a", "#451812", "#f0f10a", "#746c5b"],
        "final": ["#f60606", "#f5f5f5", "#f0f10a", "#960a0a", "#451812", "#746c5b"],
        "to_final": [0, 1, 3, 4, 2, 5],
        "cleanup": (4, 18709, "0c8133f41e369083"),
    },
    "oddie": {
        "extracted": ["#25561b", "#547e9d", "#48a835", "#395266", "#0d100d", "#dd4f47"],
        "final": ["#25561b", "#48a835", "#547e9d", "#395266", "#dd4f47"],
        "to_final": [0, 2, 1, 3, None, 4],
        "cleanup": (4, 20385, "cfd188d8ce81ce71"),
    },
}


@pytest.mark.parametrize("name", ["roadie-tol30", "oddie"])
def test_owner_images_at_the_default_extraction(name, owner_selection, tmp_path):
    from conftest import SELECTIONS

    owner_selection(name)                     # skips if absent, fails if not the Task 1 files
    out = tmp_path / name
    t0 = time.perf_counter()
    rec = run(SELECTIONS / name, out)
    dt = time.perf_counter() - t0
    want = OWNER_DEFAULT[name]
    ext = rec["extraction"]["palette"]
    assert [e["hex"] for e in ext] == want["extracted"]
    assert [p["hex"] for p in rec["palette"]] == want["final"]
    assert [e["final_index"] for e in ext] == want["to_final"]
    labels = np.array(Image.open(out / "labels.png")).astype(np.int32)
    labels[labels == LABELS_OUTSIDE] = OUTSIDE
    digest = hashlib.sha256(labels.tobytes()).hexdigest()[:16]
    log = rec["cleanup"]
    assert (log["passes"], log["pixels_changed"], digest) == want["cleanup"]
    assert rec["ready"] is False
    assert rec["not_ready_reason"] == not_ready_reason(len(want["final"]), 4, 0, 4)
    with pytest.raises(ColorsError, match="not ready"):
        verify_colors(out, SELECTIONS / name)
    shares = [f"{e['hex']} {e['share']:.1%}" for e in ext]
    print(f"\n{name}: make_colors {dt:.2f} s; extracted {shares}; final {want['final']}; "
          f"{rec['not_ready_reason']}; colors_id {rec['colors_id']}")


def test_not_ready_reason_advises_raising_colors_only_below_the_cap():
    at_cap = not_ready_reason(6, 4, 0, 4)
    assert at_cap == ("6 colors remain after cleanup, but colors allows at most 4 (the "
                      "printer's palette); add merge pairs (by extraction index, from "
                      "regions.png) to the config file")
    assert "raise colors" not in at_cap
    below = not_ready_reason(5, 3, 1, 4)
    assert below.startswith("5 colors remain after 1 merge(s) and cleanup, but colors allows "
                            "at most 3; add merge pairs")
    assert below.endswith("or raise colors up to the printer's palette (4)")


def test_not_ready_at_and_below_the_cap_end_to_end(not_ready, sel5, tmp_path):
    assert "raise colors" not in not_ready[0]["not_ready_reason"]       # colors 4 = cap
    rec = run(sel5, tmp_path / "c3", flags={"extract": 5, "colors": 3, "edges": "exact"})
    assert rec["ready"] is False
    assert rec["not_ready_reason"] == not_ready_reason(5, 3, 0, 4)
    assert "or raise colors up to the printer's palette (4)" in rec["not_ready_reason"]


def test_not_ready_reason_names_the_outline_step_when_it_ran():
    assert not_ready_reason(5, 4, 2, 4, outline=True).startswith(
        "5 colors remain after outline handling, 2 merge(s) and cleanup, but")
    assert not_ready_reason(5, 4, 0, 4, outline=True).startswith(
        "5 colors remain after outline handling and cleanup, but")
    assert not_ready_reason(5, 4, 0, 4).startswith("5 colors remain after cleanup, but")


def test_cleanup_fate_is_recorded(tmp_path):
    # A one-pixel color that cleanup merges into its neighbour.
    rgba = np.zeros((60, 60, 4), np.uint8)
    rgba[5:55, 5:55] = (200, 30, 30, 255)
    rgba[30, 30] = (30, 30, 200, 255)
    sel = write_sel(tmp_path / "sel", rgba)
    out = tmp_path / "out"
    rec = run(sel, out, width_mm=5.0, flags={"colors": 2})
    ext = rec["extraction"]["palette"]
    assert [(e["fate"], e["final_index"]) for e in ext] == [("final", 0), ("cleanup", None)]
    assert ext[1]["hex"] in rec["cleanup"]["dropped_hex"]
    verify_colors(out, sel)
    d = _copy(out, tmp_path, "edited")
    _edit_record(d, lambda r: r["cleanup"].update(dropped_hex=[]))
    with pytest.raises(ColorsError, match="fate 'cleanup' but its hex is not in "
                                          "cleanup.dropped_hex"):
        verify_colors(d, sel)

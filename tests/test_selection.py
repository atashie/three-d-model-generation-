import json

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError
from selection_fixtures import (
    BIRD_SEED,
    DARK_LINE,
    DISC,
    DISC_SEED,
    GAP_BETWEEN_LEGS,
    RING_POINT,
    STROKE_POINT,
    empty,
    roadie_like,
    soft_blob,
    two_subjects,
)

from tdmg.rules import load_rules
from tdmg.selection import (
    Intake,
    SelectionError,
    SelectionSpec,
    load_image,
    load_mask,
    pixels_sha256,
    select_from_mask,
    select_subject,
)


def _at(img, p):
    x, y = p
    return img[y, x]


def _save(tmp_path, rgba, name="in.png", exif=None):
    p = tmp_path / name
    im = Image.fromarray(rgba)
    if exif is not None:
        im.save(p, exif=exif)
    else:
        im.save(p)
    return p


def test_fixtures_have_the_structure_they_claim():
    r = roadie_like()
    assert _at(r, DISC_SEED)[3] == 255 and tuple(_at(r, DISC_SEED)[:3]) == (57, 46, 40)
    assert tuple(_at(r, BIRD_SEED)[:3]) == (230, 20, 20)
    assert _at(r, RING_POINT)[3] == 255
    s = soft_blob()
    assert 0 < np.count_nonzero((s[..., 3] > 0) & (s[..., 3] < 255))   # soft edges exist
    assert _at(s, STROKE_POINT)[3] >= 128
    assert 30 < np.linalg.norm(np.subtract(DARK_LINE, DISC)) < 80   # kept at 30, cut at 80


def test_load_image_hashes_and_keeps_rgba(tmp_path):
    p = _save(tmp_path, roadie_like())
    a = load_image(p)
    assert a.rgba.shape == (200, 200, 4) and a.rgba.dtype == np.uint8
    assert len(a.file_sha256) == 64 and len(a.pixels_sha256) == 64
    assert a.source_name == "in.png" and a.exif_transposed is False
    assert load_image(p).pixels_sha256 == a.pixels_sha256


def test_load_image_applies_exif_orientation(tmp_path):
    exif = Image.Exif()
    exif[0x0112] = 6                       # rotate 90 degrees clockwise to display
    p = _save(tmp_path, np.zeros((10, 20, 4), np.uint8), exif=exif)
    a = load_image(p)
    assert a.rgba.shape[:2] == (20, 10) and a.exif_transposed is True


def test_load_image_ignores_out_of_range_orientation(tmp_path):
    exif = Image.Exif()
    exif[0x0112] = 9                       # not a valid Orientation; Pillow does not transpose
    p = _save(tmp_path, np.zeros((10, 20, 4), np.uint8), exif=exif)
    a = load_image(p)
    assert a.rgba.shape[:2] == (10, 20) and a.exif_transposed is False


def test_pixels_sha256_changes_with_one_pixel(tmp_path):
    img = roadie_like()
    a = load_image(_save(tmp_path, img, "a.png"))
    img[0, 0, 0] ^= 1
    b = load_image(_save(tmp_path, img, "b.png"))
    assert a.pixels_sha256 != b.pixels_sha256


def test_pixels_sha256_ignores_file_encoding(tmp_path):
    img = roadie_like()
    png = load_image(_save(tmp_path, img, "x.png"))
    tif = load_image(_save(tmp_path, img, "x.tif"))
    assert np.array_equal(tif.rgba, img)                    # TIFF round-trip is lossless
    assert png.pixels_sha256 == tif.pixels_sha256
    assert png.file_sha256 != tif.file_sha256


def _palette_png(tmp_path):
    im = Image.new("P", (4, 4), 0)
    im.putpalette([10, 20, 30, 200, 0, 0] + [0] * 762)
    im.putpixel((1, 1), 1)
    p = tmp_path / "p.png"
    im.save(p, transparency=0)
    return p, {(0, 0): (10, 20, 30, 0), (1, 1): (200, 0, 0, 255)}


def _la_png(tmp_path):
    p = tmp_path / "la.png"
    Image.new("LA", (2, 2), (100, 50)).save(p)
    return p, {(0, 0): (100, 100, 100, 50)}


@pytest.mark.parametrize("make", [_palette_png, _la_png], ids=["palette-transparency", "LA"])
def test_load_image_keeps_alpha_of_8bit_modes(tmp_path, make):
    p, expected = make(tmp_path)
    a = load_image(p)
    for point, rgba in expected.items():
        assert tuple(_at(a.rgba, point)) == rgba


def _gray16_png(tmp_path):
    p = tmp_path / "g16.png"
    Image.fromarray(np.tile(np.arange(0, 65536, 4096, dtype=np.uint16), (4, 1))).save(p)
    return p


def _two_frame_gif(tmp_path):
    p = tmp_path / "two.gif"
    frames = [Image.new("RGB", (4, 4), c) for c in ("red", "blue")]
    frames[0].save(p, save_all=True, append_images=frames[1:])
    return p


def _garbage(tmp_path):
    p = tmp_path / "junk.png"
    p.write_bytes(b"not an image")
    return p


def _truncated_png(tmp_path):
    full = tmp_path / "full.png"
    Image.fromarray(np.zeros((200, 200), np.uint8)).save(full)   # 4x4 fails at open instead
    data = full.read_bytes()
    p = tmp_path / "cut.png"
    p.write_bytes(data[:len(data) // 2])          # valid header, missing pixel data
    return p


@pytest.mark.parametrize("make, message", [
    (_gray16_png, "16-bit"),
    (_two_frame_gif, "2 frames"),
    (_garbage, "not a readable image"),
    (_truncated_png, "not a readable image"),
], ids=["16-bit", "multi-frame", "garbage", "truncated"])
def test_load_image_rejects_inputs_it_cannot_decode_faithfully(tmp_path, make, message):
    with pytest.raises(SelectionError, match=message):
        load_image(make(tmp_path))


def _intake(rgba):
    return Intake(rgba, "f" * 64, pixels_sha256(rgba), False, "x.png")


def _m(sel, p):
    x, y = p
    return bool(sel.mask[y, x])


def test_roadie_like_remove_disc_then_keep_bird():
    sel = select_subject(_intake(roadie_like()),
                         SelectionSpec(remove_at=((30, 100),), keep_at=((100, 80),)))
    assert _m(sel, BIRD_SEED) and not _m(sel, DISC_SEED)
    assert not _m(sel, GAP_BETWEEN_LEGS) and not _m(sel, RING_POINT)
    assert _m(sel, (70, 143)) and _m(sel, (130, 143))          # both shoes kept
    assert sel.result["status"] == "one_piece"
    assert sel.controls["source"] == "controls"


def test_high_tolerance_cuts_the_feet_off():
    sel = select_subject(_intake(roadie_like()), SelectionSpec(
        remove_at=((30, 100),), keep_at=((100, 80),), color_tolerance=80))
    assert not _m(sel, (70, 143))
    assert sel.steps[-1]["pieces_before"] > 2


def test_frame_is_kept_when_not_removed():
    sel = select_subject(_intake(roadie_like()), SelectionSpec())
    assert _m(sel, DISC_SEED) and sel.result["status"] == "multiple_pieces"


def test_defaults_come_from_the_rules_registry():
    rules = load_rules()
    sel = select_subject(_intake(roadie_like()), SelectionSpec())
    c = sel.controls
    assert c["alpha_min"] == {"value": rules["perception.alpha.min_opaque"].default,
                              "rule": "perception.alpha.min_opaque"}
    assert c["color_tolerance"]["rule"] == "perception.flood.color_tolerance"
    explicit = select_subject(_intake(roadie_like()), SelectionSpec(color_tolerance=12))
    assert explicit.controls["color_tolerance"] == {"value": 12.0, "rule": None}


def test_soft_edges_keep_the_thin_stroke():
    sel = select_subject(_intake(soft_blob()), SelectionSpec())
    assert _m(sel, STROKE_POINT) and sel.result["status"] == "one_piece"


def test_two_subjects_need_a_keep_point():
    sel = select_subject(_intake(two_subjects()), SelectionSpec())
    assert sel.result["status"] == "multiple_pieces"
    assert any("--keep-at" in w for w in sel.result["warnings"])
    one = select_subject(_intake(two_subjects()), SelectionSpec(keep_at=((30, 30),)))
    assert one.result["status"] == "one_piece" and not one.mask[30, 90]


def test_empty_image_does_not_crash():
    sel = select_subject(_intake(empty()), SelectionSpec())
    assert sel.result["status"] == "empty" and sel.result["selected_px"] == 0


def test_instructions_alone_are_reported_as_not_applied():
    sel = select_subject(_intake(two_subjects()), SelectionSpec(instructions="only the left one"))
    assert sel.interpretation == {"text": "only the left one", "machine_interpreted": False}
    assert any("not machine-interpreted" in w for w in sel.result["warnings"])


def test_holes_are_counted():
    img = two_subjects()
    img[28:33, 28:33, 3] = 0                     # a 5x5 hole inside the left circle
    sel = select_subject(_intake(img), SelectionSpec(keep_at=((15, 30),)))
    assert sel.result["holes_px"] == [25]


@pytest.mark.parametrize("spec, message", [
    (SelectionSpec(remove_at=((500, 5),)), "remove_at point 500,5 is outside the 200x200"),
    (SelectionSpec(remove_at=((0, 0),)), "remove_at point 0,0 is not in the current selection"),
    (SelectionSpec(remove_at=((30, 100),), keep_at=((30, 100),)),
     "keep_at point 30,100 is not in the current selection"),
    (SelectionSpec(remove_at=((30, 100), (30, 100))),
     "remove_at point 30,100 is not in the current selection"),
    (SelectionSpec(keep_at=((100, 80), (100, 80))), "duplicate keep_at point 100,80"),
], ids=["outside", "transparent", "keep-removed", "duplicate-remove", "duplicate-keep"])
def test_unusable_points_raise(spec, message):
    with pytest.raises(SelectionError, match=message):
        select_subject(_intake(roadie_like()), spec)


@pytest.mark.parametrize("point", [(1.5, 2), (True, 2), ("3", 2)], ids=["float", "bool", "str"])
def test_points_must_be_integers(point):
    with pytest.raises(ValidationError):
        SelectionSpec(keep_at=(point,))


@pytest.mark.parametrize("spec, message", [
    (SelectionSpec(alpha_min=0),
     r"alpha_min 0 is outside perception\.alpha\.min_opaque range \[1, 255\]"),
    (SelectionSpec(alpha_min=256),
     r"alpha_min 256 is outside perception\.alpha\.min_opaque range \[1, 255\]"),
    (SelectionSpec(color_tolerance=-1),
     r"color_tolerance -1 is outside perception\.flood\.color_tolerance range \[0, 441\.7\]"),
    (SelectionSpec(color_tolerance=500),
     r"color_tolerance 500 is outside perception\.flood\.color_tolerance range"),
], ids=["alpha-0", "alpha-256", "tolerance-negative", "tolerance-500"])
def test_controls_outside_the_rule_range_raise(spec, message):
    with pytest.raises(SelectionError, match=message):
        select_subject(_intake(roadie_like()), spec)


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_tolerance_is_refused_at_construction(value):
    with pytest.raises(ValidationError):
        SelectionSpec(color_tolerance=value)


def test_range_edges_are_accepted():
    for spec in (SelectionSpec(alpha_min=1), SelectionSpec(alpha_min=255),
                 SelectionSpec(color_tolerance=0), SelectionSpec(color_tolerance=441.7)):
        select_subject(_intake(roadie_like()), spec)


def test_tolerance_zero_removes_only_the_exact_colour():
    img = roadie_like()
    sel = select_subject(_intake(img), SelectionSpec(remove_at=(DISC_SEED,), color_tolerance=0))
    removed = (img[..., 3] >= 128) & ~sel.mask
    assert (img[removed][:, :3] == DISC).all()
    exact = (img[..., :3] == DISC).all(axis=-1) & (img[..., 3] == 255)
    assert sel.steps[1]["removed_px"] == removed.sum() == exact.sum()
    assert _m(sel, BIRD_SEED) and _m(sel, RING_POINT)


def test_keep_step_does_not_share_the_controls_list():
    sel = select_subject(_intake(roadie_like()),
                         SelectionSpec(remove_at=(DISC_SEED,), keep_at=(BIRD_SEED,)))
    assert sel.steps[-1]["points"] == sel.controls["keep_at"]
    assert sel.steps[-1]["points"] is not sel.controls["keep_at"]


def test_selection_is_deterministic_in_process():
    spec = SelectionSpec(remove_at=(DISC_SEED,), keep_at=(BIRD_SEED,), instructions="bird")
    a, b = (select_subject(_intake(roadie_like()), spec) for _ in range(2))
    assert np.array_equal(a.mask, b.mask)
    assert (a.controls, a.steps, a.result, a.interpretation) ==            (b.controls, b.steps, b.result, b.interpretation)


def _mask_file(tmp_path, arr, name="m.png"):
    p = tmp_path / name
    Image.fromarray(arr).save(p)
    return p


def test_user_mask_replaces_controls(tmp_path):
    m = np.zeros((200, 200), np.uint8)
    m[60:100, 65:135] = 255
    m[0, 0] = 255                                   # a transparent pixel in the image
    sel = select_from_mask(_intake(roadie_like()), load_mask(_mask_file(tmp_path, m), (200, 200)),
                           SelectionSpec(instructions="just the body"))
    assert sel.controls["source"] == "user_mask" and sel.mask.sum() == 40 * 70 + 1
    assert any("transparent" in w for w in sel.result["warnings"])
    assert not any("not machine-interpreted" in w for w in sel.result["warnings"])


def test_bad_user_masks_raise(tmp_path):
    grey = np.full((200, 200), 100, np.uint8)
    with pytest.raises(SelectionError, match="0 and 255"):
        load_mask(_mask_file(tmp_path, grey), (200, 200))
    with pytest.raises(SelectionError, match="size"):
        load_mask(_mask_file(tmp_path, np.zeros((5, 5), np.uint8), "s.png"), (200, 200))
    with pytest.raises(SelectionError, match="either"):
        select_from_mask(_intake(roadie_like()), np.zeros((200, 200), bool),
                         SelectionSpec(remove_at=((30, 100),)))


@pytest.mark.parametrize("make, message", [
    (_gray16_png, "16-bit"),
    (_two_frame_gif, "2 frames"),
    (_garbage, "not a readable image"),
    (_truncated_png, "not a readable image"),
], ids=["16-bit", "multi-frame", "garbage", "truncated"])
def test_load_mask_rejects_files_it_cannot_decode_faithfully(tmp_path, make, message):
    with pytest.raises(SelectionError, match=message):
        load_mask(make(tmp_path), (4, 4))


def test_load_mask_rejects_an_exif_rotation(tmp_path):
    exif = Image.Exif()
    exif[0x0112] = 6
    p = tmp_path / "rot.png"
    Image.fromarray(np.zeros((4, 4), np.uint8)).save(p, exif=exif)
    with pytest.raises(SelectionError, match="EXIF rotation"):
        load_mask(p, (4, 4))


def test_load_mask_accepts_orientation_one(tmp_path):
    exif = Image.Exif()
    exif[0x0112] = 1
    p = tmp_path / "one.png"
    Image.fromarray(np.zeros((4, 4), np.uint8)).save(p, exif=exif)
    assert load_mask(p, (4, 4)).shape == (4, 4)


@pytest.mark.parametrize("mask", [
    np.zeros((100, 200), bool),                  # wrong shape
    np.zeros((200, 200, 1), bool),               # not 2-D
    np.zeros((200, 200), np.uint8),              # not bool
], ids=["wrong-shape", "3-d", "uint8"])
def test_select_from_mask_validates_its_array(mask):
    with pytest.raises(SelectionError, match="mask"):
        select_from_mask(_intake(roadie_like()), mask, SelectionSpec())


def test_records_are_strict_json(tmp_path):
    m = np.zeros((200, 200), np.uint8)
    m[60:100, 65:135] = 255
    sels = [select_subject(_intake(roadie_like()),
                           SelectionSpec(remove_at=(DISC_SEED,), keep_at=(BIRD_SEED,))),
            select_from_mask(_intake(roadie_like()),
                             load_mask(_mask_file(tmp_path, m), (200, 200)), SelectionSpec())]
    for sel in sels:
        record = {"controls": sel.controls, "steps": sel.steps, "result": sel.result,
                  "interpretation": sel.interpretation}
        assert json.loads(json.dumps(record, allow_nan=False)) == record


def test_mask_mode_records_only_the_controls_it_uses(tmp_path):
    mask = np.zeros((200, 200), bool)
    sel = select_from_mask(_intake(roadie_like()), mask, SelectionSpec())
    assert set(sel.controls) == {"alpha_min", "source", "user_mask_sha256"}
    with pytest.raises(SelectionError, match="--tolerance has no effect with --mask"):
        select_from_mask(_intake(roadie_like()), mask, SelectionSpec(color_tolerance=30))


def _rgba_mask(tmp_path, alpha):
    a = np.zeros((4, 4, 4), np.uint8)
    a[:2, ..., :3] = 255                 # top half white
    a[..., 3] = 255
    a[0, 0, 3] = alpha
    return _mask_file(tmp_path, a, f"rgba{alpha}.png")


def _p_mask_with_transparency(tmp_path):
    im = Image.new("P", (4, 4), 0)
    im.putpalette([0, 0, 0, 255, 255, 255] + [0] * 762)
    im.putpixel((1, 1), 1)
    p = tmp_path / "pt.png"
    im.save(p, transparency=1)
    return p


def _la_mask(tmp_path):
    p = tmp_path / "la.png"
    Image.new("LA", (4, 4), (255, 0)).save(p)
    return p


@pytest.mark.parametrize("make", [lambda t: _rgba_mask(t, 0), _p_mask_with_transparency,
                                  _la_mask], ids=["RGBA", "P-transparency", "LA"])
def test_load_mask_refuses_transparency(tmp_path, make):
    with pytest.raises(SelectionError, match="mask has transparent pixels"):
        load_mask(make(tmp_path), (4, 4))


def test_load_mask_accepts_opaque_rgba(tmp_path):
    m = load_mask(_rgba_mask(tmp_path, 255), (4, 4))
    assert m[:2].all() and not m[2:].any()

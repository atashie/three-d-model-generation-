import numpy as np
from PIL import Image
from selection_fixtures import (
    BIRD_SEED,
    DISC_SEED,
    RING_POINT,
    STROKE_POINT,
    roadie_like,
    soft_blob,
)

from tdmg.selection import load_image


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

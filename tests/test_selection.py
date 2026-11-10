import numpy as np
from selection_fixtures import (
    BIRD_SEED,
    DISC_SEED,
    RING_POINT,
    STROKE_POINT,
    roadie_like,
    soft_blob,
)


def _at(img, p):
    x, y = p
    return img[y, x]


def test_fixtures_have_the_structure_they_claim():
    r = roadie_like()
    assert _at(r, DISC_SEED)[3] == 255 and tuple(_at(r, DISC_SEED)[:3]) == (57, 46, 40)
    assert tuple(_at(r, BIRD_SEED)[:3]) == (230, 20, 20)
    assert _at(r, RING_POINT)[3] == 255
    s = soft_blob()
    assert 0 < np.count_nonzero((s[..., 3] > 0) & (s[..., 3] < 255))   # soft edges exist
    assert _at(s, STROKE_POINT)[3] >= 128

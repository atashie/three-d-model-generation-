"""After the float64 change (flat-3): how far does smooth_outline's contour reach beyond the
image box [0, W] x [0, H]? The same kinds of masks as the 2026-11-11 float32 measurement
(tests/test_smooth_labels.py): full-image masks, and random masks with foreground on two
borders, at sizes 20 x 20 to 2000 x 1500 and sigma 0.6 to 10 (where 8 sigma fits)."""
import numpy as np

from tdmg.smoothing import smooth_outline

SIZES = [(20, 20), (40, 60), (101, 77), (300, 500), (1000, 800), (1500, 2000)]
SIGMAS = [0.6, 1.0, 1.5, 2.5, 4.0, 6.0, 10.0]


def overshoot(mask, sigma):
    h, w = mask.shape
    minx, miny, maxx, maxy = smooth_outline(mask, sigma).bounds
    return max(-minx, -miny, maxx - w, maxy - h, 0.0)


rng = np.random.default_rng(0)
worst_ratio = 0.0
for sigma in SIGMAS:
    worst = 0.0
    for h, w in SIZES:
        if 8 * sigma > min(h, w):
            continue
        masks = [np.ones((h, w), bool)]
        for _ in range(3 if h * w < 1e6 else 1):
            m = rng.random((h, w)) < 0.6
            m[:, :3] = True
            m[:3, :] = True
            masks.append(m)
        for m in masks:
            worst = max(worst, overshoot(m, sigma))
    worst_ratio = max(worst_ratio, worst / sigma)
    print(f"sigma {sigma}: worst overshoot {worst:.3g} px")
print(f"worst overshoot / sigma: {worst_ratio:.3g}")

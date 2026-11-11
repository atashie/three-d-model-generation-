"""Tests for tdmg.color.quantize (docs/plans/2026-11-11-color-palette.md, Task 3).

The synthetic images are built here. Expected palettes are derived from the method
(weighted means in CIELAB, rounded to sRGB), not read off the output.
"""

import hashlib
import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tdmg import color
from tdmg.color import ColorError, Quantized, lab_to_srgb8, quantize, srgb_to_lab

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research" / "verification" / "2026-11-11-color-palette"
SELECTIONS = ROOT / "artifacts" / "selection-runs"


def hexes(rgbs) -> list[str]:
    return ["#" + "".join(f"{int(v):02x}" for v in c) for c in rgbs]


def full_mask(img: np.ndarray) -> np.ndarray:
    return np.ones(img.shape[:2], bool)


def weighted_mean_hex(colors_counts) -> str:
    """The rounded sRGB of the count-weighted CIELAB mean of (rgb, count) pairs."""
    lab = srgb_to_lab(np.array([c for c, _ in colors_counts], np.uint8))
    w = np.array([n for _, n in colors_counts], np.float64)
    return hexes([lab_to_srgb8((lab * w[:, None]).sum(0) / w.sum())])[0]


# --- CIELAB conversion ------------------------------------------------------------------

# Reference values: the W3C CSS Color Module Level 4 sample code (section 19, "Sample code
# for Color Conversions", https://www.w3.org/TR/2026/CRD-css-color-4-20261103/), run in
# Node.js on 2026-11-11 with its own multiply-matrices.js: lin_sRGB, then
# lin_sRGB_to_XYZ, then XYZ_to_Lab fed XYZ * D50 / D65 (XYZ_to_Lab divides by its D50
# white, so this gives CIELAB relative to the spec's D65 white, with no chromatic
# adaptation). The printed values are copied here as Node printed them.
LAB_REFERENCES = [
    ((255, 255, 255), (100.0, 0.0, 0.0)),
    ((0, 0, 0), (0.0, 0.0, 0.0)),
    ((255, 0, 0), (53.23711559542937, 80.09011352310385, 67.20326351172214)),
    ((0, 255, 0), (87.73551910966, -86.18159689039895, 83.18662027363)),
    ((0, 0, 255), (32.30087290398018, 79.1952703074042, -107.85546553974265)),
]


def test_lab_reference_values():
    rgb = np.array([r for r, _ in LAB_REFERENCES], np.uint8)
    want = np.array([lab for _, lab in LAB_REFERENCES])
    # 1e-9: both are float64 evaluations of the same formulas; only the operation order
    # differs (numpy against JavaScript), which moves the last few bits, not the 9th decimal.
    np.testing.assert_allclose(srgb_to_lab(rgb), want, rtol=0, atol=1e-9)


def test_lab_round_trip_references_and_grid():
    rgb = np.array([r for r, _ in LAB_REFERENCES], np.uint8)
    np.testing.assert_array_equal(lab_to_srgb8(srgb_to_lab(rgb)), rgb)
    levels = np.arange(0, 256, 5)  # 52 levels per channel, 140,608 colors, includes 0 and 255
    grid = np.stack(np.meshgrid(levels, levels, levels, indexing="ij"), -1).reshape(-1, 3)
    grid = grid.astype(np.uint8)
    np.testing.assert_array_equal(lab_to_srgb8(srgb_to_lab(grid)), grid)


def test_lab_to_srgb8_clips_out_of_gamut():
    out = lab_to_srgb8(np.array([[150.0, 0, 0], [-10.0, 0, 0], [50.0, 300.0, 0]]))
    assert out.dtype == np.uint8
    assert out[0].tolist() == [255, 255, 255]
    assert out[1].tolist() == [0, 0, 0]


# --- quantize: synthetic images ---------------------------------------------------------


def test_exact_flat_shapes_give_their_colors_and_areas():
    img = np.zeros((40, 50, 3), np.uint8)
    img[:, :] = (240, 240, 240)          # 40*50 - 600 - 300 = 1100 px
    img[0:20, 0:30] = (200, 30, 30)      # 600 px
    img[25:35, 20:50] = (30, 60, 200)    # 300 px
    q = quantize(img, full_mask(img), 3)
    assert isinstance(q, Quantized)
    assert q.hex == ("#f0f0f0", "#c81e1e", "#1e3cc8")
    assert q.counts == (1100, 600, 300)
    assert q.shares == pytest.approx((0.55, 0.30, 0.15))
    assert q.rgb.dtype == np.uint8 and q.rgb.shape == (3, 3)
    assert (q.labels[0:20, 0:30] == 1).all()
    assert (q.labels[25:35, 20:50] == 2).all()
    assert q.converged and q.dropped == 0
    assert q.n_requested == 3 and q.n_distinct_colors == 3
    np.testing.assert_allclose(q.lab, srgb_to_lab(q.rgb))


def test_anti_aliased_edge_gives_core_colors_and_edge_pixels_to_nearest():
    red, white = np.array([210, 20, 20]), np.array([245, 245, 245])
    blend_r = np.rint(0.75 * red + 0.25 * white).astype(np.uint8)  # nearer red
    blend_w = np.rint(0.25 * red + 0.75 * white).astype(np.uint8)  # nearer white
    img = np.zeros((100, 102, 3), np.uint8)
    img[:, :50] = red
    img[:, 50] = blend_r
    img[:, 51] = blend_w
    img[:, 52:] = white
    q = quantize(img, full_mask(img), 2)
    # Each core takes its nearer blend column, so each palette color is the rounded
    # weighted mean of 5000 core and 100 blend pixels: within a fiftieth of the blend's
    # distance of the core, plus rounding.
    exp_red = weighted_mean_hex([(tuple(red), 5000), (tuple(blend_r), 100)])
    exp_white = weighted_mean_hex([(tuple(white), 5000), (tuple(blend_w), 100)])
    assert set(q.hex) == {exp_red, exp_white}
    r = q.hex.index(exp_red)
    w = q.hex.index(exp_white)
    assert (q.labels[:, :51] == r).all()
    assert (q.labels[:, 51:] == w).all()
    lab_core = srgb_to_lab(np.array([red, white], np.uint8))
    lab_blend = srgb_to_lab(np.array([blend_r, blend_w], np.uint8))
    # The weighted mean moves at most (100 / 5100) of the blend's distance from the core
    # (triangle inequality); rounding to 8 bits moves it at most half a level per channel,
    # bounded here by the largest move to any of the 26 neighbours one level away.
    shift_bound = np.linalg.norm(lab_blend - lab_core, axis=1) * 100 / 5100
    steps = np.stack(np.meshgrid(*[[-1, 0, 1]] * 3, indexing="ij"), -1).reshape(-1, 3)
    for k, core in ((r, 0), (w, 1)):
        nb = np.clip(q.rgb[k].astype(int) + steps, 0, 255).astype(np.uint8)
        round_bound = np.linalg.norm(srgb_to_lab(nb) - q.lab[k], axis=1).max()
        assert np.linalg.norm(q.lab[k] - lab_core[core]) <= shift_bound[core] + round_bound


def test_five_separated_colors_squeezed_to_four_merge_the_closest_pair():
    colors = [(0, 0, 0), (255, 255, 255), (0, 0, 255), (255, 0, 0), (235, 0, 0)]
    img = np.zeros((10, 50, 3), np.uint8)
    for i, c in enumerate(colors):
        img[:, 10 * i:10 * (i + 1)] = c
    lab = srgb_to_lab(np.array(colors, np.uint8))
    d = np.linalg.norm(lab[:, None] - lab[None], axis=2) + np.eye(5) * 1e9
    assert np.unravel_index(np.argmin(d), d.shape) in ((3, 4), (4, 3))  # the red pair
    q = quantize(img, full_mask(img), 4)
    merged = weighted_mean_hex([((255, 0, 0), 100), ((235, 0, 0), 100)])
    assert q.hex[0] == merged and q.counts[0] == 200
    assert set(q.hex[1:]) == {"#000000", "#ffffff", "#0000ff"}
    assert q.counts[1:] == (100, 100, 100)


def farthest_point_seeds(lab, counts, n):
    """The unweighted seeding Task 1 rejected: each next seed maximises dmin alone."""
    seeds = [int(np.argmax(counts))]
    dmin = np.linalg.norm(lab - lab[seeds[0]], axis=1)
    while len(seeds) < n:
        s = int(np.argmax(dmin))
        seeds.append(s)
        dmin = np.minimum(dmin, np.linalg.norm(lab - lab[s], axis=1))
    return seeds


def test_weights_matter_large_area_outweighs_small_outlier():
    green, slate, magenta = (40, 120, 40), (80, 100, 130), (255, 0, 255)
    img = np.zeros((100, 100, 3), np.uint8)
    img[:, :60] = green           # 6000 px
    img[:, 60:] = slate           # 3920 px
    img[0:2, 60:] = magenta       # 80 px outlier (0.8%)
    mask = full_mask(img)
    uniq, _, counts, ulab = color._unique_colors(img[mask])
    by_packed = {0x287828: "green", 0x506482: "slate", 0xFF00FF: "magenta"}
    assert sorted(by_packed) == [int(u) for u in uniq]
    # Farthest-point seeding would spend the second color on the outlier ...
    fp = farthest_point_seeds(ulab, counts, 2)
    assert [by_packed[int(uniq[s])] for s in fp] == ["green", "magenta"]
    # ... the count-weighted seeding picks the large slate area.
    seeds = color._seed(ulab, counts, 2)
    assert [by_packed[int(uniq[s])] for s in seeds] == ["green", "slate"]
    q = quantize(img, mask, 2)
    lab_m = srgb_to_lab(np.array([magenta], np.uint8))[0]
    lab_g, lab_s = srgb_to_lab(np.array([green, slate], np.uint8))
    nearer_slate = np.linalg.norm(lab_m - lab_s) < np.linalg.norm(lab_m - lab_g)
    assert nearer_slate
    assert q.hex == ("#287828", weighted_mean_hex([(slate, 3920), (magenta, 80)]))


def noisy_image(seed: int = 0, shape=(30, 40)) -> np.ndarray:
    """Four color centres with noise: many unique colors, a realistic k-means input."""
    rng = np.random.default_rng(seed)  # the test input only; quantize uses no randomness
    centres = np.array([[200, 40, 40], [40, 160, 60], [230, 230, 220], [30, 30, 90]])
    pick = rng.integers(0, 4, size=shape)
    img = centres[pick] + rng.integers(-25, 26, size=shape + (3,))
    return np.clip(img, 0, 255).astype(np.uint8)


def test_same_input_same_output_and_pixel_order_does_not_matter():
    img = noisy_image()
    mask = np.zeros(img.shape[:2], bool)
    mask[3:27, 5:35] = True
    a, b = quantize(img, mask, 4), quantize(img.copy(), mask.copy(), 4)
    np.testing.assert_array_equal(a.labels, b.labels)
    np.testing.assert_array_equal(a.rgb, b.rgb)
    assert (a.hex, a.counts, a.iterations) == (b.hex, b.counts, b.iterations)
    # Shuffle the masked pixels among the masked positions.
    rows, cols = np.nonzero(mask)
    perm = np.random.default_rng(1).permutation(len(rows))
    shuffled = img.copy()
    shuffled[rows, cols] = img[rows[perm], cols[perm]]
    c = quantize(shuffled, mask, 4)
    assert c.hex == a.hex and c.counts == a.counts and c.iterations == a.iterations
    np.testing.assert_array_equal(c.rgb, a.rgb)
    np.testing.assert_array_equal(c.labels[rows, cols], a.labels[rows[perm], cols[perm]])
    assert (c.labels[~mask] == -1).all()


def test_pixels_outside_the_mask_are_ignored():
    img = noisy_image(2)
    mask = np.zeros(img.shape[:2], bool)
    mask[5:25, 10:30] = True
    a = quantize(img, mask, 3)
    other = img.copy()
    other[~mask] = noisy_image(3)[~mask] // 2 + 100
    b = quantize(other, mask, 3)
    np.testing.assert_array_equal(a.labels, b.labels)
    assert a.hex == b.hex and a.counts == b.counts
    assert (a.labels[~mask] == color.OUTSIDE).all()
    assert color.OUTSIDE == -1
    assert sum(a.counts) == mask.sum()


def test_fewer_distinct_colors_than_n_gives_fewer_reported():
    img = np.zeros((10, 10, 3), np.uint8)
    img[:, 5:] = (255, 255, 0)
    q = quantize(img, full_mask(img), 4)
    assert q.hex == ("#000000", "#ffff00") or q.hex == ("#ffff00", "#000000")
    assert q.n_requested == 4 and q.n_distinct_colors == 2 and len(q.hex) == 2
    assert q.dropped == 0
    one = quantize(img, full_mask(img), 1)
    assert len(one.hex) == 1 and one.counts == (100,)


def test_every_label_is_the_nearest_rounded_palette_color():
    img = noisy_image(4, (50, 60))
    mask = full_mask(img)
    for n in (2, 3, 4):
        q = quantize(img, mask, n)
        lab = srgb_to_lab(img[mask])
        d = np.linalg.norm(lab[:, None, :] - q.lab[None, :, :], axis=2)
        np.testing.assert_array_equal(q.labels[mask], np.argmin(d, axis=1))
        np.testing.assert_array_equal(np.bincount(q.labels[mask], minlength=len(q.hex)),
                                      q.counts)
        assert sum(q.shares) == pytest.approx(1.0)


def test_order_is_area_descending_then_lab():
    img = noisy_image(5, (50, 60))
    q = quantize(img, full_mask(img), 4)
    keys = [(-c, *lab) for c, lab in zip(q.counts, q.lab.tolist())]
    assert keys == sorted(keys)
    # Equal areas fall back to L*: black (L* 0) before white (L* 100).
    img2 = np.zeros((4, 4, 3), np.uint8)
    img2[:, 2:] = 255
    assert quantize(img2, full_mask(img2), 2).hex == ("#000000", "#ffffff")


def test_palette_entry_left_without_pixels_is_dropped_and_reported():
    """Two centroids that round to the same hex: the second gets no pixel (ties go to the
    lowest index) and is dropped. Built at the finishing step, where it happens."""
    px = np.array([[100, 100, 100]] * 3 + [[0, 0, 0]], np.uint8)
    _, inverse, counts, ulab = color._unique_colors(px)
    grey = srgb_to_lab(np.array([[100, 100, 100]], np.uint8))[0]
    cent = np.array([srgb_to_lab(np.array([[0, 0, 0]], np.uint8))[0], grey, grey + 1e-6])
    labels, rgb, counts_out, dropped = color._finish(ulab, counts, inverse, cent)
    assert dropped == 1
    assert hexes(rgb) == ["#646464", "#000000"]
    assert counts_out.tolist() == [3, 1]
    assert labels.tolist() == [0, 0, 0, 1]


def test_invalid_input_is_refused():
    img = np.zeros((4, 4, 3), np.uint8)
    with pytest.raises(ColorError, match="n must be"):
        quantize(img, full_mask(img), 0)
    with pytest.raises(ColorError, match="n must be"):
        quantize(img, full_mask(img), True)
    with pytest.raises(ColorError, match="uint8"):
        quantize(img.astype(np.float64), full_mask(img), 2)
    with pytest.raises(ColorError, match=r"\(H, W, 3\)"):
        quantize(np.zeros((4, 4, 4), np.uint8), full_mask(img), 2)
    with pytest.raises(ColorError, match="mask"):
        quantize(img, np.ones((4, 5), bool), 2)
    with pytest.raises(ColorError, match="mask"):
        quantize(img, np.ones((4, 4), np.uint8), 2)
    with pytest.raises(ColorError, match="no pixel"):
        quantize(img, np.zeros((4, 4), bool), 2)


def test_result_arrays_are_read_only():
    img = noisy_image()
    q = quantize(img, full_mask(img), 2)
    for arr in (q.labels, q.rgb, q.lab):
        with pytest.raises(ValueError):
            arr[...] = 0


# --- Fixtures from the owner's images (Task 1 record) ------------------------------------


def _research_rows():
    """Parse the kmeans_w rows and palettes from the Task 1 results.txt."""
    text = (RESEARCH / "results.txt").read_text(encoding="utf-8")
    out = {}
    for block in text.split("\n== ")[1:]:
        name = block.split(":", 1)[0]
        m = re.search(r"mask sha256 (\w+), cutout sha256 (\w+)", block)
        rows = {}
        for line in block.splitlines():
            f = line.split()
            if len(f) > 10 and f[0] == "kmeans_w" and f[1].isdigit():
                # columns: method N dE_mean dE_p95 pieces small small_px% times iters
                # identical label_sha256[:16] colors nearest_mean nearest_p95 not_nearest%
                rows[int(f[1])] = {"iters": int(f[8]), "sha": f[10], "not_nearest": f[14]}
            if len(f) > 2 and f[0] == "kmeans_w" and f[1].endswith(":"):
                n = int(f[1][:-1])
                rows[n]["palette"] = re.findall(r"(#[0-9a-f]{6}) ([\d.]+%)", line)
        out[name] = {"mask": m.group(1), "cutout": m.group(2), "rows": rows}
    return out


RESEARCH_ROWS = _research_rows()


def _owner_selection(name):
    d = SELECTIONS / name
    if not (d / "mask.png").is_file() or not (d / "cutout.png").is_file():
        pytest.skip(f"owner selection {d} is not present (git-ignored owner images)")
    rec = RESEARCH_ROWS[name]
    for f, want in (("mask.png", rec["mask"]), ("cutout.png", rec["cutout"])):
        got = hashlib.sha256((d / f).read_bytes()).hexdigest()[:16]
        if got != want:
            pytest.skip(f"{d / f} has sha256 {got}, not the {want} measured in Task 1")
    mask = np.array(Image.open(d / "mask.png")) == 255
    rgb = np.array(Image.open(d / "cutout.png").convert("RGBA"))[..., :3]
    return rgb, mask


@pytest.mark.parametrize("name", ["roadie-tol30", "oddie"])
@pytest.mark.parametrize("n", [2, 3, 4])
def test_owner_images_match_task1_record(name, n):
    """The Task 1 hashes, reproduced, and what the final reassignment changes.

    What measure_palette.py hashed: a uint8 (H, W) C-order array, 255 outside the mask,
    holding each masked pixel's k-means cluster (the Lloyd assignment, before any nearest
    reassignment), renumbered by the cluster's pixel count descending, then by the L*, a*,
    b* of its rounded hex color. quantize differs in two legitimate ways: its labels are
    reassigned to the nearest rounded color, and its order uses the areas after that. So
    this test rebuilds the research quantity from tdmg.color's own conversion, unique
    colors, seeding and Lloyd steps and checks its hash; then checks that quantize gives
    the recorded palette and iteration count, and that the share of pixels whose label
    the reassignment changed is the recorded not_nearest% (the share whose assigned color
    was not their nearest).
    """
    rgb, mask = _owner_selection(name)
    want = RESEARCH_ROWS[name]["rows"][n]
    px = rgb[mask]
    _, inverse, counts, ulab = color._unique_colors(px)
    cent, assign, iters, converged = color._kmeans(ulab, counts, n)
    raw = assign[inverse]
    ids = np.unique(raw)
    plab = srgb_to_lab(lab_to_srgb8(cent[ids]))
    sizes = [int((raw == k).sum()) for k in ids]
    order = sorted(range(len(ids)), key=lambda i: (-sizes[i], *plab[i]))
    remap = np.empty(int(ids.max()) + 1, np.int64)
    for new, i in enumerate(order):
        remap[ids[i]] = new
    lab_map = np.full(mask.shape, 255, np.uint8)
    lab_map[mask] = remap[raw]
    assert hashlib.sha256(lab_map.tobytes()).hexdigest()[:16] == want["sha"]
    assert converged and iters == want["iters"]

    q = quantize(rgb, mask, n)
    assert q.converged and q.iterations == want["iters"]
    assert q.dropped == 0 and q.n_requested == n
    assert [h for h, _ in want["palette"]] == list(q.hex)
    # The recorded shares are those of the Lloyd clusters; the final counts differ from
    # them only by the reassigned pixels (Roadie N = 4: 46.9% recorded, 47.0% final).
    raw_counts = np.bincount(remap[raw], minlength=len(q.hex))
    assert [s for _, s in want["palette"]] == [f"{c / mask.sum():.1%}" for c in raw_counts]
    changed = q.labels[mask] != remap[raw]
    if (name, n) == ("roadie-tol30", 2):
        # Recorded 0.01% = 4 of 74,768 px under the script's CIELAB constants; under the
        # CSS Color 4 constants one of those pixels is nearest its own cluster's color
        # (an almost exact tie), so 3 change, which prints as 0.00%. Measured 2026-11-11
        # by evaluating the script's criterion under both sets of constants: 4 and 3.
        assert want["not_nearest"] == "0.01%" and int(changed.sum()) == 3
    else:
        assert f"{changed.mean():.2%}" == want["not_nearest"]
    assert np.abs(np.array(q.counts) - raw_counts).sum() <= 2 * changed.sum()

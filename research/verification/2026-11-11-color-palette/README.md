# Palette methods on the owner's selections, 2026-11-11

**Purpose:** Task 1 of `docs/plans/2026-11-11-color-palette.md`. Decision 3 of that plan
proposes a deterministic k-means in CIELAB for the R2 palette. It says to prefer Pillow's
median cut if median cut is as good on the metrics and by eye, because it is less code.
This record measures both before the method is fixed.

## Setup

- **Machine:** the Windows PC (see `docs/STATUS.md`), Python 3.13.1, numpy 2.5.4,
  Pillow 13.0.0, OpenCV 5.0.0. The script ran at commit `89b5ec6` plus the uncommitted
  script, which is committed with this record.
- **Inputs:** the owner's selections `artifacts/selection-runs/roadie-tol30/` and
  `artifacts/selection-runs/oddie/` (git-ignored; the images are not committed). The
  first 16 hex digits of the mask and cutout hashes are in `results.txt`.
- **Pixels:** only pixels where `mask.png` is 255 count. Their colors are the RGB of
  `cutout.png`.
- **Scale:** 60 mm width, as the owner's flat models. `mm_per_px` = 60 / (mask
  bounding-box width in px): 0.100167 for Roadie and 0.074720 for Oddie.
- **Island area:** (`flat.island.min_square_side` × nozzle)², read from
  `rules/geometry-flat.yaml` (2.0) and `profiles/printers/bambu-a1.yaml` (0.4 mm):
  0.64 mm². That is 63.79 px for Roadie and 114.63 px for Oddie. The rule is a hypothesis.

## Method (`measure_palette.py` → `results.txt`)

Command:
`uv run python research/verification/2026-11-11-color-palette/measure_palette.py
artifacts/color-palette-runs artifacts/selection-runs/roadie-tol30 artifacts/selection-runs/oddie`

- **k-means:** as Decision 3. sRGB → CIELAB (D65) in numpy. Farthest-point seeding from
  the most frequent color, ties to the lowest index. Lloyd iterations in float64, each
  unique color weighted by its pixel count, until no color changes cluster. The script's
  cap is 1000 iterations; no run reached it (3 to 14 iterations).
- **Median cut:** `Image.quantize(colors=N, method=MEDIANCUT, dither=NONE)` on a one-row
  image of the masked pixels. Pillow's own label per pixel is kept.
- **Same palette rule for both:** each cluster's color is the mean of its pixels in
  CIELAB, converted to sRGB and rounded to a hex code. For median cut this replaces
  Pillow's own palette entry, so only the partition differs between the methods. ΔE is
  measured to the CIELAB value of the rounded hex code.
- **Order:** area descending, then L*, a*, b*.
- **Measures:** per image, N and method: mean and 95th-percentile ΔE*76 of each masked
  pixel to its palette color; 4-connected pieces per color, summed; pieces below the
  island area and their share of the masked pixels; run time of two runs; whether the two
  label maps (uint8, 255 outside the mask) have the same SHA-256.
- **Edge diagnostic:** for each palette color, the share of its pixels within 2 px of the
  outside of the mask (OpenCV L2 distance transform). The 2 px is a diagnostic choice for
  this record only. 9.0% of Roadie's masked pixels and 2.3% of Oddie's are in this band.
- **Previews:** `artifacts/color-palette-runs/<selection>-n<N>-<method>.png`, git-ignored.
  Each shows the cutout, the painted subject, and the painted subject with the small
  pieces in magenta.

### CIELAB check

- **Reference colors:** white → (100, 0, 0); black → (0, 0, 0); red → (53.2408, 80.0925,
  67.2032); green → (87.7347, −86.1827, 83.1793); blue → (32.2970, 79.1875, −107.8602).
  These agree with the values commonly published for sRGB D65 (red 53.24, 80.09, 67.20;
  green 87.73, −86.18, 83.18; blue 32.30, 79.19, −107.86). Those published values were
  checked from memory; no source was fetched in this session.
- **Inverse:** sRGB → CIELAB → sRGB returns every one of the 16,777,216 8-bit colors
  exactly.
- **OpenCV:** the largest difference from OpenCV's float32 `COLOR_RGB2Lab` over all 8-bit
  colors is 0.19 L*, 0.47 a*, 0.33 b*. OpenCV uses its own constants and float32, so this
  shows agreement to about half a ΔE unit, not identity.

## Results

| Image | N | Method | ΔE mean | ΔE p95 | Pieces | Small pieces | Small px | Palette (area share) |
|---|---:|---|---:|---:|---:|---:|---:|---|
| Roadie | 2 | k-means | 31.72 | 74.14 | 288 | 273 | 1.34% | d10d0a 58.4, d0c89a 41.6 |
| Roadie | 2 | median cut | 33.35 | 71.28 | 69 | 52 | 0.48% | c4180c 63.4, e6e0ae 36.6 |
| Roadie | 3 | k-means | 22.77 | 59.63 | 535 | 518 | 3.42% | da0909 54.9, b5a9a4 34.8, eeef0a 10.3 |
| Roadie | 3 | median cut | 23.49 | 69.48 | 30 | 11 | 0.06% | e80707 49.5, fcf6c1 30.2, 623b26 20.3 |
| Roadie | 4 | k-means | **11.72** | **34.37** | 81 | 56 | 0.89% | ed0707 46.9, ededed 23.2, 5c271b 19.5, eeef0a 10.3 |
| Roadie | 4 | median cut | 20.21 | 69.43 | 588 | 553 | 3.25% | fa0506 37.6, fcf6c1 30.2, 980b0b 17.2, 5f4831 15.0 |
| Oddie | 2 | k-means | 33.60 | 46.40 | 4 | 0 | 0.00% | 406e4a 97.9, dc4f47 2.1 |
| Oddie | 2 | median cut | 32.12 | 44.15 | 591 | 580 | 0.34% | 60916e 50.1, 2b4c28 49.9 |
| Oddie | 3 | k-means | **17.81** | **35.27** | 16 | 2 | 0.00% | 337626 58.5, 436279 39.4, dc4f47 2.1 |
| Oddie | 3 | median cut | 30.49 | 42.64 | 607 | 595 | 0.34% | 294d28 49.3, 58926e 48.5, dc554c 2.2 |
| Oddie | 4 | k-means | **17.78** | **34.83** | 20 | 6 | 0.06% | 337626 58.5, 436279 39.3, dc4f47 2.1, f5f1f2 0.1 |
| Oddie | 4 | median cut | 28.10 | 42.64 | 2606 | 2581 | 1.28% | 58926e 48.1, 2d552c 44.2, 0a0e0a 5.4, dc554c 2.2 |

- **Run time:** every run took 0.03–0.07 s. Median cut was about 0.03 s on Roadie and
  0.06 s on Oddie; k-means about 0.05 s and 0.07 s.
- **Repeatability:** for every case, the two runs in one process gave the same label-map
  hash and palette. A second run of the whole script in a new process gave the same
  `results.txt` apart from the times.

**Reading:**
- **ΔE:** k-means has the lower mean in 5 of 6 cases and the lower 95th percentile in 4
  of 6. Median cut is better only at N = 2, and by small margins (mean 1.5 lower on Oddie;
  p95 about 2–3 lower on both). At N = 3 and 4, k-means is clearly better: at N = 4 the
  mean is 11.7 against 20.2 (Roadie) and 17.8 against 28.1 (Oddie).
- **Small pieces:** neither method wins everywhere. On Oddie, median cut gives hundreds
  to thousands of small pieces at every N; k-means gives at most 6. On Roadie, median cut
  gives fewer at N = 2 and 3, and k-means fewer at N = 4. The small pieces cover at most
  3.4% of the masked pixels in any case. Step 1's cleanup (Decision 4) is meant to merge
  them; these counts are before cleanup.
- **The author's look at the previews (not the owner's review):** median cut splits by
  RGB brightness, not by hue. On Oddie it paints the blue body with the same green as
  the light leaves at every N. On Roadie at N = 4 it merges the yellow beak and the white
  belly into one cream color, and splits the red into two reds. k-means keeps the hues:
  at N = 4, Roadie gets red, white, dark outline and yellow, and Oddie gets green, blue,
  red and a white.

## Surprises

1. **Farthest-point seeding spends colors on tiny outliers.** The seeding ignores pixel
   counts. On Oddie at N = 2 the second color is the red mouth (2.1%), so the leaves and
   body share one color (97.9%). At N = 4 one color is the white eye highlights (0.1%,
   6 small pieces). A count-aware seeding might do better; it was not tried here,
   because it is a change to Decision 3.
2. **Outline pixels.** Roadie's dark outline is mixed with the red and the
   background. At N = 4, k-means gives it a color of its own (#5c271b, 19.5% of the area;
   44% of its pixels are in the edge band). At N = 3, k-means merges the outline with the
   white into a grey (#b5a9a4, 34.8%), which is an edge-blend color, not a color of the
   drawing. Median cut does the same at N = 3 with a brown (#623b26, 44% in the edge
   band). On Oddie, k-means puts the thin black outlines into the blue (they are 1–2 px
   wide); median cut gives them their own near-black (#0a0e0a) at N = 4, which then
   makes 2,581 small pieces along the lines.
3. **Small pieces sit at color boundaries.** In the previews, the magenta pieces are
   along the outer edge and along the boundaries between colors, where anti-aliased
   pixels fall into a third color.
4. **The green shading on Oddie is lost by k-means.** Its two greens become one green at
   N = 3 and 4, while median cut keeps two greens (and loses the blue).

## What this supports and does not

- **Supports:** k-means in CIELAB as Decision 3 states it, over median cut. Median cut
  is not "as good": it is worse on ΔE at N = 3 and 4, and on these two images it merges
  different hues. Both are fast and repeatable on this machine. Decision 3 stays as
  written; the seeding weakness (Surprise 1) is an open question for the plan.
- **Does not support:** that the k-means palettes are the right colors for the owner.
  That is the owner's visual review of the previews, which comes later (plan Task 7).
- **Does not show** anything about printability: the small-piece counts are before
  cleanup, and nothing was sliced or printed.

## Limits

- **Two images,** both cartoons with flat colors. Photographs or gradients were not
  tested.
- **ΔE*76** is a simple distance. It overstates differences in saturated colors compared
  with newer formulas; no other formula was computed.
- **Repeatability** was checked on one machine only. Other platforms or library versions
  could round differently.
- **Pillow's pixel assignment** for median cut was used as Pillow returns it; how Pillow
  maps pixels to boxes was not inspected.
- **The reference CIELAB values** were compared with values recalled from memory, not
  with a fetched source. The OpenCV comparison is independent but not exact.

## Addendum, 2026-11-11: k-means with weighted seeding

**Why:** Surprise 1 above. The coordinator asked for a third method that weighs seeds by
pixel count. The text above is the original record and is unchanged.

**Method `kmeans_w`:** the same CIELAB k-means, except for the seeding. The first seed is
still the most frequent unique color. Each next seed is the unique color with the largest
count × dmin², where dmin is the CIELAB distance to the nearest chosen seed. Ties go to
the lowest unique-color index. As general knowledge (no source was fetched), this is the
greedy argmax form of the D² weighting of k-means++ (Arthur and Vassilvitskii, 2007). It
uses no random numbers.

**Run:** `measure_palette.py` now runs three methods. The command was the same, with the
output folder `artifacts/color-palette-runs-2/` (git-ignored previews). It ran at commit
`9882f72` plus the edited script, which is committed with this addendum. `results.txt` was
regenerated with all three methods. A diff of the old and new `results.txt`, without the
`kmeans_w` lines, the run times and the commit id, showed no difference: the numbers and
label-map hashes of the first two methods, and the CIELAB check, are unchanged.

| Image | N | ΔE mean (current seeding) | ΔE p95 (current) | Pieces / small | Small px | Palette (area share) |
|---|---:|---:|---:|---:|---:|---|
| Roadie | 2 | 31.72 (31.72) | 74.14 (74.14) | 288 / 273 | 1.34% | same as current |
| Roadie | 3 | 22.77 (22.77) | 59.63 (59.63) | 536 / 519 | 3.45% | same as current |
| Roadie | 4 | 11.72 (11.72) | 34.37 (34.37) | 81 / 56 | 0.89% | same as current |
| Oddie | 2 | **19.54** (33.60) | **41.97** (46.40) | 13 / 2 | 0.00% | 337626 58.5, 506276 41.5 |
| Oddie | 3 | **9.52** (17.81) | 44.46 (**35.27**) | 1381 / 1370 | 0.86% | 254c1a 40.4, 577089 36.0, 48a835 23.6 |
| Oddie | 4 | **7.75** (17.78) | **33.42** (34.83) | 1436 / 1424 | 0.86% | 234c1a 40.0, 4c708b 34.3, 48a835 23.6, dc4f47 2.1 |

- **Roadie:** at N = 2 and 4 the label maps are identical to the current seeding (same
  hash). At N = 3 the palette is the same but the label map differs slightly (one more
  small piece).
- **Run time and repeatability:** 0.04–0.07 s per run; both runs gave identical label maps
  in every case.

**Outliers:** the weighted seeding no longer spends a color on a tiny outlier.
- Oddie N = 2: green (58.5%) and blue (41.5%), instead of one color for 97.9% and the red
  mouth.
- Oddie N = 4: dark green, blue, light green and red. The white eye highlights (0.1%) no
  longer get a color.
- But at N = 3 the red face (2.1% of the area) gets no color: the eyes and mouth become
  dark green and blue. That is why the 95th percentile is worse at N = 3 (44.46 against
  35.27). Area weighting favours large regions over small, salient ones.

**The author's look at the previews (not the owner's review):**
- Oddie N = 4 is the closest of all runs to the drawing: both leaf greens, the blue body
  and the red face. The black outlines become thin dark-green lines.
- Those thin outline lines break up along the outer edge; that is where the extra small
  pieces sit (magenta in the previews). The current seeding put the outlines into the
  blue instead.
- Oddie N = 2 and N = 3 lose the face: N = 2 shows no face at all, and N = 3 shows it only
  as dark-green and blue lines.

**What the numbers now support:** k-means in CIELAB with the weighted seeding.
- Its ΔE mean is equal (Roadie) or much lower (Oddie: about half) in every case, and its
  95th percentile is equal or lower in 5 of 6 cases.
- Its costs: more small pieces on Oddie at N = 3 and 4 (0.86% of the pixels, before
  cleanup), and at low N a small, salient color such as Oddie's red face can be lost.
- Median cut is still not as good. The plan is not edited here. Whether a lost face at
  N = 3 matters is a question for the owner's review (plan Task 7).

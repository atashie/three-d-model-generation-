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

## Addendum, 2026-11-11: review fixes and nearest-color ΔE

**Why:** a quality review of this record asked for the fixes below. The text above is
unchanged.

**Note on Setup:** the commit named in Setup (`89b5ec6`) is the commit of the original run.
The weighted-seeding addendum ran at `9882f72`, and this run at `39999f0` plus the edited
script.

**What was added to `measure_palette.py`:**
- The `results.txt` header gives the SHA-256 of the script itself and
  `git describe --always --dirty`. This run: script sha256
  `152c3dc25852520c2f23b2b96deb416bd66473f1a1f89845d20a27df22f3e7f3`, git `39999f0-dirty`
  (the dirty part is this script, committed with this addendum).
- New columns for every method: the actual palette size (`colors`; a row with fewer than
  N colors is flagged; none was), and the ΔE*76 with each pixel moved to its nearest
  rounded palette color (`nearest_mean`, `nearest_p95`), and the share of pixels whose
  assigned color is not their nearest (`not_nearest%`; ties count as nearest).
- "Lowest unique-color index" in both k-means seedings means the lowest packed 0xRRGGBB
  value, because `np.unique` sorts the colors.
- Usage: with fewer than two arguments the script prints its usage and exits 2. It
  refuses an OUT_DIR that exists and is not a directory.
- The k-means docstring now says it returns labels, iterations and a converged flag.
- Previews round the alpha blend instead of truncating it (previews only).

**Run:** into `artifacts/color-palette-runs-3/` (git-ignored); `results.txt` was
regenerated. A diff of the old and new `results.txt`, without the header, the run times
and the new columns, showed no difference: every previously recorded number and label-map
hash is unchanged.

**Nearest-color ΔE*76** (assigned-color values from the tables above in brackets):

| Image | N | k-means mean / p95 | not nearest | median cut mean / p95 | not nearest | k-means weighted mean / p95 | not nearest |
|---|---:|---|---:|---|---:|---|---:|
| Roadie | 2 | 31.72 / 74.14 (same) | 0.01% | 33.14 / 71.28 (33.35 / 71.28) | 2.70% | 31.72 / 74.14 (same) | 0.01% |
| Roadie | 3 | 22.77 / 59.63 (same) | 0.02% | 23.07 / 69.21 (23.49 / 69.48) | 3.48% | 22.77 / 59.63 (same) | 0.01% |
| Roadie | 4 | 11.72 / 34.37 (same) | 0.01% | 19.59 / 69.21 (20.21 / 69.43) | 6.03% | 11.72 / 34.37 (same) | 0.01% |
| Oddie | 2 | 33.60 / 46.40 (same) | 0.00% | 32.09 / 44.15 (32.12 / 44.15) | 0.95% | 19.54 / 41.97 (same) | 0.02% |
| Oddie | 3 | 17.81 / 35.27 (same) | 0.00% | 30.45 / 42.64 (30.49 / 42.64) | 0.77% | 9.52 / 44.46 (same) | 0.05% |
| Oddie | 4 | 17.78 / 34.83 (same) | 0.00% | 27.48 / 42.64 (28.10 / 42.64) | 10.10% | 7.75 / 33.42 (same) | 0.03% |

- **Median cut:** Pillow's labels leave 0.77–10.10% of pixels on a palette color that is
  not their nearest. Moving them to the nearest lowers its ΔE mean by at most 0.62 and its
  p95 by at most 0.27.
- **k-means:** up to 0.05% of pixels are not on their nearest color. These are pixels
  near a cluster boundary; rounding each centroid to a hex code moves the boundary
  slightly. Their ΔE is unchanged at two decimals.

**Does any conclusion change?** No. With nearest assignment, median cut is still worse
than k-means at N = 3 and 4. At N = 2 it is still slightly better than the current seeding (mean on Oddie, p95
on both), but not than the weighted seeding on Oddie. The weighted seeding is still the method the numbers support, with the costs
stated in the previous addendum.

## Addendum: owner review of the first previews (plan Task 7), 2026-11-11

**What was reviewed:** `tdmg colors` at 60 mm, 4 colors, smooth and furry edges, for
Roadie and Oddie (`colors_id` b8d6edf6…, 1c770a7b…, 01127cd1…, 728f7785…; the previews
are in the git-ignored `artifacts/colors-review/`). The owner's answers, verbatim:

1. On Roadie: "right colors, but the grey-black (brown?) outline shows up on some edges
   but not all - think we should ask the user whether or not we want to keep the
   outlines (usually not) that are common in cartoons, and if so we should keep them
   consistently along all borders."
2. On Oddie's lost outlines and shading: "regarding teh outlines, see comment 1;
   regarding the shading / shadow, this should also be up to the user: either keep each
   color uniform (without shading) or discuss withe the user which aspect of the
   shading to include or exclude."
3. On edges: "smooth on default".

**Follow-up choices (answers to two questions):**
- **Outlines:** "Drop by default (Recommended)". `keep` redraws one uniform band of
  printable width along all outer and inner borders.
- **Shading:** "Flag pairs, I decide (Recommended)". The preview flags likely shade
  pairs. Nothing is merged unless the config says so; the default keeps the tones as
  extracted.

**Why the outline was inconsistent:** the outline was treated as an ordinary color, so
cleanup removed its thin parts and kept its wide ones.

## Addendum, 2026-11-11: outline and shade indicators (plan Task 7a)

**Why:** before any outline or shade rule is set (plan Task 7b), measure whether simple
per-color and per-pair numbers separate the cartoon outline and the shade pairs from the
other colors. The text above is unchanged.

**Run:** `measure_outline_shade.py` (in this folder; its docstring defines every column)
on the owner's selections `roadie-tol30` and `oddie`, Windows PC, at `d2fbe97` (script
sha256 `c6bb2bca…`, recorded in the output header with the library versions: Python
3.13.1, numpy 2.5.4, scipy 1.18.1). The colors are `tdmg.color.quantize` at N = 4, 5, 6
and 7, unchanged, **before any cleanup**, at 60 mm wide. The opening is
`tdmg.color.open_mask` at `printable_limits_px(...).min_width_px` (0.4 mm = 3.993 px for
Roadie, 5.353 px for Oddie). Full tables: `outline-shade.txt`. The previews (one panel per
extracted color: its pixels in its color, the rest of the subject light grey) are in the
git-ignored `artifacts/outline-shade-runs/` (`roadie-tol30-n{4,5,6,7}.png`,
`oddie-n{4,5,6,7}.png`). "thin" is the share of a color's pixels that the opening does not
keep; "border" is the share with a 4-neighbour of another color or of the outside; "band"
is 2 × the Euclidean distance transform.

### Identification by eye (my visual judgement from the panels; not measured)

I looked at the panels for Roadie N = 4, 5, 6 and Oddie N = 4, 5, 7. Oddie at N = 6 has
the same colors as N = 7 except the red (per the table), and Roadie at N = 7 the same as
N = 6 plus one split; for those two I read the tables, not the panels. "Outline family"
means every cluster that traces the drawn lines: the line's core and the anti-aliasing
fringe between the line and a filled color.

| Image | N | Outline core | Fringe clusters that trace the lines | Shade pairs (same object, two lightnesses) |
|---|---:|---|---|---|
| Roadie | 4 | 2 `#5c271b` (also fills the eye pupil) | none separate | none |
| Roadie | 5 | 2 `#4e3227` | 3 `#870b0b` (red side of the lines) | none |
| Roadie | 6 | 3 `#451812` | 2 `#960a0a` (red side), 5 `#746c5b` (white side) | none |
| Roadie | 7 | 3 `#451812` | 2 `#960a0a`, 5 `#797473` (white side), 6 `#797409` (yellow side) | none |
| Oddie | 4 | none: the black lines are absorbed (mostly into dark green 0) | – | greens 0–2. The blues are **one** cluster (the shadow is merged into the body) |
| Oddie | 5 | 3 `#101311` | none separate | greens 0–2; blues still merged |
| Oddie | 6, 7 | 4 `#0d100d` | none separate; 3 `#395266` (the blue shadow) also collects dotted fringe along lines | greens 0–2; blues 1–3 (body `#547e9d`, shadow `#395266`) |

At N = 7, Oddie's red splits into the mouth (5 `#ee605b`) and the eyes (6 `#a10804`). By
eye these are different objects, not a shade pair. The small white eye highlights get no
cluster at any N from 4 to 7.

### Key numbers (from `outline-shade.txt`)

Per color, over all N:

| | outline family | every other color |
|---|---|---|
| Roadie | thin 66.3–98.5%, border 56.1–83.6%, band median 2.0 px (0.20 mm) | thin 2.7–4.7%, border 7.3–9.0%, band median ≥ 12.0 px |
| Oddie | thin 100.0%, border 63.9–68.0%, band median 2.0 px (0.15 mm) | thin 1.2–9.9%, border 2.9–15.1%, band median ≥ 7.2 px (0.54 mm) |

The highest thinness of a non-outline color is the blue shadow at N = 6 and 7 (9.9%,
which holds fringe), then Oddie's dark green at N = 4 (8.0%, which holds the absorbed
lines). The lowest outline thinness is Roadie's outline at N = 4 (66.3%: the filled
pupil is not thin).

Adjacent pairs with a small hue difference (dh):

| Image, N | Pair | By eye | dh (°) | C* i / j | dL* | Shared px |
|---|---|---|---:|---|---:|---:|
| Oddie 4–7 | dark/light green | shade pair | 0.2–0.6 | 35.6–40.9 / 69.9 | 29.2–33.0 | 2938–3881 |
| Oddie 6, 7 | blue body/shadow | shade pair | 1.5 | 21.9 / 15.0 | −17.3 | 2140–2141 |
| Oddie 7 | mouth/eyes red | not a pair | 9.5 | 62.8 / 72.2 | −25.8 | 101 |
| Roadie 4 | red/outline | outline | 0.5 | 97.4 / 30.3 | −26.7 | 4176 |
| Roadie 5–7 | red/red fringe | outline fringe | 1.8–2.5 | 100.2–100.5 / 60.3–66.5 | −20.4 to −23.4 | 3998–4056 |
| Roadie 5–7 | red fringe/outline core | outline family | 2.6–10.5 | 60.3–66.5 / 16.5–25.9 | −15.9 to 4.1 | 4219–4275 |
| Roadie 7 | yellow/yellow fringe | outline fringe | 2.7 | 94.0 / 52.3 | −46.6 | 758 |
| Roadie 6 | white/grey fringe | outline fringe | 0.4 | 0.0 / 10.7 | −50.6 | 2014 |
| Oddie 5–7 | dark green/black | outline | 8.7–18.9 | 40.5–40.9 / 1.7–1.9 | −26.5 to −27.7 | 7147–7241 |

### Does a simple rule separate them?

**Outline: yes on these two images, but as a family of colors, not one color.**
- `thin > T` puts every outline-family cluster on one side and every other color on the
  other, at every N. The gap is 9.9% (highest other) to 66.3% (lowest outline). Midpoint
  **T ≈ 38%**, a margin of about 28 percentage points each way. Border share (gap 15.1%
  to 56.1%, midpoint ≈ 36%) and band median (gap 0.20 mm to 0.54 mm, midpoint ≈ 0.37 mm)
  also separate them; the three agree on every color here.
- The single-color form ("the color with the largest thinness and the lowest L*") fails
  above N = 4. On Roadie the thinnest color is a fringe (N = 5: `#870b0b`, 93.1%, against
  the core's 86.2%; N = 6: `#746c5b`, 96.3%), while the core has the lowest L*. Lowest L*
  alone also fails: on Oddie at N = 4 it picks the dark green (L* 28.4), which is not an
  outline. Where the core is the darkest, its lead can be small: 23.8 against 27.9 (Roadie
  N = 5).
- At N = 4 the thinness rule gives the right answer for both images: Roadie has one
  outline cluster (thin 66.3%, also the lowest L*); Oddie has no color above T (highest
  8.0%), which is correct, because its lines have no cluster of their own.

**Shade pairs: not by hue and chroma alone.** Roadie's red and its outline at N = 4
(dh 0.5°, C* 97.4 / 30.3, adjacent over 4176 px) look like a shade pair by these numbers,
and so do Roadie's red/fringe pairs. No chroma floor separates them: the true blue pair
has C* 15.0, lower than the outline's 30.3. A two-step rule does separate them here:
1. Remove the outline family first (`thin > T`).
2. Among the remaining colors, flag pairs with `dh < H` and C* above a floor for both.
   The remaining pairs: the greens (dh ≤ 0.6°) and the blues (1.5°), against the red
   mouth/eyes (9.5°) and every other pair (≥ 13.2°; that one is white/yellow, where
   white has C* 0.0, so its hue means nothing; with both C* above the floor, the next is
   63.7°). Gap 1.5° to 9.5°: **H ≈ 5.5°**, a margin of 4°. The chroma floor only has to
   exclude white and black: C* 0.0–1.9, against the lowest shade color's 15.0; midpoint
   **≈ 8.5**.
   Adjacency adds nothing on these images. The true pairs share 2140–3881 px and the
   mouth/eyes 101 px, but those 101 px are fringe pixels, and the count is in image
   pixels, so it depends on resolution. dL* separates nothing (shade pairs 17–33,
   other pairs 20–51).

All these thresholds are **hypotheses from two images**, read off gaps between a few
values. The hue gap rests on a single counterexample (mouth/eyes). If they become rules,
they are `kind: hypothesis`, `validation: untested`, with this record as their only
evidence. Detection should stay a suggestion that the owner confirms, never an automatic
merge, as the owner decided.

### Which N extracts what

- Oddie's lines get their own cluster from **N = 5** (`#101311`, 6.0%) and keep it at 6
  and 7 (`#0d100d`, 5.7%).
- The green shade pair is separate at every N from 4 to 7. The blue shade pair is
  separate only from **N = 6**; at N = 4 and 5 the shadow is merged into the body.
- So, on Oddie, the outline and both shade pairs need N ≥ 6, two colors more than the
  four the owner reviewed.

### Surprises

- **Roadie's outline splits into fringes as N grows.** From N = 5, the extra clusters
  are anti-aliasing colors between the line and each fill (dark red, grey, dark yellow),
  not new regions. At N = 7, four of Roadie's seven colors trace the lines. A larger N
  helps Oddie and costs Roadie, and "drop outline" must remove the whole family.
- **Roadie's eye pupil has the outline's color** at every N (at N = 4 it is why the
  outline's band p90 is 4.5 px and its thinness only 66.3%). Dropping the outline would
  also remove the pupil.
- **Roadie's red and white never touch** (0 shared px at every N): the outline always
  separates them, so dropping it fills a gap between them.
- **Fringe also hides inside real regions.** Oddie's blue shadow cluster at N = 6 and 7
  has 1618 pieces (dotted fringe along lines), its dark green at N = 5 to 7 has 741–761
  (dotted along the veins of the light leaves), and its blue at N = 4 has 1418. These
  pixels are not clusters of their own, so neither rule sees them; the region cleanup
  must still handle them.
- Oddie's mouth has a darker upper-right part in the cutout. It gets no cluster of its
  own at any N from 4 to 7 (by eye).

## Addendum, 2026-11-11: Task 7c on the owner's images

**Setup:** Windows PC, `tdmg colors` at git HEAD after Task 7c, 60 mm, defaults (extract 6,
colors 4, smooth, `outline_color: auto`, `outlines: drop`). The outputs are in the
git-ignored `artifacts/colors-runs/` (`roadie-tol30-60-drop`, `roadie-tol30-60-keep`,
`oddie-60-default`, `oddie-60-merge-blues`). The thinness values that `tdmg.color` records
equal the N = 6 rows of `outline-shade.txt`:
- Roadie: 93.9%, 87.4% and 96.3% for the family; 4.7%, 3.7% and 2.7% for the others.
- Oddie: 100% for the black; 9.9% at most for the others.

**Results:**
- **Roadie, drop:** the family is 2, 3 and 5; the core is 3 `#451812`. The final colors
  are red, white, yellow and the core (1.6%, mostly the pupil). The plan is ready.
- **Roadie, keep:** the same family. The 0.6 mm (5.99 px) band is 38.4% of the subject.
  Twice the distance transform on the band's ridge gives a median of 6.3 px (10th–90th
  percentile 6.0–7.2 px). Axis-aligned runs of the band are mostly 6–8 px, longer where a
  border is diagonal.
- **Oddie, default:** the family is 4, the black lines. No wide area is left, so the core
  is removed. 5 colors remain and the plan is not ready. Flagged:
  - the greens 0–2: dh 0.19°, C* 40.9 and 69.9;
  - the blues 1–3: dh 1.48°, C* 21.9 and 15.0.
- **Oddie, `merge: [[3, 1]]`:** 4 colors; the plan is ready.

**Seen by eye** (my judgement of the four previews):
- **Roadie, drop:** the outline is gone and the pupil stays dark. The crest and tail tips
  keep small dark ends, and so does one dot at the belly's edge.
- **Roadie, keep:** the band looks uniform along the borders and the outer edge.
- **Oddie:** the lines and leaf veins are gone. A dotted dark fringe remains along parts of
  the outer edge; this is the fringe noted in Surprises above.

### Correction, 2026-11-11 (spec review of the Task 7c addendum)

- **Band share:** the addendum above says "the 0.6 mm (5.99 px) band is 38.4% of the
  subject". That is wrong. 38.4% is the core's final share: the band, the pupil, the dark
  tips and the cleanup's changes together. The band alone is 27781 px, about 37.2% of
  Roadie's 74768 masked pixels.
- **A by-eye effect left out:** dropping the black lines removes the only separation
  between neighbours of the same color.
  - In Oddie's default run, the overlapping dark-green leaves fuse into one region.
  - With the blue merge, the arms and feet fuse into the body's silhouette.
  
  This bears on the owner's Task 7d choice between keep and drop for Oddie.

### Correction, 2026-11-11 (Roadie with the redefined keep)

The plan's Task 7c re-run note said that Roadie under the new `keep` (the drawn lines, at
git `c266ce7`) "looks like the first version". That overstated it. The controller's
review of `artifacts/colors-runs/roadie-tol30-60-keep-v2/regions.png` found three
differences; I have not measured them myself:
- **The mouth:** its lower part is shaded in the thin dark-red family tone `#960a0a`, so
  keep redraws that shading as a stroke. The red mouth interior shrinks to a small spot
  inside a thick band.
- **The eye white** is smaller.
- **A dot:** one isolated thin speck, about 15.7 px from the edge at (300, 486), becomes a
  small dot.

## Addendum: owner review of the outline and shading previews (plan Task 7d), 2026-11-11

**What was reviewed:** the previews in the git-ignored `artifacts/colors-review-2/`:
1. Roadie, outline dropped;
2. Roadie, outline kept;
3. Oddie, dropped, not ready;
4. Oddie, dropped, blues merged;
5. Oddie, kept, blues merged (5 colors);
6. Oddie, kept, blues and greens merged.

The owner's answers, verbatim:

1. "teh "kept" version looks good, but could use some smoothing around the edges; teh
   "dropped" version is has remnant black outlines - ideally only the black of the eye
   would remain but I still spot black outlines around the tail feathers and head
   feathers and a bit in the mouth and a bit on the chest. Also, "empty" spots (like
   between the ankles and shoes, or between the beek and eye) should be filled in but it
   looks like there are some gaps."
2. "make it a choice for the user, but yes black base if fine in this case."
3. "they all look good, except they have more than 4 colors in many cases - so these
   wouldn't work for ams; i personally prefer 6, but I don't think there is a way to
   standardize this decision."
4. "I think a touch finer would be good (0.4 mm?)."
5. "drop them".

## Addendum, 2026-11-11: Task 7e-a, what survives drop, holes and inlets, stroke specks

**Setup:** Windows PC, git `45d4c0d`, no library change. The script is
`measure_wide_holes.py` (its docstring defines every term and column); its output is
`wide-holes.txt`. It runs `tdmg.color_plan.plan_colors` with the `tdmg colors` defaults
(extract 6, `outline_color: auto`, `outlines: drop`, no merge), printer bambu-a1, 60 mm, on
`artifacts/selection-runs/roadie-tol30` and `artifacts/selection-runs/oddie`. The previews
are in the git-ignored `artifacts/wide-holes-runs/` (`<name>-wide.png`, `-holes.png`,
`-strokes.png`, `-rules.png`). At 60 mm, 1 px is 0.1002 mm on Roadie and 0.0747 mm on
Oddie.

Command: `uv run python research/verification/2026-11-11-color-palette/measure_wide_holes.py
artifacts/wide-holes-runs artifacts/selection-runs/roadie-tol30 artifacts/selection-runs/oddie`

### 1. Wide outline-color components under drop

- **Roadie:** 1630 wide family pixels in 42 components (W1 to W42). 662 of them are non-core
  (21 components, N1 to N21).
- **Oddie:** no wide family pixel, so there is nothing to measure here.

The current cleanup keeps these W components in the core color (the "final" column):
- W1, W2, W3, W4, W5, W7, W8, W9 and W17: 100% each.
- W26: 26%.
- All the others: 0%.

**My by-eye identification** (from `roadie-tol30-wide.png`; the controller should check it).
Survivors of the current cleanup are in bold.

| Owner's word | Components | Members |
|---|---|---|
| pupil | **W1**: 421 px, 4.22 mm², inscribed 18.9 px = 1.89 mm, no exterior contact | core only |
| head feathers | **W2**, **W3**, **W17**, **W26**, W14, W27, W23, W16 | core: W2, W17, W14, W23, W16. `#960a0a`: W3, W26, W27 |
| tail feathers | **W7**, **W9**, W18, W19, W21, W30, W12 | core: W9, W18, W21, W12. `#960a0a`: W7, W19, W30 |
| mouth | **W5**, **W8**, W6, W10, W24, W33, W36, W37, W29 | `#960a0a`: W5, W6, W10, W36, W37. core: W8, W24, W33, W29 |
| chest (right edge of the white) | **W4**, W15, W31, W34 | `#746c5b`: W4. `#960a0a`: W31. core: W15, W34 |
| eye-beak junction | W22, W28 | `#746c5b`: W22. core: W28 |
| legs and feet | W11, W13, W20, W25, W32, W35, W38 to W42 | mixed |

The survivors are exactly the places the owner named: the head and tail tips, the mouth and
the chest dot.

**What separates the pupil from the rest (Roadie only):**
- **Inscribed width** (2 × the maximum EDT; this reads about 1 px over the true width):
  - W1 is 18.9 px (1.89 mm).
  - All 41 other W components are 6.3 px (0.63 mm, W5) or less.
  - Every other W component with core pixels is 6.0 px (0.60 mm) or less.
- **Area:** W1 is 4.22 mm². The next largest are W2 at 0.79 mm² (core) and W3 at 0.75 mm²
  (non-core).
- **Exterior contact** does not separate them:
  - W1 does not touch the exterior.
  - The core survivors W2, W8, W9 and W17 all touch it.
  - The non-core survivors W3, W5 and W7 do not touch it, and neither do some removed core
    pieces (W28, W33).
- **Compactness** does not separate them: W1 is 0.454, and the others are 0.337 to 0.675.
- **The family's stroke width:** 2 × EDT on `stroke_ridge(S)` has a median of 4.0 px
  (0.40 mm) and a p90 of 6.0 px (0.60 mm). S is the set of family thin pixels. The remnants
  are as wide as the drawn strokes; the pupil is about 3 × wider.

### 2. Holes and inlets

- **Holes:** 0 on both images, with 4-connectivity and with 8-connectivity of the outside.
- **No background shows inside the subject in the owner's preview.** In the right panel of
  `artifacts/colors-review-2/1-roadie-outline-dropped.png` (2 × scale), 0 checkerboard
  pixels (grey 200 or 235) are inside the mask, and all 2,349,376 pixels outside the mask
  are checkerboard.
  - I checked this with an inline script, which is not in the committed script. It compared
    `np.kron(mask, ones((2, 2)))` with the panel, columns 1672 to 3343.
- **Inlets:** I closed the mask (`not open_mask(not mask, w)`) and then filled holes.
  - The area this encloses grows gradually with w. No pocket jumps to its full area at a
    small w, as a pocket behind a narrow inlet would.
  - The Roadie pockets of island size or more at 2.0 mm are these:
    - P1, between the tail and the legs: 4120 px at 2.0 mm, but only 220 px at 1.25 mm.
    - P2 to P5, P7 and P8: the notches between the crest feathers and between the tail
      feathers.
    - P6: the open mouth.
    - P9: a notch at the chest.
  - On Oddie, the pockets are concavities along the dark-blue arms and feet.
- **The places the owner named.** These are my by-eye picks; the owner did not mark them.
  "Enclosed" is the largest area that the closing encloses within 12 px of the point.

  | Place | The point is | Enclosed at 0.4 mm | Enclosed at 2.0 mm |
  |---|---|---|---|
  | Forehead-beak wedge next to the eye (236, 507) | exterior | 1 px | 13 px |
  | Right foot: wedge between the cuff and the shoe (526, 627) | exterior | 4 px | 56 px |
  | Left foot: inside the cuff (560, 330) | a mask pixel, final color `#f5f5f5` | 0 px | 0 px |

  The two wedges are open background, not narrow inlets.

**Result:**
- Of the owner's named gaps, **0 are holes and 0 are narrow inlets** that I could find.
- "Fill holes" changes nothing on either image.
- I have no evidence for an inlet width.
- A closing wide enough to fill the wedges would also fill the feather notches.

**What the owner may have seen.** These are my hypotheses; I have not measured them:
1. The white areas (`#f5f5f5`, grey 245) are next to the light checker cell (235), so the
   cuffs, the eye white and the shoe holes can read as empty.
2. Under drop, neighbors of the same color fuse. The white cuff merges with the white shoe
   hole and the sole, and the eye white loses its ring. The separation that the line gave is
   gone.
3. In the cutout, the black line made the open background wedges at (236, 507) and
   (526, 627) look closed.

The owner should mark the gaps on an image before a rule is made for them.

### 3. Stroke specks under keep

- **Roadie:** S has 34 8-connected components.
  - Three are real strokes:
    - S1: 17940 px.
    - S2: 444 px, 4.46 mm². This is the ring of the right shoe's hole.
    - S3: 234 px, 2.35 mm², 8.3 mm long. This is a piece of the left shoe's line.
  - The other 31 components are 22 px (0.22 mm², 0.8 mm across) or less.
  - 28 of the 31 touch the exterior (d_ext 1 px). The edge band covers them anyway.
  - The other 3 are interior, and these become stray dots:
    - S11: 3 px at (292, 470), in the mouth.
    - S23: 1 px at (300, 486). This is the dot the controller found.
    - S22: 1 px at (260, 464), at the eye-beak junction.
- **Oddie:** 6 components, all real strokes. The smallest is S6: 450 px, 2.51 mm², 10.3 mm
  long.

### Proposed rules

These are hypotheses from two images. Rules (a) and (b) rest on Roadie alone.

**(a) Keep a core-color wide component only if its inscribed width (2 × the maximum EDT) is
1.25 mm or more.** The others take the nearest non-family color, as thin pixels do.
- **The gap on Roadie** is 0.60 mm (the widest core component that is not the pupil) to
  1.89 mm (the pupil). The midpoint is 1.245 mm, rounded to 1.25 mm. The margins are
  0.65 mm below and 0.64 mm above, about 6.5 px each way.
- **An area rule also separates them:** 0.79 mm² to 4.22 mm², midpoint about 2.5 mm².
- **The evidence is thin:** one positive against 41 negatives, on one image. Oddie has no
  wide family pixel, so it does not test the rule.
- **The threshold depends on the print width:**
  - At 120 mm, Roadie's strokes and remnants would both be about 1.2 mm wide, which is
    close to the threshold.
  - A scale-free form is "inscribed ≥ 2 × the family's p90 stroke width". On Roadie that is
    12 px, which lies between 6.3 px and 18.9 px (1.05 and 3.15 times the p90 of 6.0 px).
    This is also a hypothesis from one image.
- **I do not propose an exterior condition** ("does not touch the exterior"). It changes
  nothing on Roadie, and it would remove a pupil that touches the head's outline.
- **Simulated** (the last step of the script):
  - Thin pixels and non-core wide pixels take the nearest non-family color. A core W
    component is kept only if it does not touch the exterior and its inscribed width is
    1.25 mm or more. Then `clean_regions` runs.
  - Roadie still has 4 final colors. The core keeps 422 px in **1 component, the pupil**.
  - By eye, `roadie-tol30-rules.png` has no dark head tips, no dark tail tips, no dark
    mouth and no chest dot.
  - The simulation keeps the exterior condition. Without it, the result is the same: no
    other component reaches 12.48 px. I did not run that variant separately.

**(b) Non-core wide pixels take the nearest non-family color.** No threshold is needed.
- It removes W3, W4, W5, W7 and W26, the non-core survivors.
- This includes the mouth's dark red W5, which goes 72% to red and 28% to yellow.
- **(b) alone does not remove all of the mouth's darkness.** W8 (50 px, core `#451812`, at
  the right end of the mouth) survives the current cleanup. Rule (a) is needed for W8, and
  also for the core tips W2, W9 and W17.

**(c) Fill holes:** there are no holes on these images, so this changes nothing. **I do not
propose an inlet-closing rule:**
- No named gap is an inlet.
- A closing wide enough to reach the wedges also fills the feather notches (P2 to P8, which
  are already partly enclosed at 0.4 to 2.0 mm).
- Ask the owner to mark the gaps (see the hypotheses above).

**(d) Under keep, do not draw a stroke component whose area is below the island area.** The
island area is 0.64 mm², from `flat.island.min_square_side` with the 0.4 mm nozzle. It is an
existing rule, so no new number is needed.
- **The gap on both images:**
  - The specks are 0.221 mm² or less (Roadie S4).
  - The smallest real strokes are 2.35 mm² (Roadie S3) and 2.51 mm² (Oddie S6).
- **Margins:** about 2.9 × below the island area and 3.7 × above it. The arithmetic
  midpoint of the gap would be 1.28 mm², so the island area is inside the gap.
- **What it removes:** the 3 interior specks (S11, S22 and S23) and the 28 edge specks.
  The edge band covers the edge specks anyway.

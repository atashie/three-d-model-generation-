# Colored flat geometry: measurements (R2 step 2)

Records for `docs/plans/2026-11-12-color-geometry.md`. Windows PC, shapely 2.2.0,
GEOS 3.14.1, numpy 2.5.4, OpenCV 5.0.0. The owner's images and plans are git-ignored
(`artifacts/`); only the scripts and numbers are kept here.

## Task 1: vectorizing the fine label map (2026-11-12, at `a4a2a4f`)

**Script:** `measure_vectorize.py`. **Output:** `vectorize.txt`.

**Inputs:** the four approved owner plans (`artifacts/colors-runs/*-f64`). All are at
60 mm wide, sigma 2.5 px, supersample 4, 4 colors and base 0.

**Steps, for each plan:**
1. Build the R1 silhouette S (`smooth_outline` at `flat.smooth.sigma_px`, intersected
   with the image box, then `to_model` and `clean`).
2. Build the fine map (`smooth_labels`).
3. Vectorize each color with `mask_outline(fine == c)`, scaled by 1/s.
4. Try `coverage_simplify` at 0, 0.5/s and 1/s px.
5. Clip each color to S, with no fixed grid and with `grid_size` 1e-6 and 1e-5 mm.

### Results

| Plan | Fine map | Raw vertices | Skin triangles, raw | At 1/s px | Base below skin |
|---|---|---|---|---|---|
| Roadie, outline dropped | 3344 × 3168 | 22,554 | 61,916 | 44,340 | 31,196 |
| Roadie, outline kept | 3344 × 3168 | 28,191 | 143,788 | 79,636 | 31,196 |
| Oddie, blues merged | 4096 × 4052 | 29,069 | 65,688 | 47,272 | 29,020 |
| Oddie, kept, blues and greens merged | 4096 × 4052 | 46,406 | 214,496 | 118,040 | 29,020 |

- **Triangles:** the largest raw total is about 244,000 (214,496 + 29,020), a quarter of
  the F5 limit (1,000,000, `slicer.orca.max_triangles_per_plate`). Simplifying is not
  needed for F5.
  - At 0.5/s px, `coverage_simplify` changes nothing: the tolerance is below the
    fine staircase step.
  - At 1/s px, it roughly halves the triangles, but moves boundaries by up to 0.35 px
    (0.035 mm).
- **Partition, clipped with no grid:**
  - The pairwise overlap area was exactly 0 in every case.
  - The gap (area of S minus the union's) was between −4.3e-12 and 6.8e-12 mm². That
    is float rounding of the area sums.
- **With a fixed grid,** the gap grew to about 1e-6 mm² (1e-6 mm grid) and 5e-6 mm²
  (1e-5 mm grid): snap rounding moves vertices. A grid makes the partition worse here.
- **Time and memory:**
  - `smooth_labels` took 0.75–1.22 s, vectorizing 0.71–1.22 s, and clipping under
    0.2 s.
  - The tracemalloc peak was 121 MiB (Roadie) and 160 MiB (Oddie).
  - `verify_colors` took 0.44–1.38 s.
- **Coverage validity:** `shapely.coverage_is_valid` was **False** on the raw polygons of
  every plan.
  - **Cause, confirmed by running code** (a scratch script; the commands are below):
    `mask_outline` removes collinear vertices. Where three colors meet, the two colors on
    one side have a vertex at the junction, and the color across the edge does not.
    Shapely's coverage definition needs matching vertices on shared edges.
  - **Checks:**
    - A 4 × 4 synthetic T-junction (left half color 0; right half colors 1 and 2) is
      invalid (3 invalid edge parts).
    - Roadie (outline dropped) is invalid (15 invalid edge parts).
    - Both become valid after `shapely.snap(p, union of all boundaries, 1e-9)` adds the
      neighbours' vertices.
  - **What it means:** the regions do not overlap or gap. Only the coverage functions'
    vertex-matching precondition fails.

### Decisions taken from these numbers (plan Decision 3, amended)

- **No simplification** (`SIMPLIFY_PX` = 0). The raw boundaries keep every fine step
  (1/s px, about 0.025 mm here), and the triangle counts are well within F5. Without
  simplification, the coverage functions are not needed.
- **No fixed grid** (`GRID_MM` = none). Plain GEOS overlays gave zero overlap and gaps at
  float-rounding level. The grid only added error.
- **How the partition is gated:** by `C1.partition`'s measured overlap and gap. Coverage
  validity is not used: the junction vertices make it fail on valid partitions.
- **Limits:** this covers four plans from two images. The synthetic tests in Tasks 3 and
  4 cover junctions, borders along the outline and deliberate overlaps.

Scratch check of the coverage cause (not kept as a script; run 2026-11-12):

```python
polys = [mask_outline(f == c) for c in np.unique(f)]
shapely.coverage_is_valid(polys)                      # False
allb = shapely.union_all([p.boundary for p in polys])
shapely.coverage_is_valid([shapely.snap(p, allb, 1e-9) for p in polys])   # True
```

Note (2026-11-12, Task 3): `tdmg.flat` made `_apply_transform` and `_polygons` public as
`apply_transform` and `polygon_parts`, so only `measure_vectorize.py`'s imports and call
sites were renamed. The re-run on the Windows PC (shapely 2.2.0, GEOS 3.14.1, numpy 2.5.4,
opencv 5.0.0) reproduced `vectorize.txt` line for line, apart from its hand-written header
and the timings: image sizes, areas, scales, vertex counts, coverage validity, boundary
deviations, overlaps, gaps, triangle counts and the tracemalloc peaks were all identical.
`vectorize.txt` was not overwritten.

## Task 3: color regions on the owner's plans (2026-11-12)

**Script:** `measure_regions.py`. **Output:** `regions.txt` (working tree after Task 3, Windows
PC).

- **The first Task 3 code** (each inlay opened on its own, trimmings to the base; plan
  Decision 5 as written) left base-colored area where the plan has another color:
  - 1.2, 21.3, 1.0 and 5.3 mm² on the four plans (Roadie drop, Roadie keep, Oddie merge
    blues, Oddie keep), in 2,844–9,882 pieces;
  - on Roadie keep, 19.7 mm² of it from the kept outline band;
  - at most 0.15 mm² in pieces touching the outline.

  This was measured with a scratch script on that code, which is not kept; the numbers
  are quoted in the plan's Decision 5 replacement. **The owner chose "Match preview"**: no
  cleaning.
- **The current code:** the base-colored area outside the base color's own fine region is
  0 on three plans and 4.1e-16 mm² on Roadie drop: 14 rounding-sized pieces on the outline.
  So there are no hairlines.
- **Thin parts** (narrower than 0.4 mm, `flat.thin_regions`; information only):
  - The largest is the kept outline band on Roadie keep: 14.33 mm² of 244.65 mm².
  - The rest are 0.08–4.09 mm².
  - The piece counts (101–11,655) are high because every convex corner and staircase
    tooth of the fine map counts. Treat the area as an indicator, not a count of narrow
    features.
  - The slicer checks in step 4 judge whether these print.
- **Time of `color_regions`:** 2.2–7.9 s per plan. A synthetic 4096² map in the quality
  review took 23.6 s, most of it in the thin report's buffers.

## Task 5: the glue route on the owner's plans (2026-11-12)

**Script:** `measure_glue.py`. **Output:** `glue.txt` (commit `d1d2b34` plus the
uncommitted Task 5 working tree, Windows PC). T 3.0 mm and the rule defaults: clearance
0.2 mm, min piece 2.0 mm (4 mm²), skin 0.6 mm, opening 0.4 mm, island 0.64 mm².

### First run: fold on a candidate's total area (the reason for the amendment)

`glue.txt` held this run first; it was replaced by the run below. Its numbers:

- Every glue body passed F1 and its export check; F2.fits_build_volume and F5.triangles
  passed on every plate (at most 147,064 triangles, the Oddie keep base).
- F4.glue_fit passed on all four. The smallest gap was 0.198531 mm (Roadie keep),
  against a threshold of 0.198071 mm. That gap is below c minus the shrink's chord error
  minus the snap (0.199034 mm), so the opening's chord error in the margin is needed: a
  margin of only the shrink chord and the snap would FAIL that plan.
- Folds: 2, 7, 2 and 9 (Roadie drop, Roadie keep, Oddie merge blues, Oddie keep).
- **Thin outline bands did not survive the shrink:** on the two "keep" plans, the outline
  color's pocket was mostly uncovered (180 of 255.5 mm² on Roadie keep, 183 of 192 mm²
  on Oddie keep), and what remained was cut into small pieces (9 of 13 and 4 of 4 below
  4 mm²). The owner chose "Fold small pieces too" (plan Decision 8, amendment).
- Time: `glue_geometry` 0.8–10.4 s, `glue_checks` 1.1–2.0 s.

### The amendment as first written failed on every plan (not kept)

With the pocket = candidate ∩ (kept pieces buffered by the clearance), the leftover
(candidate minus that buffer) was 1,867, 2,056, 2,971 and 2,499 parts on the four plans,
1,842–2,959 of them below 0.01 mm²: the fine map's staircase teeth and the cusps at
rounded corners, which the clearance band cannot reach. Rebuilding the cells from them
on Roadie drop left 154 base pinches after 4 rounds of joining, so `color_cells`
refused. Measured with a scratch script (not kept). So the leftover is cleaned with the
R1 opening and island rule, and parts of the pocket that hold no piece go to the base
(`tdmg.color_glue`, step 4).

### Current run (amended rule)

| Plan | Folds | Leftover to base | Small pieces dropped | Pockets / pieces | Smallest piece | Smallest gap / threshold | Uncovered | Base triangles |
|---|---|---|---|---|---|---|---|---|
| Roadie drop | 2 | 2.651 mm² | 1 (1.544 mm²) | 7 / 7 | 6.116 mm² | 0.198953 / 0.198068 mm | 1.585 mm² | 61,358 |
| Roadie keep | 7 | 206.8 mm² (outline band) | 9 (16.11 mm²) | 8 / 8 | 4.194 mm² | 0.198869 / 0.198061 mm | 3.73 mm² | 80,630 |
| Oddie merge blues | 2 | 0 | 0 | 5 / 5 | 23.98 mm² | 0.198637 / 0.198063 mm | 2.12 mm² | 55,820 |
| Oddie keep | 10 | 0 | 0 | 3 / 4 | 20.47 mm² | 0.198944 / 0.198063 mm | 1.212 mm² | 75,868 |

- Every body (the base and each color's pieces) passes F1 and its export check after
  STL storage; F2.fits_build_volume, F5.triangles, F4.glue_partition and F4.glue_fit
  pass on all four. No empty pockets.
- **F4.glue_partition** (added in the quality review): the rebuilt cells against the
  gridded S differ by 0 to 5.1e-7 mm² (bound 1.85e-3 to 2.97e-3 mm²), the pockets overlap
  by 0, and the glue base's expected volume equals area(S) T - area(pockets) d to
  5.6e-7 mm³ or better (bound 5.5e-3 to 8.9e-3 mm³).
- **The outline bands:** on Roadie keep, 206.8 of the band's 255.5 mm² goes to the base,
  and 4 pieces of 4.19–13.6 mm² are kept. On Oddie keep, the band (192 mm², 4 pieces of
  at most 1.83 mm²) now folds whole into the base (the 10th fold), so color 2 has no
  glue pieces at all.
- **Uncovered** is now 1.2–3.7 mm² per plan (182 and 184 mm² on the keep plans before):
  the corners rounded to r + c, the staircase teeth, and leftover parts narrower than
  the opening.
- The rebuild joined 2 pinches on Roadie keep (area moved 8.2e-11 mm²); the F4.glue_fit
  margin then adds PINCH_K G to the pocket's move.
- Time: `glue_geometry` 1.1–12.7 s, `glue_checks` 1.0–1.1 s.

## Task 7: the owner's review (2026-11-12)

The owner reviewed `top.png` and `parts.png` of the four runs (`colored-runs.txt`). Their
answer, verbatim:

> teh colors match, but for the glued-together versions of our images let's make sure to
> not add teh outline - that would be unrealistic to glue on, I think. Everyting else
> looks ok

**What follows from it (controller, 2026-11-12):**
- **The problem:** a colors plan does not record which pixels of the outline color are the
  redrawn band and which are the image's own dark regions, such as Roadie's pupil. So
  the band cannot be removed from an `outlines: keep` plan alone.
- **The change:** for a plan with `outlines: keep`, `tdmg flat --colors` writes the AMS
  version only, and says that a glue print needs the plan with `outlines: drop`. For the
  owner's images, that is Roadie's and Oddie's drop plans, already reviewed above.
- **Everything else** (colors, the other folds, piece sizes) is accepted.

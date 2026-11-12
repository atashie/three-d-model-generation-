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

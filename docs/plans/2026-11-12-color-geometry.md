# Colored flat geometry (`tdmg flat --colors`) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** build step 2 of the R2 color design (`docs/plans/2026-11-11-color-design.md`).
`tdmg flat SELECTION_DIR --colors COLORS_DIR` turns a verified color plan into solid
bodies:
- **AMS:** a base body and one inlay body per color in a 0.6 mm top skin.
- **Glue:** a base with pockets and per-color pieces shrunk by a clearance.

It also writes a parts sheet and the checks that the bodies partition the R1 shape. No
3MF and no slicing yet (steps 3 and 4).

**Architecture:**
- **Pure geometry:** a new module, `src/tdmg/color_geometry.py`, with no I/O. It takes:
  - the R1 silhouette, cleaned in mm;
  - the fine label map (`tdmg.smoothing.smooth_labels`);
  - the transform and the rule values.

  It returns per-color polygons, the AMS bodies and the glue pieces.
- **Checks:** a second new module, `src/tdmg/color_checks.py`, holds the new checks.
- **The command:** `tdmg.flat` gets `make_colored_flat`. It reuses R1's outline, cleaning,
  extrusion and F-checks, and writes its own record (`colored.json`) in the style of
  `flat.json`: canonical JSON, the record last, and an id that hashes the identity.

**Tech stack:**
- shapely 2.2 / GEOS 3.14: the coverage functions and fixed-precision overlay;
- manifold3d (extrusion);
- trimesh (STL);
- Pillow (previews);
- Typer.

No new dependency.

**Status:** written 2026-11-12. The owner approved it on 2026-11-12 ("approved"), with
the three starting values in Decision 7 unchanged.

**Format:** this follows the repo's plan style (decisions with evidence, then tasks with
tests), not full code, as `docs/plans/2026-11-11-color-palette.md` does. Every task is
test-first, and each gets a subagent spec review and a quality review. Task 8 is the
Codex critical review.

## Decisions

1. **Input: a verified plan and its selection.**
   - **Checks:**
     - Call `verify_colors(colors_dir, selection_dir, check_preview=False)` first. It
       refuses a changed or inconsistent plan, a plan that is not ready, a different
       selection, and rule values that differ from the registry.
     - `--width-mm` is optional. It defaults to the plan's `width_mm`. If given, it must
       equal the plan's value exactly (design: compare the requested width, not the
       scale). Otherwise it is refused, and the message says to re-run `tdmg colors`.
     - `--printer` defaults to the plan's printer. A different one is refused: the
       cleanup limits used that printer's nozzle.
     - `--thickness-mm` is required and must exceed the skin depth, so there is base
       material under every inlay.
   - **Smoothing:** `--smooth-px` with `--colors` is refused. The preview the owner
     approved drew the outer outline with `flat.smooth.sigma_px`, so the model must use
     the same value.
   - **Why:** the color design's section "Requirements step 2 inherits from step 1".
2. **The silhouette is R1's, made the same way.**
   - **Steps:**
     - `smooth_outline(mask, flat.smooth.sigma_px)`;
     - intersect it with the image box [0, W] × [0, H] (required: the outline can
       overshoot the image by up to 2.5e-15 px, `overshoot_f64.txt`);
     - `to_model`;
     - `clean`, with the same opening and island rules.
   - **Reuse:** the outline step of `make_flat` is factored into one function that both
     commands call, so the colored body cannot drift from the single-color one.
   - Call the cleaned silhouette S.
3. **Color regions come from the fine map, as a coverage.**
   - **Fine map:** `smooth_labels(labels, sigma_px, supersample)`, with the verified
     plan's values.
   - **Vectorize each color c:** `mask_outline(fine == c)`, scaled by 1/s. The colors'
     polygons share vertices exactly: integer grid, same arithmetic. So together they
     are a valid coverage of the image box, and `shapely.coverage_is_valid` must say so
     (a refusal if not, as a bug).
   - **Simplify:** `shapely.coverage_simplify` at tolerance `SIMPLIFY_PX`. This keeps the
     shared edges shared, so neighbours cannot gap or overlap. The fine staircase is
     1/s px (0.025 mm for Roadie at 60 mm). Unsimplified, it gives two vertices per fine
     step and may approach the 1,000,000-triangle F5 limit. Task 1 measures the
     triangle counts and the deviation, then fixes `SIMPLIFY_PX`. It is a numerical
     choice, not a rule, like `QUAD_SEGS`.
   - **Clip:** transform to mm and clip each color to S. All overlays run with one fixed
     `grid_size`, `GRID_MM`. On a fixed grid, GEOS's snap-rounding gives neighbouring
     results consistent edges. Task 1 measures the gaps and overlaps with and without
     the grid, and fixes `GRID_MM`, well below the STL's float32 rounding at these
     sizes.
4. **Which colors become inlays.**
   - Every final palette color except the base (`base_index`) is an inlay.
   - The base color's top is S minus the union of the inlays, so the base absorbs
     anything removed from an inlay.
5. **Each inlay is cleaned like an R1 part.**
   - **Rules:** the opening (`flat.sliver.opening_width`) and the island area
     (`flat.island.min_square_side` × nozzle)², per inlay color.
   - **Why it is needed:** clipping makes new slivers along the outline, where a color
     border runs close to S's edge (the plan was cleaned at the exact-mask scale, and S
     is smoothed).
   - **Where removed material goes:** to the base, by Decision 4.
   - **Report:**
     - per color: the area before and after;
     - colors that vanish entirely, as a warning, with the filament count it leaves.
6. **The bodies (face up; face down is a flip, decided by measurement in step 4).**
   - **AMS base:** S extruded from 0 to T − d, united with the base top extruded from
     T − d to T. One manifold body.
   - **AMS inlay for color c:** its cleaned region extruded from T − d to T, in place.
   - **Glue base:**
     - S extruded to T, with a pocket of depth d for every glue region (Decision 8).
     - It equals the AMS base when no region is folded.
   - **Glue piece:** z from 0 to d at its model x, y. Each color's plate prints its
     pieces where they sit in the model, so the parts sheet's numbers match the model
     directly. Neighbouring pieces cannot touch: each was shrunk by the clearance.
7. **New rules, each a hypothesis.** The owner confirms the starting values before
   Task 1. All three are `kind: hypothesis` and `validation: untested`, and the test
   strip in step 5 sets them.
   - **`color.skin.depth_mm` = 0.6:**
     - **Basis:** the owner's decision in the color design ("0.6 mm, three 0.2 mm layers
       to start").
     - **Provenance:** unverified. The test strip checks whether 0.6 mm of a light color
       hides a dark base.
   - **`color.glue.clearance_mm` = 0.2 per side.**
     - **Evidence:**
       - Prusa KB: printers are "accurate to at least 0.2 mm" [P];
       - a vendor's PLA "standard" radial clearance of 0.20–0.30 mm [S];
       - sliding fits of 0.1–0.3 mm [S].

       All three are in
       `research_notes/.../articulated_flexi_print_design.md` and
       `fdm_design_rules_and_ai_ecosystem.md`.
     - **Caveat:** none is for glued inlays. The pieces only need to drop in, and the
       glue fills the gap.
   - **`color.glue.min_piece_side_mm` = 2.0:**
     - **The rule:** a glue piece whose shrunk area is below (side)², 4 mm², is folded.
     - **Basis:** no source was found. Our reason is a piece small enough to lose or to
       be unable to place with tweezers.
     - **Provenance:** unverified, stated as our own guess.
8. **Glue regions: fold the tiny ones, then shrink.**
   - **Start:** each connected inlay polygon is a candidate piece.
   - **Shrink:** buffer it by −clearance (round joins, `QUAD_SEGS`). An inward buffer
     keeps convex corners sharp and rounds concave ones, so the gap is at least the
     clearance everywhere and never less.
   - **Clean:** apply the R1 opening and island rules to the shrunk piece.
   - **Fold:** a candidate is folded when its cleaned, shrunk area is below the
     min-piece area.
     - It goes into the neighbour (base included) with the longest shared boundary.
       Ties go to the lowest color index, then the base.
     - Folding repeats, smallest first, until nothing changes, as `clean_regions` does
       in pixels.
     - A region folded into the base has no pocket.
   - **Pockets:** the folded regions, unshrunk.
   - **Report:** per piece, its number, color and area. The record also gives the
     pocket area that no piece covers beyond the clearance band (a neck that the shrink
     removed), as a measured number.
9. **Checks** (design "Gate additions"), in `tdmg.color_checks`. Each is a `CheckResult`.
   - **Every body:** parsed back from its STL bytes, then `merge_exact`, then the F1
     topology checks, `export_check` against its own polygons and thickness, and
     `build_volume_check`.
   - **`C1.partition` (AMS):**
     - The inlay polygons and the base top are pairwise interior-disjoint (overlap area
       at most a derived tolerance).
     - Their union equals S (symmetric-difference area within the same tolerance).
     - The body volumes sum to area(S) × T within the summed `export_check` volume
       tolerances.
     - The tolerances are derived from `GRID_MM` (one grid step along the boundaries)
       and stated in the check, as `export_check` does.
   - **`C1.filaments`:** the number of non-empty AMS bodies is at most the plan's
     `colors` and the printer's palette cap.
   - **`C1.glue_fit`:** each piece, buffered by (clearance − one grid step), lies within
     its pocket. It reports the smallest measured gap.
   - **Triangles:** F5 on the sum over all AMS bodies (one plate), and on each glue
     plate.
   - **Unknown here:**
     - F3.thin_regions is reported per body, information only, as in R1.
     - F6 is UNKNOWN: slicing is step 4.

   So the verdict is always NOT CERTIFIED, as for `tdmg flat`.
10. **Outputs** (this settles the design's conflict: the 3MF writer is step 3).
    - **AMS:**
      - `ams/base.stl`;
      - `ams/color-<i>-<rrggbb>.stl`, one per inlay color, with final palette index i.
      - The names give colors, never AMS slots (PLAN section 2).
    - **Glue:** `glue/base.stl` and `glue/color-<i>-<rrggbb>.stl`.
    - **Previews:**
      - `top.png`: the top skin drawn from the polygons in palette colors, to compare
        with the plan's `regions.png`;
      - `parts.png`: the numbered diagram, each glue piece numbered at
        `point_on_surface`, with the list of pieces per color.
    - **The record, `colored.json`:**
      - schema `tdmg.colorflat/1`, algorithm `colorflat-1`;
      - `colorflat_id` = SHA-256 of the canonical identity: the algorithm, `colors_id`,
        the selection's mask hash, and the params (width, thickness, printer, the three
        new rules and the R1 rules with their values, `SIMPLIFY_PX`, `GRID_MM`,
        supersample, sigma);
      - per body: its color, area, volume, triangles and checks;
      - the folding and cleaning reports, the warnings, the output hashes, the
        environment, the verdict and the review line.
    - **No `flat.json`:** `tdmg slice` refuses a colored folder until step 4 teaches it.
    - **How it is written:** as `make_flat` does. Everything is built, encoded and gated
      in memory, so a refused input writes nothing. A FAIL still writes the files for
      review.

## Tasks

1. **Measure the vectorization** (research first).
   - **Where:** script and record in `research/verification/2026-11-12-color-geometry/`.
   - **Inputs:** the four approved owner plans (`artifacts/colors-runs/*-f64`) at
     60 × 3 mm.
   - **Measures:**
     - `coverage_is_valid` on the raw polygons;
     - vertex and extruded triangle counts at `SIMPLIFY_PX` of 0 (none), 0.5/s and
       1/s px;
     - the largest distance from the simplified to the raw boundaries;
     - after clipping to S, the overlap and gap areas between colors, with and without
       `grid_size` (candidates 1e-6 and 1e-5 mm);
     - the run time and the tracemalloc peak.
   - **Choose:** `SIMPLIFY_PX` and `GRID_MM` from the numbers, and record why. If the
     coverage approach fails on a real plan, stop and report before Task 3.
2. **The three rules.**
   - Add them to `rules/color.yaml` with refs and exact locators, as confirmed by the
     owner.
   - Run `scripts/gen_docs.py`; `tests/test_rules.py` passes.
   - Read each locator against its value (CLAUDE.md rule 2).
3. **`color_geometry`: regions** (Decisions 3–5). Synthetic tests:
   - two flat colors in a square give an exact partition of S;
   - a three-color junction leaves no gap or overlap;
   - a color border running along the outline leaves no sliver: it goes to the base;
   - an inlay that cleaning erases is reported as vanished;
   - `coverage_simplify` keeps shared edges identical;
   - repeat runs are byte-identical;
   - an invalid coverage (built by hand) is refused.
4. **Bodies and AMS checks** (Decisions 6 and 9). Tests:
   - each body passes F1 and `export_check`;
   - the volumes sum to area × T;
   - a body moved by 0.01 mm FAILs `C1.partition` (an overlap);
   - a region deleted by hand FAILs it (a gap);
   - a five-color body set for a four-slot printer FAILs `C1.filaments`;
   - thickness ≤ skin depth is refused.
5. **Glue** (Decision 8). Tests:
   - a square inlay's measured gap is the clearance (to the grid);
   - a concave corner's gap is at least the clearance;
   - a tiny region surrounded by one color folds into it;
   - one touching two colors folds into the longer shared boundary;
   - one surrounded by the base leaves no pocket;
   - cascading folds reach a fixed point;
   - a neck that the shrink removes is reported as uncovered pocket area;
   - a piece pushed 0.1 mm toward its pocket wall FAILs `C1.glue_fit`.
6. **`make_colored_flat`, record, previews, CLI.**
   - Factor R1's outline step (Decision 2), with `tests/test_flat.py` and
     `tests/test_make_flat.py` passing unchanged.
   - Add `--colors` to `tdmg flat`, with the same exit codes.
   - **Tests:**
     - **Refusals, with nothing written:** a tampered plan, a different selection, a
       width or printer other than the plan's, `--smooth-px` with `--colors`, a not-ready
       plan, a non-empty `--out`.
     - **Record:** `colorflat_id` changes with each identity input and not with the
       environment.
     - **Outputs:** the output hashes, and repeat runs byte-identical.
     - **Previews:** `top.png` matches the polygons at a few probe pixels, and
       `parts.png` has one number per piece.
     - **CLI:** the output under `_plain()`.
7. **Run on the owner's plans and get the owner's review.**
   - **Runs:** `tdmg flat --colors` on the four approved plans at 60 × 3 mm. Record the
     checks, counts, folds and times in the Task 1 folder (the records, not the images).
   - **The owner reviews `top.png` and `parts.png`:**
     - Do the colors match the approved previews?
     - Are the folds acceptable?
     - Are the pieces a size you can handle?

     Record the answers verbatim.
8. **Docs, STATUS, Codex critical review, push and CI.**
   - **Docs:**
     - update `docs/print-types/attributes/color-multi.md` and
       `docs/guide/pipeline-and-gate.md`;
     - update the color design's step-2 notes, recording the outputs decision
       (Decision 10).
   - **STATUS:** this step's results and the next steps.
   - **Codex review:** recorded in `research/reviews/2026-11-12-color-geometry/`, with
     each finding verified and handled.
   - **Then:** push, and record the CI result in STATUS.

## Out of scope (later steps)

- **The 3MF writer** (one object with parts, or separate objects): step 3, chosen by
  import tests in OrcaSlicer and PrusaSlicer.
- **AMS slicing:** the change count, the waste, and face up against face down. Step 4.
  Until then, `tdmg slice` does not read colored folders.
- **Printing:** the test strip (clearance, and the skin over a dark base), then the first
  AMS and glue prints. Step 5.

## Risks stated to the owner

- **0.6 mm pieces are thin:** three layers. They may curl or break when handled. The test
  strip shows this. A deeper pocket for the glue route alone is a possible later option,
  not built here.
- **Triangle count:** the fine map's staircase is dense, and Task 1 decides whether
  simplification keeps the AMS plate under the F5 limit.
- **Mac parity:** the fine map is not shown to be bit-identical on the Mac. The geometry
  is gated by its own checks, not by matching the fine map's bytes (color design,
  step-2 requirements).

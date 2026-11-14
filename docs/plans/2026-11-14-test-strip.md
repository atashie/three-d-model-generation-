# Test strips (R2 step 5, part 1) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** make two small calibration prints. They let the owner set two R2 rules from a
real print on the A1:
- **Clearance strip:** which per-side gap lets a glue piece drop into its pocket
  (`color.glue.clearance_mm`, now 0.2, a hypothesis).
- **Skin strip:** how deep a light color must be to hide a dark base
  (`color.skin.depth_mm`, now 0.6, a hypothesis).

The first AMS print and the first glue print of an owner plan (step 5, part 2) come after
the strips. They are not in this plan.

**Architecture:**
- **Module and command:** a new module, `tdmg.test_strip`, builds both strips from fixed
  rectangles. It uses the same geometry code as `tdmg flat --colors`:
  - `color_cells` and `glue_geometry` for the clearance strip;
  - `_body` / `prism_mesh` with per-cell z ranges for the skin strip.
  A new command, `tdmg strip OUT`, writes both strips, gates them and slices them.
- **Same checks, not new ones:** the strips are gated by the existing checks, called as
  functions, and sliced with the pinned OrcaSlicer and A1 profile.
- **To print:** the owner prints from Bambu Studio (`.3mf` / `.stl`), as for every
  model so far.

**Tech stack:** shapely, trimesh, the existing `tdmg.color_geometry`, `tdmg.color_glue`,
`tdmg.color_checks`, `tdmg.threemf`, `tdmg.orca_input`, `tdmg.slicing`,
`tdmg.color_slicing` and `tdmg.color_gcode`. No new dependency.

**Status:** written 2026-11-14 from the owner's answers on 2026-11-14 (below). It is not
yet approved.

**Format:** the repo's plan style: decisions with evidence, then tasks. Every task is
test-first and gets subagent spec and quality reviews. The Codex review is the last code
task.

## What is known (evidence)

- **The owner's answers (2026-11-14):**
  - gaps: 0.10 to 0.35 mm per side, by 0.05 (six pockets);
  - skin depths: 0.2 to 1.0 mm, by 0.2 (five patches, 1 to 5 layers at 0.2 mm);
  - filaments: white over black, the worst case;
  - judging: by hand and eye (drops in, sticks or is loose), with a photo. No calipers.
- **The rules being tested** (`rules/color.yaml`): both are `kind: hypothesis`,
  `validation: untested`. The notes on each say the test strip sets it.
- **The geometry code is reusable:**
  - `glue_geometry(cells, ..., clearance_mm=c)` makes each pocket from a region and each
    piece by shrinking the pocket by c, then measures and fixes the gap
    (`color_glue.py`).
  - `_body(name, index, cells, ranges, grid)` meshes cells with one z range per cell, so
    one body can have patches of different depths (`color_geometry.py`).
- **Rules the strip layout must meet:**
  - `fdm.wall.min_thickness` 0.9 mm;
  - `fdm.hole.min_diameter` 2.0 mm.

## Decisions

1. **The clearance strip is one base and six pieces, built by the real glue code.**
   - **Layout:**
     - **Base:** 3.0 mm thick, with six square pockets 10 mm a side, 0.6 mm deep
       (`color.skin.depth_mm`), 5 mm apart and 5 mm from the edges.
     - **Pockets and gaps:** one pocket per gap, 0.10 mm at the left.
     - **Labels:** gap k (1 to 6) is marked by k round holes, 2.0 mm across
       (`fdm.hole.min_diameter`), in a row below its pocket. You can read the strip
       without labels or a font.
   - **How the pieces are made:** `glue_geometry` is called once per gap on the same
     cells. From call k, only pocket k's piece is kept.
     - **Pockets:** they do not depend on the gap. The task proves that the base and
       pockets are identical across the six calls, and fails otherwise.
   - **Why squares:** a square has straight edges and sharp corners. Real pockets have
     both. Curved edges are not tested. This is a stated limit, not a claim.
   - **Gated by:** `F4.glue_fit` (the gap of each piece against its own pocket) and
     `F4.glue_partition`, as for a plan. Each body is also gated by the R1 mesh checks
     (`tdmg.checks`).
   - **Sliced:** the base and the six pieces (one plate, as R1 parts) with
     `slice_glue_plate`'s checks. Only the checks that apply to a part with holes and
     pockets are required; the task lists them and says why.
2. **The skin strip is one two-color model: black base, white patches.**
   - **Layout:**
     - **Base:** black, 3.0 mm thick.
     - **Patches:** seven, each 12 mm square, 4 mm apart, all reaching the top. From the
       left:
       - black only (the reference);
       - white 0.2, 0.4, 0.6, 0.8 and 1.0 mm deep;
       - white full depth, 3.0 mm (the reference for "fully hidden").
     - **Labels:** patches 2 to 6 are marked by 1 to 5 holes (one per layer) in a row
       below them.
   - **How it is made:** the white body is the patch cells, each with z range
     (3.0 − d, 3.0). The base is every cell, cut to 3.0 − d under patch cells. All
     bodies are on the same grid and z floats, as `ams_bodies` does.
   - **Gated by:** `F4.color_partition` and the 3MF read-back
     (`F2.export_3mf_matches_bodies`).
   - **Sliced:** face up with the step 4 color path (`slice_face`). Its checks are
     required as for a plan:
     - `F6.color_changes`;
     - `F6.tool_placement`;
     - `F6.filaments_used`;
     - the outer-edge F3 checks.
   - **Colors:** palette white `#FFFFFF`, black `#000000`. The filament profiles carry
     them, as in step 4.
3. **The layout numbers are not rules.** They are the test object's size: 10 and 12 mm
   squares, 4 and 5 mm spacing, 3.0 mm thick.
   - They are module constants, named and stated here.
   - Each is checked against the rules it must meet (walls ≥ 0.9 mm, holes ≥ 2.0 mm).
   - The gaps and depths are the owner's choices, recorded in `strip.json` with this
     plan as the source.
4. **The output folder.** `tdmg strip OUT` writes:
   - `clearance/`: `base.stl`, `pieces.stl` and `slice/` (G-code, checks);
   - `skin/`: `model.3mf` (portable, one shell per color), `palette.json` and
     `slice/`;
   - `strip.json`: the record (`tdmg.strip/1`, with the algorithm label `strip-1`).
     It holds:
     - the gaps and depths;
     - every check;
     - the slicer identity;
     - the file hashes.
   - `results-template.md`: the form the owner fills in after printing (Decision 5).
5. **How the owner judges, and what changes after.**
   - **Clearance:** each piece goes into its own pocket. The owner records one of:
     - "won't go in";
     - "pressed in";
     - "drops in, snug";
     - "drops in, loose" (it rattles or falls out when turned over).
   - **Skin:** each patch, under room light and next to the two reference patches, is
     recorded as "dark shows", "slight shadow" or "looks like full white".
   - **Photo:** one photo of each strip.
   - **Then (a later task, after the print):** the results go into
     `research/verification/2026-11-14-test-strips/`. With the owner's choice, the two
     rules move to `validation: calibrated`:
     - **Clearance:** the smallest gap that drops in, snug.
     - **Skin:** the smallest depth that looks like full white, or the owner's
       accepted "slight shadow".
     A rule's value changes only if the owner chooses a different one. Then
     `gen_docs.py` runs, and the four owner plans are rebuilt and re-sliced.

## Tasks

### Task 1: strip geometry (`src/tdmg/test_strip.py`, `tests/test_test_strip.py`)

- **The layout constants and both builders:**
  - `clearance_strip(gaps_mm, *, rules)` returns the base Body, six piece Bodies and
    the Glue reports.
  - `skin_strip(depths_mm, *, rules)` returns the base Body, the white Body and the
    Cells.
- **Inputs are validated:** gaps and depths must be finite, positive and ascending, each
  depth below the thickness, and each gap below half the pocket side. A bad input raises
  a named error.
- **Tests first:**
  - **Clearance strip:**
    - each piece's measured gap to its pocket is at least its own gap (to the grid
      snap) and within one grid snap of it;
    - the base is identical across the six glue calls;
    - k holes below pocket k;
    - every wall is at least 0.9 mm;
    - every hole is at least 2.0 mm across.
  - **Skin strip:**
    - the white volume equals Σ area × d (plus the full patch);
    - the base and white bodies tile the strip with no overlap (`F4.color_partition`
      PASS);
    - the patch tops are all at 3.0 mm.
  - **Both strips:** each mesh is closed and vertex-manifold, and the output is
    byte-identical on repeat.

### Task 2: gating, files and slicing (`tdmg.test_strip.make_strips`)

- **What it writes:** the folder in Decision 4.
- **What it runs:**
  - the checks in Decisions 1 and 2, through the existing functions;
  - the slices, through `slicing.prepare` / `slice_glue_plate` / `slice_face`.
- **Some checks need a "flat record" or "colored record"** for their expected values.
  The task builds those expected values from the strip geometry directly. It does not
  fake a selection or a color plan.
- **Verdict:** `strip.json` says PRINTABLE per strip only if every required check
  PASSes. Each check that is not required is listed with its reason.
- **Tests:** with the fake slicers (`tests/fake_orca.py`), and one `-m slicer` test with
  the pinned OrcaSlicer.

### Task 3: command, owner form, docs

- **The command:** `tdmg strip OUT [--slicer-dir] [--timeout-s]`. Exit 1 only if a
  required check FAILs. It prints what to print, with which filaments, and how to judge
  it.
- **`results-template.md`:** the form in Decision 5.
- **Docs:**
  - `docs/print-types/attributes/color-multi.md` (step 5 status, how to run it);
  - `docs/guide/pipeline-and-gate.md`;
  - `README.md`;
  - `STATUS.md`.
- **CLI tests:** as for `tdmg slice`.

### Task 4: measured run and Codex review

- **Measured run:** `tdmg strip` on the PC with the pinned slicer. The record goes in
  `research/verification/2026-11-14-test-strips/` (what was run, the numbers, the
  verdicts).
- **Codex review:** in `research/reviews/2026-11-14-test-strips/`. Each finding is
  checked against the code and handled as in review practice.

### Task 5 (after the owner prints): results and rules

- **Results:** the owner's filled form and photos go into the record.
- **Rules:** the two rules change as in Decision 5.

## Out of scope

- The first AMS and glue prints of an owner plan (step 5, part 2).
- Curved pocket edges, other filament pairs, and glue strength.
- Comparing `tdmg`'s G-code with Bambu Studio's (still open from step 4).
- Measuring the gap with calipers (the owner chose by hand and eye).

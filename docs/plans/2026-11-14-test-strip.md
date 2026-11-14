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
- **Module and command:** a new module, `tdmg.calibration_strip`, builds both strips
  from fixed rectangles. (Amended in Task 1 review, 2026-11-14: first named
  `tdmg.test_strip`; renamed because pytest or doctest can collect a module named
  `test_*`.) It uses the same geometry code as `tdmg flat --colors`:
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

**Status:** written 2026-11-14 from the owner's answers on 2026-11-14 (below). The owner approved
it on 2026-11-14 ("build it").

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
       - **Amended in Task 1 (controller, 2026-11-14):** six 2 mm holes with 0.9 mm walls
         need 17.4 mm, but the pocket pitch is 15 mm. So the holes go in rows of at most
         3 (4 = 3 + 1, 5 = 3 + 2, 6 = 3 + 3), each row centred under its square. The
         skin strip uses the same layout and the same 5 mm edge margin.
       - **Amended in Task 1 review (2026-11-14), the label numbers:** the hole centres
         are `HOLE_PITCH_MM` 3.5 mm apart, in a row and between the two rows. The solid
         between a square and the first row's holes is `LABEL_GAP_MM` 2.0 mm, and so is
         the bottom solid, between the second row's holes and the strip's bottom edge.
         So the strip extends 2.0 + 2.0 + 3.5 + 2.0 = 9.5 mm below the squares (the
         hole diameter, 2.0 mm, counted once for the two rows' half-holes).
   - **How the pieces are made:** `glue_geometry` is called once per gap on the same
     cells. From call k, only pocket k's piece is kept.
     - **Pockets:** they do not depend on the gap. The task proves that the base and
       pockets are identical across the six calls, and fails otherwise.
       - **Amended in Task 1 review (2026-11-14):** this holds only when no call gives
         leftover to the base (at a large gap, the pocket's corners become base) and no
         rebuild joins a pinch. The code refuses any call with leftover or a pinch fix,
         with that as the stated cause, before the identity check. It also refuses any
         call that does not give exactly one piece in each of the six pockets (a gap so
         large that the piece is below `color.glue.min_piece_side_mm` folds it, pocket
         and all, into the base), naming that rule and the gap.
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

### Task 1: strip geometry (`src/tdmg/calibration_strip.py`, `tests/test_calibration_strip.py`)

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

### Task 2: gating, files and slicing (`tdmg.calibration_strip.make_strips`)

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
- **Amended in Task 2 (2026-11-14), what was built:**
  - **Two clearance plates, not one.** Decision 1's "one plate" cannot hold both: each
    piece lies inside its pocket's outline, so the pieces cannot share a plate with the
    base where they are. `base.stl` and `pieces.stl` are sliced each on its own, in
    `clearance/slice/base/` and `clearance/slice/pieces/`.
  - **Where the pieces are.** `pieces.stl` keeps each piece where `glue_geometry` made it,
    in its pocket's place. So the pieces lie left to right in gap order, at the pocket
    pitch `POCKET_SIDE_MM` + `POCKET_SPACING_MM` = 15 mm (5 mm plus two gaps between
    two pieces). No new layout constant is needed, and no piece is moved, so the STL is
    exactly the gated geometry. **Limit:** the pieces look alike (squares of 9.8 to
    9.3 mm), so the owner must keep them in plate order. Task 3's form must say so.
  - **Required checks of a clearance plate** (`PLATE_REQUIRED`): the `tdmg slice` set
    less `F2.target_width` and `F6.portability`, plus `F4.glue_fit` and
    `F4.glue_partition` of all six glue calls. Why each one applies to a part with holes
    and pockets:
    - the seven F1 checks: the STL must be a closed, oriented, vertex-manifold solid,
      and the holes and pockets are part of its surface;
    - `F2.export_matches_geometry`: the STL against its own Body. Its occupancy check
      cuts every z interval, so it compares the pocket floors (T − d) and the holes;
    - `F2.fits_build_volume` and `F5.triangles`: per plate, as for a glue plate;
    - `F4.body_count`: 1 for the base and 6 for the pieces, the strip's own counts;
    - `F4.glue_fit` and `F4.glue_partition`: Decision 1. Each plate carries all twelve
      (six calls), as `tdmg.color_slicing` gives each glue plate the glue checks;
    - `F3.printed_connectivity`: the holes are counted per layer, so the label holes
      must print as holes and the base as one part;
    - `F3.edge_coverage` and `F3.edge_overprint`: the hole and pocket walls are model
      edges, as the outline is;
    - `F6.slicer_exit`, `F6.gcode_present`, `F6.layer_count`, `F6.single_object`: as R1.
    - **Not applicable:** `F2.target_width`. The strip's size is set by the layout
      constants (Decision 3), not by a requested width.
  - **Required checks of the skin strip:**
    - the AMS route's gate checks, as for a plan's face: the F1 checks and
      `F2.export_matches_geometry` per body, then `F2.export_3mf_matches_bodies`,
      `F2.fits_build_volume`, `F4.color_partition`, `F4.filaments` and `F5.triangles`;
    - `F2.orca_input_matches_bodies`;
    - `color_gcode.required_check_ids(2)`: `F6.color_changes`, `F6.tool_placement`,
      `F6.filaments_used`, the silhouette's `F3.edge_coverage` and `F3.edge_overprint`,
      and each tool's `F3.edge_overprint`;
    - R1's four slicer F6 checks.
    - **Not required:** each tool's `F3.edge_coverage` and every connectivity check
      (warnings, as for a plan's face); `F6.color_waste`, `F6.color_time` and
      `F6.color_filament` (information); `F6.portability` (below).
  - **`F6.portability` is not run.** PrusaSlicer is never run for a strip
    (`slicing.prepare(..., portability=False)`), so the check is UNKNOWN and not
    required. The strips are printed once, from Bambu Studio on the owner's A1, to set two
    rules. Whether a second slicer reads the file does not bear on that. Also, Task 3's
    command has no PrusaSlicer option.
  - **`F3.thin_regions` is not made.** It is always UNKNOWN and information only, and
    each layout is checked against `fdm.wall.min_thickness` when it is built.
  - **The record:**
    - `strip.json` holds the geometry identity (owner values, layout constants, rule
      values, printer, grids) and its hash `geometry_id`;
    - each plate's `slice_id`, the face record, the file hashes and `strip_id`;
    - per strip: `required_checks`, `not_required` (each check id with its reason) and
      the verdict. A check that is neither required nor given a reason stops the run
      (StripError).
    - `palette.json` carries `strip_geometry_id` in place of `colorflat_id`.
  - **Repeat runs:** as for `tdmg slice`, a repeat run is byte-identical except the
    G-code bytes and their sha256 (the slicer writes the time into its header). The
    normalised hashes stay the same.
  - **Shared code changes:** small, and each existing default is unchanged:
    - `records.write_outputs(subfolders=n)`;
    - `slicing.prepare(portability=False)` and `slicing.slice_stl(unconfigured=...)`;
    - `color_slicing.slice_face(portability_required=False)` and
      `color_slicing.glue_body_count_check(how=...)`;
    - `threemf.palette_manifest(link=...)`.
- **Measured with the real slicer (2026-11-14, on the PC; pinned OrcaSlicer 2.5.0, app
  tree checked): both strips are NOT CERTIFIED.**
  - **Clearance, pieces plate:** PRINTABLE (3 layers, 490 s, 0.47 g).
  - **Clearance, base plate:** NOT CERTIFIED. `F3.printed_connectivity` FAILs on 2 of 15
    layers:
    - at z 1.6 mm, a printed island of 1.63 mm² (sparse infill), 0.003 mm from the rest
      of the beads, at bed x 132.9 to 135.0 and y 93.7 to 95.8 mm;
    - at z 2.0 mm, an island of 0.27 mm² (internal solid infill), 0.097 mm from the
      rest.
    - The holes match on every layer (21 printed, 21 in the model). `F3.edge_coverage`
      PASSes (largest gap 0.21 mm), and so does `F3.edge_overprint`. R1's turn search
      found the part turned 90°. 15 layers, 1372 s, 6.12 g.
  - **Skin strip:** NOT CERTIFIED. These checks FAIL: `F6.tool_placement`, the
    silhouette's `F3.edge_coverage` and `F3.edge_overprint`, and each tool's
    `F3.edge_overprint`.
    - The printed plastic spans bed y 69 to 187 mm and x 115 to 141 mm. So OrcaSlicer
      turned the 118 × 26.5 mm strip a quarter turn, but the color checks place the
      model unturned (`color_gcode.PLACEMENT_ANGLE`, by design).
    - A diagnosis run (a scratch script, not kept) sliced the same shells turned a
      quarter turn in the model, long along y. Every color check PASSed, warnings
      included.
    - 15 color changes, 2725 s, 10.29 g (G-code header: 8.51 g black and 1.78 g white),
      flush 1125 mm³, prime tower 769 mm³.
  - **Open, for the controller and the owner:** the real-slicer test asserts PRINTABLE.
    It is marked `xfail(strict=True)` with this reason until the two causes are decided.
- **Amended after the real-slicer run (2026-11-14), the skin strip is laid out long
  along y (controller decision).**
  - **Cause (found in the OrcaSlicer 2.5.0 source, and seen in a measured run):**
    - The CLI arranges a model it loads ("before arrange, need_arrange=1" in the log).
    - With no `--align_to_y_axis` option, it sets `align_to_y_axis` when the machine's
      `printer_structure` is `i3` (`src/OrcaSlicer.cpp` at tag v2.5.0, the two
      "arrange_cfg.align_to_y_axis = (printer_structure_opt->value ==
      PrinterStructure::psI3)" lines). The A1's flattened `machine.json` has
      `"printer_structure": "i3"`.
    - `update_selected_items_axis_align` (`src/libslic3r/Arrange.cpp`, v2.5.0) then
      turns each item so that the principal axis of its second moments of area lies
      along y. It does not turn an item whose two second moments have a ratio above
      0.66. For a rectangle w × h the ratio is (min / max)². For 118 × 26.5 mm that is
      0.05, and the turn is +90°.
    - The measured run agrees: the log places the item at translation (141.25, 69), and
      the plastic spans bed x 115 to 141 and y 69 to 187.
    - A rectangle longer in y than in x has its principal axis along y already, so
      OrcaSlicer turns it by 0.
  - **Change:**
    - `SKIN_ALONG_Y = True`: the skin strip is its x layout turned a quarter turn
      counterclockwise (x = H − v, y = u). It is 26.5 × 118 mm, patch 1 at the front
      (smallest y), and the label holes to the right of their patches.
    - `skin_layout` refuses a layout that is not longer in y than in x (StripError).
    - No layout number changes. The clearance strip stays long along x: its plates are
      R1 parts, which are judged in any quarter turn.
    - The algorithm label is now `strip-2`. The geometry identity records
      `skin_along_y`.
  - **Real-slicer verdict (2026-11-14, on the PC; pinned OrcaSlicer 2.5.0, app tree
    checked): the skin strip is PRINTABLE.**
    - Every check PASSes, the warnings included. Only the information checks and
      `F6.portability` are UNKNOWN.
    - The plastic spans bed x 114.75 to 141.25 and y 69 to 187 mm: unturned, centred on
      (128, 128).
    - 15 layers and 15 color changes. 2727 s (G-code header: model 39 m 12 s, total
      45 m 27 s). 10.29 g (8.51 g black and 1.78 g white). Flush 1125 mm³, prime tower
      769 mm³.
- **Amended after the real-slicer run (2026-11-14), the clearance base plate's islands
  are mapped. The layout is not changed.**
  - **Where they are.** R1 found the plate turned 90°, so model x = 47.5 + (bed y − 128)
    and model y = 12.25 − (bed x − 128).
    - **z 1.6 mm:** one sparse-infill path of five segments, 1.63 mm², at model x 13.2
      to 15.3 and y 5.2 to 7.3. That is right of pocket 1's label hole (centre (10, 6.5),
      edge near x 11) and below pocket 1's lower right corner (15, 9.5), about 2.2 mm
      from each.
      - z 1.6 is the first of the five top shell layers (`top_shell_layers` 5) under the
        pocket floors at z 2.4. On it an internal bridge covers most of the plate above
        the label band, reaching well past the pockets.
      - The sparse infill left in the label band is cut into pieces by the bridge
        region and the holes' walls.
      - This piece touches nothing. Its nearest bead is a bridge line 0.0032 mm away.
    - **z 2.0 mm:** one internal-solid-infill dot of 0.27 mm² (one closed path about
      0.1 mm across) at model x 64.1 to 64.7 and y 19.9 to 20.4.
      - That is at the corner of the solid-infill region under pocket 5's floor (the
        pocket plus about 0.8 mm), just outside the pocket's top left corner (65, 19.5).
      - It is 0.097 mm from that region's nearest solid-infill line.
      - A plot of the layer shows similar small pieces at corners of pockets 1, 2 and
        4. They touch the rest (the layer has only the one island).
  - **Why: not a narrow gap between features.**
    - The pinned process profile has `wall_loops` 2, outer wall 0.42 mm, inner wall
      0.45 mm, sparse infill 0.45 mm (15 %, grid), internal solid infill 0.42 mm and
      `minimum_sparse_infill_area` 15 mm².
    - Neither island lies between two walls. Below the pocket floor there is no wall
      around a pocket. Both islands are pieces of infill clipped where two fill regions
      meet, away from any wall: sparse against bridge, and solid against sparse.
  - **Artefact or real part:**
    - **z 1.6:** most likely an artefact of the bead model. The gap is 0.0032 mm. The
      bead model is recorded to leave gaps of 0 to about 0.03 mm between beads that
      meet edge to edge (`research/verification/2026-11-13-color-slicing/README.md`,
      "Task 5 cross-check").
    - **z 2.0:** the gap is 0.097 mm, more than that. By the bead model it is a separate
      dab of 0.27 mm².
  - **The suggested rule, tested once with the real slicer and not kept:**
    - The rule: the solid between two holes, and between a hole and a pocket or the
      edge, is at least 2 × (outer wall + (`wall_loops` − 1) × inner wall) + one
      sparse line = 2 × 0.87 + 0.45 = 2.19 mm. The values were read from the pinned
      flattened profile.
    - Applied as `LABEL_GAP_MM` 2.19 and `HOLE_PITCH_MM` 2.0 + 2.19 = 4.19 (a scratch
      run; the strip became 95 × 25.57 mm, thinnest wall 2.18 mm).
    - Result: the z 1.6 island is gone. But z 2.0 has an island again: 0.41 mm² of
      internal solid infill at model x 68.2 to 68.8 and y 5.6 to 6.2, among pocket 5's
      label holes, 0.0175 mm from a hole's inner wall. NOT CERTIFIED (1 of 15 layers),
      1387 s, 6.39 g.
    - The rule did not remove the islands, and the islands are not in the gaps it
      governs. So it was not kept, and no other numbers were tried. The layout
      constants are unchanged.
  - **Real-slicer verdict with the committed code (2026-11-14):** clearance NOT
    CERTIFIED. The base plate is as measured before (`F3.printed_connectivity` FAIL at
    z 1.6 and 2.0; 15 layers, 1372 s, 6.12 g). The pieces plate is PRINTABLE (3 layers,
    490 s, 0.47 g).
  - **Open, for the controller and the owner:** the clearance base plate. The
    real-slicer test stays `xfail(strict=True)`, with the reason updated.
- **How the pieces are told apart (controller decision, 2026-11-14):** by plate order
  only, as the Task 2 amendment says. Task 3's form explains it to the owner.

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

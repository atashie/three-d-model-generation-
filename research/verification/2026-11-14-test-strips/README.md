# Test strips with the real slicer, 2026-11-14

Task 2 of `docs/plans/2026-11-14-test-strip.md` (its amendments after the real-slicer run).

**Questions:**
- Why does the pinned OrcaSlicer turn the skin strip a quarter turn?
- Where are the clearance base plate's two printed islands, and why are they there?
- Is a repeat run byte-identical?

**Short answers:**
- **The turn:** on a printer whose `printer_structure` is `i3` (the A1), OrcaSlicer's CLI
  arrange turns each item so that its principal axis lies along y. A strip long along y
  is not turned. The skin strip is now laid out long along y and is PRINTABLE.
- **The islands:** two pieces of infill, clipped where two fill regions meet inside the
  part. They are not in a narrow gap between two features. A derived gap rule was tried
  once and did not remove them. The owner decided to keep the FAIL and print anyway.
- **Repeat run:** every file is identical except one header line in each G-code (the time
  it was written), and the G-code hashes in `strip.json`.

**What kind of evidence:**
- **Source:** OrcaSlicer source at tag v2.5.0, read on 2026-11-14.
- **Measured:** real slices with the pinned OrcaSlicer 2.5.0 (app tree checked) and the
  pinned A1 profiles, on the owner's Windows PC on 2026-11-14. Nothing was printed.
- The diagnosis scripts were scratch scripts and are not kept. What they did is described
  below; every number here can be measured again from a `make_strips` run.

## 1. Why OrcaSlicer turns a strip long along x

### What was read

Files from `https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/v2.5.0/`:

| File | SHA-256 of the file read |
|---|---|
| `src/OrcaSlicer.cpp` | `a690a66e5ac117658f8751426984da5a5357d0b0abfd4e50460ebd35bf76060f` |
| `src/libslic3r/Arrange.cpp` | `c402f392d070e2aada6580f3b40cd79de8be8c552a2dfb77deba158fb865d28d` |

OrcaSlicer is AGPL-3.0. No code is copied here. The two short lines below are quoted as
evidence, with attribution (OrcaSlicer contributors, tag v2.5.0).

- **`src/OrcaSlicer.cpp`, the CLI's arrange (lines 5503 to 5507, and the same at 5978 to
  5982):** when the `align_to_y_axis` option is not given, it is set from the machine's
  printer structure:

  > `arrange_cfg.align_to_y_axis = (printer_structure_opt->value == PrinterStructure::psI3);`

  `tdmg` passes no `--align_to_y_axis` option. The A1's flattened `machine.json` (the
  pinned profile) has `"printer_structure": "i3"`.
- **`src/libslic3r/Arrange.cpp`, `update_selected_items_axis_align` (lines 249 to 351):**
  - it returns at once unless `align_to_y_axis` is set;
  - for each item it computes the second moments of area of the item's outline (a, b, c:
    the x, mixed and y central moments);
  - `ratio` is the smaller of |a| and |c| over the larger. Line 336:

    > `if (ratio>0.66) {`

    leaves the item unturned (no dominant axis);
  - otherwise the item is turned by π/2 − atan2(2b, a − c) / 2, and by 0 when that is
    within 0.01 of ±π.
- **For a rectangle w × h** (b = 0): the ratio is (min(w, h) / max(w, h))².
  - Long along x (a > c): atan2(0, a − c) = 0, so the turn is +π/2, a quarter turn
    counterclockwise.
  - Long along y (a < c): atan2(0, a − c) = π, so the turn is π/2 − π/2 = 0.
  - The skin strip, 118 × 26.5 mm: ratio 0.05, below 0.66, so it is turned when long along
    x and not turned when long along y.

### What was measured

- **The skin strip long along x (Task 2's first run):** the printed plastic spans bed x
  115 to 141 and y 69 to 187 mm, so it was turned. `F6.tool_placement`, the silhouette's
  `F3.edge_coverage` and `F3.edge_overprint`, and each tool's `F3.edge_overprint` FAILed.
- **The slicer's own log** for that input (re-run with `--debug 4`, same command and
  profiles):

  > `before arrange, need_arrange=1, duplicate_count 0, filament_color_changed 0`
  >
  > `Slic3r::GUI::PartPlateList::postprocess_arrange_polygon: bed_idx 0, selected 1, translation(x) 141.25, (y) 69`

  The translation (141.25, 69), with the plastic at x 114.75 to 141.25 and y 69 to 187,
  is consistent with a +90° turn of the 118 × 26.5 mm strip. The log line "Arrange full params" is cut off by the logger
  before it reaches `align_to_y_axis`, so the flag itself was not seen in the log.
- **The skin strip long along y (`SKIN_ALONG_Y`, committed code):** PRINTABLE. Every
  check PASSes, warnings included; only the information checks and `F6.portability` are
  UNKNOWN.
  - Printed plastic at bed x 114.75 to 141.25 and y 69 to 187 mm: not turned, centred on
    (128, 128).
  - 15 layers, 15 color changes, 2727 s (G-code header: model 39 m 12 s, total 45 m
    27 s), 10.29 g (header: 8.51 g black, 1.78 g white), flush 1125 mm³, prime tower
    769 mm³.

## 2. The clearance base plate's islands

### How they were found

- The base plate's G-code was read with `tdmg.printed.parse_gcode` and each layer's
  footprint built with `tdmg.printed.footprint` (the bead model), as
  `F3.printed_connectivity` does.
- R1's turn search placed the plate turned 90°. From the F3 checks' own bed and model
  points: model x = 47.5 + (bed y − 128) and model y = 12.25 − (bed x − 128).
- For each extra part: its area, its segments and their features, and the nearest bead of
  any other part.

### What was measured (committed layout, 95 × 24.5 mm)

`F3.printed_connectivity` FAILs on 2 of 15 layers. The holes match on every layer (21
printed, 21 in the model). `F3.edge_coverage` and `F3.edge_overprint` PASS. 1372 s, 6.12 g.

| z (mm) | Island | Model x (mm) | Model y (mm) | Nearest other bead |
|---|---|---|---|---|
| 1.6 | 1.634 mm², one sparse-infill path of 5 segments, width 0.45 mm | 13.19 to 15.30 | 5.22 to 7.33 | an internal-bridge line, 0.0032 mm |
| 2.0 | 0.272 mm², one internal-solid-infill closed path about 0.1 mm across, width 0.497 mm | 64.06 to 64.65 | 19.86 to 20.44 | an internal-solid-infill line, 0.0966 mm |

- **z 1.6:** right of pocket 1's label hole (centre (10, 6.5)) and below pocket 1's lower
  right corner (15, 9.5), about 2.2 mm from each. z 1.6 is the first of the 5 top shell
  layers (`top_shell_layers` 5) under the pocket floors at z 2.4. On it an internal
  bridge covers most of the plate above the label band. The sparse infill left in the
  label band is cut into pieces by the bridge region and the holes' walls.
- **z 2.0:** at the corner of the solid-infill region under pocket 5's floor (the pocket
  plus about 0.8 mm), just outside the pocket's top left corner (65, 19.5).
- **Profile values** (the pinned flattened `process.json`): `wall_loops` 2, outer wall
  0.42 mm, inner wall 0.45 mm, sparse infill 0.45 mm at 15 % (grid), internal solid
  infill 0.42 mm, `minimum_sparse_infill_area` 15 mm².
- **Reading:** neither island lies between two walls (below the pocket floor there is no
  wall around a pocket). Both are infill clipped where two fill regions meet.
- **Artefact or real part:** the z 1.6 gap, 0.0032 mm, is inside the bead model's
  recorded gap between beads that meet edge to edge (0 to about 0.03 mm;
  `research/verification/2026-11-13-color-slicing/README.md`, Task 5 cross-check). The
  z 2.0 gap, 0.097 mm, is not.

### The gap rule tried once (not kept)

- **Rule:** the solid between two holes, and between a hole and a pocket or the edge, is
  at least 2 × (outer wall + (`wall_loops` − 1) × inner wall) + one sparse line
  = 2 × 0.87 + 0.45 = 2.19 mm (values from the pinned profile).
- **Applied** (a scratch run only) as `LABEL_GAP_MM` 2.19 and `HOLE_PITCH_MM` 4.19. The
  strip was 95 × 25.57 mm, its thinnest wall 2.18 mm.
- **Result:** NOT CERTIFIED, 1 of 15 layers. The z 1.6 island was gone. At z 2.0 a new
  island: 0.413 mm² of internal solid infill at model x 68.2 to 68.8 and y 5.6 to 6.2,
  among pocket 5's label holes, 0.0175 mm from a hole's inner wall. 1387 s, 6.39 g.
- The rule was not kept, and no other numbers were tried.

### The owner's decision (2026-11-14)

"Keep the FAIL, print anyway". The base plate stays NOT CERTIFIED; `strip.json` carries a
`known_failures` note under the conditions in the plan's amendment.

## 3. Repeat run

`make_strips` was run twice with the real slicer (committed code) and every output file
compared byte for byte.

- **The same 14 files** in both runs.
- **Identical:** `clearance/base.stl`, `clearance/pieces.stl`, `skin/model.3mf`,
  `skin/palette.json`, `skin/slice/face-up/orca-input.3mf`, both filament profiles and
  all three `plate_1.statistics.json`.
- **Different:** each G-code (`clearance/slice/base/plate_1.gcode.failed`,
  `clearance/slice/pieces/plate_1.gcode`, `skin/slice/face-up/plate_1.gcode`) in exactly
  one line, the header "; generated by OrcaSlicer 2.5.0 on 2026-11-14 at <time>". Same
  length.
- **`strip.json`:** only those three G-codes' SHA-256 values, each in two places (the part's
  `gcode.sha256` and `outputs`). `strip_id` is the same
  (`8e853b952442cb17bdb01edc24ee1372ad8d56f65abc4ad6f97b9a2aede37039`).
- No log file is written for a strip, so none was compared.

## 4. The `tdmg strip` command (plan Task 3, 2026-11-14)

The command was run on the owner's Windows PC with the pinned OrcaSlicer 2.5.0 (app tree
checked) and the pinned A1 profiles, after the Task 3 review fixes:

```
uv run tdmg strip <scratch folder>\task3run --slicer-dir artifacts/tools/orcaslicer-2.5.0
```

- **Exit code:** 0.
- **Verdicts:**
  - skin strip PRINTABLE: 15 color changes, 2727 s (45 min), 10.29 g;
  - clearance pieces plate PRINTABLE: 3 layers, 490 s (8 min), 0.47 g;
  - clearance base plate NOT CERTIFIED, `F3.printed_connectivity` FAIL on 2 of 15
    layers: z 1.6 and 2 mm, each with 2 printed parts for the model's 1 and 21 printed
    holes for the model's 21. 1372 s (23 min), 6.12 g. The `known_failures` note is
    given, so the command exits 0 (the owner's decision, section 2).
  - The times and weights are the slicer's estimates.
- **strip_id:** `8e853b952442cb17bdb01edc24ee1372ad8d56f65abc4ad6f97b9a2aede37039`, the
  same as in section 3.
- **The terminal output** (OUT shortened to `<OUT>`):

  ```
  clearance strip: NOT CERTIFIED: base: F3.printed_connectivity FAIL
    base plate: NOT CERTIFIED: F3.printed_connectivity FAIL - 15 layers, time 23 min, filament 6.12 g
    pieces plate: PRINTABLE - 3 layers, time 8 min, filament 0.47 g
    the base plate fails one check: small loose bits of infill inside the part, on 2 of 15 layers (z 1.6, 2 mm); you decided on 2026-11-14 to print it anyway. Details: strip.json
  skin strip: PRINTABLE
    face up: 15 color changes, time 45 min, filament 10.29 g
  times and filament are the slicer's estimates
  to print, in <OUT>:
    clearance strip: open clearance/base.stl and clearance/pieces.stl in Bambu Studio and print them as two plates in the same filament. Keep the pieces in their row, left to right
    skin strip: open skin/model.3mf in Bambu Studio and print it on the AMS: filament 1 black (the base), filament 2 white (the patches)
    after printing, fill in results-template.md; the record is strip.json
    the plate_1.gcode files are for checking only, not for printing
  strip_id 8e853b952442cb17bdb01edc24ee1372ad8d56f65abc4ad6f97b9a2aede37039
  ```

- **`results-template.md`:** written, six clearance rows (0.10 to 0.35 mm) and seven
  skin rows. It was byte-identical to the form from the run before, made before the
  review fix that builds the instructions' counts from the record (with the owner's
  values the text is the same).
- The same verdicts, numbers and `strip_id` came from two earlier runs of the command the
  same day, before the review changed only the terminal wording.
- Nothing was printed. Task 4 adds the full measured-run record and the Codex review.

## 5. After the Codex review fixes (plan Task 4, 2026-11-14)

The Codex review (`research/reviews/2026-11-14-test-strips/`) changed the note's
conditions (base plate only), the note's and the terminal's wording, the skin warnings in
the terminal, `print_settings` in `strip.json` and the form. No geometry, slice or check
changed. On the owner's Windows PC, with the pinned OrcaSlicer 2.5.0 (app tree checked):

- `TDMG_ORCASLICER_DIR=artifacts/tools/orcaslicer-2.5.0 uv run pytest -m slicer
  tests/test_calibration_strip.py`: 1 passed.
- `uv run tdmg strip <scratch folder>\task4run --slicer-dir
  artifacts/tools/orcaslicer-2.5.0`: exit 0. The same verdicts and numbers as section 4,
  and the same `strip_id` (`8e853b952442cb17bdb01edc24ee1372ad8d56f65abc4ad6f97b9a2aede37039`).
  The skin face had no warnings. `print_settings`: process preset "0.20mm Standard @BBL
  A1", layer height 0.2 mm, first layer 0.2 mm, elephant foot compensation 0.075 mm. The
  terminal output (OUT shortened to `<OUT>`):

  ```
  clearance strip: NOT CERTIFIED: base: F3.printed_connectivity FAIL
    base plate: NOT CERTIFIED: F3.printed_connectivity FAIL - 15 layers, time 23 min, filament 6.12 g
    pieces plate: PRINTABLE - 3 layers, time 8 min, filament 0.47 g
    the base plate fails one check: more printed parts than in the model, on 2 of 15 layers (z 1.6, 2 mm).
    On 2026-11-14 these were small loose bits of infill inside the part, and you decided to print it anyway. This run's parts are counted, not sized. Details: strip.json
  skin strip: PRINTABLE
    face up: 15 color changes, time 45 min, filament 10.29 g
  times and filament are the slicer's estimates
  to print, in <OUT>:
    clearance strip: open clearance/base.stl and clearance/pieces.stl in Bambu Studio and print them as two plates in the same filament
      do not move, turn or arrange the pieces; results-template.md says how to keep them in order
    skin strip: open skin/model.3mf in Bambu Studio and print it on the AMS: filament 1 black (the base), filament 2 white (the patches)
    after printing, fill in results-template.md; the record is strip.json
    the plate_1.gcode files are for checking only, not for printing
  strip_id 8e853b952442cb17bdb01edc24ee1372ad8d56f65abc4ad6f97b9a2aede37039
  ```

- **Limit, not changed:** the note still counts parts and does not size them, so it
  cannot tell these infill islands from a plate split in two (review finding 2). It says
  so in `limit`. The owner decided "Not now" (2026-11-14).
- Nothing was printed.

## 6. After the owner's decisions on the review (2026-11-14)

The owner's decisions (review README, findings 2, 3, 4 and 6): the white tool's
`F3.edge_coverage.T1` and `F3.printed_connectivity.T1` are required for the skin strip
(algorithm `strip-3`), and the form judges each piece in three steps. On the owner's
Windows PC, with the pinned OrcaSlicer 2.5.0 (app tree checked):

- `TDMG_ORCASLICER_DIR=artifacts/tools/orcaslicer-2.5.0 uv run pytest -m slicer
  tests/test_calibration_strip.py`: 1 passed (it now asserts both white checks required
  and PASS, and `strip-3`).
- `uv run tdmg strip <scratch folder>\task4owner --slicer-dir
  artifacts/tools/orcaslicer-2.5.0`: exit 0. The terminal output is as in section 5,
  except the last line, `strip_id
  3f5fc698678dc19b97edb55e03f7623a1ecbe5e87e06512fca0818ad2a67a197` (new: the algorithm
  label changed).
  - **Skin strip:** PRINTABLE, 15 color changes, 2727 s (45 min), 10.29 g. All nine F3
    checks PASS: the silhouette's three and each tool's three, including
    `F3.edge_coverage.T1` and `F3.printed_connectivity.T1`. No warnings.
  - **Clearance strip:** as in section 5. The base plate NOT CERTIFIED by
    `F3.printed_connectivity` alone (z 1.6 and 2 mm), with the note; the pieces plate
    PRINTABLE.
  - **The form:** one row per gap with eight boxes: (a) won't go in, pressed in, drops
    in; (b) flat: yes, no; (c) play: none, a little, a lot.
- Nothing was printed.

## 7. The skin strip printed (plan Task 5, 2026-11-15)

The owner printed the skin strip on their Bambu Lab A1 and reported the result in this
session. This is the first print of this step: **calibrated** evidence (printed on our
printer), judged by the owner's eye, as Decision 5 planned.

- **What was printed:** `skin/model.3mf` from the `make_strips` run of section 6
  (strip_id `3f5fc698678dc19b97edb55e03f7623a1ecbe5e87e06512fca0818ad2a67a197`), from
  Bambu Studio. The owner's words on the settings: "I didn't change any settings". The
  Bambu Studio version was not recorded.
- **Filament:** eSUN PLA+, white over black. The owner's words: "esun pla+".
- **What the owner saw:**
  - top face (the face printed up): every patch with label holes was white;
  - bottom face (the face on the plate): only the patch without holes at the white end
    was white, as designed (the depth patches are white only in their top layers).
- **The result, in the owner's words:** "every square is opaque."
- **The form, from that answer:**

| Patch | Label holes | White depth (mm) | Result |
| --- | --- | --- | --- |
| 1, black reference | 0 | none (black only) | - |
| 2 | 1 | 0.2 | looks like full white |
| 3 | 2 | 0.4 | looks like full white |
| 4 | 3 | 0.6 | looks like full white |
| 5 | 4 | 0.8 | looks like full white |
| 6 | 5 | 1.0 | looks like full white |
| 7, full white reference | 0 | 3.0 (full) | - |

- **Photo:** none. The owner's words: "No, it is opaque, we don't need the picture."
- **What it shows:** with eSUN PLA+ white over black, 0.2 mm of white (one layer at the
  0.20mm Standard preset) already looks like full white. The thinnest patch passed, so
  the strip gives only an upper bound: the smallest depth that hides black is 0.2 mm or
  less. It says nothing about margin: another white, other settings or other light were
  not tested.
- **The owner's decision (2026-11-15):** keep `color.skin.depth_mm` at 0.6 mm, "Keep 0.6
  mm (Recommended)". It is three times the thinnest depth that passed, and the value also
  sets the glue pocket depth and piece thickness, so no model and no owner plan changes.
- **What changed in `rules/color.yaml`:** `color.skin.depth_mm` is now `kind: empirical`
  (the claim that 0.6 mm of white hides a black base is a physical printing rule and was
  printed), with this record as `calibrated` evidence and a calibration block. The calibration holds for
  this printer, nozzle (0.4 mm), material (eSUN PLA+ white over black), slicer (Bambu
  Studio, version not recorded) and profile (0.20mm Standard @BBL A1); other pairs are
  not covered. Not covered by this print: whether 0.6 mm glue pieces survive handling
  (the clearance strip, not yet reported).
- **Not yet reported:** the clearance strip.

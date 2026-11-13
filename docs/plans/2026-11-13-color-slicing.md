# Multicolor slicing (R2 step 4) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** build step 4 of the R2 color design (`docs/plans/2026-11-11-color-design.md`).
`tdmg slice` accepts a `tdmg flat --colors` folder. It slices the AMS version face up and
face down with the pinned OrcaSlicer, each color on its own filament. It then gates the
G-code and reports, for each face:
- the color changes;
- the flush and prime-tower waste;
- the time and the filament.

It also slices each glue plate as an R1 part. It prints nothing; that is step 5.

**Architecture:**
- **Prerequisite (Task 1):** the pinned A1 machine profile is incomplete. It must be fixed
  before any G-code from `tdmg` is printed, R1 included (Decision 1).
- **The slicing input:** an OrcaSlicer-only 3MF, written into the slice folder from the
  gated bodies. It is a slicer input, not a deliverable: the portable `model.3mf` stays
  the file to print from (Decision 2).
- **The checks:** each color change and each tool's extrusion is checked against the
  geometry, not against the slicer's own report (Decision 4).

**Tech stack:** the pinned OrcaSlicer 2.5.0 (Windows) and the existing `tdmg.slicer`,
`tdmg.slicing`, `tdmg.threemf` and `tdmg.color_checks`, plus lib3mf as the reader. No new
dependency.

**Status:** written 2026-11-13; the owner approved it on 2026-11-13 ("approved; please proceed").

**Format:** the repo's plan style: decisions with evidence, then tasks with tests. Every
task is test-first and gets subagent spec and quality reviews; the Codex review comes in
the last task.

## What is known (evidence)

- **The pinned A1 profile lacks the A1's own G-code (found 2026-11-13, while writing this
  plan).** Upstream `Bambu Lab A1 0.4 nozzle.json` (hash as pinned, `1291507…`) has an
  `include` key listing five template presets:
  - `machine_start_gcode`;
  - `machine_end_gcode`;
  - `time_lapse_gcode`;
  - `change_filament_gcode`;
  - `layer_change_gcode`.

  `scripts/setup_orcaslicer.py` `flatten` follows only `inherits`, so these templates
  never reached `profiles-flat/machine.json`. The flat profile holds the generic ones
  from the parent chain instead.

  | G-code | A1 template (fetched from tag v2.5.0, not yet pinned) | Pinned flat profile |
  |---|---|---|
  | start | 12,310 characters, with the AMS load `M620` | 577 characters (generic: `G29`, a purge line, `M109 S205`), no `M620` |
  | filament change | 6,156 characters | 4,030 characters |
  | end | 2,902 characters | 1,358 characters |
  | layer change | equal | equal |

  So every `tdmg slice` G-code so far, R1's PRINTABLE ones included, starts with
  non-A1 G-code. `tdmg slice` tells the user to "print plate_1.gcode on the A1".
  - **The owner's prints:** the one owner print was sliced in Bambu Studio, with Bambu's
    own profile.
  - **How Orca applies `include`:** not yet read (Task 1).
- **Step 3 Task 1** (`research/verification/2026-11-12-color-3mf/README.md`):
  - **Separate objects fail:** both CLIs drop each separate top-level object to the bed.
  - **D:** one object with one shell per color (`model.3mf`) stays in place, but
    OrcaSlicer prints it on one filament.
  - **B_msc works:** one components object, one mesh part per body, and
    `Metadata/model_settings.config` giving each part an `extruder`. Imported in place,
    with each body on its own filament.
    - Roadie: T1, T2 and T3 extrude only on the inlays' layers (Z 2.6 to 3.0) and within
      their XY extents.
    - The statistics count 8 filament changes.
  - **Statistics are not trustworthy:** OrcaSlicer's per-filament statistics disagree
    with the G-code, so the record does not trust them.
  - **The owner and B_msc:** the owner's Bambu Studio showed B_msc in one color.
- **The owner's decisions:**
  - color design Decision 5: measure face up and face down, then decide;
  - the owner assigns the filaments in their slicer (step 3).
- **PLAN section 2 point 7:** files are portable. A slicer-specific file is an extra file
  only, and only if a recipe needs one.

## Decisions

1. **Fix the profile first (Task 1).**
   - **Flattener:** it resolves `include` the way OrcaSlicer 2.5.0 does, read from its
     source at the tag, with every template file pinned by hash.
   - **Re-pin:** the flat machine profile's hash changes, so the pin is updated.
   - **R1:** R1's slice algorithm label is bumped. The owner's two R1 slices are re-run
     and recorded again.
   - **Message:** until Task 1 is done, `tdmg slice` stops telling the user to print its
     G-code: it says to slice `model.stl` in Bambu Studio instead. This is a one-line
     change, made at the start of Task 1.
2. **Slicing input: an OrcaSlicer-only 3MF in the slice folder** (`orca-input.3mf`).
   - **Encoding:** B_msc (Task 1 evidence), built from the same gated meshes as
     `model.3mf`, with each part's `extruder` set to its palette index + 1.
   - **The base is filament 1**, so the start G-code loads the base color.
     - **Amended in Task 4 (controller, 2026-11-13):** a plan's base can be any palette
       index, so the extruder is the body's position in shell order + 1 (the base
       first, so it is always filament 1; then the inlays by palette index), not
       "palette index + 1". The record and the message give the filament for each
       color.
     - **Amended after Task 2 (controller, 2026-11-13):** that holds face up only. The
       A1 start code loads OrcaSlicer's first tool on layer 1
       (`initial_no_support_extruder`). Face down, every color is on layer 1, and
       OrcaSlicer chose filament 2, 3 or 4 in three of the four plans. That is normal
       printer behaviour, so the requirement is now: the start block loads exactly one
       filament, and it is the first tool that prints on layer 1.
   - **Filament profiles (added after Task 2):** OrcaSlicer computes the flush volumes
     and the tool order from `filament_colour`, which the 3MF does not carry. So each
     filament is the pinned profile with only `filament_colour` set to its palette color.
     The record holds each derived profile's hash and proves that only that key differs.
   - **Writer:** deterministic, like `tdmg.threemf`.
   - **Check:** a new gate check reads it back and requires each part to be its body
     exactly. It is `model.3mf`'s check, adapted to parts.
   - **Not a deliverable:** the record says so.
3. **Face down: rotate, not mirror.** Each body is rotated 180° about the y axis through
   the model's centre: x → x0 + x1 − x, z → T − z.
   - **Why a rotation:** it keeps every mesh closed and oriented. Turned back over, the
     face reads the right way round.
   - **Exactness:** the rotated coordinates are exact float32 (the sums are on the
     storage grid). Task 3 proves this or finds the exceptions.
   - **Two G-codes:** `face-up/plate_1.gcode` and `face-down/plate_1.gcode`. Both are
     gated, and the record compares them.
   - **No default face yet:** the owner picks one after seeing the numbers (Task 7).
4. **What is measured and gated, per face.** Every check reads the G-code. The expected
   values come from the gated bodies.
   - **`F6.color_changes`:**
     - from the bodies, each layer's set of colors (a body is on a layer when the layer's
       slice height is inside its z range);
     - the minimum number of changes: Σ over layers (colors on the layer − 1), plus one
       wherever a layer does not start with the previous layer's last color;
     - the G-code's tool changes (`T<n>` below 255, after the start G-code) must equal
       that minimum. If OrcaSlicer orders tools differently, the check FAILs, and Task 2
       records why before any rule is relaxed.
     - **Amended after Task 2 (controller, 2026-11-13):** OrcaSlicer orders each layer
       without looking ahead. Face down it made 10 changes where the true minimum is 9,
       on every plan with the profile colors. The gated rule is now:
       - (a) each layer's set of tools in the G-code equals the set of bodies on that
         layer (from the bodies);
       - (b) on each layer, every tool prints in one contiguous run;
       - (c) the change count equals Σ over layers (colors − 1), plus the layer
         boundaries where the next layer's first tool differs from the previous layer's
         last.
       - The true minimum is recorded as information.
       - **What counts:** a change is one `T<n>` (n < 255) after the first
         `; CHANGE_LAYER` and before the end block, inside `M620 S<n>A` … `M621 S<n>A`
         and `; CP TOOLCHANGE START` … `END`. The start load and the end unload
         (`T255`) are not changes. Evidence:
         `research/verification/2026-11-13-color-slicing/README.md`.
   - **`F6.tool_placement`:** each tool extrudes only on its body's layers, and within
     its body's footprint, with the same bead model and tolerance as R1's
     F3 (no new number). Every body is printed by its own tool. This is
     the check Task 1 of step 3 did by hand.
   - **`F6.filaments_used`:** exactly the plan's colors are used, each once as a filament.
   - **Information only, not gated (UNKNOWN status):**
     - the flush and prime-tower volume, from the G-code's own markers (Task 2 finds
       which), and the time;
     - the total filament per tool, from the G-code (not the statistics);
     - the statistics' `filament_changes`, recorded beside the G-code count.
   - **F3 (thin features) per color:** R1's footprint checks run on each layer's union of
     all tools (the silhouette, as in R1) and on each tool's footprint. Kept outline
     bands narrower than a bead (Roadie keep: 14.3 mm² under 0.4 mm) show up here.
     Whether a per-color F3 FAIL blocks PRINTABLE is an owner decision in Task 7, made
     from the measured numbers. Until then, the per-color F3 checks are information.
     - **Amended in Task 5 (controller, 2026-11-13, after review):** until the owner's
       Task 7 decision, every F3 result (the silhouette's three and each tool's three)
       is required for PRINTABLE, not information. Without them, a G-code that prints
       half an inlay passes the three F6 checks. Measured on the Task 2 G-codes:
       - the silhouette's `F3.printed_connectivity` FAILs on every multicolor layer,
         because neighbouring tools' beads meet edge to edge (gaps up to about 0.03 mm
         in the bead model);
       - its `F3.edge_coverage` FAILs face down on Roadie keep and Oddie keep.

       So no owner plan is PRINTABLE until Task 7. The owner then decides from the
       numbers which, if any, become information.
     - **Also from the Task 5 review:** prime-tower plastic must not reach into the
       silhouette (`F6.tool_placement`).
     - **No quarter-turn search for color (controller, 2026-11-13):** R1 lets the model
       match in any quarter turn. For a symmetric model, a color swap then equals a
       correct print turned 180°, and it passed. OrcaSlicer places the color input in
       place and centred, with no rotation (Task 2), so color slices are checked at that
       placement only.
5. **Glue plates:** each `glue-*.stl` is sliced as an R1 part, with R1's checks unchanged.
   Its record is beside the AMS record in the same `slice.json`.
   - **Amended in Task 6 (controller, 2026-11-13):** two R1 checks do not fit a plate of
     loose pieces.
     - `F2.target_width` is dropped for glue plates: the target width belongs to the
       whole model.
     - `F4.body_count` is required against the plate's piece count from `colored.json`'s
       glue report (the glue base is one body).
6. **PrusaSlicer:** `F6.portability` runs on the portable `model.3mf`: `--info` reads it
   as one manifold object, and it slices, single extruder, as measured in step 3.
   - **Note (Task 6):** the volume is information, not a condition. R1's STL volume
     tolerance is derived for admesh's computation, which does not reproduce
     PrusaSlicer's 3MF volumes. Measured differences from the palette sum: −1.23 to
     +0.25 mm³. The
   OrcaSlicer-only input is not given to PrusaSlicer.
7. **Record and command:**
   - **Command:** `tdmg slice COLORED_DIR --out DIR` writes `slice.json` (schema
     `tdmg.colorslice/1`) with a `colorslice_id`. The id covers the colored record's
     hash, the input 3MF's hash, the pinned slicer and profiles, the command template and
     the face.
   - **Verdict:** PRINTABLE only if every required check passes on that face. The
     verdict is per face and per glue plate.
   - **A FAIL:** quarantines its G-code (`.failed`), as in R1.
   - **The message:** names the G-code to print and the filament each color goes on.

## Tasks

1. **Profile fix** (Decision 1).
   - **First step:** the print message (one-line change, with a test).
   - **Read the source:** how OrcaSlicer v2.5.0 resolves `include`, from
     `PresetBundle.cpp` / `Preset.cpp` at the tag. Record the file, the function and the
     lines in `research/verification/2026-11-13-a1-profile-include/`.
   - **Flattener:** it resolves `include` that way; the pin lists every template file's
     hash.
   - **Tests:** the flattener against fixture chains with and without `include`;
     `--verify-only` passes on the PC.
   - **Real slice, Roadie R1:** the start G-code in the output is the template's (its
     first lines and its `M620` load).
   - **R1 re-runs:** the slice label is bumped and the owner's two R1 slices are re-run.
     Their verdicts are recorded again, old against new: layers, time, weight and F3.
   - **Stop and report** if Orca's resolution differs from a plain merge in a way the
     source does not explain.
2. **Slicing experiment** (research first; `research/verification/2026-11-13-color-slicing/`).
   - **Files:** the B_msc input for the four owner plans, face up and face down, sliced
     with the fixed profile.
   - **Recorded from each G-code:**
     - the tool-change order per layer;
     - whether the start G-code loads filament 1;
     - the flush and prime-tower markers and volumes;
     - the time;
     - per-tool extents.
   - **Compared:** the G-code counts against the statistics.
   - **Decides:** the exact counting rules of Decision 4 (which commands count as a
     change, and where the start G-code ends) and the markers to read.
   - **Stop and report** if any face fails to slice, or if a body lands on the wrong
     tool or out of place.
3. **Face-down geometry.** A function turns the gated bodies over (Decision 3).
   - **Tests:**
     - exact float32 coordinates;
     - F1 still passes;
     - the volumes are equal;
     - turning twice gives back the original;
     - the inlays sit at z 0 to the skin depth.
4. **`orca-input.3mf` writer and its read-back check** (Decision 2).
   - **Tests:**
     - byte-identical repeat runs;
     - lib3mf read-back of every part, exactly;
     - each part's extruder in `model_settings.config`;
     - the failure cases from step 3's check (a moved vertex, a missing or extra part, a
       wrong extruder, an aliased zip part).
5. **G-code readers and the checks** `F6.color_changes`, `F6.tool_placement` and
   `F6.filaments_used`, plus the information measures (Decision 4).
   - **Tests:** hand-written G-code fixtures with known answers:
     - a change too many;
     - a tool on the wrong layer;
     - a tool outside its body;
     - a missing body;
     - an extra filament.
   - **Real slicer:** the Task 2 G-codes, under `-m slicer`.
6. **Wire into `tdmg slice`** (Decisions 5–7). It covers both faces, the glue plates,
   PrusaSlicer on `model.3mf`, the record and id, the quarantine and the message.
   - **Tests:**
     - the refusals: a colored folder without `colored.json`, a tampered record, a
       missing STL;
     - repeat runs give the same record;
     - R1 folders behave as before (apart from Task 1's label and the message);
     - the CLI output.
   - **Owner plans:** re-run all four.
7. **Owner review.**
   - **Done 2026-11-13.** Material: `research/verification/2026-11-13-color-slicing/
     owner-review.txt` and the images in `artifacts/color-review/` (git-ignored). The
     owner chose from two questions (AskUserQuestion, answers verbatim):
     - default face: "Face up (Recommended)";
     - F3 gating: "Outer edge only (Recommended)". As offered: the whole-model edge
       coverage and each color's overprint are gated, and per-color coverage and all
       connectivity become warnings in the record. Face up, all four plans become
       PRINTABLE, but the keep plans print with their thin interior outline lines
       missing, reported as a warning.
   - **What follows in code:**
     - `tdmg slice` slices face up by default (`--face down` or `--face both` on
       request);
     - the required F3 set is the silhouette's `F3.edge_coverage` and
       `F3.edge_overprint`, plus each tool's `F3.edge_overprint`;
     - the silhouette's and each tool's `F3.printed_connectivity` and each tool's
       `F3.edge_coverage` are warnings: recorded, and printed by the CLI when they do
       not pass.
   - **Shown:** face up against face down (changes, waste, time, the per-color F3
     numbers) and the G-code preview images.
   - **The owner decides:**
     - the default face;
     - whether a per-color F3 FAIL blocks PRINTABLE.
   - **Recorded:** the decisions verbatim; the defaults are set.
8. **Docs, STATUS, Codex review, push and CI.**

## Out of scope

- Printing anything, and the test strip (step 5).
- Choosing the flush volumes. They are the slicer's, measured here and not tuned.
- Reordering colors within a layer (color design, "Not done").
- PrusaSlicer multi-extruder slicing.
- A Bambu Studio project file. The owner assigns filaments in Bambu Studio from
  `model.3mf`, as in step 3.

## Risks

- **Fixing the profile changes R1.** The R1 verdicts are re-run in Task 1; if one changes,
  STATUS says so.
- **The minimum-change count may be too strict.** OrcaSlicer's tool order may not match
  Decision 4's "minimum". Task 2 measures the order before the rule is fixed.
- **The glue route as a print:** the glue plates may need more than one plate on the A1
  bed. Each is sliced on its own here.
- **CI:** CI has no real slicer, so the `-m slicer` tests run on the PC only, as in R1.

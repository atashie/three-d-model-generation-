# Pipeline and gate

The full design is in [the plan, section 4](../PLAN.md#4-pipeline-stages-and-the-gate-contract). This page is the short version.

## Stages

| Stage | What happens |
|---|---|
| S0 Intake | Load and hash the image; read the job: print type, target size in mm, printer, filaments, optional plain-language interpretation |
| S1 Perception | Resolve subject/exclusions, show an editable cutout preview, save the mask and report unresolved instructions; optionally estimate depth. Machine learning, fenced and cached |
| S2 Base geometry | Build the shape: extrude a flat outline, build a height grid, or generate 3D |
| S3 Normalize | One explicit image-to-model transform (origin, scale, Y flip), units, target size, orientation, triangle budget |
| S4 Entry gate and repair | Make the geometry valid before any boolean operation; repair from least to most destructive |
| S5 Features | Add bases, loops, text, joints, connectors, cuts. After scaling, so clearances stay absolute |
| S6 Color | Assign colors in the way the print type needs |
| S7 Package | Write a portable 3MF (standard format, colors not slots), plus STL on request, with stable IDs |
| S8 Final gate | Read the written file back and run every required check |
| S9 Slicer check | Slice headless with a pinned slicer and profile; check the result |
| S10 Manifest | Record verdicts, evidence, assumptions and file hashes |

## What "printable" means

The [input interpretation](input-interpretation.md) step (`tdmg select`) records which
subject the user wants and shows it for review. Geometry checks do not determine that: a
valid solid can still include an unwanted background.

## What exists today

- **`tdmg select`** covers S0 and S1, with explicit controls and no language
  interpretation.
- **`tdmg flat`** covers S2–S4 and S8 for flat (G1) shapes. It:
  - outlines the mask, smoothed by default (`--smooth-px 0` gives the exact pixel
    outline), and transforms it to millimetres;
  - removes slivers and specks by the cleaning rules (`flat.sliver.opening_width`,
    `flat.island.min_square_side`, both untested hypotheses);
  - extrudes the shape and writes `model.stl`, `outline.png` and the record `DIR/flat.json` (`--out DIR`);
  - gates the bytes it writes, with F1, F2, `F3.thin_regions` (measured; always
    UNKNOWN), F4, F5 and the placeholder `F6.slicer` (always UNKNOWN).

  Its verdict is therefore always NOT CERTIFIED. Exit code 0 means only that no check
  failed; 1 means a check failed (files written); 2 means an input or I/O error.
- **`tdmg slice`** covers S9 (see below). It judges thin features from the G-code and
  replaces the placeholder F6 check with measured ones. It also slices a
  `tdmg flat --colors` folder, each color on its own filament (the last section).
- **`tdmg colors`** is the first half of S6 for flat multicolor (R2; see below). It
  writes a color plan for review.
- **`tdmg flat --colors`** builds the plan's colored bodies as STL files, for an AMS
  print and for a glued print, and writes the AMS bodies as one multicolor `model.3mf`
  (see below). `tdmg slice` slices them (see the last section).

There are no loops or bases yet. The only 3MF output is the multicolor `model.3mf`.

Every check returns **PASS**, **FAIL**, or **UNKNOWN**, with the measured value, the threshold, and the rule it came from. A check that cannot be measured is UNKNOWN; it never passes silently. Each recipe declares the checks it requires. The verdict is **PRINTABLE** only if all of them pass. Otherwise it is **NOT CERTIFIED**, with the reasons.

| Family | What it checks |
|---|---|
| F1 Format and topology | Closed, manifold, consistently oriented, no pinched vertices, positive volume (`format.3mf.edge_manifold`, `format.3mf.consistent_orientation`, `gate.topology.vertex_manifold`); self-intersection is a warning (`format.3mf.self_intersection_is_warning`) |
| F2 Scale and fit | Units, target size, fits the A1's 256 mm build volume, numbers in a safe range |
| F3 Printability geometry | Thin walls, small features, overhangs, trapped supports, stability |
| F4 Structure-specific | Joint clearances, body count, connector fit, color regions |
| F5 Resources | Triangle count (`slicer.orca.max_triangles_per_plate`), file size |
| F6 Sliced output | Two slicers, OrcaSlicer and PrusaSlicer, accept the file and produce the expected objects; for 3MF their readers must differ |

If no slicer is installed, F6 is UNKNOWN, so nothing can be PRINTABLE. Without
PrusaSlicer (`--prusaslicer-dir` or `TDMG_PRUSASLICER_DIR`), `F6.portability` is UNKNOWN,
so the verdict is NOT CERTIFIED.

**`tdmg slice` (S9, 2026-11-10)** slices a `tdmg flat` output with a pinned,
hash-verified OrcaSlicer 2.5.0 and the Bambu A1 profiles. It replaces the placeholder
with measured F6 checks:

- **F6.slicer_exit:** the decoded exit code.
- **F6.gcode_present:** the slicer wrote G-code.
- **F6.layer_count:** the layer count matches the expected count. This catches a
  truncated print; an open mesh slices with exit 0 to a fraction of its layers.
- **F6.single_object:** one object in the slicer's statistics.
- **F6.portability (2026-11-11):** a second pinned, hash-verified slicer, PrusaSlicer
  2.9.7, must read `model.stl` as modelled and slice its full height. `--info` must report
  a manifold mesh with no open edges, the record's part and facet counts, its sizes and
  its volume within derived float bounds. `--export-gcode`, with the bed, nozzle, layer
  and filament settings taken from the pinned A1 profile (every other setting is
  PrusaSlicer's default, so this is not the A1 print process), must write a complete
  G-code with the expected layer count and Z heights, and with extrusion on every layer
  at that layer's height. That shows plastic is laid on every layer to the top, not that
  each layer is fully printed. Its exit code 0 alone is not trusted: an
  outside-bed part exits 0 with no G-code, and an open mesh exits 0 with a truncated one.
  Both slicers read STL with the same library (admesh), so for STL this shows that a
  second slicer accepts the file; it does not show that an independent reader agrees.
  PrusaSlicer's output is kept as `prusaslicer.portability-only.gcode.txt`. It is
  generic G-code, not for the A1: **never print it.** Each PrusaSlicer run is limited by
  `slicer.prusa.timeout_s`. `--skip-tree-check` skips the full install check for both
  slicers and caps the verdict at NOT CERTIFIED.

It also measures F3 from the G-code (the thin-wall policy the owner approved,
`docs/plans/2026-11-10-thin-wall-policy.md`). Each extruding move is modelled as a
"bead", a line of its stated width with round ends, and the printed footprint of every
layer is compared with the model's section at that height:

- **F3.printed_connectivity:** on every layer, the printed parts and holes match the
  model's one to one. A narrow connection the slicer drops FAILs it.
- **F3.edge_coverage:** every model-edge sample is within `acceptance.dimension.tolerance`
  (0.2 mm) of printed plastic; on the first layer the allowance adds the profile's
  elephant-foot compensation (0.075 mm, so 0.275 mm).
- **F3.edge_overprint:** the reverse. No printed plastic lies farther than the same
  allowance outside the model.

G-code the analysis does not understand gives UNKNOWN, never PASS. These checks hold
only for the pinned OrcaSlicer 2.5.0 A1 profile, do not judge strength, and keep sharp
corners strict (a corner sharper than about 62° can fail coverage). `F3.thin_regions`
from the flat record is carried along as information only.

The slice verdict requires every check of the flat record except `F6.slicer` and
`F3.thin_regions`, plus the F3 and F6 checks above. With both slicers, the owner's
Roadie and Oddie (60 × 3 mm, smoothed) are **PRINTABLE** (2026-11-11, and again after
the float64 blur of flat-3; `research/verification/2026-11-11-prusaslicer-windows/`).
They are PRINTABLE again with the fixed A1 profile (`slice-5`, 2026-11-13, next section).

### The A1 profile and the G-code reader (`slice-5`, 2026-11-13)

- **What was wrong:** the A1 machine preset has an `include` key. It names five template
  presets: the start, end, time-lapse, filament-change and layer-change G-code. The
  flattener followed only `inherits`, so the flat `machine.json` held the generic G-code
  of the parent presets. Its start G-code had 577 characters and did not load the AMS.
- **The fix:** `scripts/setup_orcaslicer.py` now resolves `include` as OrcaSlicer 2.5.0
  does, read from its source at tag v2.5.0. A preset is its parent's resolved settings,
  then each included template in the order listed, then the preset's own keys. Every
  template file is pinned by hash, and a template that does not match the pin is
  refused. The start G-code is now the A1's own: 12,310 characters, with the AMS load
  (`M620`). `--profiles-only DIR` flattens the profiles again for a verified install.
- **The label:** the slice algorithm is now `slice-5`, so a `slice_id` made with the
  old profile differs from a new one.
- **The firmware G-command rule:** the A1 G-code holds Bambu firmware commands that are
  not moves, such as G392 and G39.3. `tdmg.printed` accepts only the ones the pinned A1
  template writes: G392, G380, G39, G39.3, G39.4, G29.2, G29.4 and G2814
  (`FIRMWARE_G_COMMANDS`). It accepts them in two places only:
  - in FEATURE "Custom" (the start and end code);
  - in the time-lapse code that runs at each layer change, between the template's
    `; SKIPPABLE_START` and `; SKIPPABLE_END` lines. Such a block may not extrude.

  After a firmware command, the head position is unknown until the next absolute X, Y
  and Z. Any other G-command outside the reader's list is refused everywhere, so the F3
  checks are UNKNOWN, never PASS.
- **The R1 re-runs:** Roadie and Oddie are PRINTABLE, with the same F3 numbers as on
  2026-11-11. The slicer's time estimate is longer with the fixed profile (Roadie
  471.9 → 866.7 s, Oddie 484.2 → 876.1 s), and its weight estimate is 0.025 g lower.
  Record: `research/verification/2026-11-13-a1-profile-include/`.
- **The print message:** when the verdict is PRINTABLE, `tdmg slice` says: "slice
  model.stl in Bambu Studio to print; plate_1.gcode is for checking only (tdmg's G-code
  is not yet printed or compared with Bambu Studio's own slice); …".

### What PRINTABLE means for you

PRINTABLE means: every check this project requires passed, for this exact file, with
these exact slicer versions and the A1 profile. To print, open `model.stl` in Bambu Studio
and slice it there; `tdmg slice` says so. `plate_1.gcode` is for checking only: no G-code
from `tdmg` has been printed or compared with Bambu Studio's own slice, and until
2026-11-13 the pinned A1 profile lacked the A1's own start, end and filament-change G-code
(`research/verification/2026-11-13-a1-profile-include/`). PRINTABLE is a strong "nothing
we know how to measure is wrong", not a promise:

- **Size accuracy is not proven.** The 0.2 mm tolerance in `acceptance.dimension.tolerance`
  is a hypothesis until a print is measured with calipers.
- **Strength is not judged.** A thin part can print and still snap.
- **Other settings are not covered.** A different printer, nozzle, material profile or
  slicer version is outside what was checked.

The slicer does not validate meshes, so F1 still guards topology. When any required
check FAILs, the G-code is written as `plate_1.gcode.failed` instead of `plate_1.gcode`;
do not print it. The record is `DIR/slice.json`; it links back to the flat record
by hash. Exit codes are as for `tdmg flat`, with a missing or unverified slicer
counted as exit 2.

Setup is explicit and Windows x64 only: `uv run python scripts/setup_orcaslicer.py
--dest artifacts/tools/orcaslicer-2.5.0` downloads and hash-checks the pinned release
and flattens the A1 profiles, resolving each preset's `inherits` and `include` as
OrcaSlicer 2.5.0 does (`--verify-only DIR` rechecks an install; `--profiles-only DIR`
flattens the profiles again for a verified install). Then pass
`--slicer-dir DIR` or set `TDMG_ORCASLICER_DIR`. Every run re-hashes the whole app
folder unless `--skip-tree-check` is given, which is recorded. `--timeout-s` overrides
`slicer.orca.timeout_s`.

## Color plans (`tdmg colors`, 2026-11-11)

`tdmg colors SELECTION_DIR --width-mm W --out DIR` reads a verified `tdmg select` folder
and suggests a palette for a multicolor print (attribute page:
[C2 one body per filament](../print-types/attributes/color-multi.md)). Review its preview
before any geometry is built.

**What it does, in order:**
1. It extracts `extract` colors (default 6, `color.extract.default_count`) inside the
   mask, with k-means in CIELAB. The same input always gives the same palette.
2. It finds the cartoon outline color (`color.outline.thin_share`). By default
   (`outlines: drop`) the outline pixels go to the nearest other color; wide dark areas
   such as a pupil stay (`color.outline.keep_area_width_ratio`). With `outlines: keep`
   the lines are redrawn as one even band, `outline_width_mm` wide (default
   `color.outline.keep_width`, 0.5 mm), along the drawing's lines and the outer edge.
3. It applies the merges you chose (`merge`). It flags likely shade pairs
   (`color.shade.max_hue_diff_deg`, `color.shade.min_chroma`) but never merges them
   itself.
4. It removes regions too thin or too small to print, with R1's
   `flat.sliver.opening_width` and `flat.island.min_square_side`.
5. It smooths all region borders together (`edges`: `smooth`, the default, `furry` or
   `exact`).

**Settings:** command-line flags override a YAML file given with `--config`, and the file
overrides the rules and the printer profile. Unknown keys and values are refused. The
keys are `colors` (the most colors in the final palette; default 4, the AMS lite's
slots), `extract`, `edges`, `base` (`auto` is the largest color), `outlines`,
`outline_color` (`auto`, `none`, or a list of extraction indices such as `[3]`), `merge` (a list of
`[from, into]` extraction indices) and `outline_width_mm`. For example:

```yaml
colors: 4
outlines: keep
merge: [[4, 1]]   # fold extracted color 4 into color 1
```

**Outputs:** `labels.png` (the region map), `regions.png` (the preview) and the record
`colors.json`, whose `colors_id` hashes every input and setting. The preview shows the
image, the extracted colors with their indices and flags, and the final regions.

**Exit codes:** 0 means the plan is ready. 1 means the files are written but more colors
remain than `colors` allows; choose merges from the preview and run again. A plan that is
not ready cannot be built. 2 means an input, config or I/O error.

**Checking a plan:** `tdmg.colors_verify.verify_colors` reads a plan back with its
selection folder (about 1.4 s for the owner's Oddie on the PC). It checks the record's
own consistency, the printer's color cap and that the recorded rule values are today's.
Then it runs the plan again from the selection and the recorded settings. The labels must
come out the same, and so must every record field that can be rebuilt (floats to 1e-9,
everything else exactly). So hand edits to the labels or to those fields are refused,
even with the hashes updated. Not rebuilt: the preview image (only hashed), and these,
which are checked in form only: the software versions, where each setting came from, the
config file's hash, and which colors vanished in smoothing. A plan made on a machine whose
results differ is refused too; the owner-image results are measured on the Windows PC only.

**Not proven:** every color rule is an untested hypothesis set from two images, and
nothing has been printed from a color plan.

## Colored bodies (`tdmg flat --colors`, 2026-11-12)

`tdmg flat SELECTION_DIR --colors COLORS_DIR --thickness-mm T --out DIR` turns a ready
color plan into solid bodies (attribute page:
[C2 one body per filament](../print-types/attributes/color-multi.md)).

**What it reads and refuses:** the selection folder and a `tdmg colors` folder made from
it. It checks the plan with `verify_colors` first. It refuses, and writes nothing:
- a plan that `verify_colors` refuses: changed, inconsistent, not ready, made from another
  selection, or with rule values that differ from today's;
- a `--width-mm` or `--printer` other than the plan's (both default to the plan's,
  because the plan's cleanup used that width and that printer's nozzle);
- any `--smooth-px`: the preview you approved drew the outline with
  `flat.smooth.sigma_px`, so the model uses it too;
- a `--thickness-mm` that is not above `color.skin.depth_mm` (0.6 mm), so that there is
  base material under every inlay;
- an `--out` folder that is not new or empty.

**What it builds:**
- **AMS version:** a base body over the whole silhouette, and one inlay body per other
  color in the top 0.6 mm. The top is exactly the approved preview; nothing more is
  cleaned.
- **Glue version:** a base with 0.6 mm pockets, and per color the pieces, each 0.6 mm
  thick and `color.glue.clearance_mm` (0.2 mm) smaller than its pocket on every side,
  placed where it sits in the model. A region whose pieces would all be smaller than
  `color.glue.min_piece_side_mm` squared (4 mm²) is folded into a neighbour; smaller
  pieces in other regions are dropped, and the pocket area around them becomes base
  color.
- A plan made with `outlines: keep` and an outline color gets **no glue version**: a
  drawn outline is not realistic to glue on, and the plan does not record which pixels
  are the band. For a glue print, make the plan with `outlines: drop`.

**Outputs:** `ams-base.stl` and `ams-color-<i>-<rrggbb>.stl` (one per inlay color),
`model.3mf` (the same AMS bodies as one multicolor 3MF: one object with one closed shell
per color, each triangle colored; written from exactly the gated meshes), `palette.json`
(what each shell of `model.3mf` is: body, palette index, color, triangle range, area and
volume, and the 3MF's SHA-256), `glue-base.stl` and `glue-color-<i>-<rrggbb>.stl` (one per
color with pieces), `top.png`, `parts.png` and the record `colored.json`, with
`colorflat_id`. The names give the palette index and color, never AMS slots. Without a
glue version there are no `glue-*.stl` and no `parts.png`.

**Checks:** every body gets F1 and `F2.export_matches_geometry` on its written bytes. The
AMS bodies also get `F4.color_partition`, `F4.filaments`, `F2.fits_build_volume` and
`F5.triangles` (as one plate), and `F2.export_3mf_matches_bodies`. That check requires:
- the zip holds only the writer's three parts, and the content-types and relationships
  parts are the writer's bytes;
- the model part is exactly the bytes the writer makes for the gated bodies (since
  2026-11-13). lib3mf reads data it does not compare, such as slicer paint data, without
  a warning, and a slicer can act on it, so the bytes are compared too;
- lib3mf reads `model.3mf` back as one object in millimetres with no build transform,
  each shell exactly its body's gated mesh, closed and oriented, in its color.

The glue version gets `F4.glue_partition`,
`F4.glue_fit`, and `F2.fits_build_volume` and `F5.triangles` per plate. `F3.thin_regions`
is information only (UNKNOWN) and `F6.slicer` is UNKNOWN, so the verdict is always NOT
CERTIFIED.

**Exit codes:** as for `tdmg flat`, with `DIR/colored.json` for `DIR/flat.json`. 0 means
the files are written and no check FAILed; 1 means they are written and a check FAILed;
2 means an input or I/O error. An I/O failure while writing can leave a folder without
`colored.json`; do not use such a folder.

**What to open:** `top.png`, and compare it with the plan's `regions.png`: the colors
should match. Then open `model.3mf` in your slicer (Bambu Studio was checked) and give
each color a filament; `palette.json` lists which part is which color. The OrcaSlicer
CLI does not assign them from the file. For the glue version, open `parts.png`: each glue piece has a number, and
the legend lists the pieces per color, the folds and the leftovers. Check that the pieces
are a size you can handle.

**Slicing:** `tdmg slice DIR --out OUT` slices this folder (next section). Nothing has
been printed, and the three new rules are untested hypotheses. The runs on the owner's four plans are recorded
in `research/verification/2026-11-12-color-geometry/colored-runs.txt` (Windows PC only):
no check FAILed on any of them.

## Slicing a colored folder (`tdmg slice`, R2 step 4, 2026-11-13)

```
tdmg slice DIR --out OUT [--slicer-dir ...] [--prusaslicer-dir ...] [--face up|down|both]
```

`DIR` is a `tdmg flat --colors` folder (plan `docs/plans/2026-11-13-color-slicing.md`).
The command slices the AMS version with the pinned OrcaSlicer, each color on its own
filament, and checks the G-code against the gated bodies. It also slices each glue plate
as an R1 part. It prints nothing.

**Terms:**
- **Face up:** the model as built, with the colors in the top 0.6 mm. `model.3mf` is face
  up.
- **Face down:** the model turned 180° about the y axis, so the colors are in the first
  three layers, on the bed. It is a rotation, not a mirror: turned back over, the face
  reads the right way round.
- **Color change (tool change):** the printer unloads one filament and loads another
  during the print.
- **Flush:** plastic pushed out at a change to clear the old color from the nozzle.
- **Prime tower:** a small tower beside the model, printed at the changes, so that the new
  color flows evenly before it reaches the model.

**Refused, with nothing written:**
- no `colored.json`, another schema or algorithm, or an identity that does not match
  `colorflat_id`;
- any listed file (STL, `model.3mf`, `palette.json`, PNG) missing or changed since
  `tdmg flat --colors`;
- AMS STLs that, read back as the gate reads them, do not match `model.3mf`;
- `--face` on a single-color folder;
- everything R1 refuses (output folder, slicers, profiles, timeout).

The colored record's own checks are not a refusal: as with `DIR/flat.json`, they are
carried into each verdict, and a FAIL quarantines the G-code. As in R1, a file changed
together with its hash in `colored.json` is not detected; `colorslice_id` records the
lineage (the hash of `colored.json`).

**Faces:** face up by default (the owner's decision, plan Task 7: "Face up
(Recommended)"). `--face down` or `--face both` on request. Only the faces sliced are in
the record.

**Outputs, in `OUT`:**
- `face-up/` (and `face-down/` when sliced):
  - `orca-input.3mf`: the OrcaSlicer-only input. It holds the same gated meshes as
    `model.3mf`, one part per body, and a settings file that puts each part on its
    filament. The OrcaSlicer CLI prints `model.3mf` on one filament, so it needs this
    file. It is **not a deliverable**: print from `model.3mf`.
  - `plate_1.gcode` (or `plate_1.gcode.failed`) and `plate_1.statistics.json`.
- `filaments/filament-<n>.json`: the pinned filament profile with only `filament_colour`
  set to the color. OrcaSlicer computes the flush and the tool order from that color.
  These are not pinned profiles; their hashes are recorded.
- one folder per glue plate (`glue-base/`, `glue-color-<i>-<rrggbb>/`), with R1's files;
- `prusaslicer.portability-only.gcode.txt`, sliced from `model.3mf` (never print it);
- `slice.json`, schema `tdmg.colorslice/1`, with `colorslice_id`, written last.

**Filaments:** the base is always filament 1. The inlays follow by palette index
(filament 2, 3, …), whatever the base's palette index. `filament_map` in the record, and
the message, give the filament for each color.

**Checks per face.** Every expected value comes from the gated bodies, not from the
slicer's own report.
- **`F2.orca_input_matches_bodies`:** `model.3mf`'s check, adapted to parts. The zip
  parts, the model part and the settings file must be exactly the writer's bytes.
  lib3mf reads each part back: its vertices and triangles must be its body's exactly,
  closed and oriented, on its own filament.
- **`F6.color_changes`:**
  - each layer's set of tools in the G-code equals the set of bodies on that layer;
  - on each layer, each tool prints in one run;
  - the number of changes equals the sum over layers of (colors on the layer − 1), plus
    one for each layer whose first tool differs from the previous layer's last;
  - each change lies inside the A1's change code (`M620 S<n>A` … `M621 S<n>A`, in a
    `; CP TOOLCHANGE` block);
  - the start code loads exactly one filament, and it is the first tool on layer 1.

  The true minimum number of changes is recorded as information. OrcaSlicer orders each
  layer without looking ahead, so face down it can use one change more than the minimum
  (Roadie drop: 10 against 9).
- **`F6.tool_placement`:** each tool prints only on its body's layers and inside its
  body's outline, within the F3 allowance (0.2 mm; 0.275 mm on layer 1). Every body is
  printed by its own tool. The prime tower does not reach into the model. The model is
  judged where OrcaSlicer places it (centred, not turned), so a print with two colors
  swapped, or turned by 90°, 180° or 270°, FAILs. (R1 still accepts any quarter turn.)
- **`F6.filaments_used`:** exactly the plan's filaments are loaded and used, one per
  body, in the plan's colors.
- **R1's slicer checks:** `F6.slicer_exit`, `F6.gcode_present`, `F6.layer_count` and
  `F6.single_object`.
- **F3, gated "outer edge only"** (the owner's decision, plan Task 7). The F3 checks run on
  the whole model (all tools together) and on each tool against its own body.
  - **Required:** the whole model's `F3.edge_coverage` and `F3.edge_overprint`, and each
    tool's `F3.edge_overprint`.
  - **Warnings** (recorded in the face's `warnings`, never blocking): each tool's
    `F3.edge_coverage`, and every `F3.printed_connectivity`. Each warning keeps its
    status (FAIL or UNKNOWN). On the owner's plans, connectivity FAILs where two colors'
    lines meet edge to edge: in the bead model their beads leave a hairline gap (up to
    about 0.03 mm). It also FAILs when a color is left mostly unprinted, so the warning
    states the measured mismatch, not a cause. A thin line the slicer skips, such as a
    kept outline line, shows as a coverage warning.
  - **The trade-off:** a color left partly unprinted inside the model (half an inlay)
    only warns. Half of the base's first layer is still caught. The owner accepted this.
- **`F6.portability`:** PrusaSlicer reads and slices `model.3mf`. Its volume is recorded
  but is not a condition: no derivation of PrusaSlicer's 3MF volume exists.
- **Information only (UNKNOWN):** `F6.color_waste` (flush and prime tower, in mm³),
  `F6.color_time` (the slicer's time estimate) and `F6.color_filament` (the filament
  per tool, read from the G-code). The statistics' values are recorded beside them.

**The G-code reader:** the multicolor G-code is read by R1's strict reader, with three
additions for the prime tower: its extrusion is kept apart from the model; the
`; CP TOOLCHANGE` blocks must pair, and inside them the firmware G-commands are read as
in Custom; and the dwell `G4` is accepted in the prime tower. A second pass reads the
change structure: the `T<n>` commands, the `M620`/`M621` pairs and the flush blocks.
G-code that either pass cannot read gives UNKNOWN, never PASS.

**Glue plates:** each `glue-*.stl` is sliced as an R1 part into its own folder, with R1's
checks and required set, except `F2.target_width`, which does not apply to a plate of
pieces. `F4.body_count` requires the plate's bodies to be its pieces in the glue report
(1 for the base), and the glue assembly's `F4.glue_fit` and `F4.glue_partition` are
required too. A glue print needs every plate, so the glue route is printable only when
every glue plate is PRINTABLE; the message names the plates that block it.

**Verdicts:** one per face and one per glue plate. A face is PRINTABLE only if every
required check passes: the colored record's AMS checks, the checks above and
`F6.portability`. A required check that FAILs quarantines that G-code
(`plate_1.gcode.failed`). An UNKNOWN does not quarantine it, but the verdict is NOT
CERTIFIED.

**Message:** per face, the verdict, the changes, flush, prime tower and time, and each
warning that does not pass. For example: "warning: color 1 #451812 (filament 2): edge
coverage FAIL, edges up to 4.99 mm from its printed lines (for example thin areas the
slicer skips, or a part left unprinted)", and one connectivity line per face: "warning:
connectivity check FAIL for the whole model, … (the printed lines split into more parts
than the model; …)", or "connectivity check UNKNOWN for …: <the check's reason>". Then the
filament for each color, and what to print:
- face up PRINTABLE: "to print face up: open model.3mf in Bambu Studio (it is face up)
  and give each color the filament listed; …";
- only face down PRINTABLE: the message says to turn `model.3mf` over;
- both PRINTABLE: it says that the owner's default is face up.

`tdmg`'s G-code is for checking only: it is not yet printed or compared with Bambu
Studio's own slice.

**Exit codes:** 0 means the files are written and no required check FAILed (UNKNOWN
checks and warnings are allowed). 1 means a required check FAILed (files written). 2
means an input or setup error, with nothing written. A warning never sets exit code 1.

**The owner's four plans** (60 × 3 mm, 4 colors each, face up, 2026-11-13, Windows PC):
all four are **PRINTABLE**, with warnings. The numbers are the slicer's.

| Plan | Changes | Flush mm³ | Prime tower mm³ | Time s | Coverage warnings (largest gap) |
|---|---|---|---|---|---|
| Roadie drop | 9 | 951.3 | 1054.7 | 1873 | base 0.28 mm |
| Roadie keep | 9 | 951.3 | 1054.7 | 2002 | base 1.59 mm; color 1 (the outline color) 4.99 mm; color 2 0.23 mm |
| Oddie merge blues | 9 | 900.0 | 1054.7 | 1910 | base 0.20 mm |
| Oddie keep | 9 | 600.0 | 1054.7 | 2124 | base 0.23 mm; color 2 (the outline color) 4.72 mm |

- **Connectivity:** every plan also has the connectivity warning.
- **The keep plans:** the thin outline lines inside the picture are not printed. The
  outer outline band is.
- **Face down** (measured in Tasks 2 and 6): the prime tower is about half (548–592 mm³),
  because it stops after the last change. The time is within 2 minutes of face up.
  Roadie drop face down is NOT CERTIFIED (the whole model's edge coverage is UNKNOWN:
  0.251 mm against 0.275 mm). On the keep plans, face down layer 1 skips most of the
  outline color, and the whole model's edge coverage FAILs (1.179 and 0.637 mm).
- **The glue route** on the two drop plans is not printable: `glue-base` FAILs
  `F3.edge_coverage`, and one or two small color plates FAIL F3.

Records: `research/verification/2026-11-13-color-slicing/` (`README.md`,
`owner-slices-task7.txt`, `owner-review.txt`).

**Not proven:** nothing multicolor has been printed. `tdmg`'s G-code has not been
compared with Bambu Studio's slice. The flush amounts are OrcaSlicer's, measured and not
tuned.

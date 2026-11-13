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
  replaces the placeholder F6 check with measured ones.
- **`tdmg colors`** is the first half of S6 for flat multicolor (R2; see below). It
  writes a color plan for review.
- **`tdmg flat --colors`** builds the plan's colored bodies as STL files, for an AMS
  print and for a glued print (see below). `tdmg slice` cannot slice them yet.

There are no loops, bases or 3MF output yet.

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

### What PRINTABLE means for you

PRINTABLE means: every check this project requires passed, for this exact file, with
these exact slicer versions and the A1 profile. Print `plate_1.gcode` on the A1, or open
`model.stl` in Bambu Studio and slice it there. It is a strong "nothing we know how to
measure is wrong", not a promise:

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
and flattens the A1 profiles (`--verify-only DIR` rechecks an install). Then pass
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
`F5.triangles` (as one plate), and `F2.export_3mf_matches_bodies` (lib3mf reads
`model.3mf` back: only the writer's three zip parts, one object in millimetres with no
build transform, each shell exactly its body's gated mesh, closed and oriented, in its
color); the glue version gets `F4.glue_partition`,
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

**Not yet:** the folder has no `DIR/flat.json`, so `tdmg slice` refuses it until step 4
of the color design. Nothing has been printed, and the
three new rules are untested hypotheses. The runs on the owner's four plans are recorded
in `research/verification/2026-11-12-color-geometry/colored-runs.txt` (Windows PC only):
no check FAILed on any of them.

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
  writes a color plan for review. It builds no geometry yet.

There are no loops, bases, colored geometry or 3MF output yet.

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
Roadie and Oddie (60 × 3 mm, smoothed) are **PRINTABLE** (2026-11-11,
`research/verification/2026-11-11-prusaslicer-windows/`).

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
selection folder. It checks the record's own consistency and the printer's color cap, then
runs the plan again from the selection and the recorded settings and rules. The labels and
the record must come out the same (floats to the last digits), so a plan edited by hand is
refused. A plan made on a machine whose results differ is refused too; the owner-image
results are measured on the Windows PC only.

**Not proven:** every color rule is an untested hypothesis set from two images, and
nothing has been printed from a color plan.

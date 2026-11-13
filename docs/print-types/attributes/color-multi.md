# C2 One body per filament

## What it is

The print uses several filaments. Each color is a separate body, and the slicer gives
each body its own filament. On a flat print (G1) the plan is:
- a base of one color at full thickness;
- one thin inlay body per other color in the top skin (the design is in
  [the R2 color design](../../plans/2026-11-11-color-design.md)).

The same color plan serves two routes:
- **AMS:** one print. The A1 changes filament where the colors meet.
- **Glue:** the base has shallow pockets. Each color is printed separately and glued
  into its pocket.

**Status (2026-11-13):** steps 1 to 3 exist, and step 4 is under way.
`tdmg colors` turns a selection into a reviewed color plan (step 1). `tdmg flat --colors` turns a ready plan into gated STL
bodies for both routes (step 2), and writes the AMS bodies as one multicolor
`model.3mf` (step 3). `tdmg slice` slices the AMS version face up and face down, each
color on its own filament, and each glue plate (step 4, Task 6; see
`docs/guide/pipeline-and-gate.md`). Nothing in this page is printed.

## When to use / when not to

- **Use** for images with a few flat colors, such as cartoons, logos and badges.
- **Use with care** for images with shading or gradients. Shades of one color become
  separate colors, and the owner must choose which to merge. The preview shows the
  likely pairs.
- **Do not use** for photos. Color reduction to 4 colors does not keep a photo's look.
- **Do not use** when the shape matters more than color. Use C1.

## Pipeline specifics

S6 (color) is done by `tdmg colors SELECTION_DIR --width-mm W --out DIR`, before any
geometry. The steps, all deterministic:

1. **Extract** `extract` colors (default 6) inside the mask, with k-means in CIELAB.
2. **Outlines:** a color made mostly of thin lines is the outline family.
   - `outlines: drop` (default) gives its pixels to the nearest other color. Wide dark
     areas, such as a pupil, stay.
   - `outlines: keep` redraws the drawing's own lines as one even band of
     `outline_width_mm`, plus a band along the outer edge.
3. **Merges:** the owner's `merge: [[from, into], ...]`, by the extraction index shown
   in the preview. Likely shade pairs are flagged, never merged automatically.
4. **Cleanup:** regions too thin or too small to print go to a neighbour color, as R1
   does for the outline.
5. **Smoothing:** all region borders are smoothed together, so neighbours cannot gap or
   overlap (`edges: smooth | furry | exact`).

Outputs: `labels.png` (the region map), `regions.png` (the preview) and `colors.json`
(the record, with `colors_id`). When more colors remain than `colors` (default 4, the
AMS lite's slots), the plan is written as not ready, and the command exits 1. A plan that
is not ready cannot be built. The settings come from flags, then a YAML config file, then
the rules; see the [pipeline guide](../../guide/pipeline-and-gate.md).

**Step 2, the bodies:** `tdmg flat SELECTION_DIR --colors COLORS_DIR --thickness-mm T
--out DIR` (design: [the step 2 plan](../../plans/2026-11-12-color-geometry.md)). It first
checks the plan with `tdmg.colors_verify.verify_colors` against the same selection folder.
The silhouette is R1's, made by the same code and clipped to the image box.

- **AMS:** a base body of the base color over the whole silhouette, and one inlay body
  per other color in the top `color.skin.depth_mm` (0.6 mm). The inlays are exactly the
  approved preview: the plan's smoothed regions inside the smoothed silhouette, with no
  further cleaning (owner decision "Match preview", 2026-11-12). Thin parts are reported,
  not removed.
- **Glue:** a base with a pocket `color.skin.depth_mm` deep for each glue region, and per
  color the pieces: each is its pocket shrunk by `color.glue.clearance_mm` on every side,
  as thick as the pocket, and placed where it sits in the model.
  - A region with no shrunk piece of at least `color.glue.min_piece_side_mm` squared
    (4 mm²) is folded into the neighbour with the longest shared boundary. Folding
    repeats until nothing changes. A region folded into the base has no pocket.
  - In the regions that stay, smaller pieces are dropped too, and the pocket area that no
    kept piece needs becomes base color, so no pocket is empty (owner decision "Fold small
    pieces too", 2026-11-12). This leftover area is reported per color.
- **No glue version for a drawn outline:** a plan made with `outlines: keep` and an
  outline color draws an outline band, and the plan does not record which outline-color
  pixels are the band. Such a plan gets the AMS version only. For a glue print, make the
  plan with `outlines: drop` (owner decision, 2026-11-12: a kept outline "would be
  unrealistic to glue on").

All 2-D geometry is snapped to a storage grid, a power of two in mm chosen so that every
grid point is a float32 number; writing the STL therefore moves no x or y coordinate. Each
body is meshed directly from the shared grid cells, without 3-D booleans: a manifold3d
union first tried here failed F1 after STL storage on 3 of the 4 owner plans.

Outputs: `ams-base.stl` and `ams-color-<i>-<rrggbb>.stl` (one per inlay color);
`model.3mf` (the AMS bodies as one 3MF object with one closed shell per color, colored per
triangle with the 3MF Materials extension) and `palette.json` (what each shell is);
`glue-base.stl` and `glue-color-<i>-<rrggbb>.stl` (all pieces of one color, one plate);
`top.png` (the AMS top skin, to compare with the plan's `regions.png`); `parts.png` (the
glue layout with each piece numbered, the folds and the leftovers); and the record
`colored.json`, with `colorflat_id`. A plan with a drawn outline gets no `glue-*.stl` and
no `parts.png`. The file names give the palette index and color, never AMS slots. There is
no `DIR/flat.json`; `tdmg slice` reads `colored.json` instead (step 4).

**On the owner's four approved plans** (Roadie and Oddie at 60 × 3 mm, Windows PC,
`research/verification/2026-11-12-color-geometry/colored-runs.txt`), no check FAILed, so
the command exits 0; the only checks that did not pass are the UNKNOWN `F3.thin_regions`
and `F6.slicer`, so the verdict is NOT CERTIFIED. The two `outlines: drop` plans got a
glue version, with 7 and 5 pieces (smallest 6.12 and 23.98 mm²). On Roadie's, color 3
(4.18 mm²) has no glue piece: it was folded, and the record warns about it. The two
`outlines: keep` plans got the AMS version only. The owner reviewed `top.png` and
`parts.png`: "teh colors match"; the folds and piece sizes were accepted.

**The 3MF (step 3):** the encoding was chosen by real imports, not by reading slicer
source. Separate objects per color were dropped to the bed by the OrcaSlicer and
PrusaSlicer CLIs, and PrusaSlicer crashed on them. One object with one shell per color
stays in place in both, and the owner's Bambu Studio shows its colors. The owner opened
the Roadie drop plan's `model.3mf` in Bambu Studio: the parts were in place, each color
could be given a filament, and it sliced ("1) yes. 2) yes. 3) yes"). The pinned
OrcaSlicer and PrusaSlicer CLIs slice all four plans' `model.3mf` in place (exit 0), but
OrcaSlicer prints everything with one filament: the CLI does not assign filaments from
the file's colors. Assign the filaments in the slicer, using `palette.json`.

## Parameters

- `color.extract.default_count`: how many colors to extract before merges.
- `color.edges.furry_sigma_px`: the blur of the `furry` edge preset. `smooth` uses
  `flat.smooth.sigma_px`.
- `color.outline.thin_share`: when a color counts as outline.
- `color.outline.keep_area_width_ratio`: which wide areas of the outline color stay
  under `drop`.
- `color.outline.keep_width`: the default width of the kept outline.
- `color.shade.max_hue_diff_deg` and `color.shade.min_chroma`: when two colors are
  flagged as a shade pair.
- `flat.sliver.opening_width` and `flat.island.min_square_side`: the cleanup limits,
  shared with R1. In step 2 they also clean the glue pieces and leftovers, and the
  opening width sets which parts are reported as thin.
- `color.skin.depth_mm` (0.6 mm): the top skin of the AMS inlays; for glue, the pocket
  depth and the piece thickness.
- `color.glue.clearance_mm` (0.2 mm): the gap per side between a glue piece and its
  pocket.
- `color.glue.min_piece_side_mm` (2 mm): the smallest glue piece, as the side of a
  square.

All of these are untested hypotheses. The color rules rest on two images. The three
step 2 rules are starting values the owner approved; the minimum piece side has no
source.

## Failure modes

| Symptom | Cause | Check | Mitigation |
|---|---|---|---|
| Too many colors for the AMS | Shading or outlines give extra colors | The record's `ready` flag; exit 1 | Merge flagged shade pairs, or raise `colors` if the setup has more slots |
| Outline left on some edges only | Cleanup removes only the thinnest parts of a line | The owner's preview review | `outlines` is an explicit choice: drop removes it everywhere; keep redraws it as one even band along every line, with small breaks where lines meet (cleanup removed 1.7% of Roadie's band and 0.3% of Oddie's at 0.5 mm) |
| A wanted dark area disappears | `drop` treats it as outline | The preview; the record lists the kept areas | `outlines: keep`, or report the image so the rule can be checked |
| A small colored detail is lost | It is below the printable size, or a wide kept outline covers it | The record's cleanup counts; the fate `band` in the extraction list | Print larger (a larger `--width-mm`), or a narrower `outline_width_mm` |
| Gaps or overlaps between colors | Each color smoothed on its own | One shared smoothing of all borders (by construction) | None needed |
| The wrong filament in a slot | The file names colors, not slots | The palette in the preview and record; the file names and `top.png`'s legend | Assign spools in the slicer from the palette |
| A color is missing from the glue version | All its regions are too small for a piece, so they were folded | A warning in the record and the command's output; `parts.png` lists the color as "no pieces (all folded)" | Print larger, or use the AMS version |
| No glue version at all | The plan keeps a drawn outline | The command prints "glue: not built" with the reason | Make the plan with `outlines: drop` |
| A glue piece does not drop in, or sits loose | The printer's error differs from `color.glue.clearance_mm` | `F4.glue_fit` checks the model only, not the print | The clearance test strip (step 5) |

## Required checks

- **Step 1 (exists):** `verify_colors` re-reads the plan with its selection folder. It
  checks the record's consistency, the printer's color cap, the method versions and that
  the rule values are today's. Then it runs the plan again from the selection and the
  recorded settings: the labels and every record field that can be rebuilt must come out
  the same. So hand edits to them are refused, even with the hashes updated. The plan must
  be ready. Not rebuilt: the preview (`regions.png`, only hashed), and these, which are
  checked in form only: the software versions, the settings' sources and config hash, and
  the colors that vanished in smoothing.
- **Step 2 (exists):** every body is read back from its STL bytes and gets the F1
  topology checks and its own `F2.export_matches_geometry`.
  - **AMS:** `F4.color_partition` (the inlays and the base top do not overlap, their
    union equals the silhouette, and the volumes sum to its area × T, all within derived
    rounding bounds); `F4.filaments` (the non-empty bodies are at most `colors` and the
    printer's slots); `F2.fits_build_volume` on all bodies together and `F5.triangles` on
    their sum, as one plate; `F2.export_3mf_matches_bodies` (lib3mf reads `model.3mf`
    back, and each shell must be its body's gated mesh exactly, in its color; the zip
    holds only the writer's three parts, and the build item has no transform).
  - **Glue:** `F4.glue_partition` (the base's cells cover the silhouette, the pockets do
    not overlap and lie inside it, and the base's volume is right); `F4.glue_fit` (each
    piece, grown by the clearance less a derived rounding margin, lies inside its pocket;
    it reports the smallest gap); `F2.fits_build_volume` and `F5.triangles` per plate (the
    base, and each color).
  - `F3.thin_regions` per body is information only (UNKNOWN), and `F6.slicer` is UNKNOWN
    until step 4. So the verdict is always NOT CERTIFIED.
- **Step 4 (Task 6 done; Tasks 7 and 8 open):** `tdmg slice` slices both faces and the
  glue plates. Per face, `F6.color_changes`, `F6.tool_placement` and `F6.filaments_used`
  read the G-code against the bodies, and every F3 result is required until the owner's
  Task 7 review; so no face is PRINTABLE yet. `F6.portability` on `model.3mf` records the
  volume as information. Owner plans:
  `research/verification/2026-11-13-color-slicing/owner-slices-task6.txt`.

## Calibration needed

- The skin depth (`color.skin.depth_mm`, 0.6 mm to start): does it hide a dark base, and
  do 0.6 mm glue pieces survive handling?
- The pocket clearance for the glue route (`color.glue.clearance_mm`).
- The smallest piece a person can glue (`color.glue.min_piece_side_mm`).
- Whether a 0.5 mm kept outline prints cleanly.

Each needs a test print. None is done.

## Evidence

- The palette method, the outline and shade measures, and the owner's reviews:
  [the color palette record](../../../research/verification/2026-11-11-color-palette/README.md).
- The design and the owner's decisions:
  [R2 color design](../../plans/2026-11-11-color-design.md),
  [the step 1 plan](../../plans/2026-11-11-color-palette.md),
  [the step 2 plan](../../plans/2026-11-12-color-geometry.md) and
  [the step 3 plan](../../plans/2026-11-12-color-3mf.md).
- The step 2 measurements, the owner-plan runs and the owner's review:
  [the color geometry record](../../../research/verification/2026-11-12-color-geometry/README.md)
  (`colored-runs.txt`, `bodies.txt`, `glue.txt`).
- The 3MF encoding tests, the re-import of the four plans and the owner's Bambu Studio
  checks: [the color 3MF record](../../../research/verification/2026-11-12-color-3mf/README.md).
- The AMS lite's 4 slots: `profiles/printers/bambu-a1.yaml`.

## Open gaps

- Nothing is printed. `tdmg slice` measures the color changes, the waste and the time
  face up and face down, but the default face and whether a per-color F3 FAIL blocks
  PRINTABLE are the owner's Task 7 decisions.
- The OrcaSlicer CLI slices `model.3mf` on one filament, so `tdmg slice` gives OrcaSlicer
  its own input, `orca-input.3mf`; per-color filaments for printing are assigned in the
  slicer GUI (Bambu Studio was checked by the owner).
- In `model.3mf` the shells touch along their shared walls. Each shell is closed on its
  own; the 3MF core spec treats touching shells only as a self-intersection warning
  (`format.3mf.self_intersection_is_warning`).
- The three step 2 rules are untested hypotheses.
- In the glue version, pocket strips that no piece covers beyond the clearance are left
  for the glue to fill: 1.59 and 2.12 mm² on the two owner plans built with glue
  (`glue.txt`).
- The rules rest on two images, and the wide-area rule on one example.
- The owner-image tests and runs (steps 1 and 2) ran on the Windows PC only, not on the
  Mac. A plan made on one machine and checked on another is refused if their results
  differ.
- The smoothed region borders (the fine map) and R1's outline are now blurred in
  float64. With float32, their last bits depended on which internal code path OpenCV
  used. In float64 they are the same either way on the PC; this is not shown on the Mac.
- Empty spots between parts of the subject are not filled. No evidence shows a need yet.
- The color changes and the purge waste per change are not measured.

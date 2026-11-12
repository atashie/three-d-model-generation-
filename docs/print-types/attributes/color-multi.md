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

**Status (2026-11-11):** only step 1 exists. `tdmg colors` turns a selection into a
reviewed color plan. It builds no geometry, so nothing in this page is printed yet.

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

Step 2 (planned) builds the base and the inlays from the plan. It must first check the
plan with `tdmg.colors_verify.verify_colors` against the same selection folder.

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
  shared with R1.

All of these are untested hypotheses. The color rules rest on two images.

## Failure modes

| Symptom | Cause | Check | Mitigation |
|---|---|---|---|
| Too many colors for the AMS | Shading or outlines give extra colors | The record's `ready` flag; exit 1 | Merge flagged shade pairs, or raise `colors` if the setup has more slots |
| Outline left on some edges only | Cleanup removes only the thinnest parts of a line | The owner's preview review | `outlines` is an explicit choice: drop removes it everywhere; keep redraws it as one even band along every line, with small breaks where lines meet (cleanup removed 1.7% of Roadie's band and 0.3% of Oddie's at 0.5 mm) |
| A wanted dark area disappears | `drop` treats it as outline | The preview; the record lists the kept areas | `outlines: keep`, or report the image so the rule can be checked |
| A small colored detail is lost | It is below the printable size, or a wide kept outline covers it | The record's cleanup counts; the fate `band` in the extraction list | Print larger (a larger `--width-mm`), or a narrower `outline_width_mm` |
| Gaps or overlaps between colors | Each color smoothed on its own | One shared smoothing of all borders (by construction) | None needed |
| The wrong filament in a slot | The file names colors, not slots | The palette in the preview and record | Assign spools in the slicer from the palette |

## Required checks

- **Step 1 (exists):** `verify_colors` re-reads the plan with its selection folder. It
  checks the record's consistency, the printer's color cap, the method versions and that
  the rule values are today's. Then it runs the plan again from the selection and the
  recorded settings: the labels and every record field that can be rebuilt must come out
  the same. So hand edits to them are refused, even with the hashes updated. The plan must
  be ready. Not rebuilt: the preview (`regions.png`, only hashed), the software versions
  and the settings' sources.
- **Step 2 (planned):** each color body is closed; the bodies do not overlap; together
  they equal the R1 shape; the filament count is at most `colors`; the color changes
  read from the G-code match the plan.

## Calibration needed

- The skin depth (0.6 mm is a starting value): does it hide a dark base?
- The pocket clearance for the glue route.
- The smallest piece a person can glue.
- Whether a 0.5 mm kept outline prints cleanly.

Each needs a test print. None is done.

## Evidence

- The palette method, the outline and shade measures, and the owner's reviews:
  [the color palette record](../../../research/verification/2026-11-11-color-palette/README.md).
- The design and the owner's decisions:
  [R2 color design](../../plans/2026-11-11-color-design.md) and
  [the step 1 plan](../../plans/2026-11-11-color-palette.md).
- The AMS lite's 4 slots: `profiles/printers/bambu-a1.yaml`.

## Open gaps

- Nothing is printed. No geometry is built from a color plan yet.
- The rules rest on two images, and the wide-area rule on one example.
- The owner-image tests ran on the Windows PC only, not on the Mac. A plan made on one
  machine and checked on another is refused if their results differ.
- The smoothed region borders (the fine map) depend in their last float bits on which
  internal code path OpenCV uses (measured on the PC: switching OpenCV's optimisations
  changed 3 fine pixels in a small test). `labels.png` and `colors_id` do not depend on
  it. R1's outline smoothing has the same property.
- Empty spots between parts of the subject are not filled. No evidence shows a need yet.
- The color changes and the purge waste per change are not measured.

# Color for flat prints (R2): design

**Status:** design agreed with the owner on 2026-11-11, section by section, in chat. No
code yet. The implementation plan for step 1 comes next.

**Why:** the owner asked for color options in the image-to-print workflow, in two forms:
- one multicolor print on a 4-slot AMS, with as few color changes as possible;
- separately printed colored pieces glued together, where the user does not rebuild the
  model from small scraps.

This is R2, flat multicolor (docs/PLAN.md section 3; roadmap step 3 in section 11).

## Owner decisions (2026-11-11)

1. **Color depth: top skin only.** The colors sit only in the top layers (0.6 mm, three
   0.2 mm layers to start) on a full-thickness base of one color. For 4 colors that is
   at most 3 × (4 − 1) = 9 color changes, against 45 for colors through the full 3 mm.
   The owner set aside two alternatives: full thickness, and stepped heights (the R3
   style).
2. **Palette: suggested from the image.** The tool picks N representative colors from
   the image and writes their hex codes. The user assigns spools in the slicer. This
   replaces, for now, PLAN section 11's "palette snapped to the job's filament colors";
   snapping can be added later as an option.
3. **Glue route: inlays in pockets.** The base carries the whole silhouette with shallow
   pockets. Each colored piece drops into its own pocket and sits flush. The pockets
   locate the pieces and hold them while the glue sets.
4. **Tiny regions: merged for glue only.** The AMS output keeps every region the slicer
   can print. The glue output folds regions too small to handle into the surrounding
   color, and the preview and report list them.
5. **Face up or face down: measure both, then decide.** Face down puts the color changes
   in the first layers, so the prime tower stops at 0.6 mm (Bambu's wiki reports about
   40% less tower material in its example for this). Face up gives the face a normal
   top-surface finish. Both are sliced with OrcaSlicer and compared before a default is
   set.
6. **Review before geometry.** The color step (`tdmg colors`) writes a preview that the
   owner reviews before any geometry is built.
7. **A reusable module, steered by a config file.**
   - The color module serves this workflow (image → flat shape → colored flat shape) and
     must be adaptable to later ones.
   - User guidance such as "smooth" or "furry" edges and the number of colors (an
     integer, default 4) comes from a config file. New options found in chat are added
     to it as named keys.

## Design

### Commands and outputs

1. **`tdmg colors SELECTION_DIR [--config FILE] [--colors N] --out DIR`** works on the
   selected image and mask, and writes:
   - `palette.json`: the hex codes, each color's share of the area, and the base color
     (the largest by default; `base` in the config changes it);
   - `regions.png`: the image painted in the palette, for review;
   - the region map and `colors.json`, the record with its id.
2. **`tdmg flat SELECTION_DIR --colors COLORS_DIR ...`** builds the R1 silhouette, then
   splits the top skin into color bodies. It writes:
   - **AMS:** `model.3mf`, one named body per color (the base and each color's inlay),
     with a palette manifest. The file names colors, never AMS slots (PLAN section 2).
   - **Glue:** `glue/base.stl` (the silhouette with pockets) and `glue/<color>.stl` (that
     color's pieces, laid flat), with a parts sheet. The sheet lists the pieces per color
     and has a numbered diagram of where each piece goes.
3. **`tdmg slice`** handles the 3MF with AMS settings in the pinned OrcaSlicer. It reports
   the color changes, the flush and prime-tower waste and the time from the G-code and
   the statistics. The glue STLs are each gated as R1 parts.

### The color module (`tdmg.color`)

- **Input:** an image and a mask. **Output:** a color plan (the palette, a region map and
  the region outlines in pixel space) plus a record of every step. It knows nothing about
  extrusion or thickness, so later workflows can use the same plan:
  - reliefs and lithophanes (R3), with colors as height bands;
  - figurines (R7), with colors projected onto a surface;
  - assembled parts (R5), with one color per part.
- **Steps, all deterministic:**
  1. **Quantize:** reduce the colors inside the mask to N, with a fixed-seed method in a
     perceptual color space (CIELAB). The method is chosen and measured in step 1 of the
     build.
  2. **Clean up:** anti-aliased boundary pixels become speckle. Regions below the
     printable minimum, about one bead width, are merged into the neighbour they share
     the longest edge with (the R1 sliver and island rules).
  3. **Smooth:** each region boundary is smoothed with one shared boundary per pair of
     regions, so neighbours cannot gap or overlap. Smoothing each color on its own would
     leave slivers.
- **Shared smoothing:** R1's outline smoothing and the region smoothing become one module.

### Geometry (the flat-print adapter)

- **Base:** the silhouette at full thickness, minus the top skin wherever an inlay sits.
- **One body per color:** that color's regions, the skin depth thick. They fill the
  cut-outs exactly in the AMS output, and are shrunk by the pocket clearance in the glue
  output.
- **The base color** shows wherever there is no inlay.

### Keeping color changes low

1. **Colors only in the top skin.** Changes are at most (skin layers) × (N − 1).
2. **Fewer colors per layer.** A color whose regions are all tiny is merged, and the
   report says so.
3. **Face up or down,** measured (decision 5).
4. **Not done:** reordering colors within a layer. The slicer already prints the last
   color of a layer first on the next, and flush amounts are its job; they are measured,
   not modelled.

### The config file

```yaml
colors: 4            # N, an integer 2–4; default 4 (the AMS lite's slot count)
edges: smooth        # smooth | furry | exact
base: auto           # auto (largest area) or a color index from the preview
min_glue_piece: auto # the rule's default
face: auto           # auto | up | down
```

- **Precedence:** command-line flags override the file, and the file overrides the rule
  defaults. The settings used are written into the record and enter its id.
- **Strict:** unknown keys or values are refused, never guessed.
- **No language at runtime:** words like `furry` are named presets. Each maps to fixed
  settings documented in `rules/` with evidence. Requests found in chat become new named
  keys. The tool reads only the keys (CLAUDE.md rule 1).
- **The `furry` limit:** jagged detail survives only down to about one bead width
  (0.42 mm). Finer points merge or vanish in the slicer, and F3.edge_coverage flags them.
  So `furry` means less smoothing and sharp corners kept, not hair-fine strands.

### New rules (each starts as a hypothesis with evidence)

- **The skin depth:** 0.6 mm. It is to be checked on the test strip: does 0.6 mm of a
  light color hide a dark base?
- **The pocket clearance:** set from the test strip.
- **The smallest glue piece.**
- **The color-count cap:** 4, the AMS lite's slots (PLAN Q1).
- **The `edges` presets.**

### Gate additions

- Each color body is closed, the bodies do not overlap, and together they equal the R1
  shape within the export tolerance.
- The number of filaments is at most N.
- The color changes read from the G-code equal the sum over layers of (colors on the
  layer − 1).
- Each glue piece and the base pass the R1 checks, and each piece fits its pocket with
  the stated clearance.

### Requirements step 2 inherits from step 1 (added 2026-11-11, Task 6 review)

- **Verify the plan:** read it with `tdmg.colors_verify.verify_colors`, always with the selection
  folder, so that `labels.png` is tied to the mask being extruded.
- **Compare the plan with this run:** the printer and nozzle in the plan's identity must
  equal the profile in use. Its rule values must equal the current registry; a mismatch
  is refused, or accepted only on purpose and recorded.
- **Width:** compare the requested `width_mm`, not the scale (`tdmg colors` uses the
  exact mask width; `tdmg flat`'s smoothed outline differs by 0.4–0.6%).
- **Palette trust:** the palette hex codes go into the 3MF. `verify_colors` checks them
  only for internal consistency, because they are results outside the identity.
- **Clipping:** the fine region map is clipped to the R1 outline intersected with the
  image box (the outline can overshoot the image by up to about 2e-6 px).
- **The fine map is not byte-stable across OpenCV code paths** (added 2026-11-11, Task 8
  review). Both `smooth_labels` and R1's `smooth_outline` blur in float32, and the last
  bits depend on OpenCV's code path: switching `cv2.setUseOptimized` changed 3 fine
  pixels in a 17 × 17 test and the outline coordinates of all five owner selections. In
  float64 the blur was bitwise the same both ways on every case tried. So step 2 must
  gate its geometry by its own checks, not by reproducing the fine map's bytes. Moving
  both to float64 is open: it changes R1's outputs, so the owner decides.

## Testing

- **Synthetic images with known answers:**
  - flat-colored shapes with exact regions;
  - the same with anti-aliased edges;
  - speckle;
  - 5 colors squeezed to 4.

  The tests assert the palette, the merges and byte-identical repeat runs.
- **Partition checks** on the geometry, as above.
- **Config:** refusals, precedence, and the record and its id.
- **Real slicer:** the change count, and the waste face up against face down.

## Build order

1. `tdmg.color` and `tdmg colors`: palette, cleanup, presets, config and preview. The
   owner reviews the Roadie and Oddie previews.
2. The colored flat geometry, the glue pieces and parts sheet, and the per-body checks.
3. 3MF output: a deterministic writer. The choice between separate objects and one
   assembly is made by import tests in OrcaSlicer and PrusaSlicer (PLAN section 11,
   step 3), and the owner confirms the result in Bambu Studio.
4. Multicolor slicing: AMS settings, the change count, and the face-up or face-down
   measurement.
5. Prints: a test strip (pocket clearances, and the skin over a dark base), then the
   first AMS print and the first glue print.

## Reservations stated to the owner

- **Image complexity:** color reduction is the hard part. Flat cartoon colors reduce
  well; shading and gradients give speckle that must be merged, so the preview review
  matters.
- **Waste per change:** it is unknown for this setup until it is measured with the
  slicer.
- **Glue fit:** it needs one calibration print.
- **Size:** this is several steps of work, like R1.

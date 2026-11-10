# G1 Flat / 2.5D extrusion

## What it is

A shape made by tracing an outline from an image and extruding it straight up: keychains, signs, badges, coasters, cookie cutters. Every stage after the foreground mask is deterministic. Machine learning is needed only to cut the subject out of a photo; a clean graphic on a plain background needs no model at all.

## When to use / when not to

- **Use** when the subject reads well as a silhouette or a few flat layers.
- **Do not use** when depth matters, such as a face or a landscape. Use relief (G2) or full 3D (G3).

## Pipeline specifics

1. **Mask.** Threshold a plain background, or use a perception model (fenced, cached).
   `tdmg select` produces the mask.
2. **Outline.** `tdmg flat` builds the outline in one of two ways:
   - **Smoothed, the default** (`tdmg.smoothing`): a Gaussian blur of the mask by
     `flat.smooth.sigma_px`, then the 0.5 iso-contour, traced with contourpy.
   - **Exact, with `--smooth-px 0`:** the pixel-cell outline of the mask.

   Smoothing removes the jaggedness of soft or low-resolution images. Its cost is
   rounding corners and tips on a scale of about sigma.
3. **Clean.** Repair polygons with Shapely. Iterate over every polygon part, because a repair can return several. Remove slivers and tiny islands.
4. **Normalize.** Apply one explicit image-to-model transform:
   - flip Y, because image rows count downward;
   - decide whether coordinates are pixel centres or pixel edges;
   - scale to one target width in millimetres.
5. **Extrude** each part, naming the triangulation engine explicitly.

## Parameters

| Rule | Role |
|---|---|
| `vectorize.opencv.contour_offset_px` | The measured half-pixel shift of traced outlines |
| `flat.smooth.sigma_px` | Gaussian smoothing of the outline, in image pixels; 0 turns it off |
| `flat.sliver.opening_width` | Shrink and regrow to delete slivers narrower than the nozzle |
| `flat.island.min_square_side` | Drop islands too small to print |
| `fdm.wall.min_thickness`, `fdm.wall.single_perimeter` | Thinnest printable strokes and walls; `fdm.wall.min_thickness` is the width `F3.thin_regions` measures against (information only) |
| `acceptance.dimension.tolerance` | The allowance for `F3.edge_coverage` and `F3.edge_overprint` in `tdmg slice`, plus the profile's elephant-foot compensation on the first layer |
| `fdm.hole.min_diameter` | Smallest hole, for example a keychain loop |
| `fdm.text.min_char_height`, `fdm.text.emboss_min_height` | Legible text |

## Failure modes

| Symptom | Cause | Check | Mitigation |
|---|---|---|---|
| Print is mirrored top to bottom | Image Y axis points down; model Y points up | Asymmetric test glyph | Explicit Y flip in S3 |
| Shapes slightly thin, holes slightly big | OpenCV traces pixel centres (bias of `vectorize.opencv.contour_offset_px`) | Compare against a chosen reference outline: dimensions, holes, gaps, topology | `tdmg flat` does not trace pixel centres. With `--smooth-px 0` it uses the exact pixel-cell outline (area equals the pixel count). The default smoothed outline is an iso-contour of the blurred mask: it has no centre bias, but it does round corners |
| Crash or a missing piece after cleanup | Repair returned several polygons, or a mix of polygons and lines | Diagonal-touch fixture | Handle every polygon part; report collapsed slivers |
| Hair-thin strands, or specks that vanish | Features narrower than the nozzle | `F3.printed_connectivity` and `F3.edge_coverage` in `tdmg slice`, from the G-code (`F3.thin_regions` in `tdmg flat` is information only) | Opening by `flat.sliver.opening_width`; island filter |
| Jagged border on a soft or low-resolution image | The mask boundary is ragged a few pixels deep | Owner's view in a slicer; perimeter length | Default smoothing, `flat.smooth.sigma_px` |
| Tips blunted, crevices filled, thin lines vanish | Smoothing works on a scale of about sigma; a line about 3 px wide or less disappears at 2.5 px | The record's removed and added regions, and part and hole counts; topology warnings | A smaller `--smooth-px`, or 0 |
| Wrong size | Units guessed from DPI (potrace assumes 72, OpenSCAD 96) | F2 target dimensions | Scale to one authoritative width in millimetres |
| 100,000 curves, or hundreds of unsliceable objects | Unsimplified SVG import | F5 triangle and object counts | Simplify while preserving topology |
| Crash on a blank image | No contours found | Empty-mask fixture | Return "no printable foreground" |

## Required checks

F1 (closed, manifold, oriented), F2 (target size, fits the bed), F3 (thin features, judged from the slicer's G-code: printed connectivity, edge coverage and edge overprint), F5 (triangle budget), F6 (slicer accepts the file, in two slicers).

## Calibration needed

None specific to flat geometry. The Phase 1 dimensional check, three caliper measurements, confirms scale and the pixel-cell outline on your A1.

## Evidence

- Tracing, cleanup and extrusion tooling: [flat and relief pathways note](../../../research_notes/Image%20to%20printable%203D%20model%20landscape/image_to_flat_and_relief_pathways.md).
- Half-pixel bias, multipart repair output, Y flip: [stack smoke test](../../../research/verification/2026-11-08-stack-smoke/README.md), sections 3 and 5.
- What OrcaSlicer prints at thin features, and the F3 results on the owner's models: [thin-wall record](../../../research/verification/2026-11-10-thin-walls/README.md).
- Synthesis: [landscape report](../../../reports/Image%20to%20printable%203D%20model%20landscape.md), "Flat and relief prints need machine learning only for the mask".

## Open gaps

- **Decided (2026-11-10, `tdmg flat`):** the reference outline is the exact
  pixel-cell outline of the mask. It is the union of the pixel squares, so it has no
  half-pixel bias, and its staircase edge is one pixel high. OpenCV centre tracing is
  not used.
  - The exact outline is used with `--smooth-px 0`.
  - The default since flat-2 smooths it (`flat.smooth.sigma_px`).
- **Transform:** x_mm = (x_px − x0)·s and y_mm = (y1 − y_px)·s, where (x0, y1) and the
  width come from the bounding box of the outline actually used (the smoothed one by
  default). That box sits at the origin.
- **Not measured:** whether a smoothed outline prints better.
- The sliver and island rules are engineering hypotheses, not published rules.
- **Thin regions:** `F3.thin_regions` measures the outline narrower than
  `fdm.wall.min_thickness`; tapered tips and staircase corners always produce some, so
  it is information only. The pass/fail policy (owner-approved, 2026-11-10) is in
  `tdmg slice`, from what the G-code prints. It holds for the pinned OrcaSlicer 2.5.0 A1
  profile only, does not judge strength, keeps sharp corners strict (sharper than about
  62° can fail coverage), and cannot see a printed-over hole of 0.4 mm or less. See
  `research/verification/2026-11-10-thin-walls/README.md`.
- **Cleaning measurement:** the change cleaning makes is reported as a boundary-sampled
  Hausdorff distance, with a derived upper bound.
- **Sliced and printed, not measured:** the owner's Roadie and Oddie slice with every
  F3 check passing. The owner printed the smoothed Roadie STL, sliced in Bambu Studio,
  and judged it "great" by eye; no caliper measurements exist.

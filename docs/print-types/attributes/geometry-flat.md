# G1 Flat / 2.5D extrusion

## What it is

A shape made by tracing an outline from an image and extruding it straight up: keychains, signs, badges, coasters, cookie cutters. Every stage after the foreground mask is deterministic. Machine learning is needed only to cut the subject out of a photo; a clean graphic on a plain background needs no model at all.

## When to use / when not to

- **Use** when the subject reads well as a silhouette or a few flat layers.
- **Do not use** when depth matters, such as a face or a landscape. Use relief (G2) or full 3D (G3).

## Pipeline specifics

1. **Mask.** Threshold a plain background, or use a perception model (fenced, cached).
2. **Trace.** Trace the outline with OpenCV contours, which return holes as a second level, or with vtracer.
3. **Clean.** Repair polygons with Shapely. Iterate over every polygon part, because a repair can return several. Remove slivers and tiny islands.
4. **Normalize.** Apply one explicit image-to-model transform:
   - flip Y, because image rows count downward;
   - decide whether coordinates are pixel centres or pixel edges;
   - scale to one target width in millimetres.
5. **Extrude** each part, naming the triangulation engine explicitly.

## Parameters

| Rule | Role |
|---|---|
| `vectorize.opencv.contour_offset_px` | Correct the half-pixel shift of traced outlines |
| `flat.sliver.opening_width` | Shrink and regrow to delete slivers narrower than the nozzle |
| `flat.island.min_square_side` | Drop islands too small to print |
| `fdm.wall.min_thickness`, `fdm.wall.absolute_floor` | Thinnest printable strokes and walls |
| `fdm.hole.min_diameter` | Smallest hole, for example a keychain loop |
| `fdm.text.min_char_height`, `fdm.text.emboss_min_height` | Legible text |

## Failure modes

| Symptom | Cause | Check | Mitigation |
|---|---|---|---|
| Print is mirrored top to bottom | Image Y axis points down; model Y points up | Asymmetric test glyph | Explicit Y flip in S3 |
| Shapes slightly thin, holes slightly big | OpenCV traces pixel centres | Pixel-cell comparison fixture | Correct by `vectorize.opencv.contour_offset_px`, or trace pixel edges |
| Crash or a missing piece after cleanup | Repair returned several polygons, or a mix of polygons and lines | Diagonal-touch fixture | Handle every polygon part; report collapsed slivers |
| Hair-thin strands, or specks that vanish | Features narrower than the nozzle | F3 minimum feature | Opening by `flat.sliver.opening_width`; island filter |
| Wrong size | Units guessed from DPI (potrace assumes 72, OpenSCAD 96) | F2 target dimensions | Scale to one authoritative width in millimetres |
| 100,000 curves, or hundreds of unsliceable objects | Unsimplified SVG import | F5 triangle and object counts | Simplify while preserving topology |
| Crash on a blank image | No contours found | Empty-mask fixture | Return "no printable foreground" |

## Required checks

F1 (closed, manifold, oriented), F2 (target size, fits the bed), F3 (wall and feature minimums), F5 (triangle budget), F6 (slicer accepts the file).

## Calibration needed

None specific to flat geometry. The Phase 1 dimensional check, three caliper measurements, confirms scale and the half-pixel correction on your A1.

## Evidence

- Tracing, cleanup and extrusion tooling: [flat and relief pathways note](../../../research_notes/Image%20to%20printable%203D%20model%20landscape/image_to_flat_and_relief_pathways.md).
- Half-pixel bias, multipart repair output, Y flip: [stack smoke test](../../../research/verification/2026-11-08-stack-smoke/README.md), sections 3 and 5.
- Synthesis: [landscape report](../../../reports/Image%20to%20printable%203D%20model%20landscape.md), "Flat and relief prints need machine learning only for the mask".

## Open gaps

- Which tracer gives the most accurate boundary on real images has not been measured.
- The sliver and island rules are engineering hypotheses, not published rules.
- Nothing has been printed yet.

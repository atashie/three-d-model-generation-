# R1 Flat single-color

**Attributes:** [G1 flat](../attributes/geometry-flat.md) · A0 no joints · [C1 single filament](../attributes/color-single.md) · [L1 one print](../attributes/assembly-single.md). **Phase:** 1.

## What it is

A one-color flat object made from an image: a keychain, a sign, a badge, a coaster, or a cookie cutter. It is the first recipe because it exercises every pipeline stage with almost no machine learning.

## When to use / when not to

- **Use** for a logo, a silhouette, or line art.
- **Do not use** for photos where depth or color carries the meaning.

## Pipeline specifics

**Built so far (2026-11-10):** three commands, each writing a record that the next one
checks.
1. `tdmg select IMAGE --out DIR`: S0/S1, the subject mask and a preview for review.
2. `tdmg flat SEL_DIR --width-mm W --thickness-mm T --out DIR`: S2–S4 and S8, the
   outline (smoothed by default; `--smooth-px 0` keeps the exact pixel outline),
   cleaning, extrusion, `model.stl` and its gate.
3. `tdmg slice FLAT_DIR --out DIR`: S9, slicing with the pinned OrcaSlicer 2.5.0 and A1
   profiles, the F6 checks, and F3 judged from the G-code.

See [pipeline and gate](../../guide/pipeline-and-gate.md). Not built yet: the base
plate, keychain loop, text, cookie cutter, 3MF output (S7) and the manifest (S10).

These are the steps added on top of the attribute pages:
- **Base plate:** optional, under the traced shape.
- **Keychain loop:** the hole is at least `fdm.hole.min_diameter`, and the ring around it is at least `fdm.wall.min_thickness`.
- **Text:** characters at least `fdm.text.min_char_height` tall and raised at least `fdm.text.emboss_min_height`.
- **Cookie cutter:** open generators default to a blade wall of `template.cookie_cutter.wall`, but `fdm.wall.min_thickness` takes precedence, so the recipe uses the larger value. Geometry only: the project makes **no food-safety claim**.

## Parameters

`fdm.hole.min_diameter`, `fdm.wall.min_thickness`, `fdm.text.min_char_height`, `fdm.text.emboss_min_height`, `template.cookie_cutter.wall`, `acceptance.dimension.tolerance`, plus those of the attribute pages. The hole rule is depth-dependent; outside the depths its source covers, the check returns UNKNOWN.

## Failure modes

| Symptom | Cause | Check | Mitigation |
|---|---|---|---|
| Loop snaps | Ring thinner than two perimeters | F3 wall minimum around the hole | Grow the ring |
| Text unreadable | Characters too small or too low | F3 feature minimum | Enlarge or drop text |
| Cookie cutter used with food | Not a geometry question | None. Outside the gate | Labelled as a geometric prototype; see the plan's section on safety and rights |

## Required checks

F1, F2, F3 (walls, features, holes), F4 (body count), F5, F6. The recipe's code will declare these, and the docs will be generated from that declaration.

Today the required sets are declared by the commands, not yet by the recipe
(`FLAT_REQUIRED_CHECKS` in `src/tdmg/flat.py`, `SLICE_REQUIRED_CHECKS` in
`src/tdmg/slicing.py`). The `tdmg slice` verdict requires:
- F1: all seven topology checks;
- `F2.fits_build_volume`, `F2.target_width`, `F2.export_matches_geometry`;
- `F3.printed_connectivity`, `F3.edge_coverage`, `F3.edge_overprint`;
- `F4.body_count`, `F5.triangles`;
- `F6.slicer_exit`, `F6.gcode_present`, `F6.layer_count`, `F6.single_object`,
  `F6.portability`.

`F3.thin_regions` is information only there. `tdmg flat` alone also requires
`F3.thin_regions` and the placeholder `F6.slicer`, both always UNKNOWN, so its verdict is
always NOT CERTIFIED. No hole, text or loop check exists yet, because those features are
not built.

## Calibration needed

- **First run:** print one output and measure three named dimensions with calipers. Each must be within `acceptance.dimension.tolerance` of its design value.
- **Same session:** print the clearance ladder. R1 doesn't need it, but it unlocks later recipes.

## Evidence

- Cookie-cutter defaults: [flat and relief pathways note](../../../research_notes/Image%20to%20printable%203D%20model%20landscape/image_to_flat_and_relief_pathways.md).
- Hole, text and wall rules: [rules reference](../../reference/rules.md).
- Slicing the owner's models: [OrcaSlicer record](../../../research/verification/2026-11-10-orcaslicer-windows/README.md) and the F3 results in the [thin-wall record](../../../research/verification/2026-11-10-thin-walls/README.md).
- Portability and the first PRINTABLE verdicts: [PrusaSlicer record](../../../research/verification/2026-11-11-prusaslicer-windows/README.md).
- The first print (owner report): [outline-smoothing record](../../../research/verification/2026-11-10-outline-smoothing/README.md), "First physical print".

## Open gaps

- **PRINTABLE is not calibrated:** the owner's Roadie and Oddie (60 × 3 mm, smoothed)
  are PRINTABLE with both pinned slicers (2026-11-11). The tolerance is still a
  hypothesis and strength is not judged. For STL, both slicers share the admesh reader,
  so 3MF output must re-check portability.
- **One print, by eye only:** the owner printed the smoothed Roadie STL from
  `tdmg flat` in matte PLA, sliced in Bambu Studio with its standard settings (not
  `tdmg slice`'s G-code), and judged it "great". There are no caliper measurements, so
  the first-run calibration above is not done.
- **Roadie's edge:** still a bit rough in Bambu Studio; accepted for now (open item).
- **F3 limits:** the G-code checks hold only for the pinned OrcaSlicer 2.5.0 A1 profile,
  model each line as an idealised bead, do not judge strength, keep sharp corners strict,
  and cannot see a printed-over hole of 0.4 mm or less.
- **Not built:** base plate, keychain loop, text, 3MF output.
- The acceptance tolerance is the roadmap's own target, a hypothesis until prints confirm it.

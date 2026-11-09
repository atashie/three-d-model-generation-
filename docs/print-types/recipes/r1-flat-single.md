# R1 Flat single-color

**Attributes:** [G1 flat](../attributes/geometry-flat.md) · A0 no joints · [C1 single filament](../attributes/color-single.md) · [L1 one print](../attributes/assembly-single.md). **Phase:** 1.

## What it is

A one-color flat object made from an image: a keychain, a sign, a badge, a coaster, or a cookie cutter. It is the first recipe because it exercises every pipeline stage with almost no machine learning.

## When to use / when not to

- **Use** for a logo, a silhouette, or line art.
- **Do not use** for photos where depth or color carries the meaning.

## Pipeline specifics

These are the steps added on top of the attribute pages:
- **Base plate:** optional, under the traced shape.
- **Keychain loop:** the hole is at least `fdm.hole.min_diameter`, and the ring around it is at least `fdm.wall.min_thickness`.
- **Text:** characters at least `fdm.text.min_char_height` tall and raised at least `fdm.text.emboss_min_height`.
- **Cookie cutter:** a blade wall of `template.cookie_cutter.wall`. Geometry only: the project makes **no food-safety claim**.

## Parameters

`fdm.hole.min_diameter`, `fdm.wall.min_thickness`, `fdm.text.min_char_height`, `fdm.text.emboss_min_height`, `template.cookie_cutter.wall`, plus those of the attribute pages.

## Failure modes

| Symptom | Cause | Check | Mitigation |
|---|---|---|---|
| Loop snaps | Ring thinner than two perimeters | F3 wall minimum around the hole | Grow the ring |
| Text unreadable | Characters too small or too low | F3 feature minimum | Enlarge or drop text |
| Cookie cutter used with food | Not a geometry question | None. Outside the gate | Labelled as a geometric prototype; see the plan's section on safety and rights |

## Required checks

F1, F2, F3 (walls, features, holes), F4 (body count), F5, F6. The recipe's code will declare these, and the docs will be generated from that declaration.

## Calibration needed

- **First run:** print one output and measure three named dimensions with calipers. They should be within ±0.2 mm.
- **Same session:** print the clearance ladder. R1 doesn't need it, but it unlocks later recipes.

## Evidence

- Cookie-cutter defaults: [flat and relief pathways note](../../../research_notes/Image%20to%20printable%203D%20model%20landscape/image_to_flat_and_relief_pathways.md).
- Hole, text and wall rules: [rules reference](../../reference/rules.md).

## Open gaps

- No R1 output has been printed yet.
- The ±0.2 mm acceptance band is the roadmap's own target, not a published tolerance.

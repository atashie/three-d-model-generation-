# C1 Single filament

## What it is

The whole print uses one filament. It can still contain several bodies, such as a chain of separate links. Color information from the image is discarded.

## When to use / when not to

- **Use** for most first prints, and whenever the shape matters more than color.
- **Do not use** when the design depends on color. Use C2 for flat multicolor work.

## Pipeline specifics

- S6 does nothing.
- S7 writes STL when there is exactly one body, otherwise 3MF. In a 3MF, bodies that must keep their relative positions go into one components object, so a slicer cannot move them apart.

## Parameters

No rules are specific to single color.

## Failure modes

| Symptom | Cause | Check | Mitigation |
|---|---|---|---|
| Separate bodies fused, or one body vanishes | Overlapping bodies merged on import. Cura merges overlapping volumes by default | F4 body count | Keep bodies disjoint; write 3MF, not STL, for several bodies |
| Parts rearranged by the slicer | Bodies written as separate build items | Read-back check of the 3MF | One components object per assembly |

## Required checks

F4 body count matches the recipe's expectation.

## Calibration needed

None.

## Evidence

- Cura's merge behavior and 3MF build-item rules: [landscape report](../../../reports/Image%20to%20printable%203D%20model%20landscape.md), the print-readiness gate section.
- Separate build items: [stack smoke test](../../../research/verification/2026-11-08-stack-smoke/README.md), section 5.

## Open gaps

- How Bambu Studio treats several bodies in a plain 3MF has not been tested on this project's files.

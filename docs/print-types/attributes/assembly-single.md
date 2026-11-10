# L1 One print

## What it is

Everything prints in one job on one plate.

## When to use / when not to

- **Use** whenever the model fits the A1's build volume of 256 × 256 × 256 mm.
- **Do not use** when the model is larger than that. Use L2 and split it into parts.

## Pipeline specifics

- S3 places the model on the bed and orients it.
- S8 checks the fit against the printer profile.

## Parameters

| Rule or profile field | Role |
|---|---|
| `build_volume_mm` in `profiles/printers/bambu-a1.yaml` | Bed fit |
| `slicer.orca.max_triangles_per_plate` | Triangle budget for the plate |

## Failure modes

| Symptom | Cause | Check | Mitigation |
|---|---|---|---|
| Slicer refuses the plate | Model larger than the build volume; OrcaSlicer rejects plates whose objects do not fit | F2 bed fit is a FAIL, not a warning | Scale down, or switch to L2 |
| Slicer refuses the plate (OrcaSlicer code −59 in its source), or slices a huge mesh slowly | More triangles than the plate limit. OrcaSlicer 2.5.0 did not enforce its `--mtcpp` limit for STL input (measured on Windows), so do not rely on the slicer to refuse | F5 triangle budget, enforced by tdmg itself | Decimate in S3, with measured error |

## Required checks

F2 bed fit, F5 triangle budget.

## Calibration needed

None.

## Evidence

- Build volume: [A1 profile](../../../profiles/printers/bambu-a1.yaml) and its sources.
- OrcaSlicer bed-fit rejection and triangle limit: [landscape report](../../../reports/Image%20to%20printable%203D%20model%20landscape.md), slicer paragraph.
- Measured on Windows with OrcaSlicer 2.5.0 (a box larger than the bed exits −50, "No object is fully inside the print volume"; `--mtcpp` not applied to an STL): [OrcaSlicer record](../../../research/verification/2026-11-10-orcaslicer-windows/README.md).

## Open gaps

- OrcaSlicer has run on the Windows PC only (`tdmg slice`); it has not been run on the Mac.

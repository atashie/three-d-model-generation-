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

The planned [input interpretation](input-interpretation.md) step checks which
subject the user wants. Geometry checks do not determine that: a valid solid can
still include an unwanted background. The interpretation interface is not yet implemented.

Every check returns **PASS**, **FAIL**, or **UNKNOWN**, with the measured value, the threshold, and the rule it came from. A check that cannot be measured is UNKNOWN; it never passes silently. Each recipe declares the checks it requires. The verdict is **PRINTABLE** only if all of them pass. Otherwise it is **NOT CERTIFIED**, with the reasons.

| Family | What it checks |
|---|---|
| F1 Format and topology | Closed, manifold, consistently oriented, positive volume (`format.3mf.edge_manifold`, `format.3mf.consistent_orientation`); self-intersection is a warning (`format.3mf.self_intersection_is_warning`) |
| F2 Scale and fit | Units, target size, fits the A1's 256 mm build volume, numbers in a safe range |
| F3 Printability geometry | Thin walls, small features, overhangs, trapped supports, stability |
| F4 Structure-specific | Joint clearances, body count, connector fit, color regions |
| F5 Resources | Triangle count (`slicer.orca.max_triangles_per_plate`), file size |
| F6 Sliced output | Two slicers with different 3MF readers, OrcaSlicer and PrusaSlicer, accept the file and produce the expected objects |

If no slicer is installed, F6 is UNKNOWN, so nothing can be PRINTABLE.

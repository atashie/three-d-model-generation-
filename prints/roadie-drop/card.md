# roadie-drop

A finished print in the tdmg library: recipe R2 (Flat multicolor), class flat-icon. Finished on 2026-11-17 by `tdmg finish`.

## What to print

Route **ams**, face **down**. Files (in `files/`):

- `files/model.3mf` (SHA-256 `ec2961184e1b235fb4f051c00824095f9642128a565a829e4f1527b1a4f822d7`)
- `files/palette.json` (SHA-256 `2d96bbaa5582a8b6d15856d51fbf9c9ef861b1f3adb0ef1cfd4aa232ad1f9170`)

How: to print face down: open model.3mf in Bambu Studio, which is face up, and turn it over: select the model, Rotate (R), 180 degrees about X: a rigid half turn, not a mirror; the same face is on the bed as in face-down/ (tdmg turns it about y, so the plate layout is turned 180 degrees). The inlays go on the bed. Then give each color the filament listed; each face's plate_1.gcode is for checking only (tdmg's G-code is not yet printed or compared with Bambu Studio's own slice); prusaslicer.portability-only.gcode.txt is not for printing. The G-code files are not in the library.

Only the ams route was confirmed by the owner; the recipe's other routes (glue) are not in this entry.

## Filaments

From `palette.json` (shell order in `model.3mf`), with the filament numbers tdmg sliced with:

| Shell | Role | Color | Body | Filament |
|---|---|---|---|---|
| 0 | base | `#f60606` | ams-base | 1 |
| 1 | inlay | `#f5f5f5` | ams-color-1-f5f5f5 | 2 |
| 2 | inlay | `#f0f10a` | ams-color-2-f0f10a | 3 |
| 3 | inlay | `#451812` | ams-color-3-451812 | 4 |

## Size

Width 60.0 mm (the subject's width), thickness 3.0 mm (job.yaml).
`ams-base.stl` extents: 59.97 x 49.40 x 3.00 mm (colored.json).

## Layer settings

tdmg sliced it with the pinned orcaslicer-2.5.0 profiles (filament "Bambu PLA Basic @BBL A1", machine "Bambu Lab A1 0.4 nozzle", process "0.20mm Standard @BBL A1"). Whether Bambu Studio's own profiles of these names hold the same settings has not been checked.
From the pinned process profile: layer height 0.2 mm, first layer height 0.2 mm.
- face down: 15 layers

## Historical verdict

At commit `13f839f79598a345b24b2a2f39a05c58dd6c249c`, under the rules then in force (rules SHA-256 `18d564c8715f7fe99b154f6521f563310f9b0725d4639738fab2071b7d17bdae`). `tdmg library verify roadie-drop` re-runs it under the current code and rules and reports the differences; it never rewrites this.

- face down: **PRINTABLE**

PRINTABLE means every required gate check passed for this face with the pinned slicers (OrcaSlicer 2.5.0 on orca-input.3mf and, for portability, PrusaSlicer 2.9.7 on model.3mf) and the A1 profile. It is not a guarantee: the acceptance tolerance (acceptance.dimension.tolerance) is still a hypothesis, no calibration print has been measured, no tdmg G-code has been printed, and strength is not judged.

Warnings:

- color 3 #451812 has no glue piece: all of its regions are too small for a piece (rule color.glue.min_piece_side_mm) and were folded, so the glue model does not use it
- base #f60606 (filament 1): edge coverage FAIL, edges up to 0.36 mm from its printed lines (for example thin areas the slicer skips, or a part left unprinted)
- connectivity check FAIL: the whole model printed 12 parts against 1 in the model (3 of 15 layers differ, z 0.2 to 0.6); base #f60606 (filament 1) printed 8 parts against 7 in the model (3 of 15 layers differ, z 0.2 to 0.6); color 1 #f5f5f5 (filament 2) printed 8 parts against 7 in the model (3 of 15 layers differ, z 0.2 to 0.6); on the owner's plans a connectivity FAIL is where two colors' lines meet edge to edge, see research/verification/2026-11-13-color-slicing/owner-review.txt

## What was not checked

Checks that could not be measured (UNKNOWN): F3.thin_regions, F6.color_filament, F6.color_time, F6.color_waste.

Rules this print used that have not been calibrated on our printer (each with its kind and validation, from rules/):

- `acceptance.dimension.tolerance` = 0.2 (rules/ default) mm: hypothesis, untested
- `color.glue.clearance_mm` = 0.2 mm: hypothesis, untested
- `color.glue.min_piece_side_mm` = 2.0 mm: hypothesis, untested
- `fdm.wall.min_thickness` = 0.9 (rules/ default) mm: empirical, untested
- `flat.island.min_square_side` = 2.0 (rules/ default) x_nozzle: hypothesis, untested
- `flat.sliver.opening_width` = 0.4 mm: hypothesis, untested
- `flat.smooth.sigma_px` = 2.5 px: hypothesis, untested
- `format.3mf.consistent_orientation` = true (rules/ default) bool: normative, untested
- `format.3mf.edge_manifold` = true (rules/ default) bool: normative, untested
- `gate.topology.vertex_manifold` = true (rules/ default) bool: hypothesis, untested
- `perception.alpha.min_opaque` = 128 alpha8: hypothesis, untested
- `slicer.orca.max_triangles_per_plate` = 1000000 (rules/ default) triangles: tool_limit, measured
- `slicer.orca.timeout_s` = 300 s: hypothesis, untested
- `slicer.prusa.timeout_s` = 300 s: hypothesis, untested

Strength is not judged, and tdmg has measured no printed dimension.

## The owner's confirmation

Confirmation 1 (print (ams, face down)), given on 2026-11-16 at job revision 2, in the owner's words (verbatim):

    done, and the newly printed items look great

All 1 current print confirmation(s) are copied verbatim into provenance.json.

## Public

The owner said the design may be public: the printable files are in `files/`, tracked in git.

## Source

- `source/roadie.png`, SHA-256 `ed33495f5fa84f7cb818268fbac75391c8d8163aaec1422c271ac9af9b5673bf`; origin: drawing
- `source/` is git-ignored: it exists only on this disk and its copies.

See `provenance.json` for the code, environment, rules, profiles, checks and confirmations, and `purge.json` for the job's files that were deleted.

# Design note: slicing and the printed-footprint checks (`tdmg slice`)

Stage S9. A slicer turns a solid into G-code, the line-by-line instructions the printer
follows. `tdmg slice` runs a pinned OrcaSlicer 2.5.0 with the Bambu A1 profiles, reads
the G-code back, and judges it (F6 slicer checks, F3 thin-feature checks). With a pinned
PrusaSlicer 2.9.7 it also runs `F6.portability`. It works on an R1 `tdmg flat` folder
and on an R2 `tdmg flat --colors` folder.

## Decisions in force

**Setup and trust:**
- **OrcaSlicer on the PC:** approved by the owner on 2026-11-10. It is AGPL-3.0, so it
  is only run as a subprocess; no code or profile file enters the repo.
- **Pin and verify everything:** the exe, the dll, the flattened profiles and, on every
  run, the full app tree (about 2.5 s). `--skip-tree-check` is recorded, changes the
  slice id and caps the verdict at NOT CERTIFIED. The slicer is found only through
  `--slicer-dir` / `TDMG_ORCASLICER_DIR` (and `--prusaslicer-dir` /
  `TDMG_PRUSASLICER_DIR`), never by searching. `tdmg` never downloads anything; the
  setup scripts do, when the user runs them.
- **Exit codes:** Windows gives the full 32-bit code (measured); macOS/Linux decoding is
  assumed until measured. An exit of 0 does not mean the mesh is valid.
- **The A1 profile must flatten `include` templates** as OrcaSlicer 2.5.0 does. Until
  `slice-5` (2026-11-13) every G-code started with generic start code: do not print a
  G-code from an earlier run.
- **Print from Bambu Studio:** `tdmg`'s `plate_1.gcode` is for checking only until it
  has been compared with Bambu Studio's own slice or printed. The owner slices
  `model.stl` / `model.3mf` in Bambu Studio.

**What the checks mean:**
- **F6:** exit 0, non-empty G-code, the expected layer count (from the STL's z extent as
  stored, with a float32 bound; both neighbouring counts at an exact half layer), one
  object. An F6 PASS shows only these, not intact geometry or printability (F1 covers
  geometry; F4.body_count counts bodies, because two bodies in one STL are one object).
- **Any required FAIL quarantines the G-code** as `.failed`, even after exit 0.
- **F3 is judged from the printed footprint** (thin-wall plan, owner's Decision 2,
  2026-11-10): every extruding move is modelled as a bead and compared with the model's
  section per layer. `F3.printed_connectivity` (same parts and holes),
  `F3.edge_coverage` (edge within `acceptance.dimension.tolerance`, plus elephant-foot
  compensation on the first layer) and `F3.edge_overprint`. Owner, Decision 2a
  (2026-11-10): add the reverse overprint check "yes"; keep sharp corners strict "yes".
  Anything the parser does not understand gives UNKNOWN, never PASS.
- **Near-passes are settled by refinement** (owner, 2026-11-16, "Face down, settle check
  (Recommended)"): pairs of edge samples are bisected down to 0.001 mm (a stopping
  choice, not a threshold). The tolerance did not change. Tied quarter turns are judged
  per check; a non-finite gap is never a PASS.
- **`F6.portability`:** PrusaSlicer reads and slices the file with six explicit settings
  from the A1 profile (the rest are PrusaSlicer's defaults). For STL both slicers read
  with admesh, so it shows a second slicer accepts the file, not an independent reader.
  Its G-code is `prusaslicer.portability-only.gcode.txt`, never for the A1.
- **PRINTABLE** means every required check passed with the pinned slicers and the A1
  profile. It does not mean measured: `acceptance.dimension.tolerance` is a hypothesis,
  no calipers were used, and strength is not judged.

**Color slicing** ([color slicing plan](../plans/2026-11-13-color-slicing.md), approved
2026-11-13, "approved; please proceed"):
- OrcaSlicer gets its own input, `orca-input.3mf`, with each body on its own filament
  (base = filament 1; inlays by shell order). It is not a deliverable.
- Face down is a rigid half turn (a rotation, not a mirror), so the face reads the right
  way when turned back.
- `F6.color_changes`, `F6.tool_placement` (including the prime tower and flush staying
  off the model) and `F6.filaments_used`. Color slices are checked at the plate
  placement only (no quarter turns), so a color swap on a symmetric model FAILs.
- **F3 for color: "Outer edge only (Recommended)"** (owner, 2026-11-13). Required: the
  silhouette's `F3.edge_coverage` and `F3.edge_overprint`, and each color's
  `F3.edge_overprint`. Per-color coverage and all connectivity are warnings.
- **Default face: slice both, prefer face down** (owner, 2026-11-16: "Slice both, prefer
  down (Recommended)"). `--face auto` (the default) chooses down if it is PRINTABLE, else
  up, else none, and records `preferred_face` and the reason. This replaced "Face up
  (Recommended)" (owner, 2026-11-13) on 2026-11-16, after the first AMS print smeared
  face up and looked good face down. `model.3mf` itself stays face up.
- Glue plates are sliced as R1 parts, without `F2.target_width`, with `F4.body_count`
  checked against the glue report.

## Review findings that still constrain the code

- Research scripts refuse to delete an existing non-empty folder (Codex review of the
  slicer check, 2026-11-10, finding 1; removed record; the kept OrcaSlicer record has a
  dated note).
- A hand-edited check status in `out/flat.json` with unchanged parameters is pinned by the
  record hash but not refused (same review, remaining limits).
- The G-code's motion is read, not its layer comments
  ([`research/reviews/2026-11-11-portability/`](../../research/reviews/2026-11-11-portability/README.md)).
- Rotation ties, truncation, commanded Z and G92, extrusion amounts and sampling bounds
  ([`research/reviews/2026-11-10-thin-walls/`](../../research/reviews/2026-11-10-thin-walls/README.md)).
- Firmware conditionals may not hide a tool change or a model extrusion, and flush
  plastic is located ([`research/reviews/2026-11-13-color-slicing/`](../../research/reviews/2026-11-13-color-slicing/README.md)).
- Refinement and NaN gaps; the record's `print` field
  ([`research/reviews/2026-11-16-face-down/`](../../research/reviews/2026-11-16-face-down/README.md)).

## Still open

- Outline-kept plans fail face down: up to 1.18 mm (Roadie) and 0.64 mm (Oddie) of the
  outer edge unprinted on the first layer. `auto` prints them face up. Cause not
  investigated.
- No owner plan has every glue plate PRINTABLE.
- The kept plans' thin interior outline lines are skipped by the slicer (a warning).
- Nearly symmetric parts can be "placement ambiguous" (UNKNOWN).
- Printed-over holes of 0.4 mm or less are not seen; sharp corners are strict.

## Records and plans

- Plans: [slicer check](../plans/2026-11-10-slicer-check.md),
  [thin-wall policy](../plans/2026-11-10-thin-wall-policy.md),
  [portability](../plans/2026-11-11-portability-check.md),
  [color slicing](../plans/2026-11-13-color-slicing.md),
  [face down by default](../plans/2026-11-16-face-down-default.md).
- Measurements: [OrcaSlicer on Windows](../../research/verification/2026-11-10-orcaslicer-windows/README.md),
  [thin walls](../../research/verification/2026-11-10-thin-walls/README.md),
  [PrusaSlicer on Windows](../../research/verification/2026-11-11-prusaslicer-windows/README.md),
  [A1 profile include](../../research/verification/2026-11-13-a1-profile-include/README.md),
  [color slicing](../../research/verification/2026-11-13-color-slicing/README.md),
  [first AMS print](../../research/verification/2026-11-15-first-ams-print/README.md).

## Removed records

- `research/reviews/2026-11-10-slicer/`: Codex review of the slicer check
  (`b3f285e..e667259`), 5 findings, all confirmed; fixes in `426cd2b`. Removed in commit
  `814a962723454efa7693b8ef8af715062368975a` (see git history, or tag
  `pre-restructure`). Where each point lives now: finding 1 (scripts could delete
  data): above, and the OrcaSlicer record's "Script safety fix". Findings 2 (float32
  layer tolerance), 3 (quarantine on any FAIL) and 4 (full tree check every run): the
  decisions above and the slicer plan's execution notes. Finding 5 (STATUS and guide
  contradicted themselves): obsolete. Remaining limits: edited check statuses (above);
  what an F6 PASS shows (above); "portability UNKNOWN", obsolete since
  `F6.portability` (2026-11-11). "682 tests pass": a point-in-time result, obsolete.

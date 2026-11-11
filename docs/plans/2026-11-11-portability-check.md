# Portability check (F6.portability with PrusaSlicer) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** replace the always-UNKNOWN `F6.portability` in `tdmg slice` with a measured
check. A second slicer, PrusaSlicer 2.9.7, whose file reader is independent of the
Bambu/Orca lineage, must:

- accept `model.stl`, with the expected parts, facets, dimensions and volume;
- slice it completely with A1-equivalent settings.

This is the last required check still UNKNOWN for the owner's Roadie and Oddie.

**Why:** `F6.portability` is defined in docs/PLAN.md section 4 (F6) and section 9. The owner
approved installing PrusaSlicer on 2026-11-11. The evidence is
`research/verification/2026-11-11-prusaslicer-windows/`:
- **Exit codes:** rc 1 on errors, and **rc 0 is not success**: an outside-bed part writes
  no G-code, and an open mesh slices truncated.
- **`--info`** matches the flat record's sizes to 6 decimals, the facet counts exactly,
  and the volumes within 5e-6 relative.
- **Layer counts:** the owner models slice to 15 layers with explicit settings; the open
  cube gives 10 of 100.
- **Repeatability:** only the line-1 timestamp differs between runs.

**Status:** written 2026-11-11. Tasks 1–3 done the same day; Task 4 in progress. See
"Execution notes".

## Decisions

1. **Pin and verify, as for OrcaSlicer.**
   - `profiles/slicers/prusaslicer-2.9.7.yaml` holds the release asset and zip SHA-256,
     the `prusa-slicer-console.exe` and `PrusaSlicer.dll` hashes, and the app tree hash.
   - `scripts/setup_prusaslicer.py` installs and verifies it (`--dest`, `--zip`,
     `--verify-only`). Share code with `scripts/setup_orcaslicer.py` where it is clean.
     Windows x64 only.
   - Locate it with `--prusaslicer-dir` or `TDMG_PRUSASLICER_DIR`, never by searching.
     The full tree is verified on every run, as for OrcaSlicer, unless `--skip-tree-check`
     is given, which covers both slicers.
2. **No vendor profile, so no copied profile files.** The slicing settings are passed
   explicitly and taken from the pinned, hash-checked OrcaSlicer A1 profiles, so there is
   one source of truth:
   - the bed shape from `printable_area`, and the height from `printable_height`;
   - `nozzle_diameter`, `layer_height` and `initial_layer_print_height`;
   - `filament_diameter`.

   If a needed value is missing, the run is refused.
3. **The check.** `F6.portability` PASSes only if all of the following hold. Otherwise it
   FAILs and names the first failed condition. It is UNKNOWN when PrusaSlicer is not
   configured, which keeps the current behaviour, and the reason says how to set it up.
   - **`--info`:**
     - exit code 0;
     - `manifold = yes` and no `open_edges` line;
     - `number_of_parts` equals the flat record's `mesh.bodies`;
     - `number_of_facets` equals `mesh.triangles`;
     - each of `size_x/y/z` equals the record's `extents_mm` within the 6-decimal print
       rounding (5e-7 mm) plus a float32 storage bound, using the same derivation as the
       export check (`STL_COORD_RTOL`);
     - `volume` within a derived bound: PrusaSlicer computes it in float32 from float32
       vertices. Derive it in a comment, and check it against the measured 6e-7 and
       4.4e-6 relative values. If a sound bound cannot be derived, report it rather than
       inventing one.
   - **`--export-gcode`** with the explicit settings:
     - exit 0;
     - a non-empty G-code file;
     - its `;LAYER_CHANGE` count in `allowed_layer_counts` (the same STL-based set as
       F6.layer_count);
     - its last `;Z:` equal to the expected top within the existing Z tolerance.
   - The measured values hold the full parsed `--info`, the layer count, the last Z, both
     return codes and the capped stderr tails.
4. **Outputs:** keep PrusaSlicer's G-code only as a portability artefact, as
   `portability/prusaslicer.gcode` with its normalised hash in the record. It is
   generic, not Bambu firmware G-code, and must never be presented as printable for the
   A1. Say so in the record and the CLI.
5. **Identity:** add PrusaSlicer's pinned identity (version, exe, dll and tree hashes,
   whether the tree was verified) and the explicit settings to `slice_id`. Bump
   `SLICE_ALGORITHM_VERSION` to `slice-4`.
6. **Certification:** with this check passing, the owner's models may reach
   **PRINTABLE** for the first time. The record and CLI must say plainly what that
   means, and the docs must explain it to the owner:
   - every required gate check passed for this file with the pinned slicers and the A1
     profile;
   - the acceptance tolerance (`acceptance.dimension.tolerance`) is still a hypothesis;
   - no calibration print has been measured;
   - strength is not judged.

## Tasks
1. **Pin, setup script and locate.** Port the research measurements into tests with a
   fake PrusaSlicer, as `fake_orca.py` does for OrcaSlicer.
2. **The F6.portability check in `make_slice` and the CLI**, with the record, the
   identity, `slice-4` and the PRINTABLE wording.
   - Fake-slicer tests: PASS; open mesh; outside-bed with rc 0 and no G-code; size,
     volume, parts or facets mismatch; a truncated layer count; not configured
     (UNKNOWN); tree mismatch.
   - A real-slicer integration test marked `slicer` that needs both env vars.
3. **Run on the owner's models** and record the result: expected PRINTABLE. Also run the
   open-cube and outside-bed controls through `tdmg slice`.
4. **Docs, STATUS, Codex review, push and CI.**

## Out of scope
- 3MF input.
- Printing PrusaSlicer's G-code.
- PrusaSlicer vendor profiles.
- macOS and Linux setup.

## Execution notes

- **Tasks 1–2** (commits `2a736ec`, `b60e8f0`, `290ba52`, `c88f4f3`, `058cfbb`,
  `b12f6c1`): the pin, `scripts/setup_prusaslicer.py` with code shared with the OrcaSlicer
  setup in `scripts/_slicer_setup.py`, `src/tdmg/portability.py`, and `F6.portability` in
  `tdmg slice` (`slice-4`), tested with `tests/fake_prusa.py` and a real-slicer test.
- **Changes from the decisions above:**
  - **Reader independence:** for STL, both slicers read with admesh. The check is worded
    as "a second slicer accepts and slices the file", and 3MF must re-run it with
    different readers.
  - **File name:** the G-code is `prusaslicer.portability-only.gcode.txt` in the output
    folder (not `portability/prusaslicer.gcode`), so that it is not mistaken for
    printable G-code. It is quarantined as `.failed` like `plate_1.gcode`.
  - **Z check:** every `;Z:` value must follow the expected sequence, not only the last.
  - **Timeout:** each PrusaSlicer run is limited by a new rule, `slicer.prusa.timeout_s`
    (300 s; the slowest measured run took 1.16 s).
  - **`--skip-tree-check`** covers both slicers and caps the verdict at NOT CERTIFIED.
- **Codex critical review** (`research/reviews/2026-11-11-portability/`). Three findings,
  all confirmed and fixed within `slice-4` (unpushed):
  - layer comments alone could PASS: the G-code's motion is now read, and it must be
    complete and extrude on every layer at its height;
  - the volume bound missed admesh's zeroed normals;
  - "every setting explicit" overstated: only the six listed settings are; the rest are
    PrusaSlicer's defaults.
- **Task 3:** see the addendum "`F6.portability` through `tdmg slice`" in
  `research/verification/2026-11-11-prusaslicer-windows/README.md`. Roadie and Oddie are
  PRINTABLE. The open cube and the outside-bed part FAIL `F6.portability`.

# Thin-wall policy (F3 from slicer output) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** replace the always-UNKNOWN `F3.thin_regions` with two checks measured from what
the slicer actually prints. Both run in `tdmg slice`, because they need the G-code:

- `F3.printed_connectivity`: no connection in the model goes unprinted.
- `F3.edge_coverage`: no part of the outline is left unprinted beyond a stated tolerance.

`F3.thin_regions` stays as a measurement for information only, and is no longer
required.

**Why:** the owner asked for the thin-wall rule in plain English and chose it as the next
step on 2026-11-10. The evidence is `research/verification/2026-11-10-thin-walls/`:
- **The owner's models:** above the first layer, every outline point of Roadie and Oddie
  is within 0.07 mm of printed plastic. Thin tips are filled with gap infill, and each
  model is one printed part on every layer.
- **The control bridges:** connections 0.3 mm wide or narrower are not printed. The
  printed footprint then splits, and the edge gap is about 2.5 mm. A 0.45 mm bridge is
  missing on the first layer only.
- **The first layer:** it is deliberately shrunk by `elefant_foot_compensation`
  (0.075 mm), which gives gaps of up to 0.24 mm there.

**Status:** written 2026-11-10. The owner approved the rule in Decision 2 on
2026-11-10 ("I approve this rule"). Not started.

## Decisions

1. **Where the checks run:** in `tdmg slice`. Code from the research script
   `measure_coverage.py` becomes `src/tdmg/printed.py`:
   - G-code parsing: Z_HEIGHT, FEATURE, LINE_WIDTH, M82/M83, and G1 with G2/G3 arcs;
   - the footprint per layer;
   - the model section per layer, taken from the hash-checked STL bytes;
   - rotation-aware alignment;
   - per-layer metrics.

   Anything not understood in the G-code makes the check UNKNOWN, never PASS. That
   includes absolute E, unknown arc forms, a missing LINE_WIDTH and an unknown alignment.
2. **Proposed rule, for the owner to approve.** It uses existing rules and profile values
   only, with no new numbers:
   - `F3.printed_connectivity` PASSes when, on every layer, the printed footprint has the
     same number of parts as the model section, and the same number of holes. Any extra
     printed part (a split) or a missing one FAILs, naming the layer(s) and location.
     This is conservative: the 0.45 mm control bridge, missing on the first layer only,
     would FAIL.
   - `F3.edge_coverage` PASSes when, above the first layer, every model-edge sample is
     within `acceptance.dimension.tolerance` (0.2 mm) of printed plastic. On the first
     layer, the allowance is that tolerance plus the profile's
     `elefant_foot_compensation`, read from the flattened process profile (0.075 mm, so
     0.275 mm). Otherwise it FAILs, giving the largest gap, its layer and its location.
   - `F3.thin_regions` stays in the flat record as information and is removed from the
     required set. Its note points to the two slicer-based checks.
3. **Honest scope, stated in the docs and the record:**
   - the bead model, a line of the stated width with round ends, approximates real
     plastic;
   - a printed single thin line can still be fragile, and strength is not judged;
   - this holds for the pinned OrcaSlicer and A1 profile only.

   The rule `acceptance.dimension.tolerance` remains a hypothesis until caliper
   measurements exist.
4. **Certification:** with this policy, Roadie and Oddie would pass F3, so only
   `F6.portability` (no second slicer) would block PRINTABLE. Nothing in this plan claims
   PRINTABLE.
5. **Performance:** footprint unions over every layer took seconds per model in the
   research runs. Measure this, and document it if it exceeds about 10 s.

## Tasks

1. **`printed.py`:** port the research code as tested functions. Tests use synthetic
   G-code strings for G1 lines, arcs, relative/absolute E and a missing width, plus small
   synthetic models.
2. **Checks and verdict in `tdmg slice`:**
   - add the two F3 checks to slice's required set, and drop `F3.thin_regions` from the
     required set while keeping it in the record;
   - record the per-layer metrics (worst layer only, plus a compact per-layer list);
   - test with the fake slicer by having it write G-code fixtures: a connected case, a
     split case and an uncovered tip.
3. **Run on the owner's models** and record it. Expect F3 PASS for both, leaving only
   `F6.portability`. Also run the bridge controls through `tdmg slice`.
4. **Docs, STATUS, Codex review, push and CI.**

## Out of scope
- Strength or impact judgement.
- Profiles other than the pinned A1 0.20 mm PLA.
- Auto-thickening thin features.
- PrusaSlicer portability.

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

**Status:** written 2026-11-10. The owner approved Decision 2 and later Decision 2a.
Tasks 1–3 executed the same day; Task 4 in part (docs and STATUS done; Codex review,
push and CI not done). See "Execution notes".

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
2a. **Owner decisions after review (2026-11-10):**
    - **Reverse check, "yes":** add `F3.edge_overprint`, which FAILs when printed plastic
      lies more than the same allowance outside the model. That also closes "plastic
      printed over a small hole".
    - **Sharp corners, "yes":** keep them strict. A corner sharper than about 62° can fail
      `F3.edge_coverage` by construction, because a round bead misses a vertex by
      r(1/sin(θ/2) − 1). Revisit if a real model trips it.
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

## Execution notes

- **Tasks 1–2:** `src/tdmg/printed.py` plus the F3 checks in `tdmg slice`. Three checks
  are now required: `F3.printed_connectivity`, `F3.edge_coverage` and `F3.edge_overprint`
  (Decision 2a). `F3.thin_regions` is information only in slice.
- **Review-driven changes:**
  - **Placement:** the known placement (OrcaSlicer centres the bbox on the plate) replaces
    a fitted shift. The fitted shift could absorb one-sided errors, which were measured
    false PASSes.
  - **Holes:** holes and parts are matched one to one.
  - **Exceptions:** any analysis exception gives UNKNOWN, and the outputs are still
    written.
  - **Feature allow-list:** features outside it, such as brim, skirt and support, give
    UNKNOWN.
  - **Parser:** G-code forms OrcaSlicer does not write are refused. That covers G01, a
    missing space, N line numbers and checksums, G5, G18 and G19, firmware retract, and a
    Custom extrusion after the model starts.
  - **Z checks:** Z order and continuity are checked.
  - **Rotation ties:** tied quarter-turns are judged by the worse result.
  - **Identity:** the tolerance and elephant-foot values enter `slice_id`.
- **Task 3:** see the addendum in `research/verification/2026-11-10-thin-walls/README.md`.
  Roadie and Oddie pass all three F3 checks. Only `F6.portability` blocks PRINTABLE.
- **Known limits:** printed-over holes of 0.4 mm or less cannot be told apart at 0.2 mm;
  sharp corners are strict; strength is not judged.
- **Task 4 (2026-11-10, in part):** the docs and `docs/STATUS.md` describe the three
  F3 checks (documentation audit commit). Not done: an independent Codex review of
  `src/tdmg/printed.py` (none is recorded in `research/reviews/`), the push, and CI.
  The commits from `70806d2` onward are local only.

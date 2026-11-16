# Face down by default, and edge-coverage near-passes settled: implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task by task.

**Goal:** `tdmg slice COLORED_DIR` slices face down by default. `F3.edge_coverage` turns a
"within sampling uncertainty" result into a measured PASS or FAIL by refining the edge
samples where it matters.

**Why (the owner's evidence and decision):**
- **Evidence:** the first AMS print of Roadie (outline dropped) face up came out smeared.
  The same `model.3mf` turned over in Bambu Studio, with nothing else changed, "look[s]
  great". Record: `research/verification/2026-11-15-first-ams-print/README.md`.
- **The owner's choice (2026-11-16):** "Face down, settle check (Recommended)". Make face
  down the default, and sample the edge more finely so that near-passes get a real PASS
  or FAIL. The tolerance itself does not change.
- **The near-pass that started this:** Roadie drop, face down, z 0.2 mm. The largest
  sampled gap is 0.251 mm against 0.275 mm. Samples are 0.05 mm apart, so the bound
  (`COVERAGE_BOUND_MM`, 0.025 mm) leaves it UNKNOWN, and the face is NOT CERTIFIED.

**Architecture:**
- Face: one constant (`tdmg.color_slicing.DEFAULT_FACE`), plus its messages, CLI help and
  docs.
- Refinement: in `tdmg.printed`, after the 0.05 mm samples. It applies to any layer where
  the coarse result is within the bound, for the silhouette and for each tool, for R1 and
  R2 alike. No threshold changes.

**Tech stack:** Python 3.13, shapely 2, numpy, pytest. Nothing new.

---

## Decisions

1. **Default face: down.**
   - `DEFAULT_FACE = "down"`, with the comment citing the owner's decision and the print
     record.
   - `--face up` and `--face both` stay.
   - **Messages:**
     - The face-down print message says how to turn the model in Bambu Studio: select it,
       Rotate (R), 180° about X. It is the same face down as `turn_over` (about y): a
       rigid half turn, not a mirror, so the face reads as designed when the print is
       picked up and turned back.
     - The "both" message names face down as the owner's default.
   - **Not changed:**
     - `model.3mf` stays face up (written by `tdmg flat`, checked by
       `F2.export_3mf_matches_bodies`);
     - the calibration skin strip stays face up (`SKIN_FACE`; it was printed and
       calibrated that way).
2. **Settling near-passes in `F3.edge_coverage`:**
   - **Why it is valid:** the distance to the footprint is 1-Lipschitz. Between two
     consecutive samples a and b, a distance s apart on one straight piece of the edge,
     the true largest gap is at most (d_a + d_b + s) / 2. This is tighter than the current
     max + s / 2, and exact as a bound.
   - **When it runs:** only on a layer the 0.05 mm samples leave within the bound (`near`
     in `_judged`): no sample over the allowance, but sampled max + `COVERAGE_BOUND_MM`
     over it. Each pair of consecutive samples whose pair bound exceeds the allowance is
     bisected: new samples at the midpoint, recursively.
   - **The result:**
     - **FAIL:** a new sample is over the allowance.
     - **PASS:** every pair's bound is within the allowance.
     - **Still UNKNOWN:** a pair is still open when its spacing reaches
       `EDGE_REFINE_MIN_MM`.
   - **`EDGE_REFINE_MIN_MM`:** 0.001 mm, a resolution and not a threshold. The A1 G-code
     gives coordinates to 3 decimals (`G1 X123.156 Y141.322`, measured in
     `artifacts/slice-runs/color5-roadie-drop-v3-f64-down/face-down/plate_1.gcode`), so a
     finer spacing measures nothing real. Put the comment and the evidence beside the
     constant.
   - **Pairs:**
     - Pairs must not join samples of different rings, or across a ring's closing
       duplicate.
     - Samples are paired only along the segmentized boundary, where consecutive points
       lie on one straight piece.
   - **The record (`measured`):** the coverage check adds:
     - `refined_layers`: the z of each layer refined;
     - the final bound used: `pair_bound_max_mm`, the largest pair bound after
       refinement, on the worst refined layer;
     - `refine_min_mm`.

     The note says when refinement ran and what it settled. The sampled `max_gap_mm`
     stays the largest gap actually sampled, the refined samples included.
   - **Scope:**
     - every place `F3.edge_coverage` is judged: R1 `tdmg slice`, the colored silhouette
       and each tool's coverage;
     - `F3.edge_overprint` is not changed (its grid bound needs a different refinement;
       out of scope, noted in the docs);
     - turn choice (`SCORE_BOUND_MM`) is not changed.
   - **Determinism:** the same inputs give byte-identical records. Bisection is
     deterministic: midpoints in a fixed order, and no randomness.
3. **Versions:**
   - bump `SLICE_ALGORITHM_VERSION` (`slice-6`) and `COLORSLICE_ALGORITHM`
     (`colorslice-2`), each with a dated comment;
   - bump the strip's `ALGORITHM` if its identity includes slice results that can change
     (check how `strip_id` is built).

## Tasks

### Task 1: refinement in `tdmg.printed` (tests first)

- **Unit tests, on synthetic geometry** (a square section and a footprint built to leave
  known gaps):
  - a near-pass whose true largest gap is under the allowance becomes PASS;
  - a near-pass whose true largest gap is over it, hidden between two coarse samples,
    becomes FAIL, and the new largest sample is over the allowance;
  - a case that stays open down to `EDGE_REFINE_MIN_MM` stays UNKNOWN;
  - layers not near are untouched, so their results are byte-identical to before;
  - no pair joins two rings: a section with a hole, the gap near the ring seam;
  - the pair bound is never below the true distance: a property test on random points
    along random segments.
- **Then:** implement, and wire it into `_coverage` and its colored equivalent in
  `tdmg.color_gcode` through `_judged` or beside it.

### Task 2: face down by default

- **Tests first:** CLI and `make_color_slice` defaults; the print messages; `tdmg slice`
  on a single-color folder still refuses `--face`, against the new default.
- **Then:** constant, messages, help text.

### Task 3: real-slicer re-run and record

With the pinned OrcaSlicer 2.5.0 and PrusaSlicer 2.9.7, on the owner's PC:
- **The four owner plans:** `tdmg slice` with the new default (face down) and with
  `--face up`.
- **R1:** Roadie and Oddie.
- **The strip:** `tdmg strip`.

Record each verdict and every `F3.edge_coverage` status change against the 2026-11-15/16
runs in `research/verification/2026-11-15-first-ams-print/README.md`, in a new section.
Run the real-slicer tests.

### Task 4: docs and review

- **Docs:**
  - `docs/print-types/attributes/color-multi.md` (face, refinement);
  - `docs/guide/pipeline-and-gate.md`;
  - `README.md` if it names the face;
  - STATUS.
- **Codex review** in `research/reviews/2026-11-16-face-down/`, handled as before.

## Amendment after Task 3 (2026-11-16): slice both faces, prefer face down

- **What Task 3 found** (`research/verification/2026-11-15-first-ams-print/README.md`,
  last section): the two outline-kept plans FAIL `F3.edge_coverage` face down. On the
  first layer, part of the outer edge is unprinted: Roadie 1.18 mm, Oddie 0.64 mm against
  0.275 mm. Both pass face up. The two outline-dropped plans pass both ways.
- **The owner's decision (2026-11-16):** "Slice both, prefer down (Recommended)".
- **Decision 1a:**
  - **Default (`--face` not given) is `auto`:** slice both faces, then choose the face
    to print: down if it is PRINTABLE, else up if it is PRINTABLE, else none.
  - **The record** gains `preferred_face` ("down", "up" or null) and the reason, for
    example "face down is PRINTABLE (the owner's preference)" or "face down is NOT
    CERTIFIED (F3.edge_coverage FAIL); face up is PRINTABLE".
  - **The CLI** prints the chosen face's print instructions and one line saying why.
    The other face's verdict is still printed.
  - **Exit codes under `auto`:**
    - a FAIL on the face not chosen does not set exit 1 when the chosen face is
      PRINTABLE;
    - with no PRINTABLE face, the exit is as today;
    - glue plates are judged as today.
  - **Explicit faces:** `--face up`, `down` and `both` behave exactly as now. `both`
    makes no choice; it reports both faces.
  - **Versions:** `colorslice-2` is not pushed yet, so it covers this too. Its comment
    is updated.
  - **The face option is part of `colorslice_id`** (the implementer's addition, accepted
    at review): `auto` and `both` slice the same faces but differ in the record and the
    exit rule. So `colorslice-2` ids made at 3bb2d6b do not reproduce.
- **Task 2b:** implement Decision 1a, tests first: each preference branch, the exit
  codes, the record and the messages. Then the spec and quality reviews. Then re-run
  the four owner plans with the default.

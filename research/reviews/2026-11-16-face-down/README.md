# Independent critical review of face down by default and refined edge coverage, 2026-11-16

Plan: `docs/plans/2026-11-16-face-down-default.md`, Task 4.

**How the review was run:** with the installed OpenAI Codex CLI (0.167.0):

```
codex exec --sandbox read-only --ephemeral -o review.txt "$(cat prompt.md)"
```

It covered commits `ec6e9ac..ac32a08`: the plan, the refinement, the face choice, the
docs, the re-run records and this prompt. `prompt.md` is the prompt and `review.txt` is
Codex's response, verbatim.

**What Codex ran:** 283 geometry and G-code tests and 17 face-choice tests, plus in-memory
reproductions. It could not run the filesystem-based integration tests, the Hypothesis
property test or the real slicers.

## Findings and how each was handled

Each finding was checked against the code before it was fixed (CLAUDE.md, Review
practice). Each fix was written as a failing test first. All five held.

1. **Medium: refinement could erase a connectivity FAIL.**
   - **Verdict: holds,** confirmed with Codex's 10 × 9.98 mm reproduction as a test.
   - **The cause:** two quarter turns tie on score. Refinement settles coverage
     differently on them. The old rule then made all three F3 checks UNKNOWN, including a
     connectivity FAIL that held on every turn.
   - **Fixed** (`7da0577`): `judge_f3` resolves tied turns per check. A check that every
     tied turn agrees on keeps its result; a check they disagree on alone is UNKNOWN.
   - **This changes unrefined cases too.** It is more informative and still sound: a
     status that holds on every plausible placement does not depend on the placement.
   - It is stated in the docstring, the `slice-6` comment and `pipeline-and-gate.md`.
   - Colored slices use one fixed turn and are not affected.
2. **Medium: a NaN gap could give a false PASS.**
   - **Verdict: holds** under fault injection (every midpoint gap NaN). A 0.21 mm notch
     against 0.2 mm PASSed. No real footprint was found that gives NaN.
   - **Fixed** (`c513b62`):
     - `refine_edge` raises on a non-finite gap (coarse on a near layer, or refined), so
       the check is an UNKNOWN analysis error;
     - `_judged` PASSes only when the bound is shown to be within the allowance, so a NaN
       maximum or bound is UNKNOWN;
     - an infinite gap still FAILs.
3. **Low: the saved record omitted the turn for face down.**
   - **Verdict: holds** (read in the code and in the re-run `slice.json`).
   - **Fixed** (`b99164c`): the record gains a `print` field with the chosen face's full
     instructions. The CLI prints that field, so the terminal and the record cannot differ.
     `review` and `model_3mf.note` point to it.
4. **Low: the 0.001 mm floor's justification was wrong.**
   - **Verdict: holds.** Codex's case is UNKNOWN at 0.001 mm and PASS at 0.0001 mm, so a
     finer floor can measure something.
   - **Fixed** (`3397b0b`): the value stays. It is now described as a computational
     stopping choice:
     - conservative, because an open pair stays UNKNOWN;
     - at most 6 halvings from 0.05 mm;
     - matched to the G-code's 0.001 mm coordinate step.

     The comment, the docs and a dated note under the plan's Decision 2 say so. Codex's
     case is a test.
5. **Low: the docs contradicted the re-runs and the print record.**
   - **Verdict: holds.**
   - **Fixed** (`1ba9f57` and the commit with this record):
     - the guide and `color-multi.md` give the re-run results;
     - the README says Roadie (outline dropped) was printed and Oddie was not;
     - STATUS no longer says both outline-dropped plans were printed;
     - a stale "nothing is printed yet" line on the test strips is fixed too.

## Re-checks after the fixes (2026-11-16, the owner's PC)

The pinned OrcaSlicer 2.5.0 and PrusaSlicer 2.9.7 were used, with outputs in
`artifacts/slice-runs/fd8/`.

| Run | Result |
| --- | --- |
| R1 Roadie | PRINTABLE |
| R1 Oddie | PRINTABLE |
| Roadie outline dropped | face down chosen |
| Oddie blues merged | face down chosen |
| Roadie outline kept | face up chosen (face down FAIL) |
| Oddie outline kept | face up chosen (face down FAIL) |

The two outline-dropped plans exit 1 because of their glue plates, as before. Every
verdict equals the `fd7` run.

**Real-slicer tests** (`pytest -m slicer`, both pinned slicers): 8 passed after one
expectation was updated. `test_the_real_slicer_passes_all_three_checks[down]` pinned the
Roadie drop plan face down as NOT CERTIFIED (coverage UNKNOWN). Refinement now settles
that layer, so the test expects PRINTABLE on both faces.

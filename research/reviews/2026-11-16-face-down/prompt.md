You are doing an independent, critical and adversarial review of commits ec6e9ac..HEAD in this repository (run `git log --oneline ec6e9ac..HEAD` and `git diff ec6e9ac..HEAD -- src tests docs README.md research`). Read CLAUDE.md first: the project's rules (no unexplained numbers, rules with evidence in rules/*.yaml, docs agree with code, never call something verified unless it was run, research files are records). Assume the work is wrong somewhere and try to show where.

**What these commits build** (plan, with an amendment: docs/plans/2026-11-16-face-down-default.md):

1. **Edge-coverage refinement.**
   - `F3.edge_coverage` samples each model-section edge every 0.05 mm.
   - Before, a layer whose sampled largest gap was within 0.025 mm of the allowance was UNKNOWN.
   - Now such a "near" layer is refined. Consecutive samples a, b at spacing s on one straight piece of one ring have a pair bound (d_a + d_b + s)/2 (distance to the footprint is 1-Lipschitz). Open pairs are bisected down to `EDGE_REFINE_MIN_MM` (0.001 mm, argued to be the G-code's coordinate resolution).
   - Results: FAIL if a refined sample is over the allowance; PASS if every pair bound is within it; else UNKNOWN.
   - Code: src/tdmg/printed.py (`pair_bound`, `_edge_pairs`, `refine_edge`, `layer_metrics`, `_judged`, `_coverage`).
   - It applies to R1 `tdmg slice` and to the colored silhouette's and each tool's coverage (src/tdmg/color_gcode.py goes through the same functions).
   - Versions: `slice-6`, `colorslice-2`, `strip-4`.
2. **Face choice for a colored folder.** `tdmg slice COLORED_DIR` now slices both faces by default (`auto`) and chooses face down if PRINTABLE, else face up if PRINTABLE, else none.
   - It records `preferred_face` and a reason.
   - It judges the exit code on the chosen face, with glue plates as before.
   - Explicit `--face up|down|both` behaves as before.
   - Code: src/tdmg/color_slicing.py (`DEFAULT_FACE`, `choose_face`, messages) and src/tdmg/cli.py (`_color_failed`, the slice command).

**The evidence and the owner's decisions** are in research/verification/2026-11-15-first-ams-print/README.md:
- the owner's face-up print smeared, and the face-down print "look[s] great";
- the owner chose "Face down, settle check", then "Slice both, prefer down";
- the real-slicer re-runs.

These are owner decisions. Do not report them as defects, but do report code that does not do what they say.

Look hardest for:
1. **Can the refinement ever PASS a layer whose true largest edge gap exceeds the allowance?** For example:
   - pairs that are not on one straight piece;
   - pairs across rings or across the closing point;
   - samples in model vs bed coordinates (rotation, the alignment's shift);
   - floating-point at the allowance;
   - a footprint that changes between the coarse and refined evaluation;
   - MultiPolygon sections;
   - holes;
   - an infinite or NaN gap;
   - a layer that is refined on one turn but judged on another.

   Is the 0.001 mm floor argued soundly? Is anything that could not be measured ending as PASS instead of UNKNOWN?
2. **Did the refinement change any result it should not?** For example: layers that are not near, `share_over_allowance`, the turn choice (`SCORE_BOUND_MM`), `F3.edge_overprint`, or records and ids beyond the stated version bumps.
3. **The face choice:** can the CLI exit 0, or print instructions for a face, when that face is not PRINTABLE? Can the face not chosen hide a problem that also affects the chosen face? Can the instructions be misread, so the owner prints the wrong face, prints a G-code (only `model.3mf` is for printing), or mirrors the model? Is the "rotate 180° about X" instruction the same physical face down as `turn_over` (src/tdmg/orca_input.py)?
4. **Does the plan, with its amendment, match the code? Do the docs and docstrings match the code?** Docs: README.md, docs/STATUS.md, docs/guide/pipeline-and-gate.md, docs/guide/glossary.md, docs/print-types/attributes/color-multi.md.
5. **Does any claim go beyond what was run or measured?** Check the docs, plan, record, code comments, CLI output and record texts.

Report each finding with:
- severity (High/Medium/Low);
- file:line;
- a concrete failing scenario;
- whether you confirmed it by running code or only by reading.

Give an in-memory reproduction where possible. Do not modify files. If uv or pytest cannot run in the sandbox, use plain Python reproductions (the venv is .venv/Scripts/python.exe) and say what you could not run. tests/fake_orca.py has the fake slicers the tests use; you need not run the real slicer.

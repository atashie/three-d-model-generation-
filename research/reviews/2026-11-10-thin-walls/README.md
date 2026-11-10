# Independent critical review of the thin-wall (F3) policy and the docs audit, 2026-11-10

The owner asked for this review after the documentation audit. I ran the installed OpenAI
Codex CLI (0.167.0) with `codex exec --sandbox read-only --ephemeral` on commits
`fdb6e67..a1451a8`. The full response is in [review.txt](review.txt).

Codex re-analysed the saved owner G-code: the hashes and F3 measurements match the
records. It confirmed that the research corrections were appended, not rewritten. It ran
in-memory reproductions, but its read-only sandbox blocked the test suite.

Before this, the F3 work had a subagent spec and quality review, an adversarial
re-review, and fixes after each. I checked every finding below against its reproduction
before handling it. Each scenario is now a test that failed first. The fixes are in
`313cdbc` (code) and `a5e3e73` (controls).

1. **A rotation tie could falsely FAIL a correct print.** Confirmed: a square with an
   off-centre hole had four zero medians, and taking the worst turn gave FAIL.
   - **Fix:** each quarter-turn now gets a two-sided score over all layers (mean edge gap
     plus mean overprint distance). Turns within twice the score's derived sampling bound
     (about 0.171 mm) are ties. Tied turns with different verdicts give UNKNOWN
     ("placement ambiguous").
   - **Result:** the square now PASSes, and the bar case is never PASS.
   - **Controller's decision:** keep this conservative derived window. Nearly symmetric
     parts may be UNKNOWN more often.
2. **Truncated G-code passed.** Confirmed. Coverage now FAILs when the G-code's own layer
   count is outside the allowed set, or when the model continues above the last printed
   Z. `F6.layer_count` also cross-checks the G-code layer count against the statistics.
3. **Commanded Z and G92 offsets were ignored.** Confirmed.
   - Commanded Z is now tracked, and every model extrusion must sit at its layer's
     Z_HEIGHT within a derived rounding tolerance.
   - G92 may set only E; no real file sets X, Y or Z with it.
   - Both of Codex's cases give UNKNOWN.
4. **The extrusion amount was ignored.** Confirmed.
   - The amount of plastic (E) of each segment is now checked against OrcaSlicer
     v2.5.0's own flow model (`Flow::mm3_per_mm`). The filament diameter and flow ratio
     come from the hash-checked profile.
   - **Measured:** written E against the model's prediction has median 1.0000, and
     0.978–1.021 over 99.8% of 58,344 segments.
   - **Tolerance:** derived from the printed precision (X/Y to 3 decimals, E to 5), with
     no new number. Every segment of the 16 real files passes it.
   - **Refused:** M221 other than S100, and M92/M200/M207/M208/M209/M290. Codex's
     near-zero-E and `M221 S0` cases give UNKNOWN.
5. **Acceptance ignored the sampling bound.** Confirmed. A check now PASSes only if the
   sampled maximum plus its bound is within the allowance, FAILs if the sampled maximum
   exceeds it, and is UNKNOWN in between. Codex's 0.44 mm hole case is no longer PASS.
6. **slice_id did not track method changes.** Confirmed. The version is now `slice-3`,
   and the rule is to bump it whenever verdict semantics change, pushed or not.
7. **The bridge controls had not been run through `tdmg slice`.** Confirmed. The new
   `research/verification/2026-11-10-thin-walls/controls_slice.py` → `controls-slice.txt`
   runs them, and the hair cases, through `make_slice` with the real slicer:
   - bridges of 0.15, 0.3 and 0.45 mm FAIL connectivity and coverage;
   - bridges of 0.6 and 1.0 mm PASS all three checks;
   - every hair and spike case FAILs coverage.

**After the fixes:**
- 833 tests pass and 1 is skipped, both plain and with the CI environment variables. The
  real-slicer test passes.
- The owner's Roadie and Oddie still PASS all three F3 checks at 0°, with no tie.
- Slice time rose to 9.8 s for Roadie and 14.2 s for Oddie. The controller accepted this
  as a known cost.
- Codex did not re-review.

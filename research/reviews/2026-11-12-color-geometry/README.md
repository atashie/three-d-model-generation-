# Independent critical review of `tdmg flat --colors` (R2 step 2), 2026-11-12

This is Task 8 of `docs/plans/2026-11-12-color-geometry.md`.

**How the review was run:** with the installed OpenAI Codex CLI (0.167.0):

```
codex exec --sandbox read-only --ephemeral -o review.txt "$(cat prompt.md)"
```

It covered commits `218794d..d209c49`, all of step 2. `prompt.md` is the prompt, and
`review.txt` is Codex's response, verbatim.

**What Codex ran:**
- 457 focused tests and the generated-doc check;
- the four owner plans, in memory;
- `make_flat` and `tdmg colors` byte comparisons against `218794d`, which matched.

It did not run the file-writing integration suite or any other platform.

## Findings and how each was handled

Each finding was checked against the code before it was fixed (CLAUDE.md, Review practice).
Each fix was written as a failing test first.

1. **High: STL bodies in the wrong place could pass every check.**
   - **Verdict: holds.** The per-body `F2.export_matches_geometry` compared only bounds and
     volume. Codex moved the middle of three same-color components 1 mm inside the bounds,
     and every check passed.
   - **Fixed:** the check now cuts the decoded, merged mesh at the mid-height of each
     slab. The cut is an exact triangle–plane intersection, polygonized. Each section must
     equal the body's intended footprint within a derived float64 tolerance, written in the
     docstring.
   - **Tests:** Codex's case now FAILs for an AMS inlay, an AMS base (both heights) and a
     glue piece body. In each, the bounds, volume and F1 still pass, so the new comparison
     is what catches it.
   - **Owner plans:** unchanged, all pass.
2. **Medium: the glue clearance margin assumed a chord bound GEOS does not keep.**
   - **Verdict: holds.** GEOS draws a round join of angle A with round(A/(π/2Q)) chords,
     so one chord can span up to 1.5π/(2Q). Codex's case is a 20 mm polygon with a 16.8°
     concave notch. It gave a gap of 0.197855 mm against a threshold of 0.198071 mm, from
     the normal generator.
   - **Fixed by construction:** a guessed larger margin would not have been sound.
     - **Pieces:** each piece is eroded by its measured shortfall until it clears its
       region's boundary by the clearance (`_clear_of`).
     - **Pocket walls:** each wall is grown until it clears the kept pieces by the
       clearance (`_reach`).
     - **Loops:** both are bounded, with the bound derived in a comment; the measured
       maximum is one round.
     - **Margin:** `F4.glue_fit` keeps only the grid-snap terms and float64 rounding, with
       no chord terms.
   - **Tests:** notch angles from 3° to 80° all pass.
   - **Owner plans:** the smallest gap went from 0.198637–0.198953 mm to
     0.199998–0.200000 mm (`glue.txt`). The fix acted on every plan: the largest shortfalls
     were 1.05e-3 to 1.50e-3 mm, above the old assumed 0.96e-3 mm term.
3. **Low: the clearance rule promised more than the code.**
   - **Verdict: holds.** The rule said the gap was at least 0.2 mm everywhere.
   - **Fixed:** the summary of `color.glue.clearance_mm` now describes a nominal clearance:
     at least this before snapping to the storage grid, and at least this minus the grid
     snaps (a few micrometres) as built, gated by `F4.glue_fit`. Its kind, provenance,
     validation and value are unchanged. `gen_docs.py` was run.
4. **Low: STATUS was stale.**
   - **Verdict: holds.**
   - **Fixed:** in the same commit as these records.

## Also found during this task

- **CI on macOS 15 failed one test:** the first run of step 2, run 43321934118 on
  `d209c49`.
  - **Finding it:** GitHub job logs need a sign-in, so CI now writes failing pytest
    summary lines as public annotations. Run 43323221434 then showed
    `test_a_sub_grid_sliver_is_absorbed_not_a_cell` failing at its precondition: the
    1.1e-16 mm² sliver it relied on does not arise on arm64.
  - **Cause:** GEOS rounds differently on arm64, most likely through fused multiply-add.
  - **Fixed:** the test now builds the sliver exactly, with an apex 2^-49 mm off a grid
    edge.
  - **Scan:** a scan of the color tests found no other assertion that depends on
    rounding-level GEOS results. The exact zeros are exact by construction.
  - **What it shows:** colored geometry is not bit-identical across platforms at the
    rounding level. The same plan can give different STL bytes on the Mac under the same
    `colorflat_id`, since the id identifies the inputs and not the platform. The checks
    gate each platform's own bytes. The environment block in `colored.json` records the
    library versions but not the platform or CPU architecture.
- **Algorithm label:** `colorflat-1` became `colorflat-2`, because the glue outputs
  changed. The owner-plan runs were re-made (`colored-runs.txt`).
- **Not fixed (open):** the single-color `tdmg flat` `F2.export_matches_geometry` has the
  same bounds-and-volume-only design as finding 1.
  - Changing it would change `flat.json` for R1, so it is left for a separate change.
  - R1's real outputs are also gated by `tdmg slice`'s G-code checks.

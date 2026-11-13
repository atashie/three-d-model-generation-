# Independent critical review of multicolor slicing (R2 step 4), 2026-11-13

This is Task 8 of `docs/plans/2026-11-13-color-slicing.md`.

**How the review was run:** with the installed OpenAI Codex CLI (0.167.0):

```
codex exec --sandbox read-only --ephemeral -o review.txt "$(cat prompt.md)"
```

It covered commits `b641a47..6037574`: all of step 4, up to the docs and the prompt.
`prompt.md` is the prompt, and `review.txt` is Codex's response, verbatim.

**What Codex ran:**
- 372 reader and 3MF tests;
- 30 profile-flattening tests;
- in-memory reproductions of each finding.

It did not run the slicers, verify their installs or write temporary files; a swap test
could not start for that reason. It found the current reader gives identical model
segments on both owner R1 G-codes, old and new profile.

## Findings and how each was handled

Each finding was checked against the code before it was fixed (CLAUDE.md, Review
practice). Each fix was written as a failing test first, and each test failed before the
fix.

1. **High: firmware conditionals were read as always executed.**
   - **Verdict: holds.** Codex's three scenarios each PASSed every required color check:
     - an inlay wrapped in `M622 J1` … `M623`;
     - a whole tool change wrapped the same way;
     - G91/M82 before a conditional that sets G90/M83.
   - **Measured first:** what the four owner face-up G-codes and both R1 G-codes hold
     inside conditional blocks (`raw/conditionals-review5.json` in the color-slicing
     record). There are G90/G91/M83/G92 and the start code's calibration extrusions. There
     is never a T command, M620/M621, or a model or prime-tower extrusion.
   - **Fixed** (`07b445a`), for multicolor reading only, so R1 is unchanged:
     - a T command, M620/M621, a FLUSH block, or a model or tower extrusion inside a
       conditional is refused, so the checks are UNKNOWN;
     - conditionals must pair;
     - a mode the block changes is unknown after it.
   - **Deviation from the controller's first instruction:** that instruction refused
     every mode change inside a conditional. The real A1 G-code sets G90/M83 inside
     conditionals to the value they already had, so that rule would make every real file
     UNKNOWN. A mode set to its prior value therefore stays known. The controller
     accepted this.
2. **High: flush plastic was not located.**
   - **Verdict: holds.** Codex moved the flush to X128 Y128 Z0.4, inside the model, and
     every required check passed.
   - **Measured:** all 33 flushes in the four owner face-up G-codes are at (267, 128),
     off the 256 mm plate.
   - **Fixed** (`07b445a`): each FLUSH_START's head position must be known and outside
     the silhouette by more than the tool allowance; otherwise `F6.tool_placement` FAILs
     (or is UNKNOWN when the position is unknown).
   - **2026-11-13 (after review of `07b445a`):** a flush 0.3 mm beside the model passed, though a 27.8 mm purge there lands on it. The rule is now the measured one, with no new number: each FLUSH_START's head X/Y must be known and off the printable plate (the reader's plate bounds, the edge included); on the plate `F6.tool_placement` FAILs, unknown is UNKNOWN. The six owner Task 7 faces are unchanged (`recheck_review5.py`).
3. **Medium: a missing glue plate was not noticed.**
   - **Verdict: holds.** With both glue-piece rows deleted and the glue report intact, the
     run went ahead and the route could be called printable.
   - **Fixed** (`0c720f7`): every color the glue report gives pieces for must have a
     plate row, or the run is refused before anything runs.
4. **Low: warnings asserted an unmeasured cause.**
   - **Verdict: holds.** The dot-inlay fixture and a `G4 X1` (UNKNOWN) case both got
     "printed colors meet edge to edge".
   - **Fixed** (`0c720f7`): each warning keeps its status (FAIL or UNKNOWN). FAIL
     describes what was measured and points to the owner-review record for where colors
     meet; UNKNOWN gives the check's reason.
   - **2026-11-13 (after review of `0c720f7`):** the connectivity FAIL text is now built
     from what each check measured (parts and holes printed against the model, the
     mismatched layers), not a fixed "split into more parts"; the owner-plan pointer is
     kept as a qualified note. Two glue plate rows for one color are refused.
5. **Low: STATUS was out of date.**
   - **Verdict: holds.**
   - **Fixed:** in the same commit as this record.

## Re-checks after the fixes

- **Owner Task 7 G-codes:** the color checks were re-run on all six faces, with no
  re-slice. Every status and value equals its `slice.json`
  (`raw/recheck-review5.txt`).
- **Task 2 cross-check:** unchanged apart from run times and the verdict column. The
  verdict column changed with the owner's Task 7 gating, not with these fixes.
- **R1:** the slice5c G-codes give the same F3 results.

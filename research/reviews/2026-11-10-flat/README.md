# Independent review of `tdmg flat`, 2026-11-10

I ran the installed OpenAI Codex CLI (0.167.0) with `codex exec --sandbox read-only
--ephemeral` on commits `94df84a..a3f1978`. Its full response is in
[review.txt](review.txt). Codex ran in-memory probes, but its read-only sandbox blocked
the test suite.

Before this, each task passed a subagent spec review and a code-quality review. I
checked every finding below against the code or docs before handling it.

1. **The size checks judged polygons, not the written mesh.** Confirmed. Fixed in
   `f2367af` with a new check, `F2.export_matches_geometry`. It compares the bounds of
   the reloaded STL, its z range and its volume with the cleaned geometry, using
   tolerances derived from float32. Tests cover scaled, shifted, squashed and notched
   meshes.
2. **Collapse at the opening width.** Confirmed and measured. Features up to the width
   plus about 0.005% of it are removed: 2e-5 mm at 0.4 mm. The same holds for the
   thin-region measure. The behaviour is documented and pinned by tests. The algorithm
   is unchanged, because the margin is far below printer resolution.
3. **The selection record was trusted without checking.** Confirmed. `make_flat` now
   checks the schema and required fields, recomputes the `selection_id` with the shared
   `selection.selection_identity`, and refuses on a mismatch. The test cases include an
   empty ID and edited instructions with an old ID.
4. **Exit 2 overpromised "nothing written".** Confirmed for I/O failures in the middle
   of a write. The help and docstrings now say that a folder without `flat.json` is
   incomplete.
5. **"Removed as unprintable" overstated hypothesis rules.** Confirmed. The wording now
   cites the cleaning rules as untested hypotheses, in the code, the guide and the plan.
6. **STATUS.md was stale.** Confirmed. It is updated.
7. **`WIDTH_RTOL` was not explained.** Fixed with a derivation in the comment: a
   floating-point margin for an equality the code computes, not a physical tolerance.

**After the fixes:**
- 468 tests pass, both plain and with the CI environment variables, and ruff is clean.
- Re-runs on the owner's selections pass the new export check and are byte-identical
  to the earlier runs.
- Codex did not re-review the fixes.

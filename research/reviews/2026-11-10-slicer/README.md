# Independent review of the slicer check, 2026-11-10

I ran the installed OpenAI Codex CLI (0.167.0) with `codex exec --sandbox read-only
--ephemeral` on commits `b3f285e..e667259`. The full response is in
[review.txt](review.txt). Codex confirmed the local zip and app-tree hashes, the output
hashes, the record links, the slice IDs and the normalised G-code repeatability. Its
read-only sandbox blocked the test suite.

Before this, the work had subagent spec and quality reviews, and fixes after each.
Every finding below was checked against the code or docs before it was handled.

1. **The research scripts could delete unrelated data (High).** Confirmed by reading
   the code. `measure_orca.py` and `measure_more.py` now refuse an existing non-empty
   folder. Tried with `.`: it was refused. A dated note in the research record says so.
2. **The half-layer tolerance ignored STL float32 storage.** Confirmed: 100.099999 and
   100.100001 mm give identical STL bytes but expected 500 and 501 layers. Fixed in
   `426cd2b`. The expected layer counts now come from the z extent of the STL as
   stored, and the half-layer window is widened by a derived float32 storage bound.
   Both thicknesses now give {500, 501}, and 3.0 mm still gives {15}.
3. **A rejected exit-0 slice kept the `plate_1.gcode` name.** Confirmed. Fixed in
   `426cd2b`: any required FAIL quarantines the G-code as `plate_1.gcode.failed`, with
   `gcode.quarantined` in the record. The guide's wording now matches.
4. **The runtime check did not cover the whole installed tool.** Confirmed: a replaced
   auxiliary DLL passed `locate`. Fixed in `426cd2b`.
   - `tdmg slice` now verifies the full app tree on every run, which costs about 2.5 s.
   - `--skip-tree-check` records `app_tree_verified: false`, and the slice ID changes
     with it.
   - The millisecond gap between checking and running remains, and is documented.
5. **STATUS and the guide contradicted themselves.** Confirmed. Both are corrected.

**Remaining limits, as Codex states them:**
- edited check statuses in `flat.json` are pinned by hash but not refused;
- an F6 PASS shows only the exit status, non-empty output, the layer count and the
  object count, not intact geometry or printability (F1 covers geometry);
- portability stays UNKNOWN.

**After the fixes:**
- 682 tests pass and 1 is skipped, both plain and with the CI environment variables.
- The real-slicer integration test passes locally.
- Codex did not re-review.

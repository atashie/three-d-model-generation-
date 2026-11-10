# Independent review of outline smoothing, 2026-11-10

I ran the installed OpenAI Codex CLI (0.167.0) with `codex exec --sandbox read-only
--ephemeral` on commits `8d66458..d757132`. The full response is in
[review.txt](review.txt). Codex ran in-memory probes, including two fresh processes. Its
read-only sandbox blocked the full test suite.

Before this, the work had subagent spec and quality reviews, and the warning design had
been revised once. Every finding below was checked against the code or docs before it
was handled.

1. **The Hausdorff accuracy claim was worded for the wrong quantity.** Confirmed: a
   filled 3 × 3 hole reported 0.883 mm, while the hole's centre is more than 9 mm from
   the smoothed boundary. Handled in `070b1f2`:
   - the helper is now described as a boundary-to-region distance: a lower bound on the
     region Hausdorff distance, and not the boundary-to-boundary distance;
   - the smoothing key is renamed `hausdorff_lower_bound_px`;
   - the CLI says "outline changed by at least X mm (sampled; boundary-to-region)";
   - Codex's case is a test.
2. **Offsetting topology changes escaped the totals.** Confirmed with Codex's case: a
   merge plus a split left 3 parts and 0 holes. Fixed in `070b1f2`. Warnings now come
   from part-to-part correspondence: overlap with positive area, then counting
   disappeared, appeared, split and merged parts, and holes closed or opened per
   one-to-one pair. Merge, split and offsetting holes are tested. The limitation for an
   attached appendage removed without a topology change is still documented.
3. **The verification record treated a lower bound as a maximum.** Confirmed. A
   same-day correction note now sits under the "agree to within 0.187 px" line; the
   measurement is unchanged.
4. **The G1 page still described the exact outline as the default.** Confirmed. The
   failure-mode row and the decisions now say that the exact outline is
   `--smooth-px 0`, that the default is smoothed, and that the transform uses the
   bounding box of the outline actually used.

**After the fixes:**
- 550 tests pass, both plain and with the CI environment variables.
- The owner's selections still give no warnings, and their geometry is unchanged.
- Codex did not re-review.

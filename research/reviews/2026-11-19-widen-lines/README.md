# Independent review of the built widen-lines feature, 2026-11-19

Change: `git diff b23af64..4415fdb` (plan `docs/plans/2026-11-19-widen-lines.md`, Tasks 1
to 5, against the design `docs/plans/2026-11-19-widen-lines-design.md`).

**How the reviews were run:** OpenAI Codex CLI 0.167.0,
`codex exec --sandbox read-only --ephemeral -C <repo> -o <out> "$(cat <prompt>)" < /dev/null`.
There were three rounds, each on the fixes of the round before:

| Round | Prompt | Response (verbatim) | Reviewed |
|---|---|---|---|
| 1 | `prompt.md` | `codex-review.txt` | `b23af64..4415fdb` |
| 2 | `prompt-fixes.md` | `codex-review-fixes.txt` | the round 1 fixes (uncommitted, on 79dcd14) |
| 3 | `prompt-fixes2.md` | `codex-review-fixes2.txt` | the round 2 fixes (uncommitted, on 79dcd14) |

A first attempt at round 1 waited on standard input and did nothing; it was stopped and
run again with `< /dev/null`. Codex ran read-only tests and in-memory reproductions in
each round; it ran no slicer and no `library verify`.

## How the findings were checked

Each finding was checked by a test written to reproduce it before any fix. For round 1, a
Claude subagent wrote every reproduction outside the repo first and reported a verdict per
finding; the implementer (another Claude subagent) then moved each into `tests/`, saw it
fail, fixed the code and saw it pass. A separate Claude reviewer checked the fixes against
the findings (spec review, three passes) and another the code quality (two passes); their
points are in the table as "spec" and "quality". After every round: the full suite, `ruff`,
and `tdmg library verify roadie-drop` (identical to the historical run, exit 0).

## Findings and handling

| # | Severity | Finding | Reproduced by | Handling |
|---|---|---|---|---|
| 1.1 | High | A closed line can open on redraw: extra bridges were limited to the tree's longest bridge, so a ring's closing gap (its longest) was dropped | `test_a_varying_width_ring_stays_closed` (Codex's ring) | Fixed: ridge pieces are joined in `find_lines` by a spanning tree plus loop-closing bridges, each tested inside the line's own mask. Spec review added rings in one or two pieces, thin rings and the search speed on nets (`test_bridged_closes_a_ring_in_one_or_two_pieces`, `test_a_thin_ring_found_and_drawn_stays_closed`, `test_a_closing_run_may_cut_a_corner_by_one_half_pixel`, `test_grid_timing`, `test_closing_equals_the_whole_graph_form`); quality review added tests that can fail (`test_a_closing_bridge_past_a_third_piece_is_refused`, the straight-line test with a hole) |
| 1.2 | Medium | The line width used the plan's scale, not the model's (0.41 mm measured 0.72 mm) | `test_a_line_is_drawn_at_line_width_mm_on_the_models_scale` | Fixed for lines: `colored_flat` draws at `line_width_mm / scale_mm_per_px` of the model. The kept outline band and cleanup's opening have the same mismatch from before this feature; left for the owner (STATUS) |
| 1.3 | Medium | `drawn: true` for a line the kept outline band covers (0 pixels painted) | `test_a_line_the_kept_band_covers_is_recorded_not_drawn` | Fixed: a line is drawn only if it paints a pixel; otherwise `drawn: false` with a reason; the legend and the glue decision follow |
| 1.4 | Medium | An explicit `thin_lines: remove` changes `config_sha256` | Subagent test (scratchpad) | Not a defect: explicit defaults already set `config_sha256` before (for example `outline_color: auto`); `colors_id` is unchanged; old records verify identical. Codex accepted this in round 2 and asked for exact wording (2.6) |
| 1.5 | Medium | Changing only the unused default `color.lines.width` breaks an unchanged widen record | `test_an_explicit_line_width_survives_a_change_to_the_unused_default` | Fixed: `color.lines.width` is no longer in the lines block's rules (the width is `settings.line_width_mm`) |
| 1.6 | Medium | Remove mode checks the unused line width against the opening | `test_remove_does_not_compare_the_unused_line_width_with_the_opening` | Fixed: checked only when widening |
| 1.7 | Low | Software measurements labelled `validation: untested` | (read) | Not changed: `tests/test_rules.py` requires every hypothesis's evidence to be `untested`, and every hypothesis in the registry follows it. Whether hypothesis evidence may be `measured` is a repo-wide question for the owner (STATUS). Codex repeated it in rounds 2 and 3 (2.5, 3.2) |
| 2.1 | High | An opening was closed when another loop is in the same line (the hole check was global) | `test_an_open_loop_beside_a_closed_one_stays_open` (Codex's two rectangles) | Fixed: a per-bridge topology check; generalised in 3.1 |
| 2.2 | Medium | A line clipped away with the silhouette counted as in the model, without a warning | `test_a_recorded_line_that_is_not_in_the_model_is_warned_about` (Codex's projection, no mock) | Fixed: presence is decided from the final cells after clipping; `LINES_NOT_PAINTED` warns and the glue route is built |
| 2.3 | Medium | The line method changed but kept its version, so different plans shared an identity | "method 1" case in `test_verify_colors_checks_the_lines` | Fixed: `inside-one-color-lines/2`; verify refuses a `/1` widen record. Remove identities are unchanged |
| 2.4 | Medium | The ridge constants are thresholds outside `rules/` (CLAUDE.md rule 2); a comment overstated the path factor | `test_closing_params_from_the_rules`, `test_closing_params_refuses_bad_values` | Fixed: `color.lines.loop_path_factor`, `run_tolerance`, `close_reach` and `ridge_smooth` are hypotheses in `rules/color.yaml`, with evidence in the research README's addendum, in the widen identity only; the comment is corrected |
| 2.5 | Low | = 1.7 | | Deferred to the owner |
| 2.6 | Low | The design doc promised byte identity for every remove plan | `test_no_thin_lines_key_runs_no_line_code_and_gives_the_same_bytes` | Fixed: the design doc says byte-identical with no `thin_lines` key; an explicit `remove` keeps `colors_id` and settings but records its config's hash |
| 3.1 | High | Nested loops: a bridge could split an existing hole, closing an inner opening | `test_a_bridge_never_splits_a_hole` (Codex's nested rectangles, and a both-closed case) | Fixed: the mask's complement is split into its parts (the outside and each hole); a bridge is refused if it splits any part, so it may only separate two parts (restore a hole). Pixels within the run tolerance of the line are not counted, so a tolerated corner cut does not count as a split (the `color.lines.run_tolerance` note says so) |
| 3.2 | Low | = 1.7 | | Deferred to the owner |

Codex checked in round 3 and found correct: the clipping check, the `/1` refusal, the six
rule values in the widen identity only, unit conversion, and the remove-mode bytes against
HEAD. Its last review ran before the 3.1 fix; that fix was checked by its tests, the full
suite and `library verify roadie-drop`, and is to be reviewed with plan Task 5b.

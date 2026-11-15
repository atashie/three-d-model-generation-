# Independent critical review of the test strips (R2 step 5, part 1), 2026-11-14

This is Task 4 of `docs/plans/2026-11-14-test-strip.md`.

**How the review was run:** with the installed OpenAI Codex CLI (0.167.0), from this
folder:

```
codex exec --sandbox read-only --ephemeral -o review.txt "$(cat prompt.md)"
```

It covered commits `192ae40..44ba27d`: all of step 5, part 1, up to the Task 3 review
fixes. `prompt.md` is the prompt, and `review.txt` is Codex's response, verbatim.

**What Codex ran** (its own report, in `review.txt`):
- 47 selected tests, with `.venv/Scripts/python.exe -B -m pytest -s -p no:cacheprovider`
  (default capture failed first: no writable temporary folder in the sandbox);
- in-memory reproductions of findings 1 to 5 (an injected record through the CLI;
  synthetic G-code from `tests/gcode_fixtures.py` through `f3_checks` and the color
  checks; midpoint sampling of the white mesh);
- a byte comparison of `palette_manifest(colorflat_id=...)` against the code before the
  change: identical.

It did not run the full file-writing suite, the real slicer, Bambu Studio or any print.
Findings 6 and 7 are by reading and reasoning only. It found no change to a shared
default (`tdmg slice`, `tdmg flat`).

## Findings and how each was handled

Each finding was checked against the code before anything was changed (CLAUDE.md, Review
practice). Each fix was written as a failing test first, and each test failed before the
fix. The first fixes are in commit `33c1f31`; the prompt and `review.txt` are in `30dc746`.
The owner's decisions on findings 2, 3, 4 and 6 (2026-11-14) are in the commit after
`c032c1c`, "Calibration strips: the owner's decisions on the Codex review".
The owner's decisions are kept: the base plate stays NOT CERTIFIED and is printed
anyway, the skin strip runs along y, and the gaps and depths are unchanged. No rule value
changed.

1. **High: the accepted-failure note also covered the pieces plate.**
   - **Verdict: holds.** `known_failures` accepted the counted kind of
     `F3.printed_connectivity` FAIL on any part. A pieces-plate FAIL (six model parts,
     seven printed) got the note, alone or with the base plate's, and `tdmg strip`
     exited 0 and told the owner they had decided to print the pieces plate anyway. The
     owner's decision covers the base plate only.
   - **Fixed:** `KNOWN_FAILURE_PARTS = {"base"}`; a failing part outside it gets no
     note, so the FAIL blocks (exit 1). The decision text now names the base plate.
     Tests: `test_the_note_covers_the_clearance_base_plate_only`,
     `test_a_pieces_plate_connectivity_fail_is_not_covered` (both cases failed before).
2. **High: "extra parts" does not show that the failure is the accepted infill islands.**
   - **Verdict: holds.** `_extra_parts_only` reads part and hole counts only. The printed
     layer record has no part areas or places. A crack that splits the plate in two
     gives the same counts (1 model part, 2 printed, holes equal) and the same match
     result as an island, so it gets the note, and the terminal called it "small loose
     bits of infill".
   - **Fixed, in part:** what is said now matches what is measured. The note carries
     `limit` (`KNOWN_FAILURE_LIMIT`: counts only, a split part gets the note too). The
     terminal says "more printed parts than in the model" for this run, then "On
     2026-11-14 these were small loose bits of infill …" and "This run's parts are
     counted, not sized". Tests: `test_the_note_says_it_counts_parts_and_does_not_size_them`,
     `test_cli_strip_accepted_base_failure_exits_0`.
   - **Not fixed, for the controller and the owner:** telling an island from a split
     needs the extra parts' areas or places, which `tdmg.printed` does not record, and a
     limit on their size, which would be a new number with evidence in `rules/`. That is
     a rule and design decision, so it was not made here.
   - **Owner decision (2026-11-14): "Not now".** No sizing. The limit stays stated in the
     note and the terminal.
3. **High: a whole white patch can be missing while every required skin check passes.**
   - **Verdict: holds as a gap; by the plan's policy.** The skin face is gated "Outer edge
     only" (the owner's decision of 2026-11-13, applied to the strip in the plan's Task 2
     amendment): the white tool's `F3.edge_coverage.T1` and the connectivity checks are
     warnings. The other patches keep the white tool in use, so `F6.filaments_used` and
     `F6.color_changes` still pass. `tdmg strip` did not print the warnings.
   - **Fixed, in part:** `tdmg strip` now prints each skin warning and, when there is
     one, a line to check the strip in Bambu Studio's preview (first worded "… that every
     white patch is printed"; reworded once the white checks were required). Tests:
     `test_cli_strip_shows_the_skin_faces_warnings`,
     `test_cli_strip_prints_no_skin_warning_line_without_warnings`.
   - **Not changed at first, for the controller and the owner:** making the white tool's
     coverage and connectivity required for the strip would change how the owner's "Outer
     edge only" decision applies. In the real run of 2026-11-14 every warning PASSed.
   - **Owner decision (2026-11-14): "Require it for the strip".** For the skin strip only,
     `F3.edge_coverage.T1` and `F3.printed_connectivity.T1` (the white tool) are required
     (`SKIN_WHITE_REQUIRED`); their notes say so, and they are no longer listed as
     warnings. The black tool's checks and the whole model's connectivity stay warnings.
     Owner plans keep "Outer edge only": `color_gcode.required_check_ids` and
     `color_slicing.slice_face` are unchanged. The algorithm label is now `strip-3`.
     Tests first: `test_the_white_tools_coverage_and_connectivity_are_required_for_the_skin`,
     `test_a_white_tool_fail_blocks_the_skin_strip` (both checks: NOT CERTIFIED,
     quarantined, exit 1), `test_the_white_tools_checks_say_they_are_required`,
     `test_a_black_tool_coverage_fail_stays_a_warning`; the real-slicer test now asserts
     both checks required and PASS. Real run: the skin strip is still PRINTABLE.
4. **Medium: "the row runs left to right" cannot see a row turned half a turn.**
   - **Verdict: holds.** The pieces look alike; a row turned 180° still runs left to
     right, in reverse gap order. Codex did not show that Bambu Studio turns it; the
     defect is that the check given to the owner cannot catch it.
   - **Fixed (the form and the command):** do not move, turn or arrange the pieces; a row
     turned half a turn is in reverse order, so check it is not turned at all; mark
     piece 1 (the end that was at the left in Bambu Studio) before taking the pieces off
     the plate. The command points to the form. Test:
     `test_the_results_template_guards_the_piece_order_seating_and_light`.
   - **Open, for the owner:** a physical mark on each piece (a geometry change) would
     remove the reliance on order; not made, as it changes the layout.
   - **Owner decision (2026-11-14): "Pen mark is enough".** No change.
5. **Medium: the form did not record the print settings that decide the result.**
   - **Verdict: holds.** The white depths (0.2 to 1.0 mm by 0.2) are whole layers at the
     checked 0.2 mm layer height, not at every height (Codex's sampling: at 0.3 mm layers
     the five depths print as 0.3, 0.3, 0.6, 0.9, 0.9 mm), and
     the fit depends on the pieces' first layer. The form recorded neither, and did not
     say to seat the piece before judging.
   - **Fixed:** `strip.json` has `print_settings` (from the pinned process profile: the
     preset name, layer height, first layer height, elephant foot compensation). The form
     has a "Print settings" section that gives them, says to print with them, and asks
     for the ones used and the Bambu Studio project file. It says to put each piece in
     bed side down and press it onto the pocket floor before judging. Tests:
     `test_the_results_template_records_the_print_settings`,
     `test_the_results_template_guards_the_piece_order_seating_and_light`.
6. **Medium: "falls out when turned over" is not a measure of excess clearance.**
   - **Verdict: a fair point, not changed.** The definition "drops in, loose (it rattles
     or falls out when turned over)" is Decision 5's, which the owner approved. Changing
     how the fit is judged is the owner's choice. Reported to the controller.
   - **Owner decision (2026-11-14): "Judge it in three steps".** The form now records, per
     piece: (a) goes in: won't go in, pressed in or drops in; (b) sits flat on the pocket
     floor: yes or no; (c) side-to-side play: none, a little or a lot. "Falls out when
     turned over" is gone (`CLEARANCE_STEPS`; plan Decision 5 amendment). How the value
     is chosen from the three answers is the owner's choice at Task 5. Test first:
     `test_the_results_template_has_a_row_per_gap_and_patch`.
7. **Medium: "room light" leaves backlighting open.**
   - **Verdict: holds.** Held up to a window or lamp, light through the full-white
     reference makes it look whiter than the patches over black.
   - **Fixed (the form):** lay the strip flat, top face up, lit from the front or above;
     judge it lying down, not held up to a window or a lamp. "Under room light" and the
     two reference patches (Decision 5) are kept. Test:
     `test_the_results_template_guards_the_piece_order_seating_and_light`.

## Re-checks after the fixes

See `research/verification/2026-11-14-test-strips/README.md`, section 5, for the full
suite, ruff, the real-slicer strip test and one real `tdmg strip` run after the fixes.

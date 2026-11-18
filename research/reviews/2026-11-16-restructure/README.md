# Independent review of the built restructure, 2026-11-17

Change: `git diff pre-restructure..14e92b7` (plan `docs/plans/2026-11-16-restructure.md`,
Tasks 0 to 14, and the Task 15 docs). Plan Task 15 asks for a Codex review "handled as
before" (CLAUDE.md, Review practice).

**How the review was run:** OpenAI Codex CLI 0.167.0,
`codex exec --sandbox read-only --ephemeral -C <repo> -o codex-review.txt "$(cat prompt.md)"`.
Prompt in `prompt.md`; response verbatim in `codex-review.txt`. Codex ran
`library check roadie-drop` and 19 pytest cases, plus in-memory probes; its broader
test runs failed in the read-only sandbox (no writable temporary folder), as it says.

## How the findings were checked

Each finding was first checked by reading the code it names (findings 1, 2, 4, 7 and
10 by Claude on 2026-11-17), then by a test written to reproduce it before any fix: the
implementer (a Claude subagent) wrote each test, ran it and saw it fail, then fixed the
code and saw it pass. A separate Claude reviewer then checked each fix against the
finding (spec review), and another the code quality. Every finding reproduced; none was
rejected.

## Findings and handling

| # | Severity | Finding | Reproduced by | Handling |
|---|---|---|---|---|
| 1 | High | The check before a resumed purge was weaker than `library check` (no STAGED) | `test_a_resumed_purge_uses_library_checks_full_validator` | Fixed: every deletion path runs `check_entry`, `library check`'s own validator, and refuses a missing `source/` or `private/` |
| 2 | High | Library records not bound to each other (empty covers passed; confirmation not compared with `job.yaml`; blank purge words; resume ignored other words) | `test_records_that_contradict_each_other_are_damage` (6 cases, including Codex's swapped-model probe), `test_blank_purge_words_are_damage`, `test_a_print_confirmation_stale_at_finish_is_damage`, `..._refuses_different_purge_words` | Fixed: `_record_problems` binds confirmation, covers, printable files, folder and public answer; blank words are damage; once `COMPLETE` is written a resume with other words refuses |
| 3 | High | A custom `--prints-dir` or `--jobs-dir` inside the checkout could put the source or private files where git does not ignore them | `test_finish_refuses_a_prints_folder_git_does_not_ignore`, `test_job_new_refuses_a_jobs_folder_git_does_not_ignore`, a `set_mask` test | Fixed: `git check-ignore` on the actual destination paths before any copy (finish, `job new`, `set_mask`) |
| 4 | Medium | A leftover staging folder was deleted before the job's eligibility was checked | `test_a_staging_leftover_is_kept_when_the_job_is_not_ready`, `test_a_staging_folder_with_unexpected_files_is_not_removed` | Fixed: eligibility first; only names finish itself writes are removed, anything else refuses |
| 5 | Medium | Status ignored a changed source; a cached stage with missing or changed outputs stayed current | `test_status_reports_a_changed_or_missing_source`, `test_a_missing_or_changed_output_makes_its_stage_stale` | Fixed: status checks the source; every record's `outputs` hashes are checked |
| 6 | Medium | Input keys had no code fingerprint, so changed code reused old results | `test_the_code_fingerprint_is_part_of_every_key` | Fixed: `tdmg.jobkey/3` adds a SHA-256 of tdmg's `.py` files and `uv.lock`; recorded in `provenance.json`. Limits: bytes on disk (line endings count), packages outside `uv.lock` not seen |
| 7 | Medium | A literal `<timestamp>` G-code line hashed like a masked one; missing masked hashes compared less, silently | `test_a_literal_timestamp_marker_is_not_a_timestamp`, `test_verify_without_masked_slice_hashes_is_incomplete` | Fixed: such a line is escaped (no other file's digest changes; `prints/roadie-drop` still verifies identical); missing hashes are an incomplete comparison, exit 1 |
| 8 | Medium | Owner words through `job set` YAML double quotes lost backslashes (`\n`, `\t`) | `test_set_text_*`, including a real `python -m tdmg.cli` subprocess | Fixed: `tdmg job set NAME --text STAGE.KEY 'WORDS'` stores the words exactly; the skill uses it |
| 9 | Medium | A misrecorded confirmation could only be followed by another; the wrong words stayed current and were copied into provenance | `test_a_correction_*`, `test_a_corrected_confirmation_is_not_copied_into_provenance` | Fixed: `job confirm --corrects N`; the corrected entry is kept verbatim, never current, never copied as the owner's words |
| 10 | Low | Docs: STATUS named the deleted legacy Roadie path; the design said strips run as jobs; the skill said the PrusaSlicer folder is in the key | (read) | Fixed: STATUS points to `prints/roadie-drop/files/model.3mf`; a dated amendment in the design; the skill describes the key correctly |

Codex's test-gap list is answered by the tests named above; the lifecycle tests still
use fake slicers, and the real-slicer path is the one recorded finish
(`research/verification/2026-11-17-first-finish/`).

## The quality review of the fixes

Verdict: approved after two Important items, both fixed: `check_source` let an
`OSError` escape `tdmg job status` as a traceback (now a plain message, with a test),
and a fingerprint test's rename assertion compared the wrong pair. Most minor items
were fixed (duplicated checks, one shared git helper and timeout, notes joined rather
than replaced, tests for two `corrects` cases). Deferred, as not worth the change at
today's sizes:
- `unignored_paths` starts one git process per path; a glue job with many plates would
  start many.
- `job status` hashes every stage output on each call; heavy only for large G-code.
- One damaged entry can give two or three overlapping messages in `library check`.

## Owner-facing changes

- Any edit to a tdmg `.py` file or `uv.lock` makes every job stage stale; the next
  `job run` redoes them, and confirmations stay current when the bytes are the same.
- A resumed `finish` after `COMPLETE` must be given the purge words already recorded.
- Owner words go into `job set` with `--text`; a wrong confirmation is corrected with
  `job confirm --corrects N`.

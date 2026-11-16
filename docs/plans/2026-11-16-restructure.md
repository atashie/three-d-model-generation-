# Repository restructure: implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task by task (implementer, then spec review, then quality review,
> per task).

**Goal:** jobs, a library of finished prints and a guarded purge, with today's
research records moved intact into `docs/evidence/`, as designed in
`docs/plans/2026-11-16-restructure-design.md` (draft 2, approved by the owner on
2026-11-16: "proceed with draft 2").

**Architecture:** no package split (design decision 8). New modules `tdmg.jobs`
(job.yaml, stage runner, confirmations) and `tdmg.library` (`finish`, provenance,
card, `library check` and `verify`). The recipe registry gains stages, outputs and
classes. Existing stage commands and algorithms are unchanged, except the strip's
record paths (Task 3).

**Tech stack:** Python 3.13, typer, PyYAML (already a dependency for rules), pytest,
the fake slicers in `tests/fake_orca.py` and `tests/fake_prusa.py`. Nothing new.

---

## Facts this plan relies on (checked 2026-11-16)

- **What was printed:** `artifacts/colored-runs/roadie-tol30-60-drop-v3-f64/model.3mf`,
  SHA-256 `ec2961184e1b235fb4f051c00824095f9642128a565a829e4f1527b1a4f822d7`, written
  2026-11-13 08:05. Record: `research/verification/2026-11-15-first-ams-print/README.md`
  lines 6 and 47.
- **Stage entry points:**
  - `tdmg.selection.select_subject` / `select_from_mask`;
  - `tdmg.flat.make_flat`;
  - `tdmg.colors.make_colors`;
  - `tdmg.colored_flat.make_colored_flat`;
  - `tdmg.slicing.make_slice`;
  - `tdmg.color_slicing.make_color_slice`;
  - `tdmg.calibration_strip.make_strips`.
- **Output folders:** each stage writes into a new or empty folder, with its record
  written last (`tdmg.records`). A folder without its record is incomplete.
- **Code that reads research files:**
  - 13 test files;
  - `profiles/slicers/*.yaml` (`record` paths);
  - `scripts/setup_orcaslicer.py`;
  - `calibration_strip.SOURCE` (`docs/plans/2026-11-14-test-strip.md`) and
    `KNOWN_FAILURE_CAUSE`.
- **`tests/conftest.py`** reads `research/verification/2026-11-11-color-palette/` and
  `artifacts/selection-runs/<name>/`.

## Clarification of the design (made while planning)

A `print` confirmation is bound to:
- the printable file's SHA-256;
- the face;
- the slice record's **identity** (`colorslice_id` or `slice_id`), not its bytes.

The reason is that slice records carry G-code hashes, and G-code holds timestamps (the
strip record shows repeat runs differ). Task 0 measures exactly which fields differ.

## Tasks

Each task: tests first where code changes, then implement, then the full suite
(`uv run pytest -q`), `uv run ruff check .`, and `uv run python scripts/gen_docs.py
--check`. Commit per task.

### Task 0: repeatability baseline

**Steps:**
- Add `scripts/repeat_runs.py`. From the recorded inputs, it runs today's pipeline twice
  into two fresh scratch folders, with the pinned slicers:
  - both R1 models (select, flat, slice);
  - the four owner color plans (select, colors with their configs in
    `artifacts/colors-runs/configs/`, colored flat, slice with `--face auto`);
  - the strip.

  The selection controls come from each `selection.json`.
- For every output file, it reports byte-identical or not. For each JSON record that
  differs, it lists the JSON paths that differ.
- Record the output in `research/verification/2026-11-16-repeatability/README.md`, with
  the command, the machine and the date.

**Result:** a list of fields, each named with its reason (for example
`gcode_sha256`: G-code timestamps). The rebuild proof (Task 9) may ignore these fields
and no others. They go into `tdmg.library.VOLATILE_FIELDS`, with the record cited
beside the constant.

**Also check:** the rebuilt Roadie drop `model.3mf` against `ec296118…`. Report the
result; do not act on it (Task 14 does).

### Task 1: evidence inventory

**Steps:**
- Add `scripts/evidence_inventory.py`. It lists every tracked reference to
  `research/`, `docs/plans/`, `reports/` and `research_notes/`, by referring file and
  line, grouped by record folder (or plan file).
- Add `tests/test_evidence_inventory.py`, run on a small temporary tree: it finds a YAML
  ref, a Markdown link, a Python string constant and a profile `record`.
- Commit the inventory output as `docs/design/evidence-inventory.md`, generated. Mark
  each record folder as **cited** (by a rule, test, profile, code, script or CI) or
  **uncited** (only docs, STATUS or other records point at it).

**Owner check:** show the owner the cited and uncited lists before Task 3 deletes
anything.

### Owner decisions after Task 1 (2026-11-16)

The owner read the inventory (`docs/design/evidence-inventory.md`: 41 of 50 records
cited, 9 uncited) and decided:
- "Remove 5, keep pc-stack (Recommended)": remove `research/reviews/2026-11-10-flat`,
  `-selection`, `-slicer`, `-smoothing` and `research/verification/2026-11-10-flat-geometry`;
  keep `research/verification/2026-11-09-pc-stack` (README and
  `docs/reference/dependencies.md` cite it).
- "Leave them in place (Recommended)": cited records stay at their current paths under
  `research/`, which becomes the evidence folder. There is no `docs/evidence/`, no
  reference rewriting and no strip id change. Links inside kept records to removed
  records stay as written, pointing at git history.

Tasks 2 and 3 below replace the earlier text (which moved records to `docs/evidence/`).
Later tasks that said `docs/evidence/` now mean `research/verification/`.

### Task 2: tag, and paths beside name citations

**Steps:**
- Tag `pre-restructure` at the commit before this task, and push the tag.
- Every review cited only by name in code or tests ("Codex review 3", "Codex review
  2026-11-11, finding 1", "(Codex, 2026-11-09)", ...; the inventory's "cited by name"
  and "possibly cited" lists) gets the record's path written beside it, e.g. "Codex
  review 3 (research/reviews/2026-11-12-color-geometry)". Resolve the ambiguous dates
  from the evidence the inventory gives (2026-11-09: the forum URL is only in
  `2026-11-09-codex/phase0.md`; 2026-11-11: portability; 2026-11-16: face-down), each
  checked by reading the record.
- **Only comments, docstrings and test text that no record stores may change.** A
  citation inside a string that goes into a record (check text, notes) is left as it
  is and listed in the commit message; changing it would change record bytes.
- Then remove `NAME_ALIASES` and its STATUS-based justifications from
  `scripts/evidence_inventory.py` if no citation still depends on them (the regenerated
  inventory must show the same records cited, now by path); otherwise keep the entries
  still needed, with a justification in a durable file.

**Checks:** the regenerated inventory has the same cited set; full suite, ruff,
`gen_docs --check`, the inventory's `--check`; `scripts/repeat_runs.py --compare-only`
is not needed (no code behaviour changes), but `git diff` must show only comments,
docstrings and non-recorded test strings.

### Task 3: design notes, remove five records, rule 6, STATUS

**Steps:**
- **Write the design notes.** Create `docs/design/README.md` (index) and
  `docs/design/selection.md`, `docs/design/flat.md`, `docs/design/color.md`,
  `docs/design/slicing.md` and `docs/design/calibration.md`. Each note holds:
  - the decisions still in force, with the owner's words and dates;
  - review findings that still constrain the code;
  - links to the records in `research/` and the plans in `docs/plans/`;
  - for each removed record, the old path and the removing commit.

  Sources: the five records to remove, the plans and reviews, and STATUS's history.
- **Check them.** A subagent reviews each note against the records it replaces,
  looking for a dropped decision or a changed meaning.
- **Remove the five records** (`git rm`). Re-point any doc link to them (README, docs/,
  STATUS) to the design note; links inside kept records stay as written.
- **`research/README.md`:** what the folder is (the evidence: records that rules,
  tests, profiles, code or docs cite, kept intact), that links inside records may name
  removed paths (see tag `pre-restructure` and git history), and the five removed
  records with their removing commit.
- **CLAUDE.md rule 6:** "Records are evidence. A record that a rule, test, profile,
  code or doc cites is kept intact where it is; it is never rewritten. Job working
  data is deleted only by `tdmg finish`. A record nothing cites may leave the working
  tree once its work is done, after its standing decisions are in `docs/design/`; git
  history keeps it. Do not rewrite `research_notes/`; correct `reports/` only with a
  revision-history entry."
- **STATUS.md:** current state only; its history goes to the design notes.
- **README:** the layout table.
- **PLAN.md section 5:** a dated note that the layout changed, pointing to the design.
- **Design:** an amendment note in `docs/plans/2026-11-16-restructure-design.md`
  recording the two decisions above.
- **Docs test:** `tests/test_docs.py` checks that every `docs/design/*.md` is linked
  from `docs/design/README.md`.
- Regenerate the inventory.

### Task 4: the recipe registry

**Steps:**
- `Status.IN_PROGRESS = "in progress"`. R1 and R2 move to it.
- Add `Recipe.stages`, a tuple of stage names:
  - R1: `select`, `flat`, `slice`;
  - R2: `select`, `colors`, `colored_flat`, `slice`.
- Add `Recipe.outputs`, the required library files by route:
  - R1: `model.stl`;
  - R2 AMS: `model.3mf`, `palette.json`;
  - R2 glue: the `glue-*.stl` plates and the glue report fields.

  Planned recipes have empty tuples.
- `CLASSES = {"flat-icon": ("R1", "R2"), "figurine": ("R4", "R7"), "flexi": ("R6",
  "R8")}`, plus `resolve(class, colors: bool) -> Recipe`. It refuses a class whose
  recipes are all planned, naming the class and its status.
- `tdmg recipes` and the generated `docs/print-types/recipes.md` show classes and the
  new status.

**Tests:** statuses, `resolve` for each class, the refusal message, the generated table.

### Task 5: `.gitignore`

**Steps:** add `jobs/`, `prints/*/source/`, `prints/*/private/` and
`prints/.staging-*/`.

**Test:** `tests/test_gitignore.py` runs `git check-ignore` on sample paths, and
checks that `prints/x/card.md` and `prints/x/files/model.3mf` are *not* ignored. It
skips outside a git checkout.

### Task 6: `job.yaml` and `tdmg job new`

**Code:** `src/tdmg/jobs.py`.

**The schema** (`tdmg.job/1`):
- `name`, `class`, `recipe`;
- `source`: `file`, `sha256`, and `origin`, one of `photo`, `drawing`, `generated` or
  `unknown`. For `generated` it adds `prompt`, `generator`, `version`, `settings`,
  `references`, `chosen` and `edits`, each a string or `unknown`;
- `stages`: per-stage parameters in full;
- `confirmations`: a list;
- `revision`: an integer, bumped on every change.

**Rules:**
- **Name:** must match `^[a-z0-9][a-z0-9-]{0,62}$`; anything else is refused with a
  reason.
- **Reading:** strict. Unknown keys and wrong types are refused. Paths inside are
  relative to the job folder.
- **Writing:** through `tdmg.records` (an atomic rename) and as canonical YAML, so the
  same content gives the same bytes.

**`tdmg job new NAME --class C --image PATH [--colors] [--origin O] [--prompt ...]
[--generator ...]`:**
- creates `jobs/NAME/`, copies the image to `jobs/NAME/source/` (and any `--mask`), and
  writes `job.yaml` with default stage parameters for the resolved recipe;
- refuses an existing job, a class not ready, and an image that is missing or not an
  image.

**Tests:** names (including `..`, `a/b`, `CON`, uppercase, too long), the origin
fields, the round-trip, refusals, and byte-identical rewrites.

### Task 7: `tdmg job run`

**Steps:**
- Change parameters with `tdmg job set NAME STAGE.KEY=VALUE`. This is the only writer
  besides `job new` and `job confirm`; hand edits are read back through the strict
  loader.
- Each stage runs into `jobs/NAME/<stage>/`. The stage's **input key** is the SHA-256
  of its parameters plus the input keys of the stages before it. It is stored in
  `jobs/NAME/state.json`.
- A stage reruns only when its key changed or its folder has no record. It reruns into
  a fresh folder, and the old folder is replaced only after the new record exists.
- Status output, one line per stage: done, stale or not run, the verdict (for
  `slice`), stale confirmations, and what waits for the owner.

**Tests** (fake slicers):
- R1 and R2 jobs run end to end;
- a parameter change reruns only that stage and the ones after it;
- an interrupted stage (no record) reruns;
- the outputs equal the stage commands' outputs for the same inputs.

### Task 8: confirmations, `tdmg job confirm`

**`tdmg job confirm NAME --subject selection|colors|print --owner-said TEXT [--face
up|down]`:**
- It records the words verbatim, the date, the job revision and the covered hashes:
  - `selection`: the selection record and `preview.png`;
  - `colors`: `colors.json` and `regions.png`;
  - `print`: the printable file, the face and the slice identity.
- It refuses empty text.
- It refuses `print` when the slice verdict for that face is not PRINTABLE, unless
  `--accept-not-certified` is given. That flag is recorded too.

**Staleness:** `job run` marks a confirmation stale when a covered hash changes, and
the status shows it.

**Tests:** each subject, staleness after a rerun that changes bytes, no staleness after
a rerun with identical bytes, refusals.

### Task 9: `tdmg finish`

**Code:** `src/tdmg/library.py`.

**The steps** (design section 5):
1. Names and paths: check `NAME`; the job is exactly `jobs/NAME`; no symlink or
   junction (`Path.is_symlink()`, `Path.is_junction()`) on any component of the job,
   `prints/` or the staging path; `prints/NAME` is absent; the paths are disjoint
   after `resolve()`.
2. State: every stage done and current, a current `print` confirmation, and a clean
   git tree (`git status --porcelain` empty, outside `jobs/` and `prints/`).
3. Stage `prints/.staging-NAME/`:
   - `job.yaml`;
   - `source/`;
   - the recipe's outputs;
   - `provenance.json`: the commit, `uv.lock` SHA-256, Python and platform, key
     library versions, the rule values used (from the stage records), profile and
     slicer pin ids and hashes, algorithm ids, check results and the verdict;
   - `card.md`.
4. Rebuild: run the staged job in a scratch folder (`tempfile`) from `job.yaml` and
   `source/` only. Compare with the job's outputs, byte for byte except
   `VOLATILE_FIELDS` (Task 0). On a difference, report the files and fields, remove
   the staging folder, and delete nothing.
5. Public or not: `--public yes|no` is required, and the answer goes in the card. The
   printable files go to `files/` or `private/`.
6. Publish: rename the staging folder to `prints/NAME`, then write `COMPLETE` last.
7. Purge: `--purge-owner-said TEXT` is required. List the files, write the purge
   record (the owner's words, the date and the list) into
   `prints/NAME/provenance.json`, then delete exactly `jobs/NAME`.

   `--dry-run` does steps 1 to 4 and prints what 5 to 7 would do.

**Resume:** re-running after an interruption detects the staging folder, `prints/NAME`
without `COMPLETE`, or `COMPLETE` with the job still present, and continues from the
step left. It never redoes a publish.

**The card** (`card.md`): what to print and how, the face and the turn in Bambu Studio
(the existing `print_instructions` text), filaments per shell, size, layer settings,
the historical verdict and warnings, what was not checked, the owner's confirmation
and public answer, and the source hash and origin.

**Tests**, each with the fake slicers:
- the happy path, for R1, R2 AMS and R2 glue;
- a name with `..`;
- a junction (Windows only, with `mklink /J`; skipped elsewhere) and a symlink;
- an existing print;
- a stale confirmation;
- no print confirmation;
- a dirty tree;
- no `--public`;
- no purge words;
- a rebuild that differs (a patched stage);
- interruption after each step, then resume;
- `--dry-run` changes nothing.

### Task 10: `tdmg library check` and `tdmg library verify`

- **`check [NAME]`:** each entry has `COMPLETE`, every hash in `provenance.json`
  matches, and the source is present (or "source unavailable"). The exit code is 1 on
  any mismatch.
- **`verify NAME`:** runs the job under the current code and rules in a scratch folder,
  and reports the differences from the historical verdict and outputs. It writes
  nothing into `prints/`.

**Tests:** a tampered file, a missing source, a missing `COMPLETE`, and verify with a
changed rule value.

### Task 11: owner-image test fixtures

`tests/conftest.py`'s owner fixtures build their selection in `tmp_path` from:
- a library source (`prints/<name>/source/`) with its recorded controls, or
- a job source, or
- today's `artifacts/selection-runs/` while it exists.

They skip with a message naming the missing source, never silently.

**Tests:** the fixture resolution order; a skip message names the path.

### Task 12: the skill `.claude/skills/make-print/SKILL.md`

The conversation steps of design section 8, phase 5, with:
- the command at each step;
- which preview to show;
- the questions to ask;
- what is never done without the owner.

In plain English, and checked by a subagent against the code's real commands and
flags.

### Task 13: legacy inventory

Write `docs/design/jobs.md`: a table of every `artifacts/` folder and loose file,
assigned to tools (kept), Roadie drop, Roadie keep, R1 Roadie, Oddie, Oddie variants,
experiment, or obsolete, with a reason.

**Owner check:** the owner approves the list for Roadie drop's deletion before Task 14.

### Task 14: Roadie, the first finished print

1. `tdmg job new roadie-drop --class flat-icon --colors --image <the Roadie source>
   --origin <what the owner says>`. The parameters come from the recorded selection,
   colors config and colored-flat records of the printed run.
2. `tdmg job run roadie-drop`. Compare `model.3mf` with `ec296118…`.
   - **Equal:** continue.
   - **Different:** stop and ask the owner. The confirmation covers the printed file
     only.
3. `tdmg job confirm roadie-drop --subject print --face down --owner-said "done, and the
   newly printed items look great"` (2026-11-16; the face-down print).
4. Ask the owner: public or not, and the purge permission (their words).
5. `tdmg finish roadie-drop --public ... --purge-owner-said ...`.
6. Delete the approved Roadie drop legacy folders (Task 13 list) only.
7. Record it in `docs/evidence/` (a short record of the finish run, with its output).

### Task 15: docs, review, CI

**Docs:**
- `docs/guide/pipeline-and-gate.md` (jobs, finish, library);
- `docs/guide/00-start-here.md` (how to make a print with Claude);
- README (commands);
- `docs/print-types/README.md` (classes);
- glossary (job, library, card, provenance, purge);
- STATUS.

**Codex review** of the whole change, in `research/reviews/2026-11-16-restructure/`,
handled as before. Then CI on three OSes.

## Owner check-ins during the plan

- **After Task 1:** the cited and uncited lists.
- **After Task 3:** that the design notes keep what matters (optional; they are
  reviewed).
- **Task 13:** the legacy allowlist.
- **Task 14:** the Roadie origin, public or not, and the purge permission.
- **Any time a rebuild does not match** a file the owner approved.

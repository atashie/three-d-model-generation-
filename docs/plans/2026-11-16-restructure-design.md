# Repository restructure: design (DRAFT, for review)

**State:** draft, written 2026-11-16 for independent review (Codex and Antigravity)
before the owner approves it. Section 1 was shown to the owner; sections 2 to 8 are
the controller's proposal and have not been discussed with the owner yet. Nothing
here is built.

## Goal (the owner's words, 2026-11-16)

> "our goal is to allow a user to share a photo or image (possibly generated via text
> to image, or from a picture) and have this workflow turn it into a printable file (as
> has been done with roadie and oddie); each time a final printable file is created
> (confirmed by user) we can purge all stored data and information and documentation
> other than reusable code or reusable documentation or the actual printable file
> itself; further, we will want to be able to generate multiple classes of printable
> files including flat icons (i.e., what we have just created), simple figurines, and
> simple flexis; while we have only done work to generate the flat icons, we want to
> modularize our workflow such that we can pull specific resources to generate
> different types of outputs as desired when those resources are ready."

## Owner decisions so far (2026-11-16)

1. **User:** the owner, through Claude Code. No separate app, no other users.
2. **Purge scope:** "Also condense the past". Per-job data is purged when a print is
   confirmed, and today's `research/`, plans and reviews are condensed once: keep what
   rules cite or what explains reusable code; the rest leaves the working tree (it stays
   in git history).
3. **Kept per print:** "File + card + source": the printable file, a print card, the
   job config and the source image.
4. **Library location:** in the repo, `prints/`.
5. **Source image:** git-ignored `prints/<name>/source/` (the repo is public; the card
   records the image's hash).
6. **Roadie** (outline dropped, printed face down, "look great") is the first finished
   print; its job data is purged under the new scheme. Oddie stays an open job.

## Facts the design must respect

- CLAUDE.md rule 2: every number is a rule in `rules/*.yaml` with evidence; each
  evidence item has a `ref` (a file in this repo) and an exact `locator` string, and
  `tests/test_rules.py` proves the text exists. Today rules cite `research_notes/` (28
  refs), `docs/plans/` (6), `research/verification/` (about 8 files) and `docs/`.
- CLAUDE.md rule 6 ("research files are records; do not rewrite `research_notes/`")
  conflicts with decision 2 and must be rewritten.
- The code is one flat package, `src/tdmg/` (31 modules, about 18,000 lines), with 47
  test files (2,627 tests at the last full run). Records carry algorithm ids
  (`flat-3`, `colorflat-3`, `slice-6`, `colorslice-2`, `strip-4`) and record schemas
  (`tdmg.colors/4`, `tdmg.colorslice/1`, ...); `verify_colors` rebuilds a plan and
  refuses one whose result differs.
- Per-job working data today lives in git-ignored `artifacts/` (about 30 folders,
  including tools, TripoSR environments and run folders). Tracked per-job material is
  in `research/verification/` (owner prints, owner reviews), `research/reviews/` and
  `docs/plans/`.
- The repo is public on GitHub. CI runs on Windows, macOS and Ubuntu.

## 1. Three zones (shown to the owner)

| Zone | Holds | Tracked | Lifetime |
|---|---|---|---|
| Reusable | code, rules and their evidence, profiles, guides, per-module design docs | yes | permanent |
| Job | one image's working data: selection, previews, color plans, slice runs, decision notes | no | until the owner confirms the final print, then purged |
| Library | each finished print | file, card, config yes; source image no | permanent |

```text
src/tdmg/            reusable code (section 2)
rules/ profiles/     unchanged
docs/guide/          how to use it, what the checks mean
docs/classes/        one page per output class (flat icon, figurine, flexi)
docs/modules/        per-module design: what it does, why, decisions still in force
docs/evidence/       condensed records cited by rules
jobs/<name>/         git-ignored: job.yaml and each stage's output
prints/<name>/       model.3mf (+ palette.json), card.md, job.yaml; source/ git-ignored
.claude/skills/make-print/   the workflow Claude follows when the owner shares an image
```

Open point raised with the owner: a git-ignored job lives on one machine only.

## 2. Code layout: stages, shared resources, output classes

Split the flat package by what is shared, so an output class "pulls" only the
resources it needs. Moves only; no behaviour change (section 7).

| Package | Today's modules | Used by |
|---|---|---|
| `tdmg.core` | rules, profiles, records, paths, checks (F1/F2/F5), `_masks`, recipes | all |
| `tdmg.intake` | selection | all |
| `tdmg.flat` | flat, smoothing | flat icon, flat flexi |
| `tdmg.color` | color, color_outline, color_plan, color_config, colors, colors_verify, color_geometry, color_glue, colored_flat, color_checks | flat icon (multicolor); later flexi |
| `tdmg.export` | threemf | all |
| `tdmg.slicing` | slicer, slicing, orca_input, printed, portability, color_gcode, color_slicing | all |
| `tdmg.calibration` | calibration_strip | calibration only |
| `tdmg.classes` | new: `flat_icon` (today's R1 and R2), `figurine` (planned), `flexi` (planned) | the job runner |
| `tdmg.jobs` | new: job.yaml, stage state, `finish` (library, card, purge) | the CLI |

- **An output class** is a small declaration: its recipes (attribute combinations
  from today's registry: flat icon = R1/R2, figurine = R4/R7, flexi = R6/R8), its
  stages in order, its required checks and rule files, and a readiness status
  (`ready`, `in progress`, `planned`). The job runner refuses a class that is not
  ready. Recipes stay the attribute model; classes are the owner-facing names.
- `tdmg.recipes.Status` gains `in progress` so the generated table stops calling R1
  and R2 "planned".
- The existing commands (`select`, `flat`, `colors`, `slice`, `strip`) keep working;
  the job commands call the same functions.

## 3. Jobs

- `tdmg job new NAME --image PATH --class flat-icon` creates `jobs/NAME/` with
  `job.yaml` (image path and hash, class, size, filaments, every owner choice with
  its verbatim words and date) and copies the image in.
- Each stage writes into `jobs/NAME/<stage>/` and records its output hashes in
  `job.yaml`. `tdmg job status NAME` shows which stages are done and which wait for the
  owner.
- Owner confirmations (selection preview, color preview, the print) are recorded in
  `job.yaml` verbatim; Claude never records one the owner did not give.

## 4. The library and the print card

`tdmg finish NAME --print-name roadie` runs only if:
- the job's final stage verdict is PRINTABLE for the face chosen, and `model.3mf`'s hash
  equals the one that was sliced and judged;
- `job.yaml` holds the owner's confirmation of the physical print (verbatim, dated).

It writes `prints/<name>/`: `model.3mf`, `palette.json`, `job.yaml` (config and
decisions, no absolute paths), `source/<image>` (git-ignored) and `card.md`:
- filaments and colors per shell, face to print and how to turn it (Bambu Studio),
  size, layer settings, verdict and its warnings, tdmg version and algorithm ids, the
  source image hash, date, the owner's confirmation;
- what was not checked (e.g. glue gap untested).

## 5. Purge

- After writing the library entry, `finish` re-reads it, checks every hash, then
  deletes `jobs/<name>/`. It deletes only inside `jobs/` (path check), never follows
  links, and lists what it will delete first (`--dry-run` default in the skill; Claude
  shows the list and asks the owner).
- Tracked material made during the job (verification notes, reviews of that job) is
  condensed (section 6) in the same commit.
- Shared resources the job used (slicer installs, environments) are never purged.

## 6. Condensing the past (once, then per finished job)

- **Tag** `pre-restructure` on the last commit before condensing; the README points to
  it, so every old record is one checkout away.
- **`docs/evidence/<topic>.md`:** one condensed record per topic that rules cite
  (skin strip calibration, OrcaSlicer on Windows, A1 profile include, slicer 3MF
  import, PrusaSlicer, thin walls, the first AMS print...). Each keeps, verbatim, every
  locator string a rule cites, plus what was run, when, on what, and the result. Rule
  `ref`s move to these files; `tests/test_rules.py` keeps proving the locators exist,
  and each moved rule is re-read to check the text still supports the value.
- **`docs/modules/<module>.md`:** from the plans and reviews, the design and the
  decisions still in force for each module, and review findings that still constrain
  the code (e.g. "non-finite gaps never PASS").
- **Kept as is:** `research_notes/` and `reports/` (the landscape research, reusable
  for figurines and flexis; rules cite them), the `research/experiments/` G3 results
  condensed into `docs/evidence/g3-backends.md`.
- **Removed from the working tree:** `docs/plans/` (done plans), `research/verification/`
  and `research/reviews/` once condensed, STATUS's session history.
- **New CLAUDE.md rule 6:** records are condensed when their job or feature is done;
  evidence a rule cites is kept verbatim in `docs/evidence/`; full history is in git
  (tag `pre-restructure` and later commits). Future plans and reviews live in
  `docs/plans/` and `research/reviews/` until their work is done, then are condensed.
- **STATUS.md** becomes current state only: open jobs, next steps, open questions,
  machines. No session history.

## 7. Migration, in phases, each verified

1. **Baseline:** record hashes of every output of the owner's four plans and both R1
   models (selection, flat, colors, colored flat, slice records) and the strip, from
   the current code.
2. **Move code** into packages (section 2) with import shims removed in the same
   phase; algorithm ids unchanged. Full tests, ruff, `gen_docs --check`, real-slicer
   tests, then re-run phase 1: every output byte-identical.
3. **Add classes and jobs** (`tdmg.classes`, `tdmg.jobs`, `job new`, `job status`,
   `finish`), tests first, including purge safety (refuses outside `jobs/`, refuses
   without confirmation, refuses on hash mismatch).
4. **Condense** (section 6): evidence files, rule refs moved, rules re-read, module
   docs, CLAUDE.md, STATUS, README, tag.
5. **Roadie:** make `jobs/roadie/` from the existing Roadie drop run, record the owner's
   confirmation already given ("the newly printed items look great"), `finish` it into
   `prints/roadie/`, purge. Oddie becomes an open job.
6. **The skill** `.claude/skills/make-print/`: the conversation steps (share image,
   select and confirm, choose class and size, colors and confirm, build, slice, print
   instructions, print, confirm, finish and purge), which preview to show at each step,
   and what Claude must never do (record a confirmation not given, purge without the
   owner's yes, call something printed that was not).
7. Codex review of the whole change; CI on three OSes.

## 8. Open questions

- A job on one machine only (git-ignored) vs tracking job configs.
- Whether `artifacts/` (tools, environments) is renamed `tools/` and kept separate from
  `jobs/`.
- Whether old run folders in `artifacts/` for the other three plans are purged now or
  kept until those jobs finish.
- Whether figurine and flexi get placeholder packages now or only when work starts.

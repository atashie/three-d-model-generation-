# Repository restructure: design (DRAFT 2, after review)

**State:** draft 2, **approved by the owner on 2026-11-16** ("proceed with draft 2");
implementation plan: `docs/plans/2026-11-16-restructure.md`. Written 2026-11-16. Draft 1 was reviewed by Codex and Antigravity
(`research/reviews/2026-11-16-restructure-design/`); the owner then made decisions 7
to 10. This draft answers every finding (the table at the end).

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

## Owner decisions (2026-11-16)

1. **User:** "Me, via Claude Code (Recommended)". No separate app.
2. **Purge scope:** "Also condense the past".
3. **Kept per print:** "File + card + source".
4. **Library:** "In the repo, prints/ (Recommended)".
5. **Source image:** "Git-ignored prints/<name>/source/ (Recommended)" (the repo is
   public).
6. **Roadie:** "Yes, Roadie is done (Recommended)": the first finished print. Oddie
   stays open.
7. **Evidence:** "Move, don't rewrite (Recommended)". A record that anything cites moves
   intact; records nothing cites leave the working tree; plans and reviews are
   distilled into per-area design notes.
8. **Code split:** "Split when figurines start (Recommended)". No package split now.
9. **Public files:** "Ask per print (Recommended)". At `finish` the owner says whether
   the design may be public; if not, the printable files are git-ignored too.
10. **Rebuild proof:** "Prove a rebuild first (Recommended)". A job is purged only
    after the print has been rebuilt from the library's own files and matched.

## Amendment after Task 1 of the plan (2026-11-16)

The owner read the evidence inventory and decided: "Remove 5, keep pc-stack
(Recommended)" and "Leave them in place (Recommended)". So cited records stay at their
paths under `research/`, which is the evidence folder; there is no `docs/evidence/`.
Where sections 1, 6 and 8 below say `docs/evidence/`, read `research/` (records stay in
place, not moved). So, in section 6, no references are rewritten and the strip
algorithm id is not bumped; CLAUDE.md rule 6 uses the wording in the plan's Task 3
("kept intact where it is"), not the wording in section 6. The five uncited records were
removed in commit `814a962723454efa7693b8ef8af715062368975a` (Task 3; listed in
`research/README.md`), and their standing decisions are in `docs/design/`. Every done
plan in `docs/plans/` is cited, so none left the tree. Details:
`docs/plans/2026-11-16-restructure.md`, "Owner decisions after Task 1".

## 1. Zones

| Zone | Holds | Tracked | Lifetime |
|---|---|---|---|
| Reusable | code, rules, profiles, guides, design notes, `docs/evidence/` | yes | permanent |
| Job | `jobs/<name>/`: one print's working data | no | until `tdmg finish` |
| Library | `prints/<name>/`: each finished print | card and config yes; printable files only if the owner says public; source never | permanent |

```text
src/tdmg/              the package, as today (decision 8), plus jobs.py and library.py
rules/ profiles/       unchanged, except evidence and record paths (section 6)
docs/guide/            unchanged
docs/print-types/      unchanged home of recipe pages (no new docs/classes/)
docs/design/           new: one note per area (selection, flat, color, slicing,
                       calibration, jobs): decisions in force, review findings that
                       still constrain the code, links to evidence
docs/evidence/         records moved intact, original folder names
jobs/<name>/           git-ignored
prints/<name>/         card.md, job.yaml, provenance.json (tracked);
                       files/ (tracked only if public); source/ (git-ignored)
artifacts/tools/       slicer installs; never touched by any job command
.claude/skills/make-print/   the workflow Claude follows
```

`.gitignore` gains `jobs/`, `prints/*/source/` and `prints/*/private/` (non-public
printable files go in `private/` instead of `files/`) before any file is copied
there, with a test that `git check-ignore` covers them.

## 2. Recipes and output classes (no package split yet)

- The recipe registry (`tdmg.recipes`) stays the one source of policy. Each recipe gains:
  its stages in order, its required outputs (R1: `model.stl`; R2 AMS: `model.3mf` and
  `palette.json`; R2 glue: the plate STLs and the glue report), and status `in
  progress` (new value; R1 and R2 move to it).
- An **output class** is only an owner-facing name for a group of recipes, in the same
  registry: `flat-icon` = R1, R2; `figurine` = R4, R7; `flexi` = R6, R8. A job names a
  class and is resolved to one concrete recipe; a recipe that is not `implemented` or
  `in progress` is refused.
- **Deferred to when figurine work starts (decision 8):** splitting the package and
  untangling its imports (flat, color and slicing import each other today), and
  separating reusable primitives from flat-icon policy. Known constraints for that
  work, recorded in `docs/design/`: `paths.py` finds the checkout by depth;
  `printed.py` refuses supports and assumes a centred placement; `threemf.py` requires a
  base plus inlays; check text names module paths, so moving a module changes records.
  A figurine or flexi must declare its own checks; one it lacks is UNKNOWN, never
  inherited from flat icons.

## 3. Jobs

`jobs/<name>/job.yaml` is the declarative spec of one print:
- `name` (lowercase letters, digits and hyphens; variants are separate jobs, e.g.
  `roadie-drop`, `roadie-keep`), `class`, `recipe`;
- **source:** file name and SHA-256; `origin` (`photo`, `drawing`, `generated`,
  `unknown`); for `generated`: prompt, generator and version, settings, reference
  inputs, chosen candidate, later edits. Each field may be `unknown`. Claude records
  only what the owner states or the file shows. Image generation stays outside the
  pipeline (CLAUDE.md rule 1);
- **every stage's parameters** in full (selection controls including the mask file,
  size, colors config, merges, outline, face), not just hashes;
- **confirmations** (section 4).

Commands (they call the same functions as today's stage commands, which stay):
- `tdmg job new NAME --class C --image PATH [--origin ...]` copies the image to
  `jobs/NAME/source/` and writes `job.yaml`;
- `tdmg job run NAME` runs every stage whose inputs changed, in order, and prints the
  status: done stages, stale confirmations, what waits for the owner;
- `tdmg job confirm NAME --subject S --owner-said TEXT` (section 4);
- `tdmg finish NAME` (section 5).

The source is never deleted by a purge: `finish` moves it to the library. Abandoning a
job needs the owner's explicit word and keeps `source/` unless told otherwise.
Calibration strips run as jobs too (`jobs/strip-<date>/`); a printed result goes to
`docs/evidence/`.

## 4. Confirmations

Each confirmation in `job.yaml` holds: subject (`selection`, `colors`, `print`), the
owner's words verbatim, the date, the job revision and the SHA-256 of every file it
covers (for `print`: the printable file actually printed, the face and the slice
record). `job run` marks a confirmation stale when any file it covers changes, and
`finish` refuses stale ones. A print confirmation is not permission to purge: the purge
permission is given at `finish` (`--owner-said`), separately. Claude passes the
owner's words only when the owner gave them in the conversation.

## 5. `finish`: a guarded transaction

1. **Check names and paths:** `NAME` matches `[a-z0-9][a-z0-9-]*`; the job is exactly
   `jobs/NAME`; no path component of the job or of `prints/` is a symlink or a Windows
   junction (`is_symlink()`, `is_junction()`); `prints/NAME` does not exist; job and
   library paths are disjoint after resolving.
2. **Check state:** every required stage done; a current `print` confirmation; the git
   tree clean (so a commit pins the code).
3. **Stage** into `prints/.staging-NAME/`: the recipe's required outputs, `job.yaml`,
   `source/` (image and any mask), `card.md`, `provenance.json`. The required set comes
   from the recipe, not from a manifest.
4. **Prove the rebuild** (decision 10): in a scratch folder, run the job from the staged
   `job.yaml` and `source/` only, at the same commit, with the pinned slicers. Compare
   by the classes measured in migration phase 0: deterministic files byte-identical;
   slice records equal in every measured value and verdict, with only the named
   timestamp fields excluded. Any difference stops `finish`; nothing is deleted.
5. **Ask public or not** (decision 9): the owner's answer is recorded in the card;
   printable files go to `files/` (tracked) or `private/` (git-ignored).
6. **Publish:** rename the staging folder to `prints/NAME`, then write `COMPLETE`
   (last). `tdmg library check` treats a folder without it as incomplete.
7. **Purge:** list everything under `jobs/NAME`, require the purge permission, delete
   exactly that folder. An interrupted `finish` is resumed by running it again: each
   step checks what is already done.

**`provenance.json`:** git commit, `uv.lock` SHA-256, Python and platform, key library
versions, the values of every rule used, profile and slicer pin ids and hashes,
algorithm ids, machine-readable check results, and the verdict. The card states it as
the **historical verdict** (at that commit, under those rules).
`tdmg library verify NAME` re-runs the job under the current code and rules and
reports differences; it never rewrites the historical verdict.

**The card** (`card.md`): what to print (file, filaments per shell, face and how to turn
it in Bambu Studio, size, layer settings), the historical verdict and warnings, what
was not checked (e.g. the glue gap), the owner's confirmation, the public answer, the
source's hash and origin.

**Private files and machines:** `prints/*/source/` and `private/` exist on one disk.
`tdmg library check` verifies every hash and reports "source unavailable" where a
source is missing. Backup and moving to the Mac is a documented copy of `prints/`,
checked by `library check` on arrival. Git alone does not preserve the library.

## 6. Evidence and the past (decision 7)

- **Inventory first** (a script, output committed): every reference to `research/`,
  `docs/plans/`, `reports/`, `research_notes/` from rules, profiles, tests, code
  constants (e.g. `calibration_strip.SOURCE`), scripts, docs and CI.
- **Cited records move intact** with `git mv` to `docs/evidence/<original folder
  name>/`, with their raw files, tables, manifests and `measure_*.py` scripts. Nothing
  inside is rewritten. Every reference is updated in the same commit; `test_rules.py`
  locators stay identical because the text is unchanged. Records behind `hypothesis`
  or `untested` rules move like the rest and stay until calibrated.
- **Uncited records** (and uncited done plans and reviews) leave the working tree. Before
  that, their decisions and review findings that still constrain code go into
  `docs/design/<area>.md`, with the record's old path and the commit that removed it.
- **Kept as they are:** `research_notes/`, `reports/` (CLAUDE.md rule 6 as today).
- **Record strings in code:** `calibration_strip.SOURCE` and `KNOWN_FAILURE_CAUSE`
  change path, so `strip.json` changes: the strip algorithm id is bumped, with a
  dated comment.
- **Tag** `pre-restructure` before the move. It is an archive for people, not
  evidence: no rule, test or CI step depends on it.
- **STATUS.md** becomes current state only (open jobs, next steps, open questions,
  machines); its history goes to `docs/design/` or leaves the tree like other uncited
  records.
- **CLAUDE.md rule 6** becomes: "Records are evidence. A record that a rule, test,
  profile, code or doc cites is kept intact in `docs/evidence/`; it may move, never be
  rewritten. Job working data is deleted only by `tdmg finish`. A record nothing cites
  may leave the working tree once its work is done, after its standing decisions are
  in `docs/design/`; git history keeps it. Do not rewrite `research_notes/`; correct
  `reports/` only with a revision-history entry."

## 7. Legacy data (today's `artifacts/`)

An inventory table (committed in `docs/design/jobs.md`) assigns every `artifacts/`
folder to one of: tools (kept), Roadie, Oddie, another owner variant, experiment, or
obsolete. Deletion uses that reviewed allowlist only, never a parent folder or a
partial name. Owner-image tests (`tests/conftest.py` reads
`artifacts/selection-runs/`) are changed to build their selection in a temporary folder
from a library or job source and its recorded controls, so purging does not make them
skip silently.

## 8. Migration, in phases

0. **Repeatability baseline:** run today's code twice on the four owner plans, both R1
   models and the strip; classify each output as byte-identical or as differing only
   in named fields (e.g. G-code timestamps). This defines the comparison used by the
   rebuild proof.
1. **Evidence move** (section 6): tag, inventory, `git mv`, references, design notes,
   CLAUDE.md, STATUS. Full tests, ruff, `gen_docs --check`, real-slicer tests, CI.
2. **Recipe registry** (section 2): stages, outputs, `in progress`, classes; docs
   regenerated.
3. **Jobs and confirmations** (sections 3 and 4), tests first; `.gitignore` first.
4. **Library and `finish`** (section 5), tests first, including: names with `..`, a
   junction, an existing print, a stale confirmation, no purge permission, an
   interrupted finish, a rebuild that differs.
5. **The skill** `.claude/skills/make-print/`: share the image (and, for a generated
   one, what the owner knows of its origin), job new, selection preview and confirm,
   size and class, colors preview and confirm, build and slice, print instructions,
   the owner prints, confirm, finish (public?, purge permission). Claude never records
   a confirmation the owner did not give, never purges without the purge permission,
   never calls something printed that was not.
6. **Roadie:** `jobs/roadie-drop/` from the existing inputs; `job run` at the current
   commit. The owner's print confirmation covers the `model.3mf` actually printed:
   if the rebuilt file's hash differs from it, stop and ask the owner. Then `finish`,
   and the legacy allowlist for Roadie's old folders.
7. **Codex review** of the whole change; CI on three OSes.

## 9. Still open

- Oddie and the other variants (Roadie keep, R1 runs) stay legacy folders until their
  own jobs; the inventory marks them.
- Whether to back up private library files anywhere beyond a copy (none chosen).

## Review findings and where this draft answers them

| # | Finding (merged, see the review README) | Answer |
|---|---|---|
| 1 | Evidence is more than locator strings | decision 7: records move intact (section 6) |
| 2 | Tests, profiles and code read research files | inventory and `git mv` with every reference updated (section 6) |
| 3 | The tag is not usable evidence | nothing depends on the tag (section 6) |
| 4 | A print cannot be regenerated | full parameters and mask in `job.yaml`/`source/`, `provenance.json`, rebuild proof (sections 3, 5) |
| 5 | Confirmations not bound | hashes per confirmation, staleness, separate purge permission (section 4) |
| 6 | Purge paths and completeness | finish steps 1, 3, 6, 7 (section 5) |
| 7 | Byte-identical is false for some outputs | phase 0 measures it; comparison classes (sections 5, 8) |
| 8 | Package split breaks discovery, cycles | decision 8: deferred; constraints recorded (section 2) |
| 9 | Shared slicing and export are flat-specific | recorded; new classes declare their own checks, missing ones UNKNOWN (section 2) |
| 10 | Classes duplicate recipes; one output shape | classes are names in the recipe registry; outputs per recipe (section 2) |
| 11 | Legacy data mixed | inventory and allowlist; conftest change (section 7) |
| 12 | Docs migration under-specified | no `docs/classes/`; inventory covers doc links; `docs/design/` (sections 1, 6) |
| 13 | Private source has no backup plan | `library check`, documented copy (section 5) |
| 14 | Text-to-image provenance | `source.origin` fields (section 3) |
| 15 | Public 3MF is a derivative | decision 9 (section 5, step 5) |
| 16 | Rule 6 vs uncalibrated rules | their records move and stay (section 6) |
| 17 | Job layer over-designed | four job commands over the same functions; no second option parser (`job.yaml` holds parameters) |
| 18 | Strip output has no home | strip jobs (section 3) |

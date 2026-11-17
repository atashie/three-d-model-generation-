# Project status

**Last updated:** 2026-11-17 (restructure Task 9: `tdmg finish`).

Keep this page current. A new session reads it right after `CLAUDE.md`, and it is the
only memory that travels between machines. It holds the current state only. Why things
are the way they are is in the design notes ([docs/design/](design/README.md)); the
evidence is in `research/` ([research/README.md](../research/README.md)); older versions of
this page are in git history.

## What works now

Phase 1 (R1, flat single-color) and R2 (flat multicolor) are under way. The commands:

- **`tdmg select IMAGE --out DIR ...`** (S0/S1): selects the subject with explicit
  controls; the owner checks `preview.png`. See [selection](design/selection.md).
- **`tdmg flat SEL_DIR --width-mm W --thickness-mm T --out DIR`** (S2–S4, S8): a flat
  STL, smoothed by default (`--smooth-px 0` keeps the exact outline), gated on the
  written file. See [flat](design/flat.md).
- **`tdmg colors SEL_DIR --width-mm W --out DIR [--config FILE]`** (R2 step 1): a color
  plan with a `regions.png` preview to review; not ready when more colors remain than the
  AMS allows.
- **`tdmg flat SEL_DIR --colors PLAN ...`** (R2 steps 2–3): the AMS bodies as one
  `model.3mf` with `palette.json`, plus a glue version (none for a plan that keeps a drawn
  outline). See [color](design/color.md).
- **`tdmg slice DIR --out OUT --slicer-dir artifacts/tools/orcaslicer-2.5.0`** (S9, R2
  step 4): pinned OrcaSlicer 2.5.0 and the A1 profiles; F6 and F3 judged from the G-code;
  `F6.portability` with `--prusaslicer-dir`. On a colored folder it slices both faces and
  prefers face down when it is PRINTABLE (`--face up|down|both|auto`). See
  [slicing](design/slicing.md).
- **`tdmg job new NAME --class flat-icon --image PATH [--colors] [--mask FILE]`**
  (restructure Task 6): makes `jobs/NAME/` with the image in `source/` and `job.yaml`
  (schema `tdmg.job/1`, `src/tdmg/jobs.py`): class, recipe, source hash and origin,
  every stage's parameters (null = the stage command's default).
- **`tdmg job set NAME STAGE.KEY=VALUE ...`, `tdmg job run NAME --slicer-dir DIR`,
  `tdmg job status NAME`** (restructure Task 7, `src/tdmg/job_runner.py`): set
  parameters (strict YAML values); run each stage not done into `jobs/NAME/<stage>/`,
  driven as the stage commands drive it (tests show the files equal a run by hand,
  except G-code timestamps and their hashes); input keys (parameters, upstream record
  hashes, algorithm ids, rules, profiles) in `state.json`; a rerun goes into
  `<stage>.new/` and replaces the old folder only when its record exists; `--rerun
  STAGE`; a per-job `.lock`.
- **`tdmg job confirm NAME --subject selection|colors|print --owner-said TEXT [--face
  up|down] [--route single|ams|glue] [--date YYYY-MM-DD] [--accept-not-certified]`**
  (restructure Task 8): appends the owner's verbatim words to `job.yaml` (now
  `tdmg.job/2`; `/1` still read) with the date, revision and covered file hashes; a print
  entry adds the route, face, slice identity and verdicts. Refuses blank words, stages not
  done, files that differ from their records, faces not sliced, and a verdict not
  PRINTABLE without `--accept-not-certified`. Status shows each confirmation current or
  stale, re-hashing the covered files each time. `state.json` (now `tdmg.jobstate/2`)
  holds each stage record's hash, so a hand-edited record makes its stage stale. A print
  confirmation is not permission to purge.
- **`tdmg finish NAME --public yes|no --purge-owner-said TEXT [--confirmation N]
  [--dry-run] --slicer-dir DIR`** (restructure Task 9, `src/tdmg/library.py`): checks the
  paths (no links), every stage done, a current print confirmation and a clean git tree;
  stages `prints/.staging-NAME/` (`job.yaml`, `source/`, the confirmed route's printable
  files, `provenance.json`, `card.md`); rebuilds the job in a scratch folder and compares
  every file, allowing only the measured G-code timestamp lines and `slice.json`'s G-code
  hashes; renames it to `prints/NAME`, writes `purge.json` then `COMPLETE`; checks the
  entry against `purge.json`, renames `jobs/NAME` to `jobs/.purging-NAME`, checks it holds
  exactly what was listed, and deletes it. Printable files in `files/` (public) or
  `private/` (git-ignored). Resumes after an interruption. Spec-review fixes done
  (2026-11-17). Tested with fake slicers only: **not yet run on a real job** (that
  is Task 14, Roadie).
- **`tdmg strip OUT`** (R2 step 5, part 1): the two calibration strips and the results
  form. See [calibration](design/calibration.md).

**To print:** open `model.stl` or `model.3mf` in Bambu Studio and assign the filaments
`tdmg slice` lists; turn the model over if the chosen face is down. Do not print
`tdmg`'s own `plate_1.gcode`: it is for checking only until it has been compared with
Bambu Studio's slice. Never print a G-code from a run before `slice-5` (2026-11-13; it
had generic start code).

**PRINTABLE** means every required check passed with the pinned slicers and the A1
profile. It is not a guarantee: `acceptance.dimension.tolerance` is a hypothesis, nothing
has been measured with calipers, and strength is not judged.

## Where things stand

| Area | State |
|---|---|
| Research | Landscape report (v2.1) and seven source notes. Evidence records in `research/` (verification, reviews, experiments), kept intact; five uncited ones removed on 2026-11-16 (`research/README.md`) |
| Plan | `docs/PLAN.md` v2.1; owner decisions in its section 13. Plans in `docs/plans/`; standing decisions per area in `docs/design/` |
| Phase 0 (foundations) | **Done.** Package `tdmg`, rules with checked citations, A1 profile, docs; CI on Windows, macOS and Linux |
| R1 (flat single-color) | **In progress.** select, flat, slice work. Roadie and Oddie at 60 × 3 mm are PRINTABLE (2026-11-11; again with the A1's own start code, 2026-11-13). One owner print (Roadie, Bambu Studio's slice): "it looks great", by eye. **Not built:** keychain loop or base, text, 3MF for R1, manifest |
| R2 (flat multicolor) | **In progress, step 5 part 2.** All four owner plans PRINTABLE face up; the two outline-dropped plans PRINTABLE face down (chosen by default). Printed: Roadie, outline dropped, face down "look great" (face up smeared). Skin depth 0.6 mm calibrated. No glue print; no glue route fully PRINTABLE |
| Photo-to-3D backend (R4) | TripoSR CPU test done (32–35 s/model; raw meshes fail topology). MakerLab STLs inspected. No backend chosen. `research/experiments/2026-11-g3-local-vs-hosted/` |
| Restructure | **In progress** (plan `docs/plans/2026-11-16-restructure.md`). Tasks 0–9 done; next Task 10 (`tdmg library check` and `verify`) |

## Machines

| Machine | Facts | What has been verified on it |
|---|---|---|
| M5 MacBook | Apple M5, arm64, 16 GB, macOS 26.3, no CUDA | Python 3.13 stack installed and tested (`research/verification/2026-11-08-stack-smoke/`); all tests; wheel build and install. No slicer installed, so `tdmg slice` has not run a real slicer here. The owner fixtures (colors) have not been run here, so cross-platform parity is unverified |
| PC | Windows 11 Pro 10.0.26200 x64; i9-12900K (16 cores/24 threads), 64 GB RAM; Intel UHD 770, no discrete GPU | Core sync, tests, lint, docs, wheel install and geometry smoke checks passed. Optional import failures (PyMeshLab, Open3D, rembg/ONNX Runtime, bpy) recorded in [research/verification/2026-11-09-pc-stack/README.md](../research/verification/2026-11-09-pc-stack/README.md). Pinned OrcaSlicer 2.5.0 in `artifacts/tools/orcaslicer-2.5.0/` and PrusaSlicer 2.9.7 in `artifacts/tools/prusaslicer-2.9.7/`, both run by `tdmg slice` |

- **CI:** `macos-15` (arm64), `ubuntu-latest`, `windows-latest`. The real slicers are not
  installed in CI, so `-m slicer` tests run on the PC only. Last CI-verified commit:
  `04806a8` (restructure Task 2; run 43973575937, all three OSes). Earlier in the
  restructure, `5216570` (run 43946283675) failed on a doc test; `f17d56f` fixed it
  (run 43946335668 passed). The Task 3 commits are not pushed.
- **Latest local validation (2026-11-17, PC, restructure Task 9 re-review minors):**
  `uv run pytest -q` gave 3244 passed and 12 skipped (8 real-slicer tests; four symlink tests, since this
  account cannot create symlinks; the junction tests ran); `tests/test_finish.py` also
  passed under `CI=true GITHUB_ACTIONS=true`; `ruff check`, `gen_docs.py --check` and
  `evidence_inventory.py --check` passed.
- **Antigravity** (`agy` 1.5.9, Gemini) at `C:\Users\arikt\AppData\Local\agy\bin` on the
  PC. A session started before the install needs a restart or that folder on PATH; in
  Git Bash set `MSYS_NO_PATHCONV=1` for `agy-doctor`. 18 models (Gemini 4
  Hydrogen/Argon, 3.8 Flash, Claude, GPT-OSS); no image model and no image-generation
  tool, so Google image generation would come from the Gemini app/AI Studio by hand or
  the Gemini API. `agy-delegate` returned empty output twice while `agy -p` worked.
- **Local data, not in git:** original images in `C:/Users/arikt/Downloads/three-d-test/`
  (STLs in its `makersLabModels/`). Runs in `artifacts/selection-runs/`,
  `artifacts/flat-runs/`, `artifacts/colors-runs/` (the approved plans are `*-f64`;
  configs in `configs/`; the previews the owner approved in `artifacts/colors-review-3/`),
  `artifacts/colored-runs/`, `artifacts/slice-runs/`. The printed
  Roadie AMS file is `artifacts/colored-runs/roadie-tol30-60-drop-v3-f64/model.3mf`.
- **Environments:** the core `.venv` uses Python 3.13. TripoSR uses
  `artifacts/triposr-py311` (3.11.15), with sources in `artifacts/TripoSR` and
  `artifacts/torchmcubes` and weights in `artifacts/triposr-data`. Do not recreate
  environments, redownload models or repeat costly trials without checking these first.
  The owner's approvals for that TripoSR setup (checkpoints, compilers) hold for it only;
  they do not authorize unrelated cloud spending or upload batches.

## Next steps, in order

1. **The owner prints figures** (R2 step 5, part 2). For an AMS print: `tdmg slice
   COLORED_DIR`, then follow its "chosen:" line and print instructions. Record each
   print. The first glue print is also the first test of the 0.2 mm glue gap: record how
   the pieces fit and the filament.
2. **Repository restructure** (owner's goal, 2026-11-16: any image in, a confirmed
   printable file out, for several output classes; per-job data purged once the owner
   confirms a final file). Design `docs/plans/2026-11-16-restructure-design.md` (draft 2,
   approved: "proceed with draft 2"); plan `docs/plans/2026-11-16-restructure.md`, Tasks
   0 to 15, run with subagents task by task. Done: Task 0 (repeat runs: 119 of 159 files
   identical, the rest differ only in G-code timestamp lines; the printed Roadie
   `model.3mf` rebuilds identically), Task 1 (evidence inventory), Task 2 (tag
   `pre-restructure`; record paths beside name citations), Task 3 (design notes), Task 4
   (recipe registry: `in progress` status, stages, outputs by route, output classes and
   `resolve`), Task 5 (`.gitignore` for `jobs/` and the library's private parts),
   Task 6 (`job.yaml` and `tdmg job new`), Task 7 (`tdmg job set`, `job run`, `job
   status`), Task 8 (`tdmg job confirm`), Task 9 (`tdmg finish`; tested with fake
   slicers and temporary git repositories, not run on a real job; not yet reviewed by
   Codex). Next: Task 10 (`tdmg library check` and `verify`).
3. **Outline-kept plans fail face down (open):** up to 1.18 mm of the outer edge is
   unprinted on the first layer (Roadie keep; Oddie keep 0.64 mm). `auto` prints them
   face up for now. Cause not investigated.
4. **The glue route (open):** no owner plan has every glue plate PRINTABLE.
5. **Caliper measurements,** if the owner gets calipers: three named dimensions within
   `acceptance.dimension.tolerance` (still a hypothesis), logged as a calibration.
6. **R1 features:** the keychain loop or base, then 3MF output for R1 (R2 already
   writes `model.3mf`).
7. **Roadie's roughness (open):** the owner finds Roadie's smoothed edge "close but
   still a bit rough", acceptable for now. Options: a per-image `--smooth-px`, or a
   better source image.
8. **R4 backend (open):** help the owner choose under their decision rule: a cheap
   standard service, around $1 per model, beats a homemade pipeline if it does
   everything we need.

**Ideas, not started:** owner-generated "print-friendly" input art (flat colors, plain
background), recorded with its prompt and model, run through the unchanged pipeline.

**Small open items:** the stray `C:\c\...` folder (scratch files from a subagent) needs
deleting by the owner; `colored_flat.py`'s REVIEW_END text is deliberately unchanged;
R1's `F2.export_matches_geometry` checks only bounds and volume (see
[flat](design/flat.md)).

## Open questions for the owner

| Question | State |
|---|---|
| Hosted API keys (Replicate, fal) | Still deferred; local results are available, but no hosted batch has been authorized |
| Is a monthly plan acceptable for a commercial API, such as Meshy's $20 Pro plan? | Not answered |
| Use Meshy's free printability check as a second opinion? It means uploading the mesh | Not answered |
| Photo privacy with hosted services, and their data and training terms | Uploading is allowed for now. **Marked to revisit** |
| MakerLab engine/version, credits, settings, uploaded input provenance | Unknown; the owner supplied STLs, not generation metadata |
| Intended output form | Not settled (a pending decision in earlier handoffs) |
| Oddie shape acceptance and desired Roadie depth/form | Not settled. The extracted Roadie is a flat-backed relief; do not silently convert it to a full figurine |

## Owner decisions, in short

The full list is in `docs/PLAN.md` section 13; decisions per area, with the owner's
words and dates, are in [docs/design/](design/README.md).
- **Printer:** Bambu Lab A1. Bambu Studio is the owner's slicer.
- **Portable files:** print files must not depend on the AMS unit or the slicer. They use
  standard 3MF, name colors rather than slots, and ship a palette manifest.
- **Jobs default to at most 4 filaments,** the AMS lite's slot count. A job declares its
  real cap.
- **Licence and use:** personal use; the repo is MIT. The owner is in the US.
- **Roadmap order:** R1 → R2 → R3 → R4. A command-line tool and Python library first.
- **Photo-to-3D:** local is preferred. Hosted models are fine to try; most work will be
  simple objects. GPU rental is unnecessary for now.
- **Interpretation:** plain-language instructions, applied through explicit selection
  controls; no LLM in the default runtime.
- **Style choices** (outlines, shading, merges) are explicit config options with
  defaults, never side effects of cleanup.
- **Restructure** (2026-11-16): the ten design decisions in the restructure design; after
  the inventory, "Remove 5, keep pc-stack (Recommended)" and "Leave them in place
  (Recommended)" (records stay under `research/`, no `docs/evidence/`).

## Handoff: the restructure

- **State:** Tasks 0–9 of `docs/plans/2026-11-16-restructure.md` are done, on `main`.
  Tasks 0–2 and the tag `pre-restructure` are pushed; Tasks 3 onwards are not. Next is
  Task 10, `tdmg library check` and `verify`.
- **Task 9 decisions:** the purge record is its own file, `purge.json`, written after the
  publish and before `COMPLETE`, so `COMPLETE` is last and lists it, and `provenance.json`
  stays the file that was staged and checked (accepted after the spec review; dated
  notes in the plan's Task 9 step 7 and design section 5 step 7). After the review the
  deletion goes through a tombstone `jobs/.purging-NAME`, the entry is checked against
  `purge.json` before anything is deleted, a `STAGED` manifest binds a resumed publish,
  unreadable folders stop finish, and git renames are judged by both paths. The rebuild compares every file of every
  stage folder (not only the records and printable files); only the slice.json rows of
  the repeatability record's table may differ, so the "inferred, not measured" `.failed`
  forms (top-level `plate_1.gcode.failed`, `face-up/plate_1.gcode.failed`, a top-level
  PrusaSlicer `.failed`) still stop a finish when their hash differs. `--dry-run` needs
  `--public` but not the purge words.
- **Task 3 did:** design notes `docs/design/{selection,flat,color,slicing,calibration}.md`
  with an index; removed the five uncited records in commit `814a962` (listed in
  `research/README.md`); replaced CLAUDE.md rule 6; cut this page to current state.
- **Keep in mind:** later tasks that say `docs/evidence/` mean `research/verification/`
  (plan, "Owner decisions after Task 1"). Links inside kept records to removed records
  stay as written. `docs/design/evidence-inventory.md` is generated; regenerate it after
  touching references.

## How this project works

- **Owner:** a data scientist who is new to 3D printing. Explain 3D concepts plainly.
- **Evidence over priors:** never fill a gap with an assumption. Say what was verified,
  how, and what was not.
- **Code decides:** the default pipeline has no LLM calls.
- **Independent review:** after each meaningful change, run an independent read-only
  review with the OpenAI Codex CLI, verify each finding against its source before
  applying it, and record the handling in `research/reviews/`. If Codex is not installed
  on the PC, ask the owner how they want reviews done.
- **Commits:** small, descriptive commits pushed to `main` at
  https://github.com/atashie/three-d-model-generation-; the repo name ends with a hyphen.
  Push access on the PC must be set up by the owner, over SSH or with `gh auth login`.
- **Owner images** are not committed until their rights are confirmed; tests use
  synthetic look-alikes.

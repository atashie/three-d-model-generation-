# Project status

**Last updated:** 2026-11-19 (widen-lines Tasks 1–5 built and pushed; Codex review, Task 5b and Task 6 next; `roadie-mural` paused).

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
  parameters (strict YAML values; `--text STAGE.KEY 'WORDS'` stores owner words exactly,
  with no YAML reading); run each stage not done into `jobs/NAME/<stage>/`,
  driven as the stage commands drive it (tests show the files equal a run by hand,
  except G-code timestamps and their hashes); input keys (`tdmg.jobkey/3`: parameters, upstream
  record hashes, algorithm ids, rules, profiles, and a fingerprint of tdmg's own `.py`
  files and `uv.lock`, so any code change makes every stage stale; a rerun that writes
  the same bytes keeps the confirmations) in `state.json`; a stage whose recorded output
  files are missing or changed, or a changed source, is stale; a rerun goes into
  `<stage>.new/` and replaces the old folder only when its record exists; `--rerun
  STAGE`; a per-job `.lock`.
- **`tdmg job confirm NAME --subject selection|colors|print --owner-said TEXT [--face
  up|down] [--route single|ams|glue] [--date YYYY-MM-DD] [--accept-not-certified] [--corrects N]`**
  (restructure Task 8): appends the owner's verbatim words to `job.yaml` (now
  `tdmg.job/2`; `/1` still read) with the date, revision and covered file hashes; a print
  entry adds the route, face, slice identity and verdicts. Refuses blank words, stages not
  done, files that differ from their records, faces not sliced, and a verdict not
  PRINTABLE without `--accept-not-certified`. Status shows each confirmation current or
  stale, re-hashing the covered files each time. `state.json` (now `tdmg.jobstate/2`)
  holds each stage record's hash, so a hand-edited record makes its stage stale. A print
  confirmation is not permission to purge. `--corrects N` records a correction of a
  misrecorded entry: the earlier entry is kept verbatim but is never current and never
  copied into a library entry as the owner's words (Codex review, 2026-11-17).
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
  (2026-11-17). First run on a real job 2026-11-17 (Roadie, Task 14): rebuild
  matched, published `prints/roadie-drop/`, job purged
  (`research/verification/2026-11-17-first-finish/`).
- **`tdmg library check [NAME]`** and **`tdmg library verify NAME --slicer-dir DIR`**
  (restructure Task 10, `src/tdmg/library.py`): check verifies every entry's files
  against `COMPLETE` (none changed, missing or extra) and its records against each other
  (`STAGED`, `purge.json`, `provenance.json`, `job.yaml`); `source/` or `private/` missing
  entirely is a note ("source unavailable": a clone has neither), exit 0 unless
  `--require-private`; an entry without `COMPLETE`, a `.staging-NAME` folder or a job left
  in `jobs/` is incomplete (run `tdmg finish NAME` again); exit 1 on damage or incomplete.
  verify runs the entry's `job.yaml` and `source/` under today's code and rules in a
  scratch folder, compares with `provenance.json` (record hashes but `slice.json`'s,
  algorithms, verdicts, checks, slice identity, printable-file hashes) and lists what
  changed (commit, versions, rules, algorithms, profiles, PrusaSlicer configured or not);
  exit 0 identical, 1 differs, 2 cannot run. Both run on `prints/roadie-drop` with the
  real slicers (2026-11-17): check ok, verify identical.
- **The make-print skill** (restructure Task 12,
  [`.claude/skills/make-print/SKILL.md`](../.claude/skills/make-print/SKILL.md)): the
  conversation Claude follows when the owner shares an image, from `tdmg job new` to
  `tdmg finish` and `tdmg library check`, with the hard rules (only the owner's own words
  in a confirmation or the purge permission). `tests/test_make_print_skill.py` checks
  that every `tdmg` command, flag and `job set` key in it exists in the CLI, and that the
  same slicer folders are given throughout; it also checks flag values, that every
  STAGE.KEY the text names exists, that each `job set` line is accepted by a temporary
  job, and that commands carrying the owner's words start with `MSYS_NO_PATHCONV=1` and
  single-quote them. Its steps up to the colors stage were run once on a scratch job
  with a test image (2026-11-17, PC); the job, confirmation and finish steps were run
  with the owner for Roadie (Task 14, 2026-11-17).
- **Owner's words verbatim on Windows** (Task 12 quality review, measured 2026-11-17 on
  the PC): Click expanded every argument on Windows (`$HOME`, `%USERNAME%`, `~`, globs),
  even inside shell single quotes. The `tdmg` script and `python -m tdmg.cli` now call
  `tdmg.cli.main()`, which turns that off (`tests/test_entry_point.py`). Git Bash also
  turns a leading `/` into a Windows path (`/yes` became `C:/Program Files/Git/yes`)
  unless `MSYS_NO_PATHCONV=1`; a doubled backslash reached Python as one. The skill says
  how to quote, and to check each read-back. `tdmg finish --dry-run` takes
  `--purge-owner-said` and prints it back as `purge.json` will hold it; the real run
  prints it before writing `purge.json`.
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
| Restructure | **Done** (plan `docs/plans/2026-11-16-restructure.md`, Tasks 0–15, 2026-11-17). First library entry `prints/roadie-drop/` |

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
- **Latest local validation (2026-11-17, PC, restructure Task 10):** `uv run pytest -q`
  gave 3292 passed and 12 skipped (after the Task 10 re-review minors) (8 real-slicer tests; four symlink tests, since this
  account cannot create symlinks; the junction tests ran); `tests/test_library.py` (47
  tests) also passed under `CI=true GITHUB_ACTIONS=true`; `ruff check`, `gen_docs.py --check` and
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
  Roadie AMS file is now the library's `prints/roadie-drop/files/model.3mf` (its legacy
  folder was deleted after the finish, 2026-11-17).
- **Environments:** the core `.venv` uses Python 3.13. TripoSR uses
  `artifacts/triposr-py311` (3.11.15), with sources in `artifacts/TripoSR` and
  `artifacts/torchmcubes` and weights in `artifacts/triposr-data`. Do not recreate
  environments, redownload models or repeat costly trials without checking these first.
  The owner's approvals for that TripoSR setup (checkpoints, compilers) hold for it only;
  they do not authorize unrelated cloud spending or upload batches.

## Next steps, in order

1. **The owner prints figures** (R2 step 5, part 2), now through jobs: share an image
   and Claude follows the make-print skill (`tdmg job new` … `tdmg finish`). Oddie (the
   owner's preferred plan: outline kept, blues and greens merged) is the obvious next
   job; its legacy folders stay in `artifacts/` until then (`docs/design/jobs.md`). The
   first glue print is also the first test of the 0.2 mm glue gap: record how the
   pieces fit and the filament.
2. **Repository restructure: done** (2026-11-17; plan
   `docs/plans/2026-11-16-restructure.md`, Tasks 0–15; see "Handoff: the restructure").
   Deferred from its quality review: one git process per path in `unignored_paths`,
   output hashing on every `job status`, overlapping `library check` messages
   (`research/reviews/2026-11-16-restructure/README.md`). The optional test-suite
   speed-up (about 12 minutes; share built R2 jobs across tests) is not started.
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

9. **`roadie-mural`, paused 2026-11-19 (owner: "Let's pause this work - we will return to
   it later").** A job from a phone photo of a painted school mural (R2, 60 mm wide; the
   thickness of 3 mm is not set yet). State in `jobs/roadie-mural/` (git-ignored):
   - Selection: a mask made by code (not recorded as commands), `roadie-mural-mask-3.png`
     on the owner's OneDrive Desktop. The owner's selection confirmation is **stale**: it
     was given for an earlier mask.
   - Colors: "4 colors, ready" (extract 6; merges [[4, 0], [5, 1]]; outline dropped).
     The owner has not confirmed the colors.
   - Open question: does the owner's "the black is the outline" mean keep the outline?
   - The owner's complaints: white specks on the beak, and scrabbly shoes.
   - **Cause, found in software on this one photo:** the grey fringe on each side of a
     black line quantizes as shaded white. When the outline is dropped, the line goes to
     the nearest color, so white takes most of it. The borders then run along the ragged
     red edge, and leave two beak specks of 0.7 and 0.8 mm² (just above the 0.64 mm²
     island minimum).
   - **Test** (scratchpad simulation on the final labels, judged by eye): the fringe was
     taken as line by growing the dark pixels (max channel < 90) by 4 px (0.13 mm) before
     splitting the line, and the borders were smoothed at 0.21 mm (6.5 px).
     - Result: both beak specks are gone, and the borders run along the middle of the
       lines.
     - With 7 px (0.23 mm), the line starts to cut the thin ring around the lace hole.
     - With no growth and the stronger smoothing alone, the specks stay.
   - Also: `flat.smooth.sigma_px` works in pixels, so on this photo (0.032 mm/px) it
     smooths about 2.7 times less on the print than on Roadie.
   - **Design waiting for the owner's choice:**
     - (A, recommended) new color settings `colors.smooth_mm` and
       `colors.outline_fringe_mm`, off by default, so `roadie-drop` still verifies
       identical;
     - (B) make both the new default;
     - (C) one `colors.source=photo` switch.
   - Also proposed:
     - a list of small pieces, with zoomed crops, in the color review;
     - mask steps recorded as selection commands (cut at a frame edge, drop light pixels
       that touch the outside, fill holes, smooth the outline in mm), since the bumpy
       sole bottoms come from the hand-made mask;
     - a photo acceptance case in `docs/guide/input-interpretation.md`;
     - a photo section in the make-print skill.
   - Small bug: `job set select.remove_at=null` is refused for list keys. Use `[]` to
     clear them before setting `select.mask`.

10. **`colors.thin_lines: widen`: Tasks 1–5 built, reviewed (spec + quality per task)
    and pushed (to 4415fdb); next Task 7's Codex review, then Task 5b, then Task 6.**
    Plan `docs/plans/2026-11-19-widen-lines.md`; design
    `docs/plans/2026-11-19-widen-lines-design.md`; evidence
    `research/verification/2026-11-19-widen-lines/` (with two addenda: find_lines on the
    turkey, and slicing at line widths 0.41–0.6 mm).
    - What exists: rules `color.lines.width` (0.41), `.host_share` (0.9),
      `.min_elongation` (3, length / width); settings `thin_lines` (remove | widen) and
      `line_width_mm`, kept out of colors.json under remove (`recorded_settings`), old
      job.yaml files load (`jobs.ADDED_FIELDS`); `tdmg.color_lines.find_lines` and
      `draw_lines` (MST bridging, closed loops, bounds); colors.json schema
      `tdmg.colors/5` with a `lines` block under widen; verify strict both ways;
      colored_flat draws the recorded lines, no glue then. Under remove everything is
      byte-identical; `tdmg library verify roadie-drop` identical (exit 0).
    - **Codex review running/ran:** `research/reviews/2026-11-19-widen-lines/`
      (`prompt.md`, `codex-review.txt` when done). Verify each finding against the code,
      reproduce with a failing test, fix, record in that folder's README (Task 7).
    - **Task 5b (owner: "to your question: yes"):** a required `F3.line_coverage` so that
      unprinted stretches of widened lines make the verdict NOT CERTIFIED; spec in the
      plan.
    - **Slicing finding:** with the pinned OrcaSlicer, 0.41 mm turkey lines leave gaps up
      to 3.9 mm (face up) / 4.5 mm (face down); full from about 0.6 mm. The owner keeps
      0.41 mm and will test-print it ("1) 0.41 mm and test-print it").
    - **Task 6:** docs (pipeline-and-gate colors section, color-multi attribute page,
      skill step 6 no longer "planned", design marked built), then run
      `roadie-thanksgiving`: `tdmg job set roadie-thanksgiving colors.thin_lines=widen`,
      `job run`, show regions.png and crops, ask for the color confirmation and the
      thickness (original 3 mm), build, slice, explain the verdict (expect NOT CERTIFIED
      from Task 5b at 0.41 mm), and the owner test-prints with `--accept-not-certified`
      only in their own words.
    - The job `roadie-thanksgiving` (git-ignored): R2, 60 mm; origin `generated` only;
      selection `remove_at [[5, 5]]`, `keep_at [[560, 540]]`, tolerance 80, confirmed
      ("perfect!"); colors "4 colors, ready", not confirmed; thickness not set; the pupils
      still join (out of scope).
    - CI: green at fa9215c on all three platforms; at 60929f7 macOS was cancelled by
      GitHub (no runner), Windows and Ubuntu green; 4415fdb not yet checked.

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

- **State:** Tasks 0–15 of `docs/plans/2026-11-16-restructure.md` are done (2026-11-17):
  docs, a Codex review of the built change (10 findings, all fixed; record
  `research/reviews/2026-11-16-restructure/README.md`), and CI green on three OSes at
  `14e92b7` and again at `e6b0a28` (the review fixes) (red on Windows from Task 9 until then: three path tests assumed this PC's
  long-path and ACL behaviour). The restructure is complete; Oddie is the next job to
  finish whenever the owner wants it in the library.
- **Task 12:** the skill asks the public question, runs `finish --dry-run` and shows what
  would be deleted, and only then asks for the purge permission, so the owner sees the
  list before giving it. `job set` reads values as YAML, so the skill puts
  `select.instructions` in YAML single quotes (words with a colon are refused
  otherwise; checked on the scratch job). For R2 it sets `colors.width_mm` first and
  `colored_flat.thickness_mm` only after the colors confirmation, so `job run` stops
  before building from colors the owner has not seen.
- **Task 11:** `tests/conftest.py` maps `roadie-tol30` to the library entry and job
  `roadie-drop` (then its legacy folder) and `oddie` to its legacy folder only. A built
  selection must have band-survival.txt's `selection_id`; a rebuilt one (library or job)
  the mask/cutout pixel hashes of `research/verification/2026-11-17-owner-fixture-pixels/`
  (PNG bytes vary with Pillow/zlib), the legacy copy results.txt's file hashes. A
  present source that a stage refuses or that that differs is passed over with a warning, and the test
  fails when none matches. On the PC (2026-11-17) the owner tests use the legacy folders
  (no `prints/` or `jobs/` yet); a one-off check with a job made from the owner's
  `roadie.png` and the recorded controls rebuilt `selection.json` byte for byte by both
  the library and the job path. Since Task 14 Roadie's legacy folders are gone and its
  owner tests build from `prints/roadie-drop/source/` (git-ignored) or skip.
- **Task 10 decisions** (dated note in the plan's Task 10): "source unavailable" alone
  exits 0, since it is the normal state of every clone; `--require-private` makes it a
  failure for a copied `prints/`. After the spec review, `provenance.json` also holds
  `slice.json`'s hash with its G-code hash fields masked and each G-code file's hash without
  its timestamp line, and `verify` compares them (a G-code body change is a difference);
  it cannot compare the stages' other files or the checks' measured values, and says so.
  A stage the current code refuses exits 1; a slicer missing on this machine exits 2. OS
  files (`.DS_Store`, `._*`, `Thumbs.db`, `desktop.ini`) are damage with their own
  message. `uv.lock` is hashed as git's blob at HEAD. After the re-review, a reformatted
  current `slice.json` is a difference, and a stage failing with an I/O or slicer error is
  worded "failed (possibly the environment)" (still exit 1).
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

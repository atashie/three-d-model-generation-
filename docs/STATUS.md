# Project status

**Last updated:** 2026-11-11 (R2 color step 1 complete: Task 8 docs and Codex review
done; earlier: F6.portability, first PRINTABLE). Phase 1 (R1, flat single-color) is under way,
with three commands, and R2 (flat multicolor) has its first command:

- **`tdmg select`** (S0/S1): selects the subject. The owner confirmed the results.
- **`tdmg flat`** (S2–S4, S8): makes a flat STL, smoothed by default (`--smooth-px 0`
  keeps the exact outline), and gates it.
- **`tdmg slice`** (S9): slices it with a pinned, hash-verified OrcaSlicer 2.5.0 and the
  Bambu A1 profiles. It measures F6 and judges F3 from the printed G-code footprint
  (`F3.printed_connectivity`, `F3.edge_coverage`, `F3.edge_overprint`). With a pinned
  PrusaSlicer 2.9.7 (`--prusaslicer-dir`), it also measures `F6.portability`.
- **`tdmg colors`** (R2 step 1): turns a selection into a reviewed color plan.
  - **Steps:** it extracts 6 colors (CIELAB k-means), handles cartoon outlines (drop
    by default, or keep as a 0.5 mm line), applies the owner's merges, cleans regions
    to printable size and smooths the region borders.
  - **Outputs:** it writes `labels.png`, a `regions.png` preview and a verifiable
    `colors.json`.
  - **Not ready:** when more colors remain than the AMS allows, it marks the plan not
    ready and suggests merges.
  - **Not built yet:** no geometry is made from the plan (design step 2).

The owner's Roadie and Oddie at 60 × 3 mm (smoothed) each give one valid body that slices
to 15 layers (about 8 minutes, 2.3 g and 4.3 g). Both are now **PRINTABLE** (2026-11-11):
every required check passed with the pinned slicers and the A1 profile. That is not a
guarantee: the acceptance tolerance is still a hypothesis, nothing has been measured with
calipers, and strength is not judged. The owner printed this same Roadie STL (Bambu
Studio, matte PLA) and judged it "great" by eye. Not done yet: loop or base, 3MF. The R4
backend is still open.

Keep this page current. A new session reads it right after `CLAUDE.md`, and it is the only memory that travels between machines.

## Where things stand

| Area | State |
|---|---|
| Research | Landscape report (v2.1) and seven historical source notes; Windows/TripoSR/MakerLab results in `research/experiments/2026-11-g3-local-vs-hosted/`. Verification records in `research/verification/` (the 2026-11-10 ones cover selection, flat geometry, smoothing, OrcaSlicer on Windows and thin walls). Independent reviews in `research/reviews/` |
| Plan | `docs/PLAN.md` v2.1, with dated factual notes from 2026-11-10. The owner's decisions are in its section 13. Phase 1 plans are in `docs/plans/` |
| Phase 0 (foundations) | **Baseline and Windows extension verified.** Package `tdmg`, rules with checked citations, A1 printer profile and docs. Local checks and hosted CI pass on Windows, macOS and Linux |
| Phase 1 (R1 flat single-color) | **In progress: three stages work; the owner's two models are PRINTABLE.** `tdmg select` (S0/S1); `tdmg flat` (S2–S4, S8: smoothed or exact outline, cleaning, manifold3d extrusion, gate on the written STL); `tdmg slice` (S9: pinned OrcaSlicer 2.5.0, F6 checks, F3 from the G-code, `F6.portability` with pinned PrusaSlicer 2.9.7; G-code from any FAIL is kept as `.failed`). Functionally tested, and run on the owner's two images on the Windows PC. Verdict for both: PRINTABLE (2026-11-11), with the caveats above. One owner print (Roadie, Bambu Studio's own slice, judged by eye). **Not built:** loop or base, text, 3MF, manifest. Records: `research/verification/2026-11-10-*` and `2026-11-11-prusaslicer-windows/` |
| Photo-to-3D backend (needed for R4) | TripoSR CPU test completed: ten measured runs, 32–35 seconds/model, 3.55–4.00 GiB peak working set. Repeated geometry matches exactly after sorting; OBJ bytes differ. All raw meshes fail topology checks; Roadie's background dominates its shape. See `research/experiments/2026-11-g3-local-vs-hosted/RESULTS-PC.md`. No backend chosen |

## Machines

| Machine | Facts | What has been verified on it |
|---|---|---|
| M5 MacBook | Apple M5, arm64, 16 GB, macOS 26.3, no CUDA | Python 3.13 stack installed and functionally tested (`research/verification/2026-11-08-stack-smoke/`); all tests; wheel build and install. OrcaSlicer is not installed, so `tdmg slice` has not run a real slicer here |
| PC | Windows 11 Pro 10.0.26200 x64; i9-12900K (16 cores/24 threads), 64 GB RAM; Intel UHD 770, no discrete GPU | Core sync, tests, lint, docs, wheel installation and geometry smoke checks passed. Optional import failures recorded in `research/verification/2026-11-09-pc-stack/README.md`. The pinned OrcaSlicer 2.5.0 is installed in `artifacts/tools/orcaslicer-2.5.0/` and the pinned PrusaSlicer 2.9.7 in `artifacts/tools/prusaslicer-2.9.7/`; both are run by `tdmg slice` |

CI includes `macos-15` (arm64), `ubuntu-latest`, and `windows-latest`; the wheel smoke step selects the platform's Python path. All three jobs passed for commit `cc331ad` in [GitHub Actions run 42746111436](https://github.com/atashie/three-d-model-generation-/actions/runs/42746111436), verified on 2026-11-09. The last CI-verified commit is `fdb6e67`, which includes `tdmg slice` (run 42877445218, verified 2026-11-10); the real slicer is not installed in CI. CI passed on all three OSes for `5e87442` (run 42922009479, verified 2026-11-10). That commit includes the F3 thin-wall policy (`slice-3`), the documentation audit and the F3 Codex review fixes; the real slicer is not installed in CI. For `5632ca4` (`F6.portability`, `slice-4`, and the portability Codex review fixes; run 43033039270, checked 2026-11-11), `ubuntu-latest` and `windows-latest` passed; `macos-15` did not run: GitHub cancelled it after no macOS runner picked it up ("The job was not acquired by Runner of type hosted even after multiple attempts"). CI then passed on all three OSes for `c93dfa1`, which adds only this STATUS note to `5632ca4` (run 43035563763, verified 2026-11-11); the real slicers are not installed in CI.

Latest local validation (2026-11-11, Windows PC, R2 step 1 after the Task 8 review fixes):
`uv run pytest -q` gave **1760 passed and 3 skipped**. `uv run ruff check .` and
`uv run python scripts/gen_docs.py --check` passed. CI for the push of R2 step 1: see
below once recorded. Earlier (portability, `slice-4`): 961 passed and 3 skipped,
both plain and with
`CI=true GITHUB_ACTIONS=true`. The three skipped tests are the real-slicer tests, which
passed on their own (3 passed) with the `TDMG_ORCASLICER_DIR=… TDMG_PRUSASLICER_DIR=…
uv run pytest -m slicer` command in `CLAUDE.md`. `uv run ruff check .`,
`uv run python scripts/gen_docs.py --check` and both setup scripts' `--verify-only`
passed. These commits are pushed; for CI see above.

## Next steps, in order

1. **R2 color, step 1 (`tdmg colors`): done, pending CI.** The design is
   `docs/plans/2026-11-11-color-design.md`, and the plan is
   `docs/plans/2026-11-11-color-palette.md`. Tasks 1–8 are done; Task 7 was approved by
   the owner on 2026-11-11 ("amazing work. 1-4 are great").
   - **Task 8:**
     - **Docs:** `docs/print-types/attributes/color-multi.md` (C2) and the
       "Color plans" section of `docs/guide/pipeline-and-gate.md`.
     - **Codex review** of `8a5856e..e74689b`, with 9 findings, all handled
       (`research/reviews/2026-11-11-color-palette/`).
       - The main fix: `verify_colors` now rebuilds the plan from the selection and
         requires identical labels and record. It also requires the recorded rule values
         to be today's and `colors` to be within the printer's cap.
       - A new fate, `band`, and the record schema is now `tdmg.colors/4`. Older plans in
         `artifacts/` are refused; remake them.
       - A subagent review of the fixes found three more gaps, also fixed.
   - **Owner question (open):** the fine map (`smooth_labels`) and R1's outline
     (`smooth_outline`) blur in float32, and their last bits depend on OpenCV's code
     path. Measured: switching OpenCV's optimisations changed the outline of all five
     owner selections and 3 fine pixels in a small test. In float64 the blur was the same
     both ways. Moving both to float64 changes R1's outputs, including the files judged
     PRINTABLE, so the owner decides. `labels.png` and `colors_id` are not affected.
   - **Modules:**
     - `tdmg.color` (quantize, from_labels, clean_regions, open_mask);
     - `tdmg.color_outline` (outline family, drop and keep, shade pairs);
     - `tdmg.color_plan` (`plan_colors`, pure);
     - `tdmg.color_config` (strict config keys: colors, extract, edges, base, outlines,
       outline_color, merge, outline_width_mm);
     - `tdmg.smoothing.smooth_labels`;
     - `tdmg.colors` (`make_colors`, `build_colors`, record schema `tdmg.colors/4`,
       preview);
     - `tdmg.colors_verify.verify_colors` (step 2 must call it with the selection folder;
       it rebuilds the plan, about 1.4 s for the owner's Oddie).
   - **Owner decisions:**
     - colors suggested from the image;
     - a top skin of 0.6 mm;
     - inlay glue pieces;
     - smooth edges by default;
     - outlines dropped by default, with `keep` redrawing the drawing's own lines at 0.5 mm;
     - only pupil-like dark areas survive a drop;
     - shade pairs flagged, never merged automatically;
     - extract 6 colors;
     - the owner prefers Oddie with the outline kept and both shade pairs merged.
   - **Configs used:** `artifacts/colors-runs/configs/`. The previews the owner approved
     are in `artifacts/colors-review-3/` (git-ignored).
   - **All new rules are hypotheses,** untested. They rest on two images, and on one
     example (the pupil) for `color.outline.keep_area_width_ratio`.
   - **Open:** the owner fixtures have not been run on the Mac, so cross-platform parity is
     unverified. Because `verify_colors` rebuilds, a plan made on the PC and checked on
     the Mac is refused if their results differ.
2. **R2 design step 2: colored flat geometry** (`tdmg flat --colors`).
   - **What it builds:** the base and top-skin inlays, plus the glue pieces with pockets.
   - **What it inherits:** the requirements in the color design's section "Requirements
     step 2 inherits from step 1".
   - **What follows:** steps 3–5 (3MF writer, AMS slicing with the face-up/face-down
     measurement, then prints).
3. **Caliper measurements,** if the owner gets calipers: three named dimensions within
   `acceptance.dimension.tolerance` (still a hypothesis), logged as a calibration.
4. **R1 features and 3MF:** the keychain loop or base, then 3MF output with a UUID
   identity scheme.
5. **Roadie's roughness (open):** the owner finds Roadie's smoothed edge "close but
   still a bit rough", acceptable for now. Options: a per-image `--smooth-px`, or a
   better source image.
6. **R4 backend (open):** help the owner choose under their decision rule: a cheap
   standard service, around $1 per model, beats a homemade pipeline if it does
   everything we need.

## Done so far (history)

- **F6.portability (2026-11-11):** PrusaSlicer 2.9.7 pinned and hash-verified
  (`profiles/slicers/prusaslicer-2.9.7.yaml`, `scripts/setup_prusaslicer.py`); its CLI
  measured on Windows (`research/verification/2026-11-11-prusaslicer-windows/`). In
  `tdmg slice` (`slice-4`), `F6.portability` checks PrusaSlicer's `--info` read of
  `model.stl` (manifold, parts, facets, sizes, volume) and its slice: a complete G-code
  with extrusion on every layer at its height, given the A1 bed, nozzle, layer and
  filament settings (the rest are PrusaSlicer's defaults). Both slicers read STL with
  admesh, so for STL this shows a second slicer accepts the file, not an independent
  reader; 3MF output must re-check. Controls: an open cube and an outside-bed part FAIL
  it, as do cut or comment-only versions of the real G-code. Roadie and Oddie are
  PRINTABLE. Codex critical review: three findings, all fixed
  (`research/reviews/2026-11-11-portability/`). Plan:
  `docs/plans/2026-11-11-portability-check.md`.

- **PC setup (2026-11-09):** completed locally, with optional failures documented in
  `research/verification/2026-11-09-pc-stack/README.md`. PyMeshLab, Open3D,
  rembg/ONNX Runtime and bpy fail to import in the tested environment; orca123d and
  MeshLib import.
- **Local CPU test:** completed for TripoSR in the isolated `artifacts/triposr-py311`
  (Python 3.11.15); see `RESULTS-PC.md` and `CPU-PREFLIGHT.md` in
  `research/experiments/2026-11-g3-local-vs-hosted/`. SF3D remains gated;
  Pixal3D/Hunyuan3D CPU-only Windows support was not established. No hosted uploads,
  GPU rental or printing in that experiment.
- **Option walk-through for R4:** option 4 (renting a GPU) is unnecessary for now
  (`OPTION-4-GPU-RENTAL.md`). Option 5 (Bambu MakerLab): the owner's two STLs pass
  measured closed-topology tests, each with two bodies; engine, cost and settings are
  unknown (`MAKERLAB-RESULTS.md`). `artifacts/makerlab/roadie-bird-only.stl` drops the
  frame and is a flat-backed relief. Awaiting the owner's view on refining Oddie.
- **Subject selection (`tdmg select`):** plan
  `docs/plans/2026-11-10-subject-selection.md`, executed. `tdmg select IMAGE --out DIR
  [--instructions TEXT] [--remove-at X,Y]... [--keep-at X,Y]... [--tolerance T]
  [--alpha-min A] [--mask FILE]` writes `mask.png`, `cutout.png`, `preview.png` and
  `selection.json`. Roadie at tolerance 30 gives one 74,768 px bird; Oddie, from its
  transparency, one 298,172 px piece; repeat runs are byte-identical; the owner
  confirmed both. Codex review: `research/reviews/2026-11-10-selection/`.
- **Flat geometry (`tdmg flat`):** plan `docs/plans/2026-11-10-flat-geometry.md`,
  executed. At 60 × 3 mm, one body each; repeat runs are byte-identical. Codex review:
  `research/reviews/2026-11-10-flat/`.
- **Outline smoothing:** plan `docs/plans/2026-11-10-outline-smoothing.md`, executed.
  Gaussian blur by `flat.smooth.sigma_px` (2.5 px), then a contourpy iso-contour;
  warnings only on topology changes. Owner's view in Bambu Studio: Oddie perfect,
  Roadie close but a bit rough. Record:
  `research/verification/2026-11-10-outline-smoothing/`; review:
  `research/reviews/2026-11-10-smoothing/`.
- **Slicer check (`tdmg slice`):** plan `docs/plans/2026-11-10-slicer-check.md`,
  executed. Setup: `uv run python scripts/setup_orcaslicer.py --dest
  artifacts/tools/orcaslicer-2.5.0` (Windows x64; `--verify-only DIR` rechecks).
  Record: `research/verification/2026-11-10-orcaslicer-windows/`; review:
  `research/reviews/2026-11-10-slicer/`.
- **First physical print (owner, reported 2026-11-10):** "I printed roadie and it looks
  great." Printed `artifacts/flat-runs/roadie-tol30-60x3-s3/model.stl` (smoothed,
  60 × 3 mm; sha256 3d5d2601…6d653), sliced in Bambu Studio with its standard settings,
  in matte PLA. The tdmg G-code was not used. No calipers, so
  `acceptance.dimension.tolerance` is unchecked; by eye, the thin spike tips printed
  acceptably.
- **Thin-wall policy (F3):** plan `docs/plans/2026-11-10-thin-wall-policy.md`. The owner
  approved Decisions 2 and 2a: add the reverse (overprint) check, and keep sharp corners
  strict. `src/tdmg/printed.py` models every extruding move as a bead and compares each
  layer's footprint with the model section. Roadie and Oddie: connectivity PASS on
  15/15 layers; worst edge gap 0.231 / 0.222 mm, on the first layer (allowance
  0.275 mm); worst overprint 0.013 mm. Limits: pinned OrcaSlicer A1 profile only,
  strength not judged, sharp corners strict, printed-over holes of 0.4 mm or less not
  seen. Record: `research/verification/2026-11-10-thin-walls/` (see its addendum). No
  Codex review yet.
- Owner images are not committed until their rights are confirmed; the tests use
  synthetic look-alikes.

## Open questions for the owner

| Question | State |
|---|---|
| Hosted API keys (Replicate, fal) | Still deferred; local results are now available, but no hosted batch has been authorized |
| Is a monthly plan acceptable for a commercial API, such as Meshy's $20 Pro plan? | Not answered |
| Use Meshy's free printability check as a second opinion? It means uploading the mesh | Not answered |
| Photo privacy with hosted services, and their data and training terms | Uploading is allowed for now. **Marked to revisit** |
| The PC's OS | Verified: Windows 11 Pro x64, build 26200 |
| MakerLab engine/version, credits, settings, uploaded input provenance | Unknown; owner supplied STLs, not generation metadata |
| Oddie shape acceptance and desired Roadie depth/form | Not explicitly settled. Extracted Roadie is a flat-backed relief; do not silently convert it to a full figurine |

## Owner decisions, in short

The full list is in `docs/PLAN.md` section 13.
- **Printer:** Bambu Lab A1. Bambu Studio is the owner's slicer.
- **Portable files:** print files must not depend on the AMS unit or the slicer. They use standard 3MF, name colors rather than slots, and ship a palette manifest.
- **Jobs default to at most 4 filaments,** the AMS lite's slot count. A job declares its real cap.
- **Licence and use:** personal use; the repo is MIT. The owner is in the US.
- **Roadmap order:** R1 → R2 → R3 → R4. A command-line tool and Python library first.
- **Photo-to-3D:** local is preferred. Hosted models are fine to try, and most work will be simple objects.
- **GPU rental:** unnecessary for now, per owner.
- **Interpretation:** user wants plain-language subject/exclusion instructions; keep Roadie's bird and ignore its grey background. Implemented as explicit selection (`tdmg select`): text is recorded verbatim, and points or a mask apply it. No change to default no-LLM runtime policy.
- **First R1 step:** subject selection first (2026-11-10). Interpretation via explicit controls was accepted; a phrase grammar or opt-in LLM can come later.
- **First flat size:** 60 mm wide, 3 mm thick, for Roadie and Oddie (2026-11-10).
- **OrcaSlicer:** the owner approved installing it on the PC when the slicer plan starts (2026-11-10).
- **Thin-wall rule (F3):** judge thin features from what the slicer prints (Decision 2 of the thin-wall plan); add the reverse overprint check and keep sharp corners strict (Decision 2a, 2026-11-10).

## Compaction handoff

- **Latest session (2026-11-10):**
  - **Built and reviewed, then pushed with green CI (up to `fdb6e67`):** `tdmg select`,
    `tdmg flat`, outline smoothing and `tdmg slice`. Each had subagent spec and quality
    reviews and a Codex review. The A1 profiles are flattened from the pinned v2.5.0
    source and kept out of the repo (AGPL).
  - **F3 thin-wall policy** (`src/tdmg/printed.py`; three required F3 checks in `tdmg
    slice`, `slice-3`). It had subagent reviews, a documentation audit and a Codex critical
    review; all seven Codex findings were fixed
    (`research/reviews/2026-11-10-thin-walls/`).
  - **Known costs and limits:** slices take about 10–14 s. Nearly symmetric parts can be
    "placement ambiguous" (UNKNOWN).
  - **Pushed and CI-verified:** `5e87442` (run 42922009479).
- **Start next session:** read `CLAUDE.md`, this page, `docs/PLAN.md`, then the plans in
  `docs/plans/` (the latest is the thin-wall policy).
  - The CLI has `select`, `flat` and `slice`. It has no 3MF, loop or base, second
    slicer, or language interpreter.
  - The local outputs are in `artifacts/selection-runs/`, `artifacts/flat-runs/` and
    `artifacts/slice-runs/` (the F3 runs are `*-60x3-f3`). The pinned slicer is in
    `artifacts/tools/orcaslicer-2.5.0/`.
  - The real-slicer test runs with `TDMG_ORCASLICER_DIR=artifacts/tools/orcaslicer-2.5.0
    uv run pytest -m slicer`.
- **Evidence for R4:** read `RESULTS-PC.md` and `MAKERLAB-RESULTS.md` in the experiment
  directory. Local TripoSR: fast, repeatable geometry, invalid raw topology. MakerLab:
  both supplied meshes pass measured closed-topology checks but each has two bodies.
  Neither route is certified printable, and neither was sliced or printed.
- **Local data, not in Git:** original images in
  `C:/Users/arikt/Downloads/three-d-test/`; original STLs in its `makersLabModels/`
  subfolder. Raw generated meshes in `artifacts/triposr-runs/`; derived bird-only
  STL and preview in `artifacts/makerlab/`. The derived STL preserves every retained
  triangle. All `artifacts/` content and the Downloads inputs remain local; tracked
  hashes, scripts and preview sheets document/reproduce the operations when inputs exist.
- **Environments:** core `.venv` uses Python 3.13; generation uses
  `artifacts/triposr-py311` (3.11.15). Source checkouts are `artifacts/TripoSR` and
  `artifacts/torchmcubes`; weights/configs in `artifacts/triposr-data`.
  Do not recreate environments, redownload models or repeat costly trials without
  checking these existing artifacts first.
- **Review corrections:** Trimesh component splitting can repair temporary copies;
  future inspection disables this. Original CPU component volumes are qualified
  in the results; whole-mesh topology/exports unaffected. First chair memory sample
  watched only the Windows launcher and was discarded; corrected ten-run batch is authoritative.
- **Pending decisions:** intended output form, whether to refine Oddie, MakerLab
  generation metadata, and R4 backend choice. R1 remains the first implementation
  phase in the roadmap. Existing checkpoint/compiler approvals persist for that
  approved setup; they do not authorize unrelated cloud spending or upload batches.

## How this project works

- **Owner:** a data scientist who is new to 3D printing. Explain 3D concepts plainly.
- **Evidence over priors:** never fill a gap with an assumption. Say what was verified, how, and what was not.
- **Code decides:** the default pipeline has no LLM calls.
- **Independent review:** after each meaningful change, the previous sessions ran an independent read-only review with the OpenAI Codex CLI, verified each finding against its source before applying it, and recorded the handling in `research/reviews/`. If Codex is not installed on the PC, ask the owner how they want reviews done.
- **Commits:** small, descriptive commits pushed to `main` at https://github.com/atashie/three-d-model-generation-; the repo name ends with a hyphen. Push access on the PC must be set up by the owner, over SSH or with `gh auth login`.

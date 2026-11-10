# Project status

**Last updated:** 2026-11-10. Phase 1 is under way, with three commands:

- **`tdmg select`** (S0/S1): selects the subject. The owner confirmed the results.
- **`tdmg flat`** (S2–S4, S8): makes a flat STL, smoothed by default, and gates it.
- **`tdmg slice`** (S9): slices it with a pinned, hash-verified OrcaSlicer 2.5.0 and the
  Bambu A1 profiles, measuring F6.

The owner's Roadie and Oddie at 60 × 3 mm each give one valid body that slices to 15
layers (about 8 minutes, 2.3 g and 4.3 g). The certification is NOT CERTIFIED:
F3.thin_regions UNKNOWN (no thin-wall policy) and F6.portability UNKNOWN (no second
slicer). Not done yet: loop or base, 3MF, the F3 policy, PrusaSlicer, and printing. The
R4 backend is still open.

Keep this page current. A new session reads it right after `CLAUDE.md`, and it is the only memory that travels between machines.

## Where things stand

| Area | State |
|---|---|
| Research | Landscape report (v2.1) and seven historical source notes; Windows/TripoSR/MakerLab results in `research/experiments/2026-11-g3-local-vs-hosted/`. Independent reviews in `research/reviews/2026-11-09-codex/`, `research/reviews/2026-11-09-pc/` and `research/reviews/2026-11-10-selection/` |
| Plan | `docs/PLAN.md` v2.1 adds plain-language image interpretation and a reviewable subject mask. The owner's decisions are in its section 13 |
| Phase 0 (foundations) | **Baseline and Windows extension verified.** Package `tdmg`, 26 rules with checked citations (28 since Phase 1), A1 printer profile and docs. Local checks and hosted CI pass on Windows, macOS and Linux |
| Phase 1 (R1 flat single-color) | **Started.** `tdmg select` (S0 intake and S1 subject selection) is implemented and tested. It ran on both owner images, and the owner confirmed the results. See `docs/guide/input-interpretation.md` and `research/verification/2026-11-10-subject-selection/`. **`tdmg flat` (2026-11-10)** has the following parts:
  - an exact pixel-cell outline, an explicit transform, and cleaning by the rules;
  - manifold3d extrusion;
  - a gate on the written STL: F1 topology, including pinched vertices; F2 size and
    export match; F3 measured as UNKNOWN; F4; F5; F6 UNKNOWN.

  See `research/verification/2026-11-10-flat-geometry/`. **`tdmg slice` (2026-11-10)**
  slices with a pinned OrcaSlicer 2.5.0 and measures F6; see
  `research/verification/2026-11-10-orcaslicer-windows/`. Not started: the loop or base,
  3MF, the F3 policy, PrusaSlicer, and printing. |
| Photo-to-3D backend (needed for R4) | TripoSR CPU test completed: ten measured runs, 32–35 seconds/model, 3.55–4.00 GiB peak working set. Repeated geometry matches exactly after sorting; OBJ bytes differ. All raw meshes fail topology checks; Roadie's background dominates its shape. See `research/experiments/2026-11-g3-local-vs-hosted/RESULTS-PC.md`. No backend chosen |

## Machines

| Machine | Facts | What has been verified on it |
|---|---|---|
| M5 MacBook | Apple M5, arm64, 16 GB, macOS 26.3, no CUDA | Python 3.13 stack installed and functionally tested (`research/verification/2026-11-08-stack-smoke/`); all tests; wheel build and install |
| PC | Windows 11 Pro 10.0.26200 x64; i9-12900K (16 cores/24 threads), 64 GB RAM; Intel UHD 770, no discrete GPU | Core sync, 133 tests, lint, docs, wheel installation and geometry smoke checks passed. Optional import failures recorded in `research/verification/2026-11-09-pc-stack/README.md` |

CI includes `macos-15` (arm64), `ubuntu-latest`, and `windows-latest`; the wheel smoke step selects the platform's Python path. All three jobs passed for commit `cc331ad` in [GitHub Actions run 42746111436](https://github.com/atashie/three-d-model-generation-/actions/runs/42746111436), verified on 2026-11-09.

Latest local validation (2026-11-10, Windows PC, after the slicer check): **682 tests
passed and 1 skipped** (the real-slicer test, which runs only when
`TDMG_ORCASLICER_DIR` is set; it passed locally). Both plain and
`CI=true GITHUB_ACTIONS=true` runs passed, as did `ruff check .` and the
generated-doc check. CI passed on all three OSes for `fdb6e67`, which includes
`tdmg slice` (run 42877445218, verified 2026-11-10). That was the first CI run of
the POSIX timeout tree-kill path, and the fake-slicer tests passed on macOS and Linux.
The real slicer is not installed in CI.

## Next steps, in order

1. **Set up and verify on the PC — completed locally, with optional failures documented.** See `research/verification/2026-11-09-pc-stack/README.md`. All requested optional packages installed; PyMeshLab, Open3D, rembg/ONNX Runtime and bpy fail to import in the tested environment. Orca123d and MeshLib import. Historical verification checklist:
   - Record the OS, CPU, RAM, disk, and Python and uv versions in a new `research/verification/<date>-pc-stack/README.md`.
   - Run `uv sync` and `uv run pytest`.
   - Check which optional packages install on this platform: pymeshlab, open3d, rembg with onnxruntime, bpy, orca123d, meshlib.
   - Rerun the smoke scripts in `research/verification/2026-11-08-stack-smoke/` and note any differences.
   - Add the PC's OS to CI if it is not covered.
2. **Local CPU test — completed for TripoSR; other candidates not run.** Results and limitations are in `research/experiments/2026-11-g3-local-vs-hosted/RESULTS-PC.md`. Historical preparation and remaining candidate constraints:
   - Historical preflight is in `research/experiments/2026-11-g3-local-vs-hosted/CPU-PREFLIGHT.md`. TripoSR checkpoint approval was granted and the trial completed. SF3D remains gated; Pixal3D/Hunyuan3D CPU-only Windows support was not established by their READMEs.
   - Owner approved the official TripoSR checkpoint and 30 minutes/model, and supplied `Downloads/three-d-test/oddie.png` and `roadie.png` (cartoons, not object photographs). Source commits and binary dependencies prepared in isolated `artifacts/triposr-py311` (Python 3.11.15).
   - Owner approved C++ Build Tools and reviewed torchmcubes/ANTLR builds; all installed successfully. Checkpoint verified and loaded with `weights_only=True`. Inference and auxiliary-model imports work in isolated Python 3.11.15. This local experiment made no hosted uploads, GPU rental, slicing or printing. Raw exported meshes were preserved; historical component-volume diagnostics have a documented Trimesh implicit-repair caveat. Repairability is still unproven.
3. **Next: discuss local results and continue the option walk-through:**
   - option 4, renting a GPU: owner agrees it is unnecessary for now. Current-price walkthrough is in `research/experiments/2026-11-g3-local-vs-hosted/OPTION-4-GPU-RENTAL.md`. No spending or uploads.
   - option 5, Bambu MakerLab: owner supplied `Downloads/three-d-test/makersLabModels/oddie.stl` and `roadie.stl`. Both pass measured closed-topology tests, each has two bodies. Engine/cost/settings unknown; no slicing or printing verified. See `research/experiments/2026-11-g3-local-vs-hosted/MAKERLAB-RESULTS.md`. Derived `artifacts/makerlab/roadie-bird-only.stl` omits the disconnected frame and preserves the bird exactly; it remains a flat-backed relief.
   - Owner requirement: accept plain-language interpretation such as "keep the roadrunner bird, ignore the grey background" before generation. **Explicit selection is implemented as `tdmg select`** (text recorded verbatim; points or a mask apply it). `cutout.png` is the prepared input for any generator, including MakerLab. No language interpreter exists.
   - Await owner's assessment of whether Oddie's shape is worth refining; topology repairability is not yet measured.

   Then help the owner choose the R4 backend under their decision rule: a cheap standard service, around $1 per model, beats a homemade pipeline if it does everything we need.
4. **Phase 1, R1 vertical slice,** as in `docs/PLAN.md` section 11. Its first test fixtures are the prototype defects listed in `research/verification/2026-11-08-stack-smoke/README.md` section 5.
   - **2026-11-10: subject selection (S0/S1) is done.** The plan, `docs/plans/2026-11-10-subject-selection.md`, is executed, with execution notes. The command:
     - `tdmg select IMAGE --out DIR [--instructions TEXT] [--remove-at X,Y]... [--keep-at X,Y]... [--tolerance T] [--alpha-min A] [--mask FILE]`.
     - It writes `mask.png`, `cutout.png`, `preview.png` and `selection.json` (with hashes, `selection_id`, library versions, and `machine_interpreted: false`).
   - Results on the owner's images (in the git-ignored `artifacts/selection-runs/`):
     - Roadie at tolerance 30 gives one 74,768 px bird.
     - Oddie, from its own transparency, gives one 298,172 px piece.
     - The counts equal the planning measurements, and a repeated run was byte-identical.
     - The owner confirmed both selections.
   - **Reviews:** each task had a spec review and a code-quality review; then an independent Codex review found 7 issues. All were verified and fixed; see `research/reviews/2026-11-10-selection/README.md`.
   - **2026-11-10: flat geometry (`tdmg flat`) is done.** The plan is
     `docs/plans/2026-11-10-flat-geometry.md`, executed with notes.
     - It ran on the owner's selections at the owner's chosen 60 × 3 mm: Roadie gave
       37,148 triangles and Oddie 33,248, one body each, and repeat runs were byte for
       byte identical.
     - Reviews: each task had subagent spec and quality reviews; then an independent
       Codex review. See `research/reviews/2026-11-10-flat/`.
     - Pending from the owner: whether Bambu Studio imports
       `artifacts/flat-runs/*-60x3-a/model.stl` as one piece at about 60 mm. This is a
       manual check, not F6.
   - **2026-11-10: outline smoothing is done.** The owner found the 60 mm Roadie's border
     jagged in Bambu Studio, although it imported correctly as one piece at the right
     size.
     - `tdmg.smoothing`, a standalone module, now runs by default in `tdmg flat`:
       Gaussian blur by `flat.smooth.sigma_px` (2.5 px), then a contourpy iso-contour.
       `--smooth-px 0` keeps the exact outline.
     - Warnings fire only on topology changes.
     - Plan: `docs/plans/2026-11-10-outline-smoothing.md`. Record:
       `research/verification/2026-11-10-outline-smoothing/`.
     - Owner's view in Bambu Studio (2026-11-10): Oddie is perfect; Roadie is close but
       still a bit rough, and acceptable for now. This remains an open item: perhaps
       a per-image `--smooth-px`, or a better source image.
   - **First physical print (owner, reported 2026-11-10):** "I printed roadie and it looks great."
     - Printed: `artifacts/flat-runs/roadie-tol30-60x3-s3/model.stl` (smoothed, 60 × 3 mm;
       sha256 3d5d2601…6d653), sliced in Bambu Studio with its standard settings, in
       matte PLA. The tdmg G-code was not used.
     - The owner has no calipers, so `acceptance.dimension.tolerance` is unchecked. Visual
       judgement only: the thin spike tips (the F3 regions) printed acceptably by eye.
   - **Next, in order:**
     1. **Done 2026-11-10: the slicer check (`tdmg slice`).**
        - Plan: `docs/plans/2026-11-10-slicer-check.md`.
        - Evidence: `research/verification/2026-11-10-orcaslicer-windows/`.
        - Setup: `scripts/setup_orcaslicer.py`, which installs into the git-ignored
          `artifacts/tools/orcaslicer-2.5.0`.
     2. An F3 thin-wall pass/fail policy, based on research into how the slicer prints
        narrow regions. The G-code and statistics are now available to measure it.
     3. A first physical print and caliper check (`acceptance.dimension.tolerance`). The
        G-code exists, so the owner can print a slice now if they want. It is still NOT
        CERTIFIED.
     4. R1 features (keychain loop or base) and 3MF output with a UUID identity scheme.
     5. The F6 portability check with PrusaSlicer.
   - Owner images are not committed until their rights are confirmed; the tests use synthetic look-alikes.

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

## Compaction handoff

- **Latest session (2026-11-10):**
  - **Subject selection:** `tdmg select` was built, reviewed and pushed, and CI is
    green.
  - **Flat geometry:** `tdmg flat` was built by subagents with two reviews per task,
    reviewed by Codex, and run on the owner's selections.
  - **Outline smoothing and the slicer check:** both were built and reviewed the same
    way. The owner approved the OrcaSlicer install. The A1 profiles are flattened from
    the pinned v2.5.0 source and kept out of the repo (AGPL).
  - **Pushing:** the owner said "push, then proceed" for this line of work. Push after
    the Codex findings are handled, then confirm that CI passes.
- **Start next session:** read `CLAUDE.md`, this page, `docs/PLAN.md`, then the two
  plans in `docs/plans/`.
  - The CLI has `select`, `flat` and `slice`. It has no 3MF, loop or base, second
    slicer, or language interpreter.
  - The local outputs are in `artifacts/selection-runs/`, `artifacts/flat-runs/` and
    `artifacts/slice-runs/`. The pinned slicer is in `artifacts/tools/orcaslicer-2.5.0/`.
  - The real-slicer test runs with `TDMG_ORCASLICER_DIR=artifacts/tools/orcaslicer-2.5.0
    uv run pytest -m slicer`.
- **Evidence:** read `RESULTS-PC.md` and `MAKERLAB-RESULTS.md` in the experiment
  directory. Local TripoSR: fast, repeatable geometry, invalid raw topology.
  MakerLab: both supplied meshes pass measured closed-topology checks but each
  has two bodies. Neither route is certified printable; no slicer run or print verified.
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

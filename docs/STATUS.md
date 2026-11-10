# Project status

**Last updated:** 2026-11-10: subject-selection implementation plan written (next steps, item 4); nothing implemented yet. Previous update 2026-11-09, after inspecting owner-supplied MakerLab STLs. Both pass the measured closed-topology tests but contain two bodies. Roadie's unwanted frame was removed in a separate derived STL. Plain-language subject interpretation added to the plan; implementation pending. Backend choice remains open.

Keep this page current. A new session reads it right after `CLAUDE.md`, and it is the only memory that travels between machines.

## Where things stand

| Area | State |
|---|---|
| Research | Landscape report (v2.1) and seven historical source notes; Windows/TripoSR/MakerLab results in `research/experiments/2026-11-g3-local-vs-hosted/`. Independent reviews in `research/reviews/2026-11-09-codex/` and `research/reviews/2026-11-09-pc/` |
| Plan | `docs/PLAN.md` v2.1 adds plain-language image interpretation and a reviewable subject mask. The owner's decisions are in its section 13 |
| Phase 0 (foundations) | **Baseline and Windows extension verified.** Package `tdmg`, 26 rules with checked citations, A1 printer profile and docs. Local checks and hosted CI pass on Windows, macOS and Linux |
| Phase 1 (R1 flat single-color) | Not started |
| Photo-to-3D backend (needed for R4) | TripoSR CPU test completed: ten measured runs, 32–35 seconds/model, 3.55–4.00 GiB peak working set. Repeated geometry matches exactly after sorting; OBJ bytes differ. All raw meshes fail topology checks; Roadie's background dominates its shape. See `research/experiments/2026-11-g3-local-vs-hosted/RESULTS-PC.md`. No backend chosen |

## Machines

| Machine | Facts | What has been verified on it |
|---|---|---|
| M5 MacBook | Apple M5, arm64, 16 GB, macOS 26.3, no CUDA | Python 3.13 stack installed and functionally tested (`research/verification/2026-11-08-stack-smoke/`); all tests; wheel build and install |
| PC | Windows 11 Pro 10.0.26200 x64; i9-12900K (16 cores/24 threads), 64 GB RAM; Intel UHD 770, no discrete GPU | Core sync, 133 tests, lint, docs, wheel installation and geometry smoke checks passed. Optional import failures recorded in `research/verification/2026-11-09-pc-stack/README.md` |

CI includes `macos-15` (arm64), `ubuntu-latest`, and `windows-latest`; the wheel smoke step selects the platform's Python path. All three jobs passed for commit `cc331ad` in [GitHub Actions run 42746111436](https://github.com/atashie/three-d-model-generation-/actions/runs/42746111436), verified on 2026-11-09.

Latest local pre-commit validation (2026-11-09): `uv sync --locked`, **135 tests
passed**, `ruff check .`, generated-doc check and `git diff --check` passed.
Earlier 133-test counts below are the original stack-verification record.

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
   - Owner requirement: accept plain-language interpretation such as "keep the roadrunner bird, ignore the grey background" before generation. Planned S0/S1 selection and cutout preview documented in `docs/guide/input-interpretation.md`; no interpreter implemented yet.
   - Await owner's assessment of whether Oddie's shape is worth refining; topology repairability is not yet measured.

   Then help the owner choose the R4 backend under their decision rule: a cheap standard service, around $1 per model, beats a homemade pipeline if it does everything we need.
4. **Phase 1, R1 vertical slice,** as in `docs/PLAN.md` section 11. Its first test fixtures are the prototype defects listed in `research/verification/2026-11-08-stack-smoke/README.md` section 5.
   - **2026-11-10: owner chose to start Phase 1 with subject selection (S0/S1).** The plan is `docs/plans/2026-11-10-subject-selection.md`, and it is not yet implemented. It adds `tdmg select`, where the user's words are recorded verbatim and code applies explicit `--remove-at`/`--keep-at` points or a corrected mask. Measurements behind its design are in `research/verification/2026-11-10-subject-selection/`:
     - Roadie's disc is opaque, so its transparency does not isolate the bird.
     - Removing the disc from one seed point, then keeping the bird piece, leaves one 74,768 px bird at tolerance 30.
     - Oddie is one piece at every alpha cutoff.
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
- **Interpretation:** user wants plain-language subject/exclusion instructions; keep Roadie's bird and ignore its grey background. Planned, not implemented. No change to default no-LLM runtime policy.

## Compaction handoff

- **Immediate user instruction:** documentation and experiment records committed
  and pushed (`c93f82a`, `cc331ad`); compaction handoff prepared. Do not start a new experiment or choose the next
  implementation step; discuss that with the owner after the handoff.
- **Release verification:** all three GitHub Actions jobs passed for `cc331ad`
  (run linked above), including the new Windows job. Windows core acceptance is
  complete; optional-package failures and experimental backend limits still apply.
- **Start next session:** read `CLAUDE.md`, this page, then `docs/PLAN.md` and
  `docs/guide/input-interpretation.md`. The pipeline/CLI currently has foundations
  only; no production image-generation command or language interpreter exists.
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

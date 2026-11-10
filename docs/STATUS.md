# Project status

**Last updated:** 2026-11-10 (documentation audit after the F3 thin-wall policy). Phase 1
(R1, flat single-color) is under way, with three commands:

- **`tdmg select`** (S0/S1): selects the subject. The owner confirmed the results.
- **`tdmg flat`** (S2–S4, S8): makes a flat STL, smoothed by default (`--smooth-px 0`
  keeps the exact outline), and gates it.
- **`tdmg slice`** (S9): slices it with a pinned, hash-verified OrcaSlicer 2.5.0 and the
  Bambu A1 profiles. It measures F6 and judges F3 from the printed G-code footprint
  (`F3.printed_connectivity`, `F3.edge_coverage`, `F3.edge_overprint`).

The owner's Roadie and Oddie at 60 × 3 mm (smoothed) each give one valid body that slices
to 15 layers (about 8 minutes, 2.3 g and 4.3 g) and passes every F3 check. Both are **NOT
CERTIFIED: F6.portability UNKNOWN** (no second slicer). The owner printed Roadie (Bambu
Studio, matte PLA) and judged it "great" by eye; there are no caliper measurements. Not
done yet: PrusaSlicer, loop or base, 3MF. The R4 backend is still open.

Keep this page current. A new session reads it right after `CLAUDE.md`, and it is the only memory that travels between machines.

## Where things stand

| Area | State |
|---|---|
| Research | Landscape report (v2.1) and seven historical source notes; Windows/TripoSR/MakerLab results in `research/experiments/2026-11-g3-local-vs-hosted/`. Verification records in `research/verification/` (the 2026-11-10 ones cover selection, flat geometry, smoothing, OrcaSlicer on Windows and thin walls). Independent reviews in `research/reviews/` |
| Plan | `docs/PLAN.md` v2.1, with dated factual notes from 2026-11-10. The owner's decisions are in its section 13. Phase 1 plans are in `docs/plans/` |
| Phase 0 (foundations) | **Baseline and Windows extension verified.** Package `tdmg`, rules with checked citations, A1 printer profile and docs. Local checks and hosted CI pass on Windows, macOS and Linux |
| Phase 1 (R1 flat single-color) | **In progress: three stages work; nothing is certified.** `tdmg select` (S0/S1); `tdmg flat` (S2–S4, S8: smoothed or exact outline, cleaning, manifold3d extrusion, gate on the written STL); `tdmg slice` (S9: pinned OrcaSlicer 2.5.0, F6 checks, F3 from the G-code; G-code from any FAIL is kept as `plate_1.gcode.failed`). Functionally tested, and run on the owner's two images on the Windows PC. Verdict for both: NOT CERTIFIED, F6.portability UNKNOWN. One owner print (Roadie, Bambu Studio's own slice, judged by eye). **Not built:** PrusaSlicer check, loop or base, text, 3MF, manifest. Records: `research/verification/2026-11-10-*` |
| Photo-to-3D backend (needed for R4) | TripoSR CPU test completed: ten measured runs, 32–35 seconds/model, 3.55–4.00 GiB peak working set. Repeated geometry matches exactly after sorting; OBJ bytes differ. All raw meshes fail topology checks; Roadie's background dominates its shape. See `research/experiments/2026-11-g3-local-vs-hosted/RESULTS-PC.md`. No backend chosen |

## Machines

| Machine | Facts | What has been verified on it |
|---|---|---|
| M5 MacBook | Apple M5, arm64, 16 GB, macOS 26.3, no CUDA | Python 3.13 stack installed and functionally tested (`research/verification/2026-11-08-stack-smoke/`); all tests; wheel build and install. OrcaSlicer is not installed, so `tdmg slice` has not run a real slicer here |
| PC | Windows 11 Pro 10.0.26200 x64; i9-12900K (16 cores/24 threads), 64 GB RAM; Intel UHD 770, no discrete GPU | Core sync, tests, lint, docs, wheel installation and geometry smoke checks passed. Optional import failures recorded in `research/verification/2026-11-09-pc-stack/README.md`. The pinned OrcaSlicer 2.5.0 is installed in `artifacts/tools/orcaslicer-2.5.0/` and run by `tdmg slice` |

CI includes `macos-15` (arm64), `ubuntu-latest`, and `windows-latest`; the wheel smoke step selects the platform's Python path. All three jobs passed for commit `cc331ad` in [GitHub Actions run 42746111436](https://github.com/atashie/three-d-model-generation-/actions/runs/42746111436), verified on 2026-11-09. The last CI-verified commit is `fdb6e67`, which includes `tdmg slice` (run 42877445218, verified 2026-11-10); the real slicer is not installed in CI. `origin/main` is at `0cf75c9`. The F3 work, the documentation audit and the F3 Codex review fixes (commits from `70806d2` onward) are being pushed; check CI before calling them verified.

Latest local validation (2026-11-10, Windows PC, after the F3 Codex review fixes, `slice-3`):
`uv run pytest -q` gave **833 passed and 1 skipped**, both plain and with
`CI=true GITHUB_ACTIONS=true`. The skipped test is the real-slicer test, which passed on its own
with `TDMG_ORCASLICER_DIR=artifacts/tools/orcaslicer-2.5.0 uv run pytest -m slicer`.
`uv run ruff check .` and `uv run python scripts/gen_docs.py --check` passed.

## Next steps, in order

1. **F6 portability with PrusaSlicer.** It is the last blocker to PRINTABLE for the
   owner's Roadie and Oddie. Pin and hash-verify PrusaSlicer 2.9.7 as was done for
   OrcaSlicer, measure its CLI on Windows first, and record it in
   `research/verification/`.
2. **Caliper measurements,** if the owner gets calipers: three named dimensions within
   `acceptance.dimension.tolerance` (still a hypothesis), logged as a calibration.
3. **R1 features and 3MF:** the keychain loop or base, then 3MF output with a UUID
   identity scheme.
4. **Roadie's roughness (open):** the owner finds Roadie's smoothed edge "close but
   still a bit rough", acceptable for now. Options: a per-image `--smooth-px`, or a
   better source image.
5. **R4 backend (open):** help the owner choose under their decision rule: a cheap
   standard service, around $1 per model, beats a homemade pipeline if it does
   everything we need.

## Done so far (history)

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
  - **Pushing:** the owner said "push, then proceed" for this line of work. After
    pushing, confirm that CI passes.
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

# Project status

**Last updated:** 2026-11-09, at the end of the first working session, on the owner's M5 Mac. Development now moves to the owner's PC.

Keep this page current. A new session reads it right after `CLAUDE.md`, and it is the only memory that travels between machines.

## Where things stand

| Area | State |
|---|---|
| Research | Landscape report (v2.1, with revision history) and seven source notes. Independent Codex reviews are in `research/reviews/2026-11-09-codex/` |
| Plan | `docs/PLAN.md` v2. The owner's decisions are in its section 13 |
| Phase 0 (foundations) | **Done.** Package `tdmg`, 26 rules with checked citations, A1 printer profile, docs, 133 tests. CI green on macOS arm64 and Linux |
| Phase 1 (R1 flat single-color) | Not started |
| Photo-to-3D backend (needed for R4) | Being chosen with the owner, one option at a time. A measured local test is designed but not run: `research/experiments/2026-11-g3-local-vs-hosted/PROTOCOL.md` |

## Machines

| Machine | Facts | What has been verified on it |
|---|---|---|
| M5 MacBook | Apple M5, arm64, 16 GB, macOS 26.3, no CUDA | Python 3.13 stack installed and functionally tested (`research/verification/2026-11-08-stack-smoke/`); all tests; wheel build and install |
| PC | 64 GB RAM, no discrete GPU. OS and CPU **not yet recorded** | Nothing yet |

CI runs on GitHub's `macos-15` (arm64) and `ubuntu-latest`. **It does not run on Windows.** If the PC runs Windows, add `windows-latest` and fix what breaks. For example, a venv's Python on Windows is in `Scripts\python.exe`, not `bin/python`.

## Next steps, in order

1. **Set up and verify on the PC.**
   - Record the OS, CPU, RAM, disk, and Python and uv versions in a new `research/verification/<date>-pc-stack/README.md`.
   - Run `uv sync` and `uv run pytest`.
   - Check which optional packages install on this platform: pymeshlab, open3d, rembg with onnxruntime, bpy, orca123d, meshlib.
   - Rerun the smoke scripts in `research/verification/2026-11-08-stack-smoke/` and note any differences.
   - Add the PC's OS to CI if it is not covered.
2. **Run the local photo-to-3D test on the PC's CPU,** following the protocol. First confirm from each README which candidates run without a GPU. Ask the owner before any download over a few GB, and before running third-party install scripts.
3. **Report the results to the owner, and continue the option walk-through:**
   - option 4, renting a GPU;
   - option 5, Bambu MakerLab.

   Then help the owner choose the R4 backend under their decision rule: a cheap standard service, around $1 per model, beats a homemade pipeline if it does everything we need.
4. **Phase 1, R1 vertical slice,** as in `docs/PLAN.md` section 11. Its first test fixtures are the prototype defects listed in `research/verification/2026-11-08-stack-smoke/README.md` section 5.

## Open questions for the owner

| Question | State |
|---|---|
| Hosted API keys (Replicate, fal) | Deferred until local results are in |
| Is a monthly plan acceptable for a commercial API, such as Meshy's $20 Pro plan? | Not answered |
| Use Meshy's free printability check as a second opinion? It means uploading the mesh | Not answered |
| Photo privacy with hosted services, and their data and training terms | Uploading is allowed for now. **Marked to revisit** |
| The PC's OS | Not answered |

## Owner decisions, in short

The full list is in `docs/PLAN.md` section 13.
- **Printer:** Bambu Lab A1. Bambu Studio is the owner's slicer.
- **Portable files:** print files must not depend on the AMS unit or the slicer. They use standard 3MF, name colors rather than slots, and ship a palette manifest.
- **Jobs default to at most 4 filaments,** the AMS lite's slot count. A job declares its real cap.
- **Licence and use:** personal use; the repo is MIT. The owner is in the US.
- **Roadmap order:** R1 → R2 → R3 → R4. A command-line tool and Python library first.
- **Photo-to-3D:** local is preferred. Hosted models are fine to try, and most work will be simple objects.

## How this project works

- **Owner:** a data scientist who is new to 3D printing. Explain 3D concepts plainly.
- **Evidence over priors:** never fill a gap with an assumption. Say what was verified, how, and what was not.
- **Code decides:** the default pipeline has no LLM calls.
- **Independent review:** after each meaningful change, the previous sessions ran an independent read-only review with the OpenAI Codex CLI, verified each finding against its source before applying it, and recorded the handling in `research/reviews/`. If Codex is not installed on the PC, ask the owner how they want reviews done.
- **Commits:** small, descriptive commits pushed to `main` at https://github.com/atashie/three-d-model-generation-; the repo name ends with a hyphen. Push access on the PC must be set up by the owner, over SSH or with `gh auth login`.

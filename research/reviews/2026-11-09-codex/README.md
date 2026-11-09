# Independent review by OpenAI Codex, 2026-11-09

**What:** The project owner asked for an independent review of all code, plans, and documentation. OpenAI Codex CLI 0.165.0 ran in a read-only sandbox, with live web search, at its configured default model and reasoning effort. It ran as separate, scoped sessions. Each prompt is saved next to its output.

**Line numbers:** findings cite files as they were at commit `6165e41`. Later commits changed those files, so open that commit to follow a line reference.

## Records

| Scope | Prompt | Output | Status |
|---|---|---|---|
| Code and verification scripts | `prompt-code.txt` | `code-and-verification.md` | Complete. The session was resumed once after a network drop, to write its final answer |
| Plan v1 | `prompt-plan.txt` | `plan-v1.md` | Complete. Resumed once after a network drop |
| Research report: first attempt | `research-interim-notes.md` | — | Failed. Its context filled, and compaction failed during the network outage. Its interim notes were given to the two follow-up runs as hypotheses |
| Research report: fact-check against primary sources | `prompt-research-factcheck.txt` | pending | Running |
| Research report: fidelity to the notes, and missing topics | `prompt-research-fidelity.txt` | pending | Running |

## How the findings were handled

Each finding was reproduced or checked against its source before anything changed.

**Code and verification:**
- **Reproduced locally:** the hole-bias direction; the MultiPolygon output of `make_valid`; the mirrored Y axis; the zip date fields.
- **Inferred from the code, not run:** the empty-mask crash.
- **Applied:** all corrections in `research/verification/2026-11-08-stack-smoke/README.md`; the prototype defects are listed there as required Phase 1 tests.
- **Lock file:** `networkx` and `lxml` added.

**Plan v1:**
- **Checked against sources and applied in plan v2:**
  - OpenCASCADE's licence, from the OCCT README.
  - The existing GPL-2.0 Blender 3MF add-on with paint export, from its docs and the GitHub API.
  - DrLex's radial vs vertical clearance, from the articulation note.
  - The heightfield and voxel-memory arithmetic.
  - Layer color changes working for any geometry.
- **Narrowed:** the review said OrcaSlicer's JSON output is unavailable on macOS. In the v2.5.0 source, only the `result.json` warnings file is written under a Linux-only guard. The G-code statistics export, which is also JSON, sits outside any platform guard. Plan v2 states both facts. Neither has been run on the M5 yet.

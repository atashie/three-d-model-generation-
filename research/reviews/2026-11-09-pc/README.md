# Independent PC verification review

Ran the installed OpenAI Codex CLI with `--sandbox read-only --ephemeral`.
Full response: [review.txt](../../verification/2026-11-09-pc-stack/review.txt).

Findings checked and handled:

1. **Timeout loses results:** confirmed by reading the harness. It now catches
   subprocess timeouts, records captured output and the timeout duration,
   continues other checks, clears stale results at startup, and saves after each check.
2. **Stale STATUS.md:** valid against the review's initial snapshot. Updated
   during the review with hardware, local verification, optional import failures,
   Windows CI's unverified hosted status, and experiment prerequisites.

Reviewer independently checked deterministic 3MF hashes and the installed wheel's
rules/profile loading. No CI path defect or protocol violation was identified.
GitHub execution is still unverified.

## Checkpoint preparation follow-up

Independent read-only CLI review of `prepare_pc.py` (tools disabled by prompt):
see `preparation-review.txt`. Both findings were verified against the script:

- Cached files could be labeled with a different upstream revision. The script
  now reuses the recorded revision and verifies both files against its metadata.
- A commit alone does not identify modified source. Preparation now refuses a
  dirty TripoSR checkout; later inference patches must be separately recorded.

Reran preparation successfully after both fixes without downloading weights
again. The independent review covered preparation only, not an inference harness.

## Inference harness

Independent read-only CLI review is saved at
`../../experiments/2026-11-g3-local-vs-hosted/harness-review.txt`.
Findings were checked against code:

- Deadline sampling is approximate: documented scheduling/cleanup limits;
  shortened final sleep and bounded process wait. No actual run exceeded 39 seconds
  including post-export checks.
- Timeout cleanup exit race: catch vanished processes during child enumeration/kill.
- Duplicate/degenerate faces: add explicit duplicate-face and zero-area measurements;
  do not treat topology predicates alone as certification.
- Provenance: verify checkpoint, configuration, auxiliary files and clean source
  commit before each run; save package versions, runner hash and settings per run.

First execution additionally exposed Windows' Python launcher indirection. The
monitor now samples the process tree and the worker records its own lifetime peaks.
Discarded the exploratory run's memory measurement and repeated the chair twice.
Ten measured runs completed after these corrections. The preview/comparison script
is a diagnostic artifact, not a production printability gate.

## MakerLab export inspection

Independent read-only CLI review: `makerlab-review.txt`. Verified each finding:

- Trimesh component splitting defaults to repair: confirmed against installed
  `trimesh.util.submesh` source, disabled explicitly and reran inspection. MakerLab
  results remain unchanged. Also disabled it for future CPU experiments and added
  an erratum for their historical component-volume diagnostics. Whole-mesh topology
  measurements and raw exported meshes were unaffected.
- Boundary interpretation: renamed fields to `closed_edge_manifold` and
  `closed_vertex_manifold`; these intentionally test closed solids.
- Signed volumes: now report component closure/winding alongside signed volume;
  never equate a positive integral with printability.

Roadie's separate extraction uses face-adjacency components directly without
repair. Source hash and component sizes are asserted; read-back triangles equal
the selected source triangles exactly. The retained body was visually inspected
and checked for closure, winding, connectivity and positive signed volume. It is
not certified printable and was not sliced. Documentation adds the owner's
interpretation requirement without claiming implementation or altering the no-LLM
default. No inference rerun was required for this inspection.

## Final documentation/handoff audit

See `final-doc-review.txt`. Review found ambiguous Phase 0 completion after adding
Windows and no assigned follow-up for the first Windows CI run. Verified both
against PLAN/STATUS, preserved completion of the historical Mac/Linux baseline,
restored explicit Windows acceptance checks, and assigned post-push CI verification.
The final README also distinguishes planned production/slicer capabilities from
completed research experiments. Historical records retain their chronology with
current-status addenda. Local full validation: 135 tests, lint, generated docs and
whitespace checks passed. No new model generation or design step was initiated.

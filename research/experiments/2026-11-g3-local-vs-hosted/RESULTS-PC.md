# TripoSR CPU results, 2026-11-09

**Generation works on this PC in about half a minute per image. None of the raw
outputs is certified printable.** Speed and memory meet the accepted local test
criterion; repairability and acceptable shape quality have not been established.

## Setup and execution

Windows 11 Pro, i9-12900K, 64 GB RAM, no discrete GPU. Owner explicitly approved
the checkpoint, compiler installation, reviewed source builds, and 30 minutes/model.
Microsoft Visual Studio Build Tools 2022 17.14.44 installed; MSVC 14.44.35207.
torchmcubes CPU build and ANTLR 4.9.3 build succeeded. No reboot was requested.
Python 3.11.15 and torch 2.6.0+cpu in `artifacts/triposr-py311`; the project's
Python 3.13 environment was not changed.

Source and weight identities are in `preparation.json` and each run's provenance.
The official 1.68 GB checkpoint loaded with `weights_only=True`. U2Net ONNX and
DINO configuration hashes are in `auxiliary-hashes.json`. Downloads completed
before timing. Inference used cached resources with HF offline mode and telemetry
disabled; no input was uploaded. The upstream source checkout remained unmodified.

Settings: CPU, 16 threads, seed 0, deterministic PyTorch algorithms, extraction
resolution 256, chunk size 8192, foreground ratio 0.85. The last three values are
upstream `run.py` defaults, not production acceptance thresholds. Existing alpha
was preserved; only the opaque teapot input required background removal. Images
were resized and composited over gray using upstream preprocessing. The owner
inputs are cartoons, a recorded deviation from the proposed object photographs.

Each measured run uses a fresh subprocess. Time includes imports, verification,
model initialization, preprocessing, inference and OBJ export; it excludes download
and post-export geometry checks. The supervisor also records total process time.
Timeout supervision uses a 1800-second deadline with 0.5-second sampling and bounded
cleanup; it is not a real-time scheduling guarantee. No run approached the limit.

## Results (two runs per image)

| Input | Seconds to mesh | Triangles | Bodies | Peak working set, GiB | Peak private memory, GiB |
|---|---:|---:|---:|---:|---:|
| chair | 33.54 / 33.19 | 84,160 | 1 | 3.56 | 5.98 |
| hamburger | 34.16 / 34.07 | 111,172 | 8 | 3.55 | 5.97 |
| teapot | 34.32 / 34.99 | 80,712 | 1 | 4.00 | 6.50 |
| oddie | 32.62 / 32.28 | 57,800 | 1 | 3.56 | 5.97 |
| roadie | 32.66 / 32.15 | 189,800 | 2 | 3.57 | 5.98 |

Memory columns are maximum process-tree samples across each pair. The worker also
records its Windows lifetime peak working set and commit counters. Private/commit
memory is not physical RAM usage. System swap was about 72–84 MiB and did not
increase within any run; this is a system-wide observation, not a process attribution.
The first exploratory `chair-1` completed in 36.68 seconds but its original monitor
only watched Windows' launcher. Its memory numbers are invalid and excluded;
the corrected `chair-2` and `chair-3` are the reported pair.

All outputs have finite coordinates, positive total signed volume, consistent
winding, and no duplicate faces. Roadie has one exactly zero-area face; the other
four have none. **All five fail
watertightness, edge-manifoldness and the closed vertex-link test**, both repeated
runs. Invalid vertex-link counts: chair 351, hamburger 528, teapot 240, oddie 268,
roadie 595. Positive total volume does not prove each component is valid: the
hamburger has small components with negative signed volume. No repairs were applied.

Topology is measured after reading the OBJ with `process=False`. The pre-export
meshes also fail watertightness, so this is not just an export/read-back artifact.
The vertex test requires a single connected cyclic link; duplicate and zero-area
faces are reported separately. Self-intersection, wall thickness, physical scale,
support needs, slicer acceptance and printed dimensions were not tested.

**Repeatability:** all five OBJ pairs differ in bytes. After sorting vertices and
canonicalizing triangles while preserving winding, vertex coordinates and triangle
connectivity match exactly, with maximum sorted vertex distance 0. This establishes
same-environment geometric repeatability for these ten runs, not cross-platform
equality or texture/color repeatability. Saved outputs remain the replay artifacts.

## Visual assessment and limits

**Diagnostic correction, same day:** later independent review found that Trimesh's
default component splitting may fill holes in temporary component copies. The saved
raw meshes and whole-mesh topology measurements are unaffected, but historical
`body_volumes` are not reliable raw-component measurements. They must not be used
to infer repairability. Future harness runs explicitly disable component repair;
the original run records and hashes remain intact. Total signed volume is an
algebraic measurement and does not establish solid volume for these open meshes.

See [previews.png](previews.png): two diagnostic views, with display-only orientation
from upstream's Gradio helper. The actual OBJ coordinates were not changed.
Chair and teapot are recognizable; hamburger has small detached pieces. Oddie has
a recognizable body and leaf silhouette. Roadie is dominated by a rounded disc,
consistent with its circular background being treated as foreground. It is not
an acceptable standalone character reconstruction. This is visual assessment,
not a measured shape-accuracy score. A single image cannot verify unseen surfaces.

This supports TripoSR as a fast local **candidate**, not a chosen R4 backend. The
protocol's repairability criterion is unresolved, and the Roadie failure requires
better input isolation or a different generator rather than topology repair alone.
No hosted model was called by this experiment; no paid account or GPU rental was
created. **Subsequent update:** owner declined GPU rental for now and supplied
MakerLab exports, inspected in `MAKERLAB-RESULTS.md`. The final backend decision
remains open.

## Artifacts and reproduction

- `runs/<label>/`: logs, metrics, resources and package/source/input provenance.
- `summary.json`: combined results and repeatability comparisons.
- `artifacts/triposr-runs/<label>/mesh.obj`: raw meshes (ignored by Git).
- `artifacts/triposr-runs/<label>/input.png`: exact preprocessed model input.
- Harness: `run_pc.py`; comparison/preview script: `summarize_pc.py`.

For example, use the isolated Python to run `run_pc.py --index 3 --label oddie-new`.
Labels must be new to avoid overwriting evidence. Full inference reruns require
the prepared source checkout, cached model/config files and original image paths.

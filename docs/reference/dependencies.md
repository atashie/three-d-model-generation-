# Dependencies and licences

Versions are from `uv.lock`. The core is mostly permissive, but three bundled native libraries are LGPL-2.1: OpenCASCADE (with an exception), GEOS and FFmpeg. All are used unmodified through pip packages, which is the usual way to meet LGPL; bundling them into a distributed app would add obligations. The **declared licence** comes from each package's own metadata, printed by `scripts/dependency_licences.py` on 2026-11-09. A package's metadata does not list the licences of native libraries or model weights it bundles, so the **notes** column adds those by hand.

**Verification states** (docs/PLAN.md section 9):
- **resolved:** a wheel exists for this platform;
- **imported:** installed and imported on the target Mac;
- **tested:** a functional check ran;
- **validated:** used in a real pipeline run.

## Core

The tables below retain the M5 verification baseline. Windows core verification
and optional native-import failures are recorded in
[PC stack results](../../research/verification/2026-11-09-pc-stack/README.md).
The separate [TripoSR CPU experiment](../../research/experiments/2026-11-g3-local-vs-hosted/RESULTS-PC.md)
used Python 3.11.15, torch 2.6.0+cpu, torchmcubes 0.1.0, rembg 2.0.61 with U2Net,
and ONNX Runtime 1.20.1 successfully. Its per-run provenance records exact packages
and model hashes; these are not core dependencies or changes to `uv.lock`.

| Package | Version | Declared licence | Role | State on M5 | Notes |
|---|---|---|---|---|---|
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | arrays | tested | |
| scipy | 1.18.1 | BSD | numerics | imported | |
| trimesh | 5.2.0 | MIT | mesh I/O, checks; STL read-back and layer sections in `tdmg slice` | tested | Its 3MF writer hard-codes millimetres, writes no color, and uses random UUIDs |
| networkx | 3.7 | BSD-3-Clause | needed by trimesh to load 3MF | tested | |
| lxml | 6.1.3 | BSD-3-Clause | needed by trimesh to load 3MF | tested | |
| manifold3d | 3.5.4 | Apache-2.0 | robust booleans, manifold checks | tested | Rejects non-manifold input; stores float32 |
| lib3mf | 2.5.0 | BSD | 3MF writing and spec-level checks | tested | Writes random UUIDs unless set |
| shapely | 2.2.0 | BSD-3-Clause | 2D polygon cleanup; printed-footprint analysis (`tdmg.printed`) | tested | **Bundles GEOS under LGPL-2.1** (wheel's `LICENSE_GEOS`). `make_valid` can return several polygons |
| opencv-python-headless | 5.0.0.93 | Apache-2.0 | connected components (`tdmg select`), Gaussian blur (`tdmg.smoothing`); contour tracing in the stack tests | tested | **Bundles FFmpeg under LGPL-2.1**, plus other libraries on macOS (wheel's `LICENSE-3RD-PARTY.txt`) |
| build123d | 0.13.0 | Apache-2.0 | parametric CAD | tested | |
| cadquery-ocp-novtk | 8.0.1.1.0 | Apache-2.0 (wrapper) | OpenCASCADE kernel for build123d | tested | **The kernel itself is LGPL-2.1 with a special exception.** Used as an unmodified pip dependency |
| vtracer | 0.6.15 | MIT | raster-to-vector tracing | imported | |
| contourpy | 1.4.0 | BSD-3-Clause | iso-contours for outline smoothing (`tdmg.smoothing`) | not checked on M5 | Added 2026-11-10; imported and measured on the PC (research/verification/2026-11-10-outline-smoothing) |
| pillow | 13.0.0 | MIT-CMU | image loading | imported | |
| pydantic | 2.14.3 | MIT | rule and profile schemas | tested | |
| typer | 0.28.0 | MIT | CLI | tested | |
| pyyaml | 6.0.3 | MIT | rule and profile files | tested | |

## Optional extras (not installed by default)

| Package | Extra | Declared licence | State on M5 | Notes |
|---|---|---|---|---|
| rembg | perception | MIT | imported (no model run) | Its default `bria-rmbg` weights need a paid agreement for commercial use; `u2net`, `isnet` and `birefnet-general-lite` are the practical CPU choices |
| onnxruntime | perception | MIT | imported | 1.31.1 includes the Core ML execution provider |
| pyobjc-framework-Vision | perception | MIT | imported | Apple Vision foreground masks, macOS 14+ |
| pymeshlab | analysis | GPL-3.0 | tested | Optional because of GPL; fine for personal use |

## Development

| Package | Version | Declared licence | Notes |
|---|---|---|---|
| pytest | 9.2.0 | MIT | |
| hypothesis | 6.170.15 | MPL-2.0 | property-based tests |
| ruff | 0.17.4 | MIT | lint |
| thingi10k | 1.5.0 | Apache-2.0 (code) | **Each model in the corpus has its own licence**; record it for any fixture we keep |

## External tools (not Python packages)

This table is the original Mac baseline. On the PC, MSVC Build Tools 2022
17.14.44 (compiler 14.44.35207) was installed for the isolated CPU experiment.
The owner reports MakerLab available and supplied exported STLs. The owner also
reports importing `tdmg flat` STLs into Bambu Studio and printing one Roadie from it
(2026-11-10); the machine and version are not recorded, and tdmg does not run it.

| Tool | Version | Licence | State | Role |
|---|---|---|---|---|
| OrcaSlicer | 2.5.0 (Homebrew cask on the Mac; on the PC, the pinned Windows x64 portable, `profiles/slicers/orcaslicer-2.5.0.yaml`) | AGPL-3.0 | Mac: not installed. PC: installed by `scripts/setup_orcaslicer.py` into git-ignored `artifacts/tools/`; hash-verified; runtime-validated by `tdmg slice` (2026-11-10) | Headless slicer check (`tdmg slice`), run only as a subprocess; no code or profile files in the repo |
| Bambu Studio | 2.9.1 (Homebrew cask) | AGPL-3.0 | Not installed on the M5 (2026-11-08 baseline). Used by the owner to slice and print Roadie (owner report); machine and version not recorded | The owner's slicer for sending prints to the A1 |
| PrusaSlicer | 2.9.7 (on the PC, the pinned Windows x64 portable zip, `profiles/slicers/prusaslicer-2.9.7.yaml`) | AGPL-3.0 | Mac: not installed. PC: installed by `scripts/setup_prusaslicer.py` into git-ignored `artifacts/tools/`; hash-verified; runtime-validated by `tdmg slice` (2026-11-11) | Second checker for `F6.portability`, run only as a subprocess; no code or profile files in the repo |

The "imported" and "tested" states for packages not exercised by this repo's own tests come from `research/verification/2026-11-08-stack-smoke/README.md`.

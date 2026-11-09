# Experiment protocol: photo-to-3D, local vs hosted

**Status:** planned, not run. Written 2026-11-09 after the owner approved a measured test.

**Decision it informs:** which backend R4 (single-color figurine) uses. The owner prefers local, and accepts hosted for trials. Uploading photos is allowed for now, and privacy is flagged to revisit (docs/PLAN.md section 13).

## Candidates, rechecked 2026-11-09

| Candidate | Where it would run | Status today | Licence |
|---|---|---|---|
| AssetFurnace, Hunyuan3D-MLX backend (Xiong, full pipeline) | M5 16 GB | Active (1,149 stars, pushed 2026-11-08). Its README calls this backend "the quickest to get running from a fresh clone" | App Apache-2.0; backend code MIT; weights under the Tencent community licence (fine in the US) |
| AssetFurnace, Pixal3D C++/GGML backend | M5 16 GB, if full Xcode is installed | Its README's recommended engine; 8.4 GB weights; "compiles with Metal (needs full Xcode)". Only Xcode Command Line Tools are installed now | MIT code and flow weights; bundled encoder under the DINOv3 licence |
| trellis-mac (TRELLIS.2) | the 64 GB machine, only if it is an Apple Silicon Mac | MIT, 506 stars, last push 2026-04-28; peaks near 18 GB | MIT; DINOv3 and BRIA RMBG-2.0 licences apply |
| TripoSR | any machine, CPU fallback | MIT, 7,349 stars, pushed 2026-06-04; older (2024) model | MIT |
| Hosted: Replicate `tencent/hunyuan3d-2` | Replicate | about $0.044 per run | Tencent community licence |
| Hosted: fal `fal-ai/trellis` | fal | $0.02 per run | MIT model; fal terms |

**Dropped:**
- **hy3dmlx:** the research's leading local option. Its code repository returns HTTP 404 and it is not on PyPI; only its weights remain on Hugging Face.
- **Stable Fast 3D:** no push since 2025-01-22, and its weights are gated.
- **The Hunyuan3D 2.1 Mac port:** it now redirects to a repository named `hunyuan3d-2.1-mac-rocm`.

## Inputs

- **Images:** five fixed images, recorded by SHA-256:
  - three demo images that ship with the candidates;
  - two photos from the owner of simple objects on a plain background.
- **Settings:** one fixed seed and one fixed setting per backend, recorded with the app commit, weight file hashes, and Python and package versions.

## Measurements per run

| Measure | How |
|---|---|
| Wall time | Start to written mesh |
| Peak memory | The process's peak memory, and the system swap used during the run |
| Output size | Triangle count, and file size |
| Raw printability | Watertight; edge-manifold; vertex-manifold (`gate.topology.vertex_manifold`); consistent winding; number of bodies; positive volume. Measured with trimesh plus a separate vertex-manifold check, before any repair |
| Repeatability | Same input and seed run twice on the same machine: are the outputs byte-identical or only similar? |

## Proposed criteria for "viable on the M5"

The owner should confirm or change these before the run.

- Finishes without crashing or exhausting memory, with other apps closed.
- About 30 minutes per model or less.
- Raw defects are of kinds the planned repair ladder handles: small holes and duplicate shells, not missing volume.

## Safety

- **Isolation:** each candidate is installed in its own environment, outside the project environment.
- **Review before running:** install scripts are read before they run. Weights must be safetensors or GGUF; pickled checkpoints are refused unless the owner agrees.
- **No uploads in local runs:** nothing is uploaded during local runs.
- **Consent for hosted runs:** hosted runs use the owner's own API keys and need a yes before each batch of uploads.

## Open before running

- Is the 64 GB machine an Apple Silicon Mac? MLX and Metal backends need one; on a PC without a GPU only CPU paths such as TripoSR apply.
- When can the M5 run unattended with other apps closed? Today only about 3.5 GB of its 16 GB was free.
- Should full Xcode be installed, to enable the Pixal3D backend? It is several GB from the App Store.
- Replicate and fal API keys are needed for the hosted comparison.

# Windows CPU preflight, 2026-11-09

This records the preflight. **Update:** owner approved compiler/source builds;
installation and the TripoSR CPU experiment are now complete. See `RESULTS-PC.md`.
The preparation chronology below retains the state before inference.
Machine: Windows 11 Pro x64, i9-12900K, 64 GB RAM.

## Candidate checks

| Candidate | Primary-source finding | Disposition |
|---|---|---|
| TripoSR | README treats CUDA as optional; `run.py` explicitly falls back to CPU | First candidate, subject to checkpoint approval and dependency build review |
| Stable Fast 3D | README has an explicit CPU backend section; Windows support is experimental and requires Visual Studio 2022; model access is gated | CPU candidate, but access must be supplied by owner; prior dropped status does not mean CPU is unsupported |
| AssetFurnace Pixal3D | README lists Mac, NVIDIA and AMD/ROCm, with 8.4 GB weights; no CPU-only Windows route established | Do not install or download weights on present evidence |
| Hunyuan3D-2 | README does not document a CPU-only route | Not confirmed for this experiment; absence of documentation is not proof of impossibility |

Sources checked:

- [TripoSR README](https://github.com/VAST-AI-Research/TripoSR/blob/main/README.md), Installation.
- [TripoSR run.py](https://github.com/VAST-AI-Research/TripoSR/blob/main/run.py), device fallback and model initialization.
- [TripoSR loader](https://github.com/VAST-AI-Research/TripoSR/blob/main/tsr/system.py), `from_pretrained` calls `torch.load`.
- [Official weight listing](https://huggingface.co/stabilityai/TripoSR/tree/main): `model.ckpt`, 1.68 GB; no safetensors file listed.
- [TripoSR requirements](https://github.com/VAST-AI-Research/TripoSR/blob/main/requirements.txt): includes a Git-based torchmcubes dependency; review build code before requesting installation approval.
- [SF3D README](https://github.com/Stability-AI/stable-fast-3d/blob/main/README.md), CPU Support, Windows Support, Requesting Access and Login.
- [AssetFurnace README](https://github.com/Bingeljell/image-to-3dlab/blob/main/README.md), backend table and requirements.
- [Hunyuan3D-2 README](https://github.com/Tencent-Hunyuan/Hunyuan3D-2/blob/main/README.md).

These are live source links checked on this date, not a pinned execution environment.
Pin code and record weight hashes before any eventual run.

## Historical prerequisites and preparation chronology

### Owner response and preparation, 2026-11-09

The owner approved loading the official checkpoint, supplied
`C:/Users/arikt/Downloads/three-d-test/`, and accepted 30 minutes per model.
The two files are `oddie.png` and `roadie.png`. Visual inspection shows cartoons,
not physical-object photographs; roadie includes a circular background. These
are the owner-selected inputs, a deviation from the original photo protocol.
The three demo inputs selected are chair, hamburger, and teapot from TripoSR.

Source checkouts under ignored `artifacts/`:
- TripoSR: `107cefdc244c39106fa830359024f6a2f1c78871`.
- torchmcubes: `a9ac95aa329957ba646e7bb057f825f5dfa77f38`.

The isolated environment is `artifacts/triposr-py311`, Python 3.11.15 with
CPU-only torch 2.6.0. An initial Python 3.12 environment could not resolve the
pinned transformers 4.35.0 tokenizer as a binary wheel; it is not used for runs.
Only binary dependencies have been installed. Core Python 3.13 is unchanged.

Reviewed torchmcubes `pyproject.toml`, `_torch_dep.py`, root and `cxx/CMakeLists.txt`:
the build uses scikit-build/CMake, locates installed PyTorch, and compiles C++20
with optional CUDA. No CUDA is needed for its CPU build. No compiler was found
on PATH or through the Visual Studio installation checks. No upstream release
or PyPI binary was found. ANTLR 4.9.3's setup.py contains package metadata and
setuptools packaging only; its source archive SHA-256 is
`f224469b4168294902bb1efa80a8bf7855f24c99aef99cbefc1bcd3cce77881b`.

**Pending then, subsequently approved/completed:** install Microsoft Visual C++ Build Tools (several GB) and
run the reviewed torchmcubes/ANTLR source builds. This is separate from the
checkpoint approval and is explicitly required by STATUS.md's install-script
and large-download instructions. No third-party source build has run.

`prepare_pc.py` records five input hashes, the model revision, code commit,
checkpoint/config hashes, seed 0, and the accepted 1800-second timeout in
`artifacts/triposr-data/preparation.json`. Input files and model weights stay
outside tracked research records. No inference has been performed.

Preparation completed: model revision `5b521936b01fbe1890f6f9baed0254ab6351c04a`;
checkpoint 1,677,246,742 bytes, SHA-256
`429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee`.
Both downloaded files match upstream revision metadata (LFS SHA-256 for the
checkpoint, Git blob identity for config). Restricted `torch.load(weights_only=True)`
succeeded with 549 tensor values. This is a deserialization check, not inference.
Torch 2.6.0+cpu, ONNX Runtime 1.20.1, rembg 2.0.61 and transformers 4.35.0 import
successfully. Thus the earlier optional-import failures do not reproduce in this
different environment; their root cause has not been isolated.
Small evidence records are saved beside this file as `preparation.json`,
`checkpoint-validation.json`, and `imports.json`.

The original prerequisite list below is retained as a record; items 1, 3 and 4
now have the owner response above.

1. Owner approval for TripoSR's official PyTorch checkpoint. The protocol allows
   only safetensors/GGUF without agreement. If approved, use an explicit
   restricted `weights_only=True` load; stop if unsupported objects are required.
   No checkpoint has been downloaded or loaded.
2. Review the exact native build/install code and obtain approval before executing
   third-party install scripts. No such scripts have run for a generation candidate.
3. Supply two owner photos of simple objects against plain backgrounds (local
   paths are sufficient). Choose three candidate demo images and record all hashes.
4. Confirm the proposed 30-minute-per-model criterion for this PC; the original
   protocol asks for confirmation and described it as an M5 criterion.
5. Resolve dependencies in a separate environment, including Windows native-import
   problems if the selected environment reproduces them. Never reuse the core venv.

At the end of this preflight, the workflow was at step 2. The subsequent CPU trial
and MakerLab inspection are now complete; GPU rental was declined for now. The
backend decision and Phase 1 remain pending. Hosted API keys remain deferred.

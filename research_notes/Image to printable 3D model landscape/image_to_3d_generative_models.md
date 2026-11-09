# AI single-image-to-3D mesh generation for FDM printing: open-weights and commercial landscape (as of 2026-11-08)

Scope note for the report writer: these notes catalogue image-to-3D generators (open and commercial), hosted inference options, and how print-ready their output is. Each finding is tagged:

- **[P]** verified from a primary source (GitHub README/LICENSE/code, Hugging Face API, official pricing or API docs) fetched on 2026-11-08
- **[S]** secondary claim (press, vendor blog about competitors, aggregator, forum, search-result snippet)
- **[U]** could not verify (stated as a gap)

GitHub star counts and "last push" dates were read from the GitHub REST API (`api.github.com/repos/...`) or the shields.io badge JSON on 2026-11-08; Hugging Face Space hardware/status from `huggingface.co/api/spaces/...` the same day. The web-search budget ran out near the end of the session, so a few items (Kaedim pricing, Luma Genie status, Hi3D API pricing, SAM 3D Objects VRAM) stayed unverified; they are listed under Gaps rather than guessed.

User hardware context for every tool below: Apple Silicon M5, 16 GB unified memory, no NVIDIA GPU. Each tool entry states "Apple Silicon", "CUDA-only", "API-only" and/or "hosted".

---

## Key Question 1: Leading open-weights single-image-to-3D models (Nov 2026)

### Takeaway
The open-weights frontier in Nov 2026 is: Microsoft **TRELLIS.2** (4B, MIT, Dec 2025, 24 GB VRAM), Tencent ARC **Pixal3D** (MIT, May–Sep 2026, TRELLIS.2 backbone, multi-view inference), **Hi3D v1.0** (Oct 23 2026, geometry-only refiner on Sparc3D, custom license), plus the still-dominant 2025 generation: Tencent **Hunyuan3D 2.0/2.1** (community license excluding EU/UK/KR; 2.5/3.0/3.1 are closed, API-only), **TripoSG**, **Step1X-3D**, **Direct3D-S2**, **PartCrafter**. Almost everything upstream is CUDA-only; Apple Silicon is reachable only via community MPS/MLX/GGML ports (TRELLIS.2, Hunyuan3D 2.0/2.1, Pixal3D, SF3D/SPAR3D, Hi3D) and, for 16 GB machines, mostly in shape-only or reduced-resolution modes.

### Cited Findings

#### Tencent Hunyuan3D 2.0 (Jan 2025; "older" baseline but still the most-starred)
- Repo `Tencent-Hunyuan/Hunyuan3D-2`: 15,357 stars, last push 2025-10-28, license "Other" (Tencent Hunyuan 3D 2.0 Community License) [P] — [GitHub API](https://api.github.com/repos/Tencent-Hunyuan/Hunyuan3D-2); [repo](https://github.com/Tencent-Hunyuan/Hunyuan3D-2)
- "It takes 6 GB VRAM for shape generation and 16 GB for shape and texture generation in total." [P] — [README](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-2/main/README.md)
- Model zoo: Hunyuan3D-DiT-v2-0 1.1B image-to-shape (2025-01-21), DiT-v2-0-Fast (2025-02-03), DiT-v2-0-Turbo (2025-03-19), Hunyuan3D-2mini 0.6B (2025-03-18), Hunyuan3D-2mv 1.1B multiview (2025-03-18), Paint-v2-0 1.3B texture, Paint-v2-0-Turbo (2025-04-01) [P] — [README](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-2/main/README.md)
- README states "Hunyuan3D 2.0 supports Macos, Windows, Linux" and ships a Gradio app, an API server (example `curl ... -o test2.glb`) and a Blender addon [P] — [README](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-2/main/README.md)
- Repo code includes mesh post-processors `FaceReducer` (default `max_facenum=40000`), `FloaterRemover`, `DegenerateFaceRemover`, `MeshSimplifier` in `hy3dgen/shapegen/postprocessors.py` [P] — [postprocessors.py](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-2/main/hy3dgen/shapegen/postprocessors.py)
- License: "THIS LICENSE AGREEMENT DOES NOT APPLY IN THE EUROPEAN UNION, UNITED KINGDOM AND SOUTH KOREA"; Territory excludes EU/UK/South Korea; licensees with >1 million monthly active users on the release date must request a license; outputs may not be used outside the Territory [P] — [LICENSE](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-2/main/LICENSE)
- HF Space `tencent/Hunyuan3D-2`: 3,432 likes, hardware `zero-a10g` (ZeroGPU), RUNNING, last modified 2025-06-02 [P] — [HF API](https://huggingface.co/api/spaces/tencent/Hunyuan3D-2)
- Apple Silicon: upstream claims macOS support, but a community port says upstream hardcodes `"cuda"` strings and needs a compatibility layer (see Hunyuan3D 2.1 Mac port below) [P] — [hunyuan3d-2.1-mac README](https://raw.githubusercontent.com/VladimirTalyzin/hunyuan3d-2.1-mac/main/README.md)

#### Tencent Hunyuan3D 2.1 (Jun 2025; PBR, fully open training code)
- Repo `Tencent-Hunyuan/Hunyuan3D-2.1`: 4,393 stars, last push 2025-10-17, license "Other" (Tencent Hunyuan 3D 2.1 Community License) [P] — [GitHub API](https://api.github.com/repos/Tencent-Hunyuan/Hunyuan3D-2.1); [repo](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1)
- "It takes 10 GB VRAM for shape generation, 21GB for texture generation and 29GB for shape and texture generation in total." Shape model 3.3B, Paint-v2-1 2B, released 2025-06-14; tested with Python 3.10 and PyTorch 2.5.1+cu124 [P] — [README](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-2.1/main/README.md)
- Technical report 2025-06-19; "first production-ready 3D asset generation model" with PBR texture synthesis [P] — [README](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-2.1/main/README.md); [arXiv 2506.15442](https://arxiv.org/html/2506.15442v1)
- Low-VRAM flag `--low_vram_mode` in Gradio app [P] — [README](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-2.1/main/README.md)
- HF Space `tencent/Hunyuan3D-2.1`: 2,360 likes, ZeroGPU, RUNNING [P] — [HF API](https://huggingface.co/api/spaces/tencent/Hunyuan3D-2.1)
- License terms (per secondary timeline): excludes EU, UK, South Korea and >1M MAU [S] — [Cinevva timeline](https://app.cinevva.com/guides/ai-3d-model-generation-timeline-2026)
- Apple Silicon (community port `VladimirTalyzin/hunyuan3d-2.1-mac`, 11 stars, last commit Aug 2026): shape and PBR texturing "verified" on MPS; Apple M4 Pro 24 GB: demo image to mesh in 344 s (30 steps, octree 192), PBR texture in 512 s at the "Safe" preset (6 views at 256 px); texturing "peaks at roughly 8 GB of swap" on 24 GB; weights ~15 GB shape + ~6.5 GB paint + ~4.5 GB DINOv2-giant; exports `.obj/.glb/.ply/.stl` and more ("Seven export formats"); sets `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0` so macOS pages instead of OOM [P] — [README](https://raw.githubusercontent.com/VladimirTalyzin/hunyuan3d-2.1-mac/main/README.md); stars via [shields.io](https://img.shields.io/github/stars/VladimirTalyzin/hunyuan3d-2.1-mac.json)
- Search-result snippet of the same port lists "16 GB of unified memory as the minimum, with 24 GB+ recommended" [S] — [search snippet of README](https://raw.githubusercontent.com/VladimirTalyzin/hunyuan3d-2.1-mac/main/README.md)
- Apple Silicon MLX port of the 2.1 shape pipeline (`AgenticVibes/hy3dmlx`, weights `AgenticVibes/hy3dmlx-shape-v2.1`): "single image in, untextured mesh out"; MLX peak memory 7.85 GB at fp16, octree 384, 50 steps on "M3 Ultra-class hardware"; output 343,508 vertices / 687,024 faces; octree 256 "finishes in ~5 minutes"; "Smaller M-series Macs may need octree_resolution=256"; DiT ~6.10 GB fp16; licensed as Model Derivative under the Tencent 2.1 Community License [P] — [HF model card](https://huggingface.co/AgenticVibes/hy3dmlx-shape-v2.1/raw/main/README.md)
- Hunyuan3D 2.1 is also the recommended coarse-mesh generator for UltraShape 1.0 (see below) [P] — [UltraShape README](https://raw.githubusercontent.com/PKU-YuanGroup/UltraShape-1.0/main/README.md)

#### Tencent Hunyuan3D 2.5 / 3.0 / 3.1 (closed; hosted/API only)
- Hunyuan3D 2.5 system technical report released 2025-06-23 (listed in the 2.0 README news) [P] — [README](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-2/main/README.md); no `Hunyuan3D-2.5` or `Hunyuan3D-3` repo exists under `Tencent-Hunyuan` (GitHub API 404) [P] — [API check](https://api.github.com/repos/Tencent-Hunyuan/Hunyuan3D-3)
- Secondary timeline: 2.5 (2025-06-23) "10B parameters; 1024 geometric resolution; open-source request unanswered"; 3.0 announced 2025-09-16 "Closed (weights never released)... 1536³ geometry, 3.6B voxels"; 3.1 launched 2026-01-28 "1536³ geometry; 20 free generations a day" [S] — [Cinevva timeline](https://app.cinevva.com/guides/ai-3d-model-generation-timeline-2026)
- Tencent Cloud FAQ: Tencent HY 3D Global is provided as "API technology services"; private deployment "Not supported" [P] — [Tencent Cloud FAQ](https://intl.cloud.tencent.com/document/product/1284/75301)
- Tencent Cloud API `SubmitHunyuanTo3DProJob`: `Model` = "3.0" (default) or "3.1"; `FaceCount` default 500,000, range 3,000–1,500,000; `GenerateType` Normal / LowPoly / Geometry ("untextured white model; only GLB output"); `PolygonType` triangle or quadrilateral (LowPoly only); multi-view names left, right, back (+ top, bottom, left_front, right_front in 3.1); "when selecting 3.1, the [LowPoly] and [Sketch] parameter is unavailable" [P] — [Tencent Cloud API doc](https://www.tencentcloud.com/document/product/1284/75540)
- Apple Silicon: N/A (API-only). Hosted options and pricing: see Key Question 2.

#### Tencent Hunyuan3D-Omni (Sep 2025) and Hunyuan3D-Part (Sep 2025)
- Omni: 659 stars, last push 2025-10-17; "It takes 10 GB VRAM for generation"; 3.3B image-to-shape with multi-modal control (released 2025-09-25) [P] — [GitHub API](https://api.github.com/repos/Tencent-Hunyuan/Hunyuan3D-Omni); [README](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-Omni/main/README.md); controls via point cloud, voxel, skeleton, bounding box [S] — [Cinevva](https://app.cinevva.com/guides/ai-3d-model-generation-timeline-2026)
- Part: 557 stars, last push 2025-12-05; P3-SAM (part segmentation) + X-Part (part completion); "The current release is a light version of X-Part. The full version is available on Hunyuan3D-Studio"; recommends "scanned or AI-generated meshes (e.g., from Hunyuan3D V2.5 or V3.0) as input" [P] — [README](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-Part/main/README.md); [GitHub API](https://api.github.com/repos/Tencent-Hunyuan/Hunyuan3D-Part)
- Both CUDA-only per install instructions; no Apple Silicon port found [U].

#### Microsoft TRELLIS (v1, Dec 2024/Mar 2025; "older")
- 14,216 stars, last push 2026-10-27, MIT [P] — [GitHub API](https://api.github.com/repos/microsoft/TRELLIS)
- "An NVIDIA GPU with at least 16GB of memory is necessary. The code has been verified on NVIDIA A100 and A6000 GPUs." Outputs `sample.glb` (textured mesh, `simplify=0.95`, `texture_size=1024`) and `sample.ply` (3D Gaussians); training code and TRELLIS-text models released 2025-03-25; "Implementation of multi-image conditioning for TRELLIS-image model... tuning-free algorithm" [P] — [README](https://raw.githubusercontent.com/microsoft/TRELLIS/main/README.md)
- Submodules `diffoctreerast` and modified FlexiCubes carry separate licenses [P] — [README](https://raw.githubusercontent.com/microsoft/TRELLIS/main/README.md)
- Official HF Space `microsoft/TRELLIS` is in `CONFIG_ERROR` (not running) as of 2026-11-08 [P] — [HF API](https://huggingface.co/api/spaces/microsoft/TRELLIS)
- CUDA-only upstream; Hi3DGen/Stable3DGen removed its NVIDIA-library dependencies (see below).

#### Microsoft TRELLIS.2 (Dec 2025) — current open-weights frontier
- 12,738 stars, last push 2026-07-10, MIT [P] — [GitHub API](https://api.github.com/repos/microsoft/TRELLIS.2); HF model `microsoft/TRELLIS.2-4B` created 2025-12-01, 2,717,542 downloads, 1,465 likes [P] — [HF API](https://huggingface.co/api/models?search=TRELLIS.2)
- "Our 4B-parameter model generates high-resolution fully textured assets... Sparse 3D VAE with 16× spatial downsampling"; H100 timings: 512³ ~3 s, 1024³ ~17 s, 1536³ ~60 s [P] — [README](https://raw.githubusercontent.com/microsoft/TRELLIS.2/main/README.md)
- "Hardware: An NVIDIA GPU with at least 24GB of memory is necessary. The code has been verified on NVIDIA A100 and H100 GPUs." CUDA Toolkit 12.4 recommended [P] — [README](https://raw.githubusercontent.com/microsoft/TRELLIS.2/main/README.md)
- O-Voxel representation "robustly handles complex structures without lossy conversion: Open Surfaces (e.g., clothing, leaves), Non-manifold Geometry" — i.e., the output representation is explicitly not restricted to closed manifold solids [P] — [README](https://raw.githubusercontent.com/microsoft/TRELLIS.2/main/README.md)
- Output: `sample.glb` "PBR-ready 3D asset in GLB format", `texture_size=4096`, exported in OPAQUE mode by default; dependencies nvdiffrast/nvdiffrec have their own licenses; training code released [P] — [README](https://raw.githubusercontent.com/microsoft/TRELLIS.2/main/README.md)
- HF Space `microsoft/TRELLIS.2`: 2,351 likes, ZeroGPU, RUNNING, last modified 2026-05-20 [P] — [HF API](https://huggingface.co/api/spaces/microsoft/TRELLIS.2)
- Apple Silicon port `shivampkumar/trellis-mac` (506 stars, last commit Apr 2026, MIT port code): "400K+ vertex meshes with baked PBR textures from a single image in ~5 minutes 13 seconds on M4 Pro (24GB, cold start...), pipeline type 512"; "24GB+ unified memory recommended"; "~15GB disk space for model weights"; "Memory usage peaks at around 18GB unified memory during generation"; mesh decimated from ~800K to ~200K faces before texture bake; `--no-texture` exports geometry only; thermal throttling observed (3.5 min to 36 min); weight licenses: TRELLIS.2 MIT, DINOv3 "Meta custom license (gated...)", RMBG-2.0 "CC BY-NC 4.0 (non-commercial...)" [P] — [README](https://raw.githubusercontent.com/shivampkumar/trellis-mac/main/README.md); stars via [shields.io](https://img.shields.io/github/stars/shivampkumar/trellis-mac.json)
- Independent hands-on of trellis-mac on M1 Max 64 GB (published 2026-04-21, updated 2026-05-20): peak RSS 17.5–18.5 GB; only the 512 pipeline ran, 1024 crashed in mesh decoding; generation 152–201 s but the PBR texture bake took 66–224 minutes and produced "red noise scattered across the UV map"; vertex-color output (`--no-texture`) took ~5 min; output 300K–427K verts / 671K–865K tris GLBs; author says 16 GB Macs "will swap and become impractical" and recommends at least 24 GB [S] — [lilting.ch](https://lilting.ch/en/articles/trellis2-m1-max-hands-on)
- MLX port `lyonsno/trellis2mlx` (12 stars, last commit Oct 2026): "A complete textured shoe has been generated on a 16 GB M2 Pro; complex high-resolution objects can need considerably more memory"; `--target-faces`, `--texture-size`, `--resolution 768/1024` options; exports GLB [P] — [README](https://raw.githubusercontent.com/lyonsno/trellis2mlx/main/README.md)
- Known defect issues (see Key Question 4): duplicate inner shells (#140), micro boundary holes on a non-CUDA port (#169).

#### Tencent ARC Pixal3D (May 2026 / Sep 2026) — newest MIT image-to-3D model
- Repo `TencentARC/Pixal3D`: 2.6k stars, last commit Sep 2026 [P] — [shields.io stars](https://img.shields.io/github/stars/TencentARC/Pixal3D.json); LICENSE is MIT, "Copyright (c) 2026 Tencent." [P] — [LICENSE](https://huggingface.co/TencentARC/Pixal3D/raw/main/LICENSE)
- News: "Sep 2026: Release multi-view inference code"; "May 2026: Release training code and data preparation toolkit"; "May 2026: Release the improved version based on Trellis.2 backbone"; "May 2026: Release inference code and online demo"; "Apr 2026: Our paper is accepted to SIGGRAPH 2026"; `main` branch = TRELLIS.2 backbone, `paper` branch = Direct3D-S2 backbone [P] — [README (master)](https://raw.githubusercontent.com/TencentARC/Pixal3D/master/README.md)
- Install requires following TRELLIS.2's installation plus `natten==0.21.0` built for a CUDA arch; inference `python inference.py --image ... --output ./output.glb`; default resolution 1536 (1024 in `--low_vram` mode) [P] — [README](https://raw.githubusercontent.com/TencentARC/Pixal3D/master/README.md)
- Paper: "Pixal3D: Pixel-Aligned High-Fidelity Image to 3D Generation" [S] — [arXiv 2605.10922](https://arxiv.org/html/2605.10922); Tsinghua / Tencent ARC / Victoria Univ. of Wellington authorship [S] — [comfyui-wiki](https://comfyui-wiki.com/en/models/pixal3d/pixal3d)
- HF Space `TencentARC/Pixal3D`: 417 likes, ZeroGPU, RUNNING, modified 2026-05-15 [P] — [HF API](https://huggingface.co/api/spaces/TencentARC/Pixal3D); ComfyUI weights `Comfy-Org/Pixal3D` 858,750 downloads; GGUF quantizations exist (`Aero-Ex/Pixal3D-GGUF`, `raven38/pixal3d-q8_0-v1`) [P] — [HF API](https://huggingface.co/api/models?search=Pixal3D)
- Apple Silicon: open PR #35 "Add macOS Apple Silicon/MPS support" (author jgranie; ready for review 2026-09-12; tested on M3 Max 36 GB: ~35 min 09 s vs 13 min 25 s on RTX A5000 reference; "Meshes keep some nonmanifold and boundary edges. They are not certified watertight or print-ready."; no maintainer response) [P] — [PR #35](https://github.com/TencentARC/Pixal3D/pull/35)
- Apple Silicon via AssetFurnace: "Pixal3D (C++/GGML)" backend runs on "Mac, NVIDIA, AMD", 8.4 GB weights, "compiles with Metal (needs full Xcode)"; MIT code + flow weights, DINOv3 License for the bundled encoder [P] — [AssetFurnace README](https://raw.githubusercontent.com/Bingeljell/image-to-3dlab/main/README.md)

#### Hi3D v1.0 (released 2026-10-23) — open-weights geometry refiner from Hitem3D/Hi3D (Sparc3D lineage)
- Repo `hi3d-official/Hi3Dv1.0`: 683 stars, last commit Oct 2026 [P] — [shields.io](https://img.shields.io/github/stars/hi3d-official/Hi3Dv1.0.json); HF model created 2026-10-16, 162 likes [P] — [HF API](https://huggingface.co/api/models?search=Hi3D)
- "Hi3D v1.0 refines a coarse mesh into high-resolution geometry, conditioned on a reference image of the same object. Built upon the Sparc3D representation"; trained on "approximately two million curated 3D assets"; resolutions 512, 1024, 1536 [P] — [README](https://raw.githubusercontent.com/hi3d-official/Hi3Dv1.0/main/README.md)
- "Requirements: Linux, Python 3.10, an NVIDIA GPU with compute capability 8.0 or newer, and a CUDA toolkit in the 12.0–12.5 range... There is no CPU inference path."; `flash-attn` "has no fallback attention path"; `enable_sequential_cpu_offload` available but "does not establish a minimum supported GPU memory size" [P] — [README](https://raw.githubusercontent.com/hi3d-official/Hi3Dv1.0/main/README.md)
- Output: "Geometry only, batch size one. No textures... Output is recentered and normalized to unit maximum radius, so input world coordinates and absolute scale are not preserved."; "Geometric detail and nominal resolution do not guarantee fitness for a downstream application." [P] — [README](https://raw.githubusercontent.com/hi3d-official/Hi3Dv1.0/main/README.md)
- The example end-to-end script uses Hunyuan3D-2mini as the coarse generator; "The Hunyuan code and weights are third-party releases" [P] — [README](https://raw.githubusercontent.com/hi3d-official/Hi3Dv1.0/main/README.md)
- License "Hi3D Open License Agreement Version 1.0": "Commercial use is permitted under the Agreement. If a related product or service exceeds 200,000 monthly active users or reaches USD 1,000,000 in monthly revenue, notify the Licensor and apply for a separate written license within 60 days"; "Commercial integrations must display `Powered by Hi3D 1.0`"; standalone outputs do not trigger branding/notice obligations [P] — [README](https://raw.githubusercontent.com/hi3d-official/Hi3Dv1.0/main/README.md)
- HF Space `hugging-apps/hi3dv1`: ZeroGPU, RUNNING, modified 2026-10-23 [P] — [HF API](https://huggingface.co/api/spaces/hugging-apps/hi3dv1)
- Apple Silicon: `mlx-community/Hi3Dv1.0-mlx` (created 2026-10-23) via an `mlx-vlm` fork; refines `coarse.obj` + image at 512/1024/1536; can build the coarse mesh from SAM 3D Objects in mlx-vlm "so the whole image-to-mesh" runs on Mac [P] — [HF card](https://huggingface.co/mlx-community/Hi3Dv1.0-mlx/raw/main/README.md)
- Press on the release: "trained on ~2M assets... high-res geometry refinement up to 1536³" [S] — [Morningstar/PR Newswire](https://www.morningstar.com/news/pr-newswire/20261023cn79574/hi3d-v10-goes-open-source-the-first-production-validated-open-source-ai-3d-model)
- Sparc3D paper (v1 2025-05-20, v3 2025-06-12): Sparcubes converts raw meshes into 1024³ surfaces and handles "open surfaces, disconnected components, and intricate geometry"; abstract makes no explicit watertight/printable claim [P] — [arXiv 2505.14521](https://arxiv.org/abs/2505.14521); a search snippet of the HTML version says "all outputs are fully watertight and 3D-printable" [S] — [arXiv HTML v2](https://arxiv.org/html/2505.14521v2)

#### VAST TripoSG (Mar 2025) and TripoSF (Mar 2025)
- TripoSG: 1,891 stars, last push 2025-04-18, MIT; "1.5B parameter rectified flow model and VAE trained on 2048 latent tokens"; "CUDA-enabled GPU with at least 8GB VRAM"; CLI `python -m scripts.inference_triposg --image-input ... --output-path ./output.glb`, with `--faces 5000` to cap face count; TripoSG-scribble released 2025-04 [P] — [GitHub API](https://api.github.com/repos/VAST-AI-Research/TripoSG); [README](https://raw.githubusercontent.com/VAST-AI-Research/TripoSG/main/README.md)
- HF Space `VAST-AI/TripoSG`: 888 likes, ZeroGPU, RUNNING [P] — [HF API](https://huggingface.co/api/spaces/VAST-AI/TripoSG)
- TripoSF (SparseFlex): 778 stars, last push 2025-04-07, MIT; "Ultra-high resolution mesh modeling (up to 1024³)", "natural handling of open surfaces (like cloth or leaves)"; "CUDA-capable GPU (≥12GB VRAM for 1024³ resolution)"; it is a mesh-in → SparseFlex representation model (reconstruction/VAE), not an image-to-3D generator by itself [P] — [README](https://raw.githubusercontent.com/VAST-AI-Research/TripoSF/main/README.md)
- Both CUDA-only upstream; no Mac port found [U]. PartCrafter fine-tunes the TripoSG DiT (see KQ7).

#### Hi3DGen / Stable3DGen (Stable-X, Mar 2025)
- `Stable-X/Hi3DGen` redirects to `Stable-X/Stable3DGen`: 1,290 stars, last push 2025-07-02, MIT; "The model and code of Stable3DGen are adapted from Trellis... we have specifically removed its dependencies on certain NVIDIA libraries (kaolin, nvdiffrast, flex...)"; install uses `spconv-cu{version}` and `xformers` (CUDA) [P] — [GitHub API](https://api.github.com/repos/Stable-X/Stable3DGen); [README](https://raw.githubusercontent.com/Stable-X/Stable3DGen/main/README.md)
- "Normal-bridged geometry on TRELLIS backbone", released 2025-03-28 [S] — [Cinevva](https://app.cinevva.com/guides/ai-3d-model-generation-timeline-2026); HF Space `Stable-X/Hi3DGen` 714 likes [P] — [HF API](https://huggingface.co/api/spaces?search=hi3d)
- VRAM not stated in README [U]. Maintenance: no commits since July 2025 (shields "last commit july 2025") [P] — [shields.io](https://img.shields.io/github/last-commit/Stable-X/Stable3DGen.json)

#### StepFun Step1X-3D (May 2025)
- 901 stars, last push 2025-09-08, Apache-2.0 [P] — [GitHub API](https://api.github.com/repos/stepfun-ai/Step1X-3D)
- Geometry 1.3B + Texture 3.5B (2025-05-13); "GPU Memory Usage 27G... 152 seconds" for geometry+texture (29G with the label model); "hybrid VAE-DiT component produces watertight TSDF representations"; data preprocessing "including advanced watertight method using depth_test and winding_number proposed by CraftsMan3D" (2025-06-26); exports untextured `.glb` then textured `.glb`; environment CUDA 12.4; reuses Hunyuan3D 2.0 custom_rasterizer [P] — [README](https://raw.githubusercontent.com/stepfun-ai/Step1X-3D/main/README.md)
- Official HF Space is PAUSED [P] — [HF API](https://huggingface.co/api/spaces/stepfun-ai/Step1X-3D)
- CUDA-only; multi-view conditioning is an unchecked TODO [P] — [README](https://raw.githubusercontent.com/stepfun-ai/Step1X-3D/main/README.md)

#### DreamTech Direct3D-S2 (May 2025, NeurIPS 2025)
- 1,295 stars, last push 2025-09-26, MIT [P] — [GitHub API](https://api.github.com/repos/DreamTechAI/Direct3D-S2)
- "Generating at 512 resolution requires at least 10GB of VRAM, and 1024 resolution needs around 24GB. We don't recommend generating models at 512 resolution"; `remesh=False` option "if you need to reduce the number of triangles"; `mesh.export('output.obj')`; v1.0 and v1.1 released 2025-05-30; "v1.2 release, featuring enhanced character generation" announced 2025-06-03 (not seen released) [P] — [README](https://raw.githubusercontent.com/DreamTechAI/Direct3D-S2/main/README.md)
- Demo Space `wushuang98/Direct3D-S2-v1.0-demo` runs on `cpu-basic` hardware (so not a live GPU demo) [P] — [HF API](https://huggingface.co/api/spaces/wushuang98/Direct3D-S2-v1.0-demo)
- CUDA 12.1 toolkit required; no Mac path [P] — [README](https://raw.githubusercontent.com/DreamTechAI/Direct3D-S2/main/README.md)

#### UltraShape 1.0 (PKU-YuanGroup, Dec 2025) — refiner
- 873 stars, last commit Jan 2026 [P] — [shields.io](https://img.shields.io/github/stars/PKU-YuanGroup/UltraShape-1.0.json); HF card license `apache-2.0` [P] — [HF card](https://huggingface.co/infinith/UltraShape/raw/main/README.md)
- Two-stage: "First, use Hunyuan3D-2.1 to generate a coarse mesh from your input image", then refine; inference code and weights released 2025-12-26, training code 2025-12-31; "Release data processing scripts" still unchecked; `--low_vram` arg; data pipeline includes "a novel watertight processing method" [P] — [README](https://raw.githubusercontent.com/PKU-YuanGroup/UltraShape-1.0/main/README.md)
- Technical report 2025-12-25 [P] — [arXiv 2512.21185](https://arxiv.org/pdf/2512.21185); CUDA 12.1 recommended; an "ultrashape-mac" community repo exists (search result only) [U] — [search hit](https://github-users.yhajoa.workers.dev/199-biotechnologies/ultrashape-mac)

#### Stability AI SF3D (Aug 2024; "older") and SPAR3D (Jan 2025)
- SF3D: 1,929 stars, last push 2025-01-22, license "Other" (Stability AI Community License); "based on TripoSR"; "default options takes about 6GB VRAM"; GLB output; `--remesh_option` None/Triangle/Quad; "Support for MPS (for Mac Silicon) (experimental)... tested on M1 max 64GB"; "MPS currently consumes more memory... We recommend running the CPU version if your system has less than 32GB of unified memory."; needs `PYTORCH_ENABLE_MPS_FALLBACK=1` [P] — [GitHub API](https://api.github.com/repos/Stability-AI/stable-fast-3d); [README](https://raw.githubusercontent.com/Stability-AI/stable-fast-3d/main/README.md)
- SPAR3D: 1,087 stars, last push 2025-05-05; "By default, SPAR3D consumes 10.5GB of VRAM... low VRAM mode... roughly 7GB"; MPS experimental "tested on M4 max 36GB... OSX 15.2"; same <32 GB → CPU recommendation; GLB output [P] — [GitHub API](https://api.github.com/repos/Stability-AI/stable-point-aware-3d); [README](https://raw.githubusercontent.com/Stability-AI/stable-point-aware-3d/main/README.md)
- Stability AI Community License: free for research, non-commercial and commercial use; "If You are using... for a Commercial Purpose, You must register with Stability AI... If at any time You or Your Affiliate(s)... generate more than USD $1,000,000 in annual revenue" a separate license is needed [P] — [LICENSE.md](https://raw.githubusercontent.com/Stability-AI/stable-fast-3d/main/LICENSE.md)
- Apple Silicon: the only upstream-supported MPS path in this catalogue; AssetFurnace offers SF3D "Mac only" with "gated weights" [P] — [AssetFurnace README](https://raw.githubusercontent.com/Bingeljell/image-to-3dlab/main/README.md)

#### Meta SAM 3D Objects (Nov 2025)
- 7,655 stars, last push 2026-06-02, license "Other" (SAM License) [P] — [GitHub API](https://api.github.com/repos/facebookresearch/sam-3d-objects)
- "reconstructs full 3D shape geometry, texture, and layout from a single image... handling small objects and occlusions"; checkpoints launched 2025-11-19; encoder weights 2026-06-01; artist object set + HF leaderboard 2026-06-02; README example exports a Gaussian splat (`output["gs"].save_ply("splat.ply")`); masked-object input (SAM-style) [P] — [README](https://raw.githubusercontent.com/facebookresearch/sam-3d-objects/main/README.md)
- SAM License: "non-exclusive, worldwide, non-transferable and royalty-free limited license"; redistribution only under the same Agreement; research-publication acknowledgment; Trade Controls / ITAR clause; you own your derivatives [P] — [LICENSE](https://raw.githubusercontent.com/facebookresearch/sam-3d-objects/main/LICENSE); HF weights are gated ("Access to model facebook/sam-3d-objects is restricted") [P] — [HF](https://huggingface.co/facebook/sam-3d-objects)
- Third-party: outputs "a full textured 3D mesh" [S] — [Roboflow](https://roboflow.com/model/sam-3d-objects); in the Topoheal census its outputs appear as "SAM-3D-Objects-3DGS" with 0 of 101 assets measurable as meshes [S] — [Topoheal census](https://topoheal.com/census/)
- Apple Silicon: an MLX implementation exists inside `mlx-vlm` (used by the Hi3D MLX port as the coarse-mesh source) [P] — [Hi3D MLX card](https://huggingface.co/mlx-community/Hi3Dv1.0-mlx/raw/main/README.md)

#### Older (2024) single-image models still referenced: InstantMesh, Unique3D, CraftsMan3D
- InstantMesh: 4,593 stars, last push 2025-01-03, Apache-2.0; exports `.obj` with vertex colors or `--export_texmap`; CUDA ≥12.1 [P] — [GitHub API](https://api.github.com/repos/TencentARC/InstantMesh); [README](https://raw.githubusercontent.com/TencentARC/InstantMesh/main/README.md)
- Unique3D: 3,598 stars, last push 2025-07-17, MIT; "Adapted for Ubuntu 22.04.4 LTS and CUDA 12.1" [P] — [GitHub API](https://api.github.com/repos/AiuniAI/Unique3D); [README](https://raw.githubusercontent.com/AiuniAI/Unique3D/main/README.md)
- CraftsMan3D (`HKUST-SAIL/CraftsMan3D`): 834 stars, last push 2025-06-26; README says MIT; DoraVAE version; ships `watertight_and_sampling.py` data preprocessing; CUDA 12.4 [P] — [GitHub API](https://api.github.com/repos/HKUST-SAIL/CraftsMan3D); [README](https://raw.githubusercontent.com/HKUST-SAIL/CraftsMan3D/main/README.md)

#### Apple Silicon umbrella: AssetFurnace (`Bingeljell/image-to-3dlab`)
- 1.1k stars, last commit 2026-11-07/08 ("yesterday"), Apache-2.0; releases 0.4.0 (2026-10-08) through 0.5.8 (2026-11-08) [P] — [README](https://raw.githubusercontent.com/Bingeljell/image-to-3dlab/main/README.md); [shields.io](https://img.shields.io/github/stars/Bingeljell/image-to-3dlab.json)
- Backend table: Pixal3D (C++/GGML; Mac/NVIDIA/AMD; 8.4 GB weights; MIT + DINOv3 license), Hunyuan3D-MLX "(Xiong, full pipeline)" Mac; "Hunyuan3D-MLX (dgrauet shape + Xiong paint)" Mac; Hunyuan3D-2.1 NVIDIA "24 GB+" (~19.5 GB weights; paint "needs about 21 GB of GPU memory"; "not licensed in the EU, the UK or South Korea"); TRELLIS.2 "Mac, NVIDIA (Linux...)" (~15 GB CUDA weights; Mac Metal port ~16.5 GB, setup ~1 h); Stable Fast 3D "Mac" only [P] — [README](https://raw.githubusercontent.com/Bingeljell/image-to-3dlab/main/README.md)
- Memory hint for 16 GB machines: "FLUX.2 klein Light: the same pictures in about 5 GB of memory instead of 9, suggested on machines with 16 GB or less" (image stage, not the 3D stage) [P] — [README](https://raw.githubusercontent.com/Bingeljell/image-to-3dlab/main/README.md)
- It is a game-asset pipeline (rig/animate), not a print pipeline; no STL/printability features mentioned in README [P] — [README](https://raw.githubusercontent.com/Bingeljell/image-to-3dlab/main/README.md)

### Inferences
- For the user's 16 GB M5 Mac, the only open models with evidence of running locally are: SF3D/SPAR3D (upstream MPS, but upstream itself recommends CPU below 32 GB), Hunyuan3D 2.1 shape via MLX (~7.85 GB peak at octree 384; untextured), Pixal3D via the GGML build in AssetFurnace (memory not stated), and trellis2mlx (one textured object demonstrated on 16 GB). TRELLIS.2 via trellis-mac (~18 GB peak) and Hunyuan3D 2.1 texturing (8 GB swap on 24 GB) are above the 16 GB budget. Hi3D v1.0 upstream is Linux/CUDA-only; its MLX port's memory needs are unstated.
- Since FDM printing only needs geometry, shape-only pipelines (Hunyuan3D 2.1 MLX shape, TRELLIS.2 `--no-texture`, Hi3D geometry refiner, Direct3D-S2, TripoSG) remove the most memory-hungry stage (texturing) and most of the Mac-port breakage reported (texture bake failures).
- Licensing matters for a public repo: TRELLIS.2, Pixal3D, TripoSG, Direct3D-S2, PartCrafter, Step1X-3D (Apache), UltraShape (Apache) are permissive; Hunyuan3D 2.x excludes EU/UK/KR users; PartPacker is non-commercial; Hi3D v1.0 requires "Powered by Hi3D 1.0" branding for commercial integrations; several Mac ports bundle RMBG-2.0 (CC BY-NC) for background removal.
- Maintenance signal: TRELLIS/TRELLIS.2, Pixal3D, PartCrafter, SAM 3D Objects and the Mac ports saw 2026 commits; Hunyuan3D 2.x, TripoSG/SF, Step1X-3D, Direct3D-S2, SF3D/SPAR3D, InstantMesh, Unique3D have had no pushes since 2025.

### Gaps
- No official Tencent open release of Hunyuan3D 2.5/3.0/3.1 was found; one low-quality blog claims 3.0 was open-sourced but links no repository [U] — [search summary](https://story321com.pages.dev/blog/hunyuan-3d-3).
- VRAM requirements are not stated in the READMEs of SAM 3D Objects, Hi3DGen/Stable3DGen, HoloPart, Pixal3D (beyond a low-VRAM mode) or Hi3D v1.0 (which states only that a 96 GB-class GPU was the measured stack) [U].
- Triangle counts are not documented for most generators; the only primary numbers are Hunyuan3D `FaceReducer` default 40,000, TripoSG `--faces` cap, trellis-mac ~800K tris pre-decimation, hy3dmlx 687,024 faces, and Tencent Cloud API `FaceCount` default 500,000. Census medians (secondary) are in KQ5.
- The Reddit-mentioned "ultrashape-mac" and the "Hunyuan3D-MLX (Xiong / dgrauet)" ports referenced by AssetFurnace were not fetched; their memory needs are unknown [U].
- Hi3D v1.0 and Sparc3D watertightness claims were not verifiable from the primary README/abstract (the README explicitly disclaims downstream fitness).

---

## Key Question 2: Commercial image-to-3D APIs, pricing, formats, ownership terms

### Takeaway
Pay-per-generation prices in Nov 2026 cluster around US$0.20–0.60 per textured model: Meshy ~20–35 credits (≈$0.40–0.70 at the Pro plan's $0.02/credit), Tripo 20–50 credits at $0.01/credit ($0.20–0.50), Tencent Hunyuan 3D Pro 25 credits at $0.02/credit ($0.50), Stability SPAR3D $0.04 and SF3D $0.10, Rodin Gen-2.5 from 0.5 credits (credit price plan-dependent; $1.50/credit on the free tier). Meshy is the only vendor with documented, API-exposed printability analysis/repair, multi-color 3MF and auto-split; Tripo, Hi3D and Hunyuan expose part generation; all are API-only from a Mac's perspective.

### Cited Findings

#### Meshy
- API credit costs (official): Image to 3D mesh-only 20 credits on meshy-7.1/meshy-6 (5 on other models); with 2K textures 30; 4K 30; 8K 35; Multi-Image to 3D same schedule; "Ultra geometry surcharge: +5 for geometry_resolution '2k' or '4k'"; Remesh 5; UV Unwrap 5; Convert 1; Resize 1; Analyze Printability free; Multi-Color Print, Repair Printability, Auto Split 10 each; Relief 20; legacy meshy-7 costs the same as meshy-7.1 [P] — [Meshy API pricing](https://docs.meshy.ai/api/pricing)
- Plans (official): Free $0, 100 credits, license CC BY 4.0, no API; Pro $20/mo, 1,000 credits, API access from Pro, "Private license for all assets"; Premium $40, 3,000 credits; Ultra $100, 8,000 credits; Studio $70 team, 5,500 shared; Premium and above "Private & Customer owned"; API asset retention 3 days (Pro/Premium/Ultra), 14 days Studio; downloads `.fbx .obj .usdz .glb .stl .blend`; STL Repair tool; slicer plugins for Bambu Studio, Creality Print, OrcaSlicer, Cura, Elegoo, Lychee; 3MF not mentioned on the pricing page [P] — [Meshy pricing](https://www.meshy.ai/pricing)
- Analyze Printability API (`POST /openapi/v1/print/analyze`): returns `is_watertight`, `volume` (m³), `holes` (boundary loops), `non_manifold_edges`, `degenerate_faces`, `status` healthy/warning/error; optional wall-thickness check with `printer_type` fdm (min wall 1.0 mm) / sla (0.8 mm) / full_color (2.0 mm) and `intended_print_height_mm` or `intended_print_longest_side_mm` (1–1000, default 150 mm; STL's own longest side read as mm); accepts Meshy 6+ task IDs or external `.glb/.gltf/.obj/.fbx/.stl` URLs up to 400 MB; "Analysis is free" [P] — [Analyze Printability docs](https://docs.meshy.ai/api/analyze-printability.md)
- Repair Printability API: described (Chinese docs) as FDM printability repair of non-manifold edges, degenerate faces and holes, returning a watertight printable mesh; textures are removed by repair; changelog adds wall-thickness-aware repair [S/P] — [search summary of docs.meshy.ai](https://docs.meshy.ai/zh/api/repair-printability); [changelog](https://docs.meshy.ai/api/changelog)
- Docs banner: "lowpoly retires Oct 30, 2026" [P] — [docs page](https://docs.meshy.ai/api/analyze-printability)
- Release dates (secondary): Meshy 6 GA 2026-01-18 ("Low Poly Mode, multi-colour print export"), multiview upgrade 2026-08-07 ("main view plus up to three auxiliary views"), Meshy 7 2026-08-12 [S] — [Cinevva](https://app.cinevva.com/guides/ai-3d-model-generation-timeline-2026)

#### Tripo (VAST)
- Developer platform: "1 credit = $0.01 USD"; "3D generation: $0.10 per model, from 10 credits... image to 3D and multiview to 3D are 20–30 each"; model processing: texturing 10–30, format conversion 5–10, retopology 10–40, "segmentation and completion 30–50"; outputs "GLB, FBX, OBJ, USDZ and other mainstream formats"; per-task concurrency quotas (numbers not given); ownership terms not stated [P] — [developers.tripo3d.ai](https://developers.tripo3d.ai/)
- Model v3.1 (H3.1, `v3.1-20260211`) credit table: Image to 3D 20 (no texture) / 30 (standard) / 40 (detailed) / 50 (8K); Multiview to 3D identical; add-ons: detailed geometry +20, quad mesh +5, smart low-poly +10, "Generate in parts +20"; `face_limit` up to 1.5M by default, 2M with `geometry_quality=detailed`, 150K with quad; `generate_parts` requires `texture=false` and `pbr=false`; rate limit 10 parallel tasks; v3.0-20250812 and v2.5-20250123 remain available; no STL/3MF or printing features mentioned on this page [P] — [Tripo v3.1 model page](https://developers.tripo3d.com/en/models/v3-1)
- Consumer plans (official page, via search snippet; the page itself returned HTTP 403 to fetch): Free 200 credits/month (up to 8 models), Pro $19.9/month with 3,000 credits (up to 120 models), 10 concurrent tasks [S] — [tripo3d.ai/pricing](https://tripo3d.ai/pricing)
- AWS Marketplace listing: usage beyond prepaid credits billed at $0.01 per credit [S] — [AWS Marketplace](https://aws.amazon.com/marketplace/pp/prodview-hwlbvx7vubh7c)
- Export formats per press roundup: STL, OBJ, FBX, GLB, USD, 3MF [S] — [3Dnatives](https://www.3dnatives.com/en/ai-3d-model-generators-3d-printing-13082026/); Tripo P1.0 and H3.1 released 2026-03-09 [S] — [Cinevva](https://app.cinevva.com/guides/ai-3d-model-generation-timeline-2026)
- Hosted via fal.ai and WaveSpeed as `tripo3d/tripo/v2.5/image-to-3d` and `tripo3d/h3.1/image-to-3d` (prices not captured) [S] — [fal model page](https://fal.ai/models/tripo3d/tripo/v2.5/image-to-3d); [WaveSpeed](https://www.wavespeed.ai/models/tripo3d/h3.1/image-to-3d)

#### Hyper3D Rodin (Deemos)
- Plans: Free $0 (direct credits $1.5 per credit); Creator $30/mo ($24 yearly), "About 60 models"; Business $120/mo ($96 yearly), "About 416 models", "Full API access", 120 RPM (240 on higher tiers); Enterprise custom; Creator+ "Unlimited export and any use"; "3D Printing" appears only as a Use Cases nav link [P] — [hyper3d.ai/pricing](https://hyper3d.ai/pricing)
- Gen-2.5 API: `images` accepts one to five images, "The first image drives material generation"; tiers Gen-2.5-Extreme-Low / Low / Medium / High / Extreme-High; Extreme-High "also returns an extra mesh of up to 10M faces"; `geometry_file_format` shows glb/fbx/usdz (obj/stl not mentioned on this page); `mesh_mode` shown only as Raw; `addons: HighPack`; credits: "Base generation costs 0.5 credits. Gen-2.5-Extreme-High adds 0.5, and texture_mode=extreme-high adds 2.0"; no parts/bbox options [P] — [Rodin Gen-2.5 API spec](https://docs.hyper3d.ai/en/api-specification/rodin-gen2-5)
- Features page: Gen-1/1.5 tiers Sketch/Regular/Detail/Smooth with multi-image `concat` and `fuse`; costs reported per task via `consumed`; parallel-task cap [P] — [features](https://docs.hyper3d.ai/en/get-started/features)
- Rodin Gen-2 released 2025-10-01 ("10B parameters; recursive part-based generation"), Gen-2.5 2026-05-26 ("Raw output above 10M polygons") [S] — [Cinevva](https://app.cinevva.com/guides/ai-3d-model-generation-timeline-2026); exports STL, OBJ, FBX, GLB, GLTF, USDZ; "High-Poly Quads" option [S] — [3Dnatives](https://www.3dnatives.com/en/ai-3d-model-generators-3d-printing-13082026/)

#### Tencent Hunyuan 3D (hosted, 3.0/3.1)
- Billing: postpaid 0.02 USD/credit; prepaid packs 1,000 credits $15, 10,000 $145, 50,000 $700, 100,000 $1,350; free one-time 200 credits; Professional: Normal (textured) 25 credits, LowPoly 30, Geometry (untextured) 15, Sketch 25; add-ons +10 each for MultiViewImages, EnablePBR, FaceCount; "Selecting version 3.0 or 3.1... adds no extra credits"; Express 15 credits (+10 PBR); post-processing: 3D Part Generation 30, Smart Topology 50, UV Unfold 10, Auto Rigging 10, Convert 3D Format 5; concurrency add-on $5,000 per concurrency per month; default concurrency 3 (Professional) / 1 (Express); failed calls not charged; page last updated 2026-05-08 [P] — [Tencent Cloud billing overview](https://www.tencentcloud.com/document/product/1284/75281)
- Submit API parameters (Model 3.0/3.1, FaceCount 3,000–1,500,000, GenerateType, PolygonType, MultiViewImages) [P] — [API doc](https://www.tencentcloud.com/document/product/1284/75540); data type `File3D.Type` "valid values: GIF or OBJ or Image" (GLB/STL not listed in the data-types page) [P] — [data types](https://www.tencentcloud.com/document/product/1284/75542)
- Resellers: WaveSpeed "Hunyuan 3D V3.1 Image-to-3D Rapid" $0.27 per generation, single image only, ~62 s, GLB preview [P] — [WaveSpeed](https://wavespeed.ai/models/wavespeed-ai/hunyuan-3d-v3.1/image-to-3d-rapid); fal.ai lists "Hunyuan 3D Pro Image to 3D API" (`hunyuan-3d-v3.1-pro`) [P] — [fal 3D API overview](https://fal.ai/docs/model-api-reference/3d-api/overview.md); third-party price claims range $0.0225–$0.675 per generation across hosts [S] — [search summary](https://okmiku.com/blog/tencent-hunyuan-3d-3-1-pro-vs-rapid)
- Bambu MakerLab reportedly offers "Hunyuan 3.1" as a selectable model [S] — [Fabbaloo (snippet; page returned 403)](https://www.fabbaloo.com/news/bambu-lab-integrates-meshy-6-into-makerlab-expanding-ai-image-to-3d-capabilities)

#### Stability AI (SF3D / SPAR3D API)
- "Stable Fast 3D: 10 credits ($0.10)"; "Stable Point Aware 3D (SPAR3D): 4 credits ($0.04)"; "1 credit = $0.01" [P] — [Stability pricing](https://docs.stability.ai/pricing)

#### Hi3D / Hitem3D (hosted)
- Third-party directory (states vendor site checked 2026-11-03): Free 100 lifetime credits; Pro 1,000 credits/mo; Max 4,000; Ultra 10,000; generation 10–130 credits (v2.1 Fast 10, v3.0 Quality 30, v3.0 Master 130); Split to Print 20; Multi-color Print 10; Relief 10; exports STL, OBJ, 3MF, GLB, USDZ plus direct send to Bambu Studio/OrcaSlicer; API documented at platform.hi3d.ai; paid plans allow private/commercial use, free plan requires attribution; dollar prices "not published on the vendor's site" [S] — [Stork.ai](https://www.stork.ai/en/hi3d)
- API credit price reportedly $0.02/credit [S] — [search summary](https://docs.hitem3d.ai/en/api/getting-started/pricing)
- Hi3D's own sites (hi3d.ai, hitem3d.ai, platform.hi3d.ai, docs.hitem3d.ai) did not resolve from this environment [U].

#### Bambu Lab MakerWorld / MakerLab
- "Image-to-3D is driven by Meshy-6"; "each export draws 2 MakerLab credits"; exports STL or 3MF; multi-color workflow exports .3MF with Meshy "Multi-Color Printing" mapping textures to AMS filament zones (article 2026-03-27) [P] — [3D Printing Industry](https://3dprintingindustry.com/news/meshy-and-makerworld-team-up-to-put-ai-3d-model-generation-in-bambu-lab-users-hands-250281/)
- Fabbaloo (snippet): Meshy 6 "added alongside Hunyuan 3.1 and Tripo AI 3.0"; earlier versions relied on Tencent's Hunyuan [S] — [Fabbaloo](https://www.fabbaloo.com/news/bambu-lab-integrates-meshy-6-into-makerlab-expanding-ai-image-to-3d-capabilities)
- PrintU (photo → bobblehead figure): "ten MakerWorld credits"; download .STL or .3MF; hair depth "only depicted rudimentarily"; back "reconstructed speculatively" (article 2025-12-09, not a hands-on print test) [S] — [igor'sLAB](https://www.igorslab.de/en/bambu-lab-printu-from-portrait-photo-to-3d-figure-comfortable-fast-but-not-without-hooks/)
- Older (May–Jul 2024) forum thread on the first MakerLab Image-to-3D (Tripo3D-based): server errors, free 10 uses/month, textures lost in Cura, users advised Blender remesh; no print reports [S, older] — [Bambu forum](https://forum.bambulab.com/t/new-makerlab-tool-image-to-3d-model/76805)
- No public MakerLab API found [U].

#### 3D AI Studio (aggregator)
- Image to 3D 20 credits; packs 2,000 credits $34, 5,000 $69, 35,000 $399; plans Basic 1,000 / Studio 3,500 / Pro 18,000 credits per month (dollar prices unreadable in fetch); "Includes Meshy, Tripo, Rodin & more"; exports GLB, OBJ, FBX, STL, USDZ, PLY; assets "fully owned by the user", commercial use allowed; "dedicated API access" by contacting support; no watertight/repair/hollowing tools [P] — [3daistudio.com/pricing](https://www.3daistudio.com/pricing)
- Claims TRELLIS.2 at 10 credits and Hunyuan 3D at 35–100 credits on its platform [S] — [search summary](https://www.3daistudio.com/blog/is-trellis-2-free-pricing-how-to-get-started)

#### Others
- Kaedim: no official pricing page found; third-party figures conflict ($22–$1,200/month tiers; "quote-based"); enterprise API mentioned [S/U] — [Capterra](https://www.capterra.com/p/10015122/Kaedim/); [Costbench](https://www.costbench.com/software/ai-3d-generation/kaedim/hidden-costs/)
- Luma Genie: lumalabs.ai homepage (news through 2026-06-16) does not mention Genie; an aggregator still lists `genie-3d` on the Luma API (released 2025-08-05, last refreshed 2026-04-18, "stale") [U] — [lumalabs.ai](https://lumalabs.ai/genie); [LLM Reference](https://www.llmreference.com/model/genie-3d/luma-api)
- Autodesk Project Bernini: May 2024 research project, "strictly experimental... not available for public use"; no 2026 update found [S, older] — [Axios](https://www.axios.com/2024/05/08/autodesk-ai-3d-models-bernini)
- Adobe Substance 3D: AI features are image-to-material/texture, not image-to-mesh; no 2026 image-to-3D product found [S, older] — [Adobe Research](https://research.adobe.com/news/behind-the-tech-image-to-material-in-adobe-substance-3d-sampler-and-adobe-capture)
- CSM: "CSM's site has been offline since January 2026" [S, vendor blog] — [Meshy blog](https://www.meshy.ai/blog/best-ai-tools-for-3d-printing)
- Neural4D: markets "text-to-STL" with watertight output (vendor claim) [S] — [Neural4D](https://www.neural4d.com/features/text-to-stl)

### Inferences
- Effective per-model cost at the entry paid tier: Meshy Pro $20/1,000 credits = $0.02/credit → image-to-3D mesh-only ≈ $0.40, with 2K texture ≈ $0.60, plus $0.20 for Repair Printability; Tripo ≈ $0.20 geometry-only / $0.30 textured; Tencent Pro ≈ $0.30 geometry-only (15 credits) / $0.50 textured at the postpaid rate; Rodin Gen-2.5 base ≈ $0.75 at the free-tier $1.50/credit rate (plan credit rates not published). These are my calculations from the cited credit tables, not vendor-stated USD prices.
- For a deterministic "image → STL/3MF" pipeline, Meshy is the only vendor whose API returns machine-readable printability metrics (watertight, holes, non-manifold edges, thin walls at an intended print size) and a repair task; everything else needs a client-side repair step.
- Ownership: Meshy free tier outputs are CC BY 4.0 (not private); 3D AI Studio and Meshy Premium+ state customer ownership; Tripo, Rodin and Tencent docs fetched do not state ownership terms.

### Gaps
- Official Tripo plan page and Fabbaloo returned HTTP 403; Hi3D domains did not resolve; Kaedim has no public pricing; Luma Genie status unconfirmed [U].
- Rodin per-credit price on Creator/Business plans is not published (only "about 60 / 416 models") [U].
- Tencent Cloud output format list is ambiguous (data types page lists only GIF/OBJ/Image; API doc says Geometry mode is "only GLB output") [U].
- No vendor publishes ownership/IP terms for API output in the pages fetched except Meshy and 3D AI Studio [U].

---

## Key Question 3: Hosted inference for open models without a local GPU

### Takeaway
Open models are cheap to run hosted: fal.ai TRELLIS $0.02/generation, TRELLIS.2 $0.25–0.35, Hunyuan3D v2 multi-view $0.16; Replicate Hunyuan3D-2 ≈ $0.04–0.11/run and TRELLIS ≈ $0.04/run (TRELLIS.2 ≈ $0.93/run because of 4–8 min cold setup); Hugging Face ZeroGPU Spaces give 5 GPU-minutes/day free (40 min on PRO + $1 per 10 min) for Hunyuan3D-2/2.1, TRELLIS.2, Pixal3D, Hi3D v1 and TripoSG; raw GPU rental (Modal A100-80GB $0.000694/s ≈ $2.50/h; RunPod A100 80GB $1.19–1.79/h, L40S $0.79–1.09/h) is the route for Hi3D v1.0, Pixal3D, Step1X-3D, Direct3D-S2, PartCrafter which have no turnkey hosted endpoints.

### Cited Findings
- fal.ai `fal-ai/trellis`: "$0.02 per generation"; single `image_url`; outputs mesh/GLB (plus Gaussians/radiance fields) [P] — [fal TRELLIS](https://fal.ai/models/fal-ai/trellis)
- fal.ai `fal-ai/trellis-2`: "$0.25 at 512p, $0.30 at 1024p, and $0.35 at 1536p" per request; image URL input; GLB output; "Commercial use" tag [P] — [fal TRELLIS.2](https://fal.ai/models/fal-ai/trellis-2)
- fal.ai `fal-ai/hunyuan3d/v2/multi-view`: "$0.16 per generation"; front, back, left image URLs required; sample output `white_mesh.glb` (~720 KB) [P] — [fal Hunyuan3D v2 MV](https://fal.ai/models/fal-ai/hunyuan3d/v2/multi-view)
- fal.ai 3D API overview lists Trellis 2, Hunyuan 3D Pro (v3.1), Trellis [P] — [fal docs](https://fal.ai/docs/model-api-reference/3d-api/overview.md); aggregator prices: Hunyuan3D v2 multi-view turbo $0.015, v3.1 Rapid $0.225, v3 $0.375 [S] — [costgoat](https://costgoat.com/pricing/hunyuan-3d)
- Replicate `tencent/hunyuan3d-2`: "approximately $0.044 per run, or 22 runs per $1", Nvidia L40S, ~46 s; outputs via trimesh "glb/obj" [P] — [Replicate](https://replicate.com/tencent/hunyuan3d-2)
- Replicate `ndreca/hunyuan3d-2` (Turbo): ~$0.11/run, L40S, ~108 s [P] — [Replicate](https://replicate.com/ndreca/hunyuan3d-2)
- Replicate `firtoz/trellis`: ~$0.038/run (~26 runs per $1), A100 80GB, ~28 s; one input image; `mesh_simplify` 0.95, `texture_size` 1024; GLB output; fan-maintained, "not officially affiliated with Microsoft" [P] — [Replicate](https://replicate.com/firtoz/trellis)
- Replicate `fishwowater/trellis2`: ~$0.93/run, A100 80GB, "typically complete within 12 minutes", setup 4–8 min; must also follow DINOv3 and BRIA RMBG-2.0 licenses [P] — [Replicate](https://replicate.com/fishwowater/trellis2)
- Replicate `camenduru/instantmesh`: "approximately $0.19 to run" (5 runs per $1) [S] — [Replicate (snippet)](https://replicate.com/camenduru/instantmesh); `aryamansital/instant_mesh` 263K runs [S] — [Replicate](https://replicate.com/aryamansital/instant_mesh)
- No Replicate page found for Hi3D, Pixal3D or Hunyuan3D-2.1 [U]; Eachlabs lists Hunyuan 3D v2.1 at $0.30/execution and SaladCloud claims ~$0.009/generation self-hosted [S] — [Eachlabs](https://www.eachlabs.ai/tencent/hunyuan-3d/hunyuan-3d-v2-1); [SaladCloud](https://blog.salad.com/hunyuan3d-2-1/)
- Hugging Face ZeroGPU: hardware "NVIDIA RTX Pro 6000 Blackwell" (`large` = half card, 48 GB; `xlarge` full, 96 GB, 2× quota); daily quota Unauthenticated 2 min, Free account 5 min, PRO 40 min (extensible at "$1 per 10 minutes"), Team 40 min, Enterprise 60 min; Gradio-only; default 60 s per call, extendable via `duration`; free accounts can host 2 ZeroGPU Spaces [P] — [HF ZeroGPU docs](https://huggingface.co/docs/hub/spaces-zerogpu)
- ZeroGPU Spaces running on 2026-11-08: `tencent/Hunyuan3D-2`, `tencent/Hunyuan3D-2.1`, `microsoft/TRELLIS.2`, `TencentARC/Pixal3D`, `hugging-apps/hi3dv1`, `VAST-AI/TripoSG` (API reports hardware `zero-a10g`); `microsoft/TRELLIS` CONFIG_ERROR; `stepfun-ai/Step1X-3D` PAUSED; Direct3D-S2 demo on `cpu-basic` [P] — [HF API example](https://huggingface.co/api/spaces/microsoft/TRELLIS.2)
- Modal per-second GPU prices: H100 $0.001097, A100 80 GB $0.000694, A100 40 GB $0.000583, L40S $0.000542, A10 $0.000306, L4 $0.000222, T4 $0.000164; Starter plan "$30 / month free credits"; billing change effective 2026-09-01 [P] — [modal.com/pricing](https://modal.com/pricing)
- RunPod (page updated 2026-11-04): A100 80GB PCIe $1.79/h secure / $1.19 community; H100 PCIe $2.89 / $1.99; L40S $1.09 / $0.79; RTX 4090 $0.89 / $0.34; RTX 6000 Ada $0.99 / $0.74; RTX A6000 $0.59 / $0.33; serverless A100 $2.72/h, H100 $5.39/h, L40S $1.75/h, RTX 4090 $1.34/h [P] — [runpod.io/pricing](https://www.runpod.io/pricing)
- Hunyuan3D-2 ships an API server (`curl ... -o test2.glb`) and TRELLIS.2/Hunyuan3D are packaged for ComfyUI (`Comfy-Org/TRELLIS.2` 375,525 downloads; `Comfy-Org/Hunyuan-3D-2.1` 120,764) — relevant for self-hosting on rented GPUs [P] — [Hunyuan3D-2 README](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-2/main/README.md); [HF API](https://huggingface.co/api/models?search=TRELLIS.2)

### Inferences
- Per-generation cost on rented GPUs: TRELLIS.2 at 1536³ takes ~60 s on H100 (README) → ≈ $0.07 on Modal H100 excluding cold start; Hunyuan3D 2.1 shape (10 GB VRAM) fits an L4/A10 at ≈ $0.02–0.03 per minute of runtime. Cold-start weight loading (15–30 GB) dominates cost on serverless unless kept warm.
- ZeroGPU's 5 free minutes/day is enough for a handful of test generations via `gradio_client`, but not for a batch pipeline; PRO at 40 min + $1/10 min is the cheapest "no GPU" route for Pixal3D and Hi3D v1, which have no fal/Replicate endpoints.
- The HF API's `zero-a10g` hardware label contradicts the docs' RTX Pro 6000 statement; treat the label as legacy naming.

### Gaps
- No hosted endpoint found for Hi3D v1.0, Pixal3D, Step1X-3D, Direct3D-S2, PartCrafter, UltraShape outside HF Spaces [U].
- fal.ai price for `hunyuan-3d-v3.1-pro` not captured (page URL guess returned 404) [U].
- Replicate run counts and exact version hashes were not captured.

---

## Key Question 4: Print-readiness of generated meshes (watertight/manifold, typical defects, explicit print modes)

### Takeaway
No generator's primary documentation guarantees watertight, manifold, solid output; several (TRELLIS.2, TripoSF, Sparc3D) explicitly target open-surface/non-manifold topology, and open GitHub issues document duplicate inner shells (TRELLIS.2), thin double-shell leaks (Pixal3D via `remesh=True`) and micro boundary holes on a non-CUDA port (TRELLIS.2/ROCm). Vendor-measured numbers put even the best commercial tool at 55% fully watertight out of export (Meshy, 97% slicing in Bambu Studio after its checks). Explicit print tooling exists only on the commercial side (Meshy analyze/repair/auto-split/multi-color, Hi3D split-to-print, Tripo auto-repair/parts, Hunyuan Cloud part generation); the open side offers only generic post-processors (Hunyuan `FloaterRemover`/`DegenerateFaceRemover`) and watertight data-prep scripts.

### Cited Findings

#### What the models' own docs say about topology
- TRELLIS.2 O-Voxel "robustly handles... Open Surfaces (e.g., clothing, leaves), Non-manifold Geometry" [P] — [README](https://raw.githubusercontent.com/microsoft/TRELLIS.2/main/README.md)
- TripoSF: "natural handling of open surfaces (like cloth or leaves)" [P] — [README](https://raw.githubusercontent.com/VAST-AI-Research/TripoSF/main/README.md)
- Sparc3D (Hi3D's base): handles "open surfaces, disconnected components" [P] — [arXiv abstract](https://arxiv.org/abs/2505.14521)
- Step1X-3D: "produces watertight TSDF representations"; training data made watertight via depth_test + winding_number [P] — [README](https://raw.githubusercontent.com/stepfun-ai/Step1X-3D/main/README.md)
- Hunyuan3D-2 ships `FloaterRemover`, `DegenerateFaceRemover`, `FaceReducer(max_facenum=40000)`, `MeshSimplifier` post-processors — evidence that floaters and degenerate faces are expected outputs [P] — [postprocessors.py](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-2/main/hy3dgen/shapegen/postprocessors.py)
- Hi3D v1.0: output "recentered and normalized to unit maximum radius, so input world coordinates and absolute scale are not preserved"; "Geometric detail and nominal resolution do not guarantee fitness for a downstream application" [P] — [README](https://raw.githubusercontent.com/hi3d-official/Hi3Dv1.0/main/README.md)
- UltraShape and CraftsMan3D publish watertight data-processing methods (training-side), not output guarantees [P] — [UltraShape README](https://raw.githubusercontent.com/PKU-YuanGroup/UltraShape-1.0/main/README.md); [CraftsMan3D README](https://raw.githubusercontent.com/HKUST-SAIL/CraftsMan3D/main/README.md)
- SF3D/SPAR3D offer `--remesh_option` triangle (Botsch-Kobbelt) or quad (Instant Meshes) [P] — [SF3D README](https://raw.githubusercontent.com/Stability-AI/stable-fast-3d/main/README.md)

#### Defects documented in GitHub issues (primary, user-reported, no maintainer responses)
- TRELLIS.2 #140 "Trellis generating duplicate inner mesh walls" (2026-03-22, open): "Most generations add an entire inner shell of the mesh"; a later commenter describes inner shells "welded to the outer shell through the mesh's own holes"; workarounds are ray-cast scripts deleting faces no ray escapes from (minutes per dense mesh); no maintainer reply [P] — [issue #140](https://github.com/microsoft/TRELLIS.2/issues/140)
- TRELLIS.2 #169 (2026-06-11, open): on a ROCm port, "tens of thousands of micro boundary defects (missing single triangles, missing vertex fans)", ~220K boundary edges before `fill_holes`, while "The official reference output is watertight with 0 boundary edges"; root cause proposed: hard `> 0` thresholds on logits that flip under cross-platform fp16 differences; no maintainer response [P] — [issue #169](https://github.com/microsoft/TRELLIS.2/issues/169)
- Pixal3D #18 "thin shell double parallel surfaces with small hole leaks" (2026-05-22, open): mesh "composed of two parallel surfaces" with tiny bridging holes, "unsuitable for 3D printing"; identified cause: `remesh=True` triggers TRELLIS.2 o_voxel dual contouring; default `False` avoids it; other workarounds: `remesh_project 0.99`, visibility filtering [P] — [issue #18](https://github.com/TencentARC/Pixal3D/issues/18)
- Pixal3D PR #35 (MPS port): "Meshes keep some nonmanifold and boundary edges. They are not certified watertight or print-ready." [P] — [PR #35](https://github.com/TencentARC/Pixal3D/pull/35)
- Hunyuan3D-2 issue #113 "试了一个非watertight的例子" (tried a non-watertight example) and #278 (request to fine-tune for non-watertight meshes) exist (titles only) [P] — [issue search](https://api.github.com/search/issues?q=repo:Tencent-Hunyuan/Hunyuan3D-2+watertight)

#### Vendor and press measurements (secondary)
- Meshy blog (first posted 2026-03-05, updated 2026-10-27; vendor): 75 image-to-3D models across 10 categories; tools Meshy, Hitem3D/Hi3D, Tripo, Rodin, CSM (Hunyuan3D not benchmarked); Materialise Magics for hole count/non-manifold edges, Bambu Studio for slice validation, PrusaSlicer cross-check; "Meshy character/figurine models passed Bambu Studio slicing at a 97% rate"; "55% of Meshy models were fully watertight (zero holes) straight out of export. The rest typically had 1–3 small holes at fine-detail points such as hair tips and fingers"; 9-point Printability Score: Meshy 8/9, Hi3D 7/9, Tripo 5/9, Rodin 1/9; "Rodin's STL exports needed substantial repair for non-manifold edges"; thin-wall guidance ≥1.2 mm FDM, "walls under 0.8 mm... fail on FDM"; STL offered by all five, 3MF by Meshy/Hi3D/Tripo; Meshy Print panel: free printability check, AI Auto-Repair, Auto Split, Add Base, Multi-Color Print ("4 colors by default, up to 16"); Hi3D "watertight-by-construction" claim, Auto Character Split with connectors, no printability report; Tripo auto-repair before export; Rodin and Hunyuan3D no print tooling [S] — [Meshy blog](https://www.meshy.ai/blog/best-ai-tools-for-3d-printing)
- 3Dnatives (2026-08-13, updated 2026-09-04): explicitly "reports no hands-on print tests"; repeats Meshy's 97%; Meshy check flags "thin walls, floating parts, holes, and non-manifold edges"; Auto Repair addresses "broken meshes and inverted normals"; "dimensions are not exact and features under 1 mm can be fragile, so real-world dimensions should be scaled in the slicer"; Hi3D "watertight... Segmentation splits large models into printable parts with connectors, and a tolerance system adjusts assembly clearances"; Neural4D "closed... ready to print without prior repair"; Tripo no watertight claim; export table (Hi3D OBJ/GLB/STL/FBX/USDZ + 3MF from multicolor mode; Tripo STL/OBJ/FBX/GLB/USD/3MF; Rodin STL/OBJ/FBX/GLB/GLTF/USDZ) [S] — [3Dnatives](https://www.3dnatives.com/en/ai-3d-model-generators-3d-printing-13082026/)
- 3dprinting.com roundup: "every AI result still needs a repair pass before slicing"; Tripo "20–40 min manual repair... on complex subjects" [S] — [3dprinting.com](https://3dprinting.com/software-guides/ai-3d-model-generators/)
- 3D AI Studio's competitor blog notes the 97% / 55% figures "come from vendors measuring their own models" [S] — [3daistudio blog](https://www.3daistudio.com/blog/best-ai-tools-for-3d-printing-2026)
- Hobbyist Reddit experiment (Apr 2025): diffusion image → rembg → Hunyuan3D-2 → slicer; "the meshes are watertight, printable", "surprisingly solid" for decorative prints, "isn't engineering-grade" (self-reported; thread fetch blocked, text from search snippet) [S] — [r/StableDiffusion mirror](https://redlib.hbubli.cc/r/StableDiffusion/comments/1karts6/experiment_text_to_3dprinted_object_via_ml/mpq2ri2)
- Bambu forum (2024, older MakerLab tool): texture loss in Cura, remesh/smooth in Blender advised; no mesh-defect or print reports [S, older] — [Bambu forum](https://forum.bambulab.com/t/new-makerlab-tool-image-to-3d-model/76805)

#### Explicit print-oriented modes/features (by vendor)
- Meshy API: Analyze Printability (free; `is_watertight`, `holes`, `non_manifold_edges`, `degenerate_faces`, `volume`, thin-wall ratio at `printer_type=fdm` 1.0 mm min wall and intended print size), Repair Printability (10 credits; returns watertight mesh, strips textures), Auto Split (10), Multi-Color Print (10), Relief (20), "Analyze Printability: free" [P] — [API pricing](https://docs.meshy.ai/api/pricing); [analyze docs](https://docs.meshy.ai/api/analyze-printability.md)
- Meshy web: STL export, STL Repair tool, slicer plugins (Bambu Studio, OrcaSlicer, Cura, Creality, Elegoo, Lychee) [P] — [pricing page](https://www.meshy.ai/pricing)
- Tripo: `generate_parts` (+20 credits, geometry-only), `quad` mesh (+5), `smart low-poly` (+10), `face_limit` [P] — [Tripo v3.1](https://developers.tripo3d.com/en/models/v3-1)
- Tencent Hunyuan Cloud: GenerateType "Geometry" (untextured white model), `FaceCount`, 3D Part Generation (30 credits), Smart Topology (50) [P] — [billing](https://www.tencentcloud.com/document/product/1284/75281); [API](https://www.tencentcloud.com/document/product/1284/75540)
- Hi3D (hosted): Split to Print, Multi-color Print, Relief, direct send to Bambu Studio/OrcaSlicer [S] — [Stork.ai](https://www.stork.ai/en/hi3d)
- Bambu MakerLab: export STL/3MF (2 credits); PrintU figures STL/3MF [P/S] — [3DPI](https://3dprintingindustry.com/news/meshy-and-makerworld-team-up-to-put-ai-3d-model-generation-in-bambu-lab-users-hands-250281/); [igor'sLAB](https://www.igorslab.de/en/bambu-lab-printu-from-portrait-photo-to-3d-figure-comfortable-fast-but-not-without-hooks/)
- Open-source: Hunyuan3D-2 `FloaterRemover`/`DegenerateFaceRemover`/`FaceReducer`; TripoSG `--faces`; Direct3D-S2 `remesh`; SF3D/SPAR3D remesh options; Hunyuan3D 2.1 Mac port exports `.stl` directly [P] — see READMEs cited above and [hunyuan3d-2.1-mac](https://raw.githubusercontent.com/VladimirTalyzin/hunyuan3d-2.1-mac/main/README.md)

#### Scale/units
- Meshy analyze treats an STL's longest side as millimetres and defaults GLB prints to 150 mm height [P] — [analyze docs](https://docs.meshy.ai/api/analyze-printability.md); Hi3D v1.0 normalises to unit radius [P] — [README](https://raw.githubusercontent.com/hi3d-official/Hi3Dv1.0/main/README.md); 3Dnatives: "dimensions are not exact... scaled in the slicer" [S]

### Inferences
- All generators normalise output to a unit box/sphere (GLB has no physical units), so a pipeline must impose scale (target height/longest side) itself; Meshy's 150 mm default is a reasonable template.
- Iso-surface/SDF-based open models (Hunyuan3D 2.x, TripoSG, Step1X-3D, Direct3D-S2, Hi3D) are structurally more likely to produce closed surfaces than O-Voxel/SparseFlex models (TRELLIS.2, Pixal3D main branch, TripoSF), which deliberately support open surfaces; the census "failed lint" counts (KQ5) point the same way (Hunyuan3D-2.1 4/101, SF3D 5/101, SPAR3D 9/101 vs TRELLIS.2 101/101, TripoSG 101/101) but those metrics are vendor-run and partially withheld.
- Because defects (floaters, 1–3 small holes, degenerate faces, inner shells, non-manifold edges) are reported across all models, a deterministic repair stage (hole fill, largest-component keep, inner-shell removal, remesh/voxel-solidify, min wall thickening) is unavoidable; the Meshy Repair API, if used, also removes textures, which is fine for single-colour FDM.
- Multi-colour FDM support currently exists only in commercial tools (Meshy Multi-Color Print 3MF with AMS mapping; Hi3D multicolor 3MF); open models output textured GLBs that would need a texture→segment→3MF step.

### Gaps
- No independent (non-vendor), controlled study measuring watertightness/manifoldness/printability across open models on the same image set was found; the Meshy benchmark is vendor-run and the Topoheal census (KQ5) withholds its watertight/non-manifold columns [U].
- No per-model data on internal cavities, inverted normals or hollow-vs-solid behaviour from primary sources; only Meshy marketing mentions inverted normals [U].
- Whether the TRELLIS.2 ROCm hole defect (#169) reproduces on Apple MPS is not documented; the trellis-mac hands-on reports unusable PBR bakes but not boundary-edge counts [U].
- The Reddit hobbyist thread and Fabbaloo/Bambu wiki pages could not be fetched directly (403/402); claims from them are snippet-level [U].

---

## Key Question 5: 2025–2026 benchmarks or head-to-head comparisons of mesh geometric quality

### Takeaway
There is still no standard, independent printability benchmark. The closest things are: Topoheal's vendor-run "census" (v1.0, 2026-08-17; 2,307 assets, 23 generators, with the watertight/non-manifold columns withheld after an engine finding, and per-generator numbers posted to GitHub issues in early August later retracted), Meshy's 75-model vendor benchmark, and academic protocols (Cyc3D, Aug 2026; HY3D-Bench dataset, Feb 2026) that measure mesh/UV quality but not FDM printability.

### Cited Findings
- Topoheal census v1.0 (re-lint 2026-08-17, CC BY 4.0, run by Topoheal "the vendor of the inspection and repair tool"): 2,307 AI-generated assets from 23 generators sampled from the 3D Arena dataset; 303 assets unmeasurable; triangle meshes only. Per-generator "Failed lint" (of measurable assets) and median faces: Hunyuan3D-2.1 4 failed / 40,000 faces; SF3D 5 / 24,128; SPAR3D 9 / 29,936; TRELLIS 35 of 100 / 16,403; Meshy-5 85 of 98 / 69,170; Meshy-6 101 / 299,266; TRELLIS.2-4B 101 / 290,881; TripoSG 101 / 1,367,152; Hi3DGen 101 / 632,684; InstantMesh 101 / 74,500; Unique3D 101 / 665,808; TripoSR 97 of 97 / 60,876; Hunyuan3D-2 no lint result reported (median 40,000 faces); SAM-3D-Objects-3DGS 0 measurable; overall 1,461 of 2,004 measurable failed. Withheld columns: pass_rate, defect_not_watertight, defect_non_manifold (FINDING-7), defect_uv_missing (FINDING-10), floating debris "only as a floor" (FINDING-8), inverted/inconsistent normals [S] — [Topoheal census](https://topoheal.com/census/)
- The 3dqa-benchmark repo README: "The figures that were published in this file have been retracted... A re-lint on 2026-08-17 (FINDING-7) superseded the heal rates, and three open findings undermine the per-generator defect-rate table"; assets from 3D Arena (dataset-level MIT) [P] — [3dqa-benchmark README](https://raw.githubusercontent.com/alza123123/3dqa-benchmark/main/README.md)
- Retracted figures posted to GitHub issues on 2026-08-04 by user "topoheal": Hunyuan3D-2 "the only model to achieve a 0% defect rate across every single geometry check" (101 assets), Hunyuan3D-2.1 2.0% non-watertight [P, retracted] — [Hunyuan3D-2 issue #370](https://github.com/Tencent-Hunyuan/Hunyuan3D-2/issues/370); TRELLIS (n=100) 60.0% non-watertight, 0.0% non-manifold, 4% >30k triangles vs TRELLIS.2-4B (n=101) 91.1% non-watertight, 14.9% non-manifold, 100% >30k triangles [P, retracted] — [TRELLIS.2 issue #181](https://github.com/microsoft/TRELLIS.2/issues/181)
- Meshy 75-model benchmark (vendor): 97% Bambu Studio slice pass, 55% watertight out of export for Meshy; Printability Score Meshy 8/9, Hi3D 7/9, Tripo 5/9, Rodin 1/9; Hunyuan3D not scored [S] — [Meshy blog](https://www.meshy.ai/blog/best-ai-tools-for-3d-printing)
- Cyc3D (arXiv 2608.28080, submitted 2026-08-28): image-to-3D benchmark with "View-Cycle Structural Consistency" and Representation Quality (geometric structure, "mesh discretization and efficiency", UV parameterization); five systems tested (unnamed on the abstract page); "Closed-source feed-forward models consistently outperform open-source optimization-based baselines"; no watertight/manifold metrics named [P] — [arXiv 2608.28080](https://arxiv.org/abs/2608.28080)
- HY3D-Bench (arXiv 2602.03907, 2026-02-03, Team Hunyuan3D): a ~250k-object curated dataset "with training-ready artifacts such as watertight meshes", part-level annotations, 125k synthetic assets; validated by training Hunyuan3D-2.1-Small; not a generator comparison [P] — [arXiv 2602.03907](https://arxiv.org/abs/2602.03907)
- CelloCut (arXiv 2605.17853): watertight remeshing via tetrahedral cell cuts, with benchmarks for watertight remeshing (repair-side, not generation) [S] — [arXiv 2605.17853](https://arxiv.org/pdf/2605.17853)
- Hunyuan3D 2.0/2.1 papers report visual/user-study metrics, not physical print tests [P] — [arXiv 2501.12202](https://arxiv.org/html/2501.12202v1); [arXiv 2506.15442](https://arxiv.org/html/2506.15442v1)
- Meta SAM 3D Objects published a "3D Artist Object Set" and an HF leaderboard (2026-06-02) for reconstruction quality [P] — [README](https://raw.githubusercontent.com/facebookresearch/sam-3d-objects/main/README.md)
- 3D Arena (HF dataset, MIT) is the shared corpus of generator outputs that the census used [P] — [HF dataset](https://huggingface.co/datasets/3d-arena/3d-arena)

### Inferences
- The census's median face counts are a useful proxy for post-processing load: TRELLIS.2/Pixal3D-class outputs (~290K faces) and TripoSG (~1.37M) need decimation for slicing, whereas Hunyuan3D 2.x (40K default) and SF3D/SPAR3D (~25–30K) do not.
- Given the retraction and vendor affiliation, census numbers should be cited only as "failed lint" counts with the caveat, not as watertight percentages.

### Gaps
- No independent 2025–2026 study measuring watertightness/manifoldness/wall thickness of open image-to-3D models on a common input set was found [U].
- Cyc3D's model list and per-model geometry scores were not accessible from the abstract page [U].
- Hunyuan3D 3.x, Tripo 3.x, Rodin Gen-2.x, Pixal3D and Hi3D v1.0 are absent from the census [U].

---

## Key Question 6: Multi-view / multi-image inputs

### Takeaway
Multi-image conditioning is now common: open models Hunyuan3D-2mv (3 named views), TRELLIS (tuning-free multi-image), Pixal3D (`inference_mv.py`, Sep 2026, separate MV weights); commercial Meshy Multi-Image to 3D (main + up to 3 auxiliary views), Tripo Multiview to 3D, Rodin (1–5 images), Tencent Hunyuan 3D Pro (left/right/back, plus top/bottom/left_front/right_front in 3.1). SF3D/SPAR3D's "multiple image paths" is batching, not multi-view.

### Cited Findings
- Hunyuan3D-2mv: "Multiview Image to Shape Model" 1.1B (2025-03-18) with Fast/Turbo variants; README points to `examples` for "multiview image to 3D generation" [P] — [README](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-2/main/README.md); HF Space `tencent/Hunyuan3D-2mv` 342 likes [P] — [HF API](https://huggingface.co/api/spaces?search=hunyuan3d); fal.ai endpoint takes front/back/left URLs at $0.16 [P] — [fal](https://fal.ai/models/fal-ai/hunyuan3d/v2/multi-view)
- TRELLIS (v1): "Implementation of multi-image conditioning for TRELLIS-image model... based on tuning-free algorithm without training a specialized model, so it may not give the best results for all input images" [P] — [README](https://raw.githubusercontent.com/microsoft/TRELLIS/main/README.md)
- Pixal3D: "Sep 2026: Release multi-view inference code"; `python inference_mv.py --views_dir ... --output ./output_mv.glb`; "uses a separate set of multi-view weights (ckpts/*_mv...)"; `--num_views N`; views "are never cropped or rescaled, so the framing you provide has to be the framing the cameras describe" [P] — [README](https://raw.githubusercontent.com/TencentARC/Pixal3D/master/README.md)
- Tencent Hunyuan 3D Pro API: `MultiViewImages.N` with view names left, right, back (+ top, bottom, left_front, right_front "3.1 only"); +10 credits add-on [P] — [API doc](https://www.tencentcloud.com/document/product/1284/75540); [billing](https://www.tencentcloud.com/document/product/1284/75281)
- Meshy: "Multi-Image to 3D" task priced like Image to 3D (20/30/30/35 credits) [P] — [API pricing](https://docs.meshy.ai/api/pricing); "main view plus up to three auxiliary views" (2026-08-07) [S] — [Cinevva](https://app.cinevva.com/guides/ai-3d-model-generation-timeline-2026)
- Tripo: "Multiview to 3D" 20–50 credits (same as image) [P] — [Tripo v3.1](https://developers.tripo3d.com/en/models/v3-1); Tripo 2.5 (Jan 2025) introduced multi-image input [S] — [Cinevva](https://app.cinevva.com/guides/ai-3d-model-generation-timeline-2026)
- Rodin Gen-2.5: `images` "one to five"; Gen-1/1.5 multi-image `concat`/`fuse` modes [P] — [API spec](https://docs.hyper3d.ai/en/api-specification/rodin-gen2-5); [features](https://docs.hyper3d.ai/en/get-started/features)
- SF3D/SPAR3D: "You can also specify more than one image path separated by spaces" (batch of single-image reconstructions) [P] — [SF3D README](https://raw.githubusercontent.com/Stability-AI/stable-fast-3d/main/README.md)
- Step1X-3D: multi-view conditioning listed as an unchecked TODO; CraftsMan3D: "release multiview(4 views) conditioned model" unchecked [P] — [Step1X-3D README](https://raw.githubusercontent.com/stepfun-ai/Step1X-3D/main/README.md); [CraftsMan3D README](https://raw.githubusercontent.com/HKUST-SAIL/CraftsMan3D/main/README.md)
- Hi3D v1.0 takes one reference image plus a coarse mesh (no multi-view) [P] — [README](https://raw.githubusercontent.com/hi3d-official/Hi3Dv1.0/main/README.md)
- Hunyuan3D-Omni accepts geometric controls (point cloud, voxel, skeleton, bbox) rather than extra views [S] — [Cinevva](https://app.cinevva.com/guides/ai-3d-model-generation-timeline-2026)

### Inferences
- For a user photographing a real object, the open route with the lowest friction is Hunyuan3D-2mv (named front/back/left views, 1.1B, ~6 GB VRAM-class; hosted on fal for $0.16) or Pixal3D MV (needs CUDA/TRELLIS.2 stack); Meshy/Tripo/Rodin/Tencent cover it commercially at 20–50 credits.

### Gaps
- Pixal3D MV VRAM and view-count limits are not stated [U]; TRELLIS.2 README does not document multi-image input [U]; Hunyuan 3.1 "8-view input" claim appears only in a secondary snippet [U] — [toolnavs snippet](https://toolnavs.com/fr/article/1123-teng-xun-hy-3-d-3-1-shang-xian-quan-qiu-ping-tai-zhi-chi-8-shi-jiao-shu-ru).

---

## Key Question 7: Part-aware generation (semantically separated parts)

### Takeaway
Part-separated output is available open-source from PartCrafter (one-shot multi-part from a single image, MIT, ≥8 GB), PartPacker (NVIDIA non-commercial, ~10 GB), HoloPart (mesh + mask → completed parts, MIT) and Tencent Hunyuan3D-Part (P3-SAM segmentation + X-Part completion, light version), and commercially via Tripo `generate_parts` (+20 credits, geometry only), Tencent Cloud "3D Part Generation" (30 credits), Meshy Auto Split / Multi-Color Print and Hi3D Split to Print. All are CUDA-only or API-only; none advertises print-specific part output (connectors/tolerances) except Hi3D (secondary claim) and Meshy's AMS colour mapping.

### Cited Findings
- PartCrafter (NeurIPS 2025): "jointly generates multiple parts and objects from a single RGB image in one shot"; fully open-sourced 2025-07-13; object- and scene-level checkpoints; "A CUDA-enabled GPU with at least 8GB VRAM. You can reduce number of parts or number of tokens to save GPU memory"; fine-tunes the TripoSG DiT; MIT; 2,510 stars, last push 2026-04-16 [P] — [README](https://raw.githubusercontent.com/wgsxm/PartCrafter/main/README.md); [GitHub API](https://api.github.com/repos/wgsxm/PartCrafter); HF demo `alexnasa/PartCrafter` 122 likes [P] — [HF API](https://huggingface.co/api/spaces?search=partcrafter)
- PartPacker (NVIDIA, Jun 2025): "For inference, it takes ~10GB GPU memory (assuming float16)"; tested on 3090/4090, CUDA 12.4; multi-GPU inference option; HF card: "license_name: nvidia-non-commercial-license... This model is ready for non-commercial use" [P] — [README](https://raw.githubusercontent.com/NVlabs/PartPacker/main/README.md); [HF card](https://huggingface.co/nvidia/PartPacker/raw/main/README.md); 826 stars, last push 2025-06-26 [P] — [GitHub API](https://api.github.com/repos/NVlabs/PartPacker)
- HoloPart (VAST, Apr 2025): input is a mesh plus a per-face part mask (`mask.npy`) assembled into `input_mesh.glb`; outputs completed parts; MIT; 676 stars, last push 2025-04-11 [P] — [README](https://raw.githubusercontent.com/VAST-AI-Research/HoloPart/main/README.md); [GitHub API](https://api.github.com/repos/VAST-AI-Research/HoloPart)
- Hunyuan3D-Part: "holistic mesh is fed to part detection module P3-SAM to obtain... part segmentations and part bounding boxes. Then X-Part generate the complete parts"; "The current release is a light version of X-Part"; "P3-SAM can handle any input mesh"; papers arXiv 2509.06784 and 2509.08643; HF Space `tencent/Hunyuan3D-Part` [P] — [README](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-Part/main/README.md); license "Hunyuan 3D-Part Community License" [S] — [Cinevva](https://app.cinevva.com/guides/ai-3d-model-generation-timeline-2026)
- Tripo API: "Generate in parts: +20 credits"; `generate_parts: editable segmented parts; requires texture=false and pbr=false`; "segmentation and completion 30–50" credits as model-processing tasks [P] — [Tripo v3.1](https://developers.tripo3d.com/en/models/v3-1); [developers.tripo3d.ai](https://developers.tripo3d.ai/)
- Tencent Cloud: "3D Part Generation: 30 credits" post-processing [P] — [billing](https://www.tencentcloud.com/document/product/1284/75281)
- Meshy API: Auto Split 10 credits; Multi-Color Print 10 credits [P] — [API pricing](https://docs.meshy.ai/api/pricing); Multi-Color Print produces colour-separated 3MF, 4 colours default up to 16 [S, vendor] — [Meshy blog](https://www.meshy.ai/blog/best-ai-tools-for-3d-printing); AMS filament-zone mapping in exported 3MF [P] — [3DPI](https://3dprintingindustry.com/news/meshy-and-makerworld-team-up-to-put-ai-3d-model-generation-in-bambu-lab-users-hands-250281/)
- Hi3D (hosted): Split to Print 20 credits; "Auto Character Split with connectors"; "tolerance system adjusts assembly clearances" [S] — [Stork.ai](https://www.stork.ai/en/hi3d); [Meshy blog](https://www.meshy.ai/blog/best-ai-tools-for-3d-printing); [3Dnatives](https://www.3dnatives.com/en/ai-3d-model-generators-3d-printing-13082026/)
- Rodin Gen-2: "recursive part-based generation" [S] — [Cinevva](https://app.cinevva.com/guides/ai-3d-model-generation-timeline-2026); but the Gen-2.5 API spec exposes no parts/bbox options [P] — [API spec](https://docs.hyper3d.ai/en/api-specification/rodin-gen2-5)
- SAM 3D Objects reconstructs multiple masked objects with layout (multi-object notebook), which is object-level rather than part-level separation [P] — [README](https://raw.githubusercontent.com/facebookresearch/sam-3d-objects/main/README.md)
- HY3D-Bench dataset includes "structured part annotations" [P] — [arXiv 2602.03907](https://arxiv.org/abs/2602.03907)

### Inferences
- For multi-colour FDM, part-aware models give geometry-separated parts, but colour assignment still has to come from the texture or from a segmentation step; only Meshy (and Hi3D per secondary sources) ship that mapping to 3MF today.
- PartCrafter is the only permissive-licensed, single-image, one-shot part generator; its 8 GB VRAM need is modest but it is CUDA-only, so for the user it would run on rented GPUs or ZeroGPU.

### Gaps
- No primary documentation found on how PartCrafter/PartPacker parts behave at seams (overlaps, gaps, watertightness per part), which matters for multi-plate printing [U].
- Hunyuan3D-Part and PartCrafter VRAM for full-size inputs not stated beyond the minimums above [U].
- Whether Tripo `generate_parts` output parts are individually closed solids is not documented [U].

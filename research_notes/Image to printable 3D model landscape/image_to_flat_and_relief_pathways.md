# Deterministic image → flat / extruded / layered / relief 3D-printable geometry (state as of 2026-11-08)

Scope note: this file covers code-based (non-generative-AI, or AI-only-for-perception) pipelines from a 2D image to FDM-printable STL/3MF. Repo statistics (stars, last push, license) were pulled from the public GitHub REST API on 2026-11-08 and are marked **[GH API]**; anything from a README or official doc is **[primary]**; blog/forum/aggregator claims are **[secondary]**; **[unverified]** means I could not confirm from any source I reached. Target hardware: Apple Silicon M5, 16 GB unified memory, no NVIDIA GPU. The shared web-search budget ran out near the end of this task; remaining gaps are listed per section rather than guessed.

---

## Key question 1 — Silhouette-extrusion pipeline (image → mask → vector → polygon cleanup → solid)

### Takeaway
Every stage after the mask is fully deterministic and scriptable in Python (OpenCV `findContours`/`approxPolyDP` or potrace/vtracer → Shapely `make_valid`/`buffer`/`simplify` → `trimesh.creation.extrude_polygon` or build123d `import_svg`+`extrude`, or OpenSCAD `import()`+`linear_extrude`). The only non-deterministic step is foreground segmentation on photographs; for high-contrast art/logos an OpenCV threshold is enough and the whole pipeline is deterministic. On the M5 Mac the practical perception options are rembg's ONNX models (CPU, or CoreML EP via onnxruntime), Apple Vision's `VNGenerateForegroundInstanceMaskRequest` through PyObjC, or an MLX port of SAM 3; official SAM 3 is still CUDA/Triton-bound.

### Cited Findings

**Segmentation / background removal**
- rembg (danielgatis/rembg): 25,389 stars, last push 2026-11-06, MIT, Python. **[GH API]** — [GitHub](https://github.com/danielgatis/rembg)
- rembg latest PyPI release 2.0.87 on 2026-11-06; README requires Python >=3.11,<3.14; extras `cpu`, `gpu`, `cli`, `rocm`, `fp16`. **[primary]** — [PyPI](https://pypi.org/project/rembg/)
- rembg model list (all local ONNX, auto-downloaded to `~/.rembg/models/`): `u2net`, `u2netp`, `u2net_human_seg`, `u2net_cloth_seg`, `silueta` (~43 MB), `isnet-general-use`, `isnet-anime`, `sam` (point prompts via `sam_prompt`), `birefnet-general`, `birefnet-general-fp16`, `birefnet-general-lite`, `birefnet-portrait`, `birefnet-dis`, `birefnet-hrsod`, `birefnet-cod`, `birefnet-massive`, `bria-rmbg` (**default**, ~1.02 GB, runs at 1024×1024, slower than u2net), plus two cloud APIs (`withoutbg`, `atlascloud`). **[primary]** — [rembg README](https://github.com/danielgatis/rembg)
- rembg README: model weights carry their own licenses; "RMBG-2.0 (`bria-rmbg`) requires a paid agreement for commercial use." **[primary]** — [rembg README](https://github.com/danielgatis/rembg)
- rembg edge modes are alternatives, not layers: naive (default, best for hard edges), `-dc` decontaminate (color only), `-a` alpha matting (closed-form solver, slow, may fail to converge), `-vm` ViTMatte (network, slower). `-ppm` thresholds the mask to fully binary; `-om` returns mask only. **[primary]** — [rembg README](https://github.com/danielgatis/rembg)
- rembg README and PyPI page do **not** mention Apple Silicon, CoreML, or MPS; install docs cover CPU, CUDA, ROCm only. **[primary]** — [rembg README](https://github.com/danielgatis/rembg); [PyPI](https://pypi.org/project/rembg/)
- ONNX Runtime's CoreML Execution Provider is in the official macOS wheel; `MLProgram` format requires macOS 12+; options include `MLComputeUnits: ALL/CPUOnly/CPUAndGPU/CPUAndNeuralEngine`. **[primary]** — [onnxruntime CoreML EP docs](https://onnxruntime.ai/docs/execution-providers/CoreML-ExecutionProvider.html)
- The community `onnxruntime-silicon` wheel project (cansik, 237 stars, MIT, last push 2024-07-10) states it is no longer needed because the official wheel includes CoreML. **[GH API + secondary summary of README]** — [GitHub](https://github.com/cansik/onnxruntime-silicon)
- A third-party API mirror documents `rembg.new_session(model_name, providers=[...])` accepting an ONNX provider list (auto-detected if unspecified). **[secondary]** — [tessl.io rembg docs](https://tessl.io/registry/tessl/pypi-rembg/2.0.0/files/docs/session-management.md)
- Anecdotal Apple Silicon CoreML EP reports are mixed (one M3 user saw 766% CPU and 0% GPU with CoreML enabled; another pinned onnxruntime 1.16.3 for better results). **[secondary]** — [Deep-Live-Cam issue #357](https://github.com/hacksider/Deep-Live-Cam/issues/357)
- BiRefNet (ZhengPeng7/BiRefNet): 4,382 stars, last push 2026-10-25, MIT. **[GH API]** — [GitHub](https://github.com/ZhengPeng7/BiRefNet)
- BiRefNet variants: general (Swin-L and Swin-T "lite"), matting, portrait, HR 2048×2048, dynamic (256–2304), lite-2K (2560×1440); default inference 1024×1024 uses ~4.8 GB (FP32) / ~3.5 GB (FP16) GPU memory; official ONNX released Aug 2024; loads via `AutoModelForImageSegmentation.from_pretrained('zhengpeng7/BiRefNet', trust_remote_code=True)`; README has no CPU/Apple Silicon notes. **[primary]** — [BiRefNet README](https://github.com/ZhengPeng7/BiRefNet)
- SAM 3 (facebookresearch/sam3): 12,242 stars, last push 2026-10-23, license "SAM License" (GitHub shows NOASSERTION). **[GH API]** — [GitHub](https://github.com/facebookresearch/sam3)
- SAM License (dated 2025-11-19) is a royalty-free, non-exclusive, non-transferable license; derivatives must carry the same agreement; prohibits military/ITAR uses; does not explicitly address commercial use. **[primary]** — [LICENSE](https://raw.githubusercontent.com/facebookresearch/sam3/main/LICENSE)
- Meta released SAM 3 on 2025-11-19 (detect/segment/track from text, exemplar, visual prompts) and SAM 3.1 on 2026-03-27. **[primary]** — [Meta AI blog](https://ai.meta.com/blog/segment-anything-model-3/)
- Official SAM 3 code has a hard Triton (CUDA-only) dependency that prevents running on Apple Silicon (M4 report); a Transformers-based path reportedly works on Apple Silicon. **[primary HF discussion]** — [facebook/sam3 discussion #11](https://huggingface.co/facebook/sam3/discussions/11)
- PR #627 "Run inference on Apple Silicon (MPS) and CPU; fix SAM 3.1 start_session" opened 2026-09-25, still **open** (not merged) as of the last author comment 2026-10-25; adds CUDA→MPS→CPU device selection, lazy Triton import, disables FlashAttention 3 off CUDA. **[primary]** — [PR #627](https://github.com/facebookresearch/sam3/pull/627)
- MLX port `mlx-community/sam3-image`: text and box prompts, macOS 13+, Apple Silicon required, Python 3.13+, ~3.4 GB weights, 0.8B params, Apache-2.0, authored by Deekshith Dade. **[primary HF card]** — [HF](https://huggingface.co/mlx-community/sam3-image)
- SAM 2 (facebookresearch/sam2): 20,114 stars, Apache-2.0, last push 2026-05-30. **[GH API]** — [GitHub](https://github.com/facebookresearch/sam2)
- Apple Vision `VNGenerateForegroundInstanceMaskRequest` (macOS 14.0+) produces an instance mask of noticeable foreground objects, class-agnostic, soft mask at input resolution. **[primary Apple doc + WWDC notes]** — [Apple docs](https://developer.apple.com/tutorials/data/documentation/vision/vngenerateforegroundinstancemaskrequest.md); [WWDC23 session 10176 notes](https://wwdcnotes.com/notes/wwdc23/10176)
- `pyobjc-framework-Vision` 13.0 (released 2026-10-30, MIT, Python 3.11–3.15, universal2 wheels) wraps the Vision framework for Python; no bundled docs. **[primary]** — [PyPI](https://pypi.org/project/pyobjc-framework-Vision/)
- A deterministic alternative exists in `seehiong/printable`: a built-in flat-backdrop keyer (`key_background=true`) that needs no model download, alongside optional rembg. **[primary README]** — [GitHub](https://github.com/seehiong/printable)

**Raster → vector / contours**
- OpenCV `findContours` hierarchy is `[Next, Previous, First_Child, Parent]`; `RETR_EXTERNAL` returns only outermost contours; `RETR_CCOMP` gives a 2-level hierarchy where level-1 = outer boundaries and level-2 = holes (an object inside a hole returns to level 1); `RETR_TREE` keeps full nesting. **[primary]** — [OpenCV tutorial source](https://raw.githubusercontent.com/opencv/opencv/4.x/doc/py_tutorials/py_imgproc/py_contours/py_contours_hierarchy/py_contours_hierarchy.markdown)
- potrace (C, Peter Selinger) parameters: `-t` turdsize (suppress speckles ≤ n px), `-a` alphamax corner threshold (default 1; 0 = polygon; >4/3 suppresses all corners), `-O` opttolerance (default 0.2), `-z` turnpolicy (default minority), `-u` unit quantization (default 10 → 1/10 px), `-r` resolution (variable-size backends default 72 dpi), `-k` blacklevel, `-i` invert; backends include SVG, DXF (Béziers → circular arcs), GeoJSON, EPS, PDF; license GPL-2.0-or-later. **[primary]** — [potrace man page](https://potrace.sourceforge.net/potrace.1.html)
- pypotrace (flupke): 178 stars, last push 2024-04-15, license unasserted on GitHub; builds against system `libpotrace-dev` + `libagg-dev` (C extension). **[GH API + README]** — [GitHub](https://github.com/flupke/pypotrace); [README](https://raw.githubusercontent.com/flupke/pypotrace/master/README.rst)
- tatarize/potrace "Pure Python Port of Potrace": 171 stars, GPL-2.0, last push 2024-05-09. **[GH API]** — [GitHub](https://github.com/tatarize/potrace)
- vtracer (visioncortex): 7,485 stars, MIT, Rust, last push 2026-11-08. **[GH API]** — [GitHub](https://github.com/visioncortex/vtracer)
- vtracer modes: `--clustering color-cluster` (default, color layers), `bw` (binary, with `--threshold` or `--adaptive` Bradley–Roth), `watershed`; `--mode pixel|polygon|spline`; `--hierarchical stacked|cutout`; `--filter-speckle` 0–128 px; `--color-precision` 1–8 bits; `--gradient-step`; `--corner-threshold` (default 60), `--segment-length` (3.5–10, default 4), `--splice-threshold` (default 45); `--simplify <tol>`. Described as a "fast, linear pipeline" that skips potrace's optimal-polygon search. **[primary]** — [vtracer README](https://github.com/visioncortex/vtracer)
- vtracer PyPI 0.6.15 (2026-03-23), MIT, Python >=3.7, macOS 11 arm64 wheels for cp311–cp314; API `vtracer.convert_image_to_svg_py(inp, out, colormode="color|binary", hierarchical="stacked|cutout", mode="spline|polygon|none", filter_speckle=4, color_precision=6, layer_difference=16, corner_threshold=60, length_threshold=4.0, max_iterations=10, splice_threshold=45, path_precision=...)` plus `convert_raw_image_to_svg` and `convert_pixels_to_svg`. (Note: the GitHub README quotes `pip install vtracer==1.0.0a4` while PyPI lists 0.6.15 as latest — conflicting version strings.) **[primary, conflict noted]** — [PyPI](https://pypi.org/project/vtracer/); [README](https://github.com/visioncortex/vtracer)
- autotrace (autotrace/autotrace): 753 stars, GPL-2.0, C, last push 2026-11-06. **[GH API]** — [GitHub](https://github.com/autotrace/autotrace)
- Inkscape CLI 1.2+ is used headlessly in the Papooch cookie-cutter toolchain to produce a `-fill.svg` that OpenSCAD can consume. **[primary README]** — [GitHub](https://github.com/Papooch/cookie-cutter-generator)

**Polygon cleanup (Shapely 2.x)**
- Shapely (shapely/shapely): 4,540 stars, BSD-3-Clause, last push 2026-11-06; manual is for Shapely 2.2.0. **[GH API + primary]** — [GitHub](https://github.com/shapely/shapely); [manual](https://shapely.readthedocs.io/en/stable/manual.html)
- `shapely.make_valid(geometry, *, method='linework', keep_collapsed=True)`: `linework` (default) preserves all edges and uses an even-odd rule, can return complex results; `structure` (added 2.1.0) makes each ring valid, merges shells, subtracts holes; repairing a Polygon can return a GeometryCollection (example yields MultiLineString for a degenerate ring). **[primary]** — [make_valid reference](https://shapely.readthedocs.io/en/stable/reference/shapely.make_valid.html)
- `buffer(distance, quad_segs=16, cap_style=1, join_style=1, mitre_limit=5.0, single_sided=False)`: positive dilates, negative erodes; join_style 1 round / 2 mitre / 3 bevel; `buffer(0)` cleans self-touching/bowtie polygons (may split into MultiPolygon; results vary). **[primary]** — [manual](https://shapely.readthedocs.io/en/stable/manual.html)
- `simplify(tolerance, preserve_topology=True)`: all points within tolerance; `preserve_topology=False` uses faster Douglas–Peucker but may produce invalid geometry. `Polygon(shell, holes)` exposes `exterior`/`interiors`; valid rings may touch only at a single point. `unary_union` merges overlapping polygons and can repair some invalid MultiPolygons. `orient(polygon, sign=1.0)` → CCW exterior, CW interiors. Shapely does not validate at construction. **[primary]** — [manual](https://shapely.readthedocs.io/en/stable/manual.html)

**Extrusion to solid**
- trimesh (mikedh/trimesh): 3,719 stars, MIT, last push 2026-11-06. **[GH API]** — [GitHub](https://github.com/mikedh/trimesh)
- `trimesh.creation.extrude_polygon(polygon: shapely.Polygon, height, transform=None, mid_plane=False, **kwargs) -> Trimesh` returns a "watertight body"; kwargs go to `triangulate_polygon(polygon, triangle_args=None, engine=None, force_vertices=False)` where `engine=None|'earcut'` uses mapbox-earcut and `'triangle'` uses triangle.c; optional deps listed: `manifold3d`, `triangle`, `mapbox_earcut`. `extrude_triangulation(vertices, faces, height)` also available. **[primary]** — [trimesh.creation docs](https://trimesh.org/trimesh.creation.html)
- trimesh `export_3MF(mesh, batch_size=4096, compression=ZIP_DEFLATED, compresslevel=5)` accepts a Mesh or Scene, writes `<model unit="millimeter">`, one `<object id name=...>` per Scene geometry (names preserved), and declares the 3MF material namespace. Whether per-object colors/materials are actually written was not confirmed. **[primary source read; color writing unverified]** — [threemf.py](https://raw.githubusercontent.com/mikedh/trimesh/main/trimesh/exchange/threemf.py); [docs](https://trimesh.org/trimesh.exchange.threemf.html)
- build123d (gumyr/build123d): 3,662 stars, Apache-2.0, last push 2026-11-08. `import_svg(svg_file, *, flip_y=True, align=Align.MIN, ignore_visibility=False, label_by='id')` returns a `ShapeList` of `Wire`/`Face` (uses OCP + ocpsvg + svgpathtools); `import_dxf(dxf_file)`; `Mesher(unit=Unit.MM).add_shape(...)` with `linear_deflection`, `angular_deflection`, part numbers, labels/colors, `add_meta_data`, `write("x.3mf"|"x.stl")`; Mesher wraps lib3mf. **[GH API + primary]** — [import/export docs](https://build123d.readthedocs.io/en/latest/import_export.html); [importers source](https://build123d.readthedocs.io/en/latest/_modules/importers.html)
- CadQuery (CadQuery/cadquery): 6,079 stars, last push 2026-11-08 (license NOASSERTION on GitHub). Import formats: DXF, STEP, XCAF XML, XBF — **SVG import is not supported**; `importers.importDXF(tol=1e-06, exclude=[], include=[])`; exports STL/3MF/STEP/SVG/etc.; 3MF exporter takes only `fileName`, `tolerance=0.1`, `angularTolerance=0.1` and "parameters for color and material are absent." **[GH API + primary]** — [CadQuery import/export docs](https://cadquery.readthedocs.io/en/latest/importexport.html)
- OpenSCAD `import()` supports SVG since 2019.05; parameters `file`, `center`, `dpi`, `convexity`, `layer` (Inkscape label), `id`; `$fn/$fa/$fs`, `id`, `layer` need a development snapshot. DPI applies only when width/height lack an absolute unit (px, pt, pc, in, mm, cm); when width/height are missing the viewBox is used and `dpi` scales it; `dpi=25.4` makes 1 SVG unit = 1 mm. Not imported: text/fonts, clipping/masking; closed shapes ignore fill and stroke-width; open paths are converted to outlines using stroke-width. **[primary]** — [OpenSCAD SVG Import manual](https://en.wikibooks.org/wiki/OpenSCAD_User_Manual/SVG_Import); [Importing Geometry](https://en.wikibooks.org/wiki/OpenSCAD_User_Manual/Importing_Geometry)
- OpenSCAD releases: stable "Latest" is still 2021.01; a pre-release tag **2026.11-RC0** was published 2026-11-07. **[primary]** — [releases](https://github.com/openscad/openscad/releases); repo 10,618 stars, last push 2026-11-07 **[GH API]** — [GitHub](https://github.com/openscad/openscad)
- Bambu Studio v1.4 added SVG import ("SVG to Mesh"); users report an error "SVG does not contain a single path to be embossed" when objects/strokes are not converted to paths, fixed by Inkscape object-to-path. **[secondary release-note mirror + primary forum]** — [release note mirror](https://newreleases.io/project/github/bambulab/BambuStudio/release/v01.04.00.17); [Bambu forum](https://forum.bambulab.com/t/third-party-software-to-convert-svg-to-path-data/205891)
- Real-world failure modes when replicating Bambu's Image to Keychain offline (forum, 2024-07-26): FreeCAD SVG import produced >100,000 curves; OpenSCAD/SelfCAD imported only outlines; TinkerCAD took ~1 h per SVG; 3MF into Bambu Studio yielded "hundreds of separate paintable objects that could not be sliced, or one solid slab that could not be painted." **[primary user report]** — [Bambu forum](https://forum.bambulab.com/t/offline-method-to-recreate-the-image-to-keychain-makers-results/89827)
- Bambu forum users report the MakerLab Image to Keychain output itself frequently has non-manifold edge errors. **[primary user report]** — [Bambu forum](https://forum.bambulab.com/t/image-to-keychain-error/112729)

### Inferences
- A fully deterministic path exists for logos/line art: OpenCV threshold → `findContours(RETR_CCOMP)` (holes identified by hierarchy level) → `approxPolyDP` → Shapely `Polygon(shell, holes)` → `make_valid(method='structure')` → `buffer(0)` / negative-then-positive buffer to drop features thinner than ~nozzle width → `simplify(tol, preserve_topology=True)` → `trimesh.creation.extrude_polygon` → STL/3MF. Only photos need a perception model (rembg / Vision / SAM).
- Scale handling is the top silent-failure source: raster pixels have no physical size; SVGs from potrace default to 72 dpi, OpenSCAD assumes 96 dpi when units are absent, Inkscape ≥0.92 uses 96 px/in — pick one authoritative "target width in mm" and rescale the polygon in Shapely rather than trusting SVG units.
- Because `make_valid('linework')` can return GeometryCollections and `buffer(0)` can split into MultiPolygons, code must iterate over all Polygon parts, drop islands below a minimum area (e.g., < (2×nozzle)²), and extrude each part separately before `unary_union`/concatenation.
- CadQuery is not a drop-in for SVG; build123d (`import_svg`) or OpenSCAD `import()` are the CAD-kernel routes; trimesh is the lightest pure-mesh route and the only one of the three that needs no OCCT.
- On the M5/16 GB Mac, rembg with `u2net`/`isnet-general-use`/`birefnet-general-lite` on CPU is the lowest-friction perception path; `bria-rmbg` (default) is ~1 GB and commercially restricted; CoreML EP acceleration should be treated as experimental until measured.

### Gaps
- No primary source confirms rembg's `new_session(providers=[...])` parameter or CoreML behaviour; only a third-party mirror documents it. No rembg-on-Apple-Silicon benchmarks were found.
- Could not verify whether the Inkscape 1.x CLI exposes bitmap tracing non-interactively (only SVG→SVG/DXF conversion and `object-to-path` were seen in use).
- Could not confirm whether trimesh's 3MF exporter writes per-object color/material (grep showed the material namespace declared but not the color writer).
- pypotrace's license is unasserted on GitHub; given it links libpotrace (GPL-2.0+) treat it as GPL-encumbered until confirmed.

---

## Key question 2 — Heightmap / relief pipeline (lithophanes, depth-estimated bas-relief, heightmap-to-mesh tooling)

### Takeaway
Lithophanes are a solved, fully deterministic numpy problem (grayscale → inverted thickness map in roughly the 0.8–3 mm band → grid mesh with a base), and many small Python generators exist but almost all are low-star, personal projects. Bas-relief from learned monocular depth (Depth Anything V2/V3, Marigold, Depth Pro) is feasible on Apple Silicon (Marigold has an `--apple_silicon` MPS flag; Depth Anything V2's script falls back CUDA→MPS→CPU and Apple ships CoreML conversions of the Small model), but no paper or tool I found validates learned-depth reliefs for printing; the classical post-processing is gradient-domain depth compression (Weyrich et al. 2007) plus a base plate.

### Cited Findings

**Lithophane principles and parameters (mostly secondary)**
- Common guidance: thinnest ≈0.8 mm, thickest ≈3 mm; some sources allow 3.2–4.0 mm max for white PLA; minimums quoted range 0.4–0.8 mm; layer height ~0.1 mm (0.06–0.12 range), 0.2 mm layers cause visible banding; "too dark means too thick." **[secondary]** — [jlc3dp](https://jlc3dp.com/blog/lithophane-3d-print); [Sovol](https://www.sovol3d.com/blogs/news/how-to-3d-print-a-lithophane-a-beginners-guide-to-turning-photos-into-light-art); [Bambu forum thread](https://forum.bambulab.com/t/printing-lithophanes-flat-or-vertical/84574)
- LithophaneMaker.com (web generator): minimum thickness "depends upon the filament" and "shouldn't be less than 1.5x your nozzle's diameter"; exposes min/max thickness, frame depth/width, resolution (mm/px — smaller values give much larger STLs), width, height; outputs STL. **[primary for that tool]** — [lithophanemaker.com](https://www.lithophanemaker.com/Lithophanes.html)
- Bambu Lab publishes a CMYK color-lithophane method (stacked C/M/Y/K + white translucent filaments) with a dedicated PLA bundle. **[primary]** — [Bambu wiki](https://wiki.bambulab.com/en/knowledge-sharing/CMYK-color-lithophane-printing-instructions)

**Open-source lithophane / heightmap generators (GitHub API 2026-11-08 unless noted)**
- muldjord/lithomaker — C++, GPL-3.0, 140★, last push 2022-03-11 (older). — [GitHub](https://github.com/muldjord/lithomaker)
- s1lentCommit/stl-ready-image — Python (numpy, numpy-stl, Pillow, PySimpleGUI), MIT, 176★, last push 2026-08-08; builds a heightmap from the image and emits STL meant to be lit from the side (not backlit); exposes width/height mm and layer height (default 0.2). **[GH API + README]** — [GitHub](https://github.com/s1lentCommit/stl-ready-image)
- anoved/hmstl — C, MIT, 41★, last push 2022-07-23; grayscale heightmap → STL. — [GitHub](https://github.com/anoved/hmstl)
- colbrydi/Lithophane — Jupyter/Python, MIT, 43★, last push 2020-10-04. — [GitHub](https://github.com/colbrydi/Lithophane)
- furti/FreeCAD-Lithophane — FreeCAD workbench, MIT, 37★, last push 2021-11-05. — [GitHub](https://github.com/furti/FreeCAD-Lithophane)
- yomboprime/lithofun — JS web app, MIT, 49★, last push 2019-09-29. — [GitHub](https://github.com/yomboprime/lithofun)
- MekaElectronics/Lithophane-Generator — Python (numpy, scipy, Pillow), GPL-3.0, 1★, last push 2026-10-25; examples show 3MF output, borders, curvature. **[GH API + search summary]** — [GitHub](https://github.com/MekaElectronics/Lithophane-Generator)
- kvikindi/lithophane — MIT, 3★, last push 2021-04-16; CLI with thickness, layer height, max X/Y. — [GitHub](https://github.com/kvikindi/lithophane)
- uijincho/lithophane — Python (opencv, scikit-image, numpy-stl), MIT, 8★, last push 2025-07-21. — [GitHub](https://github.com/uijincho/lithophane)
- ibensw/lithomaker — Python, 0★, last push 2026-11-02, author describes it as "vibe coded"; bright pixels → thin. — [GitHub](https://github.com/ibensw/lithomaker)
- Adafruit "Simple Python Lithophane Generator" (caternuson) — minimal script, settings at top of file. **[secondary]** — [Adafruit Playground](https://adafruit-playground.com/u/caternuson/pages/simple-python-lithophane-generator)
- seehiong/printable — Python, MIT, 10★, last push 2026-10-03: four backends behind one CLI — `lithophane` (CPU, seconds), `heightmap` (CPU bas-relief, seconds), `triposr` and `hunyuan3d` (GPU, true 3D); rembg or a deterministic keyer for background; validates overhangs/thin walls/build volume and exits non-zero on failure; base install ~200 MB, AI models 5–30 GB each; only Apple Silicon mention is that unified memory can allocate past stated figures. **[GH API + README]** — [GitHub](https://github.com/seehiong/printable)
- Bigchx/mcp_3d_relief — Python, MIT, 24★, last push 2025-04-27: image → relief STL with `model_width` (50 mm), `model_thickness` (5 mm max height), `base_thickness` (2 mm), `skip_depth` (default true = use image directly as height), `invert_depth`, `detail_level` (1.0 → 320 px); README recommends the external Depth-Anything-V2 for a depth map. **[GH API + README]** — [GitHub](https://github.com/Bigchx/mcp_3d_relief)
- ChHarding/TouchTerrain_for_CAGEO — elevation-data → STL/OBJ terrain, 308★, last push 2026-05-26 (heightmap-to-mesh reference implementation, not image-specific). **[GH API]** — [GitHub](https://github.com/ChHarding/TouchTerrain_for_CAGEO)

**Heightmap → mesh tooling**
- OpenSCAD `surface(file, center=false, invert=false, convexity)`: text matrix (rows → Y, columns → X) or PNG where height = 0.2126R+0.7152G+0.0722B scaled to 0–100, alpha ignored; `invert` affects only images (requires 2015.03). **[primary]** — [OpenSCAD manual](https://en.wikibooks.org/wiki/OpenSCAD_User_Manual/Importing_Geometry)
- trimesh.creation has no heightmap function in its docs; heightmap meshes are built by hand (vertex grid + two triangles per cell + side walls + base) then exported. **[primary, absence noted]** — [trimesh.creation docs](https://trimesh.org/trimesh.creation.html)
- Blender's Displace modifier is the usual GUI route (subdivided plane + image texture); I could not reach the Blender manual (HTTP 403). **[unverified]**

**Monocular depth models (Apple Silicon relevance)**
- Depth Anything V2 (DepthAnything/Depth-Anything-V2): 9,114★, Apache-2.0 repo, last push 2026-03-24. Variants: Small 24.8M params (Apache-2.0), Base 97.5M, Large 335.3M, Giant 1.3B "coming soon" — Base/Large/Giant are CC-BY-NC-4.0. Usage snippet picks CUDA → MPS → CPU. Apple published Core ML conversions (`apple/coreml-depth-anything-v2-small`, added 2024-06-25). Metric-depth fine-tunes released 2024-06-22. **[GH API + primary README]** — [GitHub](https://github.com/DepthAnything/Depth-Anything-V2); [Apple CoreML model](https://huggingface.co/apple/coreml-depth-anything-v2-small)
- Depth Anything 3 (ByteDance-Seed/Depth-Anything-3): 6,657★, Apache-2.0 repo, last push 2026-07-27; released Nov 2025; "any-view" single transformer for joint depth + pose; some checkpoints CC BY-NC 4.0; PyPI `depth-anything-3`. No Mac/MPS information found. **[GH API + primary arXiv/PyPI; Mac = gap]** — [GitHub](https://github.com/ByteDance-Seed/Depth-Anything-3); [arXiv 2511.10647](https://arxiv.org/abs/2511.10647); [PyPI](https://pypi.org/project/depth-anything-3/)
- Marigold (prs-eth/Marigold): 3,249★, code Apache-2.0, weights RAIL++-M, last push 2026-09-06; diffusion (Stable Diffusion v2 fine-tune); `--apple_silicon` flag enables MPS; `--fp16` lowers VRAM; in diffusers core since v0.28.0 (2024-05-27); checkpoints: depth v1-0 (CVPR 2024, 50 steps × ensemble 10), LCM (2024-03-23), depth v1-1 (2025-05-15, 1 step × ensemble 10 for paper settings; ensemble 1 fine in practice). **[GH API + primary README]** — [GitHub](https://github.com/prs-eth/Marigold)
- Depth Pro (apple/ml-depth-pro → redirects to apple-aiml-research/ml-depth-pro): 5,780★, last push 2026-09-11; zero-shot metric depth + focal length; "2.25-megapixel depth map in 0.3 seconds on a standard GPU"; license is Apple's custom sample-code-style license (HF tag `apple-amlr`); README does not state MPS support or checkpoint size. **[GH API + primary]** — [GitHub](https://github.com/apple/ml-depth-pro); [HF](https://huggingface.co/apple/DepthPro); [LICENSE](https://raw.githubusercontent.com/apple/ml-depth-pro/main/LICENSE)

**Relief post-processing literature**
- Weyrich, Deng, Barnes, Rusinkiewicz, Finkelstein, "Digital Bas-Relief from 3D Scenes," ACM TOG 26(3), SIGGRAPH 2007: depth image → gradients → nonlinear compression of gradient magnitudes (direction preserved), discontinuities removed to collapse silhouettes → Poisson reconstruction; analogous to Fattal 2002 HDR tone mapping. Cignoni et al. earlier compressed the height field directly. **[primary]** — [paper PDF](https://gfx.cs.princeton.edu/pubs/Weyrich_2007_DBF/relief.pdf); [project page](https://reality.cs.ucl.ac.uk/projects/relief/relief.html)
- "Bas-relief modeling from RGB monocular images with regional division characteristics" (Scientific Reports 2022) segments regions, uses shape-from-shading, lets the user reorder depth, then triangulates for 3D printing. **[primary]** — [Nature](https://www.nature.com/articles/s41598-022-24974-0)
- Bambu Lab's Relief Sculpture Maker beta (forum post 2025-02-17) is "an AI-powered tool that transforms any image into a high-quality 3D printable relief model"; user feedback: dog-photo result "not perfect but really close"; another suggested printing vertically. **[primary forum]** — [Bambu forum](https://forum.bambulab.com/t/turn-images-into-3d-reliefs-join-the-relief-sculpture-maker-beta/146526)

### Inferences
- Lithophane generation is pure numpy: `thickness = t_min + (1 − gray/255) × (t_max − t_min)`, resampled to the chosen mm/px, with a rectangular base/frame; the only printability constraints are t_min ≥ ~1.5× nozzle (≈0.6 mm for 0.4 mm nozzles, 0.8 mm being the common conservative default), t_max ≈ 3 mm for white PLA, and ≤0.1 mm layers if printed vertically.
- For bas-relief from estimated depth on the M5: Depth Anything V2 Small (Apache-2.0, 24.8M params, Apple CoreML available) is the only permissively licensed and clearly Mac-friendly option; Marigold works on MPS but is diffusion-slow and weights are RAIL-licensed; Depth Pro's license is Apple-custom. Relative (affine-invariant) depth is sufficient because relief depth is remapped to a few millimetres anyway.
- Depth → relief needs: (1) foreground mask (reuse the KQ1 mask) so background sits on the base, (2) depth normalization + optional gradient-domain compression per Weyrich, (3) edge-preserving smoothing (bilateral/guided) to kill depth noise that becomes stair-step artefacts at 0.1 mm layers, (4) quantization-aware scaling so the relief spans several full layer heights, (5) a solid base plate ≥1 mm.
- No open-source project found that implements the full learned-depth → compressed relief → validated STL chain; `Bigchx/mcp_3d_relief` and `seehiong/printable` are the closest skeletons.

### Gaps
- No paper or benchmark found that evaluates modern learned monocular depth as a source for printed bas-relief (search budget exhausted before a targeted follow-up).
- Depth Anything 3 Apple Silicon/MPS support: not found in any source.
- Depth Pro checkpoint size and MPS behaviour: not stated on repo or HF page.
- Blender Displace modifier parameters: manual blocked (403).
- No primary (manufacturer/lab-tested) source for lithophane thickness ranges; all numbers are vendor/hobbyist guides.

---

## Key question 3 — Color-by-layer "filament painting" (HueForge and open alternatives)

### Takeaway
HueForge (Horn & Rhode LLC, closed-source, paid; Personal tier listed at $24 one-time on the official shop; macOS 12+ incl. Apple Silicon) maps image brightness/color to stacked layer heights and uses per-filament Transmission Distance (TD) to predict the blended color; it exports STL + a `Describe.txt` of swap heights (3MF only via a third-party plugin). Open-source re-implementations now exist and are active: Lumina Layers (1,190★, AGPL-3.0, Python, calibration-LUT approach, 3MF output), Kromacut (317★, AGPL-3.0, TypeScript), AutoForge (262★, CC BY-NC-SA 4.0, PyTorch optimizer with MPS support, outputs STL + swap txt + HueForge project), plus `td-free` for measuring TD. Filament painting differs from true multi-material in that all color comes from per-layer swaps (pause/M600 or AMS) through translucent layers, not side-by-side bodies.

### Cited Findings

**HueForge**
- HueForge converts a 2D image to a 3D-printable model mapping brightness (or color, depending on mode) to height; modes: Standard & Combo (brightness), Color Aware, Color Pop, Color Match; it does not auto-assign colors; it is not a slicer. **[primary]** — [About HueForge](https://shop.thehueforge.com/pages/about-hueforge)
- Transmission Distance "measures how much light passes through a filament at a given thickness"; HueForge ships a database of hundreds of measured filaments; users can measure with the free "Seashell Test" print or a TD1 device; values vary between batches. **[primary]** — [About HueForge](https://shop.thehueforge.com/pages/about-hueforge)
- Platforms: Windows 10/11, macOS 12+ (Intel and Apple Silicon), Linux. Output: STL + `Describe.txt` with layer-swap instructions entered manually in the slicer; "HueForge doesn't export 3MF files" — a "3MF Export Plugin by Additive Atom" exists. Latest release cited: v0.9.4.4 for all OSes. Plugins: FlatForge (flat/face-down/double-sided), Color Drop, HugeForge (tiling). **[primary]** — [About HueForge](https://shop.thehueforge.com/pages/about-hueforge); [Shop FAQ](https://shop.thehueforge.com/pages/faq)
- License tiers: Personal Use, Limited Commercial (annual re-enrollment), Professional, Lifetime Professional; beta builds commercial-tiers only; all licenses include two years of updates, then optional maintenance fee; "Household License" install scope. **[primary]** — [FAQ](https://shop.thehueforge.com/pages/faq); [License terms](https://shop.thehueforge.com/pages/license-terms)
- Pricing: official shop snippet shows Personal at "$24.00 USD" (regular $30); Limited Commercial described as annual, reverting to Personal if not renewed. **[primary snippet via search; product page itself returned HTTP 429 twice]** — [Shop product](https://shop.thehueforge.com/products/hueforge). Third-party figures: Limited Commercial ~$75/yr, Professional ~$150/yr or ~$500 lifetime; older dev post says $100/yr continuing rate. **[secondary / possibly stale]** — [huepick](https://huepick.app/articles/hueforge-basics/is-hueforge-free); [HueForge devlog](https://devlog.thehueforge.com/p/quick-poll-on-pricing-and-plans)
- Community descriptions: TD defined as "the amount (in mm) of material required to significantly dim the light to a point where more thickness will not notably stop more light"; typical prints use 0.08 mm layers (some 0.04 mm), 100% infill, no supports; swap instructions look like "At layer #23 (1.92mm) swap to Blue." **[secondary]** — [Snapmaker blog](https://www.snapmaker.com/blog/hueforge-3d-printing/); [huepick basics](https://huepick.app/articles/hueforge-basics/how-to-use-hueforge); [MakerWorld model note](https://makerworld.com/en/models/252137)
- Slicer side: PrusaSlicer's "Color change" at a layer inserts M600; "The printer automatically pauses the print as soon as it reads the color change in the G-code (M600 command)"; does not work with sequential printing; use same material type for all colors. **[primary]** — [Prusa Knowledge Base](https://help.prusa3d.com/article/color-change_1687)

**Open-source alternatives (GitHub API 2026-11-08)**
- lumina-layer-studio/Lumina-Layers — Python (FastAPI) + React/TS + Electron; AGPL-3.0-only; 1,190★; last push 2026-11-08; "Full-color flat FDM printing with calibrated filament layer mixing"; calibration via photographed calibration board → LUT (.npy/.json/.npz/.msgpack) or gradient cards → material profiles; 2/4/6/8-material presets; inputs photos, illustrations, pixel art, SVG; output 3MF or multi-plate ZIP (no STL mentioned); supported platforms Windows x64, Linux x86-64, **macOS Apple Silicon (macOS 14+)**; Python 3.12–3.14; free for individuals/businesses, attribution required for public files, closed-source integration needs commercial arrangement; credits HueForge, AutoForge, ChromaStack, LD_ColorLayering, ChromaPrint3D. **[GH API + primary README]** — [GitHub](https://github.com/lumina-layer-studio/Lumina-Layers)
- vycdev/Kromacut — TypeScript (React/Vite/Three.js/Tauri), AGPL-3.0; 317★; last push 2026-11-07; browser + desktop (Win/mac/Linux); color reduction, dithering removal, "physics-based" auto-paint using "Hiding Distance" (its TD analogue), manual layer control, exports STL and "color-aware" 3MF plus swap instructions; README does not state client- vs server-side processing. **[GH API + primary README]** — [GitHub](https://github.com/vycdev/Kromacut). A SUNLU review claims images are processed on its server and that it lacks automatic TD handling. **[secondary]** — [SUNLU](https://www.sunlu.com/community/posts/930/kromacut-is-a-powerful-100-free-and-open-source-browser-first-alternative-to-hueforge)
- hvoss-tech/AutoForge (redirect from hvoss-techfak) — Python/PyTorch, **CC BY-NC-SA 4.0** (prints you create are MIT); 262★; last push 2026-11-03; `pip install -U autoforge`; Gumbel-softmax learned optimization of per-pixel height + per-layer material; input image + HueForge filament CSV/JSON (brand, name, hex, TD); outputs `final_model.stl`, `project_file.hfp` (HueForge project), `swap_instructions.txt`, `final_model.png`; FlatForge mode emits one STL per color + clear/background/cap STLs; defaults `--layer_height 0.04`, `--background_height 0.24`, `--max_layers 75`, `--iterations 2000`, `--nozzle_diameter 0.4`; device auto-select CUDA → ROCm → **Apple MPS** → CPU; Triton optional; HF Space web UI. **[GH API + primary README]** — [GitHub](https://github.com/hvoss-techfak/AutoForge); [PyPI](https://pypi.org/project/AutoForge/)
- LucasKendi/hueforge-at-home — JS/p5.js color-mixing demo, MIT, 90★, last push 2026-08-02. **[GH API]** — [GitHub](https://github.com/LucasKendi/hueforge-at-home)
- mawoka-myblock/td-free — EUPL-1.2, 60★, last push 2026-10-19; hardware/software to measure filament TD. **[GH API]** — [GitHub](https://github.com/mawoka-myblock/td-free)
- Smaller/experimental: eddieoz/BananaForge (Python, MIT, 13★, 2025-07-23), S1N4X/SmithForge (combines a HueForge 3MF onto a base model, GPL-3.0, 9★), LuckyStrix/stackforge (per-pixel stacks for 4-toolhead printers, MIT, 3★, 2026-10-26), Akoozie/layertone (Bambu Studio swap planning, MIT, 2★, 2026-10-30), everyday3d/tailwag (optical-model relief prints, MIT, 2★, 2026-10-24), RonenGru/LumaLayer (HTML, 14★, 2026-06-15). **[GH API]** — [GitHub topic: hueforge](https://github.com/topics/hueforge)
- "Filament Painter" (painter.vec4.ca) is promoted as a free/open alternative; its repository was not located. **[secondary / unverified]** — [YouTube listing](https://www.youtube.com/watch?v=DBM5WOLuUQk)

### Inferences
- The deterministic core of filament painting is small: choose N filaments in back-to-front order, each with TD; for each pixel pick a stack height such that the simulated transmitted color (per-layer attenuation by thickness/TD) best matches the target; then the geometry is just a heightmap mesh (as in KQ2) and the color plan is a list of (layer index → filament) swaps. HueForge's value is the measured-TD database and interactive tuning, not an exotic algorithm.
- Of the open options, only Lumina Layers and AutoForge are Python; AutoForge's CC BY-NC-SA license blocks commercial embedding, and Lumina's AGPL requires source disclosure for networked use — both matter for a repository aiming to ship a tool.
- Output format strategy: STL + textual swap list is universally slicer-portable (user adds color changes / M600 manually); a Bambu/Orca-style 3MF with per-layer filament changes is more convenient but less standardized (see KQ4 on Bambu's 3MF metadata).

### Gaps
- Could not load the official HueForge product page (HTTP 429) to confirm Limited Commercial / Professional / Lifetime prices from the primary source.
- Kromacut's processing location (client vs server) conflicts between README (silent) and a vendor review (server-side).
- No source gives HueForge's internal TD-to-color mixing formula; AutoForge's README describes its optimizer but not an explicit TD attenuation equation.

---

## Key question 4 — Multi-color flat prints from an image for AMS/MMU (quantize → per-color regions → per-color bodies → multi-body 3MF)

### Takeaway
The chain is deterministic end to end: palette quantization (k-means/median-cut, or nearest-filament matching against the user's AMS colors), per-color masks → contours/polygons (KQ1 tooling, including hole hierarchy), optional morphological opening to remove sub-nozzle slivers, per-color extrusion to the same height, and a multi-object 3MF with each object assigned an extruder index. The slicer-specific part is the 3MF metadata: Bambu Studio/OrcaSlicer read per-object/per-part `extruder` from `Metadata/model_settings.config` (which `orca123d`, MIT, writes from Python), and Bambu Studio 2.5 also imports standard 3MF color info (as produced by OpenSCAD dev snapshots). Open-source image→multi-color-3MF tools exist but are tiny (≤45★).

### Cited Findings
- Bambu/Orca 3MF: per-object and per-part settings including `extruder` live in `Metadata/model_settings.config`; `orca123d` (PyPI 0.1.2, 2026-07-27, MIT, Python ≥3.13, built on build123d) "writes model-only projects: geometry and per-object/per-part settings in `Metadata/model_settings.config`, with no `project_settings.config`," e.g. `tag.add_part(..., name="Body", extruder=1)` / `extruder=2`, and OrcaSlicer applies the user's active printer/filament presets. **[primary]** — [PyPI JSON](https://pypi.org/pypi/orca123d/json); [GitHub](https://github.com/jsmnbom/orca123d)
- Third-party notes: Bambu Studio reportedly rejects a 3MF lacking `model_settings.config`; `extruder` is 1-indexed and maps to AMS slots; object IDs must be unique; plate `model_instance` entries reference objects by ID; per-filament arrays live in `project_settings.config` and may be ignored unless listed in `different_settings_to_system`. **[secondary]** — [gist (queso)](https://gist.github.com/queso/b5a33103e13b0d2b35e5fbdc2101bf8f); [Kiln MCP tool doc](https://glama.ai/mcp/servers/codeofaxel/kiln/tools/compose_multicolor_3mf)
- Bambu Studio 2.5.0 release notes: added support for importing standard 3MF files with color information. **[secondary release-note mirror]** — [newreleases.io](https://newreleases.io/project/github/bambulab/BambuStudio/release/v02.05.00.65)
- OpenSCAD added color export via 3MF with the Manifold backend (Jan 2025 report); users on snapshot 2025.12.21 report colors retained when exporting to disk and importing into Bambu Studio, but lost when using OpenSCAD's direct "export to Bambu Studio"; an OpenSCAD list contributor says Bambu's color storage may violate the 3MF spec. **[secondary + primary forum/list]** — [Fabbaloo](https://www.fabbaloo.com/news/openscad-embraces-multicolor-3d-design-with-new-geometry-engine); [Bambu forum](https://forum.bambulab.com/t/export-multicolor-design-from-openscad/232511); [OpenSCAD list](https://lists.openscad.org/empathy/thread/XNI57CXWXZKRYCZNASC4RR2SMTRQ2UKZ)
- OpenSCAD's only stable release is 2021.01; 2026.11-RC0 pre-release published 2026-11-07, so color-3MF export is snapshot/RC territory as of today. **[primary]** — [releases](https://github.com/openscad/openscad/releases)
- lib3mf (3MF Consortium reference library) Python package 2.5.0 released 2026-02-23. **[primary]** — [PyPI JSON](https://pypi.org/pypi/lib3mf/json)
- build123d's `Mesher` wraps lib3mf and can write multiple shapes with labels/colors and metadata to one 3MF. **[primary]** — [build123d docs](https://build123d.readthedocs.io/en/latest/import_export.html)
- CadQuery's 3MF exporter has no color/material parameters. **[primary]** — [CadQuery docs](https://cadquery.readthedocs.io/en/latest/importexport.html)
- A Blender 3MF add-on notes OrcaSlicer ignores `<basematerials>` for multi-color display, using per-triangle paint attributes instead; filament colors live in slicer settings. **[secondary]** — [Blender extension page](https://extensions.blender.org/add-ons/threemf-io/)

**Open-source image → multi-color tools (GitHub API 2026-11-08)**
- goblinhanyikan/PNGtoSVG-Multicolor-Printing — HTML, MIT, 45★, last push 2026-07-03: PNG → SVG → separate STL per color. — [GitHub](https://github.com/goblinhanyikan/PNGtoSVG-Multicolor-Printing)
- Pavelruh/ImageToSTLConverter — Processing, 9★, last push 2024-05-07: raster → one STL per color for single-layer multicolor; may produce large unoptimized STLs. — [GitHub](https://github.com/Pavelruh/ImageToSTLConverter)
- dterracino/pixel_to_3mf — Python, no license, 1★, last push 2026-10-15: pixel art → 3MF with AMS unit/slot mapping (1–4 AMS units). — [GitHub](https://github.com/dterracino/pixel_to_3mf)
- Aurxs/pixel3mf — Python, no license, 1★, last push 2026-11-08; depends on a separately deployed Lumina backend. — [GitHub](https://github.com/Aurxs/pixel3mf)
- strepto42/ImageTo3MF (Python, 0★, 2026-04-07), galiminus/ams_print (Python, 0★, 2026-04-13), mdsloan2000/ImageToSlicerMesh (Python, 0★, 2026-05-27), emreihlamur/image-to-stl (FastAPI, Bambu P2S 3MF, 0★, 2026-10-29), SkyTheCodeMaster/image-extruder (PNG→SVG→extrude→3MF, 0★, 2025-10-05), rosenbjerg/img-to-3mf (Shell, MIT, 1★, 2023-02-17). — [GitHub search "image to 3mf"](https://github.com/search?q=image+to+3mf)
- everything3d/figurine-colorize — MIT, 5★, 2026-10-25: "one figurine image to a multi-colour, slicer-ready 3MF" (agent skill). — [GitHub](https://github.com/everything3d/figurine-colorize)
- Hosted/closed: Layerpaint.app (browser STL painter → standard 3MF for AMS/MMU3; license unknown), MakerTools3D image→3MF, SculptChat SVG→3MF. **[secondary]** — [layerpaint.app](https://layerpaint.app/); [makertools3d](https://makertools3d.com/image-to-3mf)
- Bambu Image to Keychain is described by a MakerWorld creator as matching "vectorized colors to the filaments you have loaded"; a creator advises against fine lettering with a 0.4 mm nozzle unless scaled ≥150%. **[secondary creator notes]** — [MakerWorld model 2960292](https://makerworld.com/en/models/2960292-customizable-pin)
- vtracer `--hierarchical cutout` produces a seam-free mosaic of non-overlapping color regions (vs default `stacked`). **[primary]** — [vtracer README](https://github.com/visioncortex/vtracer)

### Inferences
- Two valid geometric strategies, both deterministic: (a) *cutout* — each color is its own flat body on a common base, regions are mutually exclusive (use vtracer `cutout` or per-mask contours); (b) *stacked* — colors are overlapping stacked slabs ordered by area (vtracer `stacked`), which prints well only if upper slabs are fully supported by lower ones. Cutout bodies plus a single full-footprint base plate in the dominant color is the safest for AMS/MMU.
- Minimum region rule of thumb for printability: after quantization, apply a morphological opening with a kernel ≈ nozzle diameter in pixels (at the target mm/px) or Shapely `buffer(-w/2).buffer(+w/2)` with w ≈ 0.4–0.5 mm; drop any polygon whose area < ~(2×nozzle)². Thin outlines (comic-style black lines) should be at least 2 extrusion widths (~0.8–0.9 mm) to survive slicing.
- Palette matching to the user's filaments is just nearest-neighbor in a perceptual space (CIELAB ΔE) against the loaded AMS hex values; k-means on the image first, then snap centroids to filament colors.
- For 3MF, the lowest-dependency route is writing the standard 3MF (one `<object>` per color, `unit="millimeter"`) and adding Bambu/Orca `model_settings.config` with `extruder` per object, as `orca123d` demonstrates; relying on standard `<basematerials>` alone is fragile in Orca/Bambu.

### Gaps
- No primary Bambu Lab specification for `model_settings.config` keys was reached; details come from `orca123d` and community reverse-engineering.
- Could not confirm whether Bambu Studio honors per-object `extruder` from a model-only 3MF the same way OrcaSlicer does (orca123d targets OrcaSlicer).
- No open-source tool found that combines quantization, nozzle-aware region cleanup, and AMS-slot-mapped 3MF in a maintained package (all candidates ≤45★, mostly 0–1★).

---

## Key question 5 — Bambu Lab MakerLab tools

### Takeaway
MakerLab (launched 2024-03-07 with Make My Sign, Make My Vase, Pixel Puzzle Maker, and two "Experiments": 3D-to-Relief Sculpture and AI Scanner) has since grown to include Image to Keychain (out of beta June 2024), Make My Lithophane, Relief Sculpture Maker (image input, "AI-powered," beta Feb 2025), Lightbox Maker, Lithophane Folding Fan, Keycap Legend Generator, Laser Box Maker, Parametric Model Maker, and AI generators (PrintMon Maker, Make My Statue, Image to 3D, PrintU). Primary MakerWorld/wiki pages blocked automated access (HTTP 403/402), so per-tool export details are from Bambu's blog/forum and 2026 third-party write-ups: exports vary by tool, 3MF is recommended for multicolor, STL for mesh editing, and at least one user downloaded an STL from Image to Keychain.

### Cited Findings
- Launch post (2024-03-07): Make My Sign (nameplates etc.), Make My Vase, Pixel Puzzle Maker (pixel wall art), 3D to Relief Sculpture (Experiment; imports .stl/.obj, frames from a chosen perspective), AI Scanner (Experiment; video orbit → model, ~30 min). **[primary]** — [Bambu Lab blog](https://blog.bambulab.com/new-launch-of-makerlab-experiments)
- Image to Keychain officially released (out of beta) per Bambu Lab's post of June 2024; can hand off to Make My Sign for text/shapes. **[primary]** — [Bambu Lab on X](https://x.com/BambulabGlobal/status/1800849058019569698)
- MakerLab hub listing names Image to Keychain, Make My Sign, Make My Lithophane, Lightbox Maker, Lithophane Folding Fan, Keycap Legend Generator, Laser Box Maker, among others (page itself returned 403 to automated fetch; names from search snippet). **[primary page, partially seen]** — [MakerLab](https://makerworld.com/en/makerlab)
- Relief Sculpture Maker beta (2025-02-17): "an AI-powered tool that transforms any image into a high-quality 3D printable relief model"; later moved from "experimental" to official. **[primary forum + secondary]** — [Bambu forum](https://forum.bambulab.com/t/turn-images-into-3d-reliefs-join-the-relief-sculpture-maker-beta/146526); [All3DP](https://all3dp.com/4/bambu-lab-reliefs-are-better-now-no-longer-experimental-feature/)
- Make My Lithophane is Bambu's official lithophane tool, monochrome or color, optimized for Bambu CMYK filaments. **[secondary]** — [All3DP tutorial](https://all3dp.com/2/colorful-bambu-lab-lithophane-tutorial/)
- Pixel Puzzle Maker converts an uploaded image into pixel art with cube pieces at 8 mm or 4 mm. **[secondary]** — [3printr](https://www.3printr.com/how-to-create-a-3d-printed-pixel-puzzle-from-any-image-2869635/)
- Make My Vase output downloadable free as STL or 3MF, opens in Bambu Studio/Cura/PrusaSlicer. **[secondary]** — [3printr](https://www.3printr.com/how-to-create-3d-print-models-of-vases-with-a-free-web-tool-5469638/)
- PrintMon Maker: AI tool turning a text prompt or image into a full-color character. **[secondary]** — [Notebookcheck](https://www.notebookcheck.net/Bambu-Lab-s-PrintMon-Maker-creates-cute-3D-printable-characters-from-text-and-image-prompts.906452.0.html)
- 2026-08-02 third-party guide (reflecting MakerWorld pages on that date): Image to Keychain takes a high-contrast logo/icon and exposes width, height, thickness, borders, holes, colors; Make My Sign takes text/graphics/plate dimensions, multicolor 3MF recommended; Make My Vase result "not automatically watertight"; Make My Lithophane exposes thickness; Pixel Puzzle exposes resolution; AI tools (Make My Statue, Image to 3D, PrintU) may consume "MakerLab Credits"; "export options differ by tool"; 3MF recommended for multicolor, STL for mesh editing. **[secondary]** — [33d.ch](https://33d.ch/en/blog/makerlab)
- A forum user "used the MakerLab image keychain generator, downloaded an STL, edited it in Onshape" (2024-09-18). **[primary user report]** — [Bambu forum](https://forum.bambulab.com/t/offline-method-to-recreate-the-image-to-keychain-makers-results/89827)
- Users report frequent non-manifold edge errors in Image to Keychain output. **[primary user report]** — [Bambu forum](https://forum.bambulab.com/t/image-to-keychain-error/112729)
- Bambu's CMYK lithophane method and filament bundle. **[primary]** — [Bambu wiki](https://wiki.bambulab.com/en/knowledge-sharing/CMYK-color-lithophane-printing-instructions)

**Open-source equivalents (mapping)**
- Image to Keychain ≈ KQ1 silhouette pipeline + KQ4 color quantization + a loop/hole primitive (no single maintained OSS package found; nearest: goblinhanyikan/PNGtoSVG-Multicolor-Printing, Lumina Layers' SVG/pixel modes). **[GH API]**
- Make My Lithophane ≈ KQ2 lithophane generators (lithomaker, stl-ready-image, etc.); color lithophane ≈ Lumina Layers / HueForge backlit mode. **[primary/GH API]**
- Pixel Puzzle ≈ dterracino/pixel_to_3mf, Aurxs/pixel3mf (tiny). **[GH API]**
- Relief Sculpture Maker (image) ≈ depth model + heightmap mesh (KQ2); no maintained OSS equivalent found.
- Make My Sign ≈ OpenSCAD `text()` + `linear_extrude` / build123d text; many MakerWorld OpenSCAD customizers exist (e.g., text keychain with SVG logo import). **[secondary]** — [MakerWorld 2731866](https://makerworld.com/en/models/2731866)

### Inferences
- MakerLab tools are web-only, require a MakerWorld login, and the AI tools are credit-metered; the deterministic ones (Keychain, Sign, Lithophane, Pixel Puzzle, Vase) are all reproducible with the open tooling in KQ1–KQ4, which is exactly the repository's goal.
- The non-manifold complaints about Image to Keychain suggest Bambu extrudes traced SVG paths without a robust polygon-validity pass — a place where a Shapely `make_valid` + `unary_union` stage gives a code-based pipeline an edge.

### Gaps
- Could not fetch makerworld.com/en/makerlab (403) or wiki.bambulab.com MakerLab pages (402/404), so per-tool export formats (3MF vs STL vs print-only), color limits, and parameter ranges are not verified from Bambu's own pages.
- No official statement found on whether Image to Keychain 3MF downloads include per-object extruder assignments.

---

## Key question 6 — Survey of open-source "image to STL / photo to 3D print" repos

### Takeaway
The space is fragmented: a few mid-size general tools (TouchTerrain 308★ for elevation data, stl-ready-image 176★, bekuto3d 373★ and rcalme/svg-to-stl 115★ for SVG→STL, lithomaker 140★) and a long tail of 0–30★ personal scripts, many stale since 2013–2022. The only large, actively maintained image→print projects are the filament-painting tools (Lumina Layers 1,190★, Kromacut 317★, AutoForge 262★). Several 2025–2026 repos are agent-skill or MCP wrappers rather than libraries.

### Cited Findings (all **[GH API 2026-11-08]**: name — language, license, stars, last push, note)
- jscad/OpenJSCAD.org — JS, MIT, 3,270★, 2026-11-07; parametric CAD incl. SVG deserializer and STL/3MF export (general tool, not image-specific). — [GitHub](https://github.com/jscad/OpenJSCAD.org)
- LittleSound/bekuto3d — TS, MIT, 373★, 2026-10-20; SVG → STL/OBJ/GLTF. — [GitHub](https://github.com/LittleSound/bekuto3d)
- ChHarding/TouchTerrain_for_CAGEO — Python, 308★, 2026-05-26; elevation → STL/OBJ. — [GitHub](https://github.com/ChHarding/TouchTerrain_for_CAGEO)
- s1lentCommit/stl-ready-image — Python, MIT, 176★, 2026-08-08; image heightmap → side-lit STL. — [GitHub](https://github.com/s1lentCommit/stl-ready-image)
- rcalme/svg-to-stl — JS/CSS, MIT, 115★, 2026-04-18; browser SVG path → STL. — [GitHub](https://github.com/rcalme/svg-to-stl)
- muldjord/lithomaker — C++, GPL-3.0, 140★, 2022-03-11 (older). — [GitHub](https://github.com/muldjord/lithomaker)
- GillesBouissac/agentscad — OpenSCAD, 126★, 2026-10-31; OpenSCAD utilities (lithophane-related per search). — [GitHub](https://github.com/GillesBouissac/agentscad)
- yomboprime/lithofun — JS, MIT, 49★, 2019-09-29. — [GitHub](https://github.com/yomboprime/lithofun)
- goblinhanyikan/PNGtoSVG-Multicolor-Printing — HTML, MIT, 45★, 2026-07-03. — [GitHub](https://github.com/goblinhanyikan/PNGtoSVG-Multicolor-Printing)
- colbrydi/Lithophane — Jupyter, MIT, 43★, 2020-10-04. — [GitHub](https://github.com/colbrydi/Lithophane)
- anoved/hmstl — C, MIT, 41★, 2022-07-23. — [GitHub](https://github.com/anoved/hmstl)
- Spiritdude/SVG2SCAD — OpenSCAD, 39★, 2019-02-23. — [GitHub](https://github.com/Spiritdude/SVG2SCAD)
- furti/FreeCAD-Lithophane — Python, MIT, 37★, 2021-11-05. — [GitHub](https://github.com/furti/FreeCAD-Lithophane)
- Lucandia/Flexifier — Python/Streamlit, AGPL-3.0 (README says GPL-3.0 code / CC BY-NC-SA models), 38★, 2025-02-07; image → flexi via potrace + OpenSCAD. — [GitHub](https://github.com/Lucandia/Flexifier)
- rmrao/img2stl — Python, 30★, 2015-11-25 (stale). — [GitHub](https://github.com/rmrao/img2stl)
- sysmaya/Grayscale-Image-to-STL — HTML, MIT, 29★, 2025-11-21; browser grayscale → STL. — [GitHub](https://github.com/sysmaya/Grayscale-Image-to-STL)
- wubbahed/lithophane — Node.js, MIT, 25★, 2015-01-03 (stale). — [GitHub](https://github.com/wubbahed/lithophane)
- Bigchx/mcp_3d_relief — Python, MIT, 24★, 2025-04-27; MCP server, image → relief STL. — [GitHub](https://github.com/Bigchx/mcp_3d_relief)
- arpruss/inflatemesh — Python, 14★, 2020-11-16; "inflate" 2D SVG to 3D STL/OpenSCAD. — [GitHub](https://github.com/arpruss/inflatemesh)
- waddyano/ImageTo3d — C#, MIT, 15★, 2018-05-27; CLI lithophane. — [GitHub](https://github.com/waddyano/ImageTo3d)
- seehiong/printable — Python, MIT, 10★, 2026-10-03; photo → STL, 4 backends, printability validator. — [GitHub](https://github.com/seehiong/printable)
- niljub/pic2stl — Python (numpy, Pillow, numpy-stl, scipy), MIT, 9★, 2026-02-09; pip package, extrusion height + base. — [GitHub](https://github.com/niljub/pic2stl)
- Pavelruh/ImageToSTLConverter — Processing, 9★, 2024-05-07; per-color STLs. — [GitHub](https://github.com/Pavelruh/ImageToSTLConverter)
- uijincho/lithophane — Python, MIT, 8★, 2025-07-21. — [GitHub](https://github.com/uijincho/lithophane)
- tjhoff/svg2threedee — Python, 8★, 2017-01-31 (stale). — [GitHub](https://github.com/tjhoff/svg2threedee)
- telefab/ImageExtruder — Python (old PIL), 4★, 2013-06-14 (stale; green-screen photos). — [GitHub](https://github.com/telefab/ImageExtruder)
- DavideDaniel/image-to-stl — Python, 2★, 2026-07-13; "AI-powered" CLI using headless Blender; depth-map tool retired July 2026. — [GitHub](https://github.com/DavideDaniel/image-to-stl)
- Theblackcat98/image-to-stl — Python, CC0-1.0, 1★, **archived** 2026-10-20 (read-only); darker pixels → higher. — [GitHub](https://github.com/Theblackcat98/image-to-stl)
- MekaElectronics/Lithophane-Generator — Python, GPL-3.0, 1★, 2026-10-25. — [GitHub](https://github.com/MekaElectronics/Lithophane-Generator)
- everything3d/figurine-colorize — Python, MIT, 5★, 2026-10-25 (Claude Code skill). — [GitHub](https://github.com/everything3d/figurine-colorize)
- GitHub search totals on 2026-11-08: "image to stl" 346 repos; "image to 3mf" 30; "lithophane" 271; "hueforge" 63; "svg to stl" 126; "cookie cutter stl" 24; "filament painting 3d print" 2; "flexi articulated print-in-place generator" 0. **[GH API]** — [GitHub search](https://github.com/search?q=image+to+stl&type=repositories)

### Inferences
- Nothing in the survey is a maintained, permissively licensed Python library that does the full image → validated, nozzle-aware, multi-body 3MF job; the repository would be filling a real gap by composing rembg/OpenCV + Shapely + trimesh/build123d + a 3MF metadata writer.
- Maintenance signal: only Lumina Layers, Kromacut, AutoForge, vtracer, rembg, trimesh, shapely, build123d, and OpenSCAD show pushes within the last 30 days; most image→STL scripts are abandoned.

### Gaps
- GitHub API rate limit (60/h unauthenticated) was hit before fetching metadata for a few more candidates (e.g., iamdougsgithub/cookie-cutter-maker had 0★/2026-10-26 from search; Flexi tools on Printables/Thingiverse are not on GitHub).
- Could not verify the license of stl-ready-image beyond the GitHub license field (MIT per API; README does not state it).

---

## Key question 7 — Template objects from images (cookie cutters, stencils, stamps, signs, coasters, keychains, badges)

### Takeaway
Cookie cutters are the best-documented template: open generators expose cutter wall ≈0.8 mm, cutter height ≈10 mm with a ~3 mm tapered blade, flange/base ≈4 mm wide × 1 mm tall, optional stamp/imprint and a support mesh for multi-path shapes; they are built from SVG via Inkscape/potrace + OpenSCAD (slow Minkowski offsets are a known pain). Keychain/sign/coaster generators exist mainly as OpenSCAD customizers on MakerWorld/Thingiverse (text + imported SVG logo + loop hole), not as maintained libraries.

### Cited Findings
- CZDanol/cookieCutterStlGenerator (Python, GPL-3.0, 7★, last push 2022-11-29): parameters `baseWidth` 4 mm, `baseHeight` 1 mm, `cutterWidth` 0.8 mm, `cutterHeight` 10 mm (incl. wedge), `cutterWedgeHeight` 3 mm (larger = sharper), `mesh` 0/1 support grid for multi-path cutters with `meshDistance` 10 mm / `meshWidth` 1 mm / `meshArea` 400 mm, `scaling`, weight `w`; inputs SVG/DXF (strokes-only SVGs work best); writes .scad and can call OpenSCAD (`--genStl=1 --openscadLocation`); "generation is slow because it relies on a Minkowski sum"; settings priority filename tokens > CLI > INI. **[GH API + primary README]** — [GitHub](https://github.com/CZDanol/cookieCutterStlGenerator)
- Papooch/cookie-cutter-generator (OpenSCAD, 7★, last push 2024-12-04): Inkscape 1.2+ CLI produces a `-fill.svg`; OpenSCAD **nightly** required for speed ("about 50 seconds versus about 30 minutes for the stable release" on the example); generators `stamp` (offset cutter + stamp of original SVG) and `outline`; Docker image ~1 GB; outputs original SVG, fill SVG, preview PNG, STL. **[GH API + primary README]** — [GitHub](https://github.com/Papooch/cookie-cutter-generator)
- jdreinhardt/SimpleCookie (Python, GPL-2.0, 2★, 2020-06-25): high-contrast image → STL via ImageMagick, Potrace, Inkscape, OpenSCAD. **[GH API + search summary]** — [GitHub](https://github.com/jdreinhardt/SimpleCookie)
- seaburr/cookie-cutter-maker (Python, MIT, 0★, 2026-10-27): PNG outline or text prompt → STL; FastAPI + local web UI; PNG path runs offline. **[GH API + search summary]** — [GitHub](https://github.com/seaburr/cookie-cutter-maker)
- iamdougsgithub/cookie-cutter-maker (JS, 0★, 2026-10-26): browser-only; photo of a cutter or drawn outline → cutter + royal-icing practice blank STLs. **[GH API + README title]** — [GitHub](https://github.com/iamdougsgithub/cookie-cutter-maker)
- DEVividious/cookie-forge: AI-agent skill; image → cutter STL sized to bed, optional imprints. **[search summary]** — [GitHub](https://github.com/DEVividious/cookie-forge)
- Lucandia/Flexifier README manual pipeline for silhouettes: ImageMagick `convert` → PNM → potrace → SVG → OpenSCAD `import()` + `linear_extrude`. **[primary]** — [GitHub](https://github.com/Lucandia/Flexifier)
- Keychain customizers on MakerWorld: text (up to two lines, font size/style, optional background box) and SVG-logo import with round/square/hex shapes. **[secondary]** — [MakerWorld 759759](https://makerworld.com/en/models/759759); [MakerWorld 2731866](https://makerworld.com/en/models/2731866)
- Inkscape extension "Paths to OpenSCAD" turns traced paths into an OpenSCAD extrusion file. **[secondary]** — [paths2openscad .inx](https://gitea.fablabchemnitz.de/FabLab_Chemnitz/mightyscape-1.1-deprecated/raw/commit/31ccee2730a67fca38c6b8cd7001d3d0a966fb62/extensions/fablabchemnitz/paths2openscad.inx)
- Bambu Image to Keychain exposes width, height, thickness, borders, holes, colors (per 2026-08 third-party description). **[secondary]** — [33d.ch](https://33d.ch/en/blog/makerlab)
- Potrace's `-a` alphamax 0 produces pure polygons (useful for CAD-clean outlines) and `-t` turdsize removes speckles. **[primary]** — [potrace man page](https://potrace.sourceforge.net/potrace.1.html)

### Inferences
- All these templates reduce to one Shapely polygon P (from KQ1) plus offsets: cookie cutter = `P.buffer(+wall) − P` extruded to blade height, `P.buffer(+flange) − P` extruded to flange height (plus optional tapered blade via a second thinner ring); stencil = plate minus P with bridges (`P.buffer(−bridge)` subtracted in strips) so islands stay attached; stamp = mirrored P extruded on a base; coaster/badge/keychain = `P.buffer(+border)` base with P as an inset/raised color body and a loop = `Point.buffer(r_outer) − Point.buffer(r_inner)` unioned at the top of the bounding box. Doing offsets in Shapely (GEOS) avoids OpenSCAD's slow Minkowski.
- The common parameter sets exposed by existing generators (wall 0.8 mm, blade 10 mm, flange 4×1 mm, loop hole ~4–5 mm) are a reasonable default schema; wall thickness should be an integer multiple of extrusion width (0.8 or 1.2 mm for a 0.4 mm nozzle) so slicers produce solid walls.

### Gaps
- No open-source generator found for stencils (with automatic bridges) or stamps specifically; "stamp" appears only as the imprint sub-feature of cookie-cutter tools.
- No maintained OSS keychain/badge generator with loop placement logic was found on GitHub; the examples are OpenSCAD customizers on model sites whose licenses were not checked.

---

## Key question 8 — Bridge to articulated prints (silhouette → auto-segmented hinged "flat flexi")

### Takeaway
No open-source tool was found that takes a 2D silhouette and automatically segments it into hinged links. Existing silhouette tools (Flexifier, "Flexi Maker (SVG to Flexi)" OpenSCAD) require manual hinge placement; the tools that auto-segment (FlexIt, printpal) operate on 3D STLs and are hosted/closed. The academic lineage is Bächer et al. SIGGRAPH 2012 (joints on the medial axis of a skinned mesh) and a JAIST thesis on sketch → rigged → CSG-jointed print-in-place figures.

### Cited Findings
- Lucandia/Flexifier (Printables "Flexifier: flexi 3D models generator"): image → potrace SVG → OpenSCAD `linear_extrude`; hinge parameters `X_TRAN_HINGE`, `Y_TRAN_HINGE`, `ROTATE_HINGE`, `HINGE_DIAMETER`, `HINGE_THICKNESS`, `HEIGHT_HING`, `CUT_THICKNESS`, `CUT_LENGTH`; placement is **manual**; Streamlit web app at flexifier.streamlit.app; 38★, last push 2025-02-07. **[GH API + primary README + Printables]** — [GitHub](https://github.com/Lucandia/Flexifier); [Printables](https://printables.com/model/505713-flexifier-flexi-3d-models-generator-print-in-place)
- "Flexi Maker (SVG to Flexi) – Parametrizable – OpenSCAD" (dochni, Thingiverse, older): converts an SVG silhouette into an articulated figure; user sets cut count, position, angle. **[secondary listing]** — [Thingiverse 4803917](https://www.thingiverse.com/thing:4803917)
- FlexIt (mrvarity.com): browser tool that slices a solid STL into a chain of hinged segments along a chosen axis with N links, pin diameter, hinge thickness, clearance presets for PLA/PETG/TPU; input is STL, not a 2D silhouette; open-source status unknown. **[secondary]** — [mrvarity FlexIt](https://mrvarity.com/apps/flexit/)
- printpal Flexi Model Creator: click-to-place joints; "calculates the surface normal and local cross-section, then automatically orients and sizes the cutter"; positions still user-chosen; hosted. **[secondary]** — [printpal](https://printpal.io/tools/flexi-model-creator)
- "Flexy Tool Cutter (Negative Volume)" (Cults3D): a cutter STL to place repeatedly as a slicer negative volume; no automation. **[secondary]** — [Cults3D](https://cults3d.com/en/3d-model/tool/flexy-tool-cutter-negative-volume-crea-modelos-articulados-create-print-in)
- Bächer, Bickel, James, Pfister, "Fabricating articulated characters from skinned meshes," SIGGRAPH 2012: converts a skinned mesh into a single-material printable articulated model, placing joint centers on an approximate medial axis to avoid brittle joints. **[primary]** — [paper PDF](https://vcg.seas.harvard.edu/content/3-publications/20120101-fabricating-articulated-characters-from-skinned-meshes/fabrication.pdf); [SIGGRAPH history](https://history.siggraph.org/?p=110526)
- JAIST thesis (Japanese, English abstract): side-view sketch → image → 3D mesh → automatic rigging (kinematic skeleton + skinning) → joints via CSG → single-piece printable movable figure, with interactive joint adjustment. **[primary, title/author not confirmed]** — [JAIST PDF](https://dspace.jaist.ac.jp/dspace/bitstream/10119/20435/2/paper.pdf)
- "Stick figure to 3D model" (Computers & Graphics 2022, DOI 10.1016/j.cag.2022.10.004) and ArtiSketch (articulated sketch modeling) are adjacent but not print-in-place tools. **[primary]** — [ArtiSketch PDF](https://zoharl3.github.io/publ/ArtiSketch.pdf)
- GitHub search "flexi articulated print-in-place generator" returned 0 repositories on 2026-11-08. **[GH API]**

### Inferences
- A deterministic auto-segmentation for flat flexis could be built from the KQ1 polygon: skeletonize the mask (e.g., `skimage.morphology.skeletonize`/medial axis), pick cut lines perpendicular to the skeleton at regular arc-length intervals where the local width exceeds the hinge diameter + 2×clearance + 2×wall, then subtract `CUT_THICKNESS` slots and add cylindrical pin/socket pairs — the medial-axis placement rule is exactly what Bächer et al. use. This is identified as a gap/opportunity; the design rules themselves are covered by the other researcher.

### Gaps
- No OSS repo or paper found that performs silhouette → automatic hinge segmentation for print-in-place; the JAIST thesis is the closest lead and its title/author were not confirmed.
- FlexIt and printpal licensing/source availability not verified.

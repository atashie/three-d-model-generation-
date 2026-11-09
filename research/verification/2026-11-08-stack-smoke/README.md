# Stack smoke test, 2026-11-08

Local checks run on the target machine before choosing the core stack. These scripts are throwaway prototypes. Each finding here should become a real test in `tests/` during Phase 1.

**Machine:** Apple M5, arm64, 16 GB unified memory, macOS 26.3. Python 3.13.15 venv made with `uv`.

## 1. Wheel availability by Python version

Method: `uv pip compile --python-platform aarch64-apple-darwin --only-binary :all:` for each package. This proves that a binary wheel *resolves*. It does not prove that the package imports and works. Section 2 covers that for the core set.

| Package | 3.12 | 3.13 | 3.14 |
|---|---|---|---|
| Core set (numpy, scipy, trimesh, manifold3d, lib3mf, shapely, opencv-python-headless, build123d, vtracer, pydantic, typer, pyyaml, thingi10k) | ok | ok | ok |
| pymeshlab 2025.7.post1 | ok | ok | ok |
| pymeshfix 0.18.1 | ok | ok | ok |
| libigl 2.6.3 | ok | ok | ok |
| open3d 0.20.0 | ok | ok | ok |
| rembg 2.0.87 | ok | ok | ok |
| onnxruntime (rembg needs it) | ok | ok | see note |
| orca123d 0.1.2 (Bambu/Orca 3MF writer) | **no** | ok | ok |
| point-cloud-utils 0.34.0 | ok | ok | **no** |
| bpy (Blender as a module) | **no** | 5.2.3 | not tested |

**Caution about this method:** `--python-platform aarch64-apple-darwin` resolves against an old macOS by default. With the default, onnxruntime showed "no wheel" on 3.14. With `MACOSX_DEPLOYMENT_TARGET=14.0`, onnxruntime 1.31.1 resolves on 3.14. Its wheels are tagged `macosx_14_0`. The target machine runs macOS 26, so the newer wheels apply. point-cloud-utils still has no 3.14 wheel at targets 12, 14, or 15.

**Conclusion:** Python 3.13 is the only version where every candidate installs. earthtojake/text-to-cad requires 3.14. If we use it, it must run in its own environment.

### 1b. Real install and import on Python 3.13 (`opt_import_smoke.py`)

This replaces the resolver-only result for the optional packages. Every package below installed with `--only-binary :all:` and imported, except cgal.

| Package | Installed wheel tag | Functional check |
|---|---|---|
| pymeshfix 0.18.1 | `cp312-abi3-macosx_11_0_arm64` | Default `clean_from_arrays` on two separate cubes kept **1** component. It silently deleted the other cube |
| libigl 2.6.3 | `cp312-abi3-macosx_11_0_arm64` | Imports |
| pymeshlab 2025.7.post1 | `cp313-cp313-macosx_11_0_arm64` | Two cubes: two-manifold true, 0 boundary edges |
| open3d 0.20.0 | `cp313-cp313-macosx_11_0_arm64` | Two cubes: watertight true |
| onnxruntime 1.31.1 | `cp313-cp313-macosx_14_0_arm64` | Providers: CoreML, Azure, CPU |
| rembg 2.0.87 (`[cpu]` extra) | pure Python | Imports. Its models were not downloaded or run |
| orca123d 0.1.2 | pure Python | Imports |
| point-cloud-utils 0.34.0 | `cp313-cp313-macosx_11_0_arm64` | Imports |
| pyobjc-framework-Vision | — | Imports |
| meshlib 3.1.4.297 | — | Imports (non-commercial licence) |
| cgal 6.0.1 (GPL-3) | **no cp313 wheel**; newest is cp312 | Not installable on 3.13. Use a separate 3.12 environment if ever needed |

**Correction to the research:** the mesh-validation note and the landscape report say pymeshfix's arm64 wheels "stop at cp312" and recommend Python 3.12. That is wrong in practice. pymeshfix and libigl ship `abi3` wheels. An abi3 wheel tagged cp312 uses CPython's stable ABI, so it is ABI-compatible with later CPython versions. The package's own `Requires-Python` still applies: pymeshfix 0.18.1 declares `>=3.10,<3.15`. ABI compatibility also does not guarantee identical behavior. We tested 3.13 only.

pymeshfix's API needs C-contiguous `float64` vertices and `int32` faces. The first call failed because of dtype and memory layout, not because the inputs were trimesh tracked arrays. Converted tracked arrays work.

## 2. End-to-end flat chain (`flat_chain_smoke.py`)

Chain: synthetic image, then OpenCV contours, then Shapely polygons, then trimesh extrusion. Checks use trimesh, manifold3d, and lib3mf. Exports are STL and two-color 3MF, plus one build123d part.

| Check | Result |
|---|---|
| Tiny speck removed by min-area filter | yes (1 polygon kept) |
| Ring keeps its hole | yes |
| trimesh: watertight, winding consistent, positive volume | yes, yes, yes |
| trimesh volume vs manifold3d volume | 2756.2 vs 2756.2 mm³ |
| Genus of ring (expected 1) | trimesh Euler number 0, manifold3d genus 1 |
| lib3mf read-back `IsManifoldAndOriented` on both objects | true, true |
| build123d tag volume vs analytic | 2341.1 vs 2341.1 mm³ |
| STL bytes identical across two processes | yes, on this machine with these exact package versions. trimesh chose its triangulation engine implicitly (manifold here); pass `engine=` explicitly. Cross-platform equality is unverified |
| 3MF bytes identical across two processes | **no** (see 4) |
| Two-color 3MF keeps base and ring together | **not guaranteed**. Each body is a separate build item, and the 3MF core spec lets consumers rearrange separate build items. Use one components object with one build item (see 5) |

Dependency finding: `trimesh.load()` on a 3MF needs `networkx` and `lxml`. trimesh does not install them by default. Both are now in `core-requirements.in` and the lock file.

## 3. Half-pixel contour bias (`half_pixel_check.py`)

`cv2.findContours` traces the *centers* of the foreground pixels on each boundary. So the outer outline sits half a pixel inside the true edge. A hole outline also runs through foreground pixel centers, which puts it half a pixel *outside* the true hole edge: **traced holes come out too large.** Example: a 3×3-pixel hole (9 cells) traces as a polygon of area 14. (Corrected 2026-11-09 after independent review; the first version of this note had the hole direction backwards.) Both effects shrink the foreground, so one outward `buffer(+0.5 px)` moves both boundaries in the right direction.

| Case | Raw contour area error | After `buffer(+0.5 px)` |
|---|---|---|
| High-res ring (R = 150 px) | −1.00% | +0.17% |
| Low-res ring (R = 15 px) | −10.07% | +1.95% |

**Why it matters:** At 0.5 mm per pixel, the bias is 0.25 mm per side. That is the same size as a print-in-place clearance, so the error alone can fuse or free a joint.

**What this test does and does not show:** pixel count is ground truth for *area* under a square-cell reading of the image. It is not ground truth for boundary position or gap width. On the 7×7 square with a 3×3 hole, the buffered polygon has area 41 against 40 pixel cells, but its boundary is still up to **0.5 px** from the pixel-cell outline (Hausdorff distance). So `buffer(+0.5)` is an area approximation, not a dimensional correction. Before choosing a fix, define the reference geometry (pixel-cell outline or a smoothed curve). Then measure outer and hole dimensions, boundary deviation, topology, and minimum gaps separately. Compare against tracers that follow pixel edges, such as vtracer and potrace, with their settings fixed.

## 4. Deterministic 3MF (`det3mf.py`)

lib3mf writes random Production-extension UUIDs on every object, build, build item, and component. Zip entry timestamps are repeatable, but lib3mf writes the fields as `(1980, 0, 0, 0, 0, 0)`, with month and day zero. That is not a valid calendar date, so normalize the timestamps ourselves if any tool rejects them. To get byte-identical 3MF files, set the UUIDs yourself with `SetUUID` and `SetBuildUUID`. This was checked: two runs gave the same SHA-256.

**Caveat on the recipe:** `det3mf.py` derives UUIDs from names alone, so changing the cube's size kept the same UUIDs. Reusing a name for two instances would give them the same UUID. Production code needs an identity scheme: a project namespace, a content or model identity, and a unique path for each instance. Component references need UUIDs too.

## 5. Independent review (Codex, 2026-11-09)

An independent read-only review by OpenAI Codex reproduced the published tables and checks, and found these defects in the prototype scripts. We reproduced the first two ourselves. The third follows directly from the code: `cv2.findContours` returns `None` for the hierarchy when it finds no contours. They must be fixed when the scripts become tests in Phase 1.

| Defect | Evidence | Fix |
|---|---|---|
| `make_valid(...).buffer(0)` can return a MultiPolygon or GeometryCollection; the script assumes one Polygon | Two diagonally touching 3×3 blocks give a MultiPolygon, and extrusion then fails. Also, the area filter runs on the combined shape, so two 4 mm² parts pass a 5 mm² threshold together | Extract the polygon parts recursively, filter each part, extrude each part, and report collapsed slivers |
| Image Y axis points down; model Y points up | An L-shaped mask came out mirrored top to bottom. The circular fixture hides this | Define one image-to-model transform (origin, pixel centers vs edges, scale, Y flip) and test it with an asymmetric glyph |
| Empty or fully filtered masks crash | `hier` is `None` for an all-zero mask; `polys[0]` fails when everything is filtered | Return a clear "no printable foreground" result |
| float32 vertices lose geometry far from the origin | A 0.2 mm box at X = 10,000,000 became empty in manifold3d with status `NoError`. lib3mf also stores float32 | Recenter before export; check non-emptiness and deviation, not only status |
| Two-color 3MF bodies are separate build items | 3MF core spec §3.4.3.1 and §4.2 | One components object, one build item |
| UUIDs come from names only | See section 4 | Identity scheme with instance paths |

## Reproduce

```bash
uv venv --python 3.13 .venv-smoke
uv pip install --python .venv-smoke/bin/python -r core-requirements-py3.13.lock.txt
.venv-smoke/bin/python flat_chain_smoke.py ./out
.venv-smoke/bin/python half_pixel_check.py
.venv-smoke/bin/python det3mf.py ./out/det.3mf
```

## Not yet checked

- No slicer is installed, so no headless slicer CLI was run.
- None of the ML perception models were installed or run (background removal, segmentation, depth).
- No image-to-3D backend was called.

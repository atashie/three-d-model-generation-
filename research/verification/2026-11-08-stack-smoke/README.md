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
| onnxruntime 1.23.2 (rembg needs it) | ok | ok | **no** |
| orca123d 0.1.2 (Bambu/Orca 3MF writer) | **no** | ok | ok |
| point-cloud-utils 0.34.0 | ok | ok | **no** |
| bpy (Blender as a module) | **no** | 5.2.3 | not tested |

**Conclusion:** Python 3.13 is the only version where every candidate resolves. earthtojake/text-to-cad requires 3.14. If we use it, it must run in its own environment.

Note: the mesh-validation research note says pymeshfix and libigl wheels stop at cp312. The resolver disagrees. Check this with a real install before depending on either.

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
| STL bytes identical across two processes | yes |
| 3MF bytes identical across two processes | **no** (see 4) |

Dependency finding: `trimesh.load()` on a 3MF needs `networkx` and `lxml`. trimesh does not install them by default. Put both in the core dependency list.

## 3. Half-pixel contour bias (`half_pixel_check.py`)

`cv2.findContours` traces the *centers* of boundary pixels. So the traced outline sits half a pixel inside the true edge, and holes come out half a pixel too small.

| Case | Raw contour area error | After `buffer(+0.5 px)` |
|---|---|---|
| High-res ring (R = 150 px) | −1.00% | +0.17% |
| Low-res ring (R = 15 px) | −10.07% | +1.95% |

**Why it matters:** At 0.5 mm per pixel, the bias is 0.25 mm per side. That is the same size as a print-in-place clearance, so the error alone can fuse or free a joint. Correct the bias explicitly, or use a tracer that follows pixel edges, such as potrace or vtracer. Then test the result against pixel-count ground truth.

The mitred buffer overshoots a little on staircase edges. Compare it with an edge-following tracer before choosing a fix.

## 4. Deterministic 3MF (`det3mf.py`)

lib3mf writes random Production-extension UUIDs on every object, build, and build item. Zip entry timestamps are already fixed at 1980-01-01. To get byte-identical 3MF files, set the UUIDs yourself with `SetUUID` and `SetBuildUUID`, using `uuid5` values derived from stable names or content. This was checked: two runs gave the same SHA-256.

## Reproduce

```bash
uv venv --python 3.13 .venv-smoke
uv pip install --python .venv-smoke/bin/python -r core-requirements-py3.13.lock.txt networkx lxml
.venv-smoke/bin/python flat_chain_smoke.py ./out
.venv-smoke/bin/python half_pixel_check.py
.venv-smoke/bin/python det3mf.py ./out/det.3mf
```

## Not yet checked

- No slicer is installed, so no headless slicer CLI was run.
- None of the ML perception models were installed or run (background removal, segmentation, depth).
- No image-to-3D backend was called.

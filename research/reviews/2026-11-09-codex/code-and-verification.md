No critical findings.

- **Major — [flat_chain_smoke.py:26](../../../research/verification/2026-11-08-stack-smoke/flat_chain_smoke.py#L26): repair output is not safe for the downstream Polygon-only code.**  
  **Code:** `p = make_valid(p).buffer(0)` followed by appending `p`; extrusion subsequently assumes `.exterior` exists.  
  **Evidence:** Calling the repository function on two diagonally touching 3×3 pixel blocks returned a `MultiPolygon`; extrusion raised `AttributeError: 'MultiPolygon' object has no attribute 'exterior'`. Its two components each had area 4, but their combined area 8 passed a minimum-area threshold of 5. A one-pixel bridge produced a `GeometryCollection` containing polygons and lines; `buffer(0)` discarded the lines. These return types and collapsed geometries are documented by [Shapely](https://shapely.readthedocs.io/en/stable/reference/shapely.make_valid.html).  
  **Suggested fix:** Recursively extract polygon components, filter each component separately, and extrude each retained polygon. Explicitly report collapsed features. If one-pixel bridges must retain physical width, trace pixel-cell boundaries before repair. Also replace `ring = polys[0]` when generalizing the pipeline; it discards additional retained components.

- **Major — [README.md:70](../../../research/verification/2026-11-08-stack-smoke/README.md#L70), [half_pixel_check.py:15](../../../research/verification/2026-11-08-stack-smoke/half_pixel_check.py#L15): the hole-bias explanation is backwards, and the buffer experiment does not establish dimensional accuracy.**  
  **Claim/code:** “holes come out half a pixel too small”; `poly.buffer(0.5, join_style="mitre")`; comparison against “pixel-count ground truth.”  
  **Evidence:** For a 7×7 filled square with a 3×3 empty square, the hole contains 9 pixel cells, while its OpenCV contour encloses area **14**: the raw hole is too large. The buffer shrank it to **8**, overshooting the correction. Against the exact union of occupied pixel cells, the buffered boundary still had Hausdorff distance **0.5 px**, despite total area being only 41 versus 40. Pixel count measures area under a square-cell interpretation; it does not establish boundary position, clearances, or the original continuous shape. [Potrace’s paper](https://potrace.sourceforge.net/potrace.pdf) explicitly discusses the ambiguity of recovering outlines from a bitmap.  
  **Suggested fix:** Correct the hole direction and describe `+0.5` as an approximation dependent on geometry. Define the intended reference geometry, then measure separate outer/hole dimensions, boundary deviation, topology, and minimum gaps. Specify and test tracer modes and smoothing parameters before recommending an alternative tracer.

- **Major — [flat_chain_smoke.py:25](../../../research/verification/2026-11-08-stack-smoke/flat_chain_smoke.py#L25): image coordinates are transferred without an orientation convention.**  
  **Code:** `Polygon(shell * mm_per_px, ...)`.  
  **Evidence:** Image rows increase downward; Cartesian Y increases upward in the usual XY top view. An asymmetric test mask’s top bar remained at low CAD Y, vertically reflecting the artwork. The circular fixture conceals this. Applying `y′ = H - 1 - y` before extrusion preserved watertightness and positive volume in my test.  
  **Suggested fix:** Define the image-to-model transform explicitly, including pixel-center versus pixel-edge coordinates, origin, scale, and Y reflection. Verify it with an asymmetric glyph and an off-center hole.

- **Major — [flat_chain_smoke.py:75](../../../research/verification/2026-11-08-stack-smoke/flat_chain_smoke.py#L75): the two-color assembly is exported as independently movable build items.**  
  **Code:** `model.AddBuildItem(o, w.GetIdentityTransform())` for both base and raised ring.  
  **Evidence:** The [3MF Core specification, §3.4.3.1 and §4.2](https://raw.githubusercontent.com/3MFConsortium/spec_core/master/3MF%20Core%20Specification.md) permits consumers to rearrange separate build items, while requiring relative positions within a component object to be preserved. The current encoding therefore does not preserve the intended base/ring relationship against compliant rearrangement. Per-object manifold checks cannot detect this.  
  **Suggested fix:** Put the two mesh resources in one `ComponentsObject` and add that assembly as one build item. Retain properties on the mesh resources. Separately verify color-to-filament assignment in the intended slicer.

- **Minor — [flat_chain_smoke.py:19](../../../research/verification/2026-11-08-stack-smoke/flat_chain_smoke.py#L19): empty masks crash.**  
  **Code:** `hier = hier[0]`; subsequently `ring = polys[0]`.  
  **Evidence:** An all-zero mask raised `TypeError: 'NoneType' object is not subscriptable`. A nonempty mask whose components are all filtered out reaches the second unchecked indexing operation.  
  **Suggested fix:** Handle `hier is None` and an empty retained-polygon list explicitly, returning a clear “no printable foreground” result.

- **Minor — [det3mf.py:13](../../../research/verification/2026-11-08-stack-smoke/det3mf.py#L13), [README.md:83](../../../research/verification/2026-11-08-stack-smoke/README.md#L83): the UUID recipe needs identity scoping before reuse.**  
  **Code:** `det("object:cube")`, `det("item:cube")`, and `det("build")` under a constant namespace.  
  **Evidence:** Changing the cube from 10 mm to 20 mm retained all three UUIDs. Reusing these names for multiple instances would likewise duplicate their identifiers. The [Production extension](https://github.com/3MFConsortium/spec_production/blob/master/3MF%20Production%20Extension.md?plain=1) uses UUIDs to identify objects and instances across packages. Components also have UUIDs: a locally created component received a random one automatically.  
  **Suggested fix:** Define identity semantics using a project namespace, canonical model/content identity, and unique instance paths. Set UUIDs on component references as well as objects, build items, and builds; verify uniqueness and repeatability.

- **Minor — [flat_chain_smoke.py:40](../../../research/verification/2026-11-08-stack-smoke/flat_chain_smoke.py#L40), [README.md:63](../../../research/verification/2026-11-08-stack-smoke/README.md#L63): determinism is demonstrated only within a limited environment, with an implicit triangulation backend.**  
  **Code/claim:** `extrude_polygon(..., height)` without `engine`; “STL bytes identical across two processes.”  
  **Evidence:** The committed hash loop calls `build()` twice in one process. I independently reproduced equality across separate processes, but that establishes local repeatability only. Installed trimesh source selects the first available engine: earcut, then manifold, then triangle. This environment selects manifold. Installing another optional backend can change the selected algorithm. The subsequent manifold3d check also shares a library with triangulation, limiting the claimed independence.  
  **Suggested fix:** Specify `engine="manifold"` for this stack, retain a subprocess test covering the complete conversion, and state the supported determinism envelope: package versions, backend, platform, and serialization settings. Treat cross-platform byte equality as unverified.

- **Minor — [core-requirements.in:1](../../../research/verification/2026-11-08-stack-smoke/core-requirements.in#L1), [README.md:89](../../../research/verification/2026-11-08-stack-smoke/README.md#L89): the reproduction environment is not fully locked.**  
  **Code:** `uv pip install ... -r core-requirements-py3.13.lock.txt networkx lxml`.  
  **Evidence:** Neither dependency appears in the input file or lockfile, although the smoke script imports the 3MF scene through trimesh and the README identifies both as required. The tested environment supplies `networkx 3.7` and `lxml 6.1.3`; reproduction resolves their versions afresh.  
  **Suggested fix:** Add both direct dependencies to the input and regenerate the lock. Record optional-package requirements separately so the optional smoke test is reproducible too.

- **Minor — [flat_chain_smoke.py:49](../../../research/verification/2026-11-08-stack-smoke/flat_chain_smoke.py#L49): float32 conversion can silently change or erase geometry outside the fixture’s coordinate range.**  
  **Code:** `np.asarray(m.vertices, np.float32)`.  
  **Evidence:** A 0.2×1×1 mm box translated to X=1,000,000 became approximately **0.25 mm³** after conversion. At X=10,000,000 it became empty with volume **0**, while `status()` still returned `Error.NoError`. `Mesh64` preserved approximately 0.2 mm³ in both tests. The installed `lib3mf.Position` also stores coordinates as `c_float`. The current small, near-origin fixture is safe from this demonstrated failure.  
  **Suggested fix:** Enforce units and coordinate bounds, recenter geometry before float32 export, and use `Mesh64` for intermediate validation where needed. Check nonemptiness and geometric deviation in addition to status, including after serialization.

- **Minor — [README.md:46](../../../research/verification/2026-11-08-stack-smoke/README.md#L46): `abi3` compatibility is overstated.**  
  **Claim:** A `cp312-abi3` wheel “installs and runs on 3.12 and all later versions.”  
  **Evidence:** Installed pymeshfix 0.18.1 declares `Requires-Python: <3.15,>=3.10`; [PyPI confirms this restriction](https://pypi.org/project/pymeshfix/0.18.1/). Stable ABI compatibility does not override package metadata or guarantee runtime behavior; [Python’s documentation](https://docs.python.org/3.13/c-api/stable.html#stable-application-binary-interface) explicitly distinguishes ABI stability from behavioral compatibility.  
  **Suggested fix:** Say the wheel is ABI-compatible with eligible later conventional CPython versions, subject to package and dependency constraints; specifically record that 3.13 was tested.

- **Nit — [README.md:48](../../../research/verification/2026-11-08-stack-smoke/README.md#L48): the pymeshfix rejection is attributed too broadly to tracked arrays.**  
  **Claim:** “It rejects trimesh’s tracked arrays directly.”  
  **Evidence:** The original arrays failed, but `.astype(np.float64)` vertices and `.astype(np.int32)` faces succeeded while both remained `trimesh.caching.TrackedArray` instances. The relevant requirements are dtype and memory layout, not rejection of that subclass.  
  **Suggested fix:** Explain the dtype/layout mismatch. The existing `np.ascontiguousarray(..., dtype=...)` conversion is appropriate.

- **Nit — [README.md:83](../../../research/verification/2026-11-08-stack-smoke/README.md#L83): the recorded ZIP date is inaccurate.**  
  **Claim:** “Zip entry timestamps are already fixed at 1980-01-01.”  
  **Evidence:** Inspecting lib3mf’s in-memory output with `zipfile` returned `(1980, 0, 0, 0, 0, 0)` for every entry, not January 1. These fields were repeatable, but contain zero month/day values.  
  **Suggested fix:** Record the observed values accurately. If valid canonical ZIP dates are required, explicitly normalize them and test the resulting archive.

**Things I checked and found correct**

- `RETR_CCOMP` parent handling retained two polygons, each with a hole, in a four-level nesting fixture; nested foreground islands are promoted to the top level as [OpenCV documents](https://docs.opencv.org/4.x/d3/dc0/group__imgproc__shape.html).
- Both published half-pixel area tables reproduced exactly.
- The ring reproduced watertightness, consistent winding, positive volume, and the reported 2756.2 mm³ in both libraries.
- Euler number 0 and genus 1 are correct for this connected, closed, orientable ring surface.
- The installed manifold3d and lib3mf constructor/property calls used by the fixtures worked.
- In-memory 3MF output contained both colors, millimeter units, and two objects that passed lib3mf’s manifold/orientation check; trimesh loaded two geometries and omitted colors.
- The build123d subtraction produced a valid solid of 2341.0951 mm³; in-memory tessellation was watertight and rounded to the reported volume.
- Separate-process STL and UUID-controlled 3MF hashes matched locally.
- Every package version listed in the core lock matched the supplied environment.
- Optional checks reproduced pymeshfix retaining one component, PyMeshLab’s topology result, Open3D watertightness, and the listed ONNX providers.
- The distinction between wheel resolution and runtime verification is sound; [uv documents the macOS deployment-target behavior](https://docs.astral.sh/uv/reference/cli/#uv-pip-compile--python-platform).
- Current [cad-server metadata](https://raw.githubusercontent.com/earthtojake/text-to-cad/main/packages/cad-server/pyproject.toml) confirms Python ≥3.14; [CGAL’s published wheels](https://pypi.org/project/cgal/) stop at cp312 for the cited release family.

**Could not verify**

- `rembg` import failed with a Numba caching error in the read-only environment. This does not settle whether the earlier unrestricted import succeeded.
- Disk-writing export paths were not executed; geometry and 3MF serialization were checked in memory instead.
- The full Python 3.12/3.14 resolution matrix, joint installation of every candidate, and cross-platform byte determinism were not reproduced.
- Slicer preservation of assembly/colors, filament assignment, and actual FDM printability remain unverified; no slicing or physical printing was performed.
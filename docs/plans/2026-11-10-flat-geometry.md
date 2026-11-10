# Flat geometry (R1 stages S2–S4, S8) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** add `tdmg flat`. It turns a reviewed selection folder (from `tdmg select`) into a
flat solid of a chosen width and thickness. It writes `model.stl`, an outline preview, and
a record with gate checks run on the written file. This is the geometric core of R1. A
keychain loop or base, 3MF output, and slicing come in later plans.

**Architecture:**
- `src/tdmg/records.py` holds the record helpers that `selection.py` already uses:
  canonical JSON, the environment block, and exclusive, ordered writes. Both stages
  share it.
- `src/tdmg/checks.py` holds gate check results and the F1 topology checks.
- `src/tdmg/flat.py` builds the outline, transforms it, cleans it, extrudes it, and
  writes the outputs.
- `src/tdmg/cli.py` gets a thin `flat` command.

**Tech stack:** numpy, Shapely 2.2 (outline union, buffers), manifold3d 3.x (extrusion
that is manifold by construction), trimesh (STL I/O and mesh queries), Pillow and OpenCV
(preview), pytest. All are core dependencies already.

**Status:** written and executed 2026-11-10 (Tasks 1–9); see "Execution notes".

**Conventions for the implementer:**
- Put imports in the top block (ruff E402). Keep lines ≤ 100 characters; ruff does not
  enforce this here, so check with awk.
- Write files with LF line endings. Use `write_bytes` for text, so Windows doesn't
  convert to CRLF.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never weaken an assertion to make a test pass. Investigate and report instead.
- Run CLI tests under `CI=true GITHUB_ACTIONS=true` as well (see CLAUDE.md).
- **Docs:** the doc lint treats any backticked dotted name whose first part is a rule
  namespace as a rule id, for example `flat`. So write the record's file name with a
  path in docs (`out/flat.json`), never bare.
- **Checked during planning** (scratch prototype, 2026-11-10, Shapely 2.2.0, manifold3d,
  trimesh as locked), on the owner's masks and a synthetic diagonal-touch mask:
  - **Speed:** the pixel-run union takes 0.04 s on Roadie.
  - **Roadie at 60 × 3 mm:** opening at 0.4 mm removes 1.19% of the area. The result is
    one body: watertight, consistently wound, 0 bad vertex links, 37,148 triangles.
  - **Diagonal touches:** two squares touching only at a corner become two separate
    valid bodies at 2, 8 and 40 mm widths.
  - **STL repeatability:** binary STL bytes are identical across two processes, and the
    trimesh STL header is all zeros.
  - **Finding: the opening shrinks the bounding box.** The 40 mm Roadie came out 39.53 mm
    wide because the spike tips round off. Decision 3 handles this.

## Decisions this plan rests on

1. **The reference outline is the exact pixel-cell outline**, the union of the mask's
   pixel squares. It represents the mask exactly. It also avoids the half-pixel bias of
   OpenCV centre tracing (rule `vectorize.opencv.contour_offset_px`), which this plan
   does not use. The staircase edge is one pixel high: about 0.1 mm for Roadie at 60 mm,
   which is under the nozzle width. Smoothing is out of scope.
2. **Size and thickness are required job parameters**, `--width-mm` and
   `--thickness-mm`, with no defaults. They are the user's choices, not design rules, so
   they need no rules-registry entries.
3. **The width applies to the selection.** The scale is `width_mm / mask width in
   pixels`, exactly. Cleaning then removes features by the cleaning rules (untested hypotheses). The record
   reports the final extents and the measured change (area removed, Hausdorff distance),
   so the user can see it. The width is not silently re-fitted.
4. **The image-to-model transform** is `x_mm = (x_px − x0)·s` and `y_mm = (y1 − y_px)·s`.
   Here `(x0, y1)` are the left and bottom edges of the mask's pixel-cell bounding box.
   The model's +Y is the image's up, and the bounding box's lower-left corner sits at
   the origin. An asymmetric glyph tests this.
5. **Cleaning** uses existing rules:
   - an opening (shrink then regrow) of `flat.sliver.opening_width`;
   - after it, parts smaller than (`flat.island.min_square_side` × nozzle diameter)²
     are dropped. The nozzle diameter comes from the printer profile.
   - Every removed island is reported. Opening also separates parts that touched only at
     a corner, which pinched vertices would otherwise cause.
6. **Extrusion uses manifold3d** with explicitly oriented rings and `FillRule.Positive`.
   The triangulation engine is therefore named, not chosen implicitly by trimesh.
7. **The gate runs on the written file (S8):** `model.stl` is read back, its corners are
   merged only where coordinates are exactly equal, and then the checks run. Statuses
   are PASS, FAIL or UNKNOWN. The overall verdict is **NOT CERTIFIED** in this plan,
   whatever happens, because two required checks cannot pass yet:
   - **F3 (thin walls):** reported as a measurement with status UNKNOWN. Tapered tips
     always leave some region below `fdm.wall.min_thickness`. Whether such regions
     matter depends on how the slicer prints narrow features, which is unresearched.
   - **F6 (slicer):** UNKNOWN until a slicer is installed and wrapped.

## Behaviour contract

- **Input:** a `tdmg select` output folder.
  - `selection.json` must exist.
  - `mask.png` must load through `selection.load_mask` at the recorded size, and its
    pixel hash must equal the recorded `mask_pixels_sha256`. Otherwise `FlatError`.
  - An empty mask gives `FlatError("no printable foreground")`, and nothing is written.
- **Outputs:** in a new or empty `--out` folder, written in the same exclusive, ordered
  way as selection:
  - `model.stl`: binary, in millimetres;
  - `outline.png`: the mask in grey, with pixels removed by cleaning in red, at mask
    resolution;
  - `out/flat.json`, written last.
- **The record** contains:
  - schema `tdmg.flat/1`, the algorithm version, and a `flat_id`. The id is a SHA-256 of
    the canonical JSON of {algorithm, mask_pixels_sha256, params with rule provenance,
    printer id}.
  - `selection` {selection_id, mask_pixels_sha256};
  - `transform` {scale_mm_per_px, x0_px, y1_px};
  - `cleaning`: the `clean` report, as amended after review (see "Execution notes"):
    {opening_mm, min_island_mm2, area_before_mm2, area_after_mm2, removed_area_mm2,
    boundary_hausdorff_mm, hausdorff_sample_step_mm, hausdorff_upper_bound_mm,
    dropped_islands {count, total_area_mm2, largest_mm2}, vanished_parts {count,
    total_area_mm2}, ignored_non_polygonal};
  - `mesh` {triangles, bodies, volume_mm3, extents_mm};
  - `checks` [...] and `verdict`;
  - `outputs` (sha256 of each file), `environment`, and a review sentence.
- **CLI:** `tdmg flat SELECTION_DIR --width-mm W --thickness-mm T --out DIR
  [--printer bambu-a1]`. `FlatError`, `SelectionError` and `OSError` exit with code 2.
  On success it prints the verdict, the failing and unknown checks, `flat_id` and the
  file paths.

---

### Task 1: Shared record helpers (refactor, no behaviour change)

**Files:** create `src/tdmg/records.py`; modify `src/tdmg/selection.py`; test with
`tests/test_records.py` (new) and the existing `tests/test_selection.py`.

Move these from `selection.py` into `records.py`, without changing behaviour:
- `_canonical` → `canonical_json(obj) -> bytes`
- `_environment` → `environment() -> dict`
- `_png_bytes` → `png_bytes(arr) -> bytes`
- the ordered exclusive writer, as `write_outputs(out_dir, files: dict[str, bytes],
  record_name: str, record_bytes: bytes) -> None`

`write_outputs` behaves as `write_selection` does today:
- it refuses a non-empty folder or a file at the path;
- it creates the folder exclusively when it is new;
- it writes each file with `"xb"`;
- it writes the record last, through a uniquely named temporary file and `os.replace`;
- it maps `FileExistsError` races to an error.

Use a new `RecordError(ValueError)` in `records.py`. `selection.py` catches it and
re-raises it as `SelectionError` with the same messages, so its tests keep passing
unchanged.

**Steps:**
1. Write `tests/test_records.py`: canonical JSON is compact, sorted and refuses NaN; the
   environment has the five keys; `write_outputs` refuses a non-empty folder, writes the
   record last, and leaves no temporary file after success.
2. Run the new tests and confirm they fail (no module).
3. Implement `records.py` and switch `selection.py` to it.
4. The whole suite passes, **including the golden selection test unchanged**. Ruff is
   clean.
5. Commit: "Extract shared record helpers for selection and later stages".

### Task 2: Gate check results and F1 topology checks

**Files:** create `src/tdmg/checks.py` and `tests/test_checks.py`.

```python
Status = Literal["PASS", "FAIL", "UNKNOWN"]


@dataclass(frozen=True)
class CheckResult:
    id: str                 # e.g. "F1.edge_manifold"
    status: Status
    measured: object        # JSON-serialisable
    threshold: object | None
    rule: str | None        # rules-registry id, when a rule sets the threshold
    note: str = ""

    def as_dict(self) -> dict: ...


def merge_exact(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Unify only exactly equal coordinates (STL stores corners). No snapping or repair."""


def topology_checks(mesh: trimesh.Trimesh) -> list[CheckResult]:
    """F1 on an exactly merged mesh."""


def verdict(results: list[CheckResult], required: set[str]) -> str:
    """'PRINTABLE' only if every required check is present and PASS; else 'NOT CERTIFIED'."""
```

The F1 checks, one result each:

| Check | Passes when | Rule |
|---|---|---|
| `F1.finite` | all coordinates are finite | none |
| `F1.no_degenerate_faces` | no face repeats a vertex index and no face has exactly zero area | none |
| `F1.no_duplicate_faces` | no two faces have the same sorted vertex set | none |
| `F1.edge_manifold` | every undirected edge is used by exactly 2 faces | `format.3mf.edge_manifold` |
| `F1.consistent_orientation` | every directed edge appears once and its reverse appears once | `format.3mf.consistent_orientation` |
| `F1.vertex_manifold` | every vertex's link (the opposite edges of its incident faces) is one closed cycle | `gate.topology.vertex_manifold` |
| `F1.positive_volume` | every body (connected component, split with `repair=False`) has a signed volume > 0 | none |

The vertex-link algorithm comes from
`research/experiments/2026-11-g3-local-vs-hosted/inspect_makerlab.py`, lines 22–38.
That is repo code under MIT; port it with a comment citing it.

**Tests (TDD):**
- **Positive fixtures:** a cube, and a box with a through-hole (from manifold3d), both
  pass every F1 check.
- **Negative fixtures**, one defect each, where the named check fails:
  - a cube with one face removed: edge_manifold FAILs;
  - a cube with one face flipped: consistent_orientation FAILs;
  - two cubes sharing one vertex: **vertex_manifold FAILs while edge_manifold and
    orientation pass**, the case CLAUDE.md warns about;
  - a duplicated face: no_duplicate_faces FAILs;
  - a zero-area face: no_degenerate_faces FAILs;
  - an inside-out cube: positive_volume FAILs.
- `verdict`: a missing required check means NOT CERTIFIED, and so do FAIL and UNKNOWN.
  All PASS gives PRINTABLE.
- Commit: "Add gate check results and F1 topology checks".

### Task 3: Outline and image-to-model transform

**Files:** create `src/tdmg/flat.py` and `tests/test_flat.py`.

```python
QUAD_SEGS = 8  # Buffer arcs per quarter circle. Chord error is r*(1-cos(pi/32)), about
               # 0.001 mm at r = 0.2 mm, far below a layer. An approximation setting.


class FlatError(ValueError):
    """The selection cannot be made into flat geometry as asked. Nothing is written."""


def mask_outline(mask: np.ndarray) -> shapely.Geometry:
    """Exact pixel-cell outline, in pixel units (x right, y down), as a union of row runs."""


def to_model(outline, width_mm: float) -> tuple[shapely.Geometry, dict]:
    """Scale to width_mm, flip Y, and put the bounding box's lower-left at the origin."""
```

**Tests:**
- **Exact area:** the outline area equals the pixel count, for random masks generated
  with a fixed seed.
- **Hole inside a hole:** a ring holding an island gives two polygons. One has a hole,
  and the island is separate.
- **Asymmetric glyph:** an L shape with its foot at the image's bottom-right keeps its
  foot at model bottom-right (low y, high x). This tests the Y flip.
- **Scale:** the transformed width equals `width_mm` to within 1e-9.
- **Empty mask:** `FlatError("no printable foreground")`.
- Commit.

### Task 4: Cleaning

**Files:** extend `src/tdmg/flat.py` and `tests/test_flat.py`.

```python
def clean(geom_mm, opening_mm, min_island_mm2, sample_step_mm) -> tuple[list[Polygon], dict]:
    """Open by opening_mm (round joins, QUAD_SEGS); split into polygons; drop small parts.

    Returns the parts, largest first, and the report described in the behaviour contract
    (original plan: a single hausdorff_mm and a dropped_islands list; see Execution notes).
    """
```

Extract polygons from any Polygon, MultiPolygon or GeometryCollection, recursively. That
handles the multi-part repair results reported in the stack-smoke review. Order the parts
deterministically: by area descending, then by the bounds tuple.

**Tests:**
- **Diagonal touch:** two squares touching at one corner come out as two parts, with no
  shared vertex.
- **Thin hair:** a 0.2 mm-wide strand attached to a square is removed, and
  `removed_area_mm2 > 0`.
- **Islands:** a speck smaller than the island area is dropped and reported; a larger
  one is kept.
- The report's numbers are plain Python floats.
- Commit.

### Task 5: Extrusion

**Files:** extend `src/tdmg/flat.py` and `tests/test_flat.py`.

```python
def extrude(parts: list[Polygon], thickness_mm: float) -> trimesh.Trimesh:
    """manifold3d extrusion of oriented rings (FillRule.Positive). Raises FlatError if empty."""
```

**Tests:**
- **Volume:** a hypothesis property test. For a random axis-aligned rectangle with a
  rectangular hole, the volume equals area × thickness within 1e-6 relative error.
- **Multiple parts:** two parts give two bodies.
- **Topology:** every F1 check from Task 2 passes on the result.
- **Repeatability:** the same input gives identical vertex and face arrays in one process.
- Commit.

### Task 6: Thin-region measurement and the remaining checks

**Files:** extend `checks.py` (or `src/tdmg/flat.py` for the flat-specific parts) and the tests.

- `thin_regions(parts, min_width_mm) -> dict`: the area of `union(parts) − opening(union,
  min_width_mm)`, its number of pieces, and the centroids of the largest five, in mm.
  Exposed as `F3.thin_regions`: status UNKNOWN, with the measurement, threshold
  `fdm.wall.min_thickness`, and the note "tapered tips always appear; pass/fail policy
  pending research on slicer handling of narrow features".
- **F2 checks:**
  - `F2.fits_build_volume`: extents ≤ the printer profile's `build_volume_mm`. PASS or
    FAIL.
  - `F2.target_width`: PASS if the transform scale × mask width equals the requested
    width. The note gives the final extents after cleaning.
- **`F4.body_count`:** PASS when there is 1 body. With more than one, UNKNOWN, with the
  note "separate pieces print loose; join them or accept". Whether several bodies are
  intended is the user's call.
- **`F5.triangles`:** ≤ `slicer.orca.max_triangles_per_plate`.
- **`F6.slicer`:** always UNKNOWN, "no slicer integration yet".
- The required set for this plan is all of F1, F2, F3, F4, F5 and F6.
- Commit.

### Task 7: Run from a selection folder and write outputs

**Files:** extend `src/tdmg/flat.py` and the tests.

```python
FLAT_ALGORITHM_VERSION = "flat-1"
RECORD_SCHEMA = "tdmg.flat/1"

def make_flat(selection_dir, width_mm, thickness_mm, out_dir, printer="bambu-a1") -> dict:
```

**Steps:**
1. Validate that width and thickness are finite and > 0 (`FlatError`).
2. Load and verify the selection (see the behaviour contract). Load the printer profile
   and the rules.
3. Build the outline, transform, clean and extrude.
4. Encode `model.stl` (binary) and `outline.png` in memory. For the preview, rasterise
   the cleaned parts back into the mask's pixel grid with `cv2.fillPoly`, using the
   inverse transform. Colour kept pixels grey (128), mask pixels lost to cleaning red
   (220, 40, 40), and everything else white. These are display constants.
5. Gate: parse the in-memory STL bytes back with trimesh, run `merge_exact`, then all
   checks. The gate therefore judges exactly the bytes that will be written.
6. Build the record and `flat_id`, then write it all with `records.write_outputs`.

**Tests:**
- **On `roadie_like()`**, selected with the standard spec into `tmp_path`:
  - a 60 × 3 mm run gives one body;
  - every F1 check passes;
  - the verdict is NOT CERTIFIED, with F3 and F6 UNKNOWN;
  - the files exist, and `out/flat.json` is canonical with LF endings;
  - the STL read back from disk equals the gated bytes.
- **Errors:** a tampered `mask.png`, where one pixel is flipped and the hash no longer
  matches, gives `FlatError` and nothing written. So does a missing `selection.json`.
- **Repeat runs:** the same inputs give byte-identical files and the same `flat_id`. A
  different thickness gives a different `flat_id`.
- **Golden:** pin the `flat_id` for the `roadie_like` 60 × 3 mm run.
- Commit.

### Task 8: `tdmg flat` command

**Files:** `src/tdmg/cli.py` and `tests/test_cli.py`.

Wire it up as described in the behaviour contract, following the `select` command's
error handling. Tests:
- a successful run on the fixture;
- missing `--width-mm` gives a usage error;
- `--thickness-mm 0` exits 2;
- a non-selection folder exits 2;
- all tests also pass with `CI=true GITHUB_ACTIONS=true`.

Commit.

### Task 9: Local run on the owner's selections (not in CI)

**Owner input needed first:** the width and thickness for the first Roadie and Oddie
prints.

For guidance: Roadie's legs are about 15–20 px wide in its 599 px-wide mask. So at 60 mm
they are about 1.5–2 mm, and at 40 mm about 1.0–1.3 mm. The minimum wall rule
`fdm.wall.min_thickness` is 0.9 mm.

Run `tdmg flat` on `artifacts/selection-runs/roadie-tol30` and `oddie`. Check repeat runs
are byte-identical, view `outline.png`, and record the results in a new section of
`research/verification/2026-11-10-subject-selection/README.md`, or in a new record
folder. The owner opens `model.stl` in Bambu Studio and reports whether it imports at the
expected size. That is a manual import check, not F6.

### Task 10: Docs, status and review

- **Docs:**
  - `docs/print-types/attributes/geometry-flat.md`: record the pixel-cell outline choice
    and the transform, and update the failure-mode table's mitigations.
  - `docs/guide/pipeline-and-gate.md`: mention `tdmg flat`.
  - `README.md` and `docs/STATUS.md`: update.
- Run `scripts/gen_docs.py`, the full suite (both environments) and ruff.
- Get an independent Codex review, then record and handle its findings.
- Push only with the owner's go-ahead, and check that CI passes on all three operating
  systems.

## Out of scope

- A keychain loop or base plate (R1 features).
- 3MF output with a UUID identity scheme.
- An F3 pass/fail policy.
- Slicer integration (F6) and installing OrcaSlicer.
- Outline smoothing.
- A cookie-cutter variant.
- Physical prints and caliper checks.

## Execution notes

- **Tasks 3–5, quality review (2026-11-10):**
  - **The Hausdorff measurement was wrong.** GEOS `hausdorff_distance` without
    densifying checks only vertices. On a bar joining two blobs it reported 0.083 mm
    where the true value is 1.63 mm. This was reproduced.
  - **Replacement:** a two-sided distance sampled on the boundaries at a quarter-pixel
    step, `boundary_hausdorff_mm`. It is a lower bound, accurate to within half a step.
  - **Upper bound:** `hausdorff_upper_bound_mm` adds half a step, plus the larger of
    opening/2 and the radius of the largest dropped island, plus the buffer chord
    error. A dropped island can be fatter than opening/2; the review gave a measured
    counterexample to the narrower bound.
  - **Other changes:**
    - islands that the opening erased entirely are reported as `vanished_parts`;
    - the report has a fixed key set;
    - `opening_mm` must be above 0, because corner separation depends on it;
    - masks must be bool or 0/255 integers.
- **Speed: accepted as a known limit, with no size rule yet.**
  - On the owner's masks, cleaning takes a fraction of a second.
  - On synthetic stress masks, after the fixes, `clean` took 26 s for 1000 × 1000 random
    blobs (from 251 s) and 27 s for a 4000 × 4000 noisy circle (from 41 s). Shapely's
    negative buffer dominates.
  - An input-size rule with evidence is deferred until a real input needs it.
- **Tasks 6–8:**
  - **Rasterising:** the outline preview tests pixel centres with shapely's exact
    `contains_xy`, not `cv2.fillPoly`. That is exact for pixel-cell outlines.
  - **Printer id:** it lives in `params` only.
  - **Inputs:** non-numeric inputs are refused.
  - **Gate FAIL:** a failing check still writes all files, carrying the verdict.
  - **Exit codes:** `tdmg flat` exits 0 when no check failed, 1 when a check failed
    (files written), and 2 on input errors (nothing written). The help text says exit 0
    does not mean certified.
- **Task 9:** see `research/verification/2026-11-10-flat-geometry/README.md`. Roadie and
  Oddie at 60 × 3 mm each give one body, pass every F1, F2, F4 and F5 check, are NOT
  CERTIFIED only through F3 and F6, and repeat byte for byte.
- **Codex review** (`research/reviews/2026-11-10-flat/`) led to:
  - a new check, `F2.export_matches_geometry`, so the size checks judge the written
    mesh;
  - verification of the selection's identity;
  - a measured note that cleaning removes features up to the opening width plus about
    0.005% of it, because the erosion collapses numerically there;
  - honest wording for exit code 2 and for what cleaning removes.

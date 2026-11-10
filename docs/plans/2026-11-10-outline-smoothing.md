# Outline smoothing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** smooth the jagged outlines of soft or low-resolution images before `tdmg flat`
extrudes them. Smoothing is a standalone module that can be called on its own. It is on
by default in `tdmg flat`, and `--smooth-px 0` turns it off.

**Why:** the owner imported the 60 × 3 mm Roadie into Bambu Studio and found its border
"very jagged", although it is a cartoon. The candidates were measured in
`research/verification/2026-11-10-outline-smoothing/`. The chosen method blurs the
binary mask with a Gaussian (σ = 2.5 px) and takes the 0.5 iso-contour with contourpy.

**Owner decisions (2026-11-10):**
- smoothing comes before the slicer plan;
- it is an optional, standalone module, because not every image needs it;
- it is on by default and can be turned off.

**Architecture:**
- **New module** `src/tdmg/smoothing.py`, with a pure function
  `smooth_outline(mask, sigma_px)`. It returns a Shapely geometry in the same pixel-cell
  coordinates as `tdmg.flat.mask_outline` (x right, y down; pixel c spans [c, c + 1]), so
  `tdmg.flat.to_model` applies unchanged.
- **New rule:** `flat.smooth.sigma_px` sets the default.
- **`make_flat` and the CLI:** they take `smooth_px`, where None means the rule default
  and 0 means the exact pixel outline. The record gets a `smoothing` section.
- **Version bump:** the default output changes, so `FLAT_ALGORITHM_VERSION` becomes
  `flat-2`.

**Tech stack:** contourpy (new core dependency, BSD-3-Clause, Windows/macOS/Linux
wheels), OpenCV `GaussianBlur`, and Shapely.

**Conventions:** the same as the flat plan.
- Imports go at the top. Lines are ≤ 100 characters (check with awk).
- Files use LF endings.
- Write edit scripts as files, not heredocs with escapes.
- Every commit ends with the trailer.
- Work test-first, never weaken an assertion, and run both test environments.

**Status:** written and executed 2026-11-10; see "Execution notes".

## Decisions

1. **Method:** a Gaussian blur of the binary mask, with zero (constant) borders so the
   foreground never reflects at an image edge. Then a filled iso-contour at level 0.5,
   from contourpy with `FillType.OuterOffset`.
   - Level 0.5 is the midpoint between background and foreground. It keeps a long
     straight edge where it was. This is a property of a symmetric blur, not a tuned
     threshold. A test checks it.
   - Pad the field by one zero pixel so every contour closes. Then translate by −0.5 px
     to map onto pixel-cell coordinates (see the record).
2. **Rule:** `flat.smooth.sigma_px`, kind `hypothesis`, unit px, default 2.5, with no
   range. Evidence: the smoothing record, with locator "candidate A at σ 2.5 px gave the
   smoothest, most cartoon-like outline". Validation `untested`.
   - The value is chosen in pixels, because the raggedness comes from the image's
     resolution and compression, not from the print size.
   - The code requires σ > 0 and finite. Callers that want no smoothing don't call the
     function.
3. **What it does to the outline:**
   - It removes boundary noise and specks smaller than about σ, and fills small notches.
   - It rounds real corners on a scale of about σ.
   - It can merge parts closer than about σ, or split parts joined by a neck thinner than
     about σ.
   The record measures these effects; nothing hides them.
4. **What the record reports:** `smoothing` {applied (bool), sigma_px {value, rule},
   method, area_change_px2, boundary_hausdorff_px (the sampled two-sided distance from
   the exact pixel outline), parts_before, parts_after}.
   - When smoothing is off: `applied: false`, with the other measurements null or
     absent. Pick one and pin it with a test.
   - `cleaning` and the gate run on the smoothed outline, unchanged.
5. **outline.png:**
   - grey: kept, inside both the mask and the final shape;
   - red: mask pixels that are not in the final shape (removed by smoothing or cleaning);
   - blue (40, 90, 220): pixels outside the mask that are in the final shape (added by
     smoothing).
   These are display constants, and the review text explains the colours.
6. **Identity:** `params` gains `smoothing` {sigma_px {value, rule}}, so `flat_id`
   changes. Bump `FLAT_ALGORITHM_VERSION` to `flat-2` and re-pin the golden id, with a
   comment.

## Tasks

### Task 1: Dependency and rule
- Run `uv add contourpy` (pin as uv resolves it; check the lock updates). Add a row to
  `docs/reference/dependencies.md`: version, licence (BSD-3-Clause, checked from the
  installed package metadata), role "iso-contours for outline smoothing", state
  "imported" on the PC.
- Add `flat.smooth.sigma_px` to `rules/geometry-flat.yaml` (Decision 2). Check that the
  locator text exists verbatim. Run `scripts/gen_docs.py`.
- Test: the rule loads with unit px and default 2.5.
- Commit.

### Task 2: `smoothing.py`
`smooth_outline(mask: np.ndarray, sigma_px: float) -> shapely.Geometry`. The mask must be
bool or 0/255 integers, as for `tdmg.flat.mask_outline`; reuse that validation. An empty
result raises `SmoothingError(ValueError)`. The docstring states the method, the
coordinate convention and the effects in Decision 3.

Tests, written first:
- A large axis-aligned square keeps its straight edge positions within 1e-3 px at the
  edge midpoints. Its corners are rounded, with the area loss reported.
- A one-pixel speck next to a large body is removed. A notch one pixel wide is filled.
- A diagonal staircase edge comes out smooth: its perimeter is within 2% of the true
  Euclidean length, while the exact pixel outline is about 41% longer.
- A ring keeps its hole.
- Coordinates: on a large disc, `smooth_outline` and `tdmg.flat.mask_outline` agree within
  1 px (sampled Hausdorff). This catches a half-pixel offset.
- A foreground touching the image border still gives a closed, valid polygon.
- The function is deterministic, in process and across two subprocess runs.
- σ ≤ 0, non-finite σ, and non-binary masks raise. An all-background mask raises
  `SmoothingError`.

Commit.

### Task 3: Use it in `make_flat` and the CLI
- `make_flat(..., smooth_px=None)`: None means the rule default; 0 means off; anything
  else must be finite and > 0.
- When on, build the outline with `smooth_outline`; when off, with `mask_outline`.
- Then `to_model` and the rest, unchanged.
- Add the `smoothing` record section and params (Decisions 4 and 6), the outline.png
  colours (Decision 5) and the version bump. Add contourpy to the recorded
  `environment`.
- CLI: `--smooth-px FLOAT`, with help "Gaussian smoothing of the outline in image
  pixels; default from rule flat.smooth.sigma_px; 0 keeps the exact pixel outline". The
  output prints whether smoothing was applied and its boundary change.
- Tests:
  - default, off and explicit runs;
  - off gives the same geometry as before (the old exact-outline path);
  - smoothing on `roadie_like()` gives a shorter perimeter than off and passes every F1
    check;
  - blue pixels appear in outline.png when smoothing adds area;
  - the record keys are pinned;
  - the golden id is re-pinned;
  - the CLI flag, including `--smooth-px 0` and `--smooth-px -1` (exit 2).
- Commit.

### Task 4: Run on the owner's selections
- Re-run Roadie and Oddie at 60 × 3 mm with the default smoothing, into new folders,
  twice each to check repeatability.
- Record in the smoothing record: perimeters, the area change, the Hausdorff from the
  exact outline, the export check, and the verdicts.
- Look at outline.png, especially Oddie's sharp leaf tips.
- The owner re-imports them into Bambu Studio and judges whether the edges are smooth
  enough.

### Task 5: Docs, status and review
- Update the G1 attribute page (smoothing step; failure modes: corners rounded, necks
  thinner than σ split), the pipeline guide, the README and STATUS. Run `gen_docs`.
- Get an independent Codex review and record how each finding was handled.
- Push, and confirm that CI passes on all three operating systems.

## Out of scope
- Choosing σ automatically per image.
- Smoothing for other recipes (relief, R4).
- An F3 policy, and slicer integration.

## Execution notes

- **Task 1** was done by the controller: contourpy 1.4.0 was added, along with the rule
  `flat.smooth.sigma_px`. The sliver rule's summary no longer claims impossibility.
- **Pad before blurring.** Tasks 2 and 3 pad the mask before blurring, the reverse of
  the prototype's order. Padding afterwards put an exact zero next to a border pixel,
  which moved an image-border edge 0.36 px inward. The reviewer confirmed this by
  measurement.
- **Record semantics after review:**
  - the area change is two-way (removed and added, as well as the net);
  - part and hole counts are compared after cleaning on both paths;
  - the boundary distance is a sampled lower bound, measured between the cleaned
    geometries.
- **Warnings.** The first warning design flagged ordinary corner rounding. Warnings now
  fire only on topology changes: parts merged, split, disappeared or appeared, or holes
  closed or opened. Changed regions are recorded as information. A thin attached
  appendage removed without a topology change is not warned about. This is documented.
- **Off path:** with smoothing off, `tdmg flat` reproduces the flat-1 STL byte for byte,
  and a test pins its sha256.
- **Task 4:** see the smoothing record. Roadie and Oddie at 60 × 3 mm each give one body,
  no warnings, and repeat byte for byte.
- **Codex review** (`research/reviews/2026-11-10-smoothing/`). Warnings now come from
  part-to-part correspondence, so offsetting merges, splits and hole changes are
  caught. The distance is described as boundary-to-region (`hausdorff_lower_bound_px`).

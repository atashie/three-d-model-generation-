# Design note: flat geometry and outline smoothing (`tdmg flat`)

Stages S2 to S4 and S8 for R1: turn a reviewed selection into a flat solid of a chosen
width and thickness, and gate the written STL. The multicolor version
(`tdmg flat --colors`) is in [color.md](color.md).

## Decisions in force

- **Size and thickness are the user's choice,** required flags with no defaults
  (`--width-mm`, `--thickness-mm`); they are job parameters, not rules. The owner's
  first size: 60 mm wide, 3 mm thick, for Roadie and Oddie (2026-11-10).
- **The width applies to the selection:** scale = width / mask width in pixels, exactly.
  Cleaning may then make the solid a little narrower (Roadie: 0.37 mm, mostly spike
  tips, at flat-1). The record reports the final extents and the change; the width is
  never silently re-fitted.
- **Transform:** `x_mm = (x_px − x0)·s`, `y_mm = (y1 − y_px)·s`. Model +Y is image up; the
  lower-left of the mask's bounding box sits at the origin.
- **Outline: smoothed by default, exact on request.** Replaced "exact pixel-cell outline,
  smoothing out of scope" on 2026-11-10, after the owner found Roadie's border "very
  jagged". Owner decisions (2026-11-10): smoothing before the slicer work; a standalone
  module, because not every image needs it; on by default, `--smooth-px 0` turns it off.
  Method: Gaussian blur of the mask (σ = `flat.smooth.sigma_px`, 2.5 px, a hypothesis),
  padded before blurring, then the 0.5 iso-contour with contourpy.
- **The blur is float64** (owner, 2026-11-11: "fix it now"; algorithm `flat-3`). With
  float32 the last bits depended on OpenCV's code path. Float64 is the same both ways on
  the PC; that two machines give identical bits is not shown.
- **Smoothing warns only on topology changes:** parts merged, split, appeared or
  disappeared, holes closed or opened, found by part-to-part correspondence. Ordinary
  corner rounding is information. A thin attached appendage removed with no topology
  change is not warned about (documented limit).
- **Cleaning** uses existing rules (`flat.sliver.opening_width`,
  `flat.island.min_square_side`, both untested hypotheses). It is described as "removed by
  the cleaning rules", never as physically unprintable. Every removed island is reported.
- **Extrusion uses manifold3d** with oriented rings, so the triangulation engine is named.
- **The gate runs on the written file:** `model.stl` is read back before the checks.
  `F3.thin_regions` is information only; thin features are judged from the G-code by
  `tdmg slice` ([slicing.md](slicing.md)).
- **Exit codes:** 0 no check failed, 1 a check failed (files written), 2 input or setup
  error. A folder without `out/flat.json` is incomplete, because an I/O failure can happen
  in the middle of a write.
- **Roadie's roughness (open):** the owner said "oddie is perfect, roadie is close but
  still a bit too rough. But this is fine for now" (2026-11-10). Options, untested: a
  per-image `--smooth-px`, or a better source image.

## Review findings that still constrain the code

- **The size checks judge the written mesh:** `F2.export_matches_geometry` compares the
  reloaded STL's bounds, z range and volume with the cleaned geometry, with float32
  tolerances (Codex review of `tdmg flat`, 2026-11-10, finding 1; removed record).
  It checks only bounds and volume, not shape (still open, see
  [`research/reviews/2026-11-12-color-geometry/`](../../research/reviews/2026-11-12-color-geometry/README.md), "Not fixed").
- **The selection record is checked, not trusted:** `make_flat` validates the schema and
  recomputes `selection_id` with `selection.selection_identity` (same review, finding 3).
- **Collapse at the opening width:** cleaning removes features up to the opening width
  plus about 0.005% of it (2e-5 mm at 0.4 mm), because the erosion collapses
  numerically there. Documented and pinned by tests; the algorithm is unchanged (same
  review, finding 2).
- **`WIDTH_RTOL`** is a floating-point margin for a computed equality, derived in the
  comment in `src/tdmg/flat.py`, not a physical tolerance (same review, finding 7).
- **The smoothing distance is a lower bound,** boundary-to-region
  (`hausdorff_lower_bound_px`), not a boundary-to-boundary Hausdorff distance (Codex
  review of smoothing, 2026-11-10, finding 1; removed record).

## Records and plans

- Plans: [`2026-11-10-flat-geometry.md`](../plans/2026-11-10-flat-geometry.md) and
  [`2026-11-10-outline-smoothing.md`](../plans/2026-11-10-outline-smoothing.md)
  (decisions and execution notes, including the Hausdorff fix and the speed limits).
- Smoothing measurements and the first physical print (Roadie, "it looks great", by
  eye): [`research/verification/2026-11-10-outline-smoothing/`](../../research/verification/2026-11-10-outline-smoothing/README.md).
- Float64 blur decision: [`research/reviews/2026-11-11-color-palette/`](../../research/reviews/2026-11-11-color-palette/README.md),
  "Owner decision: float64 blur (flat-3)".
- Repeat runs of the whole pipeline: [`research/verification/2026-11-16-repeatability/`](../../research/verification/2026-11-16-repeatability/README.md).

## Removed records

All three were removed in commit `814a962723454efa7693b8ef8af715062368975a` (see git
history, or tag `pre-restructure`).

- `research/reviews/2026-11-10-flat/`: Codex review of `tdmg flat`
  (`94df84a..a3f1978`), 7 findings, all confirmed and handled. Findings 1, 2, 3 and 7:
  above. Finding 4 (exit 2 promised "nothing written"): the exit-code decision above.
  Finding 5 (cleaning presented as physical fact): the cleaning decision above. Both
  are also in the plan's execution notes. Finding 6 (STATUS stale): obsolete. "468
  tests pass; re-runs byte-identical": a point-in-time result, obsolete.
- `research/reviews/2026-11-10-smoothing/`: Codex review of smoothing
  (`8d66458..d757132`), 4 findings, all confirmed and fixed in `070b1f2`. Finding 1:
  above. Finding 2 (offsetting topology changes escaped the totals): the warnings
  decision above and the plan's execution notes. Finding 3 (a lower bound read as a
  maximum): the correction note in the kept smoothing record. Finding 4 (the G1 page
  called the exact outline the default): fixed in
  [`geometry-flat.md`](../print-types/attributes/geometry-flat.md).
- `research/verification/2026-11-10-flat-geometry/`: the first `tdmg flat` runs on the
  owner's selections at 60 × 3 mm (commit `60f95da`, flat-1, exact outline). Both NOT
  CERTIFIED only through F3 (UNKNOWN by design) and F6 (no slicer then); every F1, F2,
  F4 and F5 check passed; repeat runs byte-identical; triangle counts and Roadie's
  1.19% removed area matched the planning prototype (also in the plan). Roadie 59.63 ×
  49.01 × 3.00 mm, 37,148 triangles, STL `70ef41cf…a925fa`; Oddie 59.75 × 65.63 × 3.00 mm,
  33,248 triangles, STL `63006bfa…88296e`. After the review fixes (`f2367af`) the export
  check passed on both, STLs unchanged. The many tiny thin regions came from pixel
  staircase corners; F3 is now judged from the G-code instead. These outputs are
  superseded by the smoothed `flat-2` and `flat-3` runs, so the numbers are history.
  The pending Bambu Studio import it listed was done (smoothing record, first lines).

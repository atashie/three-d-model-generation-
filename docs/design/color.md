# Design note: color for flat prints (R2: `tdmg colors`, `tdmg flat --colors`, 3MF)

R2 turns a selection into a reviewed color plan (`tdmg colors`), then into gated bodies
(`tdmg flat SELECTION --colors PLAN`): one multicolor `model.3mf` for the AMS (the
automatic filament changer), and a glue-together version (a base with pockets, plus
loose pieces). Slicing the result is in [slicing.md](slicing.md); the test strips are
in [calibration.md](calibration.md).

## Decisions in force

**The overall design** (owner, 2026-11-11, agreed section by section;
[color design](../plans/2026-11-11-color-design.md)):
- **Colors only in a top skin:** 0.6 mm (three 0.2 mm layers) on a one-color base. For 4
  colors that is at most 9 color changes, not 45. Full-thickness and stepped colors were
  set aside.
- **Palette suggested from the image;** the user assigns spools in the slicer. This
  replaces, for now, PLAN section 11's "palette snapped to the job's filament colors".
- **Glue route: inlays in pockets.** Tiny regions are merged for glue only; the AMS
  version keeps every region the slicer can print.
- **Review before geometry:** the owner checks `regions.png` before any solid is built.
- **A reusable module steered by a strict config file** of named keys. Words such as
  "smooth" or "furry" are named presets, never interpreted at runtime (CLAUDE.md rule 1).
  Unknown keys or values are refused.
- **At most 4 filaments** by default (the AMS lite's slots, PLAN Q1); a job declares its
  real cap.

**The color plan** ([palette plan](../plans/2026-11-11-color-palette.md); owner
answers verbatim in [the palette record](../../research/verification/2026-11-11-color-palette/README.md)
addenda):
- **Palette:** deterministic k-means in CIELAB with greedy, count-weighted seeding
  (measured better than median cut). Its known cost: a small salient color can get no
  slot at low counts.
- **Extract 6 colors by default** (owner, 2026-11-11: "Extract 6 by default
  (Recommended)").
- **Smooth edges by default** (owner, Task 7, 2026-11-11).
- **Cartoon outlines dropped by default;** `keep` redraws the drawing's own lines as a
  uniform band, default 0.5 mm (`color.outline.keep_width`). The owner asked for "a
  touch finer (0.4 mm?)"; 0.4 mm equals the cleaning opening and would be removed, and
  0.45 mm lost 13.6% / 28.6% of the band, so 0.5 mm (controller, measured, 2026-11-11).
- **Only pupil-like dark areas survive a drop** (owner: "Keep wide areas
  (Recommended)"; then only Roadie's pupil, not feather tips or shading). Rule
  `color.outline.keep_area_width_ratio`, from one example.
- **Shade pairs are flagged, never merged automatically.** The owner merges by index in
  the config (`merge`). Too many colors left: the plan is written with `ready: false`,
  exit 1, and merges are suggested. Outlines, shading and merges are explicit options,
  never side effects of cleanup.
- **Holes in the subject are filled by default** (`holes: fill | keep`).
- **`verify_colors` rebuilds the plan** from the selection and requires identical labels
  and record, today's rule values and a color count within the printer's cap. A plan
  made on another machine is refused if the results differ.
- The owner approved the four previews: "amazing work. 1-4 are great, well done."
  (2026-11-11). Oddie preferred with the outline kept and both shade pairs merged.

**The colored solids** ([geometry plan](../plans/2026-11-12-color-geometry.md),
approved 2026-11-12, "approved"):
- **Starting values,** confirmed by the owner: `color.skin.depth_mm` 0.6 (calibrated
  since 2026-11-15, see [calibration.md](calibration.md)), `color.glue.clearance_mm` 0.2
  per side and `color.glue.min_piece_side_mm` 2.0 (both untested hypotheses).
- **"Match preview":** inlays are not cleaned; the solids are exactly the approved
  preview (owner, 2026-11-12). Per-inlay trimming drew base-colored hairlines.
- **"Fold small pieces too":** in the glue version, glue pieces below the minimum fold
  into the base, so thin outline bands mostly vanish there (owner, 2026-11-12).
- **No glue version for a plan that keeps a drawn outline.** Owner, verbatim: "for the
  glued-together versions of our images let's make sure to not add teh outline - that
  would be unrealistic to glue on" (2026-11-12).
- **`--smooth-px` with `--colors` is refused,** and the width must equal the plan's
  `width_mm`.
- **Bodies are meshed directly on a float32-exact grid,** not by 3-D unions: manifold3d
  unions failed F1 after STL storage on 3 of 4 plans.

**The multicolor 3MF** ([3MF plan](../plans/2026-11-12-color-3mf.md), approved
2026-11-12):
- **Encoding D:** one mesh object with one closed shell per color, each triangle colored,
  core spec and Materials only, no UUIDs, byte-identical on repeat. Separate objects are
  dropped to the bed by both slicer CLIs, and PrusaSlicer crashes on them. The owner's
  Bambu Studio check of the hand-made files: "A and D had all colors in place".
- **`palette.json` is the guarantee;** it names colors, never AMS slots.
- The owner opened the real Roadie `model.3mf` in Bambu Studio: "1) yes. 2) yes. 3) yes"
  (in place, filaments assignable, it slices). The owner assigns filaments there.

## Review findings that still constrain the code

- `verify_colors` must rebuild, not just re-hash. Before the fix, a plan could be made
  "ready" above the printer's cap, a hand-edited `labels.png` passed, an invalid base
  index passed, and a ready plan could be refused by its own verifier
  ([`research/reviews/2026-11-11-color-palette/`](../../research/reviews/2026-11-11-color-palette/README.md), findings 1 to 4).
- Each decoded STL body is cut at the mid-height of each slab, and the section must equal
  the body's footprint (before, a body moved 1 mm inside its bounds passed). The glue
  clearance is guaranteed by construction, not by a guessed margin (`colorflat-2`)
  ([`research/reviews/2026-11-12-color-geometry/`](../../research/reviews/2026-11-12-color-geometry/README.md)).
- The 3MF check also checks the zip's raw part names, its package files and the exact
  build transform; a corrupt zip FAILs instead of raising
  ([`research/reviews/2026-11-12-color-3mf/`](../../research/reviews/2026-11-12-color-3mf/README.md)).

## Still open

- Geometry is not bit-identical across platforms at the rounding level (macOS arm64 GEOS
  differs); `colored.json` does not record the platform.
- PrusaSlicer's 3MF volume differs from the palette sum by −1.23 to +0.25 mm³, not
  explained.
- The color rules rest on two images; only 4-color plans are measured.

## Records

- [`research/verification/2026-11-11-color-palette/`](../../research/verification/2026-11-11-color-palette/README.md),
  [`2026-11-12-color-geometry/`](../../research/verification/2026-11-12-color-geometry/README.md),
  [`2026-11-12-color-3mf/`](../../research/verification/2026-11-12-color-3mf/README.md).
- Docs: [color-multi](../print-types/attributes/color-multi.md) and "Color plans" in the
  [pipeline guide](../guide/pipeline-and-gate.md).

## Removed records

None of the five records removed in commit `814a962723454efa7693b8ef8af715062368975a`
covered color.

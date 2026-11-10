# `tdmg flat` on the owner's selections, 2026-11-10

**Purpose:** Task 9 of `docs/plans/2026-11-10-flat-geometry.md`. It makes the first flat
solids from the owner-approved selections in `artifacts/selection-runs/`, at the owner's
chosen size of 60 mm wide and 3 mm thick. These are software results only. Nothing was
sliced or printed.

**Environment:** the Windows PC described in `docs/STATUS.md`, with the core `.venv` at
commit `60f95da`. The outputs are in `artifacts/flat-runs/`, which Git ignores because
they derive from the owner's images.

**Command**, run twice for each selection into new folders `-a` and `-b`:

    uv run tdmg flat artifacts/selection-runs/<selection> --width-mm 60 --thickness-mm 3 \
      --out artifacts/flat-runs/<selection>-60x3-<a|b>

| Selection | Verdict | Extents (mm) | Triangles | Bodies | Thin regions < 0.9 mm | flat_id (first 12) |
|---|---|---|---:|---:|---|---|
| roadie-tol30 | NOT CERTIFIED | 59.63 × 49.01 × 3.00 | 37,148 | 1 | 10.67 mm² in 1,087 pieces | 244dda139b5a |
| oddie | NOT CERTIFIED | 59.75 × 65.63 × 3.00 | 33,248 | 1 | 3.00 mm² in 1,107 pieces | 500d3a803067 |

- **Checks:** every F1 topology check, both F2 checks, F4 and F5 passed for both.
- **Why NOT CERTIFIED:** both verdicts were held back only by F3 (thin regions:
  UNKNOWN by design until a pass/fail policy exists) and F6 (no slicer yet). The exit
  code was 0 for both.
- **Repeatability:** the two runs gave byte-identical `model.stl`, `outline.png` and
  `flat.json` for each selection. This was checked within one environment on one
  machine.
- **STL SHA-256:**
  - roadie `70ef41cf9cbed35b6fa7d50198d48c2e3f4743c1bd586e260325497f57a925fa`
  - oddie `63006bfa020913debbe6ff2229a0c28d5c801fb68e95af0940e378e0a788296e`
- **Match with the prototype:** the triangle counts and Roadie's 1.19% removed area
  match the planning prototype exactly.
- **Width:** the requested 60 mm applies to the selection, so cleaning made the solids
  slightly narrower: Roadie by 0.37 mm, mostly at its spike tips. The record reports
  this rather than re-fitting (plan, decision 3).
- **Thin-region count:** it is high because every convex staircase corner of the
  pixel outline contributes a tiny piece. Any future F3 policy must deal with this.

## Not verified here

- **Bambu Studio import:** the owner's import of `model.stl` (pending; size and
  appearance to be reported).
- **Slicing:** with any slicer (F6).
- **Printing:** physical prints and caliper measurements.

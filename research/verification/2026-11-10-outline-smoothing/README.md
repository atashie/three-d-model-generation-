# Outline smoothing candidates, 2026-11-10

**Trigger:** the owner imported `artifacts/flat-runs/*-60x3-a/model.stl` into Bambu Studio
on 2026-11-10. Both imported properly, as one piece at the expected size. But "especially
Roadie has very jagged edges / a very jagged border, where as a cartoony image it should
be smoother."

**Diagnosis:** enlarged crops of `roadie.png` beside its selected mask were compared by
eye. The source bird is only about 600 px wide, and its edges are soft and compressed.
The mask boundary is ragged 2–3 px deep, on top of the one-pixel staircase of the exact
pixel-cell outline. At 60 mm width, one pixel is 0.1002 mm.

**Method:** `smooth_proto.py` → `roadie-results.txt`, run on the Windows PC at commit
`278639b`. It uses the owner-approved mask `artifacts/selection-runs/roadie-tol30/mask.png`
at a 60 mm width. "Hausdorff vs mask" is the repository's sampled two-sided distance
from the unsmoothed pixel-cell outline. The enlarged comparison sheet is
`artifacts/flat-runs/smoothing-comparison.png`. It is not committed, because it derives
from the owner's image.

| Candidate | Area change | Perimeter (mm) | Vertices | Hausdorff vs mask (mm) | Visual |
|---|---:|---:|---:|---:|---|
| Current: opening 0.4 mm only | −1.19% | 377.7 | 9,289 | 0.533 | ragged |
| A: Gaussian blur σ 1.5 px, 4× upsample, threshold 0.5, then opening | −0.38% | 350.6 | 16,751 | 0.472 | mostly smooth, slight ripple |
| A: same with σ 2.5 px | −0.43% | 342.0 | 16,505 | 0.572 | smooth; crest spikes and beak kept |
| C: closing then opening, r 0.25 mm | +1.11% | 354.6 | 10,415 | 0.575 | still bumpy |
| C: closing then opening, r 0.4 mm | +1.27% | 335.2 | 6,850 | 1.409 | bumpy; tips bloated |
| D: Douglas–Peucker 0.1 mm + 3 Chaikin passes | −1.52% | 347.8 | 3,289 | 0.585 | fairly smooth, slight wobble, more tip loss |

**Reading:**
- **Perimeter:** a shorter perimeter for a similar area means less raggedness.
- **Best by eye:** candidate A at σ 2.5 px gave the smoothest, most cartoon-like outline
  and kept the features.
- **What it changes:** it removes boundary noise a few pixels deep, and the 4×
  upsampling reduces the staircase to 0.025 mm.
- **Trade-off:** real sharp corners are rounded on a scale of about σ, so a crisp logo
  would be softened.

## Limits

- **Coverage:** one image, judged by eye on two crops.
- **Oddie:** not measured. It comes from a cleaner, higher-resolution source with sharp
  leaf tips.
- **Printing:** no print or slicer preview compared the candidates.
- **Choice of σ:** the values describe this image's noise; nothing shows they are right
  for other images.

## How to trace the smoothed field: contourpy against 4× upsampling

The run used `contour_proto.py` → `contour-results.txt`, with
`uv run --with contourpy` (contourpy 1.4.0, BSD-3-Clause) and σ = 2.5 px on the same
Roadie mask.

| Method | Time | Traced peak | Area (px²) | Perimeter (px) | Vertices |
|---|---:|---:|---:|---:|---:|
| Upsample 4×, threshold 0.5, pixel-cell outline | 0.19 s | 53 MiB | 74,731.2 | 4,357.0 | 10,295 |
| contourpy filled iso-contour at 0.5 | 0.01 s | 19 MiB | 74,730.8 | 3,399.1 | 4,359 |

- **Agreement:** the two outlines agree to within 0.187 px (sampled two-sided
  Hausdorff), which is the upsample's quarter-pixel staircase. The mask area is
  74,768 px.
  - *Correction, same day, after the Codex review in
    `research/reviews/2026-11-10-smoothing/`:* 0.187 px is a sampled **lower bound**
    of the boundary-to-region distance. It is not a proven maximum disagreement. A
    larger difference between samples, or one inside the other region, could exceed
    it. The measurement itself is unchanged.
- **Smoothness:** contourpy gives a smooth outline with no staircase, hence the shorter
  perimeter.
- **Cost:** it needs no upsampled array.
- **Large input:** a synthetic 4000 × 4000 disc with 0.2% random pixel flips took
  about 0.26–0.27 s (two runs) and 444 MiB of traced memory, and gave one valid part.
- **Coordinates:** contourpy treats array index i as a pixel centre. The script pads
  the field with one zero pixel and then subtracts 0.5 px. That maps padded index i to
  the pixel-cell coordinate of pixel i − 1, whose centre is at (i − 1) + 0.5, which is
  the convention `tdmg.flat` uses.

## Implementation run on the owner's selections (Task 4, commit `7f3ad54`)

The command was `uv run tdmg flat artifacts/selection-runs/<sel> --width-mm 60
--thickness-mm 3 --out artifacts/flat-runs/<sel>-60x3-s3`, with the default
`flat.smooth.sigma_px` of 2.5. Both runs exited 0, wrote no warnings and returned NOT
CERTIFIED (F3 and F6 UNKNOWN).

| Selection | Extents (mm) | Triangles | Boundary change (sampled lower bound) | Area removed / added | Parts, holes (exact → smoothed, after cleaning) |
|---|---|---:|---:|---|---|
| roadie-tol30 | 59.97 × 49.40 × 3 | 31,200 | ≥ 0.356 mm | 7.73 / 7.35 mm² | 1 → 1, 0 → 0 |
| oddie | 59.99 × 65.87 × 3 | 29,212 | ≥ 0.149 mm | 2.56 / 2.52 mm² | 1 → 1, 0 → 0 |

- **Repeatability:** the `model.stl` files are byte-identical to the earlier smoothed
  runs (`-s1`, `-s2`), which were themselves byte-identical to each other.
  - roadie sha256 `3d5d260194d75bc048d31e5deb7319a612a86e82700396ac78e515233ef6d653`
  - oddie sha256 `8cc3ca1bbbc787f73296f7dace5e4f928a6de4fbdbd9e24686e96280ec4b160c`
- **What `outline.png` showed:** the changes sit at the spike tips and leaf tips, which
  are shortened by a few pixels, and in narrow crevices, which are slightly filled.
- **Owner's verdict on the smoothed edges in Bambu Studio (2026-11-10):** "oddie is
  perfect, roadie is close but still a bit too rough. But this is fine for now."
  Roadie's remaining roughness is an open item. Options include a per-image sigma
  (`--smooth-px`) or a better source image. Neither has been tested.

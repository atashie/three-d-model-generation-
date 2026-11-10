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

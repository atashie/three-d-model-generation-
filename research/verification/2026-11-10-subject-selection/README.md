# Subject-selection measurements on the owner's images, 2026-11-10

**Purpose:** to choose a deterministic way to keep Roadie's bird and drop its grey
disc before writing the Phase 1 subject-selection plan
(`docs/plans/2026-11-10-subject-selection.md`). These are software measurements on
two images. They are not a selection implementation, and nothing was printed.

**Inputs:** the owner's `Downloads/three-d-test/roadie.png` and `oddie.png` (local, not
in Git; hashes in `input-hashes.txt`). **Environment:** Windows PC, core `.venv`
(`environment.txt`). Every number below comes from the `.txt` output beside the script
that produced it. Re-run with `uv run python -I <script> <image> ...`.

## Image structure (`inspect_imgs.py` → `inspect-images.txt`)

- **Roadie:** 836 × 792 RGBA. Alpha takes only the values 0 and 255. 36.5% of pixels are
  transparent, and these lie outside the disc. The "grey" background is a dark grey-brown,
  about RGB (57, 46, 40). After quantising to steps of 16, it covers 75.8% of the opaque
  pixels. Existing transparency therefore does not isolate the bird.
- **Oddie:** 1024 × 1013 RGBA with soft edges (256 alpha values; 0.6% of pixels partly
  transparent). The background is fully transparent.

## Roadie: colour alone does not separate the bird (`roadie_sep.py` → `roadie-separation.txt`)

Opaque pixels more than 60 RGB units from the disc colour fall into many 8-connected
pieces. The largest are 47,664, 8,124, 6,150 and 2,488 px. Dark lines inside the drawing
cut the feet and shoes off from the body. So "keep the component under a clicked point",
applied to a colour-thresholded mask, would lose the feet.

The bird has no outline that colour can tell apart from the disc. Within 3 px of the
bird, the opaque pixels lie at a median of 27.7 RGB units from the disc colour (10th
percentile 8.4, 90th 54.2). The disc's own pixels, away from the bird, reach 26.1 at the
99th percentile.

## Roadie: flood-fill the disc, then keep the bird (`roadie_flood.py` → `roadie-flood.txt`)

**Method:** start from opaque pixels (alpha ≥ 128). Take the colour at seed pixel
(x 60, y 396), which is inside the disc to the left of the bird. Remove the
4-connected region of pixels within a Euclidean RGB distance of that colour. Then count
the remaining 8-connected pieces.

| Tolerance | Pixels removed | Pieces left | Largest pieces (px) |
|---:|---:|---:|---|
| 20 | 338,781 | 1,343 | 77,526, then ≤ 36 |
| 30 | 343,264 | 1,165 | 74,768, then ≤ 21 |
| 40 | 345,552 | 1,101 | 72,915, then ≤ 27 |
| 60 | 350,442 | 1,109 | 48,100, 8,323, 6,323, 2,488, ... |

At tolerances 20, 30 and 40 the bird stays one piece; at 60 it splits. All the other
pieces are under 50 px. They are mostly fragments of the thin white ring outside the
disc, which is not connected to the bird. Lower tolerances keep more of the dark fringe
around the bird: 77,526 px at 20 against 72,915 px at 40. The gaps between the legs are
connected to the disc, so the fill removes them.

A tolerance-40 mask was inspected visually. The bird silhouette, including the gaps
between the legs, looks correct. The beak edge looks thinner than in the original and
needs checking in a preview. That mask is derived from the owner's image, so it is kept
locally in `artifacts/selection-planning/` and not committed.

**Conclusion for the design:** two explicit seeds isolate the bird with deterministic
code: "remove the colour region at this point", then "keep the piece at this point". No
language interpretation is needed.

## Oddie: transparency already isolates it (`oddie_alpha.py` → `oddie-alpha.txt`)

Oddie is one 8-connected piece at every alpha cutoff tested (1, 64, 128, 192, 255). The
piece covers 301,447 px at cutoff 1 and 294,898 px at cutoff 255, a 2.2% difference. The
thin leaf tip stays attached at every cutoff.

## Limits

- Two images only, both cartoons with flat colours. Photographs are untested.
- One seed position per image. Tolerances are Euclidean distances in 8-bit sRGB, with no
  colour-space conversion.
- Visual inspection covered only the tolerance-40 Roadie mask.
- None of this tests tracing, extrusion or printing.

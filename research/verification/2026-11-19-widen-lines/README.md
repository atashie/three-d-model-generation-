# Widening thin drawn lines: prototypes, 2026-11-19

**What this is:** software measurements, without printing, made on the PC while
designing `colors.thin_lines: widen` (`docs/plans/2026-11-19-widen-lines-design.md`).
Validation level: measured. Nothing here has been printed.

**Input:** the job `roadie-thanksgiving`. It is a Gemini-generated, 4-color Thanksgiving
Roadie, a 977 × 1024 JPEG that imitates a tdmg `top.png`, with a grey checker background
and a legend. Selection: `remove_at [[5, 5]]`, `keep_at [[560, 540]]`, tolerance 80; the
bird is one piece of 155,312 px. Colors: extract 6, width 60 mm, so 0.08357 mm/px; island
minimum 91.6 px; opening 4.79 px (0.4 mm). The source image is not in the repository: it
is git-ignored under `jobs/`. So these scripts run only while that job exists, and the
images they wrote are not kept here, since the owner has not said the design may be
public.

**How to run:** from the repository root, with `jobs/roadie-thanksgiving/` present:
`uv run python research/verification/2026-11-19-widen-lines/widen_try5.py out/ 0.41 2`
(width in mm, then the area/line split as a multiple of the width). Scripts 1 to 4 write
into `out/`; 5 and 6 take the folder as their first argument. Each script records one
step of the design conversation, and they were kept as run.

## Results

| Script | What it tried | Result |
|---|---|---|
| `widen_try.py` | Classify the outline family's thin strokes by ring share (whole components; then per pixel in a 7–11 px window) | Fails: the turkey line is a red core with a darker fringe on both sides, so the fringe touches red and brown; ring shares are 0.41–0.58 for borders and lines alike |
| `widen_try2.py` | Thin pieces of each color after the outline drop | The turkey's red pieces lie 100% inside brown, elongation 9–22, width 4.0–4.4 px. But they are fragments: the drop gave most of each line to the brown |
| `widen_try3.py` | The "color view" (family pixels counted as their CIELAB-nearest non-family color: `#ca2116` → red, `#bb4b46` → brown); whole 4-connected pieces inside one color | One line found and drawn smoothly (264 px, elongation 60). The "3"-shaped line is skipped: it joins the red garnish |
| `widen_try4.py` | Thin parts (opening at W) of every piece | Lines in fragments; 12 extra specks of 13–27 px elsewhere (feathers, eye, hat brim) |
| `widen_try5.py` | Areas = opening at 2 × W; lines = the rest, kept when ≥ 0.9 inside one color, elongation ≥ 3 and area ≥ 91.6 px; band drawn before cleanup | Finds exactly the turkey's lines (264 and 504 px). Cleanup erases them: see the table below |
| `widen_try6.py` | Lines drawn after cleanup: (a) before smoothing; (b) on the smoothed fine map (supersample 4) | (a) smoothing thins a 0.41 mm line to median 0.36 mm, p1 0.21 mm. (b) median 0.409 mm; the lines are whole and connected, with slightly beaded edges |

**Cleanup erasure of a line band drawn before cleanup** (`widen_try5.py`, area split at
2 × W):

| Width | W (px) | Line px | Erased by cleanup |
|---|---|---|---|
| 0.41 mm | 4.91 | 768 | 737 |
| 0.45 mm | 5.38 | 790 | 657 |
| 0.50 mm | 5.98 | 861 | 272 |
| 0.55 mm | 6.58 | 1291 | 33 |

**Line width as drawn** (`widen_try6.py`, distance transform on the ridge, image-pixel
units converted to mm; ridge spurs near line ends bias the low percentiles down):

| Where drawn | p1 | p5 | p10 | median |
|---|---|---|---|---|
| Pixel map, before smoothing | 0.334 | 0.334 | 0.334 | 0.367 |
| Pixel map, after smoothing | 0.209 | 0.242 | 0.292 | 0.359 |
| Fine map, after smoothing | 0.359 | 0.384 | 0.384 | 0.409 |

**Also measured:**
- `outlines: keep` with `outline_color: [4]` on this image drew a 0.5 mm band in
  `#ca2116` over 27.3% of the model (along the outer edge and most color borders), and
  the plan needed 5 colors (not ready). The job was set back to `drop` / `auto`.
- The selection: at the default tolerance (30), `remove_at` on the checker removed
  almost nothing (1,000,412 of 1,000,448 px kept), because the two checker greys (about
  107 and 144–149) are farther apart than 30. At 80, one point removed the whole checker,
  and the legend panel fell away under `keep_at`. 417 kept pixels (0.27%) are greyish
  JPEG fringe along the edge.

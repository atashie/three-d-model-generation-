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

## Addendum, 2026-11-19: `find_lines` on the same image (Task 3, commit 2a81caa)

`tdmg.color_lines.find_lines` (exact EDT; elongation defined as length / width, where
length = area / width) on `roadie-thanksgiving` at 6 colors, family `#ca2116` and
`#bb4b46`, W = 4.906 px, min_area 91.65 px, min_width 4.787 px, host share 0.9,
min_elongation 3:

| Line | Host | Area (px) | Width (px) | Length (px) | Length / width |
|---|---|---|---|---|---|
| `#f50506` | `#4a1a14` | 264 | 4.47 | 59.0 | 13.2 |
| `#f50506` | `#4a1a14` | 504 | 4.47 | 112.7 | 25.2 |

These are the prototype's two pieces (264 and 504 px). The prototypes wrote "elongation"
for area / width (a length in pixels, 60.1 and 114.7 for these pieces), not for length /
width. On this image the same two lines are found at length / width >= 3 and with no
elongation limit at all, so the image does not test that limit.

## Addendum, 2026-11-19: slicing the turkey at several line widths (after Task 5, commit f481987)

`make_colors` (`thin_lines: widen`, `line_width_mm` as listed), `make_colored_flat`
(thickness 3 mm) and `make_color_slice` (pinned OrcaSlicer 2.5.0 and PrusaSlicer 2.9.7,
`check_tree=False`) on a copy of `roadie-thanksgiving`'s selection, 60 mm wide. Red
`#f50506` is the base (tool T0); the lines are red inside the brown inlay. The table gives
the per-tool check `F3.edge_coverage.T0` (a warning, not required): the largest distance
from a red model edge to red plastic, and where it is. The lines span model x 47.2–51.3 /
y 28.7–31.6 and x 52.2–55.7 / y 29.9–32.3 (face down mirrors x).

| Line width | Face up: gap, at (x, y) mm, z | Face down: gap, at (x, y) mm, z |
|---|---|---|
| no lines (`remove`) | 0.421, (39.6, 25.0), 2.8 | 1.125, (21.3, 24.0), 0.2 |
| 0.41 mm | 3.884, (50.4, 31.7), 2.6 | 4.477, (7.6, 31.0), 0.2 |
| 0.45 mm | 1.846, (50.3, 31.8), 2.8 | 4.495, (7.6, 31.0), 0.2 |
| 0.50 mm | 1.587, (51.1, 28.6), 2.6 | 3.881, (9.6, 31.8), 0.2 |
| 0.55 mm | 1.375, (48.2, 31.0), 2.6 | 1.574, (8.8, 28.5), 0.2 |
| 0.60 mm | 0.421, (39.6, 25.0), 2.8 | 1.125, (21.3, 24.0), 0.2 |

From 0.45 to 0.55 mm the worst gap is on the lines; at 0.6 mm it is back at the no-lines
location, so OrcaSlicer prints these lines in full from about 0.6 mm. The whole-model
`F3.edge_coverage` (required) passed in every case, so the verdict did not show the
unprinted line stretches. The owner chose to keep 0.41 mm and test-print it ("1) 0.41 mm
and test-print it"), and that a widened line's coverage should count in the verdict
("to your question: yes"). Bambu Studio, which the owner prints from, was not measured.

## Addendum, 2026-11-19: the ridge joining and smoothing values (after the Codex reviews)

Software tests only (no print): `tests/test_color_lines.py` and `tests/test_colors.py` on
synthetic fixtures, Windows PC. The values below were chosen by reasoning and then checked
on those fixtures; none is tuned against a measured near miss, and none is tested on an
owner image other than the roadie-thanksgiving runs above.

- Loop path factor 3 (`color.lines.loop_path_factor`): a closing bridge is taken only where the path along the ridge is more than 3 times the bridge (in half-pixel steps). Along a straight or gently bent ridge the ratio is about 1, around a half turn at most about 2.2 (pi / 2 in length, times up to sqrt 2 for counting steps). A loop closes once its perimeter is more than about 5.3 times its gap. The factor alone does not refuse a long U (its path is unbounded against its chord); the in-line run test and the topology test do. Fixtures: the rings in one, two and 45 pieces close; the straight line, the U and the chord past a middle piece are refused.
- Run tolerance 0.5 px (`color.lines.run_tolerance`): a bridge's straight run may leave the found line by one half pixel, since the ridge and the run are rounded to half pixels and a run between two ridge points inside the line can cut a corner of its staircase edge. Fixture: a one-half-pixel-thin diamond loop closes only with it.
- Close reach 8 px (`color.lines.close_reach`): closing bridges are looked for within twice the spanning tree's reach and at least 8 px. On the varying-width ring (radius 25 px, half width 1 to 2 px, 0.1 mm/px) the closing gap was 7.1 half pixels while the tree needed a reach of 8 half pixels; 8 px is twice that, so a ring whose ridge is one piece with such a gap is still searched. A longer gap stays open.
- Ridge smoothing 1.5 px (`color.lines.ridge_smooth`): each ridge point moves to the mean of the ridge points within 1.5 px, the size of the half-pixel staircase of a ridge at an angle, which beaded the drawn edges without it (`widen_try6.py` above, "slightly beaded edges"). With it the straight band's width is within one fine pixel of the drawn width, and a drawn end is 0.64 to 0.75 px shorter than the raw ridge.

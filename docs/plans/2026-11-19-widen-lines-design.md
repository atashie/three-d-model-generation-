# Widen thin drawn lines instead of removing them: design

**Status:** approved by the owner on 2026-11-19 ("perfect!"). Not built yet. The
implementation plan comes next (`docs/plans/2026-11-19-widen-lines.md`).

**Evidence:** prototypes and measurements in
`research/verification/2026-11-19-widen-lines/README.md`.

## Why

The job `roadie-thanksgiving` (a Gemini-generated Thanksgiving Roadie, R2, 60 mm wide)
has three thin red lines drawn on a brown roast turkey. At 60 mm (0.0836 mm per image
pixel), they are about 4 px wide, which is 0.33 mm. Cleanup removes everything narrower
than `flat.sliver.opening_width` (0.4 mm), so the plan printed a plain brown turkey.

The owner's words (2026-11-19):
- "Let's raise our floor of minimum line thickness to 0.4 mm and trust our printer do
  deliver. Resize the lines to be a minimum thickness of 0.4 mm, and keep the overall size
  as is."
- After the first prototype: "The thickened lines are bad - keep them connected (no
  erasing) and make them 0.41 mm thick if possible, instead of 0.5"
- Choice between 0.41 mm drawn after cleanup (A) and 0.55 mm through cleanup (B): "A".
- On this design: "perfect!"

## What was tried first, and why it failed

These dead ends are measured. Do not try them again for this kind of line.

1. **`outlines: keep` with `outline_color: [4]`** (the line's darker red). The JPEG blur
   leaves the same in-between red along every border between two colors, so the band was
   drawn around the whole bird and along most color borders (27.3% of the model). It
   also added a 5th filament.
2. **Widening only the line pixels that survive the outline drop.** The drop had already
   given most of each line (its blur) to the brown, so only fragments came back.
3. **Widening only the parts of a line narrower than the target.** The lines broke where
   they were already wider, and the "3"-shaped line was skipped where it meets the red
   garnish.
4. **Widening before cleanup.** Cleanup's 0.4 mm opening, on the pixel grid, erased 96%
   of a 0.41 mm line (737 of 768 px), 83% at 0.45 mm and 32% at 0.5 mm. Only at 0.55 mm
   did the lines survive (33 of 1291 px lost). A pixel staircase on a curve is narrower
   than the line's true width.
5. **Widening after cleanup but before smoothing.** Edge smoothing (Gaussian, sigma
   2.5 px) thinned a 0.41 mm line to a median 0.36 mm, with parts at 0.21 mm.

## The design

1. **Settings** (owner style choices, explicit, with defaults):
   - `colors.thin_lines`: `remove` (the default, today's behaviour) or `widen`. With
     `remove`, every result is byte-identical to today, so `tdmg library verify
     roadie-drop` still reports identical.
   - `colors.line_width_mm`: the drawn width under `widen`. The default comes from a new
     rule color.lines.width (planned), 0.41 mm, kind `hypothesis`, evidence the owner's words
     above, validation `untested`. Refused at or below `flat.sliver.opening_width`.
2. **Finding the lines** happens on the extracted colors, before the outline step, so a
   line is taken as drawn:
   - **The color view:** each outline-family pixel (`color.outline.thin_share`) counts as
     the non-family color nearest to it in CIELAB. The line's darker-red blur then counts
     as red. (Spatial nearest, which the outline drop uses, gives the blur to the
     neighbouring brown.)
   - **Areas and lines:** each 4-connected piece of one color is split into its areas
     (the pixels that an opening at 2 × the line width keeps) and its lines (the rest).
     Each 8-connected part of the lines is a candidate.
   - **A candidate is a line when** all three hold:
     - at least color.lines.host_share (planned) (new rule, hypothesis, 0.9) of the pixels in a
       2 px ring around it, not counting its own color, are one other color: the host;
     - its length (area divided by its 90th-percentile width) is at least
       color.lines.min_elongation (planned) (new rule, hypothesis, 3) times its width;
     - its area is at least the island area (`flat.island.min_square_side`, 0.64 mm²).
   - On `roadie-thanksgiving` this finds exactly the turkey's lines (prototype `try5`).
3. **Outline drop, merges, cleanup and smoothing run as today.** The lines may vanish
   from the cleaned map; that is expected.
4. **Drawing the lines** happens last, on the smoothed fine map (supersample 4, 0.021 mm
   per fine pixel at 60 mm):
   - the line's center line is the ridge of the line's pixels at half-pixel resolution
     (as `stroke_band` does), then smoothed so its edges are not beaded;
   - every fine pixel of the host color, or of the line's own color, within half the width
     of the center line becomes the line's color (after the merges' remap). A line never
     paints over a third color;
   - prototype: median 0.409 mm against 0.41 mm (`try6`).
5. **Records:**
   - `colors.json` lists each line: color, host, area, length, width as drawn and as
     found, and the rules used;
   - `regions.png` shows the lines in the final colors and adds a legend line;
   - a note says the lines are drawn after cleanup, below the cleanup floor's margin, and
     untested in print.
6. **The gate is unchanged.** The model is built and sliced as before. If a slicer drops
   a line, the slice checks show it in the verdict.

**Out of scope:** narrow necks of a larger region (the white gap between the two pupils on
`roadie-thanksgiving` still closes at 60 mm). Widening a neck pushes a neighbouring color
back; that is a different change.

**Related:** `roadie-mural` (paused) has a different line problem: a black outline's grey
fringe goes to white. See `docs/STATUS.md`, Next steps.

## Tests

- A synthetic picture with a thin line inside one color, a blurred border between two
  colors, and a small dot: only the line is drawn, at 0.41 mm ± 0.03 mm, connected end to
  end; the border and the dot are unchanged.
- A line that joins a wide area of its own color (the garnish case) is drawn whole.
- `remove` gives byte-identical outputs to today; `tdmg library verify roadie-drop` stays
  identical.
- `line_width_mm` at or below 0.4 mm is refused.
- `roadie-thanksgiving` under `widen`: run as a job, then check the plan and the slice.

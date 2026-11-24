# Thin drawn lines as gaps: design

**Status:** approved by the owner on 2026-11-23 ("yes, proceed"). Not built yet. It is
built after the widen plan's Task 5b (`docs/plans/2026-11-19-widen-lines.md`), whose
line-coverage measurement it reuses.

**Evidence:** `research/verification/2026-11-22-thin-line-print/README.md`. The owner
printed `roadie-thanksgiving` with `thin_lines: widen` at 0.41 mm, face up. The red
lines did not print. A dark gap was left where they should have been, and the owner
judged it as good a border as the line, or better.

## The owner's choices (2026-11-22)

Asked how a deliberate gap fits with `remove` and `widen`, the owner chose the option
"Add gap, keep widen (Recommended)". The option read: "New thin_lines: gap cuts each line
out as an empty groove, skin-deep, with the base below. Widen stays, but the step-2
coverage check will make it NOT CERTIFIED whenever the slicer can't print the lines, as
at 0.41 mm."

Asked how wide a gap is cut, the owner chose "Set width, default 0.41 (Recommended)":
"Every line is cut at one width, gap_width_mm, default 0.41 mm, the printed value. You
can change it per job. Narrower is untested; wider gaps are more visible."

## The design

1. **Settings** (owner style choices, explicit, with defaults):
   - `colors.thin_lines`: `remove` (the default), `widen` or `gap`. No `thin_lines` key
     gives byte-identical records, as today.
   - `colors.gap_width_mm`: the groove's width under `gap`. Its default comes from a new
     rule color.lines.gap_width (planned), 0.41 mm: kind `empirical`, provenance `primary`,
     validation `calibrated`. It is the first calibrated rule, and its evidence is the
     print note: one print, face up, at 0.41 mm, so its notes say that narrower widths
     and face down are untested. The value must be finite and above 0. It is not
     compared with the cleanup opening: a groove holds no plastic, so cleanup's
     thinnest-printable-strip floor does not apply to it.
   - `line_width_mm` is unused under `gap` and is left out of the record, as under
     `remove`; `gap_width_mm` is left out of every record but a gap plan's.
2. **Finding the lines:** the same `find_lines` as `widen`, with the same rules. These
   are thin lines inside one other color, with their joined, smoothed center lines.
3. **Outline drop, merges, cleanup and smoothing run as under `remove`.** The line's
   pixels go to the host color first. So the line's own color is kept only if it is
   used elsewhere, and a color used only by the lines no longer needs an AMS slot.
4. **Cutting the grooves** happens last, on the smoothed fine map, as `widen` draws:
   - every fine pixel within half of `gap_width_mm` of a line's center line becomes a
     gap pixel, whatever its color, at the model's own scale in `tdmg flat --colors`;
   - in the 3D model a gap cell gets the base body from 0 to `T - d` only, and no inlay
     (`T` is the thickness, `d` is `color.skin.depth_mm`). The groove is then exactly
     skin-deep, with the base as its floor, as on the print. Face down, the same groove
     is at the bed side;
   - the grooves are part of the shape. No filament is assigned to them, so no slicer
     setting can fill them with a color.
5. **Records and previews:**
   - `colors.json` lists each line as `widen` does, with `mode: gap` and the width cut;
   - `regions.png` and `top.png` draw the grooves in one fixed dark display color, with
     a legend line "gap (no plastic)". It is a display color only, not a filament;
   - there is no glue version, as with `widen`: glued pieces would carry the grooves,
     which is unrealistic to glue.
6. **The gate:** no filament may be printed inside a groove more than the allowance
   (`acceptance.dimension.tolerance`, 0.2 mm, and the first-layer allowance, as for F3)
   past the groove's edge. That is the measurement of `F3.edge_overprint`: plastic
   outside the model's section on a layer. On a skin layer the section has the grooves
   cut out, so the existing required whole-model `F3.edge_overprint` may already cover
   it. The plan proves this by test first (a synthetic footprint over a groove must
   FAIL it). If it does not cover it, a required check `F3.gap_open`, present only for a
   gap plan with a groove in the model, measures the same thing per groove: for each
   face, on every skin layer (from `T - d` to `T` face up, from 0 to `d` face down), the
   printed footprint of every tool must stay at least half the groove width less the
   allowance from each groove center-line sample, and must never cover a sample. FAIL names the worst one (position in
   model mm, z, line index, tool); UNKNOWN when it cannot be measured, as for F3. It
   reuses Task 5b's sampling helper (`F3.line_coverage`), turned around. No new number.
   At 0.41 mm, half the groove (0.205 mm) is about the allowance, so plastic may come
   up to nearly the groove's middle from each side and still pass. Whether that still
   reads as a gap is shown by print, not by this check.

## Tests

- No `thin_lines` key: records byte-identical; `tdmg library verify roadie-drop` exits
  0, identical.
- A gap plan: the line's pixels go to the host; a groove of the given width (measured
  across the fine map) is cut; a color used only by the line drops out of the palette.
- The AMS bodies: the gap cells hold base material from 0 to `T - d` and nothing above;
  every body is still closed and the assembly checks pass.
- `F3.gap_open`: a synthetic footprint clear of the groove passes; one over the center
  line fails with the right position, z, line and tool; a widen or remove plan has no
  such check.
- Verify: a tampered gap block or width is caught; a widen record is not read as gap.
- The real job: `roadie-thanksgiving` with `thin_lines: gap`, built and sliced face up
  and face down (scratch run), with the verdicts reported to the owner.

**Out of scope:** grooves for lines between two colors (only lines inside one color are
found today); grooves through the whole thickness, which would cut the model apart.

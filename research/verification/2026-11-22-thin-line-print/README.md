# A 0.41 mm drawn line, printed: it left a gap, 2026-11-22

**What this is:** the first print of a plan with `colors.thin_lines: widen`
(`docs/plans/2026-11-19-widen-lines-design.md`). Validation level: calibrated (printed
on our printer), for this one print only.

## What was printed

- **The job:** `roadie-thanksgiving`, a 4-color Thanksgiving Roadie, 60 mm wide, 2.5 mm
  thick, colored skin 0.6 mm (`color.skin.depth_mm`). The turkey has two thin red lines
  inside brown, drawn by `thin_lines: widen` at 0.41 mm (`color.lines.width`, the
  owner's number). Red #f50506 is the base color, so each line was a 0.41 mm strip of
  the base body that rose through the brown skin to the top.
- **The file:** `jobs/roadie-thanksgiving/colored_flat/model.3mf`, SHA-256
  `bad109a321f0eb72ce767a9adf2d3993961fffb3e5801a7b381289e5b8dba69d` (the job is
  git-ignored; the file reaches the library only through `tdmg finish`).
- **How:** face up (as `model.3mf` opens), sliced and printed from Bambu Studio by the
  owner on the A1 with the AMS lite. Filaments: red #F50506, white #F5F3F3, dark brown
  #4A1A14, yellow #F0EE15.
- **What tdmg had said:** the pinned OrcaSlicer 2.5.0 slice was face down PRINTABLE,
  face up NOT CERTIFIED (on layer 10, the first skin layer, only red printed:
  `F6.tool_placement`, `F6.color_changes`, `F3.edge_overprint`). Face down, the per-tool
  warning `F3.edge_coverage.T0` showed red edge 4.458 mm from red plastic on 3 layers,
  on the turkey's lines; the line-width sweep in
  `research/verification/2026-11-19-widen-lines/README.md` showed the same at 0.41 mm
  face up (3.884 mm). The required line-coverage check (widen plan, Task 5b) was not yet
  built, so the gap was a warning only.

## The owner's words

The print (recorded as confirmation 3 of the job, `--route ams --face up
--accept-not-certified`, dated 2026-11-22):

> I printed it; it looked quite good and I'm happy with the product. However teh fine
> lines of red that helped define the turkey did not print, but instead a gap was left
> where the lines should have been.

In the same message: "That is actually a pretty good result, as a gap in teh brown helps
delineate teh leg (etc) of teh chicken just as well, if not better, than the red outline
would have done".

Asked, on 2026-11-22, (1) whether to record the print accepting that face up was NOT
CERTIFIED, (2) whether the top looked complete, with no missing color and no red where
it should not be, and (3) whether the bottom of the grooves was red or just looked like
a dark gap, the owner answered: "Yes, yes, gap".

## What this shows, and what it does not

- **Shown, for this print:** a 0.41 mm strip of one color inside another, in the 0.6 mm
  skin, printed face up from Bambu Studio on the A1, did not print as a line. The
  neighbouring brown stopped at the strip's edge, so the strip came out as an open,
  dark-looking groove. A line this thin does not print as a colored line.
- **Shown, for this print:** the groove read as a border. The owner judged it as good
  as or better than the red line would have been.
- **Shown:** Bambu Studio's face-up slice did not have the layer-10 fault that the
  pinned OrcaSlicer's face-up slice had (the owner saw a complete top). This is one
  print; it does not show why OrcaSlicer differs.
- **Not shown:** whether a wider line (0.45 to 0.6 mm) prints as a line; whether face
  down behaves the same; whether a groove narrower than 0.41 mm stays open; how deep the
  groove was (the owner saw a dark gap, not the red base).

## What follows

- `thin_lines: widen` at 0.41 mm should not be PRINTABLE when the slicer leaves the
  lines empty: the required check `F3.line_coverage` (widen plan, Task 5b).
- The owner chose (2026-11-22) a third mode, `thin_lines: gap`: each thin line is cut
  as an empty, skin-deep groove of one width, default 0.41 mm, the printed value.

## Addendum, 2026-11-23: the line-coverage check on this job (software, not printed)

The required check `F3.line_coverage` (widen plan, Task 5b) was run on this job's
inputs, rebuilt in a scratch folder with the pinned OrcaSlicer 2.5.0 and PrusaSlicer
2.9.7 (validation: measured). A line sample counts only on layers where its host body
(brown) has a section, i.e. the skin layers; the allowance is
`acceptance.dimension.tolerance` plus the first layer's elephant-foot compensation.

| Line width | Face | F3.line_coverage | Worst gap | Where | Samples over | Face verdict |
|---|---|---|---|---|---|---|
| 0.41 mm (2 lines) | up | FAIL | 4.241 mm vs 0.2 | layer 11 (z 2.2), line item 0, model (52.62, 30.94) | 770 | NOT CERTIFIED |
| 0.41 mm | down | FAIL | 4.241 mm vs 0.2 | layer 2 (z 0.4), same point | 1158 | NOT CERTIFIED |
| 0.6 mm (1 line found) | up | PASS | 0 | layers 10 to 12 | 0 | NOT CERTIFIED (other checks) |
| 0.6 mm | down | FAIL | 0.626 mm vs 0.275 | layer 1, model (53.04, 31.38) | 23 | NOT CERTIFIED |

At 0.41 mm the check FAILs on both faces, which agrees with the print. Face up was NOT
CERTIFIED for other reasons at both widths (`F6.color_changes`, `F6.tool_placement`,
`F3.edge_overprint.T0`, the OrcaSlicer layer-10 fault). At 0.6 mm the plan found one
line, not two. **How to run:** from the repository root, with
`jobs/roadie-thanksgiving/` present (the job is git-ignored, so the script runs only while
it exists, like the 2026-11-19-widen-lines scripts):
`uv run python research/verification/2026-11-22-thin-line-print/measure_line_coverage.py job OUT`
(or `0.6` in place of `job`), with `OUT` a folder outside the repository; it prints the
table's rows for both faces. The table above came from the scratch script this one was
cleaned from; its logs were not kept.

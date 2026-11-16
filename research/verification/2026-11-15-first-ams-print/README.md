# First AMS print of an owner plan, 2026-11-15

R2 step 5, part 2. The first multicolor print of an owner figure.

- **What was printed:** Roadie, outline dropped,
  `artifacts/colored-runs/roadie-tol30-60-drop-v3-f64/model.3mf`, face up (the default),
  sliced and printed from Bambu Studio on the owner's A1 with the AMS, four colors (red
  base, white, yellow, dark brown). That folder re-sliced with the current code the same
  day: face up PRINTABLE, 9 color changes, 1873 s (`artifacts/slice-runs/color5-roadie-drop-v3-f64`).
- **The owner's words:** "while it looked good initially while printing, the surface
  (with 4 colors) as quite \"smeared\" without crisp borders between the colors".
- **Photo:** `roadie-drop-face-up.jpg` (the owner's, taken in dim light; somewhat
  blurred).

## What the photo shows (read by eye from the photo; not measured)

- **Yellow beak:** clean, with a fairly sharp edge to the red.
- **White areas (belly, shoe rims, eye):** where the design puts them (`top.png`), but
  they look pinkish, and their borders with red are blurred. The dim light makes the
  tint hard to judge.
- **Red:** a rough, scuffed top surface; the thin crest spikes on the head are partly
  missing or stringy.
- **Strings:** a long red strand from the tail and fine strings at the head.

## Possible causes (not yet tested)

1. **Red not flushed before white:** red into white is the hardest change to flush. A
   pink tint across a white region fits this.
2. **Red dragged or oozed over the colors printed before it:** face up, the colors are
   the top three layers, and the nozzle travels over fresh plastic between them. Smears
   and strings on the top face fit this.
3. **Thin crest spikes:** narrow features in the top layers; the gate's
   `edge coverage` warning for the base (edges up to 0.28 mm from its printed lines) is
   about the edge, not about these.

The photo cannot tell 1 from 2. Neither cause is measured.

## The face-down slice (same day, pinned OrcaSlicer 2.5.0)

`tdmg slice ... --face down` (`artifacts/slice-runs/color5-roadie-drop-v3-f64-down`):
NOT CERTIFIED by `F3.edge_coverage` UNKNOWN (as recorded on 2026-11-13) and
`F6.portability` UNKNOWN (PrusaSlicer was not passed in this run); 10 color changes,
1897 s. UNKNOWN means not measured, not a failure.

## The face-down print (reported 2026-11-16)

- **What was printed:** the same `model.3mf`, turned over in Bambu Studio (rotated 180°
  about X), every other setting unchanged; sliced and printed from Bambu Studio.
- **The owner's words:** "done, and the newly printed items look great".
- **No photo.**
- **What it shows:** with only the face changed, the owner judged the result good, so
  face down removed the smearing seen face up. This print does not separate the two
  causes above (flush, drag) for the face-up print; it shows that face down, with Bambu
  Studio's default flushing, is good enough by the owner's eye.
- **What it does not change:** `tdmg slice` still defaults to face up, and its face-down
  slice of this plan is NOT CERTIFIED (`F3.edge_coverage` UNKNOWN). Changing the default is
  the owner's decision.
- **Why that check is UNKNOWN** (the run's `slice.json`): the worst layer, z 0.2 mm (the
  first layer, the colored face), leaves 0.251 mm against a tolerance of 0.275 mm. Edge
  samples are 0.05 mm apart, so the true largest gap can be up to 0.025 mm more, which
  could reach 0.276 mm. It is a near-pass the sampling cannot settle, not a measured
  failure.

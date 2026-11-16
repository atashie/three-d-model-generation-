# Design note: calibration prints (`tdmg strip`) and calibrated rules

A calibration print is a small test object printed on our own printer to set a rule
from a real result. A rule becomes `validation: calibrated` only from such a print
(CLAUDE.md rule 3). `tdmg strip OUT` makes two test strips, gates and slices them, and
writes `results-template.md`, the form the owner fills in after printing.

## Decisions in force

**The strips** ([test-strip plan](../plans/2026-11-14-test-strip.md), approved by the
owner on 2026-11-14: "build it"). Owner decisions, 2026-11-14:
- clearance gaps 0.10 to 0.35 mm per side, in steps of 0.05 (six pockets);
- skin depths 0.2 to 1.0 mm, in steps of 0.2 (five patches), white over black, the
  worst case;
- judged by hand and eye, with a photo; no calipers;
- the clearance base plate stays NOT CERTIFIED and is printed anyway ("Keep the FAIL,
  print anyway"); a `known_failures` note covers that plate only, counts parts and does
  not size them (owner on sizing: "Not now");
- the white tool's `F3.edge_coverage.T1` and `F3.printed_connectivity.T1` are required
  for the skin strip only ("Require it for the strip"); owner plans keep "Outer edge
  only";
- the clearance form judges each piece in three steps ("Judge it in three steps"): goes
  in (won't / pressed / drops), sits flat (yes / no), play (none / a little / a lot);
- the pieces are not turned, and piece 1 is marked with a pen ("Pen mark is enough").
- The layout numbers (squares, spacing, thickness) are the test object's size, not
  rules; each is checked against the rules it must meet. The strips use the same
  geometry and checks as owner plans, not new ones.

**Results:**
- **`color.skin.depth_mm` = 0.6 mm, calibrated** (2026-11-15). The owner printed the skin
  strip in eSUN PLA+ with Bambu Studio's settings unchanged: "every square is opaque"
  (every depth from 0.2 mm looked like full white). Owner: "Keep 0.6 mm (Recommended)".
  The rule is now `kind: empirical` with calibrated evidence. No photo, by the owner's
  choice.
- **The clearance strip was skipped.** Owner, 2026-11-15: "Let's skip further tests -
  the real tests will come when we begin printing actual figures that we are interested
  in". So `color.glue.clearance_mm` (0.2 mm) stays a hypothesis, untested. The first glue
  print of an owner figure is its first test: record how the pieces fit (the three
  steps above) and the filament.
- **`acceptance.dimension.tolerance` (0.2 mm) stays a hypothesis,** untested: nothing has
  been measured with calipers. If the owner gets calipers: three named dimensions,
  logged as a calibration.

**Prints so far (by eye, nothing measured):**
- Roadie R1, 60 × 3 mm, `tdmg flat` STL sliced in Bambu Studio, matte PLA, 2026-11-10:
  "it looks great".
- Roadie R2 AMS, outline dropped, 2026-11-15/16: face up "smeared"; face down "the newly
  printed items look great". This set the face-down preference ([slicing.md](slicing.md)).

## Review findings that still constrain the code

From [`research/reviews/2026-11-14-test-strips/`](../../research/reviews/2026-11-14-test-strips/README.md)
(3 High, 4 Medium, all handled):
- the `known_failures` note covers the clearance base plate only (`KNOWN_FAILURE_PARTS`),
  so a pieces-plate FAIL exits 1;
- a whole white patch could be missing with only warnings, hence the required white-tool
  checks (`strip-3`);
- the form gives the checked print settings (`print_settings` in `strip.json`) and asks
  for the ones used;
- the skin is judged lying flat, lit from the front or above, not held up to a light.

## Still open

- How Bambu Studio places `pieces.stl` is not checked; the form says to check the row
  before printing.
- Curved pocket edges, other filament pairs and glue strength are not tested.

## Records

- [`research/verification/2026-11-14-test-strips/`](../../research/verification/2026-11-14-test-strips/README.md)
  (section 7: the skin result and the clearance decision).
- [`research/verification/2026-11-15-first-ams-print/`](../../research/verification/2026-11-15-first-ams-print/README.md).
- [`research/verification/2026-11-10-outline-smoothing/`](../../research/verification/2026-11-10-outline-smoothing/README.md)
  ("First physical print").

## Removed records

None of the five records removed in commit `814a962723454efa7693b8ef8af715062368975a`
covered calibration.

# What OrcaSlicer actually prints at thin features, 2026-11-10

**Purpose:** evidence for an F3 (thin-wall) pass/fail policy. Today `F3.thin_regions`
only measures how much of the outline is narrower than `fdm.wall.min_thickness`. It is
UNKNOWN by design, and it blocks certification. These measurements ask instead what the
slicer actually lays down, by reading the G-code. Two questions matter: is any part of
the model edge left unprinted, and is any narrow connection lost?

**Setup:** the Windows PC, with the pinned OrcaSlicer 2.5.0 and A1 profiles
(`research/verification/2026-11-10-orcaslicer-windows/`). The relevant settings, from
the G-code header, are in `slicer-settings.txt`:
- the `classic` wall generator, 2 wall loops and 0.42 mm lines;
- `detect_thin_wall = 0`, `filter_out_gap_fill = 0`, `precise_outer_wall = 1`;
- `elefant_foot_compensation = 0.075` on the first layer.

The G-code uses `; FEATURE:`, `; LINE_WIDTH:` and `; Z_HEIGHT:` comments, relative
extrusion (M83) and arc moves (G2/G3, because arc fitting is enabled).

## Method (`measure_coverage.py`)

1. **Printed footprint per layer:** every extruding move, with arcs split into chords of
   at most 0.05 mm, is buffered by half its stated line width and the results are merged.
   This "bead" model, a line of that width with round ends, is an approximation of real
   squashed plastic.
2. **Model section:** the STL is cut 0.1 mm below each layer's Z.
3. **Alignment:** OrcaSlicer centres the object and may rotate it. The 25 × 10 mm controls
   below were turned 90° about Z; the owner's models were not rotated. The model section
   is aligned with the outer-wall centrelines by trying the four quarter-turns and keeping
   the best fit.
4. **Per layer:** the largest distance from any model-edge sample (0.05 mm spacing) to
   printed plastic, and the number of connected parts in the model against the
   footprint.

A side measurement (`wall_offset.py` → `wall-offset.txt`): the outer-wall centreline sits
0.21 mm inside the model edge (median 0.2098 mm, 5th to 95th percentile 0.199–0.220 mm,
on Roadie at z = 1.6). That is half the 0.42 mm line, so the outer bead's edge lands on
the model edge.

An early prototype aligned the shapes by their bounding-box corner. That gave a spurious
uniform 0.16 mm gap, and the rotation was found only through the controls. Both are
corrected in the committed script.

## Results

**The owner's models** (`coverage.txt`, the smoothed 60 × 3 mm STLs, 15 layers):

| Model | First layer: largest edge gap | Layers 2–15: largest edge gap | Parts, model/printed |
|---|---:|---:|---|
| Roadie | 0.223 mm (0.08% of edge > 0.2 mm) | 0.061 mm | 1/1 on every layer |
| Oddie | 0.242 mm (0.14% of edge > 0.2 mm) | 0.067 mm | 1/1 on every layer |

Above the first layer, every point of the outline, including Roadie's spike tips, is
within about 0.07 mm of printed plastic. Thin tips are filled with "Gap infill" lines
down to 0.096 mm wide. The larger first-layer gap matches the deliberate 0.075 mm
elephant-foot shrink. The owner printed this Roadie STL and judged it "great"
(`research/verification/2026-11-10-outline-smoothing/`), but by eye only, with no
measurements.

**Controls** (`controls.py` → `controls.txt`): two 10 mm squares joined by a 5 mm bridge,
3 mm thick.

| Bridge width | First layer | Layers above | Largest edge gap above the first layer |
|---:|---|---|---:|
| 0.15 mm | printed parts 2 (bridge lost) | 2 on every layer | 2.49 mm |
| 0.30 mm | 2 | 2 on every layer | 2.49 mm |
| 0.45 mm | 2 (bridge lost on layer 1) | 1 | 0.087 mm |
| 0.60 mm | 1 | 1 | 0.087 mm |
| 1.00 mm | 1 | 1 | 0.087 mm |

Both measures detect a lost bridge. The printed parts outnumber the model's parts, and
the edge gap jumps to about half the bridge length. Printed features stayed within
0.09 mm, and lost ones were 2.5 mm away: there is a wide gap between the two outcomes.

## What this supports, and what it does not

- **Supported:** with these settings, OrcaSlicer printed every outline point of both
  owner models, to within 0.07 mm above the first layer. A connection 0.3 mm wide or
  narrower was not printed at all. One 0.45 mm wide was missing on the first layer only.
- **Not supported:**
  - That these beads are strong. A single 0.1 mm gap-infill line is printed, but may be
    fragile.
  - Behaviour with other profiles, nozzles or slicers.
  - The bead model's accuracy against real plastic. That would need calipers or a
    microscope.
  - Any case beyond two cartoons and five bridges.

## Addendum: implementation results and corrections, 2026-11-10

The policy is implemented in `src/tdmg/printed.py` and `tdmg slice` (commits `95d8c07`,
`9785c1e`, `6f1720f`, `0a44a2d`, `019e404`). Changes relative to the research method
above:

- **Placement is the known one, not fitted.** OrcaSlicer centres the model's bounding box
  on the plate. Measured: Roadie's centre at (128.0007, 128.0013) and Oddie's at
  (127.995, 128.002), against the plate centre (128, 128), the centre of the machine
  profile's `printable_area`.
  - The research's first-layer bounding-box match was off by 0.03–0.04 mm, because the
    elephant-foot shrink is not uniform. Its 0.061 / 0.067 mm "above the first layer"
    figures therefore partly reflect misalignment. With the known placement they are
    0.027 / 0.037 mm.
  - A fitted placement was also shown to absorb one-sided errors and produce false
    PASSes, for example a side printed 0.25 mm short. That is why fitting was dropped.
- **Model sections** are cut at each layer's mid-height (Z_HEIGHT − LAYER_HEIGHT / 2),
  not at a fixed 0.1 mm offset.
- **Overprint is measured too** (owner decision). The largest distance of printed plastic
  outside the model is 0.013 mm for Roadie and 0.013 mm for Oddie (first layer: 0.012 /
  0.009 mm). The 0.5 mm first-layer lines do not push plastic outward.
- **Layer heights:** OrcaSlicer writes `; LAYER_HEIGHT: 0.4` before Internal Bridge lines
  inside a 0.2 mm layer. Only the first LAYER_HEIGHT after each Z_HEIGHT is the layer's
  height. `; Z_HEIGHT: %g` is confirmed in the v2.5.0 source (`src/libslic3r/GCode.cpp`
  line 6681).

**Final runs** (`tdmg slice`, output in the git-ignored `artifacts/slice-runs/*-60x3-f3`):

| Model | Connectivity | Edge coverage, worst (allowance) | Overprint, worst | Certification |
|---|---|---|---|---|
| Roadie | PASS, 15/15 layers | 0.231 mm, first layer (0.275) | 0.013 mm | NOT CERTIFIED: F6.portability UNKNOWN |
| Oddie | PASS, 15/15 layers | 0.222 mm, first layer (0.275) | 0.013 mm | NOT CERTIFIED: F6.portability UNKNOWN |

**Known limits of the policy:**
- **Small holes:** a hole of 0.4 mm or less that gets printed over cannot fail the
  0.2 mm overprint check, because every point inside it is within 0.2 mm of the model.
  Such holes are far below `fdm.hole.min_diameter` (2 mm).
- **Sharp corners:** corners sharper than about 62° can fail coverage by construction.
  The owner decided to keep this strict.
- **What is not judged:** strength is not judged.
- **Scope:** the checks hold only for the pinned OrcaSlicer 2.5.0 A1 profile and its
  model-feature list. Overhang wall and Bridge give UNKNOWN until they are seen.

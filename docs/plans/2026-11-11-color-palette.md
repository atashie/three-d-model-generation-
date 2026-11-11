# Color palette and regions (`tdmg.color`, `tdmg colors`) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** build step 1 of the R2 color design (`docs/plans/2026-11-11-color-design.md`).
A reusable module, `tdmg.color`, and a command, `tdmg colors`, turn a `tdmg select`
output into a reviewed color plan: a palette of N suggested colors, a region map cleaned
to printable size, and a preview for the owner. No geometry is built in this step.

**Architecture:** pure, deterministic functions in `src/tdmg/color.py`, with no knowledge
of extrusion, take an RGB image, a mask and resolved settings, and return a `ColorPlan`.
A strict config model in `src/tdmg/color_config.py` resolves the settings: flags, then
the config file, then rules and profile defaults. `write_colors` writes the record and
images in the style of `tdmg select`: canonical JSON, exclusive writes, the record last,
and an id that hashes the identity.

**Tech stack:** numpy, scipy.ndimage (labels, distance), OpenCV GaussianBlur (as
`tdmg.smoothing` uses), Pillow, pydantic, PyYAML, Typer. No new dependency.

**Status:** written 2026-11-11; not started.

**Format:** this follows the repo's plan style (decisions with evidence, then tasks with
tests), not full code. Every task is test-first. Each implementation gets a subagent
spec review and a quality review, then the Codex critical review in Task 8.

## Decisions

1. **Input: a verified `tdmg select` folder.** Read `selection.json`, `mask.png` and
   `cutout.png`, and check them against the record's hashes and `selection_id`, the way
   `tdmg.flat._read_selection` does. Factor that reader into a shared function rather than
   copying it. Colors come from the RGB of `cutout.png`, inside the mask only.
2. **The physical width is required: `--width-mm`.** The cleanup thresholds are in mm, so
   pixels per mm must be known before the preview can show what will print. The record
   holds `width_mm`, and step 2 (`tdmg flat --colors`) refuses a different width.
   `mm_per_px` = width_mm / mask bbox width in px, the same scale as `tdmg flat`.
3. **Palette: k-means in CIELAB, deterministic. Task 1 measures it before it is fixed.**
   - **Method:**
     - convert sRGB to CIELAB (D65, the standard formulas, written out in numpy);
     - initialise with farthest-point seeding from the most frequent color: no random
       numbers, ties broken by the lowest color index;
     - Lloyd iterations in float64 until no pixel changes, or an iteration cap that is
       recorded;
     - weight each unique color by its pixel count.
   - **Order:** by area descending, then by L*, a*, b*.
   - **Hex codes:** the sRGB of each cluster's mean color, rounded.
   - **Base color:** `auto` picks the largest area after cleanup.
   - **Comparison in Task 1:** Pillow's median cut (`Image.quantize`, method MEDIANCUT,
     dither NONE), which is deterministic, in RGB. If median cut is as good on the
     metrics and by eye, prefer it: less code.
4. **Cleanup to printable regions, using the existing R1 rules.** No new numbers:
   - **Thin parts:** within each color's region, pixels removed by an opening of width
     `flat.sliver.opening_width` are reassigned to the neighbouring color that has the
     most of the nearest pixels (ties to the lowest index).
   - **Small pieces:** a 4-connected piece of one color whose area is below
     `flat.island.min_square_side` squared (in nozzle widths, so 0.64 mm² at 0.4 mm) is
     merged into the neighbour color it shares the longest boundary with.
   - Both thresholds convert to pixels through `mm_per_px`.
   - **Repeat until stable** (merging can create new small pieces), with the number of
     passes recorded.
   - **A color left with no pixels is dropped.** The palette shrinks, and the record and
     CLI say so.
   - These are the AMS-printable limits. The glue-only merge (design decision 4) is
     step 2.
5. **Edges: named presets on a shared smoother.**
   - **New function:** `tdmg.smoothing.smooth_labels(labels, sigma_px, supersample)`.
     It blurs each color's indicator with the same Gaussian, upsamples the blurred fields
     by `supersample` (bilinear), and takes the argmax per fine pixel.
   - **Why that works:** every fine pixel gets exactly one color, so regions cannot gap
     or overlap by construction. For two labels it is the 0.5 iso-line R1 uses, because
     the two fields sum to 1.
   - **Outside the mask:** labels come from the nearest masked color, so that step 2 can
     clip to the R1 outline without gaps.
   - **The presets (new rule `color.edges.presets`, a hypothesis):**
     - `smooth`: σ = `flat.smooth.sigma_px` (2.5 px);
     - `exact`: no blur;
     - `furry`: σ = 1.0 px. The 1.0 is a starting guess; the owner judges it on the
       previews in Task 7.
   - **Supersampling:** the factor 4 is a numerical choice for the staircase size (at
     Roadie's scale, 0.072 mm/px / 4 = 0.018 mm, far below a bead). It is stated with
     that reason in the code, like other numerical bounds, and is not a rule.
   - **R1 is unchanged:** `smooth_outline` stays as is. A test checks the two-label case
     agrees with it.
6. **The config file.** `ColorConfig` is a pydantic model with `extra="forbid"`.
   - **Keys in this step:** `colors` (int, 2..cap), `edges` (`smooth | furry | exact`),
     `base` (`auto` or an int index into the palette, assigned after it is known).
   - **Cap:** the printer profile's palette basis (`profiles/printers/bambu-a1.yaml`,
     AMS lite, 4 slots). It is not a new rule.
   - **Defaults:** `colors` 4, `edges` smooth, `base` auto.
   - **Format:** YAML, read with `yaml.safe_load`. Anything that is not a mapping is
     refused, and so are unknown keys and bad values, each with an error naming the
     key.
   - **Precedence:** CLI flags, then the file, then the defaults. The record stores the
     resolved settings, which source each came from, and the config file's SHA-256.
   - Keys for later steps (`min_glue_piece`, `face`) are added in those steps, not now.
7. **Outputs** (`--out DIR`, exclusive, the record written last):
   - `labels.png`: the cleaned region map, 8-bit, the palette index per pixel, 255
     outside the mask. It is at image resolution; the supersampled map is recomputed in
     step 2 from it and the recorded σ, so it is not stored.
   - `regions.png`: the review preview. The original cutout and the palette-painted
     regions sit side by side, with a swatch strip labelled by index, hex code and share
     of the area. Pixels changed by cleanup are outlined.
   - `colors.json` (schema `tdmg.colors/1`): the input hashes and selection_id, the
     resolved settings and their sources, the palette (index, hex, Lab, area share,
     base flag), the cleanup log (passes, pixels reassigned per color, dropped colors),
     the method and its version, the output hashes, the environment, and `colors_id`.
     The id hashes the algorithm version, the selection_id, the cutout pixels' hash and
     the resolved settings; the environment stays outside it.
   - The design's `palette.json` becomes the `palette` section of `colors.json`, so the
     record is one file.
8. **CLI:** `tdmg colors SELECTION_DIR --width-mm W --out DIR [--colors N] [--edges E]
   [--base B] [--config FILE]`.
   - **Exit codes:** 0 written; 2 input, config or I/O error, as for the other commands.
   - **It prints:** the palette, any dropped colors, and the line "open regions.png to
     check the colors before building geometry".

## Tasks

1. **Measure palette methods** (research first, like R1). The script and record go in
   `research/verification/2026-11-1x-color-palette/`.
   - **Inputs:** the owner's Roadie and Oddie selections, at N = 2, 3 and 4.
   - **Methods:** the CIELAB k-means and Pillow's median cut.
   - **Measures:** the mean and 95th-percentile ΔE*76 to the original inside the mask;
     the number of 4-connected pieces and how many are below the island area at 60 mm;
     the run time; whether two runs give identical bytes.
   - Save the previews (git-ignored artifacts; the owner images are not committed).
   - Choose the method from the numbers. Record the choice; Decision 3 is updated if
     median cut wins.
2. **`color_config.py` and the rule.**
   - Add `color.edges.presets` to a new `rules/color.yaml`, with evidence: `smooth` cites
     the existing smoothing record; `furry` and `exact` are hypotheses with stated
     reasons.
   - Run `scripts/gen_docs.py`.
   - **Tests:** defaults; precedence (flag over file over default); refusals (an unknown
     key, `colors` 1 or 5, a bool for `colors`, an unknown `edges` value, a non-mapping
     YAML, a bad path); `base` out of range found after the palette is known; the cap
     read from the profile.
3. **`quantize`** in `color.py`.
   - **Synthetic tests:**
     - exact flat-color shapes give exactly their colors;
     - anti-aliased edges give the core colors, with edge pixels assigned to the nearest;
     - 5 well-separated colors squeezed to 4 merge the closest pair;
     - weights matter (a large area outweighs a small outlier);
     - the same input gives the same output across runs and after shuffling pixel order;
     - pixels outside the mask are ignored;
     - an image with fewer distinct colors than N gives fewer colors, reported.
   - **Lab conversion:** checked against published sRGB → Lab reference values (white,
     black, pure red, green and blue) to the stated precision.
4. **`clean_regions`.**
   - **Synthetic tests:**
     - a 1-px-wide line of a color is reassigned;
     - a speck below the island area is merged into the color around it;
     - a speck touching two colors goes to the longer shared boundary;
     - cascading merges reach a fixed point;
     - a color left empty is dropped;
     - regions above both limits are untouched;
     - thresholds scale with `mm_per_px`;
     - the log counts match the pixel changes.
5. **`smooth_labels`** in `smoothing.py`.
   - **Tests:**
     - every fine pixel has one label;
     - the two-label case matches `smooth_outline`'s polygon within one fine pixel along
       the boundary;
     - `exact` (σ 0) is a pure nearest upsample;
     - a three-color junction gives no unlabeled or doubly labelled pixels;
     - determinism.
6. **Records, preview, CLI.**
   - Add `write_colors`, the `colors` command, and the shared selection reader (moved
     from flat with flat's tests still passing).
   - **Tests:**
     - the record schema and hashes;
     - `colors_id` changes with each identity input and not with the environment;
     - a tampered selection folder is refused;
     - an existing non-empty `--out` is refused;
     - CLI exit codes and output (under `_plain()`, as other CLI tests);
     - the preview's size and that it contains the swatches.
7. **Run on the owner's images and get the owner's review.**
   - Run `tdmg colors` on Roadie and Oddie at 60 mm, N = 4, `smooth`, plus one `furry`
     run each.
   - Record the runs (the record and counts, not the images) in the Task 1 research
     folder.
   - **Owner review:** the owner reviews the `regions.png` previews and says whether the
     colors and merges are right, and whether `furry` is useful. Record the answers
     verbatim. If the owner rejects a preview, change the settings or method before
     step 2.
8. **Docs, STATUS, Codex critical review, push and CI.**
   - **New page:** `docs/print-types/attributes/color-multi.md`, with the template
     headings from `docs/print-types/README.md`.
   - **Pipeline guide:** the `tdmg colors` stage.
   - **STATUS:** this step's results and the next steps.
   - **Codex review:** record it in `research/reviews/2026-11-1x-color-palette/` and
     handle each finding.
   - Then push, and record the CI result in STATUS.

## Out of scope

- **Geometry:** the 3MF, glue pieces and slicing (steps 2–5 of the design).
- **Snapping to owned filaments** (the owner chose suggestions for now).
- **Dithering, gradients and more than the profile's cap.**
- **Interpreting free text:** config keys only.

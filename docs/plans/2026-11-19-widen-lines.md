# Widen thin drawn lines: implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task by task.

**Goal:** a color plan setting `thin_lines: widen` draws thin lines that lie inside one
other color (the red lines on `roadie-thanksgiving`'s turkey) at `line_width_mm`
(default 0.41 mm), on the smoothed fine map, after cleanup and smoothing. The 3D model
then has them. `thin_lines: remove` (the default) changes nothing.

**Design (approved by the owner 2026-11-19, "perfect!"):**
`docs/plans/2026-11-19-widen-lines-design.md`. Read it first. Evidence and prototypes:
`research/verification/2026-11-19-widen-lines/` (`widen_try5.py` = detection,
`widen_try6.py` = drawing on the fine map).

**Architecture:**
- New module `src/tdmg/color_lines.py`:
  - `find_lines`: pure detection on the extracted colors, before the outline step's
    changes matter;
  - `draw_lines`: pure drawing on a fine label map.
- `tdmg.colors.build_colors` calls `find_lines` after `plan_colors` and records the lines
  (ridge points included) in `colors.json`. The preview's fine map gets `draw_lines`.
- `tdmg.colored_flat` applies `draw_lines` from the recorded lines to its own fine map
  (line 493) before `color_regions`.
- `tdmg.colors_verify` validates the new record block.

**Hard constraint: byte-identical when off.** With `thin_lines: remove`, `colors.json`,
`labels.png`, `regions.png` and every later file must be byte-identical to today. The
library entry `prints/roadie-drop` must still verify identical
(`tdmg library verify roadie-drop`, exit 0). So:
- the two new settings are **left out** of `colors.json`'s `settings.settings`,
  `settings.sources` and `identity.settings` when `thin_lines` is `remove`: absent means
  `remove`;
- no new `methods` key, `used_rules` entry or record key appears under `remove`.

`RECORD_SCHEMA` stays `tdmg.colors/4` for `remove` records. A `widen` record is
`tdmg.colors/5`, and verify accepts both. `COLORS_ALGORITHM_VERSION` stays `colors-2`;
the new step is `methods.lines` (`LINES_METHOD = "inside-one-color-lines/1"`), present
only under widen.

**Tech stack:** Python 3.13, numpy, scipy (`ndimage`, `spatial.cKDTree`), opencv
(already used), pydantic, pytest. Nothing new to install.

**Conventions:** read `CLAUDE.md`.
- Every number comes from `rules/` with evidence (`ref` + exact `locator`).
- After a rules change, run `uv run python scripts/gen_docs.py`.
- Run `uv run ruff check .` and the tests named in each task, then the full
  `uv run pytest` before the last commit.
- Each task commits its own files only. Never `git add -A`, and never add anything under
  `jobs/` or `prints/`.

---

### Task 1: the three rules

**Files:** modify `rules/color.yaml`; regenerate `docs/reference/rules.md`. The tests are
the existing `tests/test_rules.py` and `tests/test_docs.py`.

Add, next to `color.outline.keep_width`, with the same fields as it (`kind`, `summary`,
`unit`, `default`, `scales_with_model`, `applies_to: {color: [C2]}`, `evidence`, `notes`):

1. `color.lines.width`:
   - kind `hypothesis`, unit `mm`, default `0.41`, `scales_with_model: false`.
   - Evidence: `docs/plans/2026-11-19-widen-lines-design.md`, locator `make them 0.41 mm
     thick if possible, instead of 0.5`, provenance `unverified`, validation `untested`,
     claim: the owner's choice, a preference, not a print result.
   - A second item from the research README, locator `| Fine map, after smoothing | 0.359
     | 0.384 | 0.384 | 0.409 |`, validation `untested` (software only), claim: drawn on
     the fine map, the median width is 0.409 mm against 0.41 mm.
   - Notes: it must exceed `flat.sliver.opening_width` (refused at or below it); the
     lines are drawn after cleanup, so cleanup's 0.4 mm floor does not apply to them;
     printing at this width is untested.
2. `color.lines.host_share`:
   - kind `hypothesis`, unit `ratio`, default `0.9`.
   - Evidence: the research README, locator `Finds exactly the turkey's lines (264 and
     504 px)`, provenance `primary`, validation `untested`.
   - Notes: the share of the 2 px ring around a candidate, counting no pixel of its own
     color, that is one other color.
3. `color.lines.min_elongation`:
   - kind `hypothesis`, unit `ratio`, default `3`.
   - Evidence: same README, locator `12 extra specks of 13–27 px elsewhere`, claim: with
     no size and length limits the prototype also changed specks; at 3, together with the
     island area, only the lines remain.

Copy each locator exactly from the file; `tests/test_rules.py` proves it exists. Then run
`uv run python scripts/gen_docs.py`, `uv run pytest tests/test_rules.py tests/test_docs.py
-q` and commit (`rules/color.yaml`, `docs/reference/rules.md`, and any generated page that
changed).

### Task 2: the settings

**Files:** modify `src/tdmg/color_config.py`, `src/tdmg/jobs.py` (only if the
`REAL_COLOR_KEYS` tuple needs `line_width_mm`), `src/tdmg/job_runner.py` (the
config-file keys) and `src/tdmg/cli.py` (the `--config` help text). Tests:
`tests/test_color_config.py`, plus job tests where they list color keys.

- `ColorConfig` gets:
  - `thin_lines: Literal["remove", "widen"] | None`, default `"remove"` in `DEFAULTS`;
  - `line_width_mm: OutlineWidth | None`, with a rule default `color.lines.width` in
    `RULE_DEFAULTS` and `RULE_DEFAULT_UNITS` (`mm`).
- Add `check_line_width_setting(width_mm, rules)`. Like `check_outline_width_setting`, it
  refuses a width at or below `flat.sliver.opening_width`, and the message names
  `line_width_mm` and the rule. `resolve_color_config` calls it.
- Both keys are config-file keys, like `outline_width_mm`, not flags. `job_runner` writes
  them into the colors config file when set. `jobs.STAGE_FIELDS["colors"]` gets them
  through `COLOR_KEYS`; check that, and add `line_width_mm` to `REAL_COLOR_KEYS`.
- **The identity rule:** add a helper `recorded_settings(settings, sources)`. It returns
  the settings and sources without `thin_lines` and `line_width_mm` when `thin_lines` is
  `remove`, and unchanged otherwise. Every place that writes `settings` or `sources` into
  `colors.json` or `identity` uses it (Task 5 wires it in; this task adds and tests it).
- Tests:
  - a config of `thin_lines: widen` resolves `line_width_mm` to 0.41 from the rule;
  - `line_width_mm: 0.4` and `0.3` are refused, `0.41` passes;
  - an unknown `thin_lines` value is refused;
  - `recorded_settings` drops both keys under `remove` and keeps them under `widen`;
  - `tdmg job set NAME colors.thin_lines=widen colors.line_width_mm=0.41` is accepted
    (an existing job test pattern).

### Task 3: finding the lines (`find_lines`)

**Files:** create `src/tdmg/color_lines.py` and `tests/test_color_lines.py`.

```python
@dataclass(frozen=True)
class Line:
    color: int            # extraction index of the line's color
    host: int             # extraction index of the color it lies in
    area_px: int
    width_px: float       # 2 x the 90th percentile of the exact EDT inside the part
    length_px: float      # area_px / width_px
    ridge: tuple[tuple[int, int], ...]  # (row, col) of ridge half pixels, sorted

def find_lines(q: Quantized, family: tuple[int, ...], limits: Limits,
               width_px: float, host_share: float, min_elongation: float
               ) -> tuple[Line, ...]:
```

The algorithm, exactly as in `widen_try5.py` (the design, part 2):
1. **The color view.** `view = q.labels`, and each family member's pixels become the
   non-family index nearest to it in CIELAB (`q.lab`; squared distance; ties to the
   lowest index). With an empty family, `view` is `q.labels`.
2. For each non-family color `c`, in index order: the 4-connected components of
   `view == c`, in row-major order of their first pixel. Skip components below
   `limits.min_area_px`.
3. `body = open_mask(component, 2 * width_px)` (`tdmg.color.open_mask`);
   `parts = component & ~body`. Take the 8-connected components of `parts`.
4. For each part with area >= `limits.min_area_px`:
   - **ring:** a 5 × 5 square dilation of the part, minus `view == c`, inside the image;
     OUTSIDE counts as its own value;
   - **host** = the most common ring value (ties: the lowest index). It must not be
     OUTSIDE, and its count / ring size must be >= `host_share`;
   - **width** = 2 × the 90th percentile of `scipy.ndimage.distance_transform_edt` of the
     component (padded by one False pixel) over the part's pixels;
   - **elongation** = area / max(width, 1), and it must be >= `min_elongation`.
5. **ridge** = `stroke_ridge` (from `tdmg.color_outline`) of the part upsampled 2 × 2 (as
   `stroke_band` does); store the nonzero (row, col) in sorted order.
6. Return the lines sorted by (color, first ridge point).

Tests (synthetic, built in the test file):
- A 200 × 200 host square of color 1 with a 4 px-wide curved line of color 0 inside it,
  plus a 1-pixel fringe of a family color 2 on both sides of the line: one `Line` (color
  0, host 1). Its ridge lies within 1 px of the drawn centre line.
- A border between two wide colors with a 2 px strip of a family color along it: no
  line.
- A small round dot of color 0 inside color 1, area above the island area, elongation
  < 3: no line.
- A line of color 0 that joins a wide disc of color 0 (the garnish case): the line part
  is found, and the disc is not.
- Determinism: the same input twice gives equal results.
- A line whose ring is half one color and half another: no line (host share).

### Task 4: drawing the lines (`draw_lines`)

**Files:** `src/tdmg/color_lines.py`, `tests/test_color_lines.py`.

```python
def draw_lines(fine: np.ndarray, supersample: int, lines, width_px: float) -> np.ndarray:
    """lines: iterable of (color_final, host_final, ridge) in the fine map's labels."""
```

1. **Smooth each line's ridge:** each ridge point's position (cell coordinates: row
   `(r + 0.5) / 2`, col `(c + 0.5) / 2` image px) becomes the mean of the line's ridge
   points within 1.5 image px of it (`cKDTree.query_ball_point`; indices sorted before
   averaging). Lines are smoothed independently. 1.5 px is a method constant
   (`RIDGE_SMOOTH_PX`), not a print threshold. Document it in the module docstring as
   the size of the beading it removes (the half-pixel staircase).
2. **Paint:** a fine pixel `(i, j)` has its centre at `((i + 0.5) / s, (j + 0.5) / s)`.
   It becomes `color_final` when its centre is within `width_px / 2` of a smoothed ridge
   point of that line **and** its label is `host_final`. Only nearby fine pixels are
   tested: a bounding box of the ridge plus the radius. Lines are painted in the given
   order.
3. Return a new array of the same dtype; the input is never changed. A line with
   `color_final == host_final` is skipped (the caller records why).

Tests:
- A straight horizontal ridge, `s = 4`, `width_px = 4.9`: the painted band is
  `4.9 × s` fine pixels across, ± 1 fine pixel, at every column away from the ends.
- A quarter-circle ridge of radius 30 px: the width is measured along the normals at 20
  points, each 4.9 ± 0.35 px (0.41 ± 0.03 mm at 0.0836 mm/px).
- A third color crossing the band is unchanged.
- The input array is unchanged; the output dtype equals the input's.

### Task 5: wiring into the plan, the record, verify and the 3D build

**Files:** `src/tdmg/colors.py`, `src/tdmg/colors_verify.py`, `src/tdmg/colored_flat.py`,
`src/tdmg/color_plan.py` (only if a final-index helper is needed). Tests:
`tests/test_colors.py`, `tests/test_colors_verify.py`, `tests/test_colored_flat.py`
(use their existing names), and a byte-identical test.

1. **In `build_colors`:**
   - When `settings.get("thin_lines") == "widen"`:
     - `width_px = settings["line_width_mm"] / mm_per_px`;
     - `lines = find_lines(plan.extracted, plan.outline.family, limits, width_px,
       host_share, min_elongation)`, with both read from the rules.
   - Map each line's `color` and `host` to final indices. Use `plan.final_index`; for a
     merged color, the final index of the color it was merged into. Use the plan's
     existing logic if it has one (`color_plan.final_of`).
   - A line whose color or host has no final index, or whose two final indices are equal,
     is recorded with `"drawn": false` and a reason. It is not drawn.
2. **In the record**, under widen only:
   - `"lines"`: `{"method": LINES_METHOD, "width_mm", "width_px", "rules": {the three
     rule ids: values}, "drawn_after": "cleanup and smoothing, on the fine map",
     "notes": [...], "items": [{"color", "color_hex", "host", "host_hex",
     "color_final", "host_final", "area_px", "width_px", "length_px", "drawn",
     "reason", "ridge": [[r, c], ...]}]}`;
   - `methods["lines"] = LINES_METHOD`;
   - `used_rules` (the identity's rules) gains `color.lines.host_share` and
     `color.lines.min_elongation`. `color.lines.width` stays out of it, as
     `color.outline.keep_width` does: the `line_width_mm` setting value is hashed instead
     (decided after the Task 2 quality review). The `lines` block's `rules` field still
     lists all three, as information;
   - use `color_config.widens(settings)` for every "is this a widen plan" test;
   - `RECORD_SCHEMA` becomes `tdmg.colors/5`.
   - The settings go through `recorded_settings` (Task 2).
   - **Under remove, nothing above appears**, and the schema stays `tdmg.colors/4`.
3. **The preview:** after `smooth_labels`, apply `draw_lines` with the drawn items before
   `_regions_image`. Add a legend line, for example `lines: 3 drawn at 0.41 mm after
   cleanup (thin_lines: widen); untested in print`. Under remove the preview is
   unchanged.
4. **The note** in `lines.notes`: "drawn after cleanup and smoothing, so cleanup's
   flat.sliver.opening_width floor does not apply to them; printing them at this width is
   untested".
5. **`colors_verify`:**
   - accept schema 4 without `lines` and schema 5 with `lines`; refuse widen in a
     schema-4 record and remove in a schema-5 one;
   - require `methods.lines`, `color.lines.host_share` and `color.lines.min_elongation`
     in `identity.rules`, and the settings keys
     exactly when `thin_lines` is widen (extend the `want` set at line ~273);
   - validate the block's types (ints for the indices and ridge points, finite numbers);
   - the rebuild (`render=False`) must give the same `lines` block, ridge included.
6. **`colored_flat`:** after `fine = smooth_labels(...)`, when the plan's record has a
   `lines` block, apply `draw_lines` with its drawn items and its `width_px`. Under
   widen with at least one drawn line, build no glue version: set `build_glue = False`
   and give a reason in the record, as for a kept outline band. Record the number of
   lines drawn in the colored_flat record only when the plan has `lines` (byte-identical
   otherwise).
7. **Tests:**
   - **Byte-identical:** build a plan from an existing small fixture under `remove`, and
     compare `colors.json`, `labels.png` and `regions.png` bytes with the same build
     before this change. Store expected SHA-256s, or reuse the repo's existing golden
     test if one exists. Run `uv run pytest -m slicer -k library` (or the existing
     `library verify roadie-drop` test) with the slicer env vars from `CLAUDE.md`.
   - A synthetic widen plan end to end through `make_colors` and `make_colored_flat`:
     the line's color appears in the AMS inlay polygons along the line, and the polygon
     is about `line_width_mm` wide (measure the shapely polygon's area / length).
   - `colors_verify` passes a widen plan, and fails it when the ridge is edited.

### Task 6: docs, skill, and the real job

**Files:** `docs/guide/pipeline-and-gate.md` (the colors section: step 6 after
smoothing, the settings, the record), `docs/print-types/attributes/color-multi.md` (keep
the template headings), `.claude/skills/make-print/SKILL.md` (step 6: replace "planned,
not built yet" with how to use it), `docs/plans/2026-11-19-widen-lines-design.md` (mark
it built, with the commit), `docs/STATUS.md`. Then `uv run python scripts/gen_docs.py`
and `uv run python scripts/evidence_inventory.py`.

The controller (not a subagent) then runs `roadie-thanksgiving`:
- `tdmg job set roadie-thanksgiving colors.thin_lines=widen`, then `job run`;
- look at `regions.png` and the crops;
- report to the owner, who confirms the colors and gives the thickness;
- build and slice, and report the verdict.

### Task 7: Codex review

Run as in `research/reviews/2026-11-16-restructure/README.md`:

```bash
codex exec --sandbox read-only --ephemeral -C <repo> -o codex-review.txt "$(cat prompt.md)"
```

Review the diff from the commit before Task 1. Save the prompt and response under
`research/reviews/2026-11-19-widen-lines/`. Reproduce each finding with a failing test
before fixing it, and record how each was handled in that folder's README.

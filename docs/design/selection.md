# Design note: subject selection (`tdmg select`)

Stage S0/S1: pick the part of the image that becomes the model. The command writes a
mask, a cutout, a preview and `selection.json`. The code and `rules/perception.yaml`
are the source of truth; this note says why they are the way they are.

## Decisions in force

- **Plain-language instructions, applied by explicit controls** (owner, 2026-11-09,
  PLAN Q6; accepted by "proceed", 2026-11-10). The user's words are stored verbatim with
  `machine_interpreted: false`. Code applies only explicit controls: `--remove-at`,
  `--keep-at`, `--tolerance`, `--alpha-min` or a corrected `--mask`. A phrase grammar or
  an opt-in LLM could later propose the same controls (CLAUDE.md rule 1).
- **Selection comes first in R1** (owner, 2026-11-10).
- **The owner's images are not committed** until their rights are confirmed (Oddie looks
  like a commercial game character). Tests use synthetic look-alikes; the real images
  run only locally and record hashes and counts.
- **The design comes from measurement:** Roadie's "grey" disc is opaque, color alone
  splits the bird, and "remove the disc at a point, then keep the piece at a point"
  keeps the bird whole at tolerances 20 to 40.
- **The tool reports facts, not verdicts:** `status` is `empty`, `one_piece` or
  `multiple_pieces`. Whether the right subject was chosen is the user's call, from the
  preview. The owner confirmed both selections (Roadie at tolerance 30, one 74,768 px
  piece; Oddie from its transparency, one 298,172 px piece).
- **Only the image's name and hashes are recorded,** not a copy. Replaying a run needs
  the source image (guide: `docs/guide/input-interpretation.md`). The restructure design
  (decision 5) keeps each finished print's source in a git-ignored
  `prints/<name>/source/` (`tdmg finish`, restructure Task 9, 2026-11-17).

## Review findings that still constrain the code

From the Codex review of 2026-11-10 (removed record, see below), each fixed in `33cbb52`:
- `Intake` keeps a read-only pixel copy, and `Selection` keeps a JSON snapshot; the
  identity and record are built only from the snapshot, so changing an object after
  selection cannot change provenance.
- The output folder is created exclusively when new, PNGs are created in exclusive
  mode, and the temporary record name is unique, so two writers cannot overwrite each
  other. `selection.json` is written last: a folder without it is incomplete.
- Pillow's `DecompressionBombError` becomes a `SelectionError` (exit 2, not a crash).
- Masks are validated on their decoded channels with no rounding: strictly black and
  white, opaque, no EXIF rotation. Unsupported modes are refused.
- The guide's memory figures come from `measure_memory.py` and `memory.txt` in
  [the selection record](../../research/verification/2026-11-10-subject-selection/).

## Records and plans

- Plan: [`docs/plans/2026-11-10-subject-selection.md`](../plans/2026-11-10-subject-selection.md)
  (decisions, and execution notes listing every change from the plan text).
- Measurements: [`research/verification/2026-11-10-subject-selection/`](../../research/verification/2026-11-10-subject-selection/README.md).
- Guide: [input interpretation](../guide/input-interpretation.md).

## Removed records

- `research/reviews/2026-11-10-selection/`: the Codex review of `tdmg select` (commits
  `c015619..27d5423`), 7 findings, all confirmed and handled. Removed in commit
  `814a962723454efa7693b8ef8af715062368975a` (see git history, or tag
  `pre-restructure`). Where each point lives now:
  - findings 1 to 4 and 7: the list above, and the plan's execution notes;
  - finding 5 (the guide overstated keeping the original image): fixed in the guide,
    which says replay needs the source image; summarised above;
  - finding 6 (the plan's embedded YAML kept an overclaim, its status was stale): fixed
    in the plan itself (status line and execution notes);
  - "after the fixes: 251 tests pass, golden `selection_id` unchanged": a point-in-time
    result, judged obsolete (the suite has grown; the golden id is pinned by a test).

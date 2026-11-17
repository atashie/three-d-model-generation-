# Jobs and legacy data

How print jobs, the library and today's `artifacts/` folder fit together, and what was
done with each `artifacts/` folder when the restructure began (plan Task 13,
2026-11-17).

## Jobs and the library

- A job is `jobs/<name>/` (git-ignored): `job.yaml`, `source/` and one folder per
  stage. It is made with `tdmg job new`, changed with `tdmg job set`, run with
  `tdmg job run`, and confirmed with `tdmg job confirm` in the owner's own words.
- A finished print is `prints/<name>/`, written by `tdmg finish` after a rebuild proof
  and the owner's separate purge permission. The source image and non-public printable
  files stay git-ignored. `tdmg library check` and `tdmg library verify` check it later.
- How Claude walks the owner through a job: `.claude/skills/make-print/SKILL.md`.
- Design: [the restructure design](../plans/2026-11-16-restructure-design.md), sections 3
  to 5.

## Legacy data in `artifacts/` (inventory of 2026-11-17)

`artifacts/` is git-ignored. Before the restructure it held every run, review preview
and tool. The owner decided what happens to each group (2026-11-17):
- Roadie, outline dropped (the printed version): "Yes, after finish (Recommended)".
- The other Roadie variants: "Keep as open legacy (Recommended)".
- Old exploratory runs: "Delete now (Recommended)".
- Environments: "Keep all (Recommended)".

Deletion follows the lists below only, never a parent folder or a partial name. Records
in `research/` that name a deleted path stay as written; the path then exists only on
the machine's history, not on disk.

### Kept: tools and environments

| Path | What it is |
|---|---|
| `tools/` | The pinned OrcaSlicer 2.5.0 and PrusaSlicer 2.9.7 (needed by every slice) |
| `TripoSR/`, `torchmcubes/`, `triposr-data/`, `triposr-env/`, `triposr-py311/`, `triposr-runs/` | The photo-to-3D trial (R4 backend research; record `research/experiments/2026-11-g3-local-vs-hosted/`) |
| `makerlab/` | The owner's MakerLab STL (same experiment) |
| `pc-optional/`, `wheeltest/` | One-off environment checks (records in `research/verification/2026-11-09-pc-stack/`) |
| `test-strips/` | The calibration strip run (skin strip printed; clearance strip not yet) |

### Kept: open legacy work (current plans and variants)

| Path | Belongs to |
|---|---|
| `selection-runs/roadie-tol30/` | Shared by every Roadie variant; also the owner-image test fixtures' fallback |
| `selection-runs/oddie/` | Oddie (no job yet; the test fixtures need it) |
| `colors-runs/configs/` | The color configs of the owner's plans |
| `colors-runs/roadie-tol30-60-keep-v4-f64/`, `colored-runs/roadie-tol30-60-keep-v4-f64/`, `color-review/roadie-tol30-60-keep-v4-f64/`, `slice-runs/fd8/roadie-tol30-60-keep-v4-f64/` and `.txt` | Roadie, outline kept (not printed) |
| `flat-runs/roadie-tol30-60x3-s5/`, `slice-runs/fd8/roadie-r1/` and `.txt` | Roadie single color (R1; printed earlier from a previous flat version) |
| `colors-runs/oddie-60-merge-blues-v3-f64/`, `colored-runs/oddie-60-merge-blues-v3-f64/`, `color-review/oddie-60-merge-blues-v3-f64/`, `slice-runs/fd8/oddie-60-merge-blues-v3-f64/` and `.txt` | Oddie, blues merged |
| `colors-runs/oddie-60-keep-merge-blues-greens-v4-f64/`, `colored-runs/oddie-60-keep-merge-blues-greens-v4-f64/`, `color-review/oddie-60-keep-merge-blues-greens-v4-f64/`, `slice-runs/fd8/oddie-60-keep-merge-blues-greens-v4-f64/` and `.txt` | Oddie, outline kept, blues and greens merged (the owner's preferred Oddie) |
| `flat-runs/oddie-60x3-s5/`, `slice-runs/fd8/oddie-r1/` and `.txt` | Oddie single color (R1) |

How "current" was found: each `slice-runs/fd8/` record's `links` name the colored or
flat record it was sliced from, by SHA-256 (checked 2026-11-17).

### Deleted after Roadie's finish: Roadie, outline dropped

Only after `tdmg finish roadie-drop` has published `prints/roadie-drop/` and
`tdmg library check roadie-drop` passes:
- `colors-runs/roadie-tol30-60-drop/`, `-drop-v2/`, `-drop-v3/`, `-drop-v3-f64/`,
  `roadie-tol30-60-drop-v3.log`;
- `colored-runs/roadie-tol30-60-drop-v3-f64/` (holds the printed `model.3mf`, SHA-256
  `ec296118…22d7`; the library holds an identical copy);
- `color-review/roadie-tol30-60-drop-v3-f64/`;
- `slice-runs/color-roadie-tol30-60-drop-v3-f64/`, `color2-roadie-tol30-60-drop-v3-f64/`,
  `color2-roadie-tol30-60-drop-v3-f64-both/`, `color5-roadie-drop-v3-f64/`,
  `color5-roadie-drop-v3-f64-down/`, `color5-roadie-drop-v3-f64.txt`;
- `slice-runs/fd6/roadie-tol30-60-drop-v3-f64-down/`, `-up/` and their `.txt`;
  `slice-runs/fd7/roadie-tol30-60-drop-v3-f64/` and `.txt`;
  `slice-runs/fd8/roadie-tol30-60-drop-v3-f64/` and `.txt`.

### Deleted now: old exploratory runs

Superseded runs and previews; their findings are in the kept records and design notes.
- Early tests: `3mf-import-test/`, `det1.3mf`, `det2.3mf`, `pc-flat/`.
- Palette and preview trials: `color-palette-runs/`, `color-palette-runs-2/`,
  `color-palette-runs-3/`, `colors-review/`, `colors-review-2/`, `colors-review-3/`,
  `outline-shade-runs/`, `wide-holes-runs/`, `selection-planning/`.
- Selection trials: `selection-runs/roadie-tol20/`, `roadie-tol30-repeat/`,
  `roadie-tol40/`, `tolerance-comparison.png`.
- Superseded color plans: every `colors-runs/` entry not listed above as kept or as
  Roadie drop (older `-v2`, `-v3`, `furry`, `smooth`, `default`, `w050` runs and logs).
- Superseded flat runs: every `flat-runs/` entry except the two `-s5` folders.
- Superseded slice runs: every `slice-runs/` entry except `fd8/` and the Roadie drop
  entries above (the early `color-`, `color2-`, `color3-`, `color5-` keep runs, the
  `-60x3-` R1 runs and their logs, and `fd6/` and `fd7/` apart from Roadie drop's).
- The Task 0 repeat runs: `repeat-runs/` (record:
  `research/verification/2026-11-16-repeatability/`, which keeps the report).

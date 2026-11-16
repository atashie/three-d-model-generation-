# research/: the evidence

This folder holds the records that the rules, tests, profiles, code and docs cite:
- `verification/`: measurements and runs on our machines, each with its date, machine
  and commands;
- `reviews/`: independent reviews (OpenAI Codex, and others), with how each finding was
  handled;
- `experiments/`: larger trials, such as the photo-to-3D backend test.

**Records are kept intact and never rewritten** (CLAUDE.md rule 6). A later correction
goes in a dated note or a new record, not over the old text. A record that nothing
cites may leave the working tree once its work is done, after its standing decisions
are in [docs/design/](../docs/design/README.md); git history keeps it.

**Links inside a record may name a removed path.** They stay as written. To read a
removed record, use git history, or check out the tag `pre-restructure` (the tree before
the 2026-11-16 restructure).

## Removed records

Removed in commit `814a962723454efa7693b8ef8af715062368975a` (owner, 2026-11-16: "Remove
5, keep pc-stack (Recommended)"). Their standing decisions and findings are in the
design notes named here.

| Old path | What it was | Now summarised in |
|---|---|---|
| `research/reviews/2026-11-10-flat/` | Codex review of `tdmg flat` | [docs/design/flat.md](../docs/design/flat.md) |
| `research/reviews/2026-11-10-selection/` | Codex review of `tdmg select` | [docs/design/selection.md](../docs/design/selection.md) |
| `research/reviews/2026-11-10-slicer/` | Codex review of the slicer check | [docs/design/slicing.md](../docs/design/slicing.md) |
| `research/reviews/2026-11-10-smoothing/` | Codex review of outline smoothing | [docs/design/flat.md](../docs/design/flat.md) |
| `research/verification/2026-11-10-flat-geometry/` | First `tdmg flat` runs on the owner's selections | [docs/design/flat.md](../docs/design/flat.md) |

## Finding what cites a record

[docs/design/evidence-inventory.md](../docs/design/evidence-inventory.md) lists every
reference to every record, by file and line, and marks each record cited or uncited.
Regenerate it with `uv run python scripts/evidence_inventory.py`.

# Design notes

One note per area of the pipeline. Each note holds:
- the decisions still in force, with the owner's words and dates;
- the review findings that still constrain the code;
- links to the evidence in `research/` and the plans in `docs/plans/`;
- the records removed from the working tree that covered the area, with the commit that
  removed them.

A note is a short summary. The code and `rules/*.yaml` are the source of truth for
behaviour and numbers; the records and plans are the evidence. When a decision changes,
update the note and keep only the current decision, with "replaced ... on <date>".

| Note | Area |
|---|---|
| [selection.md](selection.md) | Choosing the subject in the image (`tdmg select`) |
| [flat.md](flat.md) | Flat solids and outline smoothing (`tdmg flat`) |
| [color.md](color.md) | Color plans, colored solids and the multicolor 3MF (`tdmg colors`, `tdmg flat --colors`) |
| [slicing.md](slicing.md) | Slicing and the checks read from the G-code (`tdmg slice`) |
| [calibration.md](calibration.md) | Test strips (`tdmg strip`), calibrated rules and prints so far |
| [evidence-inventory.md](evidence-inventory.md) | Generated: which records the repository cites, and from where |

The evidence folder is described in [research/README.md](../../research/README.md). The
whole design and its reasons are in [docs/PLAN.md](../PLAN.md); the restructure that
created this folder is [docs/plans/2026-11-16-restructure-design.md](../plans/2026-11-16-restructure-design.md).

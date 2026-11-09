# three-d-model-generation

Turn an image into a file a 3D printer can print: a 3MF, or an STL when that is enough.

The pipeline is deterministic code. Machine learning appears only where no rule can do the job: cutting the subject out of a photo, estimating depth, and inventing 3D shape the camera never saw. Code, not a model's judgment, decides whether the result is printable. Every number the pipeline uses comes from a cited source.

**Status:** Phase 0 (foundations). Nothing prints yet. See the [roadmap](docs/PLAN.md#11-roadmap).

**Target printer:** Bambu Lab A1 ([profile](profiles/printers/bambu-a1.yaml)). Files are portable: standard 3MF, no dependence on the AMS unit or the slicer, checked in OrcaSlicer and PrusaSlicer, and confirmed by hand in Bambu Studio.

## Start here

- New to 3D printing files? Read [docs/guide/00-start-here.md](docs/guide/00-start-here.md).
- The design and its reasons: [docs/PLAN.md](docs/PLAN.md).
- Print types and recipes: [docs/print-types/README.md](docs/print-types/README.md).
- Every design rule and its evidence: [docs/reference/rules.md](docs/reference/rules.md).
- The research behind it: [reports/Image to printable 3D model landscape.md](reports/Image%20to%20printable%203D%20model%20landscape.md).

## Setup

Needs [uv](https://docs.astral.sh/uv/). Python 3.13 is pinned and uv installs it.

```bash
uv sync                                   # create .venv from uv.lock
uv run pytest                             # run the tests
uv run tdmg rules                         # list the design rules
uv run tdmg recipes                       # list the print recipes
uv run python scripts/gen_docs.py         # regenerate the generated docs
```

Optional extras: `uv sync --extra perception` adds background removal; `uv sync --extra analysis` adds PyMeshLab (GPL-3.0).

## Layout

| Path | Contents |
|---|---|
| `src/tdmg/` | The Python package and the `tdmg` command |
| `rules/` | Design rules with evidence (YAML) |
| `profiles/` | Printer and filament profiles |
| `docs/` | Guide, print-type pages, generated reference |
| `tests/` | Tests, including checks that docs and citations agree with code |
| `research_notes/`, `reports/` | Landscape research, November 2026 |
| `research/` | Local verification experiments and independent reviews |

## Licence

MIT, see [LICENSE](LICENSE). Some dependencies are not MIT; see [docs/reference/dependencies.md](docs/reference/dependencies.md).

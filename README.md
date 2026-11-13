# three-d-model-generation

Turn an image into a file a 3D printer can print: a 3MF, or an STL when that is enough.

The pipeline is deterministic code. Machine learning appears only where no rule can do the job: cutting the subject out of a photo, estimating depth, and inventing 3D shape the camera never saw. Code, not a model's judgment, decides whether the result is printable. Every number the pipeline uses comes from a cited source.

**Status:** Phase 0 foundations are complete. Phase 1 (R1, flat single-color) is in progress: `tdmg select` picks the subject, `tdmg flat` makes a gated flat STL, and `tdmg slice` slices it with a pinned OrcaSlicer and checks the G-code. R2 (flat multicolor) has `tdmg colors` (a reviewed color plan), `tdmg flat --colors` (gated STL bodies for an AMS print and a glue-together version, and the AMS bodies as one multicolor `model.3mf`), and `tdmg slice` on that folder (each color on its own filament, face up by default, with the color changes and waste read from the G-code). On the owner's four color plans, face up is PRINTABLE with warnings (2026-11-13); nothing multicolor has been printed. There is no keychain loop or base yet. With a pinned PrusaSlicer, `tdmg slice` also measures `F6.portability`; the owner's Roadie and Oddie single-color STLs passed every required check (PRINTABLE, 2026-11-11, and again on 2026-11-13 with the A1's own start G-code; see STATUS for what that does and does not mean). The owner printed one Roadie STL from `tdmg flat`, sliced in Bambu Studio, and judged it "great" by eye; nothing was measured. See [current status and session handoff](docs/STATUS.md) and the [roadmap](docs/PLAN.md#11-roadmap).

**Target printer:** Bambu Lab A1 ([profile](profiles/printers/bambu-a1.yaml)). The planned output is portable standard 3MF, independent of AMS slots and slicers. The OrcaSlicer check exists (`tdmg slice`, set up on Windows x64 only), and so does the PrusaSlicer check (`F6.portability`, with `--prusaslicer-dir`). Bambu Studio is checked by hand by the owner.

## Start here

- New to 3D printing files? Read [docs/guide/00-start-here.md](docs/guide/00-start-here.md).
- The design and its reasons: [docs/PLAN.md](docs/PLAN.md).
- Choosing what in an image becomes the model (`tdmg select`): [input interpretation](docs/guide/input-interpretation.md).
- What each command checks, and what "printable" means: [pipeline and gate](docs/guide/pipeline-and-gate.md).
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
uv run tdmg select IMAGE --out DIR ...    # select the subject; writes a preview to check
uv run tdmg flat SEL_DIR --width-mm W --thickness-mm T --out DIR   # flat solid + gate
                                          # (outline smoothed by default; --smooth-px 0 = exact)
uv run python scripts/setup_orcaslicer.py --dest artifacts/tools/orcaslicer-2.5.0   # once, Windows x64
uv run tdmg slice FLAT_DIR --out DIR --slicer-dir artifacts/tools/orcaslicer-2.5.0  # G-code + F3/F6
                                          # (FLAT_DIR may be a tdmg flat --colors folder; --face up|down|both)
uv run python scripts/gen_docs.py         # regenerate the generated docs
```

Optional extras: `uv sync --extra perception` adds background removal; `uv sync --extra analysis` adds PyMeshLab (GPL-3.0).

On the tested Windows Python 3.13 environment, several optional packages install
but fail native imports. See [PC verification](research/verification/2026-11-09-pc-stack/README.md).
TripoSR runs in a separate Python 3.11 environment; it is an experiment, not part
of `tdmg` or a reason to change the core Python pin. CI covers Windows, Linux,
and macOS arm64; see the status page for verification state.

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

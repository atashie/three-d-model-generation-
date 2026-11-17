# three-d-model-generation

Turn an image into a file a 3D printer can print: a 3MF, or an STL when that is enough.

The pipeline is deterministic code. Machine learning appears only where no rule can do the job: cutting the subject out of a photo, estimating depth, and inventing 3D shape the camera never saw. Code, not a model's judgment, decides whether the result is printable. Every number the pipeline uses comes from a cited source.

**Status:** Phase 0 foundations are complete. Phase 1 (R1, flat single-color) is in progress: `tdmg select` picks the subject, `tdmg flat` makes a gated flat STL, and `tdmg slice` slices it with a pinned OrcaSlicer and checks the G-code. R2 (flat multicolor) has `tdmg colors` (a reviewed color plan), `tdmg flat --colors` (gated STL bodies for an AMS print and a glue-together version, and the AMS bodies as one multicolor `model.3mf`), and `tdmg slice` on that folder (each color on its own filament, both faces by default since 2026-11-16, face down preferred when it is PRINTABLE, with the color changes and waste read from the G-code). On the owner's four color plans, face up is PRINTABLE with warnings (2026-11-13); after the 2026-11-16 changes, face down is PRINTABLE for the two outline-dropped plans and FAILs for the two outline-kept ones. One multicolor figure has been printed: Roadie (outline dropped), on the AMS from Bambu Studio's own slice of `model.3mf`; face up it came out smeared, face down the owner judged it good by eye (`research/verification/2026-11-15-first-ams-print/README.md`; nothing measured). Oddie has not been printed. `tdmg strip` makes two calibration test strips, for the glue clearance and the skin depth, and a form to record the results; the owner printed the skin strip (every depth from 0.2 mm opaque; 0.6 mm kept, now calibrated) and skipped the clearance strip, so the 0.2 mm glue gap is still untested (2026-11-15). There is no keychain loop or base yet. With a pinned PrusaSlicer, `tdmg slice` also measures `F6.portability`; the owner's Roadie and Oddie single-color STLs passed every required check (PRINTABLE, 2026-11-11, and again on 2026-11-13 with the A1's own start G-code; see STATUS for what that does and does not mean). The owner printed one Roadie STL from `tdmg flat`, sliced in Bambu Studio, and judged it "great" by eye; nothing was measured. See [current status and session handoff](docs/STATUS.md) and the [roadmap](docs/PLAN.md#11-roadmap).

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
                                          # (FLAT_DIR may be a tdmg flat --colors folder; --face up|down|both|auto)
uv run tdmg strip OUT --slicer-dir artifacts/tools/orcaslicer-2.5.0     # the two calibration test strips
                                          # + results-template.md, the form to fill in after printing
uv run tdmg job new NAME --class flat-icon --image PATH [--colors]   # start a job in jobs/NAME/:
                                          # the image in source/ and job.yaml
uv run tdmg job set NAME flat.width_mm=60 flat.thickness_mm=3   # change the job's parameters
uv run tdmg job run NAME --slicer-dir artifacts/tools/orcaslicer-2.5.0   # run the stages not done
uv run tdmg job status NAME               # each stage: done, stale or not run; what waits for you
uv run tdmg job confirm NAME --subject print --face down --owner-said "THE OWNER'S WORDS"
                                          # record the owner's words (selection|colors|print)
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
| `docs/` | Guide, print-type pages, generated reference, plans (`docs/plans/`) |
| `docs/design/` | [Design notes](docs/design/README.md): the decisions in force per area, with links to the evidence |
| `tests/` | Tests, including checks that docs and citations agree with code |
| `research_notes/`, `reports/` | Landscape research, November 2026 |
| `research/` | [The evidence](research/README.md): verification records, independent reviews and experiments that rules, tests, profiles, code and docs cite, kept intact |

## Licence

MIT, see [LICENSE](LICENSE). Some dependencies are not MIT; see [docs/reference/dependencies.md](docs/reference/dependencies.md).

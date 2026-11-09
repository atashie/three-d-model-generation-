# Working on this repo

This repo turns an image into an FDM-printable 3MF/STL. The owner is a data scientist new to 3D printing. They want vetted evidence over priors, deterministic code over LLM judgment, and every implementation double-checked. Read `docs/PLAN.md` before changing the design.

## Rules for every change

1. **No LLM calls in the runtime pipeline.** LLMs may help write code and docs; they never decide at run time.
2. **No unexplained numbers.** Every threshold, clearance or limit lives in `rules/*.yaml` with evidence. Each evidence item has a `ref` (a file in this repo) and an exact `locator` string that must appear in that file. `tests/test_rules.py` enforces this.
3. **Keep three things separate** for each rule: `kind` (normative, tool_limit, empirical, hypothesis), `provenance` (primary, secondary, unverified), and `validation` (untested, source-tested, peer-reviewed, calibrated). Never upgrade one without new evidence.
4. **Never call something verified unless it was run.** Distinguish resolved, installed and imported, functionally tested, and runtime-validated.
5. **Docs agree with code.** Generated tables come from the registries. After changing `rules/` or `src/tdmg/recipes.py`, run `uv run python scripts/gen_docs.py`. Attribute and recipe pages keep the template headings (see `docs/print-types/README.md`).
6. **Research files are records.** Do not rewrite `research_notes/`. Correct `reports/` only with a revision-history entry, and keep the old version in git.
7. **Licences:** the repo is MIT. GPL and non-commercial tools may be optional extras or subprocess tools only. Never copy their code into the repo.

## Commands

```bash
uv sync                               # Python 3.13 environment from uv.lock
uv run pytest                         # all tests
uv run python scripts/gen_docs.py     # regenerate docs/reference/rules.md and docs/print-types/recipes.md
uv run ruff check .                   # lint
```

## Environment facts (verified 2026-11-08/09 on the target Mac)

- Apple M5, 16 GB, no CUDA. Python 3.13 is pinned: it is the only version with both `bpy` and orca123d.
- trimesh needs `networkx` and `lxml` to load 3MF. Pass `engine=` to `trimesh.creation.extrude_polygon` explicitly.
- lib3mf and trimesh write random UUIDs into 3MF; set them explicitly for reproducible files.
- OrcaSlicer exit codes reach a parent process as the low 8 bits (−50 → 206, −51 → 205, −59 → 197).

## Review practice

Independent reviews by OpenAI Codex live in `research/reviews/`. Verify every finding against its source before applying it, and record how each one was handled.

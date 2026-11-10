# Working on this repo

This repo turns an image into an FDM-printable 3MF/STL. The owner is a data scientist new to 3D printing. They want vetted evidence over priors, deterministic code over LLM judgment, and every implementation double-checked.

**Start every session by reading `docs/STATUS.md`** (where things stand, machines, next steps, open questions), then `docs/PLAN.md` before changing the design. Update `docs/STATUS.md` before ending a session.

## Rules for every change

1. **No LLM calls in the default runtime pipeline.** LLMs help write code and docs. An optional LLM-assisted mode may come later only behind an explicit flag; it may propose parameters, and its output must pass the same gate (docs/PLAN.md section 2).
2. **No unexplained numbers.** Every threshold, clearance, limit or acceptance target lives in `rules/*.yaml` with evidence. Each evidence item has a `ref` (a file in this repo) and an exact `locator` string. `tests/test_rules.py` proves the text exists; it cannot prove the text supports the value, so check that by reading whenever a rule changes.
3. **Keep three things separate** for each rule: `kind` (normative, tool_limit, empirical, hypothesis), `provenance` (primary, secondary, unverified), and `validation` (untested, measured = software behaviour measured without printing, source-tested = printed by the source, peer-reviewed, calibrated = printed on our printer). Never upgrade one without new evidence.
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
uv run python scripts/setup_orcaslicer.py --verify-only artifacts/tools/orcaslicer-2.5.0   # check the pinned slicer (Windows x64)
TDMG_ORCASLICER_DIR=artifacts/tools/orcaslicer-2.5.0 uv run pytest -m slicer               # real-slicer test
```

## Environment facts (each says where and when it was verified; re-verify on any other machine)

- M5 Mac, 2026-11-08/09: Apple M5, 16 GB, no CUDA. Python 3.13 is pinned: it is the only version with both `bpy` and orca123d.
- M5 Mac, 2026-11-08/09: trimesh needs `networkx` and `lxml` to load 3MF. Pass `engine=` to `trimesh.creation.extrude_polygon` explicitly.
- M5 Mac, 2026-11-08/09: lib3mf and trimesh write random UUIDs into 3MF; set them explicitly for reproducible files.
- On macOS/Linux, OrcaSlicer exit codes are recorded as reaching a parent as the low 8 bits (−50 → 206, −51 → 205, −59 → 197). This comes from 2026-11-08/09 research notes; it has **not been re-measured with OrcaSlicer 2.5.0**, and the pin file marks POSIX decoding "assumed". Do not apply it to Windows.
- On Windows (measured 2026-11-10, OrcaSlicer 2.5.0 portable), Python receives the full 32-bit code as unsigned (−50 → 4294967246, −6 → 4294967290, −3 → 4294967293). A slicer exit of 0 does not mean the mesh is valid: an open cube sliced to 10 of 100 layers with exit 0. See `research/verification/2026-11-10-orcaslicer-windows/`.
- M5 Mac, 2026-11-09: trimesh `is_watertight` and lib3mf `IsManifoldAndOriented` both pass two solids touching at one vertex; check vertex-manifoldness separately (`tdmg.checks` does).
- Under `GITHUB_ACTIONS`, Rich styles Typer usage errors with escape codes and a box, even with `NO_COLOR` set. CLI tests normalise the output with `_plain()`. Reproduce it locally with `CI=true GITHUB_ACTIONS=true uv run pytest` (verified 2026-11-10 on the PC).
- The package reads `rules/` and `profiles/` from the checkout; a built wheel carries copies in `tdmg/_data/` (CI tests this).

## Review practice

Independent reviews by OpenAI Codex live in `research/reviews/`. Verify every finding against its source before applying it, and record how each one was handled.

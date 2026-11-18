You are doing an independent, critical and adversarial review of BUILT code in this repository: the restructure carried out by docs/plans/2026-11-16-restructure.md (Tasks 0 to 14) against its design docs/plans/2026-11-16-restructure-design.md (draft 2). The change is `git diff pre-restructure..HEAD`. Read CLAUDE.md first (the project's rules: no unexplained numbers, rules with evidence, keep kind/provenance/validation separate, never call something verified unless it was run, docs agree with code, records are evidence). Then read docs/STATUS.md and the design. Do not modify files. You may run read-only commands and tests (`uv run pytest tests/test_jobs.py` etc.); say which you ran.

Main code: src/tdmg/recipes.py, jobs.py, job_runner.py, confirmations.py, library.py, cli.py (job/finish/library commands, main()), records.py; the skill .claude/skills/make-print/SKILL.md; .gitignore and .gitattributes; tests/test_jobs.py, test_job_runner.py, test_job_confirm.py, test_finish.py, test_library.py, test_owner_fixtures.py, conftest.py. The first real library entry is prints/roadie-drop/ (its source/ is git-ignored and absent in a clone); the record of that finish is research/verification/2026-11-17-first-finish/.

Owner decisions are not defects: the owner runs everything through Claude Code; records stay in place under research/; the library is prints/<name>/ with a git-ignored source/ and private/; public is asked per print; a rebuild proof comes before any purge; no package split until figurines start.

Look hardest for:
1. **Purge safety.** Can `tdmg finish` (or a resumed one) delete anything outside jobs/<name>/, delete before the library entry is provably complete and correct, follow links or junctions, or delete files a later step needs? Can purge words or a confirmation be recorded that the owner never gave?
2. **Integrity of the library.** Can an entry pass `tdmg library check` while being wrong (a forged or edited COMPLETE/STAGED/purge.json/provenance.json, a swapped printable file, a confirmation that does not cover the published file)? Can `library verify` report "identical" when it is not?
3. **Job staleness and input keys.** Can `tdmg job run`/`status` treat a stage as current when its inputs, upstream records, code, rules or profiles changed? Can a confirmation stay current after what it covers changed?
4. **Owner words.** Are the owner's words stored verbatim on every path (Windows argument expansion, YAML parsing of `job set`, JSON escaping)? Does the skill ever lead Claude to paraphrase or invent words?
5. **Public/private.** Can a source image or a private printable file end up tracked (gitignore gaps, finish writing to the wrong folder, card or provenance leaking private paths)?
6. **Docs agree with code.** Where do STATUS, the skill, docs/guide/pipeline-and-gate.md, docs/design/jobs.md and the design disagree with what the code does?
7. **Tests.** Which important behaviours are untested or tested only with fakes in a way that could hide a real failure?

Report each finding with: severity (High/Medium/Low); file:line; a concrete failure scenario; a suggested change. End with the 3 most important changes. Be specific; skip praise.

# First real `tdmg finish`: Roadie, outline dropped (2026-11-17, the PC)

Plan `docs/plans/2026-11-16-restructure.md`, Task 14. The first run of `tdmg finish`,
`tdmg library check` and `tdmg library verify` on a real job with the pinned slicers
(OrcaSlicer 2.5.0, PrusaSlicer 2.9.7, `artifacts/tools/`). Windows 11, Git Bash.

## The job

- `tdmg job new roadie-drop --class flat-icon --colors --image .../roadie.png --origin drawing`
  (origin from the owner: "A drawing"). Source SHA-256 `ed33495f…73bf`.
- Parameters: the controls of the printed plan (`select.tolerance=30`,
  `select.remove_at=[[60, 396]]`, `select.keep_at=[[470, 470]]`, width 60 mm, thickness
  3 mm, outline dropped by default).
- `tdmg job run`: every stage done; face up and face down PRINTABLE, face down chosen;
  glue route not printable. `colored_flat/model.3mf` SHA-256
  `ec2961184e1b235fb4f051c00824095f9642128a565a829e4f1527b1a4f822d7`, the same bytes as the
  printed file (`research/verification/2026-11-15-first-ams-print/`).
- Print confirmation 1 (route ams, face down), dated 2026-11-16, the owner's words given
  that day: "done, and the newly printed items look great".

## The finish

- Owner, public question: "Yes, public". Purge permission, asked after the dry run had
  listed what would be deleted: "yes".
- Dry run, then the real run, with `--public yes --purge-owner-said 'yes'`: exit 0. The
  rebuild in a scratch folder matched every file byte for byte except the G-code
  timestamp lines and `slice.json`'s hashes of those G-code files (the allowance of
  `research/verification/2026-11-16-repeatability/`). Published `prints/roadie-drop/`;
  `purge.json` lists the job's 43 files; `jobs/roadie-drop/` deleted.
- `tdmg library check roadie-drop`: "roadie-drop: ok", exit 0.
- `tdmg library verify roadie-drop`: "identical to the historical run under the
  comparison rule", exit 0. Not compared (as it says): the stage folders' other files,
  the G-code timestamp lines, and check measurements.

## Legacy folders deleted afterwards

The 21 Roadie-drop paths listed in `docs/design/jobs.md` ("Deleted after Roadie's
finish"), each checked present and not a link first. The legacy
`colored-runs/roadie-tol30-60-drop-v3-f64/model.3mf` had the same SHA-256 as
`prints/roadie-drop/files/model.3mf` before it was deleted.

## Tests after the deletion

`tests/test_owner_fixtures.py`, `test_docs.py`, `test_evidence_inventory.py`,
`test_gitignore.py`, `test_library.py` with the real slicers: 203 passed. The Roadie
owner fixtures now build from `prints/roadie-drop/source/` (git-ignored; on this
machine only).

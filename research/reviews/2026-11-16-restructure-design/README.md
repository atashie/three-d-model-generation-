# Independent reviews of the restructure design draft, 2026-11-16

Design: `docs/plans/2026-11-16-restructure-design.md` (draft; nothing built). The owner
asked for a Codex and an Antigravity review before proceeding.

**How the reviews were run** (same prompt, `prompt.md`; both read-only, no files changed):
- **Codex** (OpenAI Codex CLI 0.167.0):
  `codex exec --sandbox read-only --ephemeral -C <repo> -o codex-review.txt "$(cat prompt.md)"`.
  Response verbatim in `codex-review.txt`. Static review; it ran no tests.
- **Antigravity** (`agy` 1.5.9, model Gemini 4 Argon (High)):
  `agy -p "$(cat prompt.md)" --model "Gemini 4 Argon (High)" --output-format json --print-timeout 25m`.
  The first run without `--output-format json` printed only `}`; the rerun with JSON
  succeeded (1 turn; 611,929 input, 32,213 output, 1,923,547 cache-read tokens). The
  response is in `antigravity-review.txt`, verbatim.

## How the findings were checked

Each claim about the repository was checked against the file it names before it was
accepted (CLAUDE.md, Review practice). Checked by reading or grep on 2026-11-16:
- `src/tdmg/paths.py:12` finds the checkout as `parents[1]` of the package: holds.
- Thirteen test files, both slicer profiles and `scripts/setup_orcaslicer.py` read or
  name files under `research/`; `tests/conftest.py:15` reads
  `research/verification/2026-11-11-color-palette/` (results): holds.
- `src/tdmg/color_checks.py:252` writes a module path (`tdmg.color_config.`) into check
  text, so moving the module changes record bytes: holds.
- `src/tdmg/calibration_strip.py:556` writes `docs/plans/2026-11-14-test-strip.md` into
  `strip.json`: holds.
- `smoothing.py:61` imports `tdmg.color`, `color_geometry.py:48` imports `tdmg.flat`,
  `color_checks.py:51` imports `tdmg.orca_input`: the proposed packages would import
  each other both ways: holds.
- `.gitignore` has no `jobs/` or `prints/*/source/` entry: holds (nothing built yet).
- `ci.yml` checkout sets no `fetch-depth`, so CI clones have no tags: holds.
- STATUS line 405: "Owner images are not committed until their rights are confirmed":
  holds.

**Antigravity quote errors (the points behind them were judged on their own):**
- Finding 6.2 quotes a "rewritten rule 6" ("Keep evidence, purge intermediates...")
  that is not in the design.
- Finding 7.2 criticises `tdmg job run NAME [--from STAGE]`; the design has `job new`,
  `job status` and `finish`, no `job run`.
- Finding 7.1 quotes the owner's goal as "Takes an image (either provided by the user,
  or generated from text through AI)"; the owner's words are different (the design
  quotes them). It also says the strips await the owner's results; the skin strip was
  printed and recorded on 2026-11-15 and the clearance strip skipped.

## Findings, merged by theme

C = Codex finding number, A = Antigravity finding number. Verdict: **holds** unless noted.

1. **Evidence is more than locator strings** (C1, A1.2; High). A condensed file can keep
   every locator and still drop the table headings, the corrections, the conditions (eSUN
   PLA+ white over black, judged by eye) and the line between "read in source" and
   "measured". Holds.
2. **Code, tests and profiles read the research files** (C2, A1.1, A5.2, A6.1; High). The
   files are fixtures and pins, not only prose. Deleting or rewriting them breaks tests,
   profile `record` paths, `strip.json` and doc links. Holds (checked above).
3. **The git tag is not a record CI or a rule can use** (A1.3; Medium). Holds. The
   `measure_*.py` scripts in the records are the only copy of some measurement methods.
4. **The library cannot regenerate a print** (C3, C4, A2.2, A3.1; High). A corrected
   `--mask` is recorded only by hash; `verify_colors` needs the selection folder and
   the stage records; a version string (`0.0.1`) and algorithm ids do not pin the code,
   lockfile, rules or profiles. Holds.
5. **Confirmations are not bound to what was approved** (C5, A2.4; High). A stale "looks
   great" would pass a rebuilt job; a print confirmation is not a purge permission.
   Holds.
6. **Purge path and completeness rules are thin** (C6, A2.4; High/Medium). Names not
   validated; Windows junctions; no completeness marker; no recovery if interrupted.
   Holds.
7. **"Byte-identical" is already false for some outputs** (C7; High). G-code
   timestamps change between repeat runs (strip record), and module paths in check
   text change with a move. Holds.
8. **The package split breaks discovery and leaves cycles** (C8, C10, A4.1, A5.1;
   Medium/High). `paths.py` depth; tests patch old module names; flat, color and
   slicing import each other. A moves-only phase cannot establish the claimed
   boundaries. Holds.
9. **"Shared" slicing and export are flat-icon specific** (C11, A4.2; Medium/High).
   `printed.py` refuses supports and assumes a centred placement; `threemf.py`
   requires base plus inlays. A figurine or flexi needs its own checks; missing ones
   must be UNKNOWN. Holds.
10. **Classes duplicate recipes; `finish` supports only one output shape** (C12, A2.1,
    A4.3; Medium/High). R1 makes an STL, the glue route makes plates. Holds.
11. **Legacy data cannot be purged by the new mechanism** (C9, A2.3; Medium). Today's
    `artifacts/` folders mix Roadie and Oddie and variants (drop, keep, R1); owner-image
    tests read `artifacts/selection-runs/`. Needs an explicit inventory. Holds.
12. **Docs migration is under-specified** (C13; Medium). No old-to-new map; new
    `docs/classes/` pages would escape `tests/test_docs.py`'s template check. Holds.
13. **The source image has no backup or machine plan** (C14; Medium). A git-ignored
    source is on one disk. Holds.
14. **Text-to-image provenance is missing** (C15, A7.1; Medium). Prompt, generator,
    settings, chosen candidate. Holds. A7.1's point that `jobs/` must not hold the only
    copy of a new image also holds.
15. **A public 3MF is a derivative of the private source** (A3.2; Medium). Keeping the
    source private does not keep the design private; rights are recorded nowhere.
    Holds; an owner decision.
16. **Rule 6 must not let calibration scripts go while rules wait for calibration**
    (A6.2; Medium). The quoted rule text is not the design's, but the point holds:
    evidence for `hypothesis`/`untested` rules must stay until they are calibrated.
17. **The job layer is over-designed for one owner** (A7.2; Low). The `job run`
    command it criticises is not in the design; the wider point (two CLI layers) is
    partly right. Judged at the redesign.
18. **Calibration strip output has no place in the new layout** (A7.1; Medium). Holds.

## Handling

The owner answered the four decisions the findings raised (2026-11-16): "Move, don't
rewrite (Recommended)", "Split when figurines start (Recommended)", "Ask per print
(Recommended)", "Prove a rebuild first (Recommended)". Draft 2 of the design answers
each of the 18 merged findings; its last table maps each finding to the section that
answers it. Finding 17 (over-design) is answered in part: four job commands over the
same functions, with parameters in `job.yaml`, not a second option parser. Nothing is
built, so no finding is "fixed" yet.

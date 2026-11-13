# Independent critical review of the multicolor 3MF (R2 step 3), 2026-11-13

This is Task 6 of `docs/plans/2026-11-12-color-3mf.md`.

**How the review was run:** with the installed OpenAI Codex CLI (0.167.0):

```
codex exec --sandbox read-only --ephemeral -o review.txt "$(cat prompt.md)"
```

It covered commits `76c9eba..fa33614`: all of step 3, up to the docs and the prompt.
`prompt.md` is the prompt, and `review.txt` is Codex's response, verbatim.

**What Codex ran:**
- 274 tests (`test_threemf.py`, `test_color_checks.py`, `test_rules.py`);
- the four owner `model.3mf` files against their STLs and palettes, and regenerated
  byte-identically;
- the Roadie drop pipeline in memory (all 11 outputs reproduced);
- 168,123 sampled float32 coordinates through lib3mf (all exact).

It did not run the file-writing integration suite or either slicer.

## Findings and how each was handled

Each finding was checked against the code before it was fixed (CLAUDE.md, Review practice).
Each fix was written as a failing test first; the tests failed (PASS where FAIL was
expected) before the fix.

1. **Medium: a near-identity build transform could pass.**
   - **Verdict: holds.** `_read_3mf` set `item_ok` from lib3mf's `HasObjectTransform()`
     only. Codex showed that a `1.0001` x scale is reported as no transform, while
     trimesh applies it (x max 20.002 mm on a 20 mm box).
   - **Fixed:** the build item's matrix (`GetObjectTransform().Fields`) must also equal the
     identity exactly. It is recorded as `item_transform`.
   - **Test:** `test_a_tiny_scale_that_lib3mf_calls_no_transform_fails`.
2. **Medium: an aliased model part could pass while another reader loads other geometry.**
   - **Verdict: holds.** The check never looked at the zip's entry names. A
     `3D/3DMODEL.MODEL` or `/3D/3dmodel.model` entry with a moved vertex, put before the
     real part, is ignored by lib3mf and loaded by trimesh (Codex: x max 999 against 20).
   - **Fixed:** the zip's entry names, read with `zipfile`, must be exactly the writer's
     three parts in order (`tdmg.threemf.PART_NAMES`), recorded as `package_parts`. An
     unreadable zip is a FAIL with the read error.
   - **Tests:** `test_an_extra_or_aliased_package_part_fails` (the two aliases, plus an
     unrelated extra part) and `test_the_package_parts_are_measured_on_a_pass`.
   - The writer never wrote such entries; neither defect was present in the owner's four
     files.
3. **Low: the record said every PrusaSlicer volume was below the palette sum.**
   - **Verdict: holds.** Roadie keep is 0.250 mm³ above.
   - **Fixed:** a dated correction under the original line in
     `research/verification/2026-11-12-color-3mf/README.md`, with all four differences.

## Also

- **Algorithm label:** kept at `colorflat-3`. That version was not yet pushed when the
  fix was made, and the 3MF, STL and PNG bytes are unchanged; only the check's measured
  fields in `colored.json` grew. The owner's four runs were re-made: exit 0, every
  `model.3mf` byte-identical to before, and the run summary unchanged
  (`research/verification/2026-11-12-color-geometry/colored-runs.txt`).
- **Codex found no defect** in the shared-wall construction against the 3MF core 1.3
  vertex-index manifold definition.

## Review of the fixes (subagent code review, 2026-11-13)

A subagent reviewer checked commit `8407443` (the fixes above), running probes against the
new and the old check. It confirmed both Codex findings closed, and found:

1. **Important: a corrupt zip could raise instead of FAIL.** `zipfile` raises
   `NotImplementedError` for a too-high "version needed" field, which the new `except`
   did not catch (found by a 3000-case byte-flip fuzz; the old code returned FAIL on
   every one). **Fixed:** any exception while reading the bytes is a FAIL with its type
   and message; the part names are kept in `measured` when they were read. Test:
   `test_a_zip_that_zipfile_cannot_open_is_a_fail_not_an_error`.
2. **Important: on Windows a backslash model part name passed.** `ZipInfo.filename` turns
   `os.sep` into "/", so `3D\3dmodel.model` (with a matching relationship) read as the
   writer's name on Windows only. **Fixed:** the raw names (`orig_filename`) are compared.
   Test: `test_a_backslash_model_part_name_fails_on_every_platform`.
3. **Minor: "exactly the identity" is exact at float32,** as lib3mf reads the matrix.
   **Fixed** in the docstring.
4. **Minor: names lost on a read error.** Fixed with item 1.
5. **Minor: the alias test did not show that the name check alone failed it.** **Fixed:**
   it also asserts `item_ok`.
6. **Suggestion: the content types and relationships parts were checked by name only.**
   **Done:** both must be the writer's bytes (`package_files_equal`). Test:
   `test_edited_package_files_fail`.

The owner's four runs were re-made again: exit 0, `model.3mf` byte-identical, run summary
unchanged.

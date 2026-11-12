# Independent critical review of `tdmg colors` (R2 step 1), 2026-11-11

Task 8 of `docs/plans/2026-11-11-color-palette.md`. I ran the installed OpenAI Codex CLI
(0.167.0) with `codex exec --sandbox read-only --ephemeral` on commits `8a5856e..e74689b`
(the whole of R2 step 1, with its docs). The prompt is in [prompt.md](prompt.md). Its final
response is in [review.txt](review.txt).

Codex ran in-memory reproductions on the owner's Roadie and Oddie selections and on
synthetic images. Its sandbox blocked `uv`; it used the project's `.venv` Python with
pytest's disk features turned off (533 tests run, 281 that need temporary files
deselected).

Before this, each step-1 task had a subagent spec review and a quality review, with fixes
after each. I checked every finding below against the code before handling it. The fixes
are in commit `7359362`. The full suite then gave 1749 passed and 3 skipped. The 3 need
the real slicers.

1. **High: a not-ready plan could be made "ready" above the printer's cap.** Confirmed by
   reading: `_identity_values` validated the settings with no cap context, so the
   `colors` check was skipped.
   - **Fix:** `verify_colors` loads the profile the identity names. It must be a known
     profile id, with the identity's nozzle. The settings are then validated with that
     profile's palette cap.
   - **Tests:** `test_verify_colors_refuses_colors_above_the_printers_cap` (Codex's
     mutation) and `test_verify_colors_refuses_a_nozzle_other_than_the_profiles`.
2. **High: labels.png could be changed by hand and pass.** Confirmed by reading:
   `verify_colors` checked labels.png's hash, counts and mask, but nothing tied the
   spatial layout to the inputs. Updating the hash in the record was enough.
   - **Fix:** `_make_colors` is split. `build_colors` computes the record and files in
     memory, and `verify_colors` calls it with `render=False`. That runs the pure plan
     again from the selection, the identity's settings and printer, and the identity's
     rule values. labels.png's pixels must equal the rebuilt labels exactly.
   - **What the record must match:** every field of the rebuilt record except those that
     depend on the fine map, the PNG encoder or the software versions (`UNRENDERED_FIELDS`:
     `tdmg_version`, `environment`, `outputs`, `regions_pixels_sha256`,
     `smoothing.vanished`) and except `settings`, whose sources and config hash cannot be
     rebuilt (`settings.settings` is already compared with the identity). Floats may
     differ by 1e-9 (`LAB_ABS_TOL`, last-digit differences between C libraries). Ints,
     bools and strings must be equal.
   - **Cost:** the rebuild adds about one plan run (a few seconds on the owner's images).
   - **Consequence, stated in the docs:** a plan made on a machine whose results differ is
     refused. The owner-image results are measured on the Windows PC only.
   - **Tests:** `test_verify_colors_refuses_labels_moved_by_hand` (Codex's cyclic shift),
     `test_verify_colors_refuses_a_record_field_changed_by_hand`, and
     `test_verify_colors_ignores_only_the_unrendered_fields`.
3. **Medium: an invalid base index passed.** Confirmed by reading: `_check_palette` never
   required the base to be in the palette, and a null setting passed `ColorConfig`, whose
   fields are optional.
   - **Fix:** `check_base` is applied against the final palette, and a null resolved
     setting is refused.
   - **Tests:** `test_verify_colors_refuses_a_base_outside_the_palette` (index k, and
     null).
4. **Medium: a ready plan that its verifier refused.** Confirmed by running: with a 5 mm
   kept band, the 11 mm test cartoon gives two colors that the band paints over
   entirely. Their fate was `cleanup`, with no cleanup entry.
   - **Fix:** a new fate, `band` (covered by the kept outline). It is allowed only for a
     non-family color under `outlines: keep` with a family. Shade-pair candidates include
     it, as the plan computes them before the band. The record schema is now
     `tdmg.colors/4`. The algorithm version is unchanged, because no result changes.
   - **Test:** `test_a_color_the_kept_band_covers_has_fate_band`.
5. **Medium: OpenCV's code path changes the fine map.** Confirmed by running
   [opencv_paths.py](opencv_paths.py) → [opencv_paths.txt](opencv_paths.txt): in float32,
   toggling `cv2.setUseOptimized` changes the blurred fields by up to 1.8e-7, and Codex's
   17 × 17 case by 3 fine pixels. In float64 the fields were bitwise equal both ways in
   all four cases.
   - **More than Codex found:** R1's `smooth_outline` has the same property. Its outline
     differed in every one of the five owner selections at σ 2.5 px
     ([opencv_paths_owner.py](opencv_paths_owner.py) →
     [opencv_paths_owner.txt](opencv_paths_owner.txt); it reads the git-ignored selections).
   - **Not fixed in code:** neither labels.png nor `colors_id` depends on the fine map, and
     the rebuild skips it. Moving both blurs to float64 changes R1's outputs, including
     files already judged PRINTABLE, so it is left for the owner to decide.
   - **Recorded:** in the design's step-2 requirements (step 2 gates its geometry by its
     own checks, not by reproducing the fine map's bytes), the attribute page's open gaps,
     and STATUS.
   - float64 being stable on this machine does not show it is stable on the Mac.
6. **Medium: unsupported method versions were accepted.** Confirmed by reading.
   - **Fix:** `identity.methods` must equal `SUPPORTED_METHODS`.
   - **Test:** `test_verify_colors_refuses_an_unsupported_method`.
7. **Low: a YAML file that is an explicit null meant "no settings".** Confirmed by
   reading: `yaml.load` gives None for both an empty file and `null`.
   - **Fix:** `yaml.compose` tells them apart. An empty or comment-only file still means no
     settings, and an explicit null document is refused.
   - **Tests:** `test_a_file_that_is_an_explicit_null_is_refused` and
     `test_a_comment_only_file_still_means_no_settings`.
8. **Low: the guide gave `outline_color` as an index.** Confirmed: it takes a list, such
   as `[3]`. The guide is corrected.
9. **Low: the attribute page said `keep` redraws the outline "everywhere".** Confirmed
   against the band-survival record. The page now states the small breaks where lines
   meet (1.7% of Roadie's band and 0.3% of Oddie's at 0.5 mm). It also adds the `band`
   fate to the lost-detail row.

## Review of the fixes (subagent spec and quality review of `7359362`)

The reviewer compared the old and new code on seven inputs. `make_colors` output was
byte-identical in six. (Correction after Codex review 2: not byte-identical. Every record
changed its `schema` from `tdmg.colors/3` to `/4`; Codex found that `schema` was the only
differing top-level field on Roadie, and the PNGs were identical. The subagent's
comparison must have set `schema` aside, which it did not record.) In the seventh (the 5 mm band), it differed only by the schema,
the two `band` fates and the preview text that names them. The reviewer found these gaps;
each was checked and handled in the next commit:

- **I-1: `verify_colors` trusted the recorded rule values.** Confirmed by the reviewer's
  repro: a plan made with a 0.05 mm opening passed with the real registry. The design's
  step-2 requirements already say a mismatch is refused.
  - **Fix:** every recorded rule value must equal the registry's (`rules=`, or
    `load_rules()`), and the rebuild then uses the registry.
  - **Test:** `test_verify_colors_refuses_rule_values_other_than_the_registrys`. The same
    plan passes when verified with the registry it was made with.
- **I-2: the float tolerance accepted an int against a float** (a count of 200.0). Fixed:
  the tolerance applies only between two floats. Anything else must have the same type
  and value. Test: `test_verify_colors_refuses_an_int_written_as_a_float`.
- **I-3: the review record and STATUS were not committed.** They are committed with these
  fixes.
- **S-1: `smoothing.vanished` was not checked at all.** It is not rebuilt, so it is now
  checked in form: final palette entries, by index and hex. Test:
  `test_verify_colors_checks_the_form_of_vanished`.
- **S-2: the docs overstated what is refused.** Reworded in the guide and the attribute
  page. They now name what is not rebuilt: the preview, the software versions and the
  settings' sources.
- **S-3: the settings copy was compared with `==`** (4.0 == 4). It is now compared as
  canonical JSON. Test: `test_verify_colors_refuses_a_settings_copy_of_another_type`.
- **S-4: the rebuild also compares the preview block and the review line**, which are code
  constants. Kept, because such a plan was not made by this code, and documented in the
  `verify_colors` docstring.
- **S-5: a file that is only `---` is now refused as null.** Kept, since it is a document
  holding null. Pinned in `test_a_file_that_is_an_explicit_null_is_refused`.
- **S-6: cost.** Measured on the PC: `verify_colors` on the owner's Oddie plan (keep, blues
  and greens merged) takes 1.45 s, or 1.37 s without the preview decode. The duplicate
  `edge_sigma_px` call is harmless and kept: it refuses a bad preset before the selection
  is read.

**Re-review of `a671a8d`:** the reviewer re-ran its repros, and every fix held. Two
suggestions were left, and both are handled in the next commit:
- The settings block (`settings`, `sources` with a known source per key, and
  `config_sha256` as a SHA-256 or null) is now checked in form. Test:
  `test_verify_colors_checks_the_form_of_the_settings_block`.
- The docs and the plan now say "every rebuildable record field" and list what is checked
  in form only.

## Owner decision: float64 blur (flat-3), 2026-11-11

**Owner, verbatim:** "fix it now" (the question was whether to move both blurs to float64
now, re-checking R1, or leave it).

**Change:** `smooth_outline` (R1) and `smooth_labels` (colors) now blur a float64 field.
- **R1 versioning:** `FLAT_ALGORITHM_VERSION` is `flat-3`, the method text says float64,
  and the golden flat id is re-pinned.
- **Colors versioning:** `LABELS_METHOD` names float64, so `colors_id` changes. The
  colors algorithm and record schema do not: `labels.png` does not depend on the blur.

**Measured on the Windows PC (all files here):**
- **Code-path stability:** with float64, toggling `cv2.setUseOptimized` gives the same
  outline for all five owner selections ([opencv_paths_owner_f64.txt](opencv_paths_owner_f64.txt);
  it was different for all five in float32). The fine map matches too.
- **Overshoot of the image box:** at most 2.5e-15 px over the same kinds of masks as the
  float32 measurement, against up to 1.9e-6 px before
  ([overshoot_f64.py](overshoot_f64.py) → [overshoot_f64.txt](overshoot_f64.txt)). The
  test allowance is now 1e-12 × max(σ, 1) px. Step 2 still intersects the outline with
  the image box.
- **R1 on the owner's models at 60 × 3 mm** ([flat3_compare.py](flat3_compare.py) →
  [flat3_compare.txt](flat3_compare.txt)). The STLs are not byte-identical to the flat-2
  ones (so not to the Roadie the owner printed). The shape moved by at most 4.6e-6 mm:
  that is the Hausdorff distance of the mid-height sections, with a symmetric difference
  below 2e-5 mm².
  - **Roadie:** the same 31,200 facets.
  - **Oddie:** 29,020 facets instead of 29,212. Its outline has 96 fewer points; the
    shape is the same within that 4.6e-6 mm.
  - **Re-sliced** with both pinned slicers: both are still **PRINTABLE**, every required
    check PASS. Edge coverage and overprint equal the flat-2 values to about 1e-8 mm
    (Roadie 0.2312 and 0.0133 mm, Oddie 0.2223 and 0.0130 mm). The slice_ids are
    `86b7d85d…` (Roadie) and `a50ecead…` (Oddie), in
    `artifacts/slice-runs/*-60x3-f64` (git-ignored).
- **The owner's four approved previews**, remade ([previews_f64.py](previews_f64.py) →
  [previews_f64.txt](previews_f64.txt)): `labels.png` is byte-identical in all four. The
  preview pixels changed are 0 and 0 (Roadie), and 88 and 51 out of about 10 million
  (Oddie).

**Not shown:** that float64 is bit-identical on the Mac. The Mac has not run this.

**Review of the float64 change (subagent spec and quality review of `18e8d2b`):** the
reviewer confirmed the code, the version bumps and every quoted number against the .txt
outputs. It ran the tie test, which still runs (no skip) and passes. It found:
- **I1: the cost figure in `smooth_labels`' docstring was a float32 measurement.**
  Re-measured with [cost_f64.py](cost_f64.py) → [cost_f64.txt](cost_f64.txt): 4.30 s and
  a 417 MiB tracemalloc peak, against 4.9 s and 356 MiB with float32. The docstring now
  gives both.
- **I2: "the fine map matches too" cited a case that already matched in float32.**
  - `opencv_paths_owner_f64.txt` is the output of
    [opencv_paths_owner.py](opencv_paths_owner.py), re-run on the float64 code. Its "f32"
    label is left over from the script, and its one labels case (oddie-60-default) gave
    0 in float32 too.
  - The case that differed, Codex's 17 × 17 map, is now re-run with
    [opencv_paths.py](opencv_paths.py) → [opencv_paths_f64.txt](opencv_paths_f64.txt): 0
    fine pixels differ, against 3 with float32. So the fine-map claim rests on this file.
- **I3: no regression test.** Added `test_results_do_not_depend_on_opencvs_optimised_code_path`
  (tests/test_smooth_labels.py). It runs that 17 × 17 map through `smooth_labels`, and
  its mask through `smooth_outline`, with the optimisations on and off. It runs on every
  OS in CI, which gives some evidence for macOS and Linux.
- **Suggestions:**
  - **S1:** the test comment now says the overshoot allowance assumes small images.
  - **S4:** the verification addendum now gives the slice_ids and how the shape was
    compared.
  - **S6:** the plan now notes the change is done.
  - **Not changed:** S2 (a looser-than-needed band in one test), S3 (a float32 stub in a
    monkeypatched test) and S5 (`to_planar` is deprecated in trimesh; the script is a
    record).

## Codex review 2: the fixes and the float64 change (`e74689b..93e4f84`), 2026-11-11

Prompt: [prompt-2.md](prompt-2.md); Codex's response, verbatim:
[review-2.txt](review-2.txt). Codex judged the nine first-review findings fixed (it re-ran
the reproductions for 1, 2, 3, 4, 6 and 7). It found no float32 measurement still shown as
current and no missing version bump. Its three findings, each checked here:

1. **Medium: a malformed PNG escaped as a raw `ValueError`.** Confirmed: Pillow's
   `Image.open` raises `ValueError` for a compressed text chunk over
   `PngImagePlugin.MAX_TEXT_CHUNK`. `_decode` in colors_verify.py caught only `OSError` and
   `DecompressionBombError`. The same gap was in `tdmg.selection._open_checked`, which
   reads the input image, the mask and the selection files. Both now catch `ValueError` and
   refuse with their own error. Tests: `test_verify_colors_refuses_a_png_pillow_will_not_decode`
   and a "huge text chunk" case in both decode tests of tests/test_selection.py.
2. **Low: `tdmg_version` and `environment` were not checked at all.** Confirmed by
   reading: they were removed before the comparison. Now `_check_provenance` checks their
   form: a non-empty version string, and an environment with exactly the library names
   `make_colors` records (`tdmg.colors.ENVIRONMENT_KEYS`), each a non-empty string. Their
   values may still be older ones. Tests: `test_verify_colors_checks_the_form_of_the_software_fields`
   (8 cases) and `test_verify_colors_accepts_an_older_tdmg_version`.
3. **Low: this README said six outputs were byte-identical.** Confirmed: the schema
   changed in all of them. Corrected in place above, marked as a correction.

**Also reported, not changed:** for an input with several faults, `make_colors` now
refuses a bad `supersample` before a bad `base` (`build_colors` checks supersample at
its start; the old code checked it later, in `smooth_labels`). Both refuse without
writing anything. Which fault is named first is not part of the contract.

**Codex could not run:** the slicers, the full suite (`uv` failed on cache access in its
sandbox, so 309 tests that write files were deselected) and another OS. The full suite
here: 1777 passed, 3 skipped (the slicer tests).

# Slicer check (S9, F6) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** add `tdmg slice FLAT_DIR --out DIR`. It slices a `tdmg flat` output with a
pinned, hash-verified OrcaSlicer 2.5.0 and the Bambu A1 profiles. It replaces the
always-UNKNOWN `F6.slicer` with checks measured from the real slicer output, and writes
a `slice.json` record that links back to the flat record.

**Why:** without a slicer run, no output can ever be PRINTABLE. The owner approved
installing OrcaSlicer on 2026-11-10. The design rests on measurements in
`research/verification/2026-11-10-orcaslicer-windows/` (read it first):
- **Exit codes:** Windows passes the full 32-bit exit code.
- **Statistics:** `--export-statistics` works on Windows.
- **No mesh validation:** an open mesh slices with exit 0 into a truncated print.
- **Triangle limit:** `--mtcpp` is not enforced for STL input.
- **G-code repeatability:** G-code differs between runs only in its timestamp line.
- **Settings:** the A1 settings must be flattened from the v2.5.0 source chains.

**Architecture:**
- **Pin file:** `profiles/slicers/orcaslicer-2.5.0.yaml` records the release, asset,
  SHA-256 hashes (zip, exe, upstream profile files, flattened profiles), the profile
  chain names and the exit-code table.
- **Setup script:** `scripts/setup_orcaslicer.py` downloads, verifies, extracts and
  flattens into `artifacts/tools/`. The user runs it explicitly; `tdmg` never downloads
  anything itself.
- **Wrapper module:** `src/tdmg/slicer.py` holds the subprocess runner, exit-code decoding,
  output parsing and the F6 checks.
- **Command:** `tdmg slice` in `cli.py`.
- **Tests:** they use a fake slicer, a small Python script invoked through
  `[sys.executable, fake.py]`, so CI needs no OrcaSlicer. One integration test runs the
  real slicer only when `TDMG_ORCASLICER_DIR` points to a verified install.

**Licence:** OrcaSlicer is AGPL-3.0. It is only ever run as a subprocess. No OrcaSlicer
code or profile file enters the repo. Hashes, setting names, and the exit-code numbers
and names (as facts, cited to `src/libslic3r/Utils.hpp` v2.5.0) are fine.

**Conventions:** the same as the flat and smoothing plans.
- Imports at the top.
- Lines ≤ 100 characters (check with awk).
- LF endings.
- Write edit scripts as files, not heredocs.
- Every commit ends with the trailer.
- Test-first; never weaken an assertion.
- Run both test environments.
- Keep the doc-lint rule-id caveat in mind: write dotted file names in docs with a path.

**Status:** written and executed 2026-11-10; see "Execution notes".

## Decisions

1. **Pin and verify everything.** Before every run, `tdmg slice` checks:
   - the exe's SHA-256;
   - the three flattened profiles' SHA-256 hashes, against the pin file.
   A mismatch raises `SlicerError`, which exits 2. The record stores the slicer version,
   the exe hash and the profile hashes.
2. **Locating the slicer.** Use `--slicer-dir DIR` or the `TDMG_ORCASLICER_DIR`
   environment variable. The directory is the setup script's output: it contains
   `app/orca-slicer.exe` and `profiles-flat/`. With neither set, fail clearly and point
   to the setup script. Never search the system for an install.
3. **Command.**
   - The arguments are `<exe> model.stl --load-settings "machine.json;process.json"
     --load-filaments filament.json --slice 0 --outputdir <tmp> --export-statistics
     --logfile <tmp>/slicer.log`, which is exactly the measured form.
   - Run it with a timeout. The timeout is a rule with evidence: slicer timeout rule (`slicer.orca.timeout_s`),
     kind hypothesis, unit `s` (add the unit). The default is generous for the measured
     0.2–0.5 s runs. Cite the record.
   - Run it in a temporary folder, then copy the outputs into the new output folder
     through `records.write_outputs`.
4. **Exit-code decoding.**
   - Windows: unsigned 32-bit to signed (measured).
   - macOS/Linux: the low 8 bits, as CLAUDE.md records for the M5. A value above 127 is
     read as a negative code.
   - Map the signed code to its v2.5.0 name from the pin file's table.
   - Record the raw code, the signed code, the name, the platform, and whether the
     decoding rule for that platform is measured or assumed.
5. **F6 checks**, run on the slicer outputs:
   - `F6.slicer_exit`: PASS if the code is 0; else FAIL, naming the code.
   - `F6.gcode_present`: `plate_1.gcode` exists and is non-empty.
   - `F6.layer_count`:
     - expected = 1 + round((thickness − initial_layer_print_height) / layer_height),
       with both heights read from the flattened process profile;
     - actual = `summary.layer_count` from the statistics file;
     - PASS only when they are equal. This catches the truncated-print case measured on
       an open mesh. Document the formula, and check that it gives 100 for the 20 mm
       cube and 15 for 3 mm.
   - `F6.single_object`: exactly one object in the statistics.
   - `F6.portability`: UNKNOWN, "second slicer (PrusaSlicer) not run". The plan's
     portability requirement is unchanged.
   - Record the statistics summary (time, weight, volume, layers) as facts, not checks.
6. **Verdict.** Combine the flat record's checks, minus its placeholder `F6.slicer`,
   with the new F6 checks. Require all of them with `checks.verdict`. The result stays
   NOT CERTIFIED while F3 is UNKNOWN; say so in the output.
7. **Record** (`out/slice.json`, schema `tdmg.slice/1`):
   - links: flat_id, the model.stl SHA-256 (it must equal flat.json's `outputs` hash,
     else `SlicerError`), selection_id;
   - the slicer {version, exe_sha256, profiles {name, sha256}, platform};
   - the command, with paths replaced by placeholders;
   - the exit code {raw, signed, name, decoding};
   - stats, checks, the combined verdict, outputs, environment;
   - a G-code content hash taken with the "generated by ... at" line normalised,
     besides the raw file hash.
   The outputs are `plate_1.gcode`, `plate_1.statistics.json`, `out/slicer.log` and
   `slice.json`, written last.
8. **CLI exit codes:** the same convention as `tdmg flat`: 0 when no check FAILed, 1
   when one did (the files are still written), 2 for input or setup errors.

## Tasks

### Task 1: Pin file, timeout rule, setup script
- `profiles/slicers/orcaslicer-2.5.0.yaml`. Copy the values from the research record:
  - the zip and exe SHA-256;
  - the flattened hashes (`flattened-hashes.txt`);
  - the upstream manifest (`source-manifest.json`);
  - the leaf preset names;
  - the exit-code table from `src/libslic3r/Utils.hpp` v2.5.0 (numbers and names);
  - the measured decoding rules per platform.
  Add a pydantic loader in `src/tdmg/slicer.py`. Test that it loads and that its hashes
  match the research record's files.
- Rule slicer timeout rule (`slicer.orca.timeout_s`), plus unit `s` in rules.py UNITS. Regenerate the docs.
- `scripts/setup_orcaslicer.py --dest DIR`:
  - download the pinned asset and verify its SHA-256;
  - extract it into a fresh `DIR/app` (refuse a non-empty one);
  - verify the exe hash;
  - run the flattening from `research/verification/2026-11-10-orcaslicer-windows/flatten_profiles.py`
    (import or copy it into the script; it's repo code). Use the pinned tag, and verify
    the upstream file hashes against the manifest and the outputs against the pin;
  - write `DIR/profiles-flat/`.
  - Windows x64 only for now. On other platforms, exit with a clear message.
  - Test the hash-verification logic offline, with a fake download.
- Commit.

### Task 2: Runner, decoding, parsing and F6 checks (`src/tdmg/slicer.py`)
- Functions:
  - `locate(slicer_dir)`, which verifies the hashes;
  - `run_slicer(cmd_prefix, stl, profiles, workdir, timeout)`;
  - `decode_exit(raw, platform)`;
  - `expected_layers(thickness, process_profile)`;
  - `parse_statistics(path)`;
  - `f6_checks(...)`.
- Tests: use a fake slicer script whose behaviour a JSON control file sets. It can write
  G-code and statistics with chosen layer counts, exit with a chosen code, or write
  nothing. Cover:
  - success;
  - nonzero exits on Windows-style and POSIX-style decoding;
  - a missing G-code file;
  - a layer mismatch, the truncated case;
  - two objects;
  - a timeout;
  - a hash mismatch, which refuses to run.
- Commit.

### Task 3: `tdmg slice` and its record
- `make_slice(flat_dir, out_dir, slicer_dir)` and the CLI command, following Decisions
  6–8.
- Tests with the fake slicer:
  - the full record and its keys;
  - a model.stl tampered after flat refuses to run;
  - exit codes 0, 1 and 2;
  - nothing written on input errors;
  - the normalised G-code hash ignores the timestamp line;
  - both test environments pass.
- An integration test marked `slicer`, skipped unless `TDMG_ORCASLICER_DIR` is set:
  `tdmg flat` then `tdmg slice` on the roadie_like fixture, with real F6 PASS.
- Commit.

### Task 4: Run on the owner's models
- Run `tdmg slice` on `artifacts/flat-runs/{roadie-tol30,oddie}-60x3-s3` and the
  integration test locally. Record the results in the OrcaSlicer research record or a
  new one.
- Ask the owner, optionally, to open the G-code or the STL in Bambu Studio and compare
  its time and weight estimates.

### Task 5: Docs, status and review
- Update:
  - `docs/guide/pipeline-and-gate.md` (S9 now exists; F6 is partly measured);
  - `docs/reference/dependencies.md` (OrcaSlicer: an external tool, AGPL, subprocess
    only, pinned);
  - the README (setup and slice commands);
  - STATUS.
- Get an independent Codex review, record how each finding was handled, push, and check
  CI.

## Out of scope
- PrusaSlicer (the portability half of F6).
- Bambu Studio's command line.
- 3MF input.
- Printing.
- An F3 policy.
- macOS and Linux setup. The decoding rule for those platforms is recorded as
  "assumed, from M5 notes" until it is measured.

## Execution notes

- **Tasks 1–2.**
  - The pin covers the release zip, the exe, `OrcaSlicer.dll` and a tree hash of all
    4,054 app files, plus the upstream and flattened profiles and the exit-code table.
  - `locate` checks the exe, the dll and the profiles on every run (0.13 s). The full
    tree is checked at setup and by `--verify-only` (2.6 s).
- **Corrections, measured and recorded in the research record's addendum:**
  - `--logfile` writes a log on success only with `--debug` 2 or higher; it is always
    written on failure.
  - Two bodies in one STL count as one object, so F4.body_count is the real guard.
  - At exact half-layer thicknesses the slicer rounds either way, so `F6.layer_count`
    accepts both neighbouring counts there.
- **Task 3, after review.**
  - The NOT CERTIFIED reason is now built from the required checks that are not PASS.
  - `tdmg slice` recomputes `flat_id` with the shared `tdmg.flat.flat_identity`, and pins the
    exact `out/flat.json` bytes (`links.flat_record_sha256`, part of `slice_id`).
  - A failed slice's G-code is written as `plate_1.gcode.failed`, and the CLI warns not
    to print it.
  - The profiles are hashed in memory and sliced from those copies. The exe and dll
    keep a millisecond check-to-use gap; this is documented.
  - **Known limit:** a hand-edited check status with unchanged parameters is not
    refused, only pinned by the record hash. Refusing it would mean re-running flat's
    checks.
- **Task 4:** see the OrcaSlicer research record's "Slicing the owner's models" section.

# OrcaSlicer 2.5.0 command line on Windows, 2026-11-10

**Purpose:** measure, before planning the F6 slicer check, how the OrcaSlicer command
line behaves on the owner's PC. The checks are Windows exit codes, the outputs, and the
A1 settings. The owner approved installing OrcaSlicer on 2026-11-10.

## Install

- **Download:** release `v2.5.0` (2026-11-07), asset
  `OrcaSlicer_Windows_V2.5.0_x64_portable.zip`, from the GitHub releases page.
- **Hash check:** its SHA-256 equals the digest GitHub publishes for the asset:
  `e355d9f8ac0be4efa4b4f99ecae448d4e99def8dee97683847ede5aa0ccb9166`. See
  `install-hashes.txt`, which also gives the `orca-slicer.exe` hash.
- **Location:** extracted to the git-ignored `artifacts/tools/orcaslicer-2.5.0/app/`. It
  is a portable copy: no installer ran and nothing was registered.
- **Licence:** OrcaSlicer is AGPL-3.0. It is used only as a separate program run as a
  subprocess; no code or profile file is copied into this repository (CLAUDE.md rule 7).

## Settings: Bambu A1 profiles

- **The app's own presets don't work from the command line here.** Settings files that
  inherit from built-in presets cannot be resolved by a fresh portable copy. With
  `"from": "User"` the error is "can not resolve preset ... directory_iterator ...
  system". With `"from": "system"` it is "Preset was not found in the loaded bundle".
  The bundled vendor profiles are a binary `BBL.opc` pack. The GUI apparently unpacks
  them on first run, which was not done.
- **Solution:** `flatten_profiles.py` fetches the A1 inheritance chains from the
  OrcaSlicer source at tag `v2.5.0` (`resources/profiles/BBL.json` index and the
  linked files). It merges each chain parent first and writes self-contained
  `machine.json`, `process.json` and `filament.json`, with no `inherits`.
  - Machine chain: fdm_machine_common ← fdm_bbl_3dp_001_common ← Bambu Lab A1 0.4 nozzle.
  - Process chain: fdm_process_common ← fdm_process_single_common ←
    fdm_process_single_0.20 ← 0.20mm Standard @BBL A1.
  - Filament chain: fdm_filament_common ← fdm_filament_pla ← Bambu PLA Basic @base ←
    Bambu PLA Basic @BBL A1.
- **What is committed:** the upstream file hashes (`source-manifest.json`) and the hashes
  of the merged outputs (`flattened-hashes.txt`). The merged files themselves live in
  `artifacts/tools/orcaslicer-2.5.0/profiles-flat/`, because they derive from the AGPL
  repository.
- **Not verified:** whether the merged settings equal what the GUI would use for the
  same presets. The merge is "child overrides parent", which matches the preset files'
  structure, but it was not checked against the GUI.

## Behaviour (`measure_orca.py` → `results.txt`)

Every case passed the same settings, plus `--slice 0 --outputdir ... --export-statistics
--logfile ...`. The Python `subprocess` return code is shown both raw and as a signed
32-bit value.

| Case | Return code (raw → signed) | Outputs | Note |
|---|---|---|---|
| 20 mm cube | 0 | `plate_1.gcode`, `plate_1.statistics.json` | 100 layers, 766 s |
| Cube with one face missing (open mesh) | **0** | both files | **only 10 layers**: a broken mesh slices "successfully" into a wrong result |
| 300 × 20 × 5 mm box (larger than the bed) | 4294967246 → −50 | none | "No object is fully inside the print volume" |
| Unreadable file | 4294967290 → −6 | none | "Loading of a model file failed" |
| Missing file | 4294967293 → −3 | none | "No such file" |
| Owner's Roadie, 60 × 3 mm, smoothed | 0 | both files | 15 layers, 473 s, 2.27 g |
| Owner's Oddie, 60 × 3 mm, smoothed | 0 | both files | 15 layers, 484 s, 4.35 g |
| Roadie with `--mtcpp=1000` (31,200 triangles) | **0** | both files | **limit not applied**; the log counts 31,200 triangles |

**Findings:**

1. **Windows exit codes are not truncated.** On Windows, Python receives the full
   32-bit code, as an unsigned value: −50 arrives as 4294967246. The macOS/Linux
   low-8-bit rule in CLAUDE.md (−50 → 206) does not apply here.
2. **Console output:** `orca-slicer.exe` prints nothing for `--help`. Error messages go
   to stderr, and `--logfile` captures a full log.
3. **Statistics export works on Windows.** `--export-statistics` writes
   `plate_N.statistics.json`, with `summary` (time, layer_count, volume, weight),
   per-layer data and per-object data. `result.json` is not written, consistent with
   its Linux-only guard in the v2.5.0 source.
4. **A slicer exit code of 0 does not imply a valid mesh.** An open mesh slices with
   exit 0 into a truncated print. Our own F1 checks must stay in front of F6.
5. **`--mtcpp` did not take effect on this STL path.** The limit check exists in
   `src/OrcaSlicer.cpp` v2.5.0, at the "triangle count ... exceeds the limit" branch,
   but it was not reached here. The option's declared default is 1,000,000
   (`src/libslic3r/PrintConfig.cpp`). This was not measured on a 3MF input.
6. **Speed:** every case took about 0.2–0.5 s.
7. **Repeatability:** two runs on the same Roadie STL and settings, about a minute
   apart, gave G-code differing in exactly one line, line 2: `; generated by
   OrcaSlicer 2.5.0 on <date> at <time>`. `plate_1.statistics.json` was
   byte-identical. A content hash taken with that line normalised is therefore
   repeatable on this machine.

## Limits

- **Coverage:** one PC, one OrcaSlicer build, STL inputs only. No 3MF input was sliced.
- **No printing:** G-code was not printed or compared with Bambu Studio's.
- **Settings check:** the merged settings were not compared with the GUI's resolved
  presets.

## Addendum, 2026-11-10 (later the same day)

Added while building `tdmg slice`, after a review of the wrapper. The text above is left as
first written; this section qualifies it. The scripts are `measure_more.py` (output
`more.txt`) and `app_tree_hash.py` (output `app-tree.txt`). They used the same install,
settings and argument form as above.

1. **`--logfile` writes a log on success only with `--debug` 2 or higher.** On exit-0
   runs of the 20 mm cube:

   | Extra arguments | Log file |
   |---|---|
   | none | not written |
   | `--debug 1` | not written |
   | `--debug 2` | 44 bytes |
   | `--debug 3` | about 12 kB, no line mentions "triangle" |
   | `--debug 4` | about 28 kB, including a "volume triangle count" line |

   The failing cases above (too big, unreadable file) wrote a log without `--debug`. So
   finding 2's "`--logfile` captures a full log" holds only for failures, or for successful
   runs with `--debug`. The earlier observation that "the log counts 31,200 triangles" came
   from a `--debug 4` run. The "volume triangle count" line appears here only at
   `--debug 4`. A wrapper must treat the log file as optional.
2. **One STL is one object.** An STL holding two separate 10 × 10 × 3 mm boxes, 10 mm
   apart (trimesh finds 2 bodies), sliced with exit 0 into 15 layers. The statistics list
   **one** object (named after the file). So the statistics' object count cannot detect
   several bodies in one STL.
3. **Layer counts at half-layer thicknesses.** These are boxes of 20 × 20 × t mm with
   initial_layer_print_height = layer_height = 0.2 mm. "Formula" is
   1 + round((t − 0.2) / 0.2) in Python float arithmetic.

   | t (mm) | (t − 0.2) / 0.2 | Formula | Slicer |
   |---|---|---|---|
   | 3.0 | 14.0 | 15 | 15 |
   | 3.05 | 14.25 | 15 | 15 |
   | 3.1 | 14.5 | 15 | 15 |
   | 3.15 | 14.75 | 16 | 16 |
   | 1.1 | 4.5 | 5 | **6** |
   | 2.1 | 9.5 | 11 | **10** |
   | 0.3 | 0.5 | 1 | **2** |
   | 0.5 | 1.5 | 2 | 2 |

   Away from a half layer, the slicer matched the nearest count. At exactly half a layer it
   chose the lower count for 3.1, 2.1 and 0.5 and the upper count for 1.1 and 0.3. So a
   check must accept either neighbour there. The plain formula disagrees with the slicer at
   1.1, 2.1 and 0.3.
4. **The whole app folder, hashed.** The folder has 4,054 files. Their tree hash is
   `b5cf3ff821f71bb6dbfb07b2fb1e806ee15e58e5af76d605d59182f0a2c33402`. It is defined in
   `app_tree_hash.py` as the SHA-256 of sorted `relpath<TAB>sha256` lines with `/`
   separators. `OrcaSlicer.dll` has SHA-256
   `4c6a3772c21851623dfa88860f530a9971288bc8ca6e0d0b6b914c145cb987af`. Two folders gave
   the same tree hash: the install above, after all the slicer runs, and a fresh
   extraction of the same zip by `scripts/setup_orcaslicer.py`. So slicing writes nothing
   into the app folder. Hashing all of it took about 1 s when the files were cached, and
   about 20 s right after extraction.
5. **The manifest's bytes.** `flatten_profiles.py` wrote `source-manifest.json` with
   `Path.write_text` on Windows, so with CRLF line ends. The flattened profiles were
   written the same way. Its SHA-256 as written is
   `2b1abe80173cf986d33de7df7708491ad2b41a36639535fb481f4cd933306cb4`, both in
   `artifacts/tools/orcaslicer-2.5.0/profiles-flat/` and in this folder's working copy.
   Git stores this folder's copy with LF, so a checkout's bytes depend on its line-end
   settings. The JSON content does not change.

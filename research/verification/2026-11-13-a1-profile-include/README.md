# The A1 profile's `include` key, 2026-11-13

Task 1 of `docs/plans/2026-11-13-color-slicing.md` (plan Decision 1).

**Question:**
- How does OrcaSlicer 2.5.0 resolve a vendor preset's `include` key?
- Does the fixed flattener put the A1's own G-code into `profiles-flat/machine.json`?
- What happens to the owner's two R1 slices (Roadie and Oddie, 60 × 3 mm) with the fixed
  profile?

**Short answer:**
- **Resolution:** a preset is its parent's resolved config, then each included preset's
  settings in the order listed, then the preset's own keys. For the A1 this is the same
  as a plain merge of the five templates' G-code keys between the parent chain and the
  leaf (the condition is checked below).
- **The fixed profile:** `machine.json` now has the A1 template G-code: the start G-code
  is 12,310 characters and loads the AMS (`M620`). Process and filament are unchanged.
- **The R1 slices: this is the plan's stop-and-report point.** Both still slice to 15
  layers, and every check that was measured before is still PASS, except F3. The verdict
  changed from **PRINTABLE** to **NOT CERTIFIED**: the three G-code F3 checks are UNKNOWN,
  because the A1 start G-code uses G-commands that `tdmg.printed` does not read (the
  first is `G392` at line 759). Nothing was changed to make them pass.

**What kind of evidence:**
- **Source:** OrcaSlicer source at tag v2.5.0, read on 2026-11-13.
- **Measured:** the flattener's output and two real slices with both pinned slicers, on
  the owner's Windows PC on 2026-11-13. Nothing was printed.

## What was read

All files were fetched on 2026-11-13 from
`https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/v2.5.0/<path>`. Their hashes and
every quoted line, with its line number, are in `source-excerpts.txt`. A script checked
each quote against the fetched file (26 quotes, 0 mismatches). OrcaSlicer is AGPL-3.0:
only short quoted lines are kept here, as evidence. No code was copied into the repo.

1. **The key name.** `Preset.hpp:76`: `#define BBL_JSON_KEY_INCLUDES "include"`.
2. **How it is parsed** (`PresetBundle.cpp`, the `parse_subfile` lambda, from line 8421).
   - The vendor files are read with `load_inherits_to_config` false (line 8434). So
     `load_from_json` keeps `include` as JSON text and does not treat it as a setting
     (`Config.cpp:977-978`).
   - The value may be an array of names or one bare name: "An array of names, or one bare
     name" (line 8473).
   - `type`, `name` and `instantiation` are attributes, not settings: `load_from_json`
     puts them in `key_values` (`Config.cpp`, from line 875).
3. **How it is resolved:** `PresetBundle::resolve_vendor_preset` (line 7781).
   - `out.config = *default_config;` (line 7828). This is the parent's resolved config
     (from `inherits`), or the collection default when there is no parent.
   - Then the includes. The comment says: "Layer each included preset's own keys over the
     parent, in the order listed; this preset's own keys go on top." (lines 7829-7830).
     The code: `out.config.apply(it->second);` for each include (line 7837).
   - Then the preset's own keys: `out.config.apply(entry.config_src);` (line 7839).
   - **A missing include is logged and skipped** (`continue` after "can not find
     include", lines 7833-7835). It is not an error that stops the load. The flattener
     refuses instead.
4. **What an included preset gives** (lines 7840-7846 and 7967).
   - It gives its resolved config's diff against the collection default:
     `out.config.diff(presets_collection.default_preset_for(out.config).config)`.
   - So a template's own `inherits` would be followed: its config is resolved like any
     other preset's.
   - A key whose value equals the option's default is **not** in the diff, so it would
     not override the parent's value.
   - The diff is stored in `install.include_maps` of the same collection (`VendorInstall`
     per list in `install_vendor`). So an include is looked up among the same kind's
     presets only (here `machine_list`).
5. **The order of loading** (`PresetBundle::install_vendor_entries`, line 8036). A preset
   resolves only after every preset it inherits from or includes. Lines 8073-8076: "A run
   of entries resolves together and commits in listing order, and ends before an entry
   that inherits or includes one already in it."
6. **The defaults of the five options** (`PrintConfig.cpp`).
   - `machine_start_gcode` (7004): `"G28 ; home all axes\nG1 Z5 F5000 ; lift nozzle\n"`.
   - `machine_end_gcode` (2510): `"M104 S0 ; turn off temperature\nG28 X0  ; home X
     axis\nM84     ; disable motors\n"`.
   - `layer_change_gcode` (5302), `time_lapse_gcode` (5310) and `change_filament_gcode`
     (8108): empty.

### What this means for the A1 machine preset

- **The upstream files:**
  - `Bambu Lab A1 0.4 nozzle.json` (sha256 `1291507434ad…`, as pinned) inherits
    `fdm_bbl_3dp_001_common`, and its `include` names five templates, in this order:
    `machine_start_gcode`, `machine_end_gcode`, `time_lapse_gcode`,
    `change_filament_gcode`, `layer_change_gcode`.
  - The full names are `Bambu Lab A1 0.4 nozzle template <key>`. All five are in
    `BBL.json` `machine_list`.
  - Each template has exactly `type`, `name`, `instantiation` (`"false"`) and the one
    G-code key. None has `inherits` or `include`.
  - No other file in the three chains has an `include` key.
  - The leaf sets none of the five G-code keys itself.
- **So Orca's result:** the parent chain's resolved config, then the five G-code keys
  from the templates, then the leaf's own keys.
- **Equal to a plain merge, here:** this is the same as a plain merge of each template's
  settings, because every template value differs from the option's default
  (`compare-flat.txt`, `template == default: False` for all five). If a template value
  equalled the default, Orca would keep the parent's value, and a plain merge would not.
  The flattener does not know Orca's defaults, so it cannot detect that case. The pinned
  output hash would show any change in the upstream files.
- **`layer_change_gcode`:** the template value equals the parent chain's value (149
  characters), so this key does not change.

## What was changed

- **`scripts/setup_orcaslicer.py` `flatten`.**
  - At each preset of the chain (root first), it layers the templates the preset's
    `include` names, in order, then the preset's own keys.
  - A template's `type`, `name` and `instantiation` are not copied.
  - **Refused:**
    - a template not in the same kind's index list;
    - a template not in the pin's `upstream_sha256`, or with a different hash;
    - a template whose `name` differs from the include;
    - a template with `inherits`, `include` or another attribute key: Orca would follow
      `inherits` and `include`, and this flattener does not model that;
    - includes that differ from the pin's `includes` list.
  - Every pinned upstream file must be used by a chain or an include (the `unused`
    check).
  - The output drops `include` (added to `drop_keys`), since it is resolved.
  - A new `--profiles-only DIR` checks the installed app (whole tree), flattens again and
    swaps the folder in. The old folder is kept as `profiles-flat.previous`.
- **The pin** (`profiles/slicers/orcaslicer-2.5.0.yaml`):
  - `includes` for the machine profile;
  - the five template hashes in `upstream_sha256`;
  - the new `machine.json` and `manifest_sha256` hashes;
  - `include` in `drop_keys`.
- **`tdmg.slicing`:** `SLICE_ALGORITHM_VERSION` changes from `slice-4` to `slice-5`. The
  checks are unchanged.
- **The 2026-11-10 record:** it is kept as it was.
  - `tests/test_slicer.py` now takes the profile hashes and the manifest from this
    record. The install, app and chain values still come from the 2026-11-10 record.
  - A test checks that only `machine.json` and the manifest changed. It also checks that
    the new manifest is the old one plus the five templates.

## What was run

1. **`flatten_with_include.py OUT`.** An independent flattener, written apart from the
   setup script, with the same resolution.
   - Output: `flatten-output.txt` (chains, includes, hashes, G-code key lengths),
     `flattened-hashes.txt` and `source-manifest.json`. The pin's values were copied from
     these files.
   - Two runs gave byte-identical `machine.json`.
2. **`compare_flat.py OLD NEW TEMPLATES`** (`compare-flat.txt`). It compares the old flat
   `machine.json` (now `profiles-flat.previous/`) with the new one:
   - **Gone:** `include`.
   - **Changed:** `machine_start_gcode` (577 → 12,310 characters),
     `machine_end_gcode` (1,358 → 2,902), `time_lapse_gcode` (429 → 1,388) and
     `change_filament_gcode` (4,030 → 6,156).
   - **Equal:** every other key, `layer_change_gcode` included.
   - Each new value equals its template exactly.
3. **`uv run python scripts/setup_orcaslicer.py --profiles-only
   artifacts/tools/orcaslicer-2.5.0`.**
   - Every upstream file matched the pin.
   - The new `machine.json` is `bc1aadae…` and the manifest is `cfcbb8d7…`.
   - The written `machine.json` is byte-identical to the research script's.
   - `--verify-only` then passed (exit 0; app tree 4,054 files, `b5cf3ff8…`).
4. **The owner's two R1 slices, as on 2026-11-11 but into new folders.** The command, for
   `sel` in `roadie-tol30` and `oddie`:
   `uv run tdmg slice artifacts/flat-runs/<sel>-60x3-s5 --out
   artifacts/slice-runs/<sel>-60x3-slice5 --slicer-dir artifacts/tools/orcaslicer-2.5.0
   --prusaslicer-dir artifacts/tools/prusaslicer-2.9.7`.
   - The CLI output is in `cli-roadie-tol30.txt` and `cli-oddie.txt`.
   - `compare_slices.py` (`compare-slices.txt`) compares them with the 2026-11-11 runs
     (`*-60x3-f64`).
5. **`pytest -m slicer`** with both pinned slicers: 2 passed and 1 failed. The failure is
   `test_roadie_slices_with_the_real_slicer`, which expects the three F3 checks to PASS;
   they are UNKNOWN.

## Results: R1, old against new

| | Roadie old (`slice-4`) | Roadie new (`slice-5`) | Oddie old | Oddie new |
|---|---|---|---|---|
| Verdict | PRINTABLE | **NOT CERTIFIED** | PRINTABLE | **NOT CERTIFIED** |
| Layers | 15 | 15 | 15 | 15 |
| Time (slicer estimate) | 471.9 s | 866.7 s | 484.2 s | 876.1 s |
| Weight (slicer estimate) | 2.2724 g | 2.2474 g | 4.3461 g | 4.3211 g |
| F3.printed_connectivity | PASS (15 layers, 0 mismatched) | UNKNOWN | PASS (15, 0) | UNKNOWN |
| F3.edge_coverage | PASS (max gap 0.231 mm, 0 layers over) | UNKNOWN | PASS (0.222 mm, 0) | UNKNOWN |
| F3.edge_overprint | PASS (0 layers over) | UNKNOWN | PASS (0) | UNKNOWN |
| Start G-code | 40 lines, generic, no `M620` | 626 lines, A1 template, 3 `M620` lines | 40 lines | 625 lines, 3 `M620` lines |

- **Every other check:** each F1, F2, F4, F5 and F6 check is PASS in both runs, and
  `F3.thin_regions` is UNKNOWN (information only) in both.
- **`F6.portability`:** still PASS. PrusaSlicer is not affected by the OrcaSlicer
  profile.
- **The new start G-code:** after the slicer's own header lines and `; FEATURE: Custom`,
  it begins `;===== machine: A1 =========================`,
  `;===== date: 20260513 ==================`, `G392 S0`, `M9833.2`, the template's first
  lines.

### Why F3 is UNKNOWN

`tdmg.printed` reads only the G-commands in `G_COMMANDS` (`src/tdmg/printed.py`):
G0, G1, G2, G3, G17, G21, G28, G29, G90, G91 and G92. That set was seen in the old,
generic G-code. Any other G-command makes the G-code unsupported, so the checks are
UNKNOWN, by design. Both new G-codes contain these G-commands, outside comments, that the
reader does not read (counted per file):

| Command | Count |
|---|---|
| G392 | 26 |
| G380 | 23 |
| G39.3 | 12 |
| G29.2 | 2 |
| G39 | 1 |
| G39.4 | 1 |
| G29.4 | 1 |
| G2814 | 1 |

The new G-code also has more G0, G90, G91 and G92 lines (for example, relative G2 arcs
for the nozzle wipe, and G0 moves with E in the template's extrusion test). Deciding how
to read these Bambu firmware commands is a design change to F3. It is not part of this
task.

## What is not known

- **Whether `plate_1.gcode` may now be printed.** `tdmg slice` still says to slice
  `model.stl` in Bambu Studio. Its stated reason ("the pinned A1 profile is incomplete")
  is no longer true after this fix, but F3 cannot be measured on the new G-code. Nothing
  from `tdmg` has been printed, with either profile.
- **Why the weight fell by 0.025 g** (about 20 mm³ on both models). The likely cause is a
  different purge in the start G-code, but this was not checked. The slicer's estimates
  are not measurements.
- **How the OrcaSlicer CLI treats `include` in a settings file it loads.** That code path
  was not read. With `--load-settings`, the old `machine.json` (which still had the
  `include` key) gave the generic G-code. So the key was not resolved there.
- **Another case of the default rule.** The flattener cannot tell when an included value
  equals Orca's default (item 4 above). That case does not occur in the pinned files.
- **Other machines and versions.** Only the Windows PC and OrcaSlicer 2.5.0 were run.

## Addendum: the G-code reader and the A1 firmware commands, 2026-11-13

The controller decided how `tdmg.printed.parse_gcode` should read the A1 template G-code:
strict outside FEATURE "Custom", and firmware G-commands accepted inside it.

**Short answer: this is a second stop-and-report point.** The reader change is made and
tested, but the real G-code still cannot be measured. The time-lapse G-code runs at every
layer change, and it holds firmware G-commands **outside** Custom. Outside Custom the
reader stays strict, as decided, so F3 is still UNKNOWN and the verdict is still NOT
CERTIFIED.

### The reader change (`src/tdmg/printed.py`)

- **Inside Custom:** a G-command that is not in `G_COMMANDS` is a firmware command. It
  may have a `.n` subcode (`CUSTOM_G_COMMAND`).
  - **The effect:** it is accepted, and it makes X, Y and the commanded Z unknown until
    the next absolute ones, as G28 does.
  - **Its words:** they must be finite plain numbers, and X and Y must be within
    `plate.within_bound`.
  - **Moves in Custom:** relative G2 arcs, R-form arcs and G0 with E are followed for the
    position only. They were already excluded from the model, and none goes through the
    arc splitter, so none can raise there except at the bound.
- **Refused even in Custom** (`CUSTOM_REFUSED_G`; my addition, not in the controller's
  list): these change how every later model move is read.
  - arc planes: G18, G19;
  - inches: G20;
  - coordinate systems and offsets: G10, G53 to G59 and their subcodes, and G29.1 (the
    template's Bambu Z offset, written only for a textured PEI plate);
  - a subcode of any followed command except G29: G0.n to G3.n, G90.1, G91.1 and G92.n.
- **Outside Custom:** unchanged.
- **Tests** (`tests/test_printed.py`):
  - a Custom block with G392 S0, G380, G39.4, G29.2, G39.3, G2814, G29.4, relative G2
    arcs, an R-form arc and G0 with E, then a model extrusion after an absolute move:
    this parses;
  - the same commands outside Custom: refused;
  - a model extrusion straight after a firmware command, with no absolute X and Y:
    refused ("unknown position");
  - X and Y set again but not Z: refused ("commanded Z None");
  - bad words, out-of-bound X or Y, and each command in `CUSTOM_REFUSED_G`, in Custom:
    refused.

### What the real G-code holds (`scan_gcommands.py` → `scan-gcommands.txt`)

Both owner G-codes (`*-60x3-slice5b`) hold these G-commands outside `G_COMMANDS`, by the
FEATURE in force:
- **In Custom (the start and end code):** G392 (2), G380 (23), G39.4 (1), G29.2 (2),
  G2814 (1) and G29.4 (1).
- **Outside Custom:** G392 (24), G39.3 (12) and G39 (1). The FEATURE in force is the
  previous layer's last feature, for example "Outer wall".
  - **Where they come from:** the template's `time_lapse_gcode`. OrcaSlicer writes it at
    each layer change, inside the template's own `; SKIPPABLE_START` and
    `; SKIPPABLE_END` comments, with no FEATURE line.
  - **G39 S1:** on the third layer, at `G0 X261 Y250`.
  - **G39.3 S1, between G392 S0 lines:** from the fourth layer on.
  - The old, generic `time_lapse_gcode` (429 characters) had no firmware G-commands.
- **Extrusion:** there is no Custom extrusion after the first model extrusion, so the
  end code does not extrude, and the rule that refuses one still holds. The time-lapse
  blocks do not extrude either: they use G92 E0 and travel only.
- **The first model extrusion:** it does not come from an unknown position or Z in
  either file. In the experiment below, the parse reached and passed every model move.

### An experiment only: SKIPPABLE blocks read as Custom (not in the code)

`experiment_skippable.py` (→ `experiment-skippable.txt`) runs `f3_checks` on the real
G-code with a "; FEATURE: Custom" line added after each `; SKIPPABLE_START`, and the
previous FEATURE restored after each `; SKIPPABLE_END`. This shows what such a rule would
give. It is not a decision.

| | F3.printed_connectivity | F3.edge_coverage | F3.edge_overprint |
|---|---|---|---|
| Roadie, old (slice-4) | PASS, 0 layers mismatched | PASS, max gap 0.23120786 mm, 0 layers over | PASS, 0 over |
| Roadie, experiment | PASS, 0 mismatched | PASS, max gap 0.23120786 mm, 0 over | PASS, 0 over |
| Oddie, old | PASS, 0 mismatched | PASS, max gap 0.22234656 mm, 0 over | PASS, 0 over |
| Oddie, experiment | PASS, 0 mismatched | PASS, max gap 0.22234656 mm, 0 over | PASS, 0 over |

- **Why the numbers are identical:** the model's moves are identical. The positive E
  outside Custom is the same to the micrometre in old and new: 891.810 mm (Roadie) and
  1,480.841 mm (Oddie) (`extrusion-by-feature.txt`).

### The weight drop (`extrusion_by_feature.py` → `extrusion-by-feature.txt`)

- **The drop is the same on both models.** The header's "filament used [mm]" falls by
  exactly 8.26 mm on both: Roadie 749.81 → 741.55, Oddie 1,434.04 → 1,425.78. That is
  0.025 g, or about 20 mm³.
- **It is not the model:** the model's extrusion is unchanged.
- **It is not the new purge, counted:** the start code's positive E in Custom grows from
  45.8 mm to 147.5 mm, yet the slicer's total falls.
- **So:** the slicer's filament estimate does not equal the G-code's positive E. The
  start and end code changes it by a constant. How OrcaSlicer counts Custom E (for
  example, retractions in the end code, or E moves inside the firmware's conditional
  blocks) was not traced.

### The slices again

- **The command:** as before, into `artifacts/slice-runs/<sel>-60x3-slice5b`. The
  `*-60x3-slice5` runs are kept.
- **The result:** both slices are NOT CERTIFIED with F3 UNKNOWN. Roadie stops at line
  5719 and Oddie at line 3486, on `G39`, outside Custom.
- **The G-code** differs from slice5's only in the header timestamp.
- **`pytest -m slicer`:** `test_roadie_slices_with_the_real_slicer` still fails, for
  this reason.

### The message

`PRINT_THIS` now gives a reason that is true: "slice model.stl in Bambu Studio to print;
plate_1.gcode is for checking only (tdmg's G-code is not yet printed or compared with
Bambu Studio's own slice); …".

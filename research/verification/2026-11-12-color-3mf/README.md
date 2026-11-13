# Multicolor 3MF import test, 2026-11-12

Task 1 of `docs/plans/2026-11-12-color-3mf.md` (plan Decision 1).

**Question:** which 3MF encoding of the AMS bodies does the pinned OrcaSlicer 2.5.0 import so that:
- every body imports;
- each body keeps its position and name;
- each body lands on its own filament, with no slicer-side assignment?

The second part of the question: does PrusaSlicer 2.9.7 import every body in place?

**Short answer:** no core/Materials encoding passes in OrcaSlicer. This is the plan's stop-and-report point.
- Separate top-level objects (A) get one filament each, but OrcaSlicer moves them. It arranges them apart, and with `--arrange 0` it drops each inlay to the bed, so the slice fails.
- One assembly (B) and one multi-shell mesh (D) stay in place, but everything prints with one filament.
- Only a Bambu/Orca metadata file (`Metadata/model_settings.config`, not part of 3MF core or Materials) gives each part its own filament in place.
- PrusaSlicer also drops every separate object (A, B, C) to the bed. It then reports a path conflict and crashes after writing the G-code. Only D slices cleanly there.

**What kind of evidence:** CLI behaviour of the two pinned slicers on Windows, measured on the owner's PC on 2026-11-12. Nothing was printed. No GUI was run. Bambu Studio was not run.

## Setup (run)

- **Slicers:** both were verified against their pins before use, with the full app tree, by `scripts/setup_orcaslicer.py --verify-only` and `scripts/setup_prusaslicer.py --verify-only`.
  - OrcaSlicer: 4,054 files, tree `b5cf3ff8…`.
  - PrusaSlicer: 1,119 files, tree `5515fb4a…`.
  - The script verifies them again through `tdmg.slicer.locate` and `tdmg.portability.locate_prusaslicer`, and records the hashes in the raw JSON.
- **Bodies:**
  - **Roadie:** the 4 AMS STLs in `artifacts/colored-runs/roadie-tol30-60-drop-v3-f64/`: `ams-base.stl` and `ams-color-1/2/3-*.stl`, colorflat-2, colorflat_id `fa6eb820…`. The script read them as binary STL and merged only exactly equal float32 vertices.
  - **Synthetic:** built with manifold3d.
    - The base is a 20 x 20 x 3 mm box with a 10 x 10 x 0.6 mm pocket at the top centre.
    - The inlay is a 10 x 10 x 0.6 mm box at z 2.4 to 3.0 mm.
  - **Probe:** the synthetic inlay alone, as encoding A.
- **Files:** written by `measure_import.py`, which uses zipfile and lxml.
  - The parts are `[Content_Types].xml`, `_rels/.rels` and `3D/3dmodel.model`, deflated, dated 1980-01-01, with mode 0644.
  - Namespaces: core `2015/02` and Materials `2015/02`. Unit `millimeter`.
  - Vertices are written as shortest round-trip float32 text (`np.format_float_positional(unique=True)`). There are no UUIDs and no metadata.
  - Two builds gave byte-identical files (all 13; SHA-256 in `raw/build.json`).
  - The synthetic and probe files are kept in `fixtures/`. The Roadie files (0.94 to 0.96 MB each) are not kept; `raw/build.json` has their hashes, and the script makes them again.

### Encodings

| Id | What | Portable (core + Materials only)? |
|---|---|---|
| A | one top-level `<object>` per body, each with its own `m:colorgroup` holding one `m:color #RRGGBBFF`; `pid`/`pindex` on the object; name `base #f60606`, `color-1 #f5f5f5`, …; one `<item>` per object | yes |
| B | the A mesh objects (colored as in A), referenced by one components object `assembly`; one `<item>` | yes |
| C | as A, but the objects reference one core `<basematerials>` group with one `<base name=… displaycolor=…>` per body (object `pid` = the group, `pindex` = the body), and there are no colorgroups. This is the valid single-`pid` form: an object has one `pid`, so "colorgroup and basematerials together" is not possible on one object | yes |
| A_shared | extra: as A, but one shared colorgroup with all colors, and `pindex` per object | yes |
| D | extra: one mesh object holding every body as its own closed shell. One shared colorgroup; each triangle has `pid` and `p1` = its body's color | yes |
| B_msc | extra, the Orca-native hint: B plus `Metadata/model_settings.config` giving each part an `extruder` (1 to 4) | **no**: Bambu/Orca project metadata |

### lib3mf read-back (2.5.0, strict mode), every file

- Unit `MilliMeter`, with no reader warnings.
- The expected mesh objects (B: plus 1 components object; D: 1 mesh), the expected names, and `IsManifoldAndOriented` true for every mesh.
- The vertices equal the source float32 vertices exactly, and the triangle counts are equal.
- The object-level property is present on every object. See `raw/build.json`.

### Commands (exactly as run; `<repo>`, `<out>` replace local paths)

OrcaSlicer, all variants:

```
<repo>\artifacts\tools\orcaslicer-2.5.0\app\orca-slicer.exe <out>\FILE.3mf
  --load-settings <repo>\...\profiles-flat\machine.json;<repo>\...\profiles-flat\process.json
  --load-filaments <f>;<f>;<f>;<f>          (f = <repo>\...\profiles-flat\filament.json, the pinned one, four times)
  [variant arguments]
  --slice 0 --outputdir <out>\orca\VARIANT\FILE\out --export-statistics --debug 3 --logfile <out>\orca\VARIANT\FILE\slicer.log
```

The CLI accepted four filaments in this form: the log has "loaded filament 1..4 from file". The variants were:

| Variant | Arguments | Files |
|---|---|---|
| plain | none | all |
| arrange0 | `--arrange 0` | all |
| arrange0_noensure | `--arrange 0 --ensure-on-bed=0` | synthetic-A, probe |
| assemble | `--assemble` | synthetic-A only (run as `orca OUT assemble synthetic-A`) |

Two more forms of the ensure-on-bed run were tried and failed; their output was overwritten by the next run, and only this observation is recorded:
- `--ensure-on-bed 0` exited −3: the `0` was read as a file name ("No such file: …\0").
- `--no-ensure-on-bed` exited −2 ("Invalid option --no-ensure-on-bed").

PrusaSlicer, `prusa-slicer-console.exe`:
- `--info FILE.3mf`
- `--export-gcode FILE.3mf -o out.gcode [--dont-arrange] --gcode-label-objects octoprint`, plus the six settings that `tdmg.portability.explicit_settings` takes from the pinned A1 profiles: `--bed-shape 0x0,256x0,256x256,0x256 --max-print-height 256 --nozzle-diameter 0.4 --layer-height 0.2 --first-layer-height 0.2 --filament-diameter 1.75`.
- `--gcode-label-objects octoprint` was added so that the G-code names each object. Its default in this setup was `disabled`: an earlier run without it showed `; gcode_label_objects = disabled`.

Commands to reproduce, from the repo root (`OUT` = a scratch folder):

```
uv run python research/verification/2026-11-12-color-3mf/measure_import.py build OUT
uv run python research/verification/2026-11-12-color-3mf/measure_import.py orca OUT plain
uv run python research/verification/2026-11-12-color-3mf/measure_import.py orca OUT arrange0
uv run python research/verification/2026-11-12-color-3mf/measure_import.py orca OUT arrange0_noensure
uv run python research/verification/2026-11-12-color-3mf/measure_import.py orca OUT assemble synthetic-A
uv run python research/verification/2026-11-12-color-3mf/measure_import.py prusa OUT
```

### How the G-code was read (`gcode_facts`)

- **Objects:** both slicers write `; printing object NAME id:N copy M` … `; stop printing object NAME …`. OrcaSlicer also writes `; start printing object, unique label id: K` and `M624`/`M625`.
- **Filaments:**
  - Tool changes are the `T<n>` lines. OrcaSlicer wraps each one in `M620 S<n>A` … `M621 S<n>A`; `T255` and `M620 S255` are the end-of-print unload.
  - Extrusion counts only G0/G1 moves that extrude and change X or Y (relative E, `M83`). E-only flush moves are excluded on purpose.
  - Each extruding move is assigned to the current object and the current tool.
- **The first filament:** the pinned machine profile's start G-code selects no filament (see Surprises), so extrusion before the first `T` is "None", the filament Orca started with. In every run with tool changes, the first change goes to a different filament, and the header `; filament:` lists the filaments used. Both show that "None" is T0 (filament 1) in these runs.
- **Positions:** the XY extent of the extrusion and the range of layer Z (from `; Z_HEIGHT:` or `;Z:`) of each object, and of each object and tool. These show where each body was printed.

## Results

Expected positions in the file:
- **Synthetic:** the base is at x, y 0 to 20 and z 0 to 3. The inlay is at x, y 5 to 15 and z 2.4 to 3.0. On the 0.2 mm layers the inlay is the layers at Z 2.6, 2.8 and 3.0.
- **Roadie:** the base is at x 0.03 to 60, y 0 to 49.4 and z 0 to 3. The three inlays are at z 2.4 to 3.0.

### OrcaSlicer 2.5.0, plain (no extra arguments)

| File | Exit | G-code | Tool changes | Filament per body (extrusion by tool) | Names | Position |
|---|---|---|---|---|---|---|
| synthetic-A | 0 | yes, 15 layers | T1 ×2, T0 ×2 (M620 S1A ×2, S0A ×2) | base → T0, inlay → T1 | 2 objects, names kept | **moved**: the objects are arranged apart (base y 124 to 144, inlay y 112 to 122), and the inlay is printed at Z 0.2 to 0.6, dropped to the bed |
| roadie-A | 0 | yes, 15 layers | T1 ×2, T2 ×3, T3 ×3, T0 ×2; statistics `filament_changes` 9 | base → T0, color-1 → T1, color-2 → T2, color-3 → T3 | 4 objects, names kept | **moved**: arranged apart, every inlay at Z 0.2 to 0.6 |
| synthetic-B, roadie-B | 0 | yes, 15 layers | none | everything on one filament | 1 object, `assembly` | **in place**: one body, centred on the bed; the inlay at Z 2.6 to 3.0 inside the base |
| synthetic-C, roadie-C | 0 | yes | none | everything on one filament | names kept | moved, as in A |
| A_shared (both) | 0 | yes | none | everything on one filament | names kept | moved, as in A |
| synthetic-D, roadie-D | 0 | yes, 15 layers | none | everything on one filament (per-triangle colors not used) | 1 object, `model` | in place, centred |
| synthetic-B_msc | 0 | yes, 15 layers | T1 ×2, T0 ×1 | base → T0; inlay → T1, which extrudes only at x 123.2 to 132.8 and Z 2.6 to 3.0, the inlay's place | 1 object, `assembly` | in place, centred |
| roadie-B_msc | 0 | yes, 15 layers | T1 ×3, T2 ×3, T3 ×2, T0 ×1; `filament_changes` 8 | base → T0; T1, T2 and T3 extrude only at Z 2.6 to 3.0, within the XY extents of color-1, color-2 and color-3 (file extents shifted by the same +98.2, +103.5 centring as the base) | 1 object | in place, centred |
| probe-inlay-only-A | 0 | yes, 3 layers | none | one filament | kept | the inlay is printed at Z 0.2 to 0.6, not 2.4 to 3.0: **a top-level object is dropped to the bed** |

The debug log for every non-Bambu 3MF says:
- "found 3mf from other vendor, split as instance";
- "process group colors, size N";
- "begin to assemble objects";
- "before arrange, need_arrange=1".

The project filament colors stayed those of the profile (`#F2754E;#FFFFFF;#FFFFFF;#FFFFFF`). The file's colors did not change the filament colors; they only chose the filament index (A and B_msc).

### OrcaSlicer 2.5.0, other variants

| Variant | File | Result |
|---|---|---|
| `--arrange 0` | synthetic-A, synthetic-A_shared, synthetic-C, roadie-A_shared, roadie-C | exit −101 `CLI_GCODE_PATH_CONFLICTS`. XY is kept, but the inlays are still dropped to the bed; the log says "gcode path conflicts found between color-1 #f5f5f5 and base #f60606" |
| `--arrange 0` | roadie-A, roadie-B_msc | exit −64 `CLI_OBJECT_COLLISION_IN_LAYER_PRINT`, with the message "Prime tower is partially outside the printable area" (the parts sit at the file's x, y from 0, at the bed corner) |
| `--arrange 0` | synthetic-B, roadie-B, synthetic-D, roadie-D | exit 0, one filament, at the file's own coordinates (roadie: x 0.25 to 59.73) |
| `--arrange 0` | synthetic-B_msc | exit 0, base T0 and inlay T1, at the file's coordinates (inlay x 5.2 to 14.8, Z 2.6 to 3.0) |
| `--arrange 0` | probe | exit 0, the inlay at the file's XY (5.2 to 14.8) but at Z 0.2 to 0.6: dropped |
| `--arrange 0 --ensure-on-bed=0` | probe, synthetic-A | accepted, but no effect seen: the probe is still dropped, and synthetic-A still exits −101 |
| `--assemble` | synthetic-A | exit 0, one object `Assembly`, T0 and T1 used, but extrusion only to Z 1.4 and statistics volume 510.8 mm³, not about 930: **a broken print**; not usable |
| `--assemble` | roadie-A | not run: the synthetic case already rules it out |

All these flags are slicer-side, and none of them gives the result without the Bambu metadata.

### PrusaSlicer 2.9.7

| File | `--info` | Slice (default or `--dont-arrange`; same result both ways) |
|---|---|---|
| A, A_shared, C (both fixtures) | exit 0; one `[file]` block per body (2 or 4) with that body's size and volume (synthetic 1140.000000 and 59.999996 mm³; Roadie 2090.488770, 126.908630, 57.799355, 2.508382 mm³), each manifold | XY kept, but every inlay is printed at Z 0.2 to 0.6. It prints "gcode path conflicts found between color-1 #f5f5f5 and base #f60606", writes a G-code that ends with `; prusaslicer_config = end`, and then exits **3221225477 (0xC0000005, access violation)** |
| B, B_msc | as A: the assembly is **expanded into separate objects**, each named after its body | same as A: dropped inlays, conflict, crash |
| D | exit 0; 1 object; `number_of_parts` 2 (synthetic) or 10 (Roadie), volume 1200.000000 or 2277.693359 mm³ | exit 0, 15 layers, at the file's XY (synthetic 0.2 to 19.8), the inlay in place. The object is named after the file (`synthetic-D`), not `model`. One extruder |
| probe | exit 0 | exit 0, the inlay at Z 0.2 to 0.6: dropped |

PrusaSlicer used no colors in any run (no tool changes), as expected from the source reading.

## Verdict per encoding (OrcaSlicer criteria: imports / in place and named / own filament)

| Encoding | OrcaSlicer | PrusaSlicer | Verdict |
|---|---|---|---|
| A | yes / **no** (arranged apart; inlays dropped to the bed; `--arrange 0` then fails with −101) / yes | inlays dropped, conflict, crash | **fails** |
| B | yes / yes (part names not visible in the CLI output) / **no** (one filament) | expanded, dropped, crash | **fails** |
| C | yes / no / no | as A | fails |
| A_shared | yes / no / no | as A | fails (confirms the source reading: one color per group) |
| D | yes / yes / no | **in place, slices** | fails in Orca; the only one that is clean in PrusaSlicer |
| B_msc (not portable) | yes / yes / **yes** | expanded, dropped, crash | passes in Orca only, through vendor metadata |

## Recommendation for plan Decision 1

**Stop before Task 2, as the plan says.** No encoding that uses only 3MF core and Materials gives one filament per body in place in OrcaSlicer 2.5.0 (CLI).

The cause is not the colour tags. It is that both slicers print every top-level object from the bed up: a body that starts at z 2.4 mm cannot be its own object. So a multicolor file must hold all the bodies in one object. Then:
- OrcaSlicer's only per-part filament source we found is its own `Metadata/model_settings.config`;
- PrusaSlicer needs one mesh object (D), because it expands assemblies into separate objects (which it then drops and crashes on).

Options for the owner to choose from (none is chosen here):

1. **D as the portable file** (one mesh object, one shell per body, per-triangle Materials colors, object names lost), with `palette.json` as the guarantee. Each slicer then needs a slicer-side step, done by the user: split the object into parts and assign the filaments. Both slicers open it in place; PrusaSlicer slices it. PLAN section 2 point 7 holds; per-body filament assignment does not come from the file.
2. **B plus `Metadata/model_settings.config`** (B_msc). It works in OrcaSlicer, in place, with the right filament per body. It is vendor metadata, and PrusaSlicer crashes on it (as on B). Under PLAN point 7 it could only be an extra, Orca/Bambu-specific file, not the portable one.
3. **Test further before deciding:**
   - D plus PrusaSlicer's own `Metadata/Slic3r_PE_model.config` (volumes by triangle range, extruder per volume), and whether OrcaSlicer reads that file for a non-Bambu 3MF;
   - the GUIs: OrcaSlicer's and Bambu Studio's handling of A. PrusaSlicer-family GUIs may offer to load objects at different heights as one multi-part object; that is a hypothesis, not tested.

## Surprises

- **Both slicers drop each top-level object to the bed**, so the plan's encoding A, picked from the source reading, cannot keep inlays in place. In OrcaSlicer, `--ensure-on-bed=0` had no visible effect.
- **PrusaSlicer 2.9.7 crashes (0xC0000005)** after writing the G-code for every file with more than one object. It first logs a path conflict, and the G-code file looks complete. A wrapper that trusted the G-code file would miss the crash; the exit code shows it.
- **OrcaSlicer's statistics per filament do not match the G-code.** In synthetic-A, `filaments[1].model.volume` is 208.5 mm³, but the inlay object is 58.6 mm³ and the G-code extrudes T1 only on the inlay. In B_msc, the statistics give filament 2 the base-sized volume (779.7 mm³), but the G-code prints the base with T0. These numbers were not used for any verdict, and the cause is not known.
- **The pinned A1 machine profile has a 577-character `machine_start_gcode` that loads no filament** (no `M620`, no `T`). It draws a purge line at x 10. The G-code therefore never selects the first filament. This was not compared with the upstream Bambu profile. It matters for step 4 (AMS printing) and should be checked before anything is printed from these profiles.
- **The file's colors never reach OrcaSlicer's filament colors** in the CLI (they stay the profile's). The colorgroup only chooses the filament index.

## Not tested

- Bambu Studio, any version (the owner's check, plan Decision 6).
- The GUIs of OrcaSlicer and PrusaSlicer, including any "load as one multi-part object" dialog.
- POSIX builds.
- Printing anything.
- Glue bodies.
- Encodings with the Production extension.
- PrusaSlicer's own metadata.
- Why PrusaSlicer crashes. The crash was seen; it was not debugged.

## Files

- `measure_import.py`: builds the bodies and the candidate files, runs the lib3mf read-back, runs both slicers, and extracts the facts from the G-code. It uses `tdmg.slicer` and `tdmg.portability` read-only.
- `fixtures/`: the synthetic and probe 3MF files (about 1.3 kB each).
- `raw/build.json`: the bodies, the file hashes and the lib3mf read-back.
- `raw/orca-plain.json`, `raw/orca-arrange0.json`, `raw/orca-arrange0_noensure.json`, `raw/orca-assemble.json`: per run:
  - the argument template;
  - the decoded exit code;
  - the G-code facts (tool commands, M620/M621, header lines, per-object and per-tool extrusion and extents);
  - the statistics (without the per-layer list);
  - the debug-log lines about vendor, arrange, colors and conflicts.
- `raw/prusa.json`: `--info` per object, and per slice the exit code, the output tails and the G-code facts.
- `raw/*-summary.txt`: the console summaries the script printed.
- No G-code is kept.

## The owner's check in Bambu Studio (2026-11-12)

The owner opened `roadie-A.3mf`, `roadie-D.3mf` and `roadie-B_msc.3mf` (copied to
`artifacts/3mf-import-test/`, git-ignored) in their Bambu Studio. Their answer, verbatim:

> It opened; roadie-a and roadie-d had all colors in place but roadie-b_msc was
> compresssed to one color; I can simply match from what I have physically available so
> this is not an issue; a warning "the 3mf is not from bambu lab, load geometry data and
> color data only

**Decision (controller, following the owner's answer): encoding D.** That is one mesh
object with one closed shell per body, a color on each triangle from one `m:colorgroup`,
and `palette.json` as the guarantee.

| Where | Result for D |
|---|---|
| Bambu Studio, the owner's slicer (by the owner) | Opens in place with all colors |
| PrusaSlicer 2.9.7 CLI | Slices in place |
| OrcaSlicer 2.5.0 CLI | In place, but on one filament |

**Why not A:** it also works in Bambu Studio, but PrusaSlicer crashes on it, and
OrcaSlicer's CLI drops its inlays to the bed.

**Filament assignment** is done by the owner in the slicer, matching the palette to the
filaments they have, as they said.

**Open for step 4:** OrcaSlicer CLI slicing of D puts everything on one filament.
Measuring color changes in OrcaSlicer will need either an Orca-specific extra file
(PLAN point 7) or another route.

# Multicolor slicing experiment, 2026-11-13

Task 2 of `docs/plans/2026-11-13-color-slicing.md` (plan Decisions 2, 3 and 4).

**Question:** the pinned OrcaSlicer 2.5.0 slices the B_msc input of each owner plan, face up and face down, with the fixed A1 profiles. In that G-code:
- which filament does the start code load?
- in what order are the tools printed on each layer, and how many changes are there?
- which markers show the flush and the prime tower, and how much plastic goes into them?
- how long does the print take, and how much filament does each tool use?
- does each tool print only its own body, in place?

And how do the G-code's numbers compare with OrcaSlicer's statistics?

**Short answer:**
- **Slicing and placement:** all 16 slices exit 0 (4 plans × 2 faces × 2 filament variants). Each tool's extrusion centrelines lie inside its own body, on its body's layers; the beads' edges reach past the body's outline by at most half a line width (see Placement). Every body is printed by its own tool, and the model is centred on the plate.
- **The start load:** the start code loads one filament: the first tool OrcaSlicer prints on layer 1 (`initial_no_support_extruder`). Face up, that is always the base (T0). Face down, OrcaSlicer chooses it: T1, T0, T2 or T3, depending on the plan. This was the plan's stop point; the controller amended Decision 2 (below).
- **Tool order:** on every layer each tool prints in one run. Each layer starts with the previous layer's last tool when that tool is on the layer. So the change count always equals Σ(colors − 1) plus the layer boundaries where the tool differs.
- **Changes against the minimum:** face up, the count equals the exact minimum, 9, in all runs. Face down it is 10 in some runs (minimum 9): the last color layer ends away from the base. The orders seen are consistent with OrcaSlicer ordering each layer without looking at the next one; its source was not read.
- **Order and flush follow the filament colors.** The CLI computes the flush matrix from `filament_colour`, which the 3MF does not set. So the runs whose filaments carry the plan's colors ("colours") are the primary measurement. The runs with the pinned profile four times ("plain") are the comparison.

**What kind of evidence:** CLI behaviour of the pinned OrcaSlicer 2.5.0 on Windows, measured on the owner's PC on 2026-11-13. Nothing was printed. No GUI was run. Bambu Studio was not run.

## Controller decisions after the stop (2026-11-13)

The first run stopped at the plan's stop point: the face-down start code did not load filament 1. The controller then amended the plan as follows. These are the rules this record checks.

1. **Decision 2, amended:** the start load need not be filament 1. The start block must load exactly one filament, and it must be the first tool that prints on layer 1. Face up that is the base; face down it is OrcaSlicer's choice.
2. **Decision 4, amended:** the gated rule has four parts.
   - (a) Each layer's set of tools in the G-code equals the set of bodies on that layer, from the bodies.
   - (b) On each layer every tool prints in one contiguous run.
   - (c) The change count equals Σ(colors on the layer − 1) plus the number of layer boundaries where the next layer's first tool differs from the previous layer's last.
   - (d) The exact minimum is recorded as information only.
3. **The colours runs are the primary measurement.** The plain runs are kept as the comparison.

## Setup (run)

- **Slicer:** `scripts/setup_orcaslicer.py --verify-only artifacts/tools/orcaslicer-2.5.0` passed before the runs.
  - Profiles: `machine.json` `bc1aadae…`, `process.json` `b4af99bd…`, `filament.json` `0254183f…`.
  - App tree: 4,054 files, `b5cf3ff8…`.
  - The script locates the slicer again through `tdmg.slicer.locate`, with the full tree.
- **Bodies:** `ams-base.stl` and `ams-color-<i>-<hex>.stl` of the four owner runs in `artifacts/colored-runs/`:
  - `roadie-tol30-60-drop-v3-f64`;
  - `roadie-tol30-60-keep-v4-f64`;
  - `oddie-60-merge-blues-v3-f64`;
  - `oddie-60-keep-merge-blues-greens-v4-f64`.

  They are read in palette order from `palette.json`, as binary STL with only exactly equal float32 vertices merged (step 3's `read_stl`). The script checks each body's vertex and triangle counts against `palette.json`. All four plans have 4 colors: base plus 3 inlays.
- **Input files (B_msc):** step 3's encoding, built with step 3's own functions (`measure_import.model_xml(bodies, "B")`, `bambu_model_settings`, `write_3mf`):
  - one components object `assembly`;
  - one mesh part per body;
  - `Metadata/model_settings.config` giving part i the `extruder` i + 1, which is palette index + 1, so the base is 1.

  lib3mf (strict) reads every part back with exactly the source vertices (`raw/build.json`).
- **Face down:** each body is rotated 180° about the y axis through the model's centre: x → x0 + x1 − x, z → T − z, y unchanged.
  - x0 and x1 are the model's x bounds and T = 3.0, the model's top. The lowest z is 0, as checked.
  - Windings are kept, since this is a proper rotation.
  - Results in all 4 plans:
    - every rotated coordinate, computed in float64, is exactly a float32 value (0 inexact in x and in z);
    - float32 arithmetic gives the same values;
    - every body's signed volume is positive and unchanged to float rounding (largest difference 2.4e-12 mm³).
  - The turned inlays span z 0 to 0.5999999046 (= 3 − float32(2.4)), not float32(0.6). They still hold the mid-heights of layers 1–3.
- **Filament variants:**
  - **colours (primary):** four derived filament profiles per plan. Each is the pinned `filament.json` with `filament_colour` set to `[palette hex]` of palette index 0..3.
    - The pinned profile has no `filament_colour` key.
    - The parsed JSON of every derived profile differs from the pinned one in exactly the key `filament_colour`, with the palette's hex: 16 of 16. Their SHA-256 values are in `raw/profiles-colours.json`.
    - They are not pinned profiles.
  - **plain (comparison):** the pinned `filament.json` four times, step 3's run. OrcaSlicer then gives the filaments the colors `#F2754E;#FFFFFF;#FFFFFF;#FFFFFF`.
- **Filament count:** 4 filaments were passed, the plan's color count. No plan had fewer than 4 colors, so the fewer-color case was not tested.
- **`--arrange 0`** was not needed: plain arranging put the model's bounding-box centre within 0.01 mm of the plate centre (128, 128).

### Commands (exactly as run; `<repo>`, `<out>` replace local paths)

OrcaSlicer, every file:

```
<repo>\artifacts\tools\orcaslicer-2.5.0\app\orca-slicer.exe <out>\PLAN-FACE.3mf
  --load-settings <repo>\...\profiles-flat\machine.json;<repo>\...\profiles-flat\process.json
  --load-filaments F0;F1;F2;F3
  --slice 0 --outputdir <out>\orca\VARIANT\PLAN-FACE\out --export-statistics --debug 3
  --logfile <out>\orca\VARIANT\PLAN-FACE\slicer.log
```

`F0;F1;F2;F3` depends on the variant:
- **plain:** the pinned `profiles-flat\filament.json` four times;
- **colours:** `<out>\filaments\PLAN\filament-<i>.json`.

To reproduce, from the repo root (`OUT` = a scratch folder):

```
uv run python research/verification/2026-11-13-color-slicing/measure_slicing.py build OUT
uv run python research/verification/2026-11-13-color-slicing/measure_slicing.py orca OUT colours
uv run python research/verification/2026-11-13-color-slicing/measure_slicing.py orca OUT plain
uv run python research/verification/2026-11-13-color-slicing/measure_slicing.py analyse OUT colours
uv run python research/verification/2026-11-13-color-slicing/measure_slicing.py analyse OUT plain
uv run python research/verification/2026-11-13-color-slicing/measure_slicing.py rules OUT colours
uv run python research/verification/2026-11-13-color-slicing/measure_slicing.py rules OUT plain
uv run python research/verification/2026-11-13-color-slicing/measure_slicing.py profiles OUT
```

### How the G-code was read (`walk`, `analyse_one`, `placement`, `check_rules`)

- **Blocks:**
  - **start:** every line before the first `; CHANGE_LAYER`. There is no `MACHINE_START_GCODE_END` marker in this G-code.
  - **layer N:** from the N-th `; CHANGE_LAYER`. Its Z is the first `; Z_HEIGHT:` after it, and its height is the first `; LAYER_HEIGHT:`.
  - **end:** from the first `; FEATURE: Custom` after the layers began. OrcaSlicer writes it before the end template.
- **Tools:**
  - Every `T<n>` line is recorded with its block, and with the `M620 S<n>A` pair and the `CP TOOLCHANGE` block it lies in.
  - `T1000` is recorded apart: the A1 start template writes it twice, and it is not a filament.
  - A real change is a `T<n>` with n < 255 in a layer block.
- **Extrusion:**
  - A G0–G3 move with E > 0 (relative E) that changes X or Y counts as extrusion, by tool, feature and layer.
  - Arcs are split into chords with `tdmg.printed._arc`.
  - E-only moves (E > 0, no XY change) are summed apart:
    - inside `; FLUSH_START` … `; FLUSH_END`;
    - elsewhere inside `; CP TOOLCHANGE START` … `END`;
    - elsewhere in the layers (unretracts), the start and the end.
  - Volumes are E × π (1.75 / 2)² mm³.
- **Order per layer:** the sequence of tools that print model features (`tdmg.printed.MODEL_FEATURES`), with consecutive repeats merged.
  - Rule (b) holds when no tool appears twice in that sequence.
  - The expected set per layer is every body whose z range holds the layer's mid-height (Z − height / 2).
- **Placement:**
  - Each body is cut at each layer's mid-height (`tdmg.printed.model_section`) and moved to the bed. The shift puts the model's bounding-box centre on the centre of the base tool's model extrusion. It is fitted from the base only, so the inlays' positions relative to the base are still tested.
  - Each tool's extrusion centrelines are sampled every 0.1 mm. For each sample, the script measures the distance to the tool's own body section and whether it lies inside another body's section.
  - The bead footprint (`tdmg.printed.footprint`) gives the area of the own section that the tool covers.
- **Minimum:** the exact minimum is a dynamic programme over each layer's last tool. It starts from the start-loaded tool (`min_changes`).

## Results

All 16 runs:
- exit 0;
- 15 layers at Z 0.2 to 3.0 (0.2 mm);
- the header `; filament: 1,2,3,4`;
- the end code unloads with `M620 S255`, `T255`, `M621 S255`;
- the header's `total estimated time` equals the statistics `time` to within 1 s.

**Placement (all 16 runs):**
- Every tool prints model features only on its body's layers: inlays on 13–15 face up and 1–3 face down; the base on 1–15.
- 0 centreline samples lie outside the tool's own body section. 0 lie inside another body's section.
- No layer has a body without its tool, and no tool prints on a layer without its body.
- The centre of the base tool's centreline extent is within 0.01 mm of the plate centre (this is also the shift used above).
- Bead area outside the tool's own body, summed over layers (the beads' edges past the body's outline; every centreline is inside, so by at most half a line width):
  - base: 6.5 to 14.2 mm² per run, the largest Roadie drop face down (14.15 mm²; Roadie keep face up 9.81 mm²);
  - inlays: 0.00 to 2.74 mm², the largest Roadie keep face up, T1 (#451812, the kept outline band; 2.44 mm² face down).
  The same values in both variants (the model paths do not depend on the colors).
- The covered fraction of each body's sections is information only:
  - base: 0.61 to 0.74 (sparse infill inside);
  - inlays: 0.52 to 0.99.

**Verdict: every body is in place, on its own tool, in every run.**

### colours (primary): filament colors from `palette.json`

Changes are given as G-code / rule (c) / exact minimum / statistics `filament_changes`. Layer orders are tool numbers in print order; T0 is the base.

| Plan, face | Start loads | Changes | Tool order on the multicolor layers | Flush mm³ | Prime tower mm³ | Time s (header = statistics) |
|---|---|---|---|---|---|---|
| Roadie drop, up | T0 | 9 / 9 / 9 / 9 | L13 0312, L14 2031, L15 1203 | 951.3 | 1054.7 | 1873 = 1874 |
| Roadie drop, down | T2 | 10 / 10 / 9 / 10 | L1 2031, L2 1230, L3 0312, then → 0 on L4 | 1051.3 | 592.4 | 1897 = 1897 |
| Roadie keep, up | T0 | 9 / 9 / 9 / 9 | L13 0123, L14 3012, L15 2301 | 951.3 | 1054.7 | 2002 = 2002 |
| Roadie keep, down | T3 | 9 / 9 / 9 / 9 | L1 3201, L2 1032, L3 2310 | 923.8 | 548.2 | 1922 = 1923 |
| Oddie merge blues, up | T0 | 9 / 9 / 9 / 9 | L13 0213, L14 3102, L15 2310 | 900.0 | 1054.7 | 1910 = 1910 |
| Oddie merge blues, down | T0 | 9 / 9 / 9 / 9 | L1 0123, L2 3102, L3 2310 | 900.0 | 548.2 | 1868 = 1869 |
| Oddie keep, up | T0 | 9 / 9 / 9 / 9 | L13 0213, L14 3021, L15 1302 | 600.0 | 1054.7 | 2124 = 2124 |
| Oddie keep, down | T1 | 9 / 9 / 9 / 9 | L1 1032, L2 2013, L3 3120 | 800.0 | 548.2 | 2096 = 2097 |

Filament per tool, from the G-code: model / prime tower / flush blocks, in mm³. The flush blocks are counted on the tool loaded during them, which is the new tool.

| Plan, face | T0 (base) | T1 | T2 | T3 | Statistics `model` T0..T3 |
|---|---|---|---|---|---|
| Roadie drop, up | 1540.0 / 838.2 / 200.0 | 117.1 / 61.8 / 251.3 | 56.0 / 61.8 / 200.0 | 1.6 / 92.8 / 300.0 | 1592.3, 117.1, 56.0, 1.6 |
| Roadie drop, down | 1533.0 / 345.8 / 300.0 | 112.5 / 77.0 / 251.3 | 54.6 / 61.8 / 200.0 | 1.7 / 107.9 / 300.0 | 1533.0, 112.5, 106.9, 1.7 |
| Roadie keep, up | 1448.5 / 838.2 / 200.0 | 171.3 / 92.8 / 300.0 | 79.4 / 61.8 / 251.3 | 37.3 / 61.8 / 200.0 | 1500.8, 171.3, 79.4, 37.3 |
| Roadie keep, down | 1447.3 / 332.4 / 300.0 | 131.0 / 77.0 / 200.0 | 77.7 / 77.0 / 200.0 | 35.3 / 61.8 / 223.8 | 1447.3, 131.0, 77.7, 87.6 |
| Oddie merge blues, up | 2756.4 / 838.2 / 200.0 | 343.3 / 92.8 / 300.0 | 250.0 / 61.8 / 200.0 | 18.9 / 61.8 / 200.0 | 2808.7, 343.3, 250.0, 18.9 |
| Oddie merge blues, down | 2758.8 / 286.4 / 200.0 | 342.2 / 107.9 / 300.0 | 246.9 / 77.0 / 200.0 | 18.4 / 77.0 / 200.0 | 2811.1, 342.2, 246.9, 18.4 |
| Oddie keep, up | 2888.7 / 838.2 / 200.0 | 301.3 / 61.8 / 200.0 | 159.3 / 92.8 / 0.0 | 17.0 / 61.8 / 200.0 | 2941.0, 301.3, 159.3, 17.0 |
| Oddie keep, down | 2884.8 / 332.4 / 300.0 | 299.9 / 61.8 / 200.0 | 112.9 / 77.0 / 100.0 | 16.4 / 77.0 / 200.0 | 2884.8, 352.2, 112.9, 16.4 |

### plain (comparison): the pinned filament profile four times

| Plan, face | Start loads | Changes | Tool order on the multicolor layers | Flush mm³ | Prime tower mm³ | Time s (header = statistics) |
|---|---|---|---|---|---|---|
| Roadie drop, up | T0 | 9 / 9 / 9 / 9 | L13 0123, L14 3120, L15 0123 | 300.0 | 1054.7 | 1827 = 1828 |
| Roadie drop, down | T2 | 10 / 10 / 9 / 10 | L1 2031, L2 1230, L3 0123, then → 0 on L4 | 500.0 | 592.4 | 1859 = 1859 |
| Roadie keep, up | T0 | 9 / 9 / 9 / 9 | L13 0123, L14 3120, L15 0123 | 300.0 | 1054.7 | 1957 = 1957 |
| Roadie keep, down | T3 | 10 / 10 / 9 / 10 | L1 3201, L2 1230, L3 0123, then → 0 on L4 | 500.0 | 592.4 | 1972 = 1972 |
| Oddie merge blues, up | T0 | 9 / 9 / 9 / 9 | L13 0123, L14 3120, L15 0123 | 300.0 | 1054.7 | 1869 = 1869 |
| Oddie merge blues, down | T0 | 10 / 10 / 9 / 10 | L1 0123, L2 3120, L3 0123, then → 0 on L4 | 400.0 | 592.4 | 1914 = 1915 |
| Oddie keep, up | T0 | 9 / 9 / 9 / 9 | L13 0123, L14 3120, L15 0123 | 300.0 | 1054.7 | 2103 = 2104 |
| Oddie keep, down | T1 | 10 / 10 / 9 / 10 | L1 1032, L2 2130, L3 0123, then → 0 on L4 | 500.0 | 592.4 | 2155 = 2156 |

| Plan, face | T0 (base) | T1 | T2 | T3 | Statistics `model` T0..T3 |
|---|---|---|---|---|---|
| Roadie drop, up | 1540.0 / 796.8 / 100.0 | 117.1 / 103.3 / 200.0 | 56.0 / 92.8 / 0.0 | 1.6 / 61.8 / 0.0 | 1592.3, 117.1, 56.0, 1.6 |
| Roadie drop, down | 1533.0 / 345.8 / 300.0 | 112.5 / 77.0 / 100.0 | 54.6 / 61.8 / 0.0 | 1.7 / 107.9 / 100.0 | 1533.0, 112.5, 106.9, 1.7 |
| Roadie keep, up | 1448.5 / 796.8 / 100.0 | 171.3 / 103.3 / 200.0 | 79.4 / 92.8 / 0.0 | 37.3 / 61.8 / 0.0 | 1500.8, 171.3, 79.4, 37.3 |
| Roadie keep, down | 1447.3 / 345.8 / 300.0 | 131.0 / 77.0 / 200.0 | 77.7 / 107.9 / 0.0 | 35.3 / 61.8 / 0.0 | 1447.3, 131.0, 77.7, 87.6 |
| Oddie merge blues, up | 2756.4 / 796.8 / 100.0 | 343.3 / 103.3 / 200.0 | 250.0 / 92.8 / 0.0 | 18.9 / 61.8 / 0.0 | 2808.7, 343.3, 250.0, 18.9 |
| Oddie merge blues, down | 2758.8 / 299.8 / 200.0 | 342.2 / 107.9 / 200.0 | 246.9 / 107.9 / 0.0 | 18.4 / 77.0 / 0.0 | 2811.1, 342.2, 246.9, 18.4 |
| Oddie keep, up | 2888.7 / 796.8 / 100.0 | 301.3 / 103.3 / 200.0 | 159.3 / 92.8 / 0.0 | 17.0 / 61.8 / 0.0 | 2941.0, 301.3, 159.3, 17.0 |
| Oddie keep, down | 2884.8 / 345.8 / 300.0 | 299.9 / 61.8 / 100.0 | 112.9 / 77.0 / 0.0 | 16.4 / 107.9 / 100.0 | 2884.8, 352.2, 112.9, 16.4 |

**Face up against face down (colours):**
- **Prime tower:** face down uses less, 548–592 mm³ against 1055 mm³. The tower is printed only up to the last layer with a change: face up on all 15 layers (24 `WIPE_TOWER_START`, 12 `CP EMPTY GRID` layers), face down only on layers 1–3 (12 `WIPE_TOWER_START`, no `CP EMPTY GRID`, 548.2 mm³), or 1–4 when the extra change falls on layer 4 (14 `WIPE_TOWER_START`, 592.4 mm³). The difference, 44.3 mm³, is exactly the layer-4 tower (per-layer tower volumes in `raw/analysis-*.json`).
- **Flush:** mostly the same; it differs by plan. Roadie drop 951 up against 1051 down; Roadie keep 951 against 924; Oddie merge blues 900 against 900; Oddie keep 600 against 800 mm³.
- **Time:** within ±80 s of face up.
- **Changes:** equal (9), except Roadie drop face down (10).

## The amended rules, checked on all 16 runs (`raw/rules-*.json`)

| Rule | colours | plain |
|---|---|---|
| Decision 2: the start block holds exactly one `T<n>` (n < 255, `T1000` aside) | 8 / 8 | 8 / 8 |
| … inside `M620 S<n>A` … `M621 S<n>A` for the same n | 8 / 8 | 8 / 8 |
| … and n is the first tool printing model features on layer 1 (also the first over all features, prime tower included) | 8 / 8 | 8 / 8 |
| 4(a): each layer's tool set = its body set | 8 / 8 | 8 / 8 |
| 4(b): each tool in one contiguous run per layer | 8 / 8 | 8 / 8 |
| 4(c): G-code real changes = Σ(colors − 1) + boundaries where the first tool ≠ the previous last (layer 1 against the start-loaded tool) | 8 / 8 | 8 / 8 |
| 4(d), information: real changes = the exact minimum | 7 / 8 (Roadie drop down: 10 against 9) | 4 / 8 (every face down: 10 against 9) |
| Statistics `filament_changes` = G-code real changes | 8 / 8 | 8 / 8 |

**Where the extra change comes from (face down):** the last color layer (L3) ends on an inlay tool, and L4 is base only, so one more change to T0 follows. This is consistent with OrcaSlicer ordering each layer by its flush matrix, starting from the previous layer's last tool, without looking at the next layer: an inference from the orders seen, not from its source. Face up, the color layers are the last layers, so the problem cannot arise.

**What the amended rules need from a reader:**
- **Change:** a `T<n>` with n < 255 between the first `; CHANGE_LAYER` and the end block.
  - In all 16 runs every one was inside `M620 S<n>A` … `M621 S<n>A`, and inside `; CP TOOLCHANGE START` … `END` under `; FEATURE: Prime tower`.
  - The start load and the end unload (`T255`, `M620 S255`) are not changes, and `T1000` is not a filament.
- **The previous tool for layer 1** is the start-loaded tool.
- **Order:** the sequence of tools printing model features within each layer.

## Markers (as written by this slicer and profile)

| What | Marker or command | Seen |
|---|---|---|
| Start-code load | `M620 M` (enable remap), then `M620 S<n>A` … `T<n>` … `M621 S<n>A`; `T1000` twice | 16 / 16 |
| Tool change | `; CP TOOLCHANGE START`, `; toolchange #k`, `; WIPE_TOWER_START`, the A1 change template (`M620 S<n>A`, `M620.11`, `M620.1`, `M620.10 A0`, `T<n>`, `M620.10 A1 … L<flush_length>`, `M628`/`M629`, flush, `M621 S<n>A`), `; CP_TOOLCHANGE_WIPE`, `; WIPE_TOWER_END`, `; CP TOOLCHANGE END` | every change |
| Flush | `; FLUSH_START` … `; FLUSH_END`, E-only moves. Their sum equals the `L` word of `M620.10 A1` in all 149 changes, to within 2e-4 mm (the moves' written rounding). There is no block when L = 0 | every change with L > 0 |
| Other E inside a change | 26.8 mm (no flush block) or 28.8 mm (with one), E-only: `G1 E18` after the firmware cut retraction (`M620.11 S1 … E-18`), `G1 E6` "Compensate for filament spillage", and unretracts. This is gross E, not net waste: the 18 mm refills a firmware retraction | every change |
| Prime tower | XY extrusion under `; FEATURE: Prime tower` (`WIPE_TOWER_START/END`, `CP EMPTY GRID START/END` on layers without a change), extruded within x 11.8–50.7, y 214.2–252.2 (`wipe_tower_x` 15, `wipe_tower_y` 217.415, width 35, brim 3) | face up every layer (24 `WIPE_TOWER_START`); face down only layers 1–3 or 1–4, up to the last change (12 or 14 `WIPE_TOWER_START`, no `CP EMPTY GRID`) |
| Time | `; model printing time: …; total estimated time: …` in the header | 16 / 16 |
| Filament used | `; filament used [mm] / [cm3] / [g] = a, b, c, d` at the end | 16 / 16 |

**Flush lengths seen:**
- 41.5752 mm (100.0 mm³);
- 52.2351 mm (125.6 mm³) and 51.4867 mm (123.8 mm³), colours runs only;
- 0 (no flush block). In the plain runs this was every white-to-white change (flush matrix entry 32). In the colours runs it occurred in 4 changes, all in Oddie keep into T2 (#0D100D): 0 → 2 three times face up (matrix entry 32) and 1 → 2 once face down (entry 38). Every change with an entry of 44 or more had a flush block. Why small entries give no flush was not explained (the source was not read).

The G-code's config has `flush_multiplier = 0.3` and the matrix. How OrcaSlicer turns a matrix entry into L was not read from its source. The flush is OrcaSlicer's; it is measured here, not tuned (plan, out of scope).

## Statistics against the G-code

- **`filament_changes`:** equals the G-code's real-change count in all 16 runs.
- **Per-filament `prime_tower` volume:** equals the G-code's Prime tower extrusion per tool in all 16 runs.
- **`model` volume per filament:** equals the G-code's model extrusion per tool, except for the start-loaded filament. That filament gets 52.296 mm³ more, which is exactly the statistics' `Custom` feature volume: the start code's purge and calibration lines. This holds in all 16 runs. It explains step 3's "statistics disagree" finding in part.
- **`flush`:** the total over filaments equals the G-code's flush-block total in all 16 runs. The split per filament does not match the G-code's tool during the flush in 14 of 16 runs; it matches in the two Oddie merge-blues colours runs. Which filament OrcaSlicer charges was not investigated.

## Note for the G-code reader of Task 5 (F3 and placement)

- **Arcs:** model moves include G2/G3 arcs (arc fitting is on).
- **The tool change:** it writes `G3 Z… I… J0 P1` (a helical lift with a P word) and `G4 S0`, under `; FEATURE: Prime tower`.
- **Prime tower extrusion:** it is not a model feature. `tdmg.printed.parse_gcode` refuses an extrusion in a feature outside `MODEL_FEATURES`, so it would refuse this G-code as it stands. This record used its own walker, with `tdmg.printed._arc` for the arcs.
- **Placement:** the model's box centre lands on the plate centre (within 0.01 mm, measured as the centre of the base's centreline extent), as R1's F3 assumes. The prime tower sits apart, within x 11.8–50.7, y 214.2–252.2.
- **Prime tower layers:** face up the tower is on every layer; face down it stops after the last layer with a change (layer 3 or 4). A reader must not expect it on every layer.

## Surprises

- **The face-down start filament is not the base** in 3 of 4 plans: T1, T2 and T3, in both variants. The A1 start template loads `T[initial_no_support_extruder]`, which is the first tool of layer 1.
- **The filament colors set the flush matrix and the order.** The CLI derives `flush_volumes_matrix` from `filament_colour`. The 3MF's colors do not reach it (step 3 found the same), so a run with the profile's default colors measures neither the plan's order nor its flush. With the plan's colors, flush is 1.60 to 3.17 times the plain runs' per run (600–1051 mm³ against 300–500 mm³). In the two runs compared, the colours G-code's CONFIG block differs from the plain one only in `extruder_colour`, `filament_colour` and `flush_volumes_matrix` (Roadie drop face up and Oddie keep face down, 725 keys each).
- **No look-ahead, as far as the orders show:** face down OrcaSlicer can leave the last color layer away from the base, which costs one more change than the exact minimum. This is inferred from the orders seen; the source was not read.
- **The turned inlay top** is 0.5999999 mm, not float32(0.6), because 3 − float32(2.4) is exact in float32.
- **Statistics `model` volume** includes the start code's purge for the start-loaded filament.

## Not tested

- Plans with fewer than 4 colors (none of the owner's), and so fewer filaments.
- `--arrange 0` (not needed).
- How OrcaSlicer computes the flush length from the matrix, and how it splits `flush` per filament in the statistics.
- Bambu Studio, the GUIs, and POSIX builds.
- Printing anything.
- The glue plates (Decision 5; Task 6).

## Files

- `measure_slicing.py`: builds the inputs (step 3's builders by import), slices, reads the G-code, checks the placement and the amended rules, and checks the derived profiles. It uses `tdmg.slicer` and `tdmg.printed` read-only.
- `raw/build.json`: per plan, the turn-over exactness record and, per face, the file hash, the bodies' bounds and volumes, `model_settings.config`, and the lib3mf read-back.
- `raw/orca-colours.json`, `raw/orca-plain.json`: per run:
  - the argument template;
  - the decoded exit code;
  - the output files;
  - the G-code's SHA-256;
  - the debug-log lines about vendor, arrange and colors.
- `raw/analysis-colours.json`, `raw/analysis-plain.json`: per run:
  - layers, start tools, changes and per-layer orders;
  - every tool-change block (from, to, flush E, L, other E, tower E);
  - flush and tower totals, and time;
  - per tool, the extrusion by feature and the extents;
  - the statistics;
  - the placement summary;
  - the exact minimum and the rule (c) count, both from the start-loaded tool, the per-layer prime-tower volumes, and, as labelled information, `info_start_loads_filament_1` (the plan's first Decision 2) and `info_minimum_changes_from_base`.
- `raw/rules-colours.json`, `raw/rules-plain.json`: the amended rules per run.
- `raw/profiles-colours.json`: the pinned filament profile's SHA-256 and each derived profile's SHA-256 and differing keys.
- No G-code is kept.

## Addendum, 2026-11-13: Task 5 cross-check (`crosscheck_task5.py`)

The production reader and checks (`src/tdmg/color_gcode.py`) were run on the eight colours G-codes of this record (kept in the Task 2 scratch folder, not in the repo), with the owner plans' bodies read as the gate reads them and face down from `tdmg.orca_input.turn_over`. Output: `raw/crosscheck-task5.txt` and `raw/crosscheck-task5.json`.

- **Gated checks:** `F6.color_changes`, `F6.tool_placement` and `F6.filaments_used` PASS on all 8.
- **Numbers against this record:** start load, change count, rule (c) count, exact minimum (from the start load), statistics `filament_changes`, per-layer orders, flush and prime-tower totals, total time, and per-tool model, prime-tower and flush volumes are equal to `raw/analysis-colours.json` and `raw/rules-colours.json` in all 8 (at the record's 3-decimal rounding).
- **Placement margin:** the largest distance of a tool's bead outside its own body is 0.0253 mm (Roadie keep, T1), against the 0.2 mm allowance.
- **F3 (information only until Task 7):** the silhouette's `F3.printed_connectivity` FAILs on all 8, always on the three multicolor layers: the union of every tool's beads splits into 4 to 64 parts. Neighbouring bodies' beads meet edge to edge at their shared outline, and the bead model leaves gaps between them of 0 to about 0.03 mm (Roadie drop face up, layer 13: 11 parts, the nearest two 0.025 and 0.026 mm from the largest). The silhouette's `F3.edge_coverage` FAILs on Roadie keep and Oddie keep face down (1.179 and 0.637 mm on layer 1) and is UNKNOWN on Roadie drop face down (0.251 against 0.275 mm). Per-tool F3 results are in the JSON.
- **Prime tower E:** written E over the model's bead formula has median 1.0204 (min 1.0185, max 1.0219) over 8,533 tower moves, about 1 / `filament_flow_ratio` (0.98). The reader does not check tower amounts.

### Revision after the controller's review (2026-11-13)

The controller's review of `354e9c1` changed three things the addendum above describes: every F3 result of `tdmg.color_gcode` (the silhouette's and each tool's) is now **required for PRINTABLE** until the owner's Task 7 review, not information; the prime tower's beads may not reach into the silhouette by more than the tools' allowance (in `F6.tool_placement`); and a turn ambiguity is judged on each check's own status. The line "F3 (information only until Task 7)" above is superseded by this. The cross-check was re-run with that code (`raw/crosscheck-task5.txt`, `.json`; `required_statuses`, `f3_values` and `verdict` per run).

- `F6.color_changes`, `F6.tool_placement` and `F6.filaments_used` still PASS on all 8; every number still equals this record. The prime tower prints nothing inside the silhouette in any run.
- **Verdict on all 8: NOT CERTIFIED**, from the required F3 checks below. Values: connectivity = layers mismatched of 15; coverage = largest model-edge gap (mm, at its z); allowance 0.275 mm on layer 1 (z 0.2), 0.2 mm above. Overprint PASSes everywhere (largest 0.025 mm), so it is left out.

| Run | Silhouette conn. / cov. | T0 conn. / cov. | T1 conn. / cov. | T2 conn. / cov. | T3 conn. / cov. |
|---|---|---|---|---|---|
| Roadie drop, up | FAIL 3 / PASS 0.231 | FAIL 2 / FAIL 0.284 | FAIL 3 / PASS 0.158 | PASS / PASS 0.135 | PASS / PASS 0.144 |
| Roadie drop, down | FAIL 3 / UNKNOWN 0.251 | FAIL 3 / FAIL 0.359 | FAIL 3 / PASS 0.230 | PASS / PASS 0.135 | PASS / PASS 0.144 |
| Roadie keep, up | FAIL 3 / PASS 0.231 | FAIL 3 / FAIL 1.588 | FAIL 3 / FAIL 4.994 | FAIL 2 / FAIL 0.234 | PASS / PASS 0.139 |
| Roadie keep, down | FAIL 3 / FAIL 1.179 | FAIL 3 / FAIL 2.204 | FAIL 3 / FAIL 7.591 | FAIL 3 / FAIL 0.247 | PASS / PASS 0.215 |
| Oddie merge blues, up | FAIL 3 / PASS 0.152 | PASS / FAIL 0.201 | PASS / PASS 0.122 | PASS / PASS 0.173 | FAIL 2 / PASS 0.111 |
| Oddie merge blues, down | FAIL 3 / PASS 0.244 | PASS / FAIL 0.290 | FAIL 1 / PASS 0.122 | PASS / FAIL 0.288 | PASS / PASS 0.110 |
| Oddie keep, up | FAIL 3 / PASS 0.221 | FAIL 2 / FAIL 0.227 | PASS / PASS 0.122 | FAIL 3 / FAIL 4.716 | PASS / PASS 0.111 |
| Oddie keep, down | FAIL 3 / FAIL 0.637 | FAIL 3 / FAIL 0.444 | PASS / PASS 0.122 | FAIL 3 / FAIL 10.333 | PASS / PASS 0.110 |

The large per-tool coverage gaps (4.7 to 10.3 mm) are on Roadie keep T1 (#451812, the kept outline band, as Placement above says) and Oddie keep T2. That they are bands narrower than a bead that the slicer leaves unprinted, as plan Decision 4 expected, is an inference for Oddie keep: where the gaps lie was not inspected.

**Placement fixed at 0° (controller decision, 2026-11-13, after the revision above).** `tdmg.color_gcode` no longer searches the quarter turns for multicolor slices. The silhouette, every tool and the prime tower are judged at the placement this record measured (Placement, above): the model's bounding-box centre on the plate centre (within 0.01 mm in all 16 runs), not turned. A search let a print with two inlays' colours swapped pass on a model that looks the same turned 180°; now that print, and a correct print turned by 90, 180 or 270°, FAILs `F6.tool_placement`. R1 (`tdmg.printed.f3_checks`) still searches the turns. The cross-check was re-run: `raw/crosscheck-task5.txt` is line for line the same as before apart from the run times (every run's chosen turn had been 0°), so the table above stands.

## Addendum, 2026-11-13: Codex review 5, findings 1 and 2

**Finding 1, firmware conditionals (M622 ... M623).** Measured with `measure_conditionals.py` on the four owner face-up G-codes of Task 7 (`artifacts/slice-runs/color2-<plan>/face-up/`) and the two R1 slice5c G-codes; output `raw/conditionals-review5.json`. Inside conditional blocks, at any depth:
- start code (all 6): G90 ×4, G91 ×2, M83 ×1, one E-only extrusion (`G1 E10`) and 6 extrusions with X/Y (the extrusion calibration lines, `G0 X128 E10` …), all in FEATURE Custom;
- time-lapse (SKIPPABLE) blocks (all 6): G92 ×30, G90 ×13, M83 ×13;
- CP TOOLCHANGE blocks (the 4 multicolor ones): G92 ×9;
- no T command, no M620/M621, no model or prime-tower extrusion, and nothing in the layers outside these blocks or in the end code.

So refusing every mode change inside a conditional would refuse every owner G-code. Each G90/M83 there sets the mode it already had before the block. The rule made instead (multicolor reading only; R1's reader is unchanged): a T command, an M620/M621, a FLUSH block, or a model or tower extrusion inside a conditional is refused (UNKNOWN); the blocks must pair; after M623, a mode that the block changed is unknown, and a move or extrusion that needs it is refused. A mode set inside to its value before stays known. This was flagged to the controller as a deviation from "refuse every mode change".

**Finding 2, flush position.** In the same G-codes the nozzle is at bed (267, 128) at every FLUSH_START (33 flushes in the four face-up G-codes; the template's `G1 X267` then `G1 Y128`), at Z 5.6 to 6.0, off the 256 mm plate. No flush block lies inside a conditional or moves in X, Y or Z. `F6.tool_placement` now FAILs when a flush's nozzle position is within the tool allowance of the silhouette, and is UNKNOWN when the position is unknown. `recheck_review5.py` (output `raw/recheck-review5.txt`) re-ran the color checks on the six Task 7 faces' G-codes: every status and value equals its `slice.json`, and the flushes are 109.1 to 109.5 mm from the model.

**Cross-check.** `crosscheck_task5.py` re-run on the eight Task 2 G-codes (it now lists every F3 check; `f3_required_ids` changed with the owner's Task 7 decision): `raw/crosscheck-task5.txt` is line for line the same apart from the run times and the verdict column, which now follows the Task 7 required set (PRINTABLE 5, NOT CERTIFIED 3: Roadie drop, Roadie keep and Oddie keep face down, by the silhouette's F3.edge_coverage: UNKNOWN, FAIL, FAIL). R1: the two slice5c G-codes give the same F3 statuses and measurements as their `slice.json`.

**Flush rule revised (2026-11-13, after the review of `07b445a`).** A flush 0.3 mm beside the model passed the first rule (the nozzle further from the silhouette than the tool allowance), though a 27.8 mm purge there lands on the model. The rule is now the one the measurement supports, with no new number: each FLUSH_START's head X/Y must be known and off the printable plate (the reader's plate bounds, edge included); on the plate `F6.tool_placement` FAILs, and an unknown position is UNKNOWN. `recheck_review5.py` re-run on the six Task 7 faces: every status and value equals its `slice.json`, and none of the 52 flushes is on the plate (`raw/recheck-review5.txt`).

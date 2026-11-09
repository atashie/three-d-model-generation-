# Repository and documentation plan

**Status:** Draft for review, 2026-11-08. Open questions are in section 12. Where a question blocks a choice, the plan states a default and labels it **(default, pending Qn)**.

**Inputs:** the landscape report in `reports/` and its seven research notes in `research_notes/`. Also the local stack checks in `research/verification/2026-11-08-stack-smoke/`.

---

## 1. Goal

A user gives an image, as a file or a URL. The program returns a file that an FDM printer can print: a 3MF, or an STL when that is enough. The program also returns a report that says why the file should print, which checks it passed, and which assumptions it made.

**In scope:** FDM printers with a 0.4 mm nozzle as the reference. Single-color, multi-material (AMS/MMU), layer-swap color, and multi-part assembly. Flat, relief, complex 3D, flat articulated, and 3D articulated geometry.

**Out of scope for now:** resin printing, G-code generation (the slicer owns that), and selling models.

## 2. Principles

1. **The runtime pipeline does not call an LLM.** LLMs help us write and review code and docs during development. A run of the tool is code from input to output. An optional LLM-assisted mode may come later. It must sit behind an explicit flag and pass the same deterministic checks.
2. **Nondeterminism is limited to two fenced stages.** These are ML perception (masks, depth) and generative image-to-3D. Each records its model ID, weights hash, seed, and parameters. Its output is cached by input hash and saved as an artifact, so every later stage can be replayed byte for byte.
3. **Every number has a source.** Design rules (clearances, wall minimums, overhang limits) live in a machine-readable rules registry. Each rule has citations and an evidence tier. Code reads values from the registry. A reviewer rejects unexplained constants.
4. **Check everything twice.** Where two independent libraries can answer the same question, use both. Examples: trimesh, manifold3d, and lib3mf for manifoldness, and two volume computations. If they disagree, the check fails.
5. **The user's printer is the final judge.** A rule stays "provisional" until a calibration print on the user's own machine confirms it. Then it becomes "calibrated".
6. **3MF is the primary output.** 3MF carries units, multiple bodies, colors, and metadata. STL is a convenience export for single-body, single-color parts.
7. **Same inputs give the same bytes.** Output files are reproducible. The smoke test showed that this is possible for STL and 3MF. For 3MF it needs explicit UUIDs.

## 3. Print-type taxonomy: the nested subsystems

A print job is one **geometry class** plus one **color/assembly strategy**. Each class and each strategy has its own docs page, rules, checks, and code module. Doc pages compose: a multi-color flat flexi uses the flat-flexi page and the per-body multi-material page.

### Geometry classes

| ID | Class | Examples | Source of geometry | Deterministic? |
|---|---|---|---|---|
| G1 | Flat / 2.5D extrusion | keychain, sign, coaster, cookie cutter, badge | mask → vector → extrude | Yes, after the mask |
| G2 | Relief / heightfield | lithophane, bas-relief, layer-color image | grayscale or depth → height grid | Yes, after depth (lithophane needs no ML) |
| G3 | Complex 3D solid | figurine, bust, toy | generative image-to-3D, then repair | No (fenced), then yes |
| G4 | Flat flexi | articulated flat animal, flexi keychain | G1 + link segmentation + hinge library | Yes, after the mask |
| G5 | 3D flexi | print-in-place articulated dragon | G3 + segmentation + joint synthesis | Research track |

### Color and assembly strategies

| ID | Strategy | How color or parts are encoded | Notes |
|---|---|---|---|
| C1 | Single color | One body | Baseline |
| C2 | Multi-material, per body | One body per color; each body is assigned to an extruder slot in the 3MF | Most portable multi-color encoding |
| C3 | Multi-material, painted | Per-triangle paint attribute (`paint_color` in Bambu/Orca, `mmu_segmentation` in PrusaSlicer) | Needed when color regions do not follow bodies (G3). No open-source Python writer exists, so we would build one |
| C4 | Layer-swap color | Filament changes at set Z heights (pause / M600) | Only for G1 and G2. HueForge-style |
| C5 | Multi-plate assembly | Separate single-color parts with connectors, arranged on plates | Cut planes, pins, dowels, clearances |

### Compatibility matrix

Legend: ✅ supported target · ⚠️ possible, with caveats · ❌ contradictory or not useful

|    | C1 | C2 | C3 | C4 | C5 |
|---|---|---|---|---|---|
| G1 | ✅ | ✅ | ⚠️ needless; C2 is simpler | ✅ | ⚠️ only for large signs |
| G2 | ✅ | ⚠️ | ⚠️ | ✅ (HueForge-style) | ⚠️ tiled panels |
| G3 | ✅ | ⚠️ needs part-aware generation | ✅ | ❌ | ✅ |
| G4 | ✅ | ✅ (color per link) | ⚠️ | ⚠️ | ❌ print-in-place |
| G5 | ✅ | ⚠️ | ✅ | ❌ | ❌ print-in-place |

The matrix will live in `docs/print-types/README.md`. The CLI will refuse ❌ combinations with an explanation.

## 4. Pipeline stages

Each stage is a function with typed inputs and outputs. Each writes an artifact and a JSON report. A run makes a **build manifest** with input hashes, parameters, tool and model versions, and output hashes.

| Stage | Purpose | Deterministic | Main tools (verified on M5 unless noted) |
|---|---|---|---|
| S0 Intake | Load the image, fix EXIF orientation, hash it, read the job spec (print type, target size in mm, printer profile, filament list) | Yes | Pillow, pydantic |
| S1 Perception | Foreground mask, optional depth map | **No** (fenced: pinned and cached) | rembg (CPU), Apple Vision via pyobjc, SAM 3 MLX port, Depth Anything V2 Small. Not yet run on M5 |
| S2 Geometry | Build the base shape for the geometry class | Yes for G1, G2, G4. **No** for G3 (fenced) | OpenCV, vtracer/potrace, Shapely, trimesh, build123d, manifold3d. Generative backends for G3 |
| S3 Features | Add base plates, loops, text, hinges, connectors, cut planes | Yes | build123d, manifold3d. BOSL2 via OpenSCAD is optional |
| S4 Validation gate | Run the checks for this print type, with thresholds from the rules registry and printer profile | Yes | trimesh, manifold3d, lib3mf. PyMeshLab optional (license, Q2) |
| S5 Repair | Only when S4 fails: run deterministic repair recipes, measure the deviation, then run S4 again | Yes | manifold3d, trimesh, voxel remesh. Deviation measured with Hausdorff distance |
| S6 Packaging | Write STL, plain 3MF, or a slicer project 3MF with extruder and plate assignments | Yes | lib3mf, our own Bambu/Orca/Prusa writers, orca123d for reference |
| S7 Slicer check | Optional. Slice headless, parse warnings, print time, and filament use | Yes | OrcaSlicer CLI, PrusaSlicer CLI. Not installed yet |
| S8 Manifest | Write `manifest.json` and a human-readable report | Yes | — |

## 5. Repository layout

```text
three-d-model-generation/
├── README.md                  # what it is, quickstart, status
├── CLAUDE.md                  # rules for AI coding sessions (principles, how to add a rule, test commands)
├── pyproject.toml             # uv project, Python 3.13, core deps + optional extras
├── uv.lock
├── docs/                      # see section 6
├── rules/                     # machine-readable design rules with citations (section 7)
│   ├── schema.json
│   ├── global.yaml
│   ├── geometry/{flat,relief,complex3d,flexi_flat,flexi_3d}.yaml
│   └── color/{single,multi_body,painted,layer_swap,multi_plate}.yaml
├── profiles/                  # user-editable hardware facts
│   ├── printers/<name>.yaml   # nozzle, bed, slots, calibrated clearances
│   └── filaments/<name>.yaml  # color hex, material, transmission distance
├── src/<package>/
│   ├── cli.py                 # `<cmd> make`, `<cmd> check`, `<cmd> calibrate`
│   ├── spec.py                # job spec models (pydantic)
│   ├── rules.py               # registry loader; resolves rule + profile overrides
│   ├── manifest.py
│   ├── intake/
│   ├── perception/            # fenced ML: mask, depth (pinned, cached)
│   ├── vectorize/             # contours, tracing, polygon cleanup, px→mm
│   ├── geometry/              # extrude, heightfield, booleans, cuts
│   ├── features/              # loops, bases, text, hinges, connectors
│   ├── recipes/               # one module per geometry class; each declares its stages and checks
│   ├── color/                 # one module per strategy (palette matching, region split, paint encoder)
│   ├── generative/            # fenced backends for G3 (hosted APIs, local shape-only)
│   ├── validate/              # check registry; every check has an ID, a rule link, and a doc
│   ├── repair/
│   ├── export/                # stl, 3mf, bambu/orca project, prusa project
│   └── slicer/                # headless slicer wrappers and output parsers
├── calibration/               # generators for test prints (clearance ladders, hinge tests)
├── tests/
│   ├── fixtures/              # small golden images and meshes
│   ├── unit/                  # analytic checks (areas, volumes, genus)
│   ├── property/              # hypothesis: random valid polygons → always-valid solids
│   ├── corpus/                # Thingi10K subsets with known defect labels
│   ├── golden/                # byte-hash tests for deterministic outputs
│   └── integration/           # slicer CLI, backend adapters (opt-in markers)
├── examples/                  # sample images and job specs
├── research/                  # dated, append-only evidence
│   └── verification/          # local experiments like the 2026-11-08 smoke test
├── research_notes/, reports/  # landscape research (move under research/ in Phase 0)
└── .github/workflows/         # CI: macOS arm64 + Linux
```

## 6. Documentation system

Five layers. Each layer has one job.

| Layer | Path | Job | Who writes it |
|---|---|---|---|
| 1. Guide | `docs/guide/` | Teach a newcomer the concepts. Choose a print type. Explain the pipeline | Hand-written |
| 2. Print-type pages | `docs/print-types/{geometry,color}/` | One page per class or strategy, all on one template | Hand-written; tables are generated |
| 3. Reference | `docs/reference/` | Design rules, checks, file formats, slicers, dependencies and licenses | **Generated** from `rules/`, the check registry, and the dependency register |
| 4. Decisions | `docs/decisions/` | Architecture decision records (ADRs): why we chose X over Y | Hand-written, one per decision |
| 5. Research | `research/` | Dated landscape notes and local verification logs. Never edited after the fact; superseded by new dated entries | Research runs and experiments |

### Guide pages (layer 1)

- `00-start-here.md`: what a mesh is, what "watertight" and "manifold" mean, STL vs 3MF, what a slicer does. Written for a data scientist who is new to 3D.
- `glossary.md`
- `choosing-a-print-type.md`: a decision tree from "what is in the image and what do I want" to a geometry class and a strategy.
- `pipeline.md`: the stage contract from section 4.
- `principles.md`: section 2, with examples.

### Print-type page template (layer 2)

Every page in `docs/print-types/` uses the same headings, so pages can be compared and linted:

1. **What it is**: one paragraph and an example photo or render.
2. **When to use / when not to**
3. **Pipeline**: which stages run and what is special in each.
4. **Parameters**: a generated table of rule IDs with default, range, unit, and status.
5. **Failure modes**: a table of symptom, cause, automated check ID, and mitigation.
6. **Required checks**: check IDs that must pass for this type.
7. **Calibration needed**: which test prints promote these rules to "calibrated".
8. **Evidence**: links to research notes, with tiers.
9. **Open gaps**: what we do not know yet.

### Keeping docs and code in sync

- `scripts/gen_docs.py` renders the rule tables, the check catalogue, and the dependency register into Markdown. CI fails if the generated files are stale.
- A lint test checks these links:
  - every check ID named in a doc exists in code;
  - every check in code has a doc entry;
  - every rule has at least one source;
  - every print-type page has all template headings.

## 7. Rules registry and evidence policy

### Rule format (illustrative)

```yaml
- id: clearance.print_in_place.per_side
  summary: Gap between moving surfaces of a print-in-place joint, measured per side.
  applies_to: [G4, G5, C5]
  unit: mm
  default: 0.3
  range: [0.2, 0.5]
  scales_with_model: false        # clearance stays absolute when the model is scaled
  depends_on: [nozzle_diameter, layer_height, material, joint_axis]
  status: provisional             # provisional | cited | calibrated
  sources:
    - ref: research_notes/.../articulated_flexi_print_design.md#1
      tier: primary
      claim: "Prusa KB: at least 0.3 mm for movable parts"
    - ref: research_notes/.../articulated_flexi_print_design.md#1
      tier: primary
      claim: "DrLex Flexi Rex drawing: about 0.5 mm"
  calibrated_by: calibration/clearance_ladder   # test print that promotes it
```

### Evidence tiers

| Tier | Meaning | Allowed use |
|---|---|---|
| unverified | Single forum post, search snippet, or our own guess | Can be a default only when no better source exists. The run report flags it |
| secondary | Reputable secondary source, vendor blog, or designer page | Default value |
| primary | Spec, source code, official docs, or peer-reviewed paper | Default value |
| calibrated | Confirmed by a test print on the user's printer, stored in the printer profile | Overrides all others for that printer |

When sources disagree, the rule stores the range and who says what. The default is picked inside the range, and the ADR or notes say why.

## 8. Verification strategy

1. **Analytic unit tests.** Known shapes with known area, volume, and genus. The smoke test already does this for an extruded ring and a build123d tag.
2. **Cross-library oracles.** For example, trimesh watertightness, manifold3d status, and lib3mf `IsManifoldAndOriented` must agree.
3. **Property-based tests** with hypothesis. For any valid polygon and height, the extrusion is watertight and its volume equals area × height within tolerance.
4. **Corpus tests.** Thingi10K has labels for non-manifold, self-intersecting, and open meshes. Our checks must flag the same meshes.
5. **Golden-hash tests.** Deterministic outputs must keep the same SHA-256 across runs and machines. A hash changes only through an intentional, reviewed update.
6. **Slicer integration tests** (opt-in). Headless OrcaSlicer or PrusaSlicer must open and slice the output with exit code 0. Parse the warnings.
7. **Physical calibration loop.** The tool generates test prints. The user records results in the printer profile, which promotes rules to "calibrated".
8. **Repair deviation budget.** Every repair reports the Hausdorff distance between input and output. Above a threshold, the run fails rather than silently changing the shape.

Two smoke-test findings are already candidates for tests:
- `cv2.findContours` shrinks shapes by half a pixel. Test the correction against pixel-count ground truth.
- lib3mf UUIDs must be set explicitly for byte-identical 3MF files.

## 9. Environment and dependencies

- **Python 3.13** with `uv`. This is the only version where every candidate wheel resolves on Apple Silicon (verified 2026-11-08).
- **Core dependencies** (all permissive licenses): numpy, scipy, trimesh, networkx, lxml, manifold3d, lib3mf, shapely, opencv-python-headless, build123d (with cadquery-ocp), vtracer, pillow, pydantic, typer, pyyaml.
- **Optional extras:**
  - `perception`: rembg, onnxruntime, pyobjc-framework-Vision.
  - `depth`: Depth Anything V2 Small (Apache-2.0; the larger variants are non-commercial).
  - `analysis`: PyMeshLab (GPL), **(default, pending Q2)**.
  - `generative`: HTTP clients for hosted backends, **(pending Q3)**.
  - `blender`: bpy 5.2.3.
- **External tools**, outside Python:
  - OrcaSlicer, via Homebrew cask. It has a working cross-platform CLI repair, rich exit codes, and JSON statistics.
  - PrusaSlicer as a second opinion.
  - OpenSCAD 2026.11 when it is stable, for the BOSL2 hinge and joiner library. Optional.
- **Separate environments:** anything that needs a different Python stays in its own environment and is called as a subprocess. This includes text-to-cad (3.14) and local image-to-3D ports (MLX/MPS).
- **License policy (default, pending Q2):** the repo is MIT. Core dependencies are MIT, BSD, or Apache. GPL, AGPL, and non-commercial tools are allowed only as optional extras or subprocess tools, and each is listed in the dependency register with its restriction. Examples: PyMeshLab, Tweaker-3, MeshFix, MeshLib, AutoForge, PartPacker, and Hunyuan3D, which excludes EU/UK/KR users.

## 10. Position on earthtojake/text-to-cad

**Recommendation:** use it as inspiration and an optional interop target, not as a core dependency. See the landscape report for the full assessment.

- **It solves a different problem.** An LLM agent writes build123d code for mechanical parts from text. Our runtime is image-driven and LLM-free.
- **It conflicts with our stack.** It requires Python 3.14, and our core needs 3.13 for onnxruntime and bpy. It ships releases several times a day, so its API is not stable to build on.
- **It is worth learning from.** It uses the same kernel stack we chose (build123d and OpenCASCADE). It has a printing DFM check, a catalogue of OpenCASCADE failure modes, and an STL non-manifold bug that was fixed (issue #433). The MIT license lets us adapt its code with attribution.

## 11. Roadmap

Each phase has an exit test. The order after Phase 1 depends on Q4.

| Phase | Deliverable | Exit test |
|---|---|---|
| 0. Foundations | Scaffold, pyproject (3.13), docs skeleton with templates, rules schema + lint, dependency register, CLAUDE.md, CI on macOS arm64 + Linux, research moved under `research/` | `uv run pytest` green in CI; docs generator runs |
| 1. Check and export | `<cmd> check model.stl|3mf` gives a JSON + text report. Deterministic STL/3MF writers. Thingi10K corpus tests. OrcaSlicer CLI wrapper | Our checks agree with Thingi10K labels on a fixed sample; golden hashes stable |
| 2. First recipe: G1 × C1 | Image → flat keychain or sign, single color. Clearance-ladder calibration print | User prints both; results recorded in the printer profile |
| 3. G1 × C2 | Palette matching to the user's filaments, per-color bodies, Bambu/Orca project 3MF with extruder assignment | Opens in the slicer with the colors already assigned |
| 4. G2 + C4 | Lithophane and depth relief; layer-swap color plan | Printed lithophane matches the preview; swap heights correct |
| 5. G3 × C1 | Generative backend adapters, scale imposition, repair recipes, auto-orient, base | Gate passes on N sample images; repair deviation within budget |
| 6. C5 | Plane cuts, connectors with calibrated clearance, plate arrangement | Parts print and assemble without sanding |
| 7. G4 | Flat flexi: link segmentation, hinge geometry (DrLex-style spec), clearance from profile | Printed flexi moves freely after break-in |
| 8. C3 | Paint-attribute encoder for Bambu/Orca/Prusa (no open-source Python writer exists yet) | Painted G3 model opens with correct colors in two slicers |
| 9. G5 | 3D flexi research track: joint placement from rig predictions, ball-and-socket synthesis | Experimental; success criteria set at the start of the phase |

## 12. Open questions

These change concrete choices above. The defaults apply until answered.

- **Q1. Printer hardware.** Which printer, nozzle, and multi-material unit (if any)? This sets the slicer to target, the project 3MF flavor, the bed size, and the first printer profile. *Default:* Bambu Lab with AMS, 0.4 mm nozzle, OrcaSlicer CLI as the headless checker.
- **Q2. License and use.** Personal use, public open source, or selling prints or models? This decides whether GPL and non-commercial tools can be core dependencies. Also: are you in the EU, UK, or South Korea? Hunyuan3D's license excludes those regions. *Default:* MIT repo with permissive core dependencies (section 9).
- **Q3. Compute and spending for complex 3D (G3).** Local only, hosted open models (fal or Replicate, cents per run), or commercial APIs (Meshy or Tripo, which add printability analysis and repair)? *Default:* hosted open models first, a local shape-only option second, commercial APIs as optional adapters.
- **Q4. First targets.** Which print types matter most to you first? *Default:* G1 × C1 first, because it exercises the whole pipeline deterministically. Then G1 × C2, then G3.
- **Q5. Interface.** Is a CLI plus a Python library enough at first, with a simple local web UI later? *Default:* yes.

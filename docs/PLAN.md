# Repository and documentation plan

**Status:** Draft v2, 2026-11-09. v1 (2026-11-08) was revised after an independent review by OpenAI Codex. Section 12 lists what changed and why. Open questions are in section 13. Where a question blocks a choice, the plan states a default and labels it **(default, pending Qn)**.

**Inputs:**
- The landscape report in `reports/`, including its erratum, and the seven research notes in `research_notes/`.
- The local stack checks in `research/verification/2026-11-08-stack-smoke/`.
- The review records in `research/reviews/2026-11-09-codex/`.

---

## 1. Goal

A user gives an image, as a file or a URL. The program returns a file that an FDM printer can print: a 3MF, or an STL when that is enough. It also returns a report that gives a verdict for each check, the evidence behind each threshold, and every assumption it made.

The program says **PRINTABLE** only when every check required for that kind of print passed. Otherwise it says **NOT CERTIFIED** and lists the checks that failed or could not be measured. It never guesses.

**In scope:** FDM printers with a 0.4 mm nozzle as the reference.

**Out of scope for now:** resin printing, G-code generation (the slicer owns that), and selling models.

## 2. Principles

1. **The runtime pipeline does not call an LLM.** LLMs help write and review code and docs during development. An optional LLM-assisted mode may come later. It must sit behind an explicit flag and pass the same gate. Following the research, an LLM may *propose* parameters; code *decides*.
2. **Nondeterminism is fenced and replayable.** ML perception and generative image-to-3D are not deterministic. Each such stage records whatever identity is available: model ID, version, weights hash, seed, and parameters. For hosted models, some of these may be unavailable, and the record says so. Every stage output is saved as an artifact. Cache keys use the full stage configuration plus the hashes of upstream artifacts, not just the input image. Replays reuse saved artifacts instead of calling the model again.
3. **Reproducibility has a stated envelope.** Within one pinned environment, the same inputs give byte-identical outputs. A pinned environment means the same lock file, platform, and slicer build and profile. Across platforms, we promise geometric equivalence within stated tolerances, not identical bytes. Hidden choices must be made explicit. Examples are trimesh's triangulation engine, OpenCASCADE tessellation tolerances, 3MF UUIDs, and zip metadata.
4. **Every number has a source and a status.** Design rules live in a rules registry. Each rule records where it comes from, what kind of rule it is, and how far it has been validated (section 7). Code reads values from the registry. A reviewer rejects unexplained constants.
5. **Checks are precise.** Each check states its exact predicate and method. Cross-library comparisons are made only between equivalent predicates.
6. **The user's printer is the final judge of empirical rules.** Calibration prints can override empirical rules for one printer and process. They never override format rules, such as the 3MF manifold requirements.
7. **3MF is the primary output.** STL is a convenience export for single-body, single-color parts. STL has no units, so checking an STL requires a stated unit assumption.

## 3. Print-type model: the nested subsystems

### Four attributes

A print job is a combination of four attributes. Each attribute value has its own docs page with its rules, checks, and failure modes. These pages are the "subsystems". A **recipe** is a named combination that we actually implement. Each recipe has a page that composes the attribute pages and adds its own checks.

| Attribute | Values |
|---|---|
| **Geometry source** | **G1** Flat / 2.5D extrusion (mask → vector → extrude) · **G2** Relief / heightfield (grayscale or depth → height grid) · **G3** Full 3D (generative image-to-3D, then repair) |
| **Articulation** | **A0** None · **A1** Flat print-in-place joints (in-plane pin-in-loop hinges) · **A2** 3D print-in-place joints (ball-and-socket, cone-pin) |
| **Color encoding** | **C1** Single filament · **C2** One body per filament, assigned in the 3MF · **C3** Per-triangle paint (`paint_color` in Bambu/Orca, `mmu_segmentation` in PrusaSlicer) · **C4** Filament changes by layer (color varies only with height) |
| **Assembly / layout** | **L1** One print, one plate · **L2** Separately printed parts, assembled after printing, possibly across several plates |

Your original categories map onto these attributes:

- **Complex 3D shape** = G3 · A0.
- **Flat flexi** = G1 · A1.
- **Fully 3D flexi** = G3 · A2.
- **Single color** = C1.
- **Multicolor** = C2, C3, or C4.
- **Single colors printed on several plates and combined** = C1 for each part · L2.

C1 allows several bodies. A single-color articulated chain is many bodies.

### Constraints between attributes

Almost every combination is physically possible. The real constraints sit inside recipes:

- C4 color can change only between layers.
- L2 cut planes must not pass through A1/A2 joints.
- C3 paint must be applied to the *final* mesh, after any repair or remeshing, because remeshing destroys triangle identity.
- A1 is defined as in-plane, so it implies G1.

### Planned recipes

The compatibility table in `docs/print-types/README.md` shows each combination as ✅ implemented, 🚧 planned, or ⏳ not planned yet. It is generated from the recipe declarations in code, the same source the CLI uses, so the docs and the CLI cannot disagree.

| Recipe | Attributes | Example |
|---|---|---|
| R1 Flat single-color | G1 · A0 · C1 · L1 | keychain, sign, cookie cutter |
| R2 Flat multicolor | G1 · A0 · C2 · L1 | two-color logo coaster |
| R3 Relief and lithophane | G2 · A0 · C1 (C4 later) | lithophane, bas-relief |
| R4 Figurine, single color | G3 · A0 · C1 · L1 | figure from a photo |
| R5 Assembled parts | G3 · A0 · C1 · L2 | figure too large for the bed, or one color per part |
| R6 Flat flexi | G1 · A1 · C1 or C2 · L1 | articulated flat animal |
| R7 Painted figurine | G3 · A0 · C3 · L1 | multicolor figure on AMS |
| R8 3D flexi | G3 · A2 · C1 · L1 | print-in-place articulated dragon (research track) |

## 4. Pipeline stages and the gate contract

### Stages

Each stage is a function with typed inputs and outputs. Each writes an artifact and a JSON report.

| Stage | Purpose | Deterministic |
|---|---|---|
| S0 Intake | Load the image, fix EXIF orientation, hash it, and read the job spec: attributes, target size in mm, printer profile, filament list | Yes |
| S1 Perception | Foreground mask, optional depth map. Fenced: pinned and cached | **No** |
| S2 Base geometry | Build the shape for the geometry source. G3 is fenced | Yes for G1/G2. **No** for G3 |
| S3 Normalize | Apply one explicit image-to-model transform: origin, pixel centers vs pixel edges, scale, Y flip. Then set units, scale to the target size, orient, and decimate to the triangle budget | Yes |
| S4 Entry gate and repair | Make the geometry valid *before* booleans; manifold3d rejects non-manifold input. Run the repair ladder from least to most destructive, measuring what each step changed | Yes |
| S5 Features | Add bases, loops, text, joints, connectors, and cut planes. This runs *after* scaling, so absolute clearances stay absolute | Yes |
| S6 Color | Recipe-specific. C2: reduce the palette, snap it to the loaded filaments, and build regions as bodies. C3: transfer color onto the final mesh, then encode paint. C4: layer schedule from an optical calibration of the filaments | Yes |
| S7 Package | Write STL, plain 3MF, or a slicer project 3MF. Assemblies are one components object, so slicers cannot pull parts apart. UUIDs come from a defined identity scheme | Yes |
| S8 Final gate | Read the *written file* back and run every check the recipe requires | Yes |
| S9 Slicer check | Slice headless with a pinned slicer build and profile. Verify the sliced output | Yes, within the pinned envelope |
| S10 Manifest | Write `manifest.json` and a readable report: verdicts, evidence, assumptions, and every artifact hash | Yes |

### Gate contract

Each check returns **PASS**, **FAIL**, or **UNKNOWN**, with the measured value, the threshold, and the rule ID. A check that cannot be measured returns UNKNOWN; it never silently passes. Each recipe declares its required checks in code. The overall verdict is PRINTABLE only if every required check passes.

| Family | Checks (method fixed per check) |
|---|---|
| F1 Format and topology | Finite coordinates. No degenerate or duplicate faces. Every edge shared by exactly two faces. No pinched vertices. Closed. Consistent outward orientation. Positive volume (the 3MF core MUST rules). Self-intersection: a warning that triggers a rebuild |
| F2 Scale and fit | Units explicit. Target dimensions met. Fits the build volume, per plate. Coordinates within float32-safe bounds; lib3mf and manifold3d store float32 |
| F3 Printability geometry | Wall thickness: one fixed method per threshold. FAIL on any localized region thinner than the minimum, and report where it is and how much of the surface was sampled. A low percentile is reported as a summary only, because a thin connector can be under 5% of the samples. Minimum feature size. Overhang area and an estimate of support need. Supports trapped inside joints or cavities. Bed contact and stability (center of mass over the footprint). Thin necks along Z |
| F4 Structure-specific | Joint clearances, measured separately as radial, vertical, and first layer. Body count as expected. Connector fit. Minimum color-region size. Filaments per layer under the printer's cap |
| F5 Resources | Triangle count under budget (OrcaSlicer refuses plates over 1,000,000 by default). File size |
| F6 Sliced output | Exit status decoded correctly (on macOS and Linux a parent process sees only the low 8 bits, so Orca's −50 arrives as 206). G-code not empty. Expected objects and filaments present. Statistics parsed |

When no slicer is installed, F6 is UNKNOWN, so the verdict cannot be PRINTABLE.

### Repair must preserve function

A repair is accepted only if all of these hold:

- Two-sided surface deviation stays within budget, with the sampling method and its limits stated. PyMeshLab's Hausdorff filter measures one direction per call and can ignore points past `maxdist`.
- Volume, area, genus, and component count change only within budget.
- Clearance and connector checks still pass. A small change can close a hinge gap while staying under any distance threshold.

Repair attempts are bounded. A repair that cannot meet these conditions makes the run fail, not pass quietly.

### Resource budgets

Each budget is a rule in the registry:

- maximum input pixels;
- triangle budget;
- a memory estimate before any voxel or grid operation (a dense float32 grid needs n³ × 4 bytes, so a 300 mm cube at 0.1 mm pitch needs 108 GB);
- timeouts.

A 1024 × 1024 heightfield alone has about 2.1 million top-surface triangles. So decimation, with protected boundaries and measured error, is part of S3. Volumetric remeshing uses sparse or chunked grids, such as OpenVDB from conda-forge.

## 5. Repository layout

```text
three-d-model-generation/
├── README.md                  # what it is, quickstart, status
├── CLAUDE.md                  # rules for AI coding sessions (principles, how to add a rule, test commands)
├── pyproject.toml, uv.lock    # Python 3.13, core deps + optional extras
├── docs/                      # section 6
├── rules/                     # rules registry (section 7)
├── profiles/
│   ├── printers/<name>.yaml   # bed, nozzle, filament slots, max filaments per layer, calibration results
│   └── filaments/<name>.yaml  # color, material, transmission distance
├── src/<package>/
│   ├── cli.py                 # make, check, calibrate
│   ├── spec.py                # job spec (pydantic)
│   ├── recipes/               # one module per recipe; declares stages, required checks, rules
│   ├── attributes/            # geometry, articulation, color, assembly helpers
│   ├── intake/, perception/, vectorize/, geometry/, features/, color/
│   ├── generative/            # fenced G3 backends (hosted, local shape-only)
│   ├── checks/                # check registry: ID, exact predicate, method, rule links
│   ├── repair/
│   ├── export/                # stl, 3mf, bambu/orca project, prusa project
│   ├── slicer/                # headless wrappers, exit-status decoding, output parsing
│   └── manifest.py
├── calibration/               # test-print generators (clearance ladders: radial, vertical, first layer)
├── tests/
│   ├── fixtures/              # analytic positive and negative meshes, named test images
│   ├── unit/, property/, golden/, corpus/, integration/
├── examples/
├── research_notes/, reports/  # landscape research, kept in place so links stay stable
├── research/
│   ├── verification/          # local experiments
│   └── reviews/               # independent review records
└── .github/workflows/         # CI on macOS arm64 and Linux
```

## 6. Documentation system

**Start lean and grow with the code.** v1 proposed five doc layers before the first print. That front-loads upkeep. Phase 0 creates only:

- `docs/guide/00-start-here.md`: what a mesh is, what "watertight" and "manifold" mean, STL vs 3MF, what a slicer does. Written for a data scientist who is new to 3D.
- `docs/guide/glossary.md`
- `docs/guide/principles.md` (section 2) and `docs/guide/pipeline-and-gate.md` (section 4)
- `docs/print-types/README.md`: the attribute model and the generated recipe status table.
- The pages that R1 needs: `attributes/geometry-flat.md`, `attributes/color-single.md`, `attributes/assembly-single.md`, and `recipes/r1-flat-single.md`.
- `docs/reference/dependencies.md`, the dependency and licence register.

Later layers arrive with the recipes that need them. Those include more attribute and recipe pages, generated rule and check references, and decision records in `docs/decisions/`.

**One source of truth.** Recipe declarations in code list their required checks and rules. `scripts/gen_docs.py` renders, from those declarations and the rules registry:

- the tables on each recipe page (parameters, required checks);
- the recipe status table.

CI fails if the generated files are stale. Hand-written text explains; generated tables state facts.

**Lint checks for agreement, not just presence:**
- every check a recipe requires exists and is documented;
- every rule a recipe uses exists;
- every citation path resolves and its `locator` text appears in the cited file.

**Page template.** Attribute and recipe pages share these headings:
1. What it is
2. When to use / when not to
3. Pipeline specifics
4. Parameters (generated)
5. Failure modes: symptom, cause, check ID, mitigation
6. Required checks (generated)
7. Calibration needed
8. Evidence
9. Open gaps

## 7. Rules registry and evidence model

v1 used one evidence tier. Review showed that one field mixes up three separate questions, so each rule now records them separately:

| Field | Values | Question it answers |
|---|---|---|
| `kind` | `normative` (a format or spec requirement) · `empirical` (a physical printing rule) · `hypothesis` (our own engineering inference) | What sort of claim is this? |
| `provenance` | `primary` · `secondary` · `unverified` | Where does the claim come from? Source code proves what a program *does*, not that a physical rule *works* |
| `validation` | `untested` · `source-tested` (the source printed it) · `peer-reviewed` · `calibrated` (printed on our printer) | Has anyone shown that it works? |

**Rules on calibration and disagreement:**
- Calibration applies only to `empirical` rules. Each calibration is bound to a printer, nozzle, material, slicer build, profile hash, and joint family. It is invalidated when any of those change.
- Calibration keeps different effects apart:
  - overall dimensional scaling, which comes from material shrinkage and depends on part size;
  - hole and gap compensation;
  - first-layer spread (elephant foot).

  Published shrinkage ranges conflict, so they stay as uncertain evidence, not as universal compensation constants.
- When sources disagree, the rule stores each value with its conditions: axis, fit type, process. Disagreeing values often describe different measurements, so we never average them.

### Example: the Flexi Rex hinge is two rules, not one

```yaml
- id: joint.pin_in_loop.clearance.radial
  kind: empirical
  summary: Radial gap between axle and hole in a flat print-in-place hinge.
  measured_as: radial            # radial | diametral | vertical | first_layer
  unit: mm
  applies_to: {articulation: [A1]}
  scales_with_model: false
  default: 0.55
  evidence:
    - ref: "research_notes/Image to printable 3D model landscape/articulated_flexi_print_design.md"
      locator: "Clearance values (mm)"   # text the link checker must find in the file
      provenance: primary
      validation: source-tested
      claim: "DrLex Flexi Rex: axle Ø2.5 mm in hole Ø3.6 mm, so 0.55 mm radial"
  calibration: {test: calibration/pin_in_loop_ladder, bound_to: [printer, nozzle, material, slicer_build, profile_hash]}

- id: joint.pin_in_loop.clearance.vertical
  kind: empirical
  measured_as: vertical
  unit: mm
  default: 0.5
  evidence:
    - ref: "research_notes/Image to printable 3D model landscape/articulated_flexi_print_design.md"
      locator: "Clearance values (mm)"   # text the link checker must find in the file
      provenance: primary
      validation: source-tested
      claim: "DrLex: about 0.5 mm between axle top and shackle"
```

General print-in-place clearance (Prusa ≥ 0.3 mm; 0.15–0.25 mm for 10 mm PLA pins in a 2025 study) is a separate rule family. It applies to other joint geometries and has its own conditions.

## 8. Verification strategy

1. **Analytic fixtures first.**
   - Positive shapes with known area, volume, and genus.
   - *Negative* meshes, each with exactly one defect: a flipped face, a missing face, a non-manifold edge, a duplicate face, a zero-area face, two cubes sharing an edge, nested shells.
   Every check must flag its own defect and only that.
2. **Equivalent-predicate cross-checks.** For example, compare "every edge has exactly two faces *and* winding is consistent" in trimesh with lib3mf `IsManifoldAndOriented`. trimesh `is_watertight` alone tests edge incidence, not orientation.
3. **Property-based tests** with hypothesis. For example, any valid polygon extruded by any height gives a closed solid whose volume is area × height.
4. **Corpus tests.** A fixed list of Thingi10K IDs. We record a confusion table against its labels, and document each disagreement rather than treating the labels as truth.
5. **Golden-hash tests inside the pinned environment.** Across platforms, compare geometry within tolerances.
6. **Slicer integration** on macOS and Linux, with exit statuses decoded correctly. The sliced output must contain the expected objects and filaments.
7. **Physical calibration and print log.** Each physical test print gets a logged result:
   - the profile hash;
   - caliper measurements on named dimensions;
   - a pass/fail on each joint after a defined break-in procedure.

The 2026-11-08 smoke test and the Codex review found defects that are now required tests:

- **Contour bias.** OpenCV contours sit half a pixel inside outer edges and half a pixel outside hole edges.
- **Multi-part shapes.** `make_valid` can return several polygons.
- **Mirroring.** The image Y axis points down.
- **Empty masks** must not crash.
- **Precision far from the origin.** float32 storage can make small geometry far from the origin vanish while every status check still says "no error".
- **Separate build items.** Slicers may move separate build items independently.
- **Duplicate UUIDs.** UUIDs taken from names alone repeat across instances.

## 9. Environment, dependencies, licences

**Python 3.13 with `uv`.** Verification states are kept separate, per package, in the dependency register. The states are resolved, installed and imported, functionally tested, and runtime-validated. On 2026-11-08 and 09:

- **Installed, imported, and functionally tested on the M5:** the core stack, plus pymeshfix, PyMeshLab, and Open3D.
- **Installed and imported only:** libigl, rembg (no model run), onnxruntime 1.31.1 (with its Core ML provider), orca123d, point-cloud-utils, the Apple Vision bindings, and MeshLib.
- **Resolved but not installed:** `bpy` 5.2.3.
- **Not installable on 3.13:** the CGAL bindings, which stop at 3.12.

3.13 is the only version with both `bpy` and orca123d. 3.14 lacks point-cloud-utils.

**Core dependencies:** numpy, scipy, trimesh, networkx, lxml, manifold3d, lib3mf, shapely, opencv-python-headless, build123d (with cadquery-ocp), vtracer, pillow, pydantic, typer, pyyaml.

**Licences are not all permissive.** v1 said they were, which was wrong. Most core packages are MIT, BSD, or Apache. The CAD kernel underneath build123d is **OpenCASCADE, under LGPL-2.1 with a special exception**. The cadquery-ocp wrapper is Apache-2.0, but the kernel's licence still applies. Installing it as a normal pip dependency, without modifying or redistributing it, is the usual way to meet LGPL. Bundling it into an app would add obligations **(pending Q2)**.

The dependency register records, for each entry, its licence and any obligations of transitive native libraries, model weights, and datasets. For example, Thingi10K fixtures carry per-model licences.

**Optional extras:**
- `perception`: rembg, onnxruntime, pyobjc-framework-Vision.
- `depth`: Depth Anything V2 Small (Apache-2.0; the larger variants are non-commercial).
- `analysis`: PyMeshLab (GPL) **(pending Q2)**.
- `generative`: hosted backends **(pending Q3)**.
- `blender`: `bpy`.

**Copyleft and non-commercial tools** (Tweaker-3, MeshFix, MeshLib, AutoForge, PartPacker, the GPL-2.0 Blender 3MF add-on, Hunyuan3D with its EU/UK/South Korea exclusion) are allowed only as optional extras, subprocess tools, or test oracles. Each is listed with its restriction **(default, pending Q2)**.

**Slicers:**
- **OrcaSlicer 2.5.0 (Homebrew cask)** is the primary headless checker. Its v2.5.0 source shows:
  - `--repair` works on all platforms.
  - The G-code statistics export (JSON: time, volume, and weight per layer and per object) is not behind a platform guard.
  - The structured warnings file, `result.json`, is written on **Linux only**.

  None of this has been run on the M5 yet. The macOS adapter must be built and tested against real runs.
- **PrusaSlicer 2.9.7** is a second opinion.
- **OpenSCAD 2026.11**, once stable, is optional, for the BOSL2 hinge and joiner library.

**Separate environments:** text-to-cad (Python 3.14 or later), the CGAL bindings (3.12), and local MLX/MPS image-to-3D ports run in their own environments as subprocesses.

**Slicer wrapper to evaluate:** `estampo` 0.4.5 (formerly `fabprint`, PyPI, August 2026). It describes itself as a build system for reproducible 3D prints that wraps OrcaSlicer and CuraEngine. It is in early development. We assess its maturity and macOS behavior before choosing between it and our own thin subprocess layer.

**Paint encoding (C3):**
- **Existing writer:** a maintained Blender 3MF add-on already exports both Bambu/Orca `paint_color` and PrusaSlicer `mmu_segmentation`. It is GPL-2.0, has 49 stars, and was last updated in November 2026.
- **Slicer import:** OrcaSlicer 2.5's source has a texture import dialog that matches texture colors to filaments and applies the result as paint. This is GUI code. A headless path is unverified.

We evaluate both as references and test oracles before writing our own encoder. A permissive standalone encoder is needed only if Q2 requires it.

## 9b. Safety, rights, and privacy

These are not geometry problems, so the gate cannot catch them. The research did not cover them well, and the review flagged them as missing.

- **Food contact.** Cookie cutters and other food-contact prints raise questions that geometry checks cannot answer:
  - the filament and its additives;
  - the printer's contact surfaces;
  - layer lines that trap bacteria;
  - cleaning and reuse.

  Until this is researched, cookie-cutter outputs are labeled as geometric prototypes, with no food-safety claim.
- **Rights in the input image.** Three separate questions apply:
  - permission to upload or process the image;
  - rights in what it depicts, such as artwork or characters;
  - the provider's terms for the output.

  An output licence does not settle input rights. The job spec records the image's source and the user's stated permitted use, and the manifest carries both.
- **Photo privacy with cloud backends.** Before any upload, the tool shows the provider and asks for explicit consent. Each hosted backend's docs page records its input retention, use for training, visibility, deletion, and subprocessors. A local-only path is always available, even if it is slower or limited to shape-only output.
- **Licences of whole configurations.** A model repo's top-level licence does not cover everything it loads. For example, TRELLIS.2 code is MIT, but a hosted TRELLIS.2 deployment on Replicate states that users must also follow the DINOv3 licence and BRIA's RMBG-2.0 licence. BRIA's RMBG weights need a paid agreement for commercial use. Pixal3D's Mac build also bundles an encoder under the DINOv3 licence. The dependency register lists code, primary weights, auxiliary weights, and datasets separately for each backend configuration.

## 10. Position on earthtojake/text-to-cad

**Recommendation:** use it as inspiration and an optional side tool, not as a core dependency. See the landscape report for the full assessment.

- **It solves a different problem.** An LLM agent writes build123d code for mechanical parts from text. Our runtime is image-driven and LLM-free.
- **It conflicts with our environment.** It requires Python 3.14 or later; our core is pinned to 3.13. It ships several releases a day.
- **It is worth learning from:**
  - its printing DFM check;
  - its rules that "a number is never read off a picture" and "a check reports facts, never a verdict";
  - its export-tolerance guidance;
  - its catalogue of OpenCASCADE failure modes.

  Its MIT licence lets us adapt code with attribution.

## 11. Roadmap

**Build one complete vertical slice before the full framework.** Every exit test names its fixtures and its pass criteria.

| Phase | Deliverable | Exit test |
|---|---|---|
| 0. Lean foundations | pyproject (3.13) + lock; CI on GitHub's macOS arm64 runner and Linux; CLAUDE.md; the Phase 0 docs from section 6; rules schema with about 15 seed rules; dependency register | CI green on both platforms; rules and doc lint pass |
| 1. R1 vertical slice | Image → mask (plain-background threshold first; rembg optional) → trace → normalize → entry gate → loop and base → STL + 3MF → final gate (F1, F2, F3 wall and feature, F5) → Orca headless slice (F6) → manifest. First calibration generator: clearance ladders, radial and vertical | Six named fixture images give their expected verdicts: asymmetric glyph, hole inside a hole, thin stroke, diagonal touch, empty mask, photo with a plain background. Golden hashes stable on macOS CI. You print two outputs and the ladder; three named dimensions within ±0.2 mm by caliper; results logged in the printer profile |
| 2. Gate hardening | Analytic negative fixtures; fixed Thingi10K sample (200 IDs); repair ladder with function-preservation checks | Each negative fixture flags exactly its defect; confusion table published with every disagreement explained |
| 3. R2 flat multicolor | Palette snapped to profile filaments; per-color bodies on a shared base as one components object; Bambu/Orca project sidecar | Sliced output assigns each body to its intended filament; filaments per layer within the profile cap; one physical print |
| 4. R3 relief and lithophane | Heightfield with decimation; lithophane thickness rules; C4 layer schedule as a stretch goal | Named fixtures within triangle budget; one printed lithophane checked against its thickness map at five measured points |
| 5. R4 figurine, single color | Hosted G3 backend adapter; local shape-only option; scale, orient, base, decimate | Ten named images, each with a recorded verdict and repair metrics; at least one physical print |
| 6. R5 assembled parts | Plane cuts that avoid joints; connectors with calibrated fits; plate assignment | Parts assemble by hand without sanding; connector fit logged |
| 7. R6 flat flexi | Link segmentation along the skeleton of the mask; pin-in-loop hinges; calibrated radial and vertical clearance | Printed flexi moves at every joint after the defined break-in |
| 8. R7 painted figurine | Evaluate Orca texture import and the GPL add-on as oracles; color transfer onto the final mesh; paint encoder | Sliced material regions match the intended palette above the minimum region size |
| 9. R8 3D flexi | Research track: joint placement from rig predictions; ball-and-socket synthesis | Success criteria set at the start of the phase |

## 12. What changed after the 2026-11-09 review

An independent read-only review by OpenAI Codex covered the code, this plan, and the research. Its findings are saved in `research/reviews/2026-11-09-codex/`. Each finding below was reproduced or checked against its source before the plan changed. One finding was narrowed after checking.

- **Gate contract added.** v1 had no definition of "printable". Section 4 now defines one, with PASS/FAIL/UNKNOWN verdicts and per-recipe required checks.
- **Stage order fixed.** Normalize and validate before booleans; add features after scaling; run the final gate on the written file.
- **Determinism scoped.** Byte-identical only within a pinned environment. Cache keys cover the full configuration.
- **Repair rules extended** with function preservation, not only Hausdorff distance.
- **Clearances split** into radial, vertical, and first layer. Calibration is bound to the process.
- **Taxonomy redesigned** from two rigid axes into four attributes and named recipes. v1 rejected valid jobs, such as layer-change color on a figurine or a single-color articulated chain.
- **Licence claim corrected.** OpenCASCADE is LGPL-2.1 with an exception.
- **Slicer claim narrowed.** The review said Orca's JSON output is unavailable on macOS. In v2.5.0 source, only `result.json` warnings are Linux-only; the statistics JSON is not platform-guarded.
- **Resource budgets added.**
- **Color stage contract added.**
- **"No paint writer exists" corrected.**
- **Verification states separated.**
- **Exit tests made measurable.**
- **Documentation started lean.**

A second round reviewed the research report against primary sources and against its own notes. It led to these plan changes:
- **Thickness rule.** No percentile-based pass/fail.
- **Slicer tools.** estampo listed as a wrapper to evaluate; OrcaSlicer's texture-to-paint import confirmed in source.
- **New section 9b** on safety, image rights, photo privacy, and licences of whole configurations.
- **Calibration** keeps shrinkage scaling separate from gap compensation.

The report itself was corrected in the same pass; its revision history lists every change.

## 13. Open questions

These change concrete choices above. The defaults apply until answered.

- **Q1. Printer hardware.** Which printer, nozzle, and multi-material unit, if any? This sets the slicer, the project 3MF flavor, the bed size, and the maximum filaments per layer. *Default:* Bambu Lab with AMS, 0.4 mm nozzle, OrcaSlicer CLI as the checker.
- **Q2. Licence and use.** Personal use, public open source, or selling prints or models? This decides whether GPL and non-commercial tools can be more than optional, and whether bundling OpenCASCADE (LGPL) matters. Also, are you in the EU, UK, or South Korea? Hunyuan3D's licence excludes those regions. *Default:* MIT repo; permissive core plus OpenCASCADE as an unmodified pip dependency; copyleft and non-commercial tools only as optional extras, subprocess tools, or test oracles.
- **Q3. Cloud use for complex 3D (R4, R5, R7).** Local only, hosted open models (fal or Replicate, cents per run), or commercial APIs (Meshy or Tripo)? Are you comfortable uploading the source photos to a cloud service? *Default:* hosted open models first, a local shape-only option second, commercial APIs as optional adapters, and an explicit opt-in before any upload.
- **Q4. First targets.** Which recipes matter most to you first? *Default:* R1 → R2 → R3 → R4, as in section 11.
- **Q5. Interface.** Is a CLI plus a Python library enough at first, with a simple local web UI later? *Default:* yes.

# Owner-supplied MakerLab exports, 2026-11-09

Read `oddie.stl` and `roadie.stl` from the owner's
`Downloads/three-d-test/makersLabModels/`. These are meshes, not screenshots.
Generator engine/version, credits, timing, settings, and exact uploaded inputs
are unverified. The owner was asked for engine/cost details. No new upload occurred.

## Geometry inspection

STL triangle corners were indexed by **exactly equal coordinates** to reconstruct
adjacency. No tolerance-based snapping, hole filling or face deletion was used.
Component splitting explicitly disables Trimesh's default repair. All measurements
are in unspecified STL coordinate units, not verified millimeters.

| Export | Triangles | Connected bodies | Closed edge/vertex tests | Consistent winding | Duplicate/zero-area faces |
|---|---:|---:|---|---|---|
| Oddie | 194,780 | 2 | Pass | Pass | 0 / 0 |
| Roadie | 120,790 | 2 | Pass | Pass | 0 / 0 |

Both are watertight and finite; both components in each file have positive signed
volume. These are stronger topology results than the local TripoSR outputs, but
not a controlled engine benchmark: settings and input provenance are unknown.
Self-intersection, thickness, physical scale, support requirements and slicer output
are unchecked, so both remain **NOT CERTIFIED**. Two closed bodies need not be
physically attached or stable on the bed.

See `makerlab-metrics.json` for hashes and measurements, and `makerlab-previews.png`
for opposite diagnostic views. Preview shading is artificial; STL contains no
standard texture information.

## Subject interpretation

Oddie is recognizable, with a separate smaller body requiring connection inspection.
Roadie contains the bird and a disconnected circular frame. The bird has a modeled
front and a flat back: this is a shallow relief, not a full figurine. The frame is
unwanted under the owner's explicit instruction to keep only the bird and ignore
the grey background. Passing topology does not establish that the right subject
or intended depth representation was generated.

Saved `artifacts/makerlab/roadie-bird-only.stl`: removed the 29,164-face frame and
retained all 91,626 bird faces. The extraction is tied to the inspected source hash,
not a general rule that smaller components should be discarded. Round-trip STL
triangle coordinates match the selected source triangles exactly. The result is
one watertight, consistently wound body with positive signed volume. Its extent is
75.829 × 7.271 × 61.752 in unspecified STL units. Source files are unchanged.
It still has a flat back and unverified printing properties. `extract_roadie.py`
and `roadie-extraction.json` record the operation; no model was regenerated.

The owner-requested interpretation capability is now in `docs/PLAN.md` v2.1 and
`docs/guide/input-interpretation.md`. Implementation is pending. Free text must
resolve into an explicit subject/exclusion mask or supported backend instruction;
retaining the text alone is not successful interpretation. Default runtime LLM
policy is unchanged.

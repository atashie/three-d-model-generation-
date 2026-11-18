# Glossary

| Term | Meaning |
|---|---|
| 3MF | 3D Manufacturing Format. A zip of XML files with units, objects, colors and metadata. ISO/IEC 25422:2025. The project's main output |
| AMS, AMS lite | Bambu's automatic filament changers. The AMS lite has 4 slots and connects to the A1 directly; larger AMS units need a hub. This project's files never name a unit |
| Portable file | A 3MF that uses only the standard format and names colors rather than slots. Checked in two slicers with different readers; a palette list covers slicers that ignore color tags |
| Bead | One line of extruded plastic. `tdmg slice` models each G-code move as a line of its stated width with round ends |
| Bed / build plate | The heated surface the print sits on. The A1's printable volume is 256 × 256 × 256 mm |
| Bridge | A horizontal span printed in mid-air between two supports |
| Card (`card.md`) | The page in a library entry that says what to print, which face goes on the bed, the filaments, the verdict at the time, what was not checked, and the owner's confirmation in their words |
| Calibration print | A small test print that measures what your printer actually does, such as the smallest gap that stays free |
| Confirmation | The owner's own words, recorded verbatim by `tdmg job confirm`, that a selection, a color plan or a print is right. It covers the files it names by hash and goes stale when they change |
| Color change (tool change) | The printer unloads one filament and loads another during a multicolor print. Each change costs time and some plastic (flush and prime tower) |
| Clearance | A deliberate gap between surfaces that must move or fit. Measured as radial, vertical, or first-layer gap |
| Elephant foot | The first layer spreading wider than designed because it is pressed onto the bed. Slicers offset it by shrinking the first layer's outline ("elephant-foot compensation", 0.075 mm in the pinned A1 profile) |
| Extrusion width / perimeter | The width of one line of plastic, about the nozzle diameter. Walls print most reliably as whole numbers of perimeters |
| Flush | Plastic pushed out at a color change to clear the old color from the nozzle |
| Footprint (printed) | The area a layer of G-code covers with plastic: the union of its beads |
| FDM | Fused deposition modelling: melting filament and laying it down layer by layer |
| Face up / face down | How a flat multicolor model lies on the bed: face up has its colors in the top layers; face down is turned 180° about the y axis, with the colors in the first layers, on the bed. By default `tdmg slice` slices both faces and prefers face down when it is PRINTABLE (since 2026-11-16) |
| Flexi | A print-in-place articulated model whose segments move after printing |
| G-code | The printer's instructions, made by the slicer |
| Gap infill | Thin lines a slicer lays in spaces too narrow for a full wall, such as a tapered tip |
| Gate | This project's set of checks that decides PRINTABLE or NOT CERTIFIED |
| Genus | The number of through-holes in a closed surface. A ring has genus 1 |
| Infill | The sparse internal structure inside a solid print |
| Job | One print in progress: `jobs/NAME/`, with the source image, the settings (`job.yaml`) and one folder per stage. Not in git; deleted by `tdmg finish` after the owner's purge permission |
| Library (entry) | `prints/NAME/`, a finished print written by `tdmg finish`: card, `job.yaml`, provenance, purge record, the printable files (`files/` if public, `private/` if not) and the source image (`source/`, git-ignored). `tdmg library check` and `verify` check it |
| Manifold | Edge-manifold: every edge belongs to exactly two triangles. Vertex-manifold: no two surfaces meet at a single pinched point. A surface that is both is locally like a sheet |
| Mesh | A surface made of triangles |
| Normal | The direction a triangle faces. Printable meshes have all normals pointing outward |
| Overhang | A surface leaning outward over empty space |
| Prime tower | A small tower beside the model, printed at the color changes, so that the new color flows evenly before it reaches the model |
| Output class | The kind of print a job asks for: `flat-icon` now, `figurine` and `flexi` later. Each class maps to recipes |
| Print-in-place | Moving parts printed already assembled, separated by clearances |
| Provenance (`provenance.json`) | The library entry's record of how the print was made: code commit, versions, rules and profile hashes, algorithm ids, record hashes, verdicts, checks and the owner's confirmations |
| Purge | Deleting a job's working data (`jobs/NAME/`) once its library entry is complete and proven to rebuild. Only `tdmg finish` purges, only with the owner's separate permission in their words, recorded with the deleted file list in `purge.json` |
| Recipe | A named combination of geometry, joints, color, and assembly that this project implements |
| Slicer | Software that cuts a mesh into layers and makes G-code, for example Bambu Studio or OrcaSlicer |
| STL | An old mesh format: triangles only, no units or color |
| Support | Temporary structure the slicer adds under overhangs, removed after printing |
| Test strip (calibration strip) | A small calibration print made by `tdmg strip`. The clearance strip tries six glue gaps; the skin strip tries five white depths over black. The owner records the results in `results-template.md` |
| Watertight | A closed surface with no holes |

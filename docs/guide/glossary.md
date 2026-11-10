# Glossary

| Term | Meaning |
|---|---|
| 3MF | 3D Manufacturing Format. A zip of XML files with units, objects, colors and metadata. ISO/IEC 25422:2025. The project's main output |
| AMS, AMS lite | Bambu's automatic filament changers. The AMS lite has 4 slots and connects to the A1 directly; larger AMS units need a hub. This project's files never name a unit |
| Portable file | A 3MF that uses only the standard format and names colors rather than slots. Checked in two slicers with different readers; a palette list covers slicers that ignore color tags |
| Bead | One line of extruded plastic. `tdmg slice` models each G-code move as a line of its stated width with round ends |
| Bed / build plate | The heated surface the print sits on. The A1's printable volume is 256 × 256 × 256 mm |
| Bridge | A horizontal span printed in mid-air between two supports |
| Calibration print | A small test print that measures what your printer actually does, such as the smallest gap that stays free |
| Clearance | A deliberate gap between surfaces that must move or fit. Measured as radial, vertical, or first-layer gap |
| Elephant foot | The first layer spreading wider than designed because it is pressed onto the bed. Slicers offset it by shrinking the first layer's outline ("elephant-foot compensation", 0.075 mm in the pinned A1 profile) |
| Extrusion width / perimeter | The width of one line of plastic, about the nozzle diameter. Walls print most reliably as whole numbers of perimeters |
| Footprint (printed) | The area a layer of G-code covers with plastic: the union of its beads |
| FDM | Fused deposition modelling: melting filament and laying it down layer by layer |
| Flexi | A print-in-place articulated model whose segments move after printing |
| G-code | The printer's instructions, made by the slicer |
| Gap infill | Thin lines a slicer lays in spaces too narrow for a full wall, such as a tapered tip |
| Gate | This project's set of checks that decides PRINTABLE or NOT CERTIFIED |
| Genus | The number of through-holes in a closed surface. A ring has genus 1 |
| Infill | The sparse internal structure inside a solid print |
| Manifold | Edge-manifold: every edge belongs to exactly two triangles. Vertex-manifold: no two surfaces meet at a single pinched point. A surface that is both is locally like a sheet |
| Mesh | A surface made of triangles |
| Normal | The direction a triangle faces. Printable meshes have all normals pointing outward |
| Overhang | A surface leaning outward over empty space |
| Print-in-place | Moving parts printed already assembled, separated by clearances |
| Recipe | A named combination of geometry, joints, color, and assembly that this project implements |
| Slicer | Software that cuts a mesh into layers and makes G-code, for example Bambu Studio or OrcaSlicer |
| STL | An old mesh format: triangles only, no units or color |
| Support | Temporary structure the slicer adds under overhangs, removed after printing |
| Watertight | A closed surface with no holes |

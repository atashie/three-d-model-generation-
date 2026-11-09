# How slicers read color from a 3MF, 2026-11-09

**Question:** the owner wants print files that work with any slicer and any AMS unit. What can a standard 3MF carry that slicers actually honor?

**Method:** read the 3MF import code of four slicers. No slicer was run, so these are source-reading results, not behavior tests.

| Slicer | Source read |
|---|---|
| PrusaSlicer | tag `version_2.9.7` |
| OrcaSlicer | tag `v2.5.0` |
| Bambu Studio | `master` branch on 2026-11-09, so not necessarily the release the owner runs |
| Cura | `main` branch |

The first version of this note assumed Bambu Studio behaves like OrcaSlicer because of their shared history. An independent review by Codex showed that assumption was wrong, and this version replaces it with Bambu's own source. See `research/reviews/2026-11-09-codex/portability.md`.

## Findings

| Slicer | Standard 3MF colors (`colorgroup`, `basematerials`) | Assemblies (component objects) | Bambu `paint_color` attribute |
|---|---|---|---|
| PrusaSlicer 2.9.7 | **Ignored.** No handler for either; the triangle parser says "we are ignoring the following attributes: p1 p2 p3 pid" | **Expanded** into separate object instances, so the grouping does not survive | **Read as a fallback** when its own attribute is empty |
| OrcaSlicer 2.5.0 | **Narrow.** A filament is assigned only from a *top-level* object's own `pid`. Each color group keeps only one color, because later colors overwrite earlier ones. Colors on parts inside an assembly are not used. No `basematerials` handler | not checked | Read and rebuilt into paint, with no check on the file's origin |
| Bambu Studio (master) | **Broad.** Reads indexed color groups (`pid` and `pindex`), per-triangle properties, and `basematerials` display colors. For a file from another program, the app says "The 3mf is not from Bambu Lab, load geometry data and color data only." It converts the colors into its color-import flow and clears any preset filament assignment | not checked | Read and rebuilt into paint. The foreign-file path checks for existing paint before converting standard colors |
| Cura (main) | **Not mapped.** No `colorgroup`, `basematerials` or `displaycolor` handling. It reads its own `extruder_nr` metadata and its own paint texture | not checked | not checked |

### Quotes from the source

PrusaSlicer 2.9.7, `src/libslic3r/Format/3mf.cpp`:

```cpp
// we are ignoring the following attributes:
// p1
// p2
// p3
// pid
// see specifications
...
std::string mm_segmentation_serialized = get_attribute_value_string(attributes, num_attributes, MM_SEGMENTATION_ATTR);
if (mm_segmentation_serialized.empty())
    mm_segmentation_serialized = get_attribute_value_string(attributes, num_attributes, "paint_color");
...
if (!_create_object_instance(component.object_id, transform * component.transform, printable, recur_counter + 1))
```

OrcaSlicer 2.5.0, `src/libslic3r/Format/bbs_3mf.cpp`:

```cpp
static constexpr const char* COLOR_GROUP_TAG = "m:colorgroup";
std::map<int, int> color_group_id_to_extruder_id_map;
m_group_id_to_color[m_current_color_group] = color;
auto extruder_itor = color_group_id_to_extruder_id_map.find(current_object->second.pid);
static constexpr const char* MMU_SEGMENTATION_ATTR = "paint_color";
```

Bambu Studio master, `src/libslic3r/Format/bbs_3mf.cpp` and `src/slic3r/GUI/Plater.cpp`:

```cpp
using ColorKey = std::pair<int, int>;
std::map<ColorKey, int> color_group_index_to_extruder_id_map;
int object_pindex = current_object->second.pindex;
group_colors[m_parent_id].push_back(bbs_get_attribute_value_string(attributes, num_attributes, "displaycolor"));
...
const wxString source_warning = _L("The 3mf is not from Bambu Lab, load geometry data and color data only.");
if (!has_painting() && standard_3mf_to_textured_meshes(model, color_group_map, volume_color_data, *tex_mesh, has_uncolored)) {
    ...
    object->config.erase("extruder");
```

## What this means for portable files

- **Closed, named mesh objects are the common ground.** Every slicer here reads them. Grouping into one assembly does not survive everywhere, because PrusaSlicer expands assemblies.
- **Standard color tags are a convenience, never something to rely on.**
  - Bambu Studio's current code honors them, through its own color-matching step.
  - OrcaSlicer honors one color per top-level object.
  - PrusaSlicer and Cura ignore them.

  So every multicolor file also needs a palette manifest that says which object is which color, and object names that carry the color.
- **To satisfy OrcaSlicer's narrow reading,** each colored body should be a top-level object with its own single-color group.
- **No encoding is proven yet.** Choosing between separate top-level objects and one assembly needs real import tests in each slicer. That is a Phase 3 exit test.
- **The paint attribute is valid only for Bambu and Prusa.** `paint_color` is read by OrcaSlicer, Bambu Studio, and PrusaSlicer, but it is an unqualified attribute, which the 3MF core schema does not allow. The core triangle schema permits extension attributes only from other namespaces (`anyAttribute namespace="##other"`). A file using it is vendor-specific by definition.

## AMS units, for the printer profile

- The A1 takes one AMS lite (4 slots) directly.
- AMS 2 Pro and AMS HT units connect only through a separate hub.
- Bambu's H2D manual says the H2D "supports up to 4 AMS 2 Pro units and 8 AMS HT units simultaneously, providing a total of 24 filament slots." That implies the AMS HT has fewer slots than the AMS 2 Pro. If the AMS 2 Pro has 4 slots, an AMS HT has 1. That last step is our inference.
- **So not every A1 setup has 4 slots.** The default palette of 4 is the AMS lite's slot count, and a job must declare its real cap.

## Not yet tested

- Any real import of a file we wrote, in any slicer.
- Bambu Studio's released version, as opposed to its master branch.

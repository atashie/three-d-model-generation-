# How slicers read color from a 3MF, 2026-11-09

**Question:** the owner wants print files that work in any slicer and with any AMS. What can a standard 3MF carry that slicers actually honor?

**Method:** read the 3MF import code of PrusaSlicer at tag `version_2.9.7` and OrcaSlicer at tag `v2.5.0`. OrcaSlicer shares its 3MF reader lineage with Bambu Studio. No slicer was run, so these are source-reading results, not behavior tests.

## Findings

| Slicer | Standard 3MF Materials extension | Bambu `paint_color` attribute | PrusaSlicer `slic3rpe:mmu_segmentation` |
|---|---|---|---|
| PrusaSlicer 2.9.7 | **Ignored.** The triangle parser says "we are ignoring the following attributes: p1 p2 p3 pid" | **Read as a fallback** when its own attribute is absent | Read |
| OrcaSlicer 2.5.0 | **Read.** `m:colorgroup` is parsed and mapped through `color_group_id_to_extruder_id_map` | Read for every triangle while parsing; the read is not gated on the file's origin | Not checked |

### PrusaSlicer 2.9.7, `src/libslic3r/Format/3mf.cpp`

```cpp
// we are ignoring the following attributes:
// p1
// p2
// p3
// pid
// see specifications
...
// Now load MM segmentation data. Unfortunately, BambuStudio has changed the attribute name after they forked us,
// leading to https://github.com/prusa3d/PrusaSlicer/issues/12502. Let's try to load both keys if the usual
// one that PrusaSlicer uses is not present.
std::string mm_segmentation_serialized = get_attribute_value_string(attributes, num_attributes, MM_SEGMENTATION_ATTR);
if (mm_segmentation_serialized.empty())
    mm_segmentation_serialized = get_attribute_value_string(attributes, num_attributes, "paint_color");
```

No `colorgroup` or `basematerials` handling was found in the file.

### OrcaSlicer 2.5.0, `src/libslic3r/Format/bbs_3mf.cpp`

- `static constexpr const char* COLOR_GROUP_TAG = "m:colorgroup";`
- `std::map<int, int> color_group_id_to_extruder_id_map;`
- `static constexpr const char* MMU_SEGMENTATION_ATTR = "paint_color";`, read in the triangle handler for every triangle.
- A file whose `Application` metadata does not start with `BambuStudio-` or `OrcaSlicer-` is logged as "3mf from other vendor". Multi-instance objects in such a file are split into separate objects.

## What this means for portable files

- **Separate bodies always survive.** One closed body per color is the encoding every slicer understands, even as plain STL files.
- **Standard color tags help only some slicers.** OrcaSlicer, and by lineage Bambu Studio, can assign filaments automatically. PrusaSlicer shows the same bodies without colors, and the user assigns filaments by hand.
- **Bambu's `paint_color` is the only per-triangle paint encoding read by more than one slicer family.** It is not part of the 3MF standard. Whether OrcaSlicer and Bambu Studio *keep* it for files from other programs, and whether strict 3MF validators accept the unknown attribute, are **untested**.

## Not yet tested

- Bambu Studio itself; its source was not read. Its behavior is inferred from the shared lineage with OrcaSlicer.
- Cura. The landscape research found no color handling in its 3MF reader.
- Any real import of a file we wrote. That is a Phase 3 exit test.

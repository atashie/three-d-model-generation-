Reviewed only `2017be7`. No files changed.

1. **High — [rules/tools.yaml:58](../../../rules/tools.yaml#L58): Orca’s automatic color assignment is substantially overstated.**

   The verification table, PLAN §§2–3, and guide present general Materials-extension support. Orca actually assigns extruders in the branch **without object configuration metadata**, using the imported top-level object’s `pid`. It does not honor `pindex`; successive colors overwrite the same group entry:

   > `m_group_id_to_color[m_current_color_group] = color;`

   Assignment then looks up:

   > `color_group_id_to_extruder_id_map.find(current_object->second.pid)`

   Evidence: [Orca v2.5.0 reader, color handler and object assembly](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.5.0/src/libslic3r/Format/bbs_3mf.cpp#L2115).

   Consequently, a multi-entry palette loses distinctions, and the planned components assembly does **not** automatically acquire each child mesh’s color. There is no `basematerials` handler.

   **Fix:** Narrow the rule to its actual conditions. Test separate mesh objects, components assemblies, multi-entry groups, and files containing configuration metadata. Until then, promise manual filament assignment, not automatic assignment.

2. **Medium — [research/verification/2026-11-09-slicer-3mf-import/README.md:44](../../../research/verification/2026-11-09-slicer-3mf-import/README.md#L44): Bambu Studio cannot be characterized by Orca’s lineage.**

   The fetched Bambu master differs materially: it supports indexed color groups, object `pindex`, triangle properties, and base-material display colors. Its reader uses:

   > `ColorKey key(object_pid, object_pindex);`

   Evidence: [Bambu reader](https://github.com/bambulab/BambuStudio/blob/master/src/libslic3r/Format/bbs_3mf.cpp#L2379).

   Moreover, the GUI routes unpainted foreign standard-color models through its color-import workflow and removes preliminary assignments:

   > `object->config.erase("extruder");`

   Evidence: [Bambu GUI import](https://github.com/bambulab/BambuStudio/blob/master/src/slic3r/GUI/Plater.cpp#L11613).

   **Fix:** Give Bambu its own versioned evidence row. Qualify “assign filaments for you” in PLAN §2 and the guide: parser support, GUI color matching, and successful headless slicing are separate capabilities.

3. **Medium — [profiles/printers/bambu-a1.yaml:11](../../../profiles/printers/bambu-a1.yaml#L11): Four filaments are not guaranteed by every supported setup.**

   AMS HT has one slot; configurations using fewer than four HT units contradict the claimed minimum. Bambu’s manual states:

   > “H2D supports up to 4 AMS 2 Pro units and 8 AMS HT units simultaneously, providing a total of 24 filament slots.”

   With four slots per Pro, that establishes one per HT. Evidence: [Bambu manual, pp. 23–24 and 75](https://csm.bblcdn.com/hub/4668d0ca43994ff3bff4b37f1a65c2e7.pdf#page=76).

   The validator excludes unknown capacities via `if u.slots is not None`. I confirmed that the current profile passes, but recording HT’s capacity as `1` makes it fail.

   **Fix:** Separate the preferred palette size from verified attached hardware capacity. Record Pro and HT separately; preserve unknown capability as unknown. Correct PLAN §13 and the guide’s “every setup” rationale. AMS-independent files do not imply hardware-independent print feasibility.

4. **Medium — [docs/PLAN.md:37](../../../docs/PLAN.md#L37): Standards compliance does not establish universal import or assembly preservation.**

   “Every slicer reads separate bodies correctly” and “open in any slicer” exceed the evidence. Prusa recursively expands component references into mesh-object instances:

   > `_create_object_instance(component.object_id, transform * component.transform, printable, recur_counter + 1)`

   Evidence: [Prusa component import](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.7/src/libslic3r/Format/3mf.cpp#L2227). An assembly’s grouping is therefore not universally preserved.

   **Fix:** Describe a tested compatibility envelope. The strongest common fallback is **separately assignable, named mesh objects**, closed geometry, explicit units/transforms, and a palette/material manifest with grouping instructions.

   Core `basematerials` can carry material names and preview colors without the Materials extension, but offers no automatic-color improvement in the inspected Prusa/Cura paths or Orca reader. The specification explicitly says:

   > “A producer MUST NOT assume that displaycolor has any effect on the printed part.”

   Evidence: [3MF core material semantics](https://github.com/3MFConsortium/spec_core/blob/master/3MF%20Core%20Specification.md#51-base-material).

   Thus neither `basematerials` nor `colorgroup` is a universal winner. Keep color extensions optional for geometry fallback; require manual mapping where necessary.

5. **Low — [research/verification/2026-11-09-slicer-3mf-import/README.md:50](../../../research/verification/2026-11-09-slicer-3mf-import/README.md#L50): Cura’s “no color handling” characterization is too broad.**

   Its current reader loads texture/UV data and calls:

   > `sliceable_decorator.setPaintTexture(texture)`

   It also recognizes `extruder_nr`. Evidence: [Cura mesh reader](https://github.com/Ultimaker/Cura/blob/main/plugins/3MFReader/ThreeMFReader.py#L173). Its workspace reader explicitly processes material profiles:

   > `material_container.deserialize(archive.open(material_container_file).read().decode("utf-8"),`

   Evidence: [Cura workspace reader](https://github.com/Ultimaker/Cura/blob/main/plugins/3MFReader/ThreeMFWorkspaceReader.py#L777).

   **Fix:** Say that the inspected plugin does not map standard `colorgroup`/`basematerials` into filament assignments. Distinguish that limitation from texture handling and Cura-specific project materials/settings.

6. **Low — [docs/PLAN.md:342](../../../docs/PLAN.md#L342): Strict validity of unqualified `paint_color` is a known constraint, not merely an unanswered experiment.**

   The core triangle schema permits extension attributes through:

   > `<xs:anyAttribute namespace="##other" processContents="lax"/>`

   It declares no unqualified `paint_color` attribute. Evidence: [3MF core triangle schema](https://github.com/3MFConsortium/spec_core/blob/master/3MF%20Core%20Specification.md#b11-core-specification-schema).

   **Fix:** Label the paint artifact as vendor-specific and outside strict core-schema validity. Test slicer acceptance separately. Adding a namespace changes the attribute name the inspected readers expect.

## Things I checked and found correct

- **PrusaSlicer:** Both new Prusa rules are substantively correct. Whole-object parsing ignores `pid`/`pindex`; triangle properties are ignored; neither resource handler exists. The fallback is used when its own segmentation string is **empty**, including absent: `if (mm_segmentation_serialized.empty())`. [Prusa reader](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.7/src/libslic3r/Format/3mf.cpp#L1839).
- **Paint retention:** The fetched Orca and Bambu readers reconstruct `paint_color` without an origin gate. I found no subsequent origin-only discard in the import paths inspected. Both call `volume->mmu_segmentation_facets.set_triangle_from_string(...)`; Bambu’s foreign-file GUI path explicitly checks existing paint before standard-color conversion. [Orca reconstruction](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.5.0/src/libslic3r/Format/bbs_3mf.cpp#L4975), [Bambu reconstruction](https://github.com/bambulab/BambuStudio/blob/master/src/libslic3r/Format/bbs_3mf.cpp#L5365).
- Keeping vendor artifacts supplemental, using separate plate files, and supplying C4 swap instructions separately are sensible portability choices.
- The evidence correctly remains `validation: untested`. **27 applicable profile/schema/CLI tests passed**; one temporary-directory test was excluded to respect read-only operation.

## Could not verify

- Actual imports, slicing, printed colors, or the owner’s installed Bambu version. Master-source behavior is not a release guarantee.
- The claim that `paint_color` is the **only** paint encoding shared across slicer families; the record does not establish that exclusivity.
- Universal portability or a uniquely “most portable” encoding without representative import fixtures and explicit acceptance criteria.
# Print types

Different kinds of print fail in different ways, so each has its own rules and checks. This section is organised so that general guidance lives in one place and specific guidance in nested pages.

## Four attributes describe any print

| Attribute | Values |
|---|---|
| **Geometry** | **G1** flat / 2.5D extrusion · **G2** relief / heightfield · **G3** full 3D |
| **Joints** | **A0** none · **A1** flat print-in-place joints · **A2** 3D print-in-place joints |
| **Color** | **C1** single filament · **C2** one body per filament · **C3** per-triangle paint · **C4** filament change by layer |
| **Assembly** | **L1** one print · **L2** parts printed separately and assembled |

The categories you started with map onto these attributes:

| Your category | Attributes |
|---|---|
| Complex 3D shape | G3 · A0 |
| Flat flexi | G1 · A1 |
| Fully 3D flexi | G3 · A2 |
| Single color | C1 (any number of bodies) |
| Multicolor | C2, C3 or C4 |
| Single colors printed on several plates, then combined | C1 per part · L2 |

## Two levels of pages

- **Attribute pages** (`attributes/`) hold the rules and failure modes of one attribute value, whatever it is combined with. For example, `geometry-flat.md` covers every flat print.
- **Recipe pages** (`recipes/`) cover one named combination that we implement. A recipe page links its attribute pages and adds only what is specific to the combination.

The recipe list and status are generated from code: [recipes.md](recipes.md).

Almost every combination is physically possible. The real constraints live inside recipes:
- Layer-change color (C4) varies only with height.
- Cut planes for assembly (L2) must avoid joints.
- Paint (C3) is applied to the final mesh, after any repair.
- Flat joints (A1) imply flat geometry (G1).

## Page template

Every attribute and recipe page has these headings, in this order. `tests/test_docs.py` checks them.

1. What it is
2. When to use / when not to
3. Pipeline specifics
4. Parameters (rule IDs from [the rules reference](../reference/rules.md))
5. Failure modes (symptom, cause, check, mitigation)
6. Required checks
7. Calibration needed
8. Evidence
9. Open gaps

## Pages so far

| Page | Covers |
|---|---|
| [attributes/geometry-flat.md](attributes/geometry-flat.md) | G1 flat / 2.5D extrusion |
| [attributes/color-single.md](attributes/color-single.md) | C1 single filament |
| [attributes/color-multi.md](attributes/color-multi.md) | C2 one body per filament (step 1: the color plan) |
| [attributes/assembly-single.md](attributes/assembly-single.md) | L1 one print |
| [recipes/r1-flat-single.md](recipes/r1-flat-single.md) | R1 flat single-color |

More pages arrive with the recipes that need them.

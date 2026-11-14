"""Calibration test strips for two R2 rules (R2 step 5, part 1).

docs/plans/2026-11-14-test-strip.md, Decisions 1 to 3 and Task 1. Two small prints let
the owner set two hypotheses from a real print:
- the clearance strip (Decision 1) tests color.glue.clearance_mm: one base with six
  square pockets and one glue piece per pocket, each with its own gap;
- the skin strip (Decision 2) tests color.skin.depth_mm: a black base with white patches
  of five depths, a black-only reference and a full-depth white reference.

Both are built from fixed rectangles with the same geometry code as tdmg flat --colors:
color_cells cuts the strip into labelled cells on the storage grid; the clearance strip
then calls glue_geometry once per gap on the same cells (make_colored_flat's arguments,
with the gap as the clearance) and keeps pocket k's piece from call k; the skin strip
meshes its bodies with _body and one z range per cell, on the cells' grid and with each
z value computed once, as ams_bodies does.

Labels are round through-holes below each square: k holes for pocket k, and 1 to 5 holes
for the five depth patches, so the strips read without a font. The holes are interior
rings of the silhouette.

The layout numbers are the test object's size, not rules (Decision 3). They are module
constants, and each layout is checked against the rules it must meet when it is built:
every wall at least fdm.wall.min_thickness and every hole at least fdm.hole.min_diameter
across (StripError otherwise).

The builders (clearance_strip, skin_strip) are pure: no I/O. make_strips (Task 2) gates,
slices and writes both strips:
- clearance/: base.stl and pieces.stl, each gated by the R1 mesh checks (tdmg.checks'
  topology checks and F2.export_matches_geometry against its Body, F2.fits_build_volume,
  F5.triangles), with F4.glue_partition and F4.glue_fit of every glue call; each STL
  sliced as an R1 part (tdmg.slicing.slice_stl, the run tdmg.color_slicing's glue plates
  use) with F4.body_count against the strip's own count (1 and GAP_COUNT), in
  clearance/slice/base/ and clearance/slice/pieces/;
- skin/: model.3mf (tdmg.threemf, one shell per color, from the gated meshes) and
  palette.json, gated by F4.color_partition, F4.filaments, F2.fits_build_volume,
  F5.triangles and F2.export_3mf_matches_bodies, and the per-body R1 mesh checks;
  sliced face up by tdmg.color_slicing.slice_face (F2.orca_input_matches_bodies and the
  step 4 color checks) in skin/slice/;
- strip.json last (schema tdmg.strip/1, algorithm strip-1).
The required sets (PLATE_REQUIRED; SKIN_INHERITED_REQUIRED and slice_face's own), and
why each check that is not required is not (not_required_reasons), are in the plan's
Task 2 amendments. PrusaSlicer is never run for a strip: F6.portability is UNKNOWN and
not required (PORTABILITY_NOT_REQUIRED).
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import numbers
import platform
from dataclasses import dataclass
from itertools import combinations, pairwise

import numpy as np
import shapely
import trimesh
from shapely.geometry import Polygon

from tdmg import __version__
from tdmg import color_slicing as _color
from tdmg import slicing as _slicing
from tdmg.checks import CheckResult, merge_exact, topology_checks
from tdmg.color_checks import (
    body_export_check,
    color_partition_check,
    export_3mf_check,
    filaments_check,
    glue_fit_check,
    glue_partition_check,
)
from tdmg.color_config import palette_cap
from tdmg.color_gcode import F3_WARNING_NOTE, INFO_CHECK_IDS, INFO_NOTE, f3_note
from tdmg.color_geometry import (
    Body,
    Cells,
    ColorGeometryError,
    ColorRegions,
    _body,
    color_cells,
    snap_move_mm,
    storage_grid_mm,
    vertex_dist,
)
from tdmg.color_glue import Glue, glue_geometry
from tdmg.colored_flat import (
    COLORED_REQUIRED_CHECKS,
    GLUE_ONLY_CHECKS,
    body_file,
    colored_environment,
)
from tdmg.flat import (
    QUAD_SEGS,
    build_volume_check,
    cleaning_params,
    encode_stl,
    mesh_summary,
    triangle_check,
)
from tdmg.profiles import PrinterProfile, load_printer
from tdmg.records import (
    RecordError,
    canonical_json,
    check_output_dir,
    record_text,
    write_outputs,
)
from tdmg.rules import load_rules
from tdmg.slicer import SlicerError
from tdmg.threemf import Shell, ThreeMFError, palette_manifest, write_multishell_3mf

# --- layout (Decision 3: the test object's size, not rules) -----------------------------

# Decisions 1 and 2: both strips are 3.0 mm thick.
THICKNESS_MM = 3.0
# Decision 1: six square pockets, 10 mm a side, 5 mm apart and 5 mm from the edges.
POCKET_SIDE_MM = 10.0
POCKET_SPACING_MM = 5.0
# Decision 1 (pockets 5 mm from the edges). Decision 2 gives no edge margin for the skin
# strip's patches; it uses the same one (a layout choice).
EDGE_MARGIN_MM = 5.0
# Decision 2: seven square patches, 12 mm a side, 4 mm apart.
PATCH_SIDE_MM = 12.0
PATCH_SPACING_MM = 4.0
# Decision 1: gap k (1 to 6) is marked by k holes. Decision 2: patches 2 to 6 (the five
# depths) by 1 to 5 holes; patch 1 (black only) and patch 7 (full white) by none.
POCKET_HOLES = (1, 2, 3, 4, 5, 6)
PATCH_HOLES = (0, 1, 2, 3, 4, 5, 0)
# The label holes' layout (Decisions 1 and 2 leave it open; a layout choice, checked
# against fdm.wall.min_thickness when built). Six holes of 2 mm with walls of at least
# 0.9 mm need 6 x 2 + 6 x 0.9 = 17.4 mm per pocket, more than the 15 mm pocket pitch, so
# the holes sit in rows of at most HOLES_PER_ROW, each row centred under its square:
# 3 holes at HOLE_PITCH_MM span 2 x 3.5 + 2 = 9 mm, inside a 10 mm pocket. Rows are
# HOLE_PITCH_MM apart, and LABEL_GAP_MM is the solid between a square and the first row's
# holes, and between the last row and the strip's bottom edge.
HOLES_PER_ROW = 3
HOLE_PITCH_MM = 3.5
LABEL_GAP_MM = 2.0
LABEL_ROWS = 2  # rows below every square: ceil(max holes / HOLES_PER_ROW), both strips
# Each hole is a regular polygon of HOLE_SEGMENTS sides, the circle tdmg.flat's buffers
# draw (4 x QUAD_SEGS per circle). An approximation setting, not a rule.
HOLE_SEGMENTS = 4 * QUAD_SEGS

# Decision 2: palette black #000000 (the base) and white #FFFFFF (the patches).
SKIN_BASE_INDEX = 0
SKIN_WHITE_INDEX = 1
SKIN_PALETTE = ((SKIN_BASE_INDEX, "#000000"), (SKIN_WHITE_INDEX, "#FFFFFF"))
# The clearance strip is one color; the cells need a base label and an inlay label.
CLEARANCE_BASE_INDEX = 0
CLEARANCE_INLAY_INDEX = 1

# The owner's answers (2026-11-14), "What is known" in the plan: gaps 0.10 to 0.35 mm by
# 0.05 (six pockets); skin depths 0.2 to 1.0 mm by 0.2 (five patches).
OWNER_GAPS_MM = (0.10, 0.15, 0.20, 0.25, 0.30, 0.35)
OWNER_DEPTHS_MM = (0.2, 0.4, 0.6, 0.8, 1.0)
GAP_COUNT = len(POCKET_HOLES)
DEPTH_COUNT = sum(1 for k in PATCH_HOLES if k)
FULL_PATCH = len(PATCH_HOLES)  # patch 7 (1-based): white through the whole thickness

# The printer the strips are for (the plan's goal: the Bambu A1); its nozzle sets the
# island area of the glue route's cleaning, as in make_colored_flat.
PRINTER_ID = "bambu-a1"

WALL_RULE = "fdm.wall.min_thickness"
HOLE_RULE = "fdm.hole.min_diameter"
SKIN_RULE = "color.skin.depth_mm"
MIN_SIDE_RULE = "color.glue.min_piece_side_mm"


class StripError(ValueError):
    """A test strip cannot be built as asked. (Not TestStripError: pytest would try to
    collect a class named Test*.)"""


@dataclass(frozen=True, eq=False)
class Layout:
    """One strip's rectangles and holes in model mm, before the grid.

    width_mm, height_mm: the strip, [0, width] x [0, height]. squares: the pockets or
    patches, left to right. hole_centres, holes: per square, its label holes (centres and
    polygons). hole_apothem_mm: each hole polygon's inscribed radius. silhouette: the
    strip minus every hole. grid_mm: G, storage_grid_mm of the strip's largest
    coordinate: the grid color_cells puts it on.
    """

    width_mm: float
    height_mm: float
    squares: tuple[Polygon, ...]
    hole_centres: tuple[tuple[tuple[float, float], ...], ...]
    holes: tuple[tuple[Polygon, ...], ...]
    hole_apothem_mm: float
    silhouette: Polygon
    grid_mm: float


def _hole(centre: tuple[float, float], apothem: float) -> Polygon:
    """A regular HOLE_SEGMENTS-gon around centre with inscribed radius apothem."""
    n = HOLE_SEGMENTS
    radius = apothem / math.cos(math.pi / n)
    x, y = centre
    return Polygon([(x + radius * math.cos(2 * math.pi * i / n),
                     y + radius * math.sin(2 * math.pi * i / n)) for i in range(n)])


def min_wall_mm(layout: Layout) -> float:
    """The thinnest solid between any two of the holes and squares, and between each of
    them and the strip's outer edge (shapely.distance, before the grid)."""
    edge = shapely.box(0, 0, layout.width_mm, layout.height_mm).exterior
    shapes = [h for hs in layout.holes for h in hs] + list(layout.squares)
    walls = [float(shapely.distance(a, b)) for a, b in combinations(shapes, 2)]
    walls += [float(shapely.distance(s, edge)) for s in shapes]
    return min(walls)


def _layout(side: float, spacing: float, counts: tuple[int, ...], rules: dict) -> Layout:
    if -(-max(counts) // HOLES_PER_ROW) > LABEL_ROWS:
        raise StripError(f"{max(counts)} holes do not fit in {LABEL_ROWS} rows of "
                         f"{HOLES_PER_ROW}")
    n = len(counts)
    width = 2 * EDGE_MARGIN_MM + n * side + (n - 1) * spacing
    hole_d = float(rules[HOLE_RULE].default)
    r = hole_d / 2
    below = LABEL_GAP_MM + 2 * r + (LABEL_ROWS - 1) * HOLE_PITCH_MM + LABEL_GAP_MM
    height = below + side + EDGE_MARGIN_MM
    grid = storage_grid_mm(max(width, height))
    # Snap rounding moves every boundary point by at most snap_move_mm(G), and float64
    # rounding each vertex by at most vertex_dist; the apothem adds both, so the gridded
    # hole still holds the rule's circle (derived, not a rule).
    apothem = r + snap_move_mm(grid) + vertex_dist([shapely.box(0, 0, width, height)])
    squares, centres, holes = [], [], []
    for i, count in enumerate(counts):
        x0 = EDGE_MARGIN_MM + i * (side + spacing)
        y0 = below
        squares.append(shapely.box(x0, y0, x0 + side, y0 + side))
        mid = x0 + side / 2
        mine = []
        for row in range(LABEL_ROWS):
            k = max(0, min(HOLES_PER_ROW, count - row * HOLES_PER_ROW))
            y = y0 - LABEL_GAP_MM - r - row * HOLE_PITCH_MM
            mine += [(mid + (j - (k - 1) / 2) * HOLE_PITCH_MM, y) for j in range(k)]
        centres.append(tuple(mine))
        holes.append(tuple(_hole(c, apothem) for c in mine))
    all_holes = [h for hs in holes for h in hs]
    silhouette = Polygon(shapely.box(0, 0, width, height).exterior.coords,
                         [h.exterior.coords for h in all_holes])
    if not silhouette.is_valid:
        raise StripError(f"the strip outline is not valid: "
                         f"{shapely.is_valid_reason(silhouette)}")
    layout = Layout(width, height, tuple(squares), tuple(centres), tuple(holes), apothem,
                    silhouette, grid)
    wall = float(rules[WALL_RULE].default)
    thinnest = min_wall_mm(layout)
    # Snap rounding can move each side of a wall by snap_move_mm(G).
    if thinnest - 2 * snap_move_mm(grid) < wall:
        raise StripError(f"the layout's thinnest wall is {thinnest:.6g} mm (less two grid "
                         f"snaps), below the {wall:g} mm of rule {WALL_RULE}")
    return layout


def clearance_layout(*, rules: dict) -> Layout:
    """The clearance strip's layout (Decision 1)."""
    return _layout(POCKET_SIDE_MM, POCKET_SPACING_MM, POCKET_HOLES, rules)


def skin_layout(*, rules: dict) -> Layout:
    """The skin strip's layout (Decision 2)."""
    return _layout(PATCH_SIDE_MM, PATCH_SPACING_MM, PATCH_HOLES, rules)


# --- inputs ------------------------------------------------------------------------------


def _values(name: str, values, count: int, below: float, what: str) -> tuple[float, ...]:
    """values as floats: a list or tuple of exactly count finite numbers above 0 (bools
    refused), strictly ascending, each below `below` (what says why)."""
    if not isinstance(values, (list, tuple)):
        raise StripError(f"{name} must be a sequence (list or tuple) of {count} numbers, "
                         f"got {values!r}")
    if len(values) != count:
        raise StripError(f"{name} must have exactly {count} values, got {len(values)}")
    out = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, numbers.Real):
            raise StripError(f"{name} must hold numbers, got {v!r}")
        v = float(v)
        if not math.isfinite(v):
            raise StripError(f"{name} must hold finite numbers, got {v}")
        if v <= 0:
            raise StripError(f"{name} must hold numbers above 0, got {v}")
        if v >= below:
            raise StripError(f"{name}: {v:g} is not below {what} ({below:g} mm)")
        out.append(v)
    if any(a >= b for a, b in pairwise(out)):
        raise StripError(f"{name} must be strictly ascending, got {out}")
    return tuple(out)


def _cells(layout: Layout, squares, inlay: int, base: int) -> Cells:
    """color_cells of the layout's silhouette: squares (some of the layout's) labelled
    inlay, the rest of the silhouette base."""
    squares = list(squares)
    rest = shapely.difference(layout.silhouette, shapely.union_all(squares))
    base_top = [p for p in shapely.get_parts(rest) if p.area > 0]
    try:
        cells = color_cells(ColorRegions({inlay: squares}, base_top, {}, []),
                            layout.silhouette, base)
    except ColorGeometryError as e:
        raise StripError(f"the strip's cells were refused: {e}") from None
    if cells.grid_mm != layout.grid_mm:
        raise StripError(f"the cells' grid {cells.grid_mm} mm is not the layout's "
                         f"{layout.grid_mm} mm")
    return cells


def _slot(polygon, squares) -> int:
    """The 0-based square that contains polygon's point on surface, or -1."""
    point = shapely.point_on_surface(polygon)
    return next((i for i, sq in enumerate(squares) if sq.contains(point)), -1)


# --- the clearance strip (Decision 1) ----------------------------------------------------


@dataclass(frozen=True, eq=False)
class ClearanceStrip:
    """gaps_mm: the gaps, pocket 1 (left) first. layout, cells: the strip and its
    labelled cells (glue_geometry's input). base: the glue base with its six pockets
    (identical in every glue call). pockets: the pocket polygons on the grid, left to
    right. pieces: one Body per gap, its pocket's piece from that gap's call (name
    f"piece-{k}", k 1 to 6). glues: the Glue of each call, in gap order (each has all six
    pieces at its own gap; their reports and checks are per call)."""

    gaps_mm: tuple[float, ...]
    layout: Layout
    cells: Cells
    base: Body
    pockets: tuple[Polygon, ...]
    pieces: tuple[Body, ...]
    glues: tuple[Glue, ...]


def _no_leftover(glue: Glue, gap: float) -> None:
    """StripError if the glue call gave any pocket area to the base (a leftover) or
    joined a pinch in its rebuild. Either changes the pocket with the gap, so the strip
    would not test one pocket at six gaps (the plan's Decision 1 amendment)."""
    leftover = float(glue.report["leftover_mm2"])
    if leftover > 0:
        raise StripError(f"at gap {gap:g} mm the glue route gives {leftover:.6g} mm^2 of "
                         "leftover to the base, so the pockets would depend on the gap")
    if glue.cells.pinch_fixes:
        raise StripError(f"at gap {gap:g} mm the glue rebuild joined "
                         f"{len(glue.cells.pinch_fixes)} pinch points, so the pockets "
                         "would depend on the gap")


def _same_base(first: Glue, glue: Glue, gap: float) -> None:
    """StripError unless glue's rebuilt cells, pockets and base mesh equal first's."""
    same = (glue.grid_mm == first.grid_mm
            and glue.cells.labels == first.cells.labels
            and [shapely.to_wkb(c) for c in glue.cells.cells]
            == [shapely.to_wkb(c) for c in first.cells.cells]
            and [(p.index, shapely.to_wkb(p.polygon)) for p in glue.pockets]
            == [(p.index, shapely.to_wkb(p.polygon)) for p in first.pockets]
            and np.array_equal(glue.bodies[0].mesh.vertices, first.bodies[0].mesh.vertices)
            and np.array_equal(glue.bodies[0].mesh.faces, first.bodies[0].mesh.faces))
    if not same:
        raise StripError(f"the base and pockets differ between gap {first.clearance_mm:g} "
                         f"mm and gap {gap:g} mm: the pockets must not depend on the gap")


def clearance_strip(gaps_mm, *, rules: dict,
                    printer: PrinterProfile | None = None) -> ClearanceStrip:
    """The clearance strip: one base with six pockets, one piece per gap.

    gaps_mm: exactly GAP_COUNT gaps, finite, above 0, strictly ascending, each below half
    the pocket side (StripError naming gaps_mm). rules: tdmg.rules.load_rules(). printer:
    the profile whose nozzle sets the cleaning's island area (default PRINTER_ID).
    glue_geometry is called once per gap on the same cells, with make_colored_flat's
    arguments: thickness THICKNESS_MM, skin and pocket depth color.skin.depth_mm,
    clearance the gap, color.glue.min_piece_side_mm, and cleaning_params' opening and
    island area. A call that gives leftover to the base or joins a pinch is refused
    (StripError, _no_leftover): then the pockets depend on the gap. From call k only
    pocket k's piece is kept; the base and the pockets must be identical across the
    calls (StripError otherwise). Every call must give exactly one piece per pocket.
    """
    gaps = _values("gaps_mm", gaps_mm, GAP_COUNT, POCKET_SIDE_MM / 2,
                   "half the pocket side")
    profile = printer if printer is not None else load_printer(PRINTER_ID)
    skin = float(rules[SKIN_RULE].default)
    side = float(rules[MIN_SIDE_RULE].default)
    opening_param, island_param = cleaning_params(rules, profile)
    layout = clearance_layout(rules=rules)
    cells = _cells(layout, layout.squares, CLEARANCE_INLAY_INDEX, CLEARANCE_BASE_INDEX)
    glues, pieces, pockets = [], [], None
    for k, gap in enumerate(gaps):
        try:
            glue = glue_geometry(cells, thickness_mm=THICKNESS_MM, skin_mm=skin,
                                 clearance_mm=gap, min_piece_side_mm=side,
                                 opening_mm=opening_param["value"],
                                 min_island_mm2=island_param["value"])
        except ColorGeometryError as e:
            raise StripError(f"the glue geometry at gap {gap:g} mm was refused: {e}") \
                from None
        _no_leftover(glue, gap)
        if (len(glue.pockets) != GAP_COUNT
                or sorted(p.pocket for p in glue.pieces) != [p.number for p in glue.pockets]):
            raise StripError(
                f"at gap {gap:g} mm the glue route gives {len(glue.pockets)} pockets and "
                f"{len(glue.pieces)} pieces, not one piece in each of {GAP_COUNT} pockets: "
                f"a piece below rule {MIN_SIDE_RULE} ({float(rules[MIN_SIDE_RULE].default):g}"
                f" mm a side) is folded into the base with its pocket")
        if glues:
            _same_base(glues[0], glue, gap)
        slots = [_slot(p.polygon, layout.squares) for p in glue.pockets]
        if sorted(slots) != list(range(GAP_COUNT)):
            raise StripError(f"at gap {gap:g} mm the pockets are not one per square "
                             f"(squares {slots})")
        by_slot = {s: p for s, p in zip(slots, glue.pockets, strict=True)}
        if pockets is None:
            pockets = tuple(by_slot[s].polygon for s in range(GAP_COUNT))
        mine = [p for p in glue.pieces if p.pocket == by_slot[k].number]
        if len(glue.pieces) != GAP_COUNT or len(mine) != 1:
            raise StripError(f"at gap {gap:g} mm there are {len(glue.pieces)} pieces and "
                             f"{len(mine)} in pocket {k + 1}; need one per pocket")
        pieces.append(_body(f"piece-{k + 1}", mine[0].index, [mine[0].polygon],
                            [(0.0, skin)], glue.grid_mm))
        glues.append(glue)
    return ClearanceStrip(gaps, layout, cells, glues[0].bodies[0], pockets, tuple(pieces),
                          tuple(glues))


# --- the skin strip (Decision 2) ---------------------------------------------------------


@dataclass(frozen=True, eq=False)
class SkinStrip:
    """depths_mm: the five depths, patch 2 first. layout, cells: the strip and its cells
    (white patches labelled SKIN_WHITE_INDEX, the rest SKIN_BASE_INDEX). patches: per
    cell, its patch number (1 to 7, left to right) for white cells, 0 for black cells
    (patch 1 is black only, so it has none of its own). base: the black body. white: the
    white body (name f"color-{SKIN_WHITE_INDEX}")."""

    depths_mm: tuple[float, ...]
    layout: Layout
    cells: Cells
    patches: tuple[int, ...]
    base: Body
    white: Body


def skin_strip(depths_mm, *, rules: dict) -> SkinStrip:
    """The skin strip: a black base with white patches of each depth and one full patch.

    depths_mm: exactly DEPTH_COUNT depths, finite, above 0, strictly ascending, each
    below THICKNESS_MM (StripError naming depths_mm). rules: tdmg.rules.load_rules().
    The cells are color_cells of the layout (patches 2 to 7 white). With T = THICKNESS_MM
    and z = T - d computed once per depth d, as ams_bodies computes T - d once:
    - white: a cell of depth patch d spans (z, T); a cell of the full patch (0, T);
    - base: a black cell spans (0, T), a cell of depth patch d (0, z); the full patch's
      cells are not in the base.
    Both bodies are _body on the cells' grid G, so they share their x, y vertices and z
    floats.
    """
    depths = _values("depths_mm", depths_mm, DEPTH_COUNT, THICKNESS_MM, "the thickness")
    layout = skin_layout(rules=rules)
    white_squares = tuple(sq for sq, k in zip(layout.squares, PATCH_HOLES, strict=True)
                          if k) + (layout.squares[FULL_PATCH - 1],)
    patch_numbers = [i + 1 for i, k in enumerate(PATCH_HOLES) if k] + [FULL_PATCH]
    cells = _cells(layout, white_squares, SKIN_WHITE_INDEX, SKIN_BASE_INDEX)
    t = THICKNESS_MM
    tops = {n: t - d for n, d in zip(patch_numbers[:DEPTH_COUNT], depths, strict=True)}
    patches = []
    for cell, label in zip(cells.cells, cells.labels, strict=True):
        if label == SKIN_BASE_INDEX:
            patches.append(0)
            continue
        slot = _slot(cell, white_squares)
        if slot < 0:
            raise StripError("a white cell lies in no patch")
        patches.append(patch_numbers[slot])
    base_cells, base_ranges, white_cells, white_ranges = [], [], [], []
    for cell, patch in zip(cells.cells, patches, strict=True):
        if patch == 0:
            base_cells.append(cell)
            base_ranges.append((0.0, t))
        elif patch == FULL_PATCH:
            white_cells.append(cell)
            white_ranges.append((0.0, t))
        else:
            base_cells.append(cell)
            base_ranges.append((0.0, tops[patch]))
            white_cells.append(cell)
            white_ranges.append((tops[patch], t))
    try:
        base = _body("base", SKIN_BASE_INDEX, base_cells, base_ranges, cells.grid_mm)
        white = _body(f"color-{SKIN_WHITE_INDEX}", SKIN_WHITE_INDEX, white_cells,
                      white_ranges, cells.grid_mm)
    except ColorGeometryError as e:
        raise StripError(f"the skin strip's bodies were refused: {e}") from None
    return SkinStrip(depths, layout, cells, tuple(patches), base, white)


# --- gating, files and slicing (Task 2) --------------------------------------------------

RECORD_SCHEMA = "tdmg.strip/1"
# The version of what strip_id names (plan Decision 4), bumped whenever the verdict for
# the same request can change. strip-1 (2026-11-14): plan Task 2.
ALGORITHM = "strip-1"
SOURCE = "docs/plans/2026-11-14-test-strip.md"
OWNER_SOURCE = "the owner's answers of 2026-11-14 (the plan's \"What is known\")"
RECORD_NAME = "strip.json"
CLEARANCE_DIR = "clearance"
SKIN_DIR = "skin"
SLICE_DIR = "slice"
BASE_STL = "base.stl"
PIECES_STL = "pieces.stl"
MODEL_3MF = "model.3mf"
PALETTE_NAME = "palette.json"
SKIN_FACE = "up"            # Decision 2: sliced face up
SKIN_ROUTE = "skin"         # the shells' names, as tdmg.colored_flat.body_file names bodies
# The deepest output path, clearance/slice/base/plate_1.gcode, has three folders.
FOLDER_LEVELS = 3
PORTABILITY = "F6.portability"
TARGET_WIDTH = "F2.target_width"
# The required sets (plan Task 2 amendments). A clearance plate: R1's set less
# F2.target_width (not applicable) and F6.portability (not required), plus the glue
# checks of Decision 1. The skin: the AMS route's gate checks, as tdmg.color_slicing
# requires them of a plan's face; slice_face adds the rest.
PLATE_REQUIRED = frozenset((_slicing.SLICE_REQUIRED_CHECKS - {TARGET_WIDTH, PORTABILITY})
                           | GLUE_ONLY_CHECKS)
SKIN_INHERITED_REQUIRED = frozenset(COLORED_REQUIRED_CHECKS - GLUE_ONLY_CHECKS
                                    - _color.INHERITED_DROPPED)
TARGET_WIDTH_NA = ("not applicable to a strip plate: the strip's size is set by the "
                   "layout constants (plan Decision 3), not by a requested width")
PORTABILITY_NOT_REQUIRED = (
    "not run and not required for a strip (plan Task 2 amendment): the strips are "
    "printed once, from Bambu Studio on the owner's A1, to set two rules; F6.portability "
    "asks whether a second slicer reads the file as modelled, which does not bear on "
    "that, and the plan's command (Task 3) has no PrusaSlicer option")
WARNING_REASON = F3_WARNING_NOTE + " As for an owner plan's face (plan Decision 2)."
STRIP_PRINTABLE_MEANING = (
    "PRINTABLE means every required gate check passed for every plate or face of this "
    "strip with the pinned OrcaSlicer 2.5.0 and the A1 profile. It is not a guarantee: the "
    "acceptance tolerance (acceptance.dimension.tolerance) is still a hypothesis, no tdmg "
    "G-code has been printed, and strength is not judged. The strip is itself the "
    "calibration print: what it shows is the owner's judgement after printing (plan "
    "Decision 5).")
REVIEW = (
    "clearance/base.stl and clearance/pieces.stl are the clearance strip; skin/model.3mf "
    "(black base, white patches; palette.json lists the colors) is the skin strip. Print "
    "from Bambu Studio: each slice/ folder's plate_1.gcode is for checking only (tdmg's "
    "G-code is not yet printed or compared with Bambu Studio's own slice). pieces.stl keeps "
    "each piece where its pocket is: piece k (k label holes on the base) is the k-th from "
    "the left; keep them in that order. A G-code kept as plate_1.gcode.failed had a "
    "required check FAIL: do not print it.")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dicts(checks) -> list[dict]:
    return [c.as_dict() for c in checks]


def _gate(body: Body) -> tuple[bytes, trimesh.Trimesh, list[CheckResult]]:
    """A body as the gate reads it, as tdmg.color_checks.ams_checks and glue_checks gate
    each body: its STL bytes, those bytes parsed back and merged exactly, and the R1 mesh
    checks on them (topology_checks, then F2.export_matches_geometry against the Body)."""
    data = encode_stl(body.mesh)
    mesh = merge_exact(trimesh.load(io.BytesIO(data), file_type="stl", process=False))
    return data, mesh, topology_checks(mesh) + [body_export_check(mesh, body)]


def _one_plate(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    """The gated meshes as one, for a plate's F2.fits_build_volume and F5.triangles (as
    ams_checks builds its plate)."""
    offsets = np.cumsum([0] + [len(m.vertices) for m in meshes[:-1]])
    return trimesh.Trimesh(
        np.vstack([np.asarray(m.vertices, dtype=np.float64) for m in meshes]),
        np.vstack([np.asarray(m.faces, dtype=np.int64) + o
                   for m, o in zip(meshes, offsets, strict=True)]),
        process=False, validate=False)


def _reason(check_id: str) -> str:
    if check_id == PORTABILITY:
        return PORTABILITY_NOT_REQUIRED
    if check_id in INFO_CHECK_IDS:
        return INFO_NOTE
    if check_id.startswith("F3.") and f3_note(check_id) == F3_WARNING_NOTE:
        return WARNING_REASON
    raise StripError(f"check {check_id} is neither required nor given a reason for not "
                     "being required")


def not_required_reasons(checks, required) -> dict[str, str]:
    """{check id: why it is not required} for every check (CheckResult or its dict) whose
    id is not in required, sorted by id. StripError for a check with no stated reason, so
    no check is left out of the verdict unexplained."""
    out = {}
    for c in checks:
        cid = c["id"] if isinstance(c, dict) else c.id
        if cid not in required and cid not in out:
            out[cid] = _reason(cid)
    return dict(sorted(out.items()))


def strip_verdict(parts: dict[str, str]) -> tuple[str, str]:
    """(verdict, certification) of a strip from the certification of each of its parts
    (plate or face name -> "PRINTABLE" or "NOT CERTIFIED: <reasons>"): PRINTABLE only if
    every part is, else each part that is not with its reasons, in part order."""
    if not parts:
        return "NOT CERTIFIED", "NOT CERTIFIED: nothing was sliced"
    if all(c == "PRINTABLE" for c in parts.values()):
        return "PRINTABLE", "PRINTABLE"
    reasons = [f"{name}: {c.removeprefix('NOT CERTIFIED: ')}"
               for name, c in parts.items() if c != "PRINTABLE"]
    return "NOT CERTIFIED", "NOT CERTIFIED: " + "; ".join(reasons)


def geometry_identity(clearance: ClearanceStrip, skin: SkinStrip, rules: dict,
                      printer: PrinterProfile) -> dict:
    """What the strips' geometry is made from: the algorithm and the plan, the owner's
    gaps and depths, the layout constants, every rule value the builders use, the printer
    and the grids. Its hash, geometry_id, links palette.json and the plates to it."""
    opening, island = cleaning_params(rules, printer)
    return {
        "algorithm": ALGORITHM, "source": SOURCE, "values_source": OWNER_SOURCE,
        "gaps_mm": list(clearance.gaps_mm), "depths_mm": list(skin.depths_mm),
        "thickness_mm": THICKNESS_MM,
        "layout": {"pocket_side_mm": POCKET_SIDE_MM, "pocket_spacing_mm": POCKET_SPACING_MM,
                   "edge_margin_mm": EDGE_MARGIN_MM, "patch_side_mm": PATCH_SIDE_MM,
                   "patch_spacing_mm": PATCH_SPACING_MM, "pocket_holes": list(POCKET_HOLES),
                   "patch_holes": list(PATCH_HOLES), "holes_per_row": HOLES_PER_ROW,
                   "hole_pitch_mm": HOLE_PITCH_MM, "label_gap_mm": LABEL_GAP_MM,
                   "label_rows": LABEL_ROWS, "hole_segments": HOLE_SEGMENTS},
        "palette": [{"index": i, "hex": h} for i, h in SKIN_PALETTE],
        "printer": printer.id,
        "rules": {r: rules[r].default for r in (SKIN_RULE, MIN_SIDE_RULE, WALL_RULE,
                                                HOLE_RULE)},
        "opening_mm": opening, "min_island_mm2": island,
        "grid_mm": {"clearance": clearance.layout.grid_mm, "skin": skin.layout.grid_mm},
    }


def _pieces_body(strip: ClearanceStrip) -> Body:
    """The six pieces as one body (pieces.stl), each cell with its own piece's z range, in
    gap order and where glue_geometry made it."""
    cells, ranges = [], []
    for piece in strip.pieces:
        for group, z0, z1 in piece.slabs:
            cells += list(group)
            ranges += [(z0, z1)] * len(group)
    try:
        return _body("pieces", CLEARANCE_INLAY_INDEX, cells, ranges, strip.glues[0].grid_mm)
    except ColorGeometryError as e:
        raise StripError(f"the pieces body was refused: {e}") from None


def _plate_stats(stats: dict | None) -> dict:
    keys = ("time_s", "weight_g", "layer_count")
    return {k: (stats or {}).get(k) for k in keys}


def _slice_plate(ctx, name: str, stl_name: str, stl: bytes, mesh: trimesh.Trimesh,
                 previous: list[CheckResult], bodies: int, geometry_id: str,
                 unconfigured: CheckResult) -> dict:
    """One clearance plate as an R1 part (tdmg.slicing.slice_stl), as tdmg.color_slicing
    slices a glue plate, with F4.body_count against bodies and PLATE_REQUIRED."""
    folder = f"{CLEARANCE_DIR}/{SLICE_DIR}/{name}"
    how = (f"bodies in {stl_name} against the strip's own count (plan Decision 1): 1 for "
           f"the base, {GAP_COUNT} for the pieces")
    previous = previous + [_color.glue_body_count_check(stl, bodies, how)]
    part = _slicing.slice_stl(ctx, stl, previous, mesh_summary(mesh), required=PLATE_REQUIRED,
                              model_name=stl_name, source=RECORD_NAME,
                              unconfigured=unconfigured)
    z_min, z_max = part["z"]
    plate_file = f"{CLEARANCE_DIR}/{stl_name}"
    identity = {"algorithm": _slicing.SLICE_ALGORITHM_VERSION,
                "strip_geometry_id": geometry_id, "plate": plate_file,
                "model_stl_sha256": _sha(stl), "slicer": ctx.slicer_identity(),
                "profiles": ctx.profile_hashes(), "command": _slicing.COMMAND_TEMPLATE,
                "f3": ctx.f3_identity(), "required": sorted(PLATE_REQUIRED),
                "expected_bodies": bodies, **part["identity"]}
    files = {f"{folder}/{n}": data for n, data in part["files"].items()}
    rec = part["record"]
    if rec["gcode"] is not None:
        rec["gcode"] = {**rec["gcode"], "file": f"{folder}/{rec['gcode']['file']}"}
    record = {
        "plate": plate_file, "folder": folder,
        "algorithm": _slicing.SLICE_ALGORITHM_VERSION,
        "slice_id": _sha(canonical_json(identity)),
        "model_stl_sha256": _sha(stl),
        "params": {"stl_z_mm": {"min": z_min, "max": z_max, "extent": z_max - z_min},
                   "expected_layer_counts": sorted(part["allowed"])},
        "required_checks": sorted(PLATE_REQUIRED),
        "not_required": not_required_reasons(part["checks"], PLATE_REQUIRED),
        "not_applicable": {TARGET_WIDTH: TARGET_WIDTH_NA},
        "summary": _plate_stats(rec["stats"]),
        "command": _slicing.COMMAND_TEMPLATE, **rec}
    return {"record": record, "files": files}


def _clearance(ctx, strip: ClearanceStrip, printer: PrinterProfile, rules: dict,
               geometry_id: str, unconfigured: CheckResult) -> tuple[dict, dict]:
    """The clearance strip gated, sliced and recorded: (section, files)."""
    pieces = _pieces_body(strip)
    glue = [c for g in strip.glues for c in (glue_partition_check(g), glue_fit_check(g))]
    files, out, plates = {}, {}, {}
    for name, stl_name, body, n in (("base", BASE_STL, strip.base, 1),
                                    ("pieces", PIECES_STL, pieces, GAP_COUNT)):
        stl, mesh, checks = _gate(body)
        checks += [build_volume_check(mesh, printer), triangle_check(mesh, rules)]
        path = f"{CLEARANCE_DIR}/{stl_name}"
        files[path] = stl
        out[name] = {"file": path, "sha256": _sha(stl), **mesh_summary(mesh),
                     "checks": _dicts(checks)}
        done = _slice_plate(ctx, name, stl_name, stl, mesh, checks + glue, n, geometry_id,
                            unconfigured)
        plates[name] = done["record"]
        files.update(done["files"])
    pockets = []
    for k, (gap, piece, pocket) in enumerate(zip(strip.gaps_mm, strip.pieces, strip.pockets,
                                                 strict=True)):
        shape = shapely.union_all(list(piece.parts))
        pockets.append({"pocket": k + 1, "gap_mm": gap, "holes": POCKET_HOLES[k],
                        "pocket_bounds_mm": [float(v) for v in pocket.bounds],
                        "piece_bounds_mm": [float(v) for v in shape.bounds],
                        "measured_gap_mm": float(shapely.distance(shape, pocket.boundary))})
    verdict, cert = strip_verdict({n: p["certification"] for n, p in plates.items()})
    stats = [p["summary"] for p in plates.values()]
    section = {
        "verdict": verdict, "certification": cert,
        "certification_note": STRIP_PRINTABLE_MEANING if verdict == "PRINTABLE" else None,
        "gaps_mm": list(strip.gaps_mm), "pockets": pockets,
        "pieces_layout": ("each piece where glue_geometry made it, in its pocket's place: "
                          "left to right in gap order, at the pocket pitch "
                          "(POCKET_SIDE_MM + POCKET_SPACING_MM; plan Task 2 amendment)"),
        "files": out,
        "glue": [{"gap_mm": g.clearance_mm, "report": g.report} for g in strip.glues],
        "glue_checks": _dicts(glue),
        "plates": plates,
        "summary": {"time_s": _total(s["time_s"] for s in stats),
                    "weight_g": _total(s["weight_g"] for s in stats)},
    }
    return section, files


def _total(values) -> float | None:
    values = list(values)
    return None if any(v is None for v in values) else float(sum(values))


def _patches(strip: SkinStrip) -> list[dict]:
    numbers = [i + 1 for i, k in enumerate(PATCH_HOLES) if k]
    depth = dict(zip(numbers, strip.depths_mm, strict=True))
    out = []
    for i, holes in enumerate(PATCH_HOLES):
        n = i + 1
        d = THICKNESS_MM if n == FULL_PATCH else depth.get(n)
        out.append({"patch": n, "holes": holes, "depth_mm": d,
                    "white": d is not None,
                    "role": ("black only (reference)" if d is None else
                             "full white (reference)" if n == FULL_PATCH else
                             "white over black")})
    return out


def _skin(ctx, strip: SkinStrip, printer: PrinterProfile, rules: dict, geometry_id: str,
          unconfigured: CheckResult) -> tuple[dict, dict, dict]:
    """The skin strip gated, written as model.3mf and palette.json, sliced face up and
    recorded: (section, files, the face's part of strip_id)."""
    hexes = dict(SKIN_PALETTE)
    bodies = [strip.base, strip.white]
    rows, shells, meshes = [], [], []
    for body in bodies:
        _, mesh, checks = _gate(body)
        role = "base" if body.index == SKIN_BASE_INDEX else "inlay"
        name = body_file(SKIN_ROUTE, body.index, hexes[body.index],
                         SKIN_BASE_INDEX).removesuffix(".stl")
        shells.append(Shell(name, role, body.index, hexes[body.index], mesh.vertices,
                            mesh.faces))
        meshes.append(mesh)
        rows.append({"name": name, "role": role, "index": body.index,
                     "hex": hexes[body.index], **mesh_summary(mesh),
                     "top_area_mm2": float(sum(c.area for c in strip.cells.of(body.index))),
                     "checks": checks})
    try:
        model_3mf = write_multishell_3mf(shells)
        palette = palette_manifest(shells, model_3mf, link={"strip_geometry_id": geometry_id},
                                   top_area_mm2=[r["top_area_mm2"] for r in rows],
                                   volume_mm3=[r["volume_mm3"] for r in rows])
    except ThreeMFError as e:
        raise StripError(f"the skin strip's model.3mf cannot be written: {e}") from None
    model_check = export_3mf_check(model_3mf, shells)
    plate = _one_plate(meshes)
    assembly = [color_partition_check(strip.cells, bodies, THICKNESS_MM),
                filaments_check(bodies, colors=len(SKIN_PALETTE),
                                palette_cap=palette_cap(printer)),
                build_volume_check(plate, printer), triangle_check(plate, rules), model_check]
    inherited = [c for r in rows for c in r["checks"]] + assembly

    fmap = _color.filament_map(shells)
    filaments = _color.filament_profiles(ctx.profile_data["filament"], fmap)
    allowed = _color.allowed_counts(shells, ctx.process)
    done = _color.slice_face(ctx, SKIN_FACE, shells, filaments, inherited,
                             SKIN_INHERITED_REQUIRED, unconfigured, allowed,
                             portability_required=False)
    prefix = f"{SKIN_DIR}/{SLICE_DIR}/"
    face = done["record"]
    face["orca_input"] = {**face["orca_input"], "file": prefix + face["orca_input"]["file"]}
    if face["gcode"] is not None:
        face["gcode"] = {**face["gcode"], "file": prefix + face["gcode"]["file"]}
    files = {f"{SKIN_DIR}/{MODEL_3MF}": model_3mf, f"{SKIN_DIR}/{PALETTE_NAME}": palette,
             **{prefix + f["file"]: f["bytes"] for f in filaments},
             **{prefix + n: data for n, data in done["files"].items()}}
    required = set(face["required_checks"])
    verdict, cert = strip_verdict({face["folder"]: face["certification"]})
    section = {
        "verdict": verdict, "certification": cert,
        "certification_note": STRIP_PRINTABLE_MEANING if verdict == "PRINTABLE" else None,
        "depths_mm": list(strip.depths_mm), "patches": _patches(strip),
        "palette": [{"index": i, "hex": h,
                     "role": "base" if i == SKIN_BASE_INDEX else "patches"}
                    for i, h in SKIN_PALETTE],
        "model_3mf": {"file": f"{SKIN_DIR}/{MODEL_3MF}", "sha256": _sha(model_3mf),
                      "check": model_check.as_dict(),
                      "note": "the file to print from: open it in Bambu Studio and give "
                              "each color the filament in filament_map"},
        "palette_json": {"file": f"{SKIN_DIR}/{PALETTE_NAME}", "sha256": _sha(palette)},
        "bodies": [{**r, "checks": _dicts(r["checks"])} for r in rows],
        "assembly": _dicts(assembly),
        "required_checks": sorted(required),
        "not_required": not_required_reasons(face["checks"], required),
        "filament_map": fmap,
        "filaments": {"note": _color.FILAMENT_NOTE,
                      "pinned_sha256": _sha(ctx.profile_data["filament"]),
                      "profiles": [{**{k: v for k, v in f.items() if k != "bytes"},
                                    "file": prefix + f["file"]} for f in filaments]},
        "command": _color.command_template(len(shells)),
        "face": face,
        "summary": {**face["summary"],
                    "weight_g": _plate_stats(face["stats"])["weight_g"]},
    }
    identity = {"orca_input_sha256": done["identity"]["orca_input_sha256"],
                "filaments": [f["sha256"] for f in filaments],
                "command": section["command"]}
    return section, files, identity


def make_strips(out_dir, slicer_dir=None, timeout_s=None, check_tree: bool = True) -> dict:
    """Build, gate and slice both strips with the owner's values (OWNER_GAPS_MM,
    OWNER_DEPTHS_MM) and write, in out_dir: clearance/ (base.stl, pieces.stl, slice/base/
    and slice/pieces/ with each plate's G-code, statistics and log when written), skin/
    (model.3mf, palette.json, slice/ with the filament profiles and face-up/) and
    strip.json last. Returns the record as written.

    Refused with SlicerError and nothing written, as tdmg slice refuses: a timeout_s that
    is not a number above 0; an out_dir that is a file or a non-empty folder; an OrcaSlicer
    that is missing or does not verify against the pin (slicer_dir, else
    $TDMG_ORCASLICER_DIR). check_tree False skips the app-tree check and caps every
    verdict at NOT CERTIFIED. A check that FAILs still writes everything, with that
    part's G-code quarantined (plate_1.gcode.failed). PrusaSlicer is never run
    (PORTABILITY_NOT_REQUIRED).

    strip_id is the SHA-256 of the canonical JSON of: the algorithm, geometry_id (the
    hash of geometry_identity), the hashes of base.stl, pieces.stl, model.3mf and
    palette.json, the pinned slicer and profiles as tdmg.slicing names them, the F3
    inputs, each plate's slice_id, and the face's orca-input.3mf hash, filament profile
    hashes and command. The timeouts, the environment and the platform are recorded
    beside it, not in it.
    """
    rules = load_rules()
    _slicing._timeout(timeout_s, rules)                # refused before anything else
    try:
        create_folder = check_output_dir(out_dir)
    except RecordError as err:
        raise SlicerError(str(err)) from None
    printer = load_printer(PRINTER_ID)
    clearance = clearance_strip(OWNER_GAPS_MM, rules=rules, printer=printer)
    skin = skin_strip(OWNER_DEPTHS_MM, rules=rules)
    geometry = geometry_identity(clearance, skin, rules, printer)
    geometry_id = _sha(canonical_json(geometry))
    ctx = _slicing.prepare(slicer_dir, timeout_s, check_tree, None, portability=False)
    unconfigured = CheckResult(PORTABILITY, "UNKNOWN", None, None, None,
                               PORTABILITY_NOT_REQUIRED)

    cl_section, cl_files = _clearance(ctx, clearance, printer, rules, geometry_id,
                                      unconfigured)
    sk_section, sk_files, sk_identity = _skin(ctx, skin, printer, rules, geometry_id,
                                              unconfigured)
    files = {**cl_files, **sk_files}
    made = (f"{CLEARANCE_DIR}/{BASE_STL}", f"{CLEARANCE_DIR}/{PIECES_STL}",
            f"{SKIN_DIR}/{MODEL_3MF}", f"{SKIN_DIR}/{PALETTE_NAME}")
    identity = {"algorithm": ALGORITHM, "geometry_id": geometry_id,
                "files": {name: _sha(files[name]) for name in made},
                "slicer": ctx.slicer_identity(), "profiles": ctx.profile_hashes(),
                "f3": ctx.f3_identity(),
                "plates": {n: p["slice_id"] for n, p in cl_section["plates"].items()},
                "skin_face": sk_identity}
    record = {
        "schema": RECORD_SCHEMA, "tdmg_version": __version__, "algorithm": ALGORITHM,
        "strip_id": _sha(canonical_json(identity)),
        "source": SOURCE,
        "geometry_id": geometry_id, "geometry": geometry,
        "params": {"timeout_s": ctx.timeout, "check_tree": check_tree},
        "slicer": ctx.slicer_record(),
        "portability": {"run": False, "reason": PORTABILITY_NOT_REQUIRED},
        "clearance": cl_section,
        "skin": sk_section,
        "verdicts": {"clearance": cl_section["verdict"], "skin": sk_section["verdict"]},
        "outputs": {name: _sha(data) for name, data in files.items()},
        "environment": {**colored_environment(), "platform": platform.platform()},
        "review": REVIEW,
    }
    try:
        data = record_text(record)
    except (ValueError, UnicodeEncodeError) as err:
        raise SlicerError(f"the record cannot be stored as strict JSON: {err}") from None
    try:
        write_outputs(out_dir, files, RECORD_NAME, data, create_folder=create_folder,
                      subfolders=FOLDER_LEVELS)
    except RecordError as err:
        raise SlicerError(str(err)) from None
    return json.loads(data)

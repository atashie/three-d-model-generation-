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

Pure: no I/O. Task 2 gates, writes and slices the strips.
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from itertools import combinations, pairwise

import numpy as np
import shapely
from shapely.geometry import Polygon

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
from tdmg.flat import QUAD_SEGS, cleaning_params
from tdmg.profiles import PrinterProfile, load_printer

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

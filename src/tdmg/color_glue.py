"""Glue-route geometry for colored flat prints (R2 step 2, Task 5).

docs/plans/2026-11-12-color-geometry.md, Decisions 6 (glue base and pieces), 7 (the glue
rules) and 8 (fold the tiny regions, then shrink; with the owner's amendment "Fold small
pieces too"). The glue route prints a base of the base color with a pocket of depth d
(color.skin.depth_mm) for every glue piece, and each inlay color as separate flat pieces
of thickness d that are glued into the pockets.

Steps, on color_cells' labelled cells (the storage grid G, pinch-free):
1. Candidates: the connected components of each inlay label's cells. Two cells are
   connected when they share an edge; color_cells' cells share edges exactly (one
   polygonization), so this is exact. (Same-label cells meeting only at a vertex are
   pinches, which color_cells has joined.)
2. Shrink and clean: a candidate's region buffered by -clearance (round joins,
   tdmg.flat.QUAD_SEGS), then the R1 opening (flat.sliver.opening_width) and island rule
   (tdmg.flat.open_parts, the same code as tdmg.flat.clean). The result is the
   candidate's pieces.
3. Fold: repeatedly, smallest first, a candidate none of whose pieces reaches
   (color.glue.min_piece_side_mm)^2 is relabelled to the neighbour with the longest
   shared boundary, then the components are recomputed (a fold can merge candidates),
   until nothing folds. Folding into the base removes the pocket.
4. Small pieces and pockets (the amendment), once per remaining candidate: only its
   pieces of at least the min-piece area are kept. The leftover is the candidate minus
   the kept pieces buffered by the clearance (round joins), cleaned with the R1 opening
   and island rule; it becomes base color (thin bands, the dropped small pieces), so no
   pocket is left without a piece. The pocket is the parts of the candidate minus the
   leftover that hold a kept piece; parts that hold none (the cusps at the leftover's
   rounded corners) join the leftover.
5. Rebuild: the pockets (labelled by color) and the base (the gridded S minus the
   pockets) go through tdmg.color_geometry.color_cells again: one snap-rounded noding
   on the storage grid, plurality labels and pinch joining. The glue base and the
   pockets are these cells.
6. Bodies: the glue base (base-labelled cells over [0, T], pocket cells over [0, T - d]);
   per inlay color one body of its kept pieces over [0, d], snapped to the rebuilt
   cells' grid (shapely.set_precision, once per candidate), at their model x, y.

Pure: no I/O. tdmg.color_checks.glue_checks gates the result (F4.glue_fit among them).
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from itertools import pairwise

import shapely
from shapely.geometry import Polygon

from tdmg.color_geometry import (
    Body,
    Cells,
    ColorGeometryError,
    ColorRegions,
    _body,
    _polygonal,
    _positive,
    color_cells,
)
from tdmg.flat import QUAD_SEGS, open_parts, order_key


class GlueError(ColorGeometryError):
    """Invalid input to the glue geometry."""


@dataclass(frozen=True, eq=False)
class Pocket:
    """One pocket of the glue base: an edge-connected component of one color's rebuilt
    cells.

    number: 1.. in order (by color index, then tdmg.flat.order_key of the pocket).
    index: its color. cells: the indices of its cells in Glue.cells.cells. polygon: the
    union of those cells (on the grid). pieces: the numbers of the pieces in it.
    """

    number: int
    index: int
    cells: tuple[int, ...]
    polygon: Polygon
    pieces: tuple[int, ...]


@dataclass(frozen=True, eq=False)
class Piece:
    """One glue piece: number 1.., color index, its polygon on the grid, and the number
    of its pocket (0 if it meets none, which F4.glue_fit FAILs)."""

    number: int
    index: int
    polygon: Polygon
    pocket: int


@dataclass(frozen=True, eq=False)
class Glue:
    """The glue route's geometry.

    grid_mm: G of the rebuilt cells. base_index: the base color. cells: the rebuilt Cells
    (color_cells of the pockets and the base; their report has the grid shift and the
    pinch joins). pockets, pieces: as above. bodies: the glue base first (name "base"),
    then one body per color with pieces (name f"color-{index}"), by index. clearance_mm,
    opening_mm, skin_mm, thickness_mm: the values used. report: JSON-safe; see
    glue_geometry.
    """

    grid_mm: float
    base_index: int
    cells: Cells
    pockets: tuple[Pocket, ...]
    pieces: tuple[Piece, ...]
    bodies: tuple[Body, ...]
    clearance_mm: float
    opening_mm: float
    skin_mm: float
    thickness_mm: float
    report: dict


def _number(name: str, value, *, zero_ok: bool = False) -> float:
    if not zero_ok:
        try:
            return _positive(name, value)
        except ColorGeometryError as exc:
            raise GlueError(str(exc)) from None
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise GlueError(f"{name} must be a number, got {value!r}")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise GlueError(f"{name} must be a finite number of at least 0, got {value}")
    return value


def _edge_lengths(cells) -> list[dict]:
    """Per cell k: {neighbour cell j or None (outside S): total shared edge length}.

    Directed edges come from the oriented rings (cell on the left); the neighbour across
    an edge is the cell with the reversed edge, found exactly because the cells share
    their vertices. Lengths are summed with math.fsum (correctly rounded, so the result
    does not depend on the order of the edges).
    """
    edges: dict[tuple, int] = {}
    rings = []
    for k, cell in enumerate(cells):
        oriented = shapely.orient_polygons(cell)
        for ring in (oriented.exterior, *oriented.interiors):
            xy = [tuple(v) for v in shapely.get_coordinates(ring).tolist()]
            for p, q in pairwise(xy):
                edges[(p, q)] = k
                rings.append((k, p, q))
    parts: list[dict] = [{} for _ in cells]
    for k, p, q in rings:
        parts[k].setdefault(edges.get((q, p)), []).append(math.dist(p, q))
    return [{j: math.fsum(v) for j, v in d.items()} for d in parts]


def _components(adjacent: list[dict], labels: list[int], base: int) -> list[tuple]:
    """The edge-connected components of each non-base label: [(label, cells tuple)]."""
    seen: set[int] = set()
    out = []
    for start, label in enumerate(labels):
        if label == base or start in seen:
            continue
        stack, comp = [start], []
        seen.add(start)
        while stack:
            k = stack.pop()
            comp.append(k)
            for j in adjacent[k]:
                if j is not None and j not in seen and labels[j] == label:
                    seen.add(j)
                    stack.append(j)
        out.append((label, tuple(sorted(comp))))
    return out


def _neighbours(comp: tuple[int, ...], label: int, adjacent: list[dict],
                labels: list[int]) -> dict[int, float]:
    """Shared boundary length per neighbouring label (outside S is not a neighbour)."""
    found: dict[int, list[float]] = {}
    for k in comp:
        for j, length in adjacent[k].items():
            if j is not None and labels[j] != label:
                found.setdefault(labels[j], []).append(length)
    return {c: math.fsum(v) for c, v in found.items()}


def _target(neighbours: dict[int, float], base: int) -> tuple[int, float]:
    """The longest shared boundary; ties to the lowest color index, then the base.

    With no neighbour at all (a part of S of one inlay color only), the base, length 0.
    """
    if not neighbours:
        return base, 0.0
    # Ties compare the fsum'd lengths with exact float equality. Exact for axis-aligned
    # grid edges (sums of multiples of G); for oblique edges, equal true lengths can differ
    # by an ulp, which then breaks the tie, deterministically, by length.
    best = min(neighbours.items(), key=lambda kv: (-kv[1], kv[0] == base, kv[0]))
    return best


def _fold(cells, labels: list[int], base: int, shrink, min_area: float) -> list[dict]:
    """Fold candidates in place (labels is changed), smallest first; returns the folds.

    A candidate folds when none of its pieces reaches min_area. Smallest first means by
    the total area of its pieces, then the lower label, then tdmg.flat.order_key of its
    region.
    """
    adjacent = _edge_lengths(cells)
    folds = []
    while True:
        small = []
        for label, comp in _components(adjacent, labels, base):
            region, parts = shrink(label, comp)
            largest = max((float(p.area) for p in parts), default=0.0)
            if largest < min_area:
                area = float(sum(p.area for p in parts))
                small.append((area, label, order_key(region), comp, region, largest))
        if not small:
            return folds
        area, label, _, comp, region, largest = min(small, key=lambda t: t[:3])
        neighbours = _neighbours(comp, label, adjacent, labels)
        into, shared = _target(neighbours, base)
        pieces = len(shrink(label, comp)[1])
        for k in comp:
            labels[k] = into
        folds.append({"label": label, "area_mm2": area, "largest_piece_mm2": largest,
                      "pieces": pieces, "region_area_mm2": float(region.area),
                      "cells": len(comp), "into": into, "into_base": into == base,
                      "shared_mm": shared,
                      "neighbours": [[c, neighbours[c]] for c in sorted(neighbours)]})


def glue_geometry(cells: Cells, *, thickness_mm, skin_mm, clearance_mm, min_piece_side_mm,
                  opening_mm, min_island_mm2) -> Glue:
    """The glue base, pockets and pieces from color_cells' cells.

    cells: color_cells' result (pinch-free). thickness_mm T > skin_mm d > 0 (d is the
    pocket depth and the piece thickness: color.skin.depth_mm); clearance_mm c > 0
    (color.glue.clearance_mm); min_piece_side_mm > 0 (color.glue.min_piece_side_mm: the
    min-piece area is its square); opening_mm > 0 (flat.sliver.opening_width) and
    min_island_mm2 >= 0 ((flat.island.min_square_side x nozzle)^2): the R1 cleaning
    applied to each shrunk candidate. All finite, bools refused; GlueError names the bad
    argument. The steps are the module docstring's.

    Shrinking: a piece comes from the candidate region R buffered by -c with round joins.
    The exact inward offset is {x in R : dist(x, boundary of R) >= c}, so every point of
    the piece is at least c from R's boundary, at convex and concave corners alike
    (convex corners stay sharp; around each concave corner the piece follows a circle of
    radius c). GEOS draws that circle as QUAD_SEGS chords per quarter turn with their
    ends on it, and a chord's middle is closer to the corner, at c cos(pi / (4
    QUAD_SEGS)). So the gap to R's boundary is >= c everywhere except at concave corners,
    where it can be short by that chord error, c (1 - cos(pi / (4 QUAD_SEGS))), about
    0.001 mm at c = 0.2 mm. The opening that follows only removes material (it rounds the
    piece's convex corners to radius opening_mm / 2 and cuts necks), apart from its own
    chord error. Where the pocket's wall is the kept pieces' outward buffer by c instead,
    it is c from the piece less that buffer's chord error, at most the same c (1 - cos(pi
    / (4 QUAD_SEGS))), and the leftover's opening can reach past that buffer by its own
    chord error, (opening_mm / 2) (1 - cos(pi / (4 QUAD_SEGS))).
    tdmg.color_checks.glue_fit_margin adds these and the snaps.

    Leftovers (deviation from the amendment's wording, which made the pocket the
    candidate intersected with the buffer): candidate minus buffer, uncleaned, is
    thousands of specks on the owner's plans (1,867 to 2,971 parts per plan, most below
    0.01 mm^2: the fine map's staircase teeth and the cusps at rounded corners, which
    the clearance band cannot reach), and rebuilding the cells from them left base
    pinches color_cells could not join (154 after 4 rounds on Roadie drop). So the
    leftover gets the R1 rules every printed region gets (flat.sliver.opening_width,
    the island area): parts narrower than the opening or smaller than the island stay
    in the pocket, as uncovered area that the glue fills.

    Folding (step 3): ties as in _fold; the target is the neighbouring label with the
    longest shared cell-edge length (outside S does not count), ties to the lowest color
    index, then the base; with no neighbour, the base. Each fold leaves one candidate
    fewer, so this ends.

    report: {"grid_mm", "clearance_mm", "min_piece_area_mm2", "opening_mm",
    "min_island_mm2", "folds": [per fold, in order: {"label", "area_mm2" (its pieces'
    total), "largest_piece_mm2", "pieces", "region_area_mm2" (unshrunk), "cells", "into",
    "into_base", "shared_mm", "neighbours": [[label, shared length], ...]}],
    "leftover": [per color with a remaining candidate: {"index", "candidates",
    "candidate_area_mm2", "pocket_area_mm2", "leftover_mm2" (to the base),
    "small_pieces" (dropped, below the min-piece area), "small_pieces_mm2"}],
    "leftover_mm2" (total), "rebuild" (the rebuilt cells' report: grid shift, pinch
    joins), "silhouette_pinches", "pockets": [{"number", "index", "area_mm2", "pieces",
    "uncovered_mm2"}], "pieces": [{"number", "index", "area_mm2", "point_on_surface",
    "pocket", "pocket_area_mm2"}], "colors": [per color with pieces: {"index",
    "pockets", "pieces", "area_mm2", "smallest_mm2", "largest_mm2"}], "uncovered_mm2",
    "empty_pockets"}. The areas are before the rebuild except the pockets' and pieces'.
    uncovered_mm2 (per pocket and in total, information): area(pocket - union(its
    pieces).buffer(c, round joins)): what the leftover's cleaning kept in the pocket. It
    includes each convex corner the opening and the buffer round to r + c (r =
    opening_mm / 2): at a corner of angle theta, (r + c)^2 (cot(theta/2) - (pi -
    theta)/2), so (4 - pi) (r + c)^2 for a square; the staircase teeth; and leftover
    parts narrower than the opening. empty_pockets counts pockets with no piece
    (F4.glue_fit FAILs them).
    """
    if not isinstance(cells, Cells):
        raise GlueError(f"cells must be a tdmg.color_geometry.Cells, got "
                        f"{type(cells).__name__}")
    t = _number("thickness_mm", thickness_mm)
    d = _number("skin_mm", skin_mm)
    c = _number("clearance_mm", clearance_mm)
    side = _number("min_piece_side_mm", min_piece_side_mm)
    opening = _number("opening_mm", opening_mm)
    min_island = _number("min_island_mm2", min_island_mm2, zero_ok=True)
    if t <= d:
        raise GlueError(f"thickness_mm ({t}) must be above skin_mm ({d}): the pockets "
                        "need a floor")
    if not cells.cells:
        raise GlueError("cells has no cells")
    base = cells.base_index
    min_area = side * side
    cell_list = list(cells.cells)
    labels = list(cells.labels)
    cache: dict[tuple, tuple] = {}

    def shrink(label, comp):
        key = (label, comp)
        if key not in cache:
            region = shapely.union_all([cell_list[k] for k in comp])
            shrunk = region.buffer(-c, quad_segs=QUAD_SEGS)
            _, parts, _ = open_parts(shrunk, opening, min_island)
            cache[key] = (region, parts)
        return cache[key]

    folds = _fold(cell_list, labels, base, shrink, min_area)

    # Step 4: kept pieces, pockets and leftovers, once per remaining candidate.
    inlays: dict[int, list[Polygon]] = {}
    kept_pieces: list[tuple[int, list[Polygon]]] = []  # per candidate
    leftover: dict[int, dict] = {}
    for label, comp in _components(_edge_lengths(cell_list), labels, base):
        region, parts = shrink(label, comp)
        kept = [p for p in parts if p.area >= min_area]
        small = [p for p in parts if p.area < min_area]
        if not kept:  # _fold leaves no such candidate; refuse rather than build on it
            raise GlueError(f"a color {label} candidate of {region.area:.6g} mm^2 has no "
                            f"piece of at least {min_area:.6g} mm^2 after folding")
        # The leftover is what the kept pieces' clearance band does not reach, cleaned
        # with the R1 rules (see the docstring, "Leftovers"); the pocket is the rest of
        # the candidate.
        kept_union = shapely.union_all(kept)
        reach = kept_union.buffer(c, quad_segs=QUAD_SEGS)
        _, rest_parts, _ = open_parts(shapely.difference(region, reach), opening,
                                      min_island)
        remain = _polygonal(shapely.difference(region, shapely.union_all(rest_parts))
                            if rest_parts else region)
        # Parts with no kept piece (the cusps at a leftover's rounded corners, or bits
        # cut off by it) would be empty pockets: they go to the base with the leftover.
        polys = [q for q in remain if q.intersects(kept_union)]
        inlays.setdefault(label, []).extend(polys)
        kept_pieces.append((label, kept))
        row = leftover.setdefault(label, {
            "index": label, "candidates": 0, "candidate_area_mm2": 0.0,
            "pocket_area_mm2": 0.0, "leftover_mm2": 0.0, "small_pieces": 0,
            "small_pieces_mm2": 0.0})
        pocket_area = float(sum(p.area for p in polys))
        row["candidates"] += 1
        row["candidate_area_mm2"] += float(region.area)
        row["pocket_area_mm2"] += pocket_area
        row["leftover_mm2"] += float(region.area) - pocket_area
        row["small_pieces"] += len(small)
        row["small_pieces_mm2"] += float(sum(p.area for p in small))
    inlays = {k: sorted(v, key=order_key) for k, v in sorted(inlays.items()) if v}

    # Step 5: rebuild the cells from the pockets and the base (the rest of the gridded S).
    s_grid = cells.silhouette
    all_pockets = [p for v in inlays.values() for p in v]
    rest = shapely.difference(s_grid, shapely.union_all(all_pockets)) if all_pockets \
        else s_grid
    base_top = sorted(_polygonal(rest), key=order_key)
    rebuilt = color_cells(ColorRegions(inlays, base_top, {}, []), s_grid, base)
    grid = rebuilt.grid_mm
    new_cells, new_labels = list(rebuilt.cells), list(rebuilt.labels)
    comps = []
    for label, comp in _components(_edge_lengths(new_cells), new_labels, base):
        region = shapely.union_all([new_cells[k] for k in comp])
        comps.append((label, order_key(region), comp, region))
    comps.sort(key=lambda b: (b[0], b[1]))

    # Step 6: pieces on the grid, each assigned to the pocket of its color it meets. A
    # candidate's kept pieces are snapped together (one set_precision of their union), so
    # two close pieces are noded once and cannot be snapped into overlap.
    snapped: list[tuple[int, Polygon]] = []
    for label, kept in kept_pieces:
        together = shapely.set_precision(shapely.union_all(kept), grid)
        snapped += [(label, q) for q in sorted(_polygonal(together), key=order_key)]
    owner: dict[int, int] = {}
    for i, (label, q) in enumerate(snapped):
        for number, (k, _, _, region) in enumerate(comps, start=1):
            if k == label and region.intersects(q):
                owner[i] = number
                break
    ordered = sorted(range(len(snapped)), key=lambda i: (
        snapped[i][0], owner.get(i, 0), order_key(snapped[i][1])))
    pieces: list[Piece] = []
    piece_rows = []
    for i in ordered:
        label, q = snapped[i]
        piece = Piece(len(pieces) + 1, label, q, owner.get(i, 0))
        pieces.append(piece)
        point = shapely.point_on_surface(q)
        area = float(comps[piece.pocket - 1][3].area) if piece.pocket else 0.0
        piece_rows.append({"number": piece.number, "index": label,
                           "area_mm2": float(q.area),
                           "point_on_surface": [float(point.x), float(point.y)],
                           "pocket": piece.pocket, "pocket_area_mm2": area})
    pockets, pocket_rows = [], []
    for number, (label, _, comp, region) in enumerate(comps, start=1):
        mine = [p for p in pieces if p.pocket == number]
        reach = (shapely.union_all([p.polygon for p in mine]).buffer(c, quad_segs=QUAD_SEGS)
                 if mine else Polygon())
        pockets.append(Pocket(number, label, comp, region, tuple(p.number for p in mine)))
        pocket_rows.append({"number": number, "index": label,
                            "area_mm2": float(region.area),
                            "pieces": [p.number for p in mine],
                            "uncovered_mm2": float(shapely.difference(region, reach).area)})

    ranges = [(0.0, t if k == base else t - d) for k in new_labels]
    bodies = [_body("base", base, new_cells, ranges, grid)]
    colors = []
    for index in sorted({p.index for p in pieces}):
        polys = [p.polygon for p in pieces if p.index == index]
        bodies.append(_body(f"color-{index}", index, polys, [(0.0, d)] * len(polys), grid))
        areas = [float(p.area) for p in polys]
        colors.append({"index": index,
                       "pockets": sum(1 for p in pockets if p.index == index),
                       "pieces": len(polys), "area_mm2": float(sum(areas)),
                       "smallest_mm2": min(areas), "largest_mm2": max(areas)})
    rows = [leftover[k] for k in sorted(leftover)]
    report = {"grid_mm": grid, "clearance_mm": c, "min_piece_area_mm2": min_area,
              "opening_mm": opening, "min_island_mm2": min_island, "folds": folds,
              "leftover": rows,
              "leftover_mm2": float(sum(r["leftover_mm2"] for r in rows)),
              "rebuild": rebuilt.report,
              "silhouette_pinches": rebuilt.report["pinches"]["silhouette_pinches"],
              "pockets": pocket_rows, "pieces": piece_rows, "colors": colors,
              "uncovered_mm2": float(sum(r["uncovered_mm2"] for r in pocket_rows)),
              "empty_pockets": sum(1 for p in pockets if not p.pieces)}
    return Glue(grid, base, rebuilt, tuple(pockets), tuple(pieces), tuple(bodies), c,
                opening, d, t, report)

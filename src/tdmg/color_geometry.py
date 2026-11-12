"""Per-color regions in model mm for colored flat geometry (R2 step 2).

docs/plans/2026-11-12-color-geometry.md, Decisions 3-5 (with the amendments after Task 1
and after the Task 3 quality review):

- Decision 3: each color c of the fine label map (tdmg.smoothing.smooth_labels) is
  vectorized as mask_outline(fine == c) scaled by 1/s about the origin, which puts it in
  the pixel-cell coordinates of tdmg.flat (x right, y down, image pixel (column x, row y)
  the cell [x, x + 1] x [y, y + 1]). tdmg.flat.apply_transform then takes it to model mm
  (x_mm = (x - x0) * scale, y_mm = (y1 - y) * scale), and it is clipped to the silhouette
  S. Task 1 measured plain float64 overlays on the approved plans (zero overlap, gaps of
  at most 7e-12 mm^2), so there is no simplification, no fixed grid and no coverage
  function here.
- Decision 4: every palette color except the base is an inlay; the base's top is S minus
  the union of the inlays, which is the base color's own fine region inside S, to
  float64 rounding.
- Decision 5, as replaced by the owner's decision ("Match preview", 2026-11-12): the
  inlays are not cleaned. Opening each color on its own and giving the trimmings to the
  base drew base-colored hairlines between touching colors (1.0-21.3 mm^2 on the four
  approved plans). So each inlay is exactly its fine region clipped to S, as in the
  approved preview. Parts narrower than the width the caller passes
  (flat.sliver.opening_width) are only reported, with tdmg.flat.thin_regions; the slicer
  checks in step 4 judge whether they print.

- Decision 6 (AMS, as amended during Task 4): color_cells puts S and the regions on the
  float32 storage grid (storage_grid_mm) and cuts S into labelled cells; ams_bodies meshes
  the base body and one inlay body per color directly from the cells (prism_mesh), face
  up, with no 3-D boolean.

Pure: no I/O, no record. The caller builds S (the cleaned R1 silhouette) and passes the
rule values.
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from functools import cmp_to_key
from itertools import pairwise

import numpy as np
import shapely
import trimesh
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon

from tdmg.flat import (
    apply_transform,
    mask_outline,
    order_key,
    polygon_parts,
    thin_regions,
)
from tdmg.smoothing import SmoothingError, check_supersample

STATUSES = ("inlay", "vanished_in_fine", "outside_silhouette")
# Float64 overlay rounding: each overlay vertex is taken to be within
# ULPS x eps x max|coordinate| of its exact position (vertex_dist). ULPS is a stated margin
# over the worst measured in tests/test_color_geometry.py (0.28 eps x max|coordinate|,
# Shapely 2.2.0 / GEOS 3.14.1, 2026-11-12), the same constant as that test's. That
# measurement is of color_regions' clipping overlay; F4.color_partition applies the bound
# to other overlays: unions, differences and pairwise intersections of the raw pieces and
# S, and of the cells. Measured for those (2026-11-12, same versions, box, circle,
# checker and kron test cases and the four approved plans, 14 to 53,635 output vertices
# each): every output vertex lies on an input boundary segment to within 0 x eps x
# max|coordinate|, since the pieces already share their vertices. A rounding bound, not a
# rule.
ULPS = 4
EPS = float(np.finfo(float).eps)
TRANSFORM_KEYS = ("scale_mm_per_px", "x0_px", "y1_px")  # what apply_transform reads


class ColorGeometryError(ValueError):
    """Invalid input to the color geometry. Nothing is built."""


@dataclass(frozen=True, eq=False)
class ColorRegions:
    """Per-color polygons in model mm, expected to partition S to float64 rounding.

    Not checked here: the tests assert it, and tdmg.color_checks.color_partition_check
    (F4.color_partition) gates it.

    inlays: palette index -> its fine region clipped to S, as polygons sorted by
      tdmg.flat.order_key, only for colors with area inside S; never the base.
    base_top: the polygons of S minus the union of all inlay polygons, sorted the same
      way.
    report: JSON-safe; see color_regions.
    warnings: one line per non-inlay color, and one if the base is not in the fine map.
    """

    inlays: dict[int, list[Polygon]]
    base_top: list[Polygon]
    report: dict
    warnings: list[str]


def _supersample(value) -> int:
    try:
        return check_supersample(value)
    except SmoothingError as exc:
        raise ColorGeometryError(str(exc)) from None


def _fine(fine) -> np.ndarray:
    a = np.asarray(fine)
    if a.ndim != 2:
        raise ColorGeometryError(f"fine must be two-dimensional, got shape {a.shape}")
    if a.dtype == np.bool_ or not np.issubdtype(a.dtype, np.integer):
        raise ColorGeometryError(f"fine must be an integer array, got {a.dtype}")
    if a.size == 0:
        raise ColorGeometryError(f"fine is empty (shape {a.shape})")
    if int(a.min()) < 0:
        raise ColorGeometryError(f"fine labels must be palette indices of at least 0, "
                                 f"got {int(a.min())}")
    return a


def fine_regions_px(fine, supersample, labels=None) -> dict[int, shapely.Geometry]:
    """Each label's region of the fine map, in image pixel units.

    fine: a 2-D integer array (bool refused) of palette indices (>= 0), as
    smooth_labels returns. supersample: its factor s, an int >= 1 (bool refused).
    labels: the labels to vectorize (ints >= 0, bool refused), or None for all. For each
    of them present in fine, in ascending order: mask_outline(fine == c) scaled by 1/s
    about the origin (fine pixel (row i, column j) is the cell [j/s, (j+1)/s] x
    [i/s, (i+1)/s]). Keys are Python ints.
    """
    a = _fine(fine)
    s = _supersample(supersample)
    present = [int(c) for c in np.unique(a)]
    if labels is not None:
        wanted = {_int("labels", c, 0) for c in labels}
        present = [c for c in present if c in wanted]
    return {c: affinity.scale(mask_outline(a == c), 1 / s, 1 / s, origin=(0, 0))
            for c in present}


def _int(name: str, value, low: int, high: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ColorGeometryError(f"{name} must be an integer, got {value!r}")
    value = int(value)
    if value < low or (high is not None and value >= high):
        bound = f"in [{low}, {high})" if high is not None else f"at least {low}"
        raise ColorGeometryError(f"{name} must be {bound}, got {value}")
    return value


def _positive(name: str, value) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ColorGeometryError(f"{name} must be a number, got {value!r}")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ColorGeometryError(f"{name} must be a finite number above 0, got {value}")
    return value


def _transform(transform) -> dict:
    if not isinstance(transform, dict) or any(k not in transform for k in TRANSFORM_KEYS):
        raise ColorGeometryError(f"transform must be tdmg.flat.to_model's dict with "
                                 f"{', '.join(TRANSFORM_KEYS)}")
    for key in TRANSFORM_KEYS:
        value = transform[key]
        if (isinstance(value, bool) or not isinstance(value, numbers.Real)
                or not math.isfinite(value)):
            raise ColorGeometryError(f"transform {key} must be a finite number, "
                                     f"got {value!r}")
    if transform["scale_mm_per_px"] <= 0:
        raise ColorGeometryError(f"transform scale_mm_per_px must be above 0, got "
                                 f"{transform['scale_mm_per_px']}")
    return transform


def _silhouette(silhouette):
    if not isinstance(silhouette, (Polygon, MultiPolygon)):
        raise ColorGeometryError(f"silhouette must be a Polygon or MultiPolygon, got "
                                 f"{type(silhouette).__name__}")
    if silhouette.is_empty or not silhouette.area > 0:
        raise ColorGeometryError("silhouette is empty (no area)")
    if not silhouette.is_valid:
        raise ColorGeometryError(f"silhouette is not valid: "
                                 f"{shapely.is_valid_reason(silhouette)}")
    return silhouette


def _polygonal(geom) -> list[Polygon]:
    """geom's polygons of positive area.

    Overlays can return lines and points where boundaries touch; they have no area and
    are dropped.
    """
    return [p for p in polygon_parts(geom)[0] if p.area > 0]


def _filaments(n: int) -> str:
    return "1 filament remains" if n == 1 else f"{n} filaments remain"


def _warning(index: int, status: str, filaments: int) -> str:
    if status == "vanished_in_fine":
        what = "not in the fine label map, so nothing of it is printed"
    else:
        what = "no area inside the silhouette, so nothing of it is printed"
    return f"color {index}: {status}: {what}; {_filaments(filaments)}"


def color_regions(fine, supersample, transform, silhouette, *, n_colors, base_index,
                  thin_width_mm) -> ColorRegions:
    """Per-color inlay polygons and the base top in model mm, clipped to the silhouette.

    fine, supersample: the fine label map and its factor (fine_regions_px).
    transform: tdmg.flat.to_model's dict. silhouette: S, a valid Polygon or MultiPolygon
    in mm with area > 0 (the cleaned R1 shape). n_colors: the palette size, an int >= 1;
    every fine label must be below it. base_index: the base color, an int in
    [0, n_colors). thin_width_mm: finite, > 0 (the caller passes
    flat.sliver.opening_width); used only to report thin parts. Bools are refused for
    every number. ColorGeometryError names the bad argument.

    For each palette index c except the base, the inlay is the positive-area polygons of
    c's fine region in mm intersected with S. Nothing is cleaned (module docstring). The
    base color is not vectorized: its top is S minus the union of the inlays.

    report: {"colors": [per palette index except the base, ascending: {"index",
    "status", "area_mm2", "parts", "thin"}], "base": {"index", "present_in_fine",
    "area_mm2" (of base_top)}, "base_thin", "silhouette_area_mm2"}. status is one of
    STATUSES: "vanished_in_fine" (not in fine), "outside_silhouette" (in fine, no area
    inside S) or "inlay". "thin" and "base_thin" are tdmg.flat.thin_regions of the
    color's polygons and of base_top at thin_width_mm: information only, never a warning.
    warnings: one line per non-inlay color and one if the base is not in fine, each
    ending with the number of filaments the AMS output will use (the base plus each
    inlay color).
    """
    a = _fine(fine)
    s = _supersample(supersample)
    n_colors = _int("n_colors", n_colors, 1)
    base_index = _int("base_index", base_index, 0, n_colors)
    if int(a.max()) >= n_colors:
        raise ColorGeometryError(f"fine has label {int(a.max())}, not below n_colors "
                                 f"{n_colors}")
    thin_width_mm = _positive("thin_width_mm", thin_width_mm)
    transform = _transform(transform)
    silhouette = _silhouette(silhouette)

    others = [c for c in range(n_colors) if c != base_index]
    regions_px = fine_regions_px(a, s, labels=others)
    inlays: dict[int, list[Polygon]] = {}
    statuses = {}
    for c in others:
        if c not in regions_px:
            statuses[c] = "vanished_in_fine"
            continue
        parts = _polygonal(shapely.intersection(
            apply_transform(regions_px[c], transform), silhouette))
        if parts:
            inlays[c] = sorted(parts, key=order_key)
            statuses[c] = "inlay"
        else:
            statuses[c] = "outside_silhouette"

    entries = []
    for c in others:
        parts = inlays.get(c, [])
        entries.append({"index": c, "status": statuses[c],
                        "area_mm2": float(sum(p.area for p in parts)),
                        "parts": len(parts), "thin": thin_regions(parts, thin_width_mm)})

    all_inlays = [p for polys in inlays.values() for p in polys]
    if all_inlays:
        base = shapely.difference(silhouette, shapely.union_all(all_inlays))
    else:
        base = silhouette
    base_top = sorted(_polygonal(base), key=order_key)
    base_area = float(sum(p.area for p in base_top))
    base_present = bool((a == base_index).any())
    report = {"colors": entries,
              "base": {"index": base_index, "present_in_fine": base_present,
                       "area_mm2": base_area},
              "base_thin": thin_regions(base_top, thin_width_mm),
              "silhouette_area_mm2": float(silhouette.area)}
    filaments = 1 + len(inlays)  # the base and one per inlay color (the AMS bodies)
    warnings = []
    if not base_present:
        warnings.append(f"base color {base_index}: not in the fine label map; it is the "
                        f"body under the inlays, and its top shows only where no inlay "
                        f"covers the silhouette ({base_area:.6g} mm^2); "
                        f"{_filaments(filaments)}")
    warnings += [_warning(e["index"], e["status"], filaments)
                 for e in entries if e["status"] != "inlay"]
    return ColorRegions(inlays, base_top, report, warnings)


# --- AMS bodies (Decision 6, as amended during Task 4) ---------------------------------
#
# The bodies are meshed directly from 2-D cells on a storage grid, with no 3-D boolean:
# a manifold3d union FAILed F1 after float32 STL storage on 3 of the 4 approved plans
# (the plan's Decision 6 amendment gives the diagnosis).

_F32 = np.finfo(np.float32)
_F32_BITS = int(_F32.nmant) + 1                     # 24: the significand, hidden bit included
_F32_QMIN = int(_F32.minexp) - int(_F32.nmant)      # -149: the subnormal step is 2^-149
_F32_QMAX = int(_F32.maxexp) - int(_F32.nmant) - 2  # 103: 2^24 x 2^103 = 2^127 is finite


def storage_grid_mm(max_abs_coord) -> float:
    """G = 2^(e - 24), e the smallest integer with max_abs_coord < 2^e.

    Derivation: float32 has a 24-bit significand (np.finfo(np.float32).nmant + 1), so it
    represents every k x 2^q with k an integer, |k| <= 2^24, and q in its exponent range
    (q >= -149, the subnormal step; q <= 103, since 2^24 x 2^104 = 2^128 overflows
    float32). A multiple k x G with |k x G| <= 2^e has
    |k| <= 2^24, so every grid point with |coordinate| <= 2^e is a float32 number (2^e
    itself is a power of two), and writing it to an STL is exact. Coordinates up to
    max_abs_coord, rounded to G, stay within 2^e; so do snap-rounded intersections, which
    lie between input coordinates. G is derived, not a rule. Only x and y go on the grid:
    the z values (0, T - d, T) are a few shared floats, each rounded to float32 the same
    way wherever it appears, so they need not be grid multiples.

    max_abs_coord: finite and above 0 (bool refused), with e - 24 in float32's exponent
    range; otherwise ColorGeometryError.
    """
    m = _positive("max_abs_coord", max_abs_coord)
    e = math.frexp(m)[1]  # m = f 2^e with 0.5 <= f < 1, so 2^(e-1) <= m < 2^e
    q = e - _F32_BITS
    if not _F32_QMIN <= q <= _F32_QMAX:
        raise ColorGeometryError(f"max_abs_coord {m} needs the grid 2^{q}, outside "
                                 f"float32's range 2^{_F32_QMIN} to 2^{_F32_QMAX}")
    return math.ldexp(1.0, q)


def snap_move_mm(grid_mm: float) -> float:
    """d = G sqrt(2)/2: how far snap rounding on G moves any boundary point, at most.

    GEOS's snap-rounding noder rounds every vertex to the nearest grid point (at most half
    a grid diagonal away) and reroutes a segment through the centre of every grid cell
    (hot pixel) it passes through, which is also within half a diagonal of the segment.
    A rerouted piece joins two points each within d of the segment, and distance to a
    segment is convex, so the whole piece stays within d of it.
    """
    return grid_mm * math.sqrt(2) / 2


def tube_area_bound(geoms, d: float) -> float:
    """An upper bound on the area within d of geoms' boundaries: 2 d L + N pi d^2.

    L is the total boundary length and N the number of ring vertices (each ring's closing
    point counted once). Every point within d of a polygonal ring is within d of one of
    its segments, so it lies either in the rectangle of width 2 d along that segment
    (area 2 d x its length) or in the disc of radius d at one of its ends. One disc per
    ring would be enough only for convex rings (their turning angles sum to 2 pi); a disc
    per vertex holds for any ring, and costs N pi d^2 (about 2e-11 mm^2 per vertex at
    60 mm), which is small next to 2 d L.
    """
    geoms = [g for g in geoms if not g.is_empty]
    length = float(sum(g.length for g in geoms))
    vertices = 0
    for g in geoms:
        for p in polygon_parts(g)[0]:
            for ring in (p.exterior, *p.interiors):
                vertices += len(ring.coords) - 1
    return 2 * d * length + vertices * math.pi * d ** 2


@dataclass(frozen=True, eq=False)
class Cells:
    """The silhouette cut into cells on the storage grid, each labelled with one color.

    grid_mm: G (storage_grid_mm).
    silhouette: the gridded S, defined as the union of the cells when they are made (it is
      not shapely.set_precision of S).
    cells: the faces of the one snap-rounded noding of S's and every piece's boundaries
      that color_cells keeps, sorted by tdmg.flat.order_key. labels: the palette index of
      each cell (base_index for base-top cells). base_index: the base color.
    report: JSON-safe; see color_cells.
    raw_silhouette: S as given, before the grid. raw_pieces: the input pieces as given,
      each (label, polygon). pinch_fixes: one dict per pinch fix (see color_cells).
      F4.color_partition checks the cells against these raw inputs.
    """

    grid_mm: float
    silhouette: Polygon | MultiPolygon
    cells: tuple[Polygon, ...]
    labels: tuple[int, ...]
    base_index: int
    report: dict
    raw_silhouette: Polygon | MultiPolygon
    raw_pieces: tuple[tuple[int, Polygon], ...]
    pinch_fixes: tuple[dict, ...] = ()

    def of(self, index: int) -> list[Polygon]:
        """The cells labelled index, in cell order."""
        return [c for c, k in zip(self.cells, self.labels, strict=True) if k == index]


def _union(polys):
    polys = list(polys)
    return shapely.union_all(polys) if polys else Polygon()


# Pinch fix (plan Decision 6 amendment, "Pinch points"). The diamond's radius is
# PINCH_K grid steps. A numerical choice tied to the grid, not a rule. Snap rounding moves
# every boundary point by at most half a grid diagonal, G sqrt(2)/2, and a diamond of
# radius K G has an inscribed circle of radius K G / sqrt(2); that must exceed the move,
# so K > 1. This is a necessary condition only (it keeps the pinch vertex inside the
# snapped diamond); that K = 2, the smallest such integer, is enough is measured, not
# proved:
# Measured 2026-11-12 (Shapely 2.2.0, GEOS 3.14.1) on random checkerboard maps: K = 1 left
# pinches unfixed in 48 of 400 maps; K = 2, 3 and 4 fixed all 1,496 pinches there, and
# K = 2 all 7,519 in 2,000 more maps. The moved area is at most 2 (K G)^2 per fix (8 G^2,
# about 1.2e-10 mm^2 at 60 mm). tests/test_color_checks.py checks K = 1 fails and K = 2
# to 4 work (test_pinch_fix_k).
PINCH_K = 2
# Rounds of pinch fixing before color_cells refuses. One round fixes every pinch found; a
# fix makes its vertex interior to one label and adds vertices only on the diamond's
# boundary, where the diamond's label is one run, so a second round should find nothing
# new unless two diamonds overlap. Measured: every one of the 2,400 maps above needed one
# round. The bound is a stated margin over that, not a rule; the report gives the rounds.
PINCH_ROUNDS = 4


def _grid_ints(xy, grid: float, what: str) -> list[tuple[int, int]]:
    """xy (an (n, 2) array) in whole grid steps, exactly; ColorGeometryError if off-grid.

    A multiple of a power of two divided by it is exact in float64, so k = x / G is an
    integer exactly when x is on the grid; the result is Python ints, so products and sums
    of them are exact at any size.
    """
    k = np.asarray(xy, dtype=np.float64) / grid
    if not np.array_equal(k, np.round(k)):
        raise ColorGeometryError(f"{what} has coordinates off the grid {grid} mm")
    return [(int(a), int(b)) for a, b in k.tolist()]


def _cell_grid(cells, grid_mm) -> float:
    if grid_mm is not None:
        return _positive("grid_mm", grid_mm)
    coords = np.concatenate([shapely.get_coordinates(c) for c in cells])
    return storage_grid_mm(float(np.abs(coords).max()))


def _half_turn_key(d: tuple[int, int]):
    """Exact counter-clockwise order of integer directions, starting at angle 0."""
    return 0 if d[1] > 0 or (d[1] == 0 and d[0] > 0) else 1


def _ccw(a: tuple[int, int], b: tuple[int, int]) -> int:
    ha, hb = _half_turn_key(a), _half_turn_key(b)
    if ha != hb:
        return ha - hb
    cross = a[0] * b[1] - a[1] * b[0]
    return -1 if cross > 0 else (1 if cross < 0 else 0)


def _vertex_runs(cells, labels, grid: float):
    """Per cell vertex v: (v, labels with two or more runs, whether S has two or more).

    At v, every incident edge gives a direction (an integer vector in grid steps, reduced
    by its gcd, so collinear edges give one direction). Each ring passing through v as
    p -> v -> n (rings oriented with the cell on their left) claims for its cell the wedge
    that starts at direction n and runs counter-clockwise to the next direction; a wedge
    no ring claims is outside S. A cell whose rings pass through v twice (a hole touching
    its shell) claims each of its wedges separately, so its two sides are not mistaken
    for one sector. The directions are sorted exactly (half-plane, then the sign of the
    integer cross product), so the order needs no angle and no tolerance.
    """
    claims: dict[tuple[int, int], dict[tuple[int, int], int | None]] = {}
    points: dict[tuple[int, int], tuple[float, float]] = {}
    for cell, label in zip(cells, labels, strict=True):
        oriented = shapely.orient_polygons(cell)
        for ring in (oriented.exterior, *oriented.interiors):
            raw = shapely.get_coordinates(ring)[:-1]
            xy = _grid_ints(raw, grid, "a cell")
            for i, v in enumerate(xy):
                points.setdefault(v, (float(raw[i][0]), float(raw[i][1])))
                around = claims.setdefault(v, {})
                for w, claimed in ((xy[i - 1], False), (xy[(i + 1) % len(xy)], True)):
                    dx, dy = w[0] - v[0], w[1] - v[1]
                    g = math.gcd(dx, dy)
                    d = (dx // g, dy // g)
                    if claimed:
                        around[d] = int(label)
                    else:
                        around.setdefault(d, None)
    out = []
    for v, around in claims.items():
        order = sorted(around, key=cmp_to_key(_ccw))
        tokens = [around[d] for d in order]
        pinching = sorted(label for label in set(tokens) - {None}
                          if _runs(tokens, label) >= 2)
        inside = [t is not None for t in tokens]
        s_pinch = _runs(inside, True) >= 2
        if pinching or s_pinch:
            out.append((points[v], pinching, s_pinch))
    return sorted(out)


def pinch_vertices(cells, labels, *, grid_mm=None) -> list[tuple[tuple[float, float],
                                                                   list[int]]]:
    """The cell vertices where a label's cells meet in two or more separate angular runs.

    cells: polygons on the grid grid_mm (default: storage_grid_mm of their largest
    |coordinate|; pass the Cells' G instead: snap rounding can carry the largest
    coordinate up to exactly 2^e, where the default would be 2G and refuse vertices at
    odd multiples of G; color_cells and ams_bodies always pass it) that tile without
    overlap and share vertices exactly (as color_cells makes them); labels: one int per
    cell. Around each vertex v the wedges between the incident edges are each claimed by one cell or by nobody (outside S); _vertex_runs
    gives the exact construction. A label whose wedges form two or more runs, read
    cyclically, pinches at v. Returns [(v, [pinching labels, ascending])], sorted by v.
    Includes vertices where S itself pinches (color_cells does not fix those).
    ColorGeometryError for coordinates off the grid.
    """
    cells = list(cells)
    grid = _cell_grid(cells, grid_mm)
    return [(v, ls) for v, ls, _ in _vertex_runs(cells, labels, grid) if ls]


def _runs(tokens: list, label) -> int:
    """How many maximal runs of label the cyclic sequence tokens has."""
    return sum(1 for i, t in enumerate(tokens) if t == label and tokens[i - 1] != label)


def _faces(silhouette, pieces, overrides, grid):
    """The labelled cells of one noding pass, sorted by order_key, and relabelled_mm2.

    pieces: [(label, polygon)]. Each face is labelled by a plurality vote over the area
    each label's pieces cover and the area outside S, "outside" being a candidate too: a
    face 40% outside, 30% A and 30% B is dropped. Ties go to "outside", then to the
    lowest label. overrides: [(polygon, label)], applied in order after that: a face with
    more than half its area in an override takes its label. relabelled_mm2 is measured
    before the overrides.
    """
    lines = shapely.union_all([shapely.boundary(silhouette)]
                              + [shapely.boundary(p) for _, p in pieces]
                              + [shapely.boundary(d) for d, _ in overrides],
                              grid_size=grid)
    faces = [f for f in shapely.get_parts(shapely.polygonize(shapely.get_parts(lines)))
             if f.area > 0]
    if not faces:
        return [], [], 0.0
    face_arr = np.asarray(faces, dtype=object)
    cover: list[dict[int, float]] = [{} for _ in faces]
    if pieces:
        geoms = np.asarray([p for _, p in pieces], dtype=object)
        face_i, piece_i = shapely.STRtree(geoms).query(face_arr, predicate="intersects")
        shared = shapely.area(shapely.intersection(face_arr[face_i], geoms[piece_i]))
        for i, j, a in zip(face_i.tolist(), piece_i.tolist(), shared.tolist(),
                           strict=True):
            c = pieces[j][0]
            cover[i][c] = cover[i].get(c, 0.0) + a
    outside_area = shapely.area(shapely.difference(face_arr, silhouette)).tolist()
    kept, labels, relabelled = [], [], 0.0
    for face, weights, outside in zip(faces, cover, outside_area, strict=True):
        best = max(weights.items(), key=lambda kv: (kv[1], -kv[0]), default=(None, 0.0))
        if best[0] is None or outside >= best[1]:
            continue
        kept.append(face)
        labels.append(best[0])
        relabelled += float(face.area) - best[1]
    if overrides and kept:
        tree = shapely.STRtree(np.asarray(kept, dtype=object))
        for diamond, label in overrides:
            for i in tree.query(diamond, predicate="intersects").tolist():
                if shapely.intersection(kept[i], diamond).area > kept[i].area / 2:
                    labels[i] = label
    order = sorted(range(len(kept)), key=lambda i: order_key(kept[i]))
    return [kept[i] for i in order], [labels[i] for i in order], relabelled


def color_cells(regions: ColorRegions, silhouette, base_index, *,
                fix_pinches: bool = True) -> Cells:
    """S and the color regions as labelled cells on the storage grid G, without pinches.

    regions: color_regions' result for silhouette S (a valid Polygon or MultiPolygon with
    area > 0). base_index: an int >= 0 (bool refused) that is not an inlay index.
    ColorGeometryError names a bad argument. Steps:
    - G = storage_grid_mm(the largest |x| or |y| of S and every piece). The pieces are
      each inlay polygon, labelled with its color, and each base_top polygon, labelled
      base_index.
    - The boundaries of S and of every piece are noded once, in one snap-rounding pass on
      G: shapely.union_all(boundaries, grid_size=G). One pass moves every boundary
      consistently, so the faces of its polygonization tile the plane with shared
      vertices, all on the grid.
    - Each face of area > 0 is labelled by a plurality vote: the area each label's
      pieces cover (shapely.intersection with the ungridded pieces) and the area outside
      S, "outside" being a candidate too. A face that "outside" wins is not a cell (it
      is a hole of S or lies beyond S's edge). A tie goes to "outside", then to the
      lowest label. Snapping moves boundaries by less than G, so a face covered by two
      labels is a sliver at a boundary: its minority area is reported, not refused.
    - Pinches (pinch_vertices): at each vertex where a label pinches and S does not, a
      diamond Point(v).buffer(PINCH_K x G, quad_segs=1) intersected with S is given to
      the lowest pinching label. A vertex where S itself pinches (S's wedges form two or
      more runs, whatever the labels) is not joined: it is counted in the report's
      silhouette_pinches, and the base body FAILs F1 there. A label pinch at the same
      vertex is then left unjoined and is not counted separately (F1 FAILs there
      anyway). The cells are rebuilt from
      scratch with every diamond's boundary in the same single noding, each face more
      than half inside a diamond taking its label (later diamonds over earlier ones), and
      this repeats until no such pinch is left.
      Pinches still found after PINCH_ROUNDS rounds are refused (ColorGeometryError).
      fix_pinches=False skips this step; it is for measurement and tests, and the AMS
      route never passes it.
    - The cells' union is the gridded S (Cells.silhouette). The raw S and pieces are kept
      in the Cells (raw_silhouette, raw_pieces) for F4.color_partition, and each pinch fix
      in pinch_fixes: {"vertex", "label", "losers" (the labels that held part of the
      diamond before), "clipped" (whether S cuts the diamond), "area_mm2" (of the
      diamond intersected with S), "bound_mm2" (that area plus tube_area_bound of its
      boundary at snap_move_mm(G): the snapped diamond lies within it, so this bounds the
      area the fix can move between labels or across S's edge)}.
    report: {"grid_mm", "max_abs_coord_mm", "faces" (cells of the first noding),
    "cells", "silhouette_shift_mm2" (area of S XOR the gridded S), "relabelled_mm2"
    (the area of the final cells, labelled by majority before any diamond's label is
    applied, that the pieces of their own label do not cover: area the snap moved
    between labels),
    "colors": [per label of the input pieces, ascending: {"index", "cells", "area_mm2"
    (of its cells), "shift_mm2" (area of the union of its pieces XOR the union of its
    cells)}], "pinches": {"fixed", "rounds", "radius_mm", "area_moved_mm2",
    "silhouette_pinches" (vertices where S itself pinches; not joined, and F1 FAILs the
    base body there), "colors": [per label that was given a diamond: {"index", "fixed",
    "area_moved_mm2"}]}}. area_moved is the area of each diamond that other labels held
    before it was given, at most 2 (PINCH_K G)^2 per fix. All of these are information:
    F4.color_partition gates the cells themselves.
    """
    if not isinstance(regions, ColorRegions):
        raise ColorGeometryError(f"regions must be a ColorRegions, got "
                                 f"{type(regions).__name__}")
    silhouette = _silhouette(silhouette)
    base_index = _int("base_index", base_index, 0)
    if base_index in regions.inlays:
        raise ColorGeometryError(f"base_index {base_index} is an inlay color in regions")
    pieces = [(c, p) for c in sorted(regions.inlays) for p in regions.inlays[c]]
    pieces += [(base_index, p) for p in regions.base_top]
    coords = np.concatenate([shapely.get_coordinates(g)
                             for g in [silhouette, *(p for _, p in pieces)]])
    max_abs = float(np.abs(coords).max())
    grid = storage_grid_mm(max_abs)
    radius = PINCH_K * grid

    faces, labels, relabelled = _faces(silhouette, pieces, [], grid)
    first_faces = len(faces)
    overrides: list[tuple] = []
    fixes: list[dict] = []
    fixed: dict[int, int] = {}
    moved: dict[int, float] = {}
    rounds = 0
    while fix_pinches:
        # A vertex where S itself pinches is left alone (joining cannot reach across
        # outside S); it is reported, and F1 FAILs the base there.
        found = [(v, ls) for v, ls, s_pinch in _vertex_runs(faces, labels, grid)
                 if ls and not s_pinch]
        if not found:
            break
        if rounds == PINCH_ROUNDS:
            raise ColorGeometryError(
                f"{len(found)} pinch points remain after {PINCH_ROUNDS} rounds of "
                f"joining, first at {found[0][0]} (labels {found[0][1]})")
        rounds += 1
        tree = shapely.STRtree(np.asarray(faces, dtype=object))
        for v, pinching in found:
            label = pinching[0]
            diamond = shapely.intersection(
                shapely.Point(v).buffer(radius, quad_segs=1), silhouette)
            near = tree.query(diamond, predicate="intersects").tolist()
            parts = {i: float(shapely.intersection(faces[i], diamond).area) for i in near
                     if labels[i] != label}
            taken = float(sum(parts.values()))
            fixed[label] = fixed.get(label, 0) + 1
            moved[label] = moved.get(label, 0.0) + taken
            overrides.append((diamond, label))
            full = shapely.Point(v).buffer(radius, quad_segs=1)
            fixes.append({"vertex": [float(v[0]), float(v[1])], "label": label,
                          "losers": sorted({labels[i] for i, a in parts.items() if a > 0}),
                          "clipped": bool(shapely.difference(full, silhouette).area > 0),
                          "area_mm2": float(diamond.area),
                          "bound_mm2": float(diamond.area) + tube_area_bound(
                              [diamond], snap_move_mm(grid))})
        faces, labels, relabelled = _faces(silhouette, pieces, overrides, grid)

    cells, labels = tuple(faces), tuple(labels)
    s_grid = _union(cells)
    colors_report = []
    for c in sorted({c for c, _ in pieces}):
        mine = [f for f, k in zip(cells, labels, strict=True) if k == c]
        source = _union(p for k, p in pieces if k == c)
        colors_report.append({"index": c, "cells": len(mine),
                              "area_mm2": float(sum(f.area for f in mine)),
                              "shift_mm2": float(shapely.symmetric_difference(
                                  source, _union(mine)).area)})
    pinches = {"fixed": sum(fixed.values()), "rounds": rounds, "radius_mm": radius,
               "area_moved_mm2": float(sum(moved.values())),
               "silhouette_pinches": sum(
                   1 for *_, s_pinch in _vertex_runs(cells, labels, grid) if s_pinch),
               "colors": [{"index": c, "fixed": fixed[c], "area_moved_mm2": moved[c]}
                          for c in sorted(fixed)]}
    report = {"grid_mm": grid, "max_abs_coord_mm": max_abs, "faces": first_faces,
              "cells": len(cells),
              "silhouette_shift_mm2": float(
                  shapely.symmetric_difference(silhouette, s_grid).area),
              "relabelled_mm2": relabelled, "colors": colors_report, "pinches": pinches}
    return Cells(grid, s_grid, cells, labels, base_index, report, silhouette,
                 tuple(pieces), tuple(fixes))


def _uncovered(lo: float, hi: float, other) -> list[tuple[float, float]]:
    """The parts of [lo, hi] outside the interval other, a (lo, hi) pair or None."""
    if other is None:
        return [(lo, hi)]
    nlo, nhi = other
    out = []
    if nlo > lo:
        out.append((lo, min(hi, nlo)))
    if nhi < hi:
        out.append((max(lo, nhi), hi))
    return [(a, b) for a, b in out if a < b]


def _twice_area(ring: list[tuple[int, int]]) -> int:
    """Twice the signed shoelace area of a closed ring of integer points (exact)."""
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in pairwise(ring))


def _triangles(cell: Polygon, grid: float) -> list:
    """cell's constrained Delaunay triangles, each 3 (x, y), counter-clockwise from above.

    Refuses (ColorGeometryError) an empty triangulation, a triangle with a vertex that is
    not one of the cell's, and triangles whose areas do not sum to the cell's. The areas
    are compared exactly: in whole grid steps (_grid_ints) the shoelace sums are Python
    integers, so twice the triangles' total must equal twice the cell's area exactly
    (the oriented exterior counted positive, its holes negative).
    """
    tris = shapely.get_parts(shapely.constrained_delaunay_triangles(cell))
    where = shapely.point_on_surface(cell).wkt
    if len(tris) == 0:
        raise ColorGeometryError(f"the triangulation of the cell at {where} has no "
                                 "triangles")
    xy = np.stack([shapely.get_coordinates(shapely.get_exterior_ring(t))[:3]
                   for t in tris])
    own = {tuple(v) for v in shapely.get_coordinates(cell).tolist()}
    if any(tuple(v) not in own for v in xy.reshape(-1, 2).tolist()):
        raise ColorGeometryError(f"the triangulation added a vertex to the cell at {where}")
    d1, d2 = xy[:, 1] - xy[:, 0], xy[:, 2] - xy[:, 0]
    clockwise = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0] < 0
    xy[clockwise] = xy[clockwise][:, [0, 2, 1]]
    k = _grid_ints(xy.reshape(-1, 2), grid, "a triangle")
    tri_total = sum(_twice_area([k[i], k[i + 1], k[i + 2], k[i]])
                    for i in range(0, len(k), 3))
    oriented = shapely.orient_polygons(cell)
    cell_total = sum(_twice_area(_grid_ints(shapely.get_coordinates(r), grid, "a cell"))
                     for r in (oriented.exterior, *oriented.interiors))
    if tri_total != cell_total:
        raise ColorGeometryError(f"the triangles of the cell at {where} cover area "
                                 f"{tri_total / 2 * grid * grid} mm^2, not the cell's "
                                 f"{cell_total / 2 * grid * grid} mm^2")
    return xy.tolist()


def _prism(cells, ranges, grid_mm=None) -> tuple[trimesh.Trimesh, float]:
    """prism_mesh's mesh and its wall area (the sum of edge length x uncovered height)."""
    cells = list(cells)
    ranges = [(float(lo), float(hi)) for lo, hi in ranges]
    if not cells or len(cells) != len(ranges):
        raise ColorGeometryError(f"need at least one cell and one (lo, hi) per cell, got "
                                 f"{len(cells)} cells and {len(ranges)} ranges")
    for cell, (lo, hi) in zip(cells, ranges, strict=True):
        if not isinstance(cell, Polygon) or cell.is_empty or not cell.is_valid:
            raise ColorGeometryError("every cell must be a valid, non-empty Polygon")
        if not (math.isfinite(lo) and math.isfinite(hi) and lo < hi):
            raise ColorGeometryError(f"a cell's range must be finite with lo < hi, got "
                                     f"({lo}, {hi})")
    grid = _cell_grid(cells, grid_mm)
    levels = sorted({z for r in ranges for z in r})
    index: dict[tuple[float, float, float], int] = {}
    faces: list[tuple[int, int, int]] = []

    def vid(x: float, y: float, z: float) -> int:
        return index.setdefault((x, y, z), len(index))

    oriented = [shapely.orient_polygons(c) for c in cells]  # exterior ccw, holes cw
    edges: dict[tuple, int] = {}  # directed edge, the cell on its left -> cell number
    for k, cell in enumerate(oriented):
        for ring in (cell.exterior, *cell.interiors):
            xy = [tuple(v) for v in shapely.get_coordinates(ring).tolist()]
            for p, q in pairwise(xy):
                if (p, q) in edges:
                    raise ColorGeometryError(f"cells {edges[(p, q)]} and {k} share the "
                                             f"directed edge {p} -> {q}: they overlap")
                edges[(p, q)] = k
    for cell, (lo, hi) in zip(oriented, ranges, strict=True):
        for a, b, c in _triangles(cell, grid):
            faces.append((vid(*a, hi), vid(*b, hi), vid(*c, hi)))  # top, facing up
            faces.append((vid(*a, lo), vid(*c, lo), vid(*b, lo)))  # bottom, facing down
    walls = 0.0
    for (p, q), k in edges.items():
        lo, hi = ranges[k]
        other = edges.get((q, p))
        for z0, z1 in _uncovered(lo, hi, None if other is None else ranges[other]):
            walls += math.dist(p, q) * (z1 - z0)
            steps = [z for z in levels if z0 <= z <= z1]  # split at every level
            for u, w in pairwise(steps):
                a, b, c, d = vid(*p, u), vid(*q, u), vid(*q, w), vid(*p, w)
                faces += [(a, b, c), (a, c, d)]  # facing away from the cell (its right)
    vertices = np.array(list(index), dtype=np.float64).reshape(-1, 3)
    mesh = trimesh.Trimesh(vertices, np.array(faces, dtype=np.int64).reshape(-1, 3),
                           process=False, validate=False)
    return mesh, walls


def prism_mesh(cells, ranges, *, grid_mm=None) -> trimesh.Trimesh:
    """One mesh of prisms: cell i spans z from ranges[i][0] to ranges[i][1].

    cells: valid Polygons that do not overlap and that share their boundary vertices
    exactly where they touch (as color_cells' cells do), with every coordinate on the
    grid grid_mm (default: storage_grid_mm of their largest |coordinate|; ams_bodies
    passes the Cells' G, and so should any caller: see pinch_vertices for why the
    default can be wrong after snap rounding). ranges: one (lo, hi) per cell, finite with lo < hi.
    ColorGeometryError for bad input, off-grid coordinates, or two cells with the same
    directed edge (an overlap).
    - Per cell, the top (at hi) and the bottom (at lo) are shapely.
      constrained_delaunay_triangles of the cell, checked to be non-empty, to use only
      the cell's vertices and to cover exactly the cell's area (_triangles), and oriented
      counter-clockwise seen from outside.
    - For every directed edge of a cell's oriented rings (the cell on its left), a wall
      covers the part of [lo, hi] that the cell across the edge (the one with the
      reversed edge, if any) does not cover. It faces away from the cell.
    - Each wall is split at every z level of any range, so vertical edges meet vertex to
      vertex (no T-junctions).
    - Vertices are deduplicated on exact (x, y, z) and numbered in first use (cells in
      the order given, tops and bottoms first, then walls): deterministic.
    Not handled here: where two cells of one mesh touch at a single point and are both
    taller there than every cell between them, the edge through that point is
    non-manifold; the F1 checks report it. color_cells removes such pinch points for the
    AMS bodies (pinch_vertices, PINCH_K), except where S itself pinches. Neighbours whose
    ranges touch but do not overlap ([0, 1] next to [1, 2]) are not handled either: the
    shared edge at z = 1 gets four faces (an overfull edge); ams_bodies never builds them
    (every base range contains [0, T - d], and an inlay body has one range).
    """
    return _prism(cells, ranges, grid_mm)[0]


@dataclass(frozen=True, eq=False)
class Body:
    """One AMS body: a solid of one filament, meshed from its cells.

    name: "base" or f"color-{index}". index: its palette index (the base's is base_index).
    parts: its cells (every cell for the base, the color's cells for an inlay); their
      bounds are the body's x and y bounds.
    slabs: its cells grouped by z range, each (cells, z0, z1), ascending by (z0, z1).
    z_range_mm: (lowest z0, highest z1).
    mesh: prism_mesh of the cells, unprocessed float64.
    expected_volume_mm3: the sum over cells of area x (z1 - z0).
    surface_mm2: 2 x the cells' area (tops and bottoms) plus the walls' area (edge length
      x uncovered height): the intended solid's surface, for its export tolerance.
    """

    name: str
    index: int
    parts: tuple[Polygon, ...]
    slabs: tuple[tuple[tuple[Polygon, ...], float, float], ...]
    z_range_mm: tuple[float, float]
    mesh: trimesh.Trimesh
    expected_volume_mm3: float
    surface_mm2: float


def vertex_dist(geoms) -> float:
    """ULPS x eps x the largest |coordinate| of geoms: the float64 overlay rounding bound."""
    coords = np.concatenate([shapely.get_coordinates(g) for g in geoms])
    return ULPS * EPS * float(np.abs(coords).max())


def _body(name: str, index: int, cells: list, ranges: list, grid: float) -> Body:
    mesh, walls = _prism(cells, ranges, grid)
    groups: dict[tuple[float, float], list[Polygon]] = {}
    for cell, r in zip(cells, ranges, strict=True):
        groups.setdefault(r, []).append(cell)
    slabs = tuple((tuple(groups[r]), *r) for r in sorted(groups))
    volume = float(sum(c.area * (hi - lo)
                       for c, (lo, hi) in zip(cells, ranges, strict=True)))
    surface = 2 * float(sum(c.area for c in cells)) + walls
    z_range = (min(lo for lo, _ in ranges), max(hi for _, hi in ranges))
    return Body(name, index, tuple(cells), slabs, z_range, mesh, volume, surface)


def ams_bodies(cells: Cells, *, thickness_mm, skin_mm) -> list[Body]:
    """The AMS bodies, face up: the base first, then one inlay per color by palette index.

    cells: color_cells' result. thickness_mm T and skin_mm d: finite and above 0 (bools
    refused), with T > d so that there is base material under every inlay.
    ColorGeometryError names the bad argument. With z0 = T - d (computed once):
    - base: every cell, from 0 to T if it is base-colored, else from 0 to z0;
    - inlay c: the cells labelled c, from z0 to T.
    Each body is prism_mesh of its cells, so all bodies use the same x, y vertices on the
    grid and the same z floats, with no boolean and no translation.
    """
    if not isinstance(cells, Cells):
        raise ColorGeometryError(f"cells must be a Cells, got {type(cells).__name__}")
    thickness_mm = _positive("thickness_mm", thickness_mm)
    skin_mm = _positive("skin_mm", skin_mm)
    if thickness_mm <= skin_mm:
        raise ColorGeometryError(f"thickness_mm ({thickness_mm}) must be above skin_mm "
                                 f"({skin_mm}): there must be base material under every "
                                 "inlay")
    if not cells.cells:
        raise ColorGeometryError("cells has no cells")
    z0 = thickness_mm - skin_mm
    base = cells.base_index
    ranges = [(0.0, thickness_mm if k == base else z0) for k in cells.labels]
    bodies = [_body("base", base, list(cells.cells), ranges, cells.grid_mm)]
    for c in sorted(set(cells.labels) - {base}):
        mine = cells.of(c)
        bodies.append(_body(f"color-{c}", c, mine, [(z0, thickness_mm)] * len(mine),
                            cells.grid_mm))
    return bodies

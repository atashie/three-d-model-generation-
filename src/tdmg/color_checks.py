"""Gate checks for colored flat geometry (docs/plans/2026-11-12-color-geometry.md, Decision 9).

AMS output: tdmg.color_geometry.color_cells cuts the silhouette into labelled cells on the
storage grid, and ams_bodies meshes a base body and one inlay body per color from them.
ams_checks gates them as tdmg.flat.make_flat gates its single body: each body's STL bytes
are parsed back and merged exactly, then get the F1 topology checks and their own
F2.export_matches_geometry; the assembly gets F4.color_partition, F4.filaments,
F2.fits_build_volume on all bodies together and F5.triangles on their sum (one plate).
F4.glue_fit (the glue route) is Task 5. Not here: F3.thin_regions per body (information),
F6 (UNKNOWN until slicing) and the verdict are added by make_colored_flat in Task 6.
"""

from __future__ import annotations

import io

import numpy as np
import shapely
import trimesh

from tdmg.checks import CheckResult, merge_exact, topology_checks
from tdmg.color_geometry import (
    ULPS,
    Body,
    Cells,
    ColorGeometryError,
    _int,
    _positive,
    _union,
    snap_move_mm,
    tube_area_bound,
    vertex_dist,
)
from tdmg.flat import build_volume_check, encode_stl, export_match, triangle_check
from tdmg.profiles import PrinterProfile


class ColorCheckError(ValueError):
    """Invalid input to a color check."""


def _thickness(value) -> float:
    try:
        return _positive("thickness_mm", value)
    except ColorGeometryError as exc:
        raise ColorCheckError(str(exc)) from None


def _cells(cells) -> Cells:
    if not isinstance(cells, Cells):
        raise ColorCheckError(f"cells must be a tdmg.color_geometry.Cells, got "
                              f"{type(cells).__name__}")
    return cells


def partition_tolerance(cells: Cells) -> tuple[float, float]:
    """(area_tol_mm2, dist_mm) on the cells and the gridded S; see color_partition_check."""
    cells = _cells(cells)
    return _area_tol(list(cells.cells), cells.silhouette)


def _area_tol(pieces: list, silhouette) -> tuple[float, float]:
    dist = vertex_dist([silhouette, *pieces])
    perimeter = float(sum(p.length for p in pieces)) + float(silhouette.length)
    return perimeter * dist, dist


def _overlap(pieces: list) -> float:
    """Total pairwise intersection area, over the pairs an STRtree finds intersecting."""
    if len(pieces) < 2:
        return 0.0
    geoms = np.asarray(pieces, dtype=object)
    tree = shapely.STRtree(geoms)
    i, j = tree.query(geoms, predicate="intersects")
    keep = i < j
    if not keep.any():
        return 0.0
    return float(shapely.area(shapely.intersection(geoms[i[keep]], geoms[j[keep]])).sum())


def color_partition_check(cells: Cells, bodies: list[Body], thickness_mm) -> CheckResult:
    """F4.color_partition: the regions partition S, the cells keep that partition, and the
    volumes add up.

    Three steps are gated, each against the step before:
    1. The raw regions (cells.raw_pieces, each inlay and base-top polygon as color_regions
       made it) against the raw S (cells.raw_silhouette):
       - raw_overlap_mm2: their total pairwise intersection area (an STRtree finds the
         pairs, so thousands of pieces are cheap);
       - raw_symmetric_difference_mm2: area of union(raw pieces) XOR raw S, reported also
         as raw_gap_mm2 (S minus the union) and raw_outside_mm2 (the union minus S).
       Both within raw_area_tol_mm2.
    2. The cells against those raw inputs (the grid step, color_cells):
       - snap_silhouette_mm2: area of union(cells) XOR raw S, within snap_silhouette_mm2;
       - per label, snap_colors[].mm2: area of union(its cells) XOR union(its raw pieces),
         within its bound_mm2.
    3. The cells among themselves: overlap_mm2 (pairwise) and symmetric_difference_mm2
       (union(cells) XOR cells.silhouette, the gridded S fixed when the cells were made),
       with gap_mm2 and outside_mm2, both within area_tol_mm2. This catches cells changed
       after color_cells.
    And the volume: volume_error_mm3 = |sum of the bodies' expected volumes - area(raw S)
    x T| within volume_tol_mm3. The meshed volumes are gated per body by
    F2.export_matches_geometry against these expected volumes.

    Thresholds (derived, not rules):
    - Float64 overlay rounding: every overlay vertex is within DIST = ULPS x eps x
      max|coordinate| of its exact position (tdmg.color_geometry.vertex_dist; ULPS's
      comment gives the measurements). An area error comes from boundaries moving by at
      most DIST, so it is at most (the pieces' perimeters + S's perimeter) x DIST:
      raw_area_tol_mm2 on the raw pieces and raw S, area_tol_mm2 on the cells and the
      gridded S.
    - Snap rounding on G moves every boundary point by at most d = G sqrt(2)/2
      (tdmg.color_geometry.snap_move_mm). So a point that changes side (in or out of S, or
      from one label to another) lies within d of the raw boundary, and the symmetric
      difference is inside the d-neighbourhood of the raw boundary, whose area is at most
      tube_area_bound (2 d L + N pi d^2; L the raw boundary length, N its vertices). Each
      pinch fix (cells.pinch_fixes) can also move its diamond's area, grown by d
      (its bound_mm2), between its label and the labels that lost to it, and across S's
      edge when S clips the diamond; that is added to those labels' bounds, and to S's
      when clipped. snap_silhouette_mm2 = tube(raw S) + clipped fixes, plus
      raw_area_tol_mm2; a label's bound = tube(its raw pieces) + its fixes, plus
      raw_area_tol_mm2.
    - volume_tol_mm3 = (snap_silhouette_mm2 + area_tol_mm2) x T.
    PASS iff every measure is within its threshold. grid_shift repeats color_cells'
    report (information). Not covered: the rounding of the area sums themselves (GEOS's
    shoelace), which is not bounded separately here.
    """
    cells = _cells(cells)
    t = _thickness(thickness_mm)
    raw_s = cells.raw_silhouette
    raw = [p for _, p in cells.raw_pieces]
    raw_tol, raw_dist = _area_tol(raw, raw_s)
    raw_union = _union(raw)
    raw_overlap = _overlap(raw)
    raw_gap = float(shapely.difference(raw_s, raw_union).area)
    raw_outside = float(shapely.difference(raw_union, raw_s).area)
    raw_symmetric = float(shapely.symmetric_difference(raw_union, raw_s).area)

    pieces = list(cells.cells)
    s_grid = cells.silhouette
    area_tol, dist = partition_tolerance(cells)
    union = _union(pieces)
    gap = float(shapely.difference(s_grid, union).area)
    outside = float(shapely.difference(union, s_grid).area)
    symmetric = float(shapely.symmetric_difference(union, s_grid).area)
    overlap = _overlap(pieces)

    d = snap_move_mm(cells.grid_mm)
    fixes = list(cells.pinch_fixes)
    snap_s = float(shapely.symmetric_difference(union, raw_s).area)
    snap_s_bound = (tube_area_bound([raw_s], d) + raw_tol
                    + sum(f["bound_mm2"] for f in fixes if f["clipped"]))
    snap_colors, colors_ok = [], True
    for c in sorted({k for k, _ in cells.raw_pieces} | set(cells.labels)):
        own_raw = [p for k, p in cells.raw_pieces if k == c]
        measured = float(shapely.symmetric_difference(_union(cells.of(c)),
                                                      _union(own_raw)).area)
        tube = tube_area_bound(own_raw, d)
        pinch = float(sum(f["bound_mm2"] for f in fixes
                          if f["label"] == c or c in f["losers"]))
        bound = tube + pinch + raw_tol
        colors_ok = colors_ok and measured <= bound
        snap_colors.append({"index": c, "mm2": measured, "bound_mm2": bound,
                            "tube_mm2": tube, "pinch_mm2": pinch})

    volume = float(sum(b.expected_volume_mm3 for b in bodies))
    expected_volume = float(raw_s.area) * t
    volume_error = abs(volume - expected_volume)
    volume_tol = (snap_s_bound + area_tol) * t
    ok = (raw_overlap <= raw_tol and raw_symmetric <= raw_tol and snap_s <= snap_s_bound
          and colors_ok and overlap <= area_tol and symmetric <= area_tol
          and volume_error <= volume_tol)
    shift = {k: cells.report.get(k) for k in ("grid_mm", "silhouette_shift_mm2",
                                              "relabelled_mm2", "colors", "pinches")}
    return CheckResult(
        "F4.color_partition", "PASS" if ok else "FAIL",
        {"raw_pieces": len(raw), "raw_overlap_mm2": raw_overlap,
         "raw_symmetric_difference_mm2": raw_symmetric, "raw_gap_mm2": raw_gap,
         "raw_outside_mm2": raw_outside, "snap_silhouette_mm2": snap_s,
         "snap_colors": snap_colors, "pieces": len(pieces), "overlap_mm2": overlap,
         "symmetric_difference_mm2": symmetric, "gap_mm2": gap, "outside_mm2": outside,
         "volume_mm3": volume, "volume_error_mm3": volume_error, "grid_shift": shift},
        {"raw_area_tol_mm2": raw_tol, "raw_vertex_dist_mm": raw_dist,
         "snap_move_mm": d, "snap_silhouette_mm2": snap_s_bound,
         "area_tol_mm2": area_tol, "vertex_dist_mm": dist, "ulps": ULPS,
         "volume_tol_mm3": volume_tol, "expected_volume_mm3": expected_volume},
        None, "tolerances are derived, not rules: float64 overlay rounding "
              "((perimeters) x ULPS x eps x max|coordinate|) and snap rounding (the area "
              "within G sqrt(2)/2 of the raw boundary, plus the pinch diamonds); "
              "grid_shift is information")


def _count(name: str, value) -> int:
    try:
        return _int(name, value, 1)
    except ColorGeometryError as exc:
        raise ColorCheckError(str(exc)) from None


def filaments_check(bodies: list[Body], *, colors, palette_cap) -> CheckResult:
    """F4.filaments: the non-empty bodies number at most min(colors, palette_cap).

    colors: the plan's colors setting; palette_cap: the printer profile's cap
    (tdmg.color_config.palette_cap). Both ints >= 1 (bool refused). A body is non-empty
    when its mesh has faces and its expected volume is above 0.
    """
    colors = _count("colors", colors)
    palette_cap = _count("palette_cap", palette_cap)
    limit = min(colors, palette_cap)
    n = sum(1 for b in bodies if len(b.mesh.faces) and b.expected_volume_mm3 > 0)
    return CheckResult("F4.filaments", "PASS" if n <= limit else "FAIL", n, limit, None,
                       f"threshold is min(the plan's colors setting {colors}, the printer "
                       f"profile's palette_cap {palette_cap} (tdmg.color_config."
                       "palette_cap)); one filament per body")


def body_export_check(mesh: trimesh.Trimesh, body: Body) -> CheckResult:
    """F2.export_matches_geometry for one body: the mesh read back is the body's solid.

    It gates the STL encoding against the Body's own intended solid: the x and y bounds
    of its cells, z = body.z_range_mm, volume = body.expected_volume_mm3, with
    tdmg.flat.export_match's float32-storage tolerances and the intended solid's surface
    area body.surface_mm2 (its tops, bottoms and the walls that prism_mesh builds). It
    does not see T or d: those are checked by F4.color_partition's volume and by the
    body tests (z ranges 0..T and T - d..T).
    """
    bounds = shapely.total_bounds(np.asarray(body.parts, dtype=object))
    return export_match(mesh, [float(v) for v in bounds],
                        [float(v) for v in body.z_range_mm], body.expected_volume_mm3,
                        body.surface_mm2)


def _same_cells(bodies: list[Body], cells: Cells) -> None:
    inlays = sorted(set(cells.labels) - {cells.base_index})
    expected = [("base", cells.base_index, cells.cells)] + [
        (f"color-{c}", c, tuple(cells.of(c))) for c in inlays]
    got = [(b.name, b.index, b.parts) for b in bodies]
    if len(got) != len(expected) or any(
            g[:2] != e[:2] or len(g[2]) != len(e[2])
            or any(a is not b and not a.equals_exact(b, 0) for a, b in zip(g[2], e[2]))
            for g, e in zip(got, expected)):
        raise ColorCheckError(
            f"the bodies are not ams_bodies of these cells: expected "
            f"{[e[:2] for e in expected]} with their cells, got {[g[:2] for g in got]}")


def ams_checks(bodies: list[Body], cells: Cells, thickness_mm, *, colors, palette_cap,
               printer: PrinterProfile, rules: dict) -> dict:
    """Gate the AMS bodies on the STL bytes that will be written.

    For each body: its STL (tdmg.flat.encode_stl) is parsed back and merged exactly
    (tdmg.checks.merge_exact), then gets topology_checks and body_export_check.
    Returns {"bodies": {name: [CheckResult]}, "assembly": [F4.color_partition,
    F4.filaments, F2.fits_build_volume on the extents of all gated meshes together,
    F5.triangles on their total triangles (one plate)], "stl": {name: bytes}}: the writer
    writes exactly the gated bytes.

    Refused (ColorCheckError): no bodies, or bodies not built from these cells. They must
    be ams_bodies(cells): the base first with every cell as its parts, then one inlay per
    non-base label, ascending, each with exactly that label's cells (cells.of).
    """
    cells = _cells(cells)
    if not bodies:
        raise ColorCheckError("no bodies to check")
    _same_cells(bodies, cells)
    per_body, stl, gated = {}, {}, []
    for body in bodies:
        data = encode_stl(body.mesh)
        mesh = merge_exact(trimesh.load(io.BytesIO(data), file_type="stl", process=False))
        per_body[body.name] = topology_checks(mesh) + [body_export_check(mesh, body)]
        stl[body.name] = data
        gated.append(mesh)
    offsets = np.cumsum([0] + [len(m.vertices) for m in gated[:-1]])
    plate = trimesh.Trimesh(
        np.vstack([np.asarray(m.vertices, dtype=np.float64) for m in gated]),
        np.vstack([np.asarray(m.faces, dtype=np.int64) + o
                   for m, o in zip(gated, offsets, strict=True)]),
        process=False, validate=False)
    assembly = [color_partition_check(cells, bodies, thickness_mm),
                filaments_check(bodies, colors=colors, palette_cap=palette_cap),
                build_volume_check(plate, printer), triangle_check(plate, rules)]
    return {"bodies": per_body, "assembly": assembly, "stl": stl}

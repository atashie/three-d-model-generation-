"""Gate checks for colored flat geometry (docs/plans/2026-11-12-color-geometry.md, Decision 9).

AMS output: tdmg.color_geometry.color_cells cuts the silhouette into labelled cells on the
storage grid, and ams_bodies meshes a base body and one inlay body per color from them.
ams_checks gates them as tdmg.flat.make_flat gates its single body: each body's STL bytes
are parsed back and merged exactly, then get the F1 topology checks and their own
F2.export_matches_geometry; the assembly gets F4.color_partition, F4.filaments,
F2.fits_build_volume on all bodies together and F5.triangles on their sum (one plate).
Glue output (tdmg.color_glue.glue_geometry): glue_checks gives each body (the glue base,
each color's pieces) the same per-body checks, each plate (the base; each color)
F2.fits_build_volume and F5.triangles, and the assembly F4.glue_partition and
F4.glue_fit. Not here: F3.thin_regions per body (information), F6 (UNKNOWN until
slicing) and the verdict are added by make_colored_flat in Task 6.
The multicolor 3MF (docs/plans/2026-11-12-color-3mf.md, Decision 4): export_3mf_check
(F2.export_3mf_matches_bodies) reads model.3mf back with lib3mf and compares it with the
gated AMS meshes; make_colored_flat adds it to the AMS assembly checks.
"""

from __future__ import annotations

import io
from itertools import pairwise

import lib3mf
import numpy as np
import shapely
import trimesh

from tdmg.checks import CheckResult, merge_exact, topology_checks
from tdmg.color_geometry import (
    PINCH_K,
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
from tdmg.color_glue import Glue
from tdmg.flat import build_volume_check, encode_stl, export_match, triangle_check
from tdmg.profiles import PrinterProfile
from tdmg.threemf import OBJECT_NAME, UNIT, Shell, check_shells, color_3mf, shell_ranges


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


def mesh_section(mesh: trimesh.Trimesh, z: float):
    """The mesh's cross-section at height z, as a polygonal geometry (possibly empty).

    Exact triangle-plane intersection: a vertex is above when its z >= z, an edge crosses
    when one end is above and the other is not, and its crossing point is a + t (b - a),
    t = (z - z_a) / (z_b - z_a), computed with the edge's ends in index order (a < b),
    so the two triangles that share an edge get the same point, bit for bit. A triangle
    with crossing edges has exactly two; their points make one segment. The segments are
    noded (shapely.union_all) and shapely.build_area makes the polygons, holes by nesting
    (even-odd). On an edge whose ends share x and y (a vertical wall edge, every
    prism_mesh wall has them) the point is exactly that x, y, since b - a is 0 there; on
    a wall's diagonal it lies within ULPS x eps x max|coordinate| of the edge's x, y
    segment (body_export_check gives the bound).
    """
    v = np.asarray(mesh.vertices, dtype=np.float64)
    f = np.asarray(mesh.faces, dtype=np.int64)
    if not len(f):
        return shapely.GeometryCollection()
    above = v[:, 2] >= z
    ends = np.stack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]], axis=1)  # (n, 3, 2)
    ends = np.sort(ends, axis=2)
    a, b = ends[..., 0], ends[..., 1]
    crossing = above[a] != above[b]
    count = crossing.sum(axis=1)
    if not count.any():
        return shapely.GeometryCollection()
    hit = count == 2  # 0 or 2 by parity; anything else cannot occur
    if np.any((count != 0) & ~hit):
        raise ColorCheckError("a triangle crosses the section plane on one edge only")
    a, b, crossing = a[hit], b[hit], crossing[hit]
    va, vb = v[a], v[b]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (z - va[..., 2]) / (vb[..., 2] - va[..., 2])  # nan on edges that do not cross
        points = va[..., :2] + t[..., None] * (vb[..., :2] - va[..., :2])  # (k, 3, 2)
    order = np.argsort(~crossing, axis=1, kind="stable")[:, :2]  # the two crossing edges
    segments = np.take_along_axis(points, order[..., None], axis=1)  # (k, 2, 2)
    segments = segments[np.any(segments[:, 0] != segments[:, 1], axis=1)]
    if not len(segments):
        return shapely.GeometryCollection()
    lines = shapely.union_all(shapely.linestrings(segments))
    return shapely.build_area(lines)


def occupancy_rows(mesh: trimesh.Trimesh, body: Body) -> list[dict]:
    """Per z interval of the body, the mesh's section against the body's footprint.

    The intervals are those between consecutive z levels of the body's slabs, so each
    cell either covers an interval or does not; the footprint there is the union of the
    cells that cover it. See body_export_check for the cut height and the tolerance.
    """
    levels = sorted({z for _, z0, z1 in body.slabs for z in (z0, z1)})
    cells = [(c, z0, z1) for group, z0, z1 in body.slabs for c in group]
    rows = []
    for lo, hi in pairwise(levels):
        z = (lo + hi) / 2
        footprint = _union([c for c, z0, z1 in cells if z0 <= lo and hi <= z1])
        section = mesh_section(mesh, z)
        dist = vertex_dist([g for g in (footprint, section) if not g.is_empty])
        tol = 2 * (float(section.length) + float(footprint.length)) * dist
        diff = float(shapely.symmetric_difference(section, footprint).area)
        rows.append({"z_range_mm": [lo, hi], "z_mm": z,
                     "mesh_area_mm2": float(section.area),
                     "expected_area_mm2": float(footprint.area),
                     "symmetric_difference_mm2": diff, "area_tol_mm2": tol,
                     "pass": diff <= tol})
    return rows


def body_export_check(mesh: trimesh.Trimesh, body: Body) -> CheckResult:
    """F2.export_matches_geometry for one body: the mesh read back is the body's solid.

    It gates the STL encoding against the Body's own intended solid:
    - the x and y bounds of its cells, z = body.z_range_mm, volume =
      body.expected_volume_mm3, with tdmg.flat.export_match's float32-storage tolerances
      and the intended solid's surface area body.surface_mm2 (its tops, bottoms and the
      walls that prism_mesh builds);
    - occupancy (Codex review 3: bounds and volume miss a component moved inside the
      bounds): for every z interval between consecutive levels of the body's slabs, the
      mesh's section at mid-height (mesh_section) against the body's footprint there
      (the union of the cells covering the interval); measured["occupancy"] has one row
      per interval with the symmetric-difference area and its tolerance.
    The occupancy tolerance (derived, not a rule): the cells' x, y are on the storage
    grid, which float32 holds exactly (tdmg.color_geometry.storage_grid_mm), so STL
    storage changes only z, and the mid-height cut, far from every float32-rounded level,
    does not see z. The section's vertices are then the cells' own vertices, exact, plus
    one crossing point per wall diagonal, computed as p + t (q - p): q - p is exact
    (grid multiples), and the product and the sum are rounded once each, so the point is
    within 1.5 eps max|coordinate| per axis, under DIST = ULPS x eps x max|coordinate|
    (tdmg.color_geometry.vertex_dist), of its wall's x, y edge. That moves area by at
    most the section's length x DIST / 2; the overlay's rounding is at most (the
    section's length + the footprint's length) x DIST, as in F4.color_partition.
    area_tol_mm2 = 2 (section length + footprint length) DIST covers both. PASS iff the
    bounds, the volume and every interval are within their tolerances. It does not see
    T or d: those are checked by F4.color_partition's volume and by the body tests
    (z ranges 0..T and T - d..T).
    """
    bounds = shapely.total_bounds(np.asarray(body.parts, dtype=object))
    base = export_match(mesh, [float(v) for v in bounds],
                        [float(v) for v in body.z_range_mm], body.expected_volume_mm3,
                        body.surface_mm2)
    rows = occupancy_rows(mesh, body)
    ok = base.status == "PASS" and all(r["pass"] for r in rows)
    return CheckResult(
        base.id, "PASS" if ok else "FAIL", base.measured | {"occupancy": rows},
        base.threshold | {"occupancy_area_tol_mm2": [r["area_tol_mm2"] for r in rows]},
        None, "tolerances cover float32 storage in the STL only, and float64 rounding "
              "for the occupancy (each z interval's mid-height section against the "
              "cells covering it); derived, not rules")


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
    F5.triangles on their total triangles (one plate)], "stl": {name: bytes}, "meshes":
    {name: the gated mesh}}: the writer writes exactly the gated bytes, and the meshes
    are those bytes parsed back and merged, for the record's summaries.

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
    meshes = {body.name: mesh for body, mesh in zip(bodies, gated, strict=True)}
    return {"bodies": per_body, "assembly": assembly, "stl": stl, "meshes": meshes}


# --- the multicolor 3MF (docs/plans/2026-11-12-color-3mf.md, Decision 4) ----------------


def _bad_directed_edges(faces: np.ndarray) -> int:
    """Directed edges that do not occur exactly once with their reverse exactly once.

    0 means closed (every edge in exactly two triangles) and consistently oriented, by
    vertex index: tdmg.checks' F1.consistent_orientation test, vectorised. Each face
    with a repeated index also counts as bad, so the result does not rely on F1's
    no_degenerate_faces: (a, a, b) alone would pass the pairing ((a, a) is its own
    reverse).
    """
    faces = np.asarray(faces, dtype=np.int64)
    a, b, c = faces[:, 0], faces[:, 1], faces[:, 2]
    repeated = int(np.count_nonzero((a == b) | (b == c) | (c == a)))
    n = int(faces.max()) + 1
    directed = faces[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
    keys, counts = np.unique(directed[:, 0] * n + directed[:, 1], return_counts=True)
    reverse = (keys % n) * n + keys // n
    pos = np.minimum(np.searchsorted(keys, reverse), len(keys) - 1)
    ok = (counts == 1) & (keys[pos] == reverse) & (counts[pos] == 1)
    return int(np.count_nonzero(~ok)) + repeated


def _read_3mf(data: bytes) -> dict:
    """The facts export_3mf_check compares, read by lib3mf (strict mode) from the bytes."""
    wrapper = lib3mf.get_wrapper()
    model = wrapper.CreateModel()
    reader = model.QueryReader("3mf")
    reader.SetStrictModeActive(True)
    reader.ReadFromBuffer(data)
    facts = {"reader_warnings": [reader.GetWarning(i)[1]
                                 for i in range(reader.GetWarningCount())],
             "unit": lib3mf.ModelUnit(model.GetUnit()).name}
    objects, meshes = [], []
    it = model.GetObjects()
    while it.MoveNext():
        o = it.GetCurrentObject()
        objects.append(o)
        if o.IsMeshObject():
            meshes.append(model.GetMeshObjectByID(o.GetResourceID()))
    facts["objects"] = len(objects)
    facts["mesh_objects"] = len(meshes)
    items = []
    bi = model.GetBuildItems()
    while bi.MoveNext():
        item = bi.GetCurrent()
        items.append({"object_id": item.GetObjectResourceID(),
                      "transform": item.HasObjectTransform()})
    facts["build_items"] = len(items)
    groups = {}
    cg = model.GetColorGroups()
    while cg.MoveNext():
        g = cg.GetCurrentColorGroup()
        groups[g.GetUniqueResourceID()] = {
            pid: g.GetColor(pid) for pid in g.GetAllPropertyIDs()}
    facts["color_groups"] = len(groups)
    if len(meshes) == 1:
        mo = meshes[0]
        facts["object_name"] = mo.GetName()
        facts["object_type"] = lib3mf.ObjectType(mo.GetType()).name
        facts["item_ok"] = (len(items) == 1 and items[0]["object_id"] == mo.GetResourceID()
                            and not items[0]["transform"])
        facts["manifold_and_oriented"] = bool(mo.IsManifoldAndOriented())
        facts["_v"] = np.array([p.Coordinates[:] for p in mo.GetVertices()],
                               dtype=np.float32).reshape(-1, 3)
        facts["_f"] = np.array([t.Indices[:] for t in mo.GetTriangleIndices()],
                               dtype=np.int64).reshape(-1, 3)
        colors = []
        for p in mo.GetAllTriangleProperties():
            ids = set(p.PropertyIDs[:])
            group = groups.get(p.ResourceID)
            if group is None or len(ids) != 1 or next(iter(ids)) not in group:
                colors.append(None)
            else:
                c = group[next(iter(ids))]
                colors.append(f"#{c.Red:02X}{c.Green:02X}{c.Blue:02X}{c.Alpha:02X}")
        facts["_colors"] = colors
    return facts


def export_3mf_check(data: bytes, shells: list[Shell]) -> CheckResult:
    """F2.export_3mf_matches_bodies: the 3MF carries the gated AMS bodies unchanged.

    shells: the tdmg.threemf.Shell of each AMS body, built from its gated mesh (its STL
    bytes parsed back and merged exactly), base first, then inlays by index. data is
    read back by lib3mf 2.x in strict mode, an independent reader (from the bytes; no
    file). PASS iff:
    - no reader warnings; unit millimeter; exactly one object, a mesh of type model named
      tdmg.threemf.OBJECT_NAME; exactly one build item, on that object, with no
      transform; one color group;
    - the object's vertices and triangles split into the shells in order
      (tdmg.threemf.shell_ranges): shell i's vertices equal its gated mesh's vertices
      exactly, compared as float32 arrays in the same order (both sides are float32
      numbers, so exact equality is the test, no tolerance), and its triangles, minus
      its vertex offset, equal the gated mesh's faces exactly; so every triangle uses
      only its own shell's vertices;
    - each shell is closed and consistently oriented by index (every directed edge once,
      its reverse once, and no face repeats an index: bad_directed_edges 0), and
      lib3mf's IsManifoldAndOriented holds for the whole object;
    - every triangle's color (its pid's color group, p1 = p2 = p3) is its shell's
      palette color, tdmg.threemf.color_3mf(hex).
    F1 and the occupancy check gate the bodies themselves; this only proves the 3MF
    carries them. Errors: shells that tdmg.threemf.check_shells refuses raise
    ThreeMFError (a caller error), and a missing lib3mf native library raises when this
    module is imported (an environment error); anything wrong with data itself, including
    bytes lib3mf cannot read, is a FAIL with what was measured. The shells touch along
    shared walls, which the 3MF core covers only as a self-intersection warning (rule
    format.3mf.self_intersection_is_warning).
    """
    arrays = check_shells(shells)
    ranges = shell_ranges(shells)
    expected = {"unit": UNIT, "objects": 1, "build_items": 1, "color_groups": 1,
                "object_name": OBJECT_NAME, "object_type": "Model",
                "shells": [{"name": s.name, "color": color_3mf(s.hex), **r}
                           for s, r in zip(shells, ranges, strict=True)],
                "vertices": ranges[-1]["vertices"][1],
                "triangles": ranges[-1]["triangles"][1]}
    note = ("read back by lib3mf (strict mode) from the bytes; vertices compared exactly "
            "as float32, triangles exactly, per shell in order; closed and oriented per "
            "shell by index; colors per triangle. The shells touch along shared walls: a "
            "self-intersection warning in the 3MF core (rule "
            "format.3mf.self_intersection_is_warning)")
    try:
        facts = _read_3mf(data)
    except (lib3mf.ELib3MFException, ValueError) as exc:   # not a readable 3MF
        return CheckResult("F2.export_3mf_matches_bodies", "FAIL",
                           {"read_error": str(exc)}, expected, None, note)
    v, f, colors = facts.pop("_v", None), facts.pop("_f", None), facts.pop("_colors", None)
    measured = {k: facts.get(k) for k in (
        "reader_warnings", "unit", "objects", "mesh_objects", "build_items", "item_ok",
        "color_groups", "object_name", "object_type", "manifold_and_oriented")}
    ok = (not facts["reader_warnings"] and facts["unit"].lower() == UNIT
          and facts["objects"] == 1 and facts["mesh_objects"] == 1
          and facts.get("item_ok") is True and facts["build_items"] == 1
          and facts["color_groups"] == 1 and facts.get("object_name") == OBJECT_NAME
          and facts.get("object_type") == "Model"
          and facts.get("manifold_and_oriented") is True)
    rows = []
    if v is not None:
        measured["vertices"], measured["triangles"] = len(v), len(f)
        ok = ok and len(v) == expected["vertices"] and len(f) == expected["triangles"]
        for s, (sv, sf), r in zip(shells, arrays, ranges, strict=True):
            v0, v1 = r["vertices"]
            t0, t1 = r["triangles"]
            got_v, got_f = v[v0:v1], f[t0:t1] - v0
            same_v = got_v.shape == sv.shape and bool(np.array_equal(got_v, sv))
            same_f = got_f.shape == sf.shape and bool(np.array_equal(got_f, sf))
            own = bool(len(got_f)) and bool(((got_f >= 0) & (got_f < v1 - v0)).all())
            bad = _bad_directed_edges(got_f) if own else None
            want = color_3mf(s.hex)
            got_c = colors[t0:t1]
            wrong = sum(1 for c in got_c if c != want) + (t1 - t0 - len(got_c))
            row = {"name": s.name, "vertices_equal": same_v, "triangles_equal": same_f,
                   "own_vertices_only": own, "bad_directed_edges": bad,
                   "color": want, "wrong_color_triangles": wrong}
            row["pass"] = same_v and same_f and own and bad == 0 and wrong == 0
            ok = ok and row["pass"]
            rows.append(row)
    else:
        ok = False
    measured["shells"] = rows
    return CheckResult("F2.export_3mf_matches_bodies", "PASS" if ok else "FAIL", measured,
                       expected, None, note)


# --- glue route (Decision 9, F4.glue_fit) -----------------------------------------------


def glue_fit_margin(grid_mm: float, *, pinch_joined: bool = False,
                    rounding_mm: float = 0.0) -> dict:
    """How far below the clearance c a correct piece's gap to its pocket wall can be.

    Derived, not a rule. tdmg.color_glue.glue_geometry builds every piece, before the
    grid, at least c - DIST from its pocket's wall by construction (the clearance fix:
    pieces are eroded, and the kept pieces' outward buffer grown, by their measured
    shortfalls; the leftover is clipped to outside that buffer). So the margin has no
    chord-error term (an earlier version allowed c (1 - cos(pi / (4 QUAD_SEGS))) and the
    opening's r (1 - cos(pi / (4 QUAD_SEGS))), which GEOS does not guarantee: it draws a
    shallow arc with one chord; Codex review 3). The bounds added:
    - Piece snap, snap_move_mm(G) = G sqrt(2)/2: shapely.set_precision moves each
      piece's boundary by at most this.
    - Pocket snap, snap_move_mm(G) again: the pockets are rebuilt by color_cells (one
      snap-rounded noding of the pockets' and the base's boundaries), which moves the
      pocket boundary by at most this. When that rebuild joined a pinch (pinch_joined),
      a diamond of radius PINCH_K G can move it further, so PINCH_K G is added too.
    - rounding_mm: float64 rounding, passed by glue_fit_check as 3 DIST (DIST = ULPS x
      eps x max|coordinate| of the gridded S, tdmg.color_geometry.vertex_dist): the
      clearance fix accepts gaps down to c - DIST, and the pocket's two overlays (the
      leftover's clip and the candidate minus it) move its vertices by at most DIST each.
      About 1e-13 mm at 60 mm, far below the snaps (3e-6 mm at 60 mm).
    """
    snap = snap_move_mm(grid_mm)
    pocket = snap + (PINCH_K * grid_mm if pinch_joined else 0.0)
    rounding = float(rounding_mm)
    return {"margin_mm": snap + pocket + rounding, "snap_move_mm": snap,
            "pocket_move_mm": pocket, "rounding_mm": rounding}


def _glue(glue) -> Glue:
    if not isinstance(glue, Glue):
        raise ColorCheckError(f"glue must be a tdmg.color_glue.Glue, got "
                              f"{type(glue).__name__}")
    return glue


def glue_fit_check(glue: Glue) -> CheckResult:
    """F4.glue_fit: every piece lies inside its pocket, at least clearance - margin from
    its wall.

    Per piece: gap_mm = shapely.distance(piece, boundary of its pocket), both on the grid,
    inside = shapely.contains_properly(pocket, piece) and same_color = (the pocket's color
    is the piece's). PASS iff every piece is inside, in a pocket of its color,
    with gap_mm >= clearance_mm - margin_mm (glue_fit_margin, with pinch_joined when the
    rebuilt cells have pinch fixes, and rounding_mm = 3 vertex_dist of the gridded S) and
    every pocket has a piece (empty_pockets lists the
    numbers of those that do not: a hole nothing fills). A piece in no pocket (number 0)
    FAILs. No pieces and no pockets: PASS, with min_gap_mm None. Reports the smallest gap
    overall and per piece.
    """
    glue = _glue(glue)
    margin = glue_fit_margin(glue.grid_mm, pinch_joined=bool(glue.cells.pinch_fixes),
                             rounding_mm=3 * vertex_dist([glue.cells.silhouette]))
    limit = glue.clearance_mm - margin["margin_mm"]
    by_number = {p.number: p for p in glue.pockets}
    filled = {piece.pocket for piece in glue.pieces}
    empty = [p.number for p in glue.pockets if p.number not in filled]
    rows, ok = [], not empty
    for piece in glue.pieces:
        if piece.pocket not in by_number:
            ok = False
            rows.append({"number": piece.number, "index": piece.index, "pocket": 0,
                         "gap_mm": None, "inside": False, "same_color": False,
                         "pass": False})
            continue
        pocket = by_number[piece.pocket]
        gap = float(shapely.distance(piece.polygon, pocket.polygon.boundary))
        inside = bool(shapely.contains_properly(pocket.polygon, piece.polygon))
        same = pocket.index == piece.index
        passed = inside and same and gap >= limit
        ok = ok and passed
        rows.append({"number": piece.number, "index": piece.index, "pocket": piece.pocket,
                     "gap_mm": gap, "inside": inside, "same_color": same,
                     "pass": passed})
    gaps = [r["gap_mm"] for r in rows if r["gap_mm"] is not None]
    pinch = (f"; plus PINCH_K x G = {PINCH_K} G for the pocket, since the rebuild joined "
             f"{len(glue.cells.pinch_fixes)} pinches" if glue.cells.pinch_fixes else "")
    return CheckResult(
        "F4.glue_fit", "PASS" if ok else "FAIL",
        {"pieces": len(rows), "min_gap_mm": min(gaps) if gaps else None,
         "empty_pockets": empty, "per_piece": rows},
        {"min_gap_mm": limit, "clearance_mm": glue.clearance_mm} | margin,
        "color.glue.clearance_mm",
        f"threshold is the clearance minus a derived margin (the piece's and the "
        f"pocket's snap to the grid, G sqrt(2)/2 each{pinch}, and float64 rounding, 3 x "
        "ULPS x eps x max|coordinate|); glue_geometry builds each piece at least the "
        "clearance from its pocket's wall before the grid; every piece needs a pocket "
        "of its color and every pocket a piece")


def glue_partition_check(glue: Glue) -> CheckResult:
    """F4.glue_partition: the rebuilt cells still tile S, the pockets do not overlap, and
    the glue base's volume adds up. The glue counterpart of F4.color_partition.

    S here is the rebuild's input, glue.cells.raw_silhouette: the gridded S of the AMS
    cells, which F4.color_partition gates against the raw silhouette. Measures:
    - snap_silhouette_mm2: area of union(glue.cells.cells) XOR that S, within
      snap_silhouette_mm2 = tube_area_bound(S, G sqrt(2)/2) + its raw area tolerance +
      the bound_mm2 of every pinch fix the rebuild made where S clips its diamond: the
      bound F4.color_partition uses for S, for this one noding;
    - overlap_mm2: total pairwise intersection area of the pocket polygons, within
      area_tol_mm2 (partition_tolerance of the rebuilt cells: float64 overlay rounding);
    - outside_mm2: total area of the pockets outside S, within snap_silhouette_mm2;
    - volume_error_mm3: |the glue base's expected volume - (area(S) x T - sum of the
      pockets' areas x d)|, within (snap_silhouette_mm2 + area_tol_mm2) x T: the cells'
      area differs from area(S) by at most the snap bound, and the pockets' unions from
      their cells by at most area_tol, times d < T.
    PASS iff every measure is within its threshold. The meshed volume is gated against
    the expected one by the base's F2.export_matches_geometry.
    """
    glue = _glue(glue)
    cells = glue.cells
    raw_s = cells.raw_silhouette
    raw_tol, _ = _area_tol([p for _, p in cells.raw_pieces], raw_s)
    area_tol, dist = partition_tolerance(cells)
    d = snap_move_mm(cells.grid_mm)
    union = _union(list(cells.cells))
    snap_s = float(shapely.symmetric_difference(union, raw_s).area)
    snap_bound = (tube_area_bound([raw_s], d) + raw_tol
                  + sum(f["bound_mm2"] for f in cells.pinch_fixes if f["clipped"]))
    pockets = [p.polygon for p in glue.pockets]
    overlap = _overlap(pockets)
    outside = float(sum(shapely.difference(p, raw_s).area for p in pockets))
    base = next(b for b in glue.bodies if b.name == "base")
    expected = (float(raw_s.area) * glue.thickness_mm
                - float(sum(p.area for p in pockets)) * glue.skin_mm)
    volume_error = abs(base.expected_volume_mm3 - expected)
    volume_tol = (snap_bound + area_tol) * glue.thickness_mm
    ok = (snap_s <= snap_bound and overlap <= area_tol and outside <= snap_bound
          and volume_error <= volume_tol)
    return CheckResult(
        "F4.glue_partition", "PASS" if ok else "FAIL",
        {"cells": len(cells.cells), "pockets": len(pockets), "snap_silhouette_mm2": snap_s,
         "overlap_mm2": overlap, "outside_mm2": outside,
         "base_volume_mm3": base.expected_volume_mm3, "volume_error_mm3": volume_error},
        {"snap_silhouette_mm2": snap_bound, "area_tol_mm2": area_tol,
         "vertex_dist_mm": dist, "snap_move_mm": d, "volume_tol_mm3": volume_tol,
         "expected_volume_mm3": expected},
        None, "tolerances are derived, not rules: snap rounding (the area within "
              "G sqrt(2)/2 of S's boundary, plus clipped pinch diamonds) and float64 "
              "overlay rounding, as for F4.color_partition")


def glue_checks(glue: Glue, *, printer: PrinterProfile, rules: dict) -> dict:
    """Gate the glue bodies on the STL bytes that will be written.

    For each body (the glue base, then each color's pieces): its STL (tdmg.flat.
    encode_stl) is parsed back and merged exactly, then gets topology_checks and
    body_export_check. Each body is its own plate: F2.fits_build_volume and F5.triangles
    on its gated mesh. Returns {"bodies": {name: [CheckResult]}, "plates": {name:
    [F2.fits_build_volume, F5.triangles]}, "assembly": [F4.glue_partition, F4.glue_fit],
    "stl": {name: bytes}, "meshes": {name: the gated mesh}}: the writer writes exactly
    the gated bytes.
    """
    glue = _glue(glue)
    per_body, plates, stl, meshes = {}, {}, {}, {}
    for body in glue.bodies:
        data = encode_stl(body.mesh)
        mesh = merge_exact(trimesh.load(io.BytesIO(data), file_type="stl", process=False))
        per_body[body.name] = topology_checks(mesh) + [body_export_check(mesh, body)]
        plates[body.name] = [build_volume_check(mesh, printer), triangle_check(mesh, rules)]
        stl[body.name] = data
        meshes[body.name] = mesh
    return {"bodies": per_body, "plates": plates,
            "assembly": [glue_partition_check(glue), glue_fit_check(glue)], "stl": stl,
            "meshes": meshes}

"""What the slicer prints, read from its G-code, against the model (F3, thin features).

Ported from research/verification/2026-11-10-thin-walls/measure_coverage.py (the research
record's README gives the method and its results), as library code that refuses what it
does not understand instead of skipping it:

- parse_gcode: the extruding moves per layer, from OrcaSlicer's "; Z_HEIGHT:",
  "; LAYER_HEIGHT:", "; FEATURE:" and "; LINE_WIDTH:" comments, relative extrusion (M83)
  and G1 moves with G2/G3 arcs in the I/J centre form. Anything it cannot read raises
  UnsupportedGcode; the checks turn that into UNKNOWN, never PASS.
- footprint: the printed area of a layer. Every extruding move is a "bead": a line of its
  stated width with round ends. This approximates real squashed plastic.
- model_section: the model's outline at a height, from the STL as stored.
- align: where the slicer put the model (it centres it and may turn it by quarter turns).
- layer_metrics: per layer, the largest distance from the model's edge to printed plastic,
  and the parts and holes of the model and of the footprint.
- f3_checks: F3.printed_connectivity and F3.edge_coverage for tdmg slice, by the rule the
  owner approved (docs/plans/2026-11-10-thin-wall-policy.md, Decision 2).

Holes: a region the footprint encloses but does not print is a hole of the print only if
it is not inside the model section. Sparse infill leaves many such voids inside the model,
by design, and they are not holes. A hole of the model must stay open in the print.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import shapely
import trimesh
from scipy.spatial import cKDTree
from shapely import affinity

from tdmg.checks import CheckResult

# Arcs are split into chords whose arc length is at most this. An approximation step, not
# a threshold: a chord of length c lies at most r - sqrt(r^2 - c^2/4) inside an arc of
# radius r, which is at most c / 2 = 0.025 mm (when r = c / 2) and about c^2 / (8 r) for
# larger arcs (0.0003 mm at r = 1 mm). The beads move by no more than that.
ARC_STEP_MM = 0.05
# Model edges are sampled at this spacing for the edge-to-plastic distance (the research
# record's value). A sampling resolution, not a threshold. Distance to the footprint is
# 1-Lipschitz along the edge, so the true largest gap is at most the sampled largest gap
# plus EDGE_SAMPLE_MM / 2 (0.025 mm): a sampled gap within that of the allowance could
# hide a true gap just over it. The rule is stated on the samples (the plan, Decision 2).
EDGE_SAMPLE_MM = 0.05
# Bead ends and joins are polygons with this many segments per quarter circle (the
# research record's value). Their vertices lie on the circle, so the polygon is inside the
# true bead: plastic is under-counted by at most r (1 - cos(pi / 8)), 0.016 mm for a
# 0.42 mm line, which can only make a gap look larger.
QUAD_SEGS = 4
# Alignment refinement: at most this many nearest-point steps, stopping when a step moves
# the model less than ALIGN_CONVERGED_MM. Numerical settings of the fit, not thresholds:
# 1e-6 mm is far below any printed size. A fit that has not converged is UNKNOWN.
ALIGN_STEPS = 100
ALIGN_CONVERGED_MM = 1e-6
QUARTER_TURNS = (0, 90, 180, 270)
CUSTOM = "Custom"            # OrcaSlicer's feature name for the start and end code
OUTER_WALL = "Outer wall"
CONNECTIVITY = "F3.printed_connectivity"
COVERAGE = "F3.edge_coverage"
F3_SLICE_CHECK_IDS = (CONNECTIVITY, COVERAGE)
TOLERANCE_RULE = "acceptance.dimension.tolerance"
ELEPHANT_FOOT_KEY = "elefant_foot_compensation"      # OrcaSlicer's spelling
SCOPE = ("The bead model (each extrusion a line of its stated width with round ends) "
         "approximates real plastic. Strength is not judged: a single thin line is printed "
         "but may be fragile. Measured for the pinned OrcaSlicer and A1 profile only.")


class UnsupportedGcode(ValueError):
    """The G-code, or the alignment, has something this module cannot measure."""


class Segment(NamedTuple):
    x0: float
    y0: float
    x1: float
    y1: float
    width: float
    feature: str


@dataclass(frozen=True)
class Layer:
    z: float                    # "; Z_HEIGHT:", the top of the layer
    height: float               # "; LAYER_HEIGHT:"
    segments: list[Segment]

    @property
    def mid_z(self) -> float:
        """The layer's mid-height, where the model is cut for this layer."""
        return self.z - self.height / 2


def _comment_value(line: str, lineno: int) -> float:
    text = line.split(":", 1)[1].strip()
    try:
        value = float(text)
    except ValueError:
        raise UnsupportedGcode(f"line {lineno}: {line!r} has no number") from None
    if not math.isfinite(value):
        raise UnsupportedGcode(f"line {lineno}: {line!r} is not finite")
    return value


def _words(code: str, lineno: int) -> dict[str, float]:
    words = {}
    for word in code.split()[1:]:
        letter, text = word[0].upper(), word[1:]
        try:
            words[letter] = float(text)
        except ValueError:
            raise UnsupportedGcode(f"line {lineno}: cannot read {word!r} in {code!r}") from None
    return words


def _arc(x, y, nx, ny, words, clockwise) -> list[tuple[float, float]]:
    """The chord ends of a G2/G3 arc in the I/J centre form, ending exactly at (nx, ny).

    The sweep follows the usual firmware convention (Marlin's plan_arc): the arc turns
    clockwise for G2 and anticlockwise for G3 from the start to the end angle, and a start
    equal to the end is a full circle.
    """
    cx, cy = x + words.get("I", 0.0), y + words.get("J", 0.0)
    r = math.hypot(x - cx, y - cy)
    a0, a1 = math.atan2(y - cy, x - cx), math.atan2(ny - cy, nx - cx)
    if clockwise:
        while a1 >= a0:
            a1 -= 2 * math.pi
    else:
        while a1 <= a0:
            a1 += 2 * math.pi
    n = max(2, math.ceil(abs(a1 - a0) * r / ARC_STEP_MM))
    pts = [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cy + r * math.sin(a0 + (a1 - a0) * k / n))
           for k in range(1, n)]
    return [*pts, (nx, ny)]


def parse_gcode(text: str) -> dict[float, Layer]:
    """{z: Layer} for every "; Z_HEIGHT:" layer, with its extruding moves.

    An extruding move is a G1, G2 or G3 with a positive E that moves in X or Y. Moves in
    FEATURE "Custom", the start and end code, are excluded; on the A1 that includes the
    purge line. Travel, retraction and unretraction (E with no X/Y motion) lay down no
    bead. G90/G91 (absolute and relative X/Y) and G92 are followed; G28 makes the position
    unknown until the next absolute X and Y.

    Raises UnsupportedGcode, outside Custom, for an extruding move: with absolute or unknown
    extrusion mode (M82, or no M83 yet), since E is then a position; before any Z_HEIGHT,
    LAYER_HEIGHT, FEATURE or LINE_WIDTH, or with a width that is not positive; from an
    unknown position; or as an arc in the R form, with a P (turns) word, or with neither I
    nor J. Also for G20 (inches) anywhere, and for G-code with no Z_HEIGHT layer at all.
    """
    relative_e = None                      # unknown until M82 or M83
    relative_xy = False
    x = y = None
    z = width = feature = None
    layers: dict[float, Layer] = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith(";"):
            tag = line[1:].lstrip()
            if tag.startswith("Z_HEIGHT:"):
                z = _comment_value(tag, lineno)
                if z not in layers:
                    layers[z] = Layer(z, math.nan, [])
            elif tag.startswith("LAYER_HEIGHT:") and z is not None:
                height = _comment_value(tag, lineno)
                if not height > 0:
                    raise UnsupportedGcode(f"line {lineno}: layer height {height} is not "
                                           "positive")
                layers[z] = Layer(z, height, layers[z].segments)
            elif tag.startswith("LINE_WIDTH:"):
                width = _comment_value(tag, lineno)
            elif tag.startswith("FEATURE:"):
                feature = tag.split(":", 1)[1].strip()
            continue
        code = line.split(";", 1)[0].strip()
        if not code:
            continue
        command = code.split()[0].upper()
        if command == "M82":
            relative_e = False
        elif command == "M83":
            relative_e = True
        elif command == "G90":
            relative_xy = False
        elif command == "G91":
            relative_xy = True
        elif command == "G20":
            raise UnsupportedGcode(f"line {lineno}: G20 (inch units) is not supported")
        elif command == "G28":
            x = y = None
        elif command == "G92":
            words = _words(code, lineno)
            x, y = words.get("X", x), words.get("Y", y)
        elif command in ("G0", "G1", "G2", "G3"):
            words = _words(code, lineno)
            if relative_xy:
                nx = None if x is None else x + words.get("X", 0.0)
                ny = None if y is None else y + words.get("Y", 0.0)
            else:
                nx, ny = words.get("X", x), words.get("Y", y)
            moves = (nx, ny) != (x, y) or (command in ("G2", "G3") and "E" in words)
            e = words.get("E", 0.0)
            if moves and e != 0.0 and feature != CUSTOM and relative_e is not True:
                raise UnsupportedGcode(f"line {lineno} ({code!r}): absolute extrusion (M82, "
                                       "or no M83 before it): only relative E is supported")
            if moves and e > 0 and feature != CUSTOM:
                _check_extrusion(f"line {lineno} ({code!r})", command, words, (x, y, nx, ny),
                                 z, layers, width, feature)
                if command == "G1" or command == "G0":
                    pts = [(nx, ny)]
                else:
                    pts = _arc(x, y, nx, ny, words, clockwise=command == "G2")
                px, py = x, y
                for qx, qy in pts:
                    if (qx, qy) != (px, py):
                        layers[z].segments.append(Segment(px, py, qx, qy, width, feature))
                    px, py = qx, qy
            x, y = nx, ny
    if not layers:
        raise UnsupportedGcode("no Z_HEIGHT layer: this is not OrcaSlicer G-code with layer "
                               "comments")
    return layers


def _check_extrusion(where, command, words, ends, z, layers, width, feature) -> None:
    if z is None:
        raise UnsupportedGcode(f"{where}: an extrusion before any Z_HEIGHT")
    if math.isnan(layers[z].height):
        raise UnsupportedGcode(f"{where}: layer {z} has no LAYER_HEIGHT")
    if feature is None:
        raise UnsupportedGcode(f"{where}: an extrusion before any FEATURE")
    if width is None or not width > 0:
        raise UnsupportedGcode(f"{where}: an extrusion without a positive LINE_WIDTH "
                               f"(it is {width})")
    if None in ends:
        raise UnsupportedGcode(f"{where}: an extrusion from an unknown position")
    if command in ("G2", "G3"):
        if "R" in words:
            raise UnsupportedGcode(f"{where}: R-form arcs are not supported")
        if "P" in words:
            raise UnsupportedGcode(f"{where}: arcs with a P (turns) word are not supported")
        if "I" not in words and "J" not in words:
            raise UnsupportedGcode(f"{where}: an arc with neither I nor J")


def footprint(segments: list[Segment]):
    """The union of every segment's bead: the segment buffered by half its width.

    Consecutive segments of one width that join end to end are buffered as one line: with
    round joins and ends that is the same union, and much faster.
    """
    if not segments:
        return shapely.Polygon()
    paths, widths = [], []
    for s in segments:
        if paths and widths[-1] == s.width and paths[-1][-1] == (s.x0, s.y0):
            paths[-1].append((s.x1, s.y1))
        else:
            paths.append([(s.x0, s.y0), (s.x1, s.y1)])
            widths.append(s.width)
    index = np.repeat(np.arange(len(paths)), [len(p) for p in paths])
    lines = shapely.linestrings(np.concatenate(paths), indices=index)
    beads = shapely.buffer(lines, np.asarray(widths) / 2, quad_segs=QUAD_SEGS)
    return shapely.union_all(beads)


def load_mesh(stl: bytes | trimesh.Trimesh) -> trimesh.Trimesh:
    if isinstance(stl, trimesh.Trimesh):
        return stl
    return trimesh.load(io.BytesIO(stl), file_type="stl", process=False)


def model_section(model: bytes | trimesh.Trimesh, z: float):
    """The model's cross-section at height z, in model x/y (empty if the plane misses it).

    Trimesh.section joins the cut segments into closed rings; it merges their ends within
    trimesh.tol.merge (1e-8), because the same cut point computed from two triangles can
    differ in the last bits. shapely.build_area then makes the area those rings enclose,
    nested rings alternating between solid and hole. (Path2D.polygons_full would need the
    optional rtree package.)
    """
    mesh = load_mesh(model)
    section = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if section is None:
        return shapely.Polygon()
    rings = [shapely.LinearRing(d[:, :2]) for d in section.discrete if len(d) >= 4]
    area = shapely.build_area(shapely.GeometryCollection(rings))
    return shapely.Polygon() if area.is_empty else area


@dataclass(frozen=True)
class Alignment:
    """Model x/y to bed x/y: turn by angle (degrees, anticlockwise) about centre, then shift."""
    angle: int
    centre: tuple[float, float]
    shift: tuple[float, float]
    median_edge_mm: float           # first layer: median model-edge-to-plastic distance

    def apply(self, geometry):
        turned = affinity.rotate(geometry, self.angle, origin=self.centre)
        return affinity.translate(turned, *self.shift)

    def to_bed(self, points: np.ndarray) -> np.ndarray:
        a = math.radians(self.angle)
        rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        c = np.asarray(self.centre)
        return (np.asarray(points) - c) @ rot.T + c + np.asarray(self.shift)

    def as_dict(self) -> dict:
        return {"angle_deg": self.angle, "centre_mm": list(self.centre),
                "shift_mm": list(self.shift), "median_edge_mm": self.median_edge_mm}


def _edge_points(geometry, spacing: float = EDGE_SAMPLE_MM) -> np.ndarray:
    return shapely.get_coordinates(shapely.segmentize(geometry.boundary, spacing))


def gaps(points: np.ndarray, printed) -> np.ndarray:
    """The distance from each point to the footprint: 0 inside it, else to its boundary.

    The same value as shapely.distance(points, printed), computed faster: a prepared
    point-in-polygon test, then an STRtree of the boundary's segments for the exact nearest
    segment of each point outside. Every point is at infinity from an empty footprint.
    """
    points = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    out = np.zeros(len(points))
    if printed.is_empty:
        out[:] = math.inf
        return out
    shapely.prepare(printed)
    outside = ~shapely.contains_xy(printed, points[:, 0], points[:, 1])
    if not outside.any():
        return out
    rings = shapely.get_rings(shapely.get_parts(printed))
    coords, index = shapely.get_coordinates(rings, return_index=True)
    joined = index[:-1] == index[1:]                 # consecutive vertices of one ring
    edges = shapely.linestrings(np.stack([coords[:-1][joined], coords[1:][joined]], axis=1))
    (which, _), dist = shapely.STRtree(edges).query_nearest(
        shapely.points(points[outside]), return_distance=True, all_matches=False)
    nearest = np.full(int(outside.sum()), math.inf)
    np.minimum.at(nearest, which, dist)
    out[outside] = nearest
    return out


def _wall_points(segments: list[Segment]) -> np.ndarray:
    walls = [s for s in segments if s.feature == OUTER_WALL]
    if not walls:
        raise UnsupportedGcode("the first layer has no Outer wall, so the model cannot be "
                               "aligned with the print")
    lines = shapely.linestrings([[(s.x0, s.y0), (s.x1, s.y1)] for s in walls])
    return shapely.get_coordinates(shapely.segmentize(lines, EDGE_SAMPLE_MM))


def align(model_first_layer, segments: list[Segment]) -> Alignment:
    """Where the slicer put the model, from the first layer's outer-wall centrelines.

    For each quarter turn about the section's centroid, the model is first moved so its
    bounding-box centre matches that of the outer-wall centrelines (the research method),
    and the turn with the smallest median model-edge-to-plastic distance is kept (the
    first on a tie). An unprinted feature at the model's extremity moves that bounding box,
    so the shift is then refined: each step moves the model by the mean vector from the
    nearest model-edge sample to each outer-wall sample. A closed outline's normals sum to
    zero, so a wall uniformly inside the edge (half a line, plus the first layer's
    elephant-foot shrink) gives no net pull, and a missing feature has no wall to pull.
    Raises UnsupportedGcode without an outer wall, or if the fit does not converge.
    A wrong alignment can only make edges look less covered; part and hole counts do not
    depend on it.
    """
    if model_first_layer.is_empty:
        raise UnsupportedGcode("the model has no section at the first layer")
    walls = _wall_points(segments)
    wx0, wy0 = walls.min(axis=0)
    wx1, wy1 = walls.max(axis=0)
    printed = footprint(segments)
    c = model_first_layer.centroid
    centre = (float(c.x), float(c.y))
    best = None
    for angle in QUARTER_TURNS:
        turned = affinity.rotate(model_first_layer, angle, origin=centre)
        mx0, my0, mx1, my1 = turned.bounds
        shift = ((wx0 + wx1 - mx0 - mx1) / 2, (wy0 + wy1 - my0 - my1) / 2)
        edge = _edge_points(affinity.translate(turned, *shift))
        med = float(np.median(gaps(edge, printed)))
        if best is None or med < best[0]:
            best = (med, angle, shift)
    _, angle, shift = best
    turned_edge = _edge_points(affinity.rotate(model_first_layer, angle, origin=centre))
    tree = cKDTree(turned_edge)
    t = np.asarray(shift, dtype=np.float64)
    for _ in range(ALIGN_STEPS):
        _, nearest = tree.query(walls - t)
        step = (walls - (turned_edge[nearest] + t)).mean(axis=0)
        t = t + step
        if math.hypot(*step) < ALIGN_CONVERGED_MM:
            break
    else:
        raise UnsupportedGcode(f"the alignment did not converge in {ALIGN_STEPS} steps")
    result = Alignment(angle, centre, (float(t[0]), float(t[1])), math.nan)
    edge = _edge_points(result.apply(model_first_layer))
    med = float(np.median(gaps(edge, printed)))
    return Alignment(angle, centre, result.shift, med)


def _polygons(geometry) -> list:
    return [g for g in getattr(geometry, "geoms", [geometry])
            if isinstance(g, shapely.Polygon) and g.area > 0]


def count_parts(geometry) -> int:
    return len(_polygons(geometry))


def count_holes(geometry, inside=None) -> int:
    """The bounded regions geometry encloses but does not cover, as connected regions.

    With inside given, a region within inside (an intended void such as sparse infill
    inside the model) is not counted.
    """
    if geometry.is_empty:
        return 0
    # Any frame strictly larger than the bounds works; 1 mm is not a measurement.
    x0, y0, x1, y1 = geometry.bounds
    frame = shapely.box(x0 - 1, y0 - 1, x1 + 1, y1 + 1)
    holes = [r for r in _polygons(frame.difference(geometry))
             if not r.intersects(frame.exterior)]
    if inside is not None:
        holes = [h for h in holes if not inside.contains(h)]
    return len(holes)


def layer_metrics(section, printed, alignment: Alignment, allowance_mm: float) -> dict:
    """One layer: the largest model-edge-to-plastic gap, where it is, and parts and holes.

    section is the model's section in model coordinates, printed the layer's footprint in
    bed coordinates. The gap is the distance from each model-edge sample, every
    EDGE_SAMPLE_MM, to the footprint (0 inside it); share_over_allowance is the share of
    samples whose gap exceeds allowance_mm. With no section, or with nothing printed where
    there is one (nothing_printed, an infinite gap), the gap entries are None.
    """
    model_bed = alignment.apply(section)
    out = {"max_gap_mm": None, "at_bed_mm": None, "at_model_mm": None,
           "share_over_allowance": None,
           "nothing_printed": not model_bed.is_empty and printed.is_empty,
           "parts_model": count_parts(model_bed), "parts_printed": count_parts(printed),
           "holes_model": count_holes(model_bed),
           "holes_printed": count_holes(printed, inside=model_bed)}
    if model_bed.is_empty or printed.is_empty:
        return out
    model_pts = _edge_points(section)
    pts = alignment.to_bed(model_pts)
    d = gaps(pts, printed)
    i = int(np.argmax(d))
    out.update(max_gap_mm=float(d[i]), at_bed_mm=[float(v) for v in pts[i]],
               share_over_allowance=float((d > allowance_mm).mean()),
               at_model_mm=[float(v) for v in model_pts[i]])
    return out


# --- F3 checks for tdmg slice ----------------------------------------------------------


def analyse(text: str, stl: bytes | trimesh.Trimesh, allowance_first_mm: float,
            allowance_mm: float) -> tuple[Alignment, list[dict]]:
    """The alignment and every layer's metrics, lowest layer first.

    The first layer is the lowest Z_HEIGHT; it gets allowance_first_mm and the others
    allowance_mm. Raises UnsupportedGcode as parse_gcode and align do.
    """
    layers = parse_gcode(text)
    mesh = load_mesh(stl)
    zs = sorted(layers)
    first = layers[zs[0]]
    alignment = align(model_section(mesh, first.mid_z), first.segments)
    out = []
    for i, z in enumerate(zs):
        allowance = allowance_first_mm if i == 0 else allowance_mm
        m = layer_metrics(model_section(mesh, layers[z].mid_z), footprint(layers[z].segments),
                          alignment, allowance)
        out.append({"z": z, "allowance_mm": allowance, **m})
    return alignment, out


def _place(point) -> str:
    return "(" + ", ".join(f"{v:.2f}" for v in point) + ")"


def f3_checks(gcode: bytes | None, stl: bytes, tolerance_mm: float, elephant_foot_mm: float,
              not_measured: str | None = None) -> tuple[list[CheckResult], dict]:
    """F3.printed_connectivity and F3.edge_coverage, and the record's "printed" entry.

    The rule (the plan, Decision 2):
    - F3.printed_connectivity PASSes when on every layer the footprint has as many parts
      and as many holes as the model section; otherwise it FAILs, naming the layers.
    - F3.edge_coverage PASSes when every model-edge sample is within tolerance_mm
      (acceptance.dimension.tolerance) of printed plastic, or within tolerance_mm plus
      elephant_foot_mm (the profile's elefant_foot_compensation) on the first layer, where
      the slicer shrinks the outline on purpose. Otherwise it FAILs, naming the largest gap.
    Both are UNKNOWN, with the reason, when not_measured is given (the slicer failed), when
    there is no G-code, or when the G-code or the alignment is unsupported.
    """
    first_mm = tolerance_mm + elephant_foot_mm
    threshold = {"first_layer_mm": first_mm, "other_layers_mm": tolerance_mm}
    record = {"measured": False, "reason": None,
              "allowance_mm": {"first_layer": first_mm, "other_layers": tolerance_mm,
                               "elefant_foot_compensation": elephant_foot_mm},
              "edge_sample_mm": EDGE_SAMPLE_MM, "alignment": None, "layers": []}
    reason = not_measured or (None if gcode else "no G-code was written")
    if reason is None:
        try:
            alignment, layers = analyse(gcode.decode("utf-8"), stl, first_mm, tolerance_mm)
        except UnicodeDecodeError as err:
            reason = f"the G-code is not UTF-8 text: {err}"
        except UnsupportedGcode as err:
            reason = f"the G-code cannot be measured: {err}"
    if reason is not None:
        record["reason"] = reason
        return [CheckResult(CONNECTIVITY, "UNKNOWN", None, None, None, f"not measured: {reason}"),
                CheckResult(COVERAGE, "UNKNOWN", None, threshold, TOLERANCE_RULE,
                            f"not measured: {reason}")], record
    record.update(measured=True, alignment=alignment.as_dict(), layers=[
        {"z": m["z"], "max_gap_mm": m["max_gap_mm"],
         "parts": [m["parts_model"], m["parts_printed"]],
         "holes": [m["holes_model"], m["holes_printed"]]} for m in layers])
    return [_connectivity(layers, alignment), _coverage(layers, alignment, threshold)], record


def _connectivity(layers: list[dict], alignment: Alignment) -> CheckResult:
    bad = [m for m in layers if (m["parts_model"], m["holes_model"])
           != (m["parts_printed"], m["holes_printed"])]
    measured = {"layers": len(layers), "layers_mismatched": len(bad),
                "angle_deg": alignment.angle}
    how = ("Parts and holes of the printed footprint against the model section, per layer; "
           "a void inside the model (sparse infill) is not a hole. ")
    if not bad:
        return CheckResult(CONNECTIVITY, "PASS", measured, None, None,
                           how + "Every layer matches. " + SCOPE)
    m = bad[0]
    measured.update(mismatched_z=[b["z"] for b in bad], first_z=m["z"],
                    parts_model=m["parts_model"], parts_printed=m["parts_printed"],
                    holes_model=m["holes_model"], holes_printed=m["holes_printed"],
                    largest_gap_at_bed_mm=m["at_bed_mm"],
                    largest_gap_at_model_mm=m["at_model_mm"])
    where = ("" if m["at_bed_mm"] is None else
             f"; its largest edge gap, likely where the connection is lost, is at bed "
             f"{_place(m['at_bed_mm'])}, model {_place(m['at_model_mm'])} mm")
    return CheckResult(
        CONNECTIVITY, "FAIL", measured, None, None,
        how + f"{len(bad)} of {len(layers)} layers differ; the first, z = {m['z']:g} mm, has "
        f"{m['parts_printed']} printed part(s) for the model's {m['parts_model']} and "
        f"{m['holes_printed']} printed hole(s) for its {m['holes_model']}{where}: a "
        "connection or a hole of the model is not printed as such. " + SCOPE)


def _coverage(layers: list[dict], alignment: Alignment, threshold: dict) -> CheckResult:
    measured_layers = [m for m in layers if m["max_gap_mm"] is not None]
    nothing = [m["z"] for m in layers if m["nothing_printed"]]
    if nothing:
        return CheckResult(
            COVERAGE, "FAIL", {"nothing_printed_z": nothing, "angle_deg": alignment.angle},
            threshold, TOLERANCE_RULE,
            f"{len(nothing)} layer(s), the first at z = {nothing[0]:g} mm, print nothing "
            "where the model has a section. " + SCOPE)
    if not measured_layers:
        return CheckResult(COVERAGE, "UNKNOWN", None, threshold, TOLERANCE_RULE,
                           "not measured: the model has no section at any printed layer")
    worst = max(measured_layers, key=lambda m: m["max_gap_mm"] - m["allowance_mm"])
    over = [m for m in measured_layers if m["max_gap_mm"] > m["allowance_mm"]]
    measured = {"worst_z": worst["z"], "max_gap_mm": worst["max_gap_mm"],
                "allowance_mm": worst["allowance_mm"], "at_bed_mm": worst["at_bed_mm"],
                "at_model_mm": worst["at_model_mm"],
                "share_over_allowance": worst["share_over_allowance"],
                "layers_over": len(over), "angle_deg": alignment.angle}
    how = (f"The largest distance from a model-edge sample (every {EDGE_SAMPLE_MM:g} mm; the "
           f"true largest is at most {EDGE_SAMPLE_MM / 2:g} mm more) to printed plastic, "
           "against the tolerance, plus the profile's elefant_foot_compensation on the "
           "first layer. ")
    summary = (f"The worst layer, z = {worst['z']:g} mm, leaves {worst['max_gap_mm']:.3f} mm "
               f"against {worst['allowance_mm']:g} mm, at bed {_place(worst['at_bed_mm'])}, "
               f"model {_place(worst['at_model_mm'])} mm"
               + (f"; {len(over)} layer(s) are over. " if over else ". "))
    return CheckResult(COVERAGE, "FAIL" if over else "PASS", measured, threshold,
                       TOLERANCE_RULE, how + summary + SCOPE)

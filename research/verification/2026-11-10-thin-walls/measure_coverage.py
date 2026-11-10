"""Compare what OrcaSlicer prints (from its G-code) with the model, layer by layer.

Usage: uv run python research/verification/2026-11-10-thin-walls/measure_coverage.py GCODE STL

Printed footprint of a layer: every extruding move (G1, and G2/G3 arcs split into chords of
at most 0.05 mm) buffered by half its "; LINE_WIDTH:" value, unioned. "Custom" moves (purge
and start code) are excluded. Model cross-section: the STL cut 0.1 mm below the layer's
"; Z_HEIGHT:". Alignment: OrcaSlicer centres the object and may rotate it about Z (a
25 x 10 mm control was turned 90 degrees). On the first layer the model section is rotated
by 0/90/180/270 degrees about its centroid and translated so its bounding-box centre matches
that of the outer-wall centrelines; the rotation with the smallest median edge-to-plastic
distance is used for every layer.
Reported per layer: the largest distance from a model-edge sample (0.05 mm spacing) to the
nearest printed plastic, its location in bed coordinates, the share of edge samples
farther than 0.2 mm, and the number of connected parts in the model and in the footprint.
The bead is modelled as a line of the stated width with round ends: an approximation of
real squished plastic.
"""
import math
import sys

import numpy as np
import shapely
import trimesh
from shapely import affinity

ARC_STEP_MM = 0.05


def extrusions(path):
    """{z: [(x0, y0, x1, y1, width, feature)]} for extruding moves (relative E only)."""
    rel_e = False
    x = y = z = width = feature = None
    out = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        s = line.strip()
        if s.startswith("; Z_HEIGHT:"):
            z = float(s.split(":")[1])
        elif s.startswith("; LINE_WIDTH:"):
            width = float(s.split(":")[1])
        elif s.startswith("; FEATURE:"):
            feature = s.split(":", 1)[1].strip()
        elif s.startswith("M83"):
            rel_e = True
        elif s.startswith("M82"):
            rel_e = False
        elif s.startswith(("G0 ", "G1 ", "G2 ", "G3 ")):
            words = s.split(";")[0].split()[1:]
            v = {w[0]: float(w[1:]) for w in words if w[0] in "XYZEIJ" and len(w) > 1}
            nx, ny = v.get("X", x), v.get("Y", y)
            pts = [(nx, ny)]
            if s.startswith(("G2", "G3")) and x is not None:
                cx, cy = x + v.get("I", 0.0), y + v.get("J", 0.0)
                r = math.hypot(x - cx, y - cy)
                a0, a1 = math.atan2(y - cy, x - cx), math.atan2(ny - cy, nx - cx)
                if s.startswith("G2"):
                    while a1 >= a0:
                        a1 -= 2 * math.pi
                else:
                    while a1 <= a0:
                        a1 += 2 * math.pi
                n = max(2, int(abs(a1 - a0) * r / ARC_STEP_MM) + 1)
                pts = [(cx + r * math.cos(a0 + (a1 - a0) * k / n),
                        cy + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(1, n)]
                pts.append((nx, ny))
            if (z is not None and x is not None and rel_e and width and v.get("E", 0.0) > 0
                    and feature != "Custom"):
                px, py = x, y
                for qx, qy in pts:
                    if (qx, qy) != (px, py):
                        out.setdefault(z, []).append((px, py, qx, qy, width, feature))
                    px, py = qx, qy
            x, y = nx, ny
    return out


def footprint(segs):
    lines = shapely.linestrings([[(a, b), (c, d)] for a, b, c, d, _, _ in segs])
    return shapely.union_all(shapely.buffer(lines, np.array([s[4] for s in segs]) / 2,
                                            quad_segs=4))


def section(mesh, z):
    sec = mesh.section(plane_origin=[0, 0, z - 0.1], plane_normal=[0, 0, 1])
    p2d, t = sec.to_2D()
    m = [t[0, 0], t[0, 1], t[1, 0], t[1, 1], t[0, 3], t[1, 3]]
    return shapely.union_all([affinity.affine_transform(p, m) for p in p2d.polygons_full])


def parts(g):
    return len([p for p in getattr(g, "geoms", [g]) if p.area > 0])


def main(gcode, stl):
    layers = extrusions(gcode)
    mesh = trimesh.load(stl, process=False)
    shift = None
    for z in sorted(layers):
        segs = layers[z]
        model = section(mesh, z)
        fp = footprint(segs)
        if shift is None:
            oc = shapely.union_all(shapely.linestrings(
                [[(a, b), (c, d)] for a, b, c, d, _, f in segs if f == "Outer wall"])).bounds
            centre = model.centroid
            best = None
            for angle in (0, 90, 180, 270):
                cand = affinity.rotate(model, angle, origin=centre)
                mb = cand.bounds
                sh = ((oc[0] + oc[2] - mb[0] - mb[2]) / 2, (oc[1] + oc[3] - mb[1] - mb[3]) / 2)
                cand = affinity.translate(cand, *sh)
                p = shapely.get_coordinates(shapely.segmentize(cand.boundary, 0.2))
                med = float(np.median(shapely.distance(shapely.points(p), fp)))
                if best is None or med < best[0]:
                    best = (med, angle, sh)
            _, angle, shift = best
            print(f"alignment: rotation {angle} deg, first-layer median edge distance "
                  f"{best[0]:.3f} mm")
        model = affinity.translate(affinity.rotate(model, angle, origin=centre), *shift)
        pts = shapely.get_coordinates(shapely.segmentize(model.boundary, 0.05))
        d = shapely.distance(shapely.points(pts), fp)
        i = int(np.argmax(d))
        print(f"z={z:.2f} max_edge_to_plastic_mm={d.max():.3f} "
              f"at_bed=({pts[i, 0]:.1f},{pts[i, 1]:.1f}) "
              f"share_over_0.2mm={100 * (d > 0.2).mean():.2f}% "
              f"parts_model={parts(model)} parts_printed={parts(fp)} "
              f"min_width_mm={min(s[4] for s in segs):.3f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

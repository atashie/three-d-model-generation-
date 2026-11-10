"""Synthetic OrcaSlicer-style G-code for tests of tdmg.printed and tdmg slice.

The text has the comment lines tdmg.printed reads, in the order the real slicer writes them
(research/verification/2026-11-10-thin-walls/README.md): a Custom start block, M83, then per
layer "; CHANGE_LAYER", "; Z_HEIGHT:", "; LAYER_HEIGHT:", and per feature "; FEATURE:" and
"; LINE_WIDTH:" before its G1 moves. Every layer commands its Z with "G1 Z", and every
extruding move has the relative E OrcaSlicer would write for its bead (FLOW, the A1 PLA
profile's filament), rounded to 5 decimals as the slicer writes E.
"""

import itertools
import math

import shapely

from tdmg.printed import BRIDGE_FEATURES, Flow

WIDTH = 0.42        # the A1 profile's line width (slicer-settings.txt in the record above)
HEIGHT = 0.2        # its layer height
FLOW = Flow(1.75, 0.98)      # its filament: filament_diameter and filament_flow_ratio
START = ("; FEATURE: Custom\nG28\nG1 X18 Y1 E10\n"      # a purge line: Custom, no width
         "G90\nG21\nM83 ; use relative distances for extrusion\n")


def loop(ring_coords) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for x, y in ring_coords]


def e_for(length, width=WIDTH, height=HEIGHT, feature="Outer wall") -> str:
    """The E word for a move of this length, as the slicer would write it."""
    e = FLOW.e_per_mm(width, height, feature in BRIDGE_FEATURES) * length
    return f"E{e:.5f}"


def path_moves(points, width=WIDTH, feature="Outer wall", height=HEIGHT) -> str:
    """Travel to the first point, then extrude along the rest."""
    pts = [(round(x, 4), round(y, 4)) for x, y in points]       # as written, 4 decimals
    lines = [f"; FEATURE: {feature}", f"; LINE_WIDTH: {width}",
             f"G1 X{pts[0][0]:.4f} Y{pts[0][1]:.4f}"]
    for (ax, ay), (bx, by) in itertools.pairwise(pts):
        lines.append(f"G1 X{bx:.4f} Y{by:.4f} "
                     f"{e_for(math.hypot(bx - ax, by - ay), width, height, feature)}")
    return "\n".join(lines) + "\n"


def walls(geometry, width=WIDTH) -> str:
    """The outer wall of every ring: the geometry inset by half a line, mitred."""
    inset = geometry.buffer(-width / 2, join_style="mitre")
    out = ""
    for poly in getattr(inset, "geoms", [inset]):
        for ring in (poly.exterior, *poly.interiors):
            out += path_moves(loop(ring.coords), width)
    return out


def fill(geometry, width=WIDTH, spacing=0.4) -> str:
    """Horizontal fill lines inside the outer wall, spaced to overlap."""
    inner = geometry.buffer(-width, join_style="mitre")      # beads overlap the wall
    if inner.is_empty:
        return ""
    x0, y0, x1, y1 = inner.bounds
    out = ""
    y = y0
    while y <= y1:
        cut = inner.intersection(shapely.LineString([(x0 - 1, y), (x1 + 1, y)]))
        for line in getattr(cut, "geoms", [cut]):
            if line.length > 0:
                out += path_moves(loop(line.coords), width, "Sparse infill")
        y += spacing
    return out


def layer(z, body, height=0.2) -> str:
    return (f"; CHANGE_LAYER\n; Z_HEIGHT: {z:g}\n; LAYER_HEIGHT: {height:g}\n"
            f"G1 Z{z:.3f}\n{body}")


def gcode(layers: list[str], start: str = START) -> str:
    # The end code travels and retracts but does not extrude, as the real one.
    return start + "".join(layers) + "; FEATURE: Custom\nG1 X0 Y0\nG1 E-.8\n"


def solid(geometry, width=WIDTH) -> str:
    """Outer walls and fill: a footprint that covers the geometry."""
    return walls(geometry, width) + fill(geometry, width)

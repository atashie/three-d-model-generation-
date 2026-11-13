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
- analyse: where the slicer put the model (its bounding box centred on the plate, turned
  by the quarter turn that fits best over all layers) and every layer's metrics.
- layer_metrics: per layer, the largest distance from the model's edge to printed plastic,
  and whether the parts and holes of the print match those of the model one to one.
- f3_checks: F3.printed_connectivity, F3.edge_coverage and F3.edge_overprint for tdmg
  slice, by the rules the owner approved (docs/plans/2026-11-10-thin-wall-policy.md,
  Decisions 2 and 2a).

Holes: a region the footprint encloses but does not print is a hole of the print only if
it is not inside the model section. Sparse infill leaves many such voids inside the model,
by design, and they are not holes. Each hole of the model must overlap exactly one hole of
the print, and each hole of the print exactly one hole of the model.

Every constant below, and the method itself, is part of what tdmg.slicing's
SLICE_ALGORITHM_VERSION names: change one and bump that version, since the verdict for
the same slice can change.
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import shapely
import trimesh
from shapely import affinity

from tdmg.checks import CheckResult

# Constants: bump tdmg.slicing.SLICE_ALGORITHM_VERSION if any of them changes.
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
QUARTER_TURNS = (0, 90, 180, 270)
# Display only: how many unmatched parts or holes a FAIL lists.
UNMATCHED_LISTED = 5
CUSTOM = "Custom"            # OrcaSlicer's feature name for the start and end code
# The features whose extrusions are the model, as seen in the pinned OrcaSlicer's G-code
# for the A1 profile: the owner's Roadie and Oddie and the bridge controls of
# research/verification/2026-11-10-thin-walls/. Any other feature that extrudes (a brim,
# skirt, support, prime tower or one not seen yet) makes the G-code unsupported, since its
# plastic is not the model's.
MODEL_FEATURES = frozenset({"Outer wall", "Inner wall", "Gap infill", "Sparse infill",
                            "Internal solid infill", "Top surface", "Bottom surface",
                            "Internal Bridge"})
# The G-commands read, each seen in the pinned OrcaSlicer's G-code for the A1 profile (the
# owner's runs, the bridge controls and the review's hair cases): moves and arcs, the XY
# plane, millimetres, homing and bed levelling (start code), absolute positioning and
# setting the position. G91 was not seen but is followed exactly. Any other G-command
# (G4, G5, G10, G18, G19, ...) makes the G-code unsupported. G17 is the only plane, so
# arcs are always read in X and Y.
G_COMMANDS = frozenset({"G0", "G1", "G2", "G3", "G17", "G21", "G28", "G29", "G90", "G91",
                        "G92"})
# A command as OrcaSlicer writes it: G, M or T, a number without a leading zero, and for
# M an optional ".n" subcode (M73.2, M201.2, M622.1 are written). Line numbers (N...),
# checksums (*nn), lower case, leading zeros and words run together are not written by
# OrcaSlicer, so they are refused rather than parsed.
COMMAND = re.compile(r"(?:G|T)(?:0|[1-9][0-9]*)|M(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
# The firmware G-commands accepted, in FEATURE "Custom" (the start and end code) and in
# SKIPPABLE blocks only: exactly those the pinned A1 template G-code writes, on the
# owner's Roadie and Oddie (research/verification/2026-11-13-a1-profile-include/
# scan-gcommands.txt): G392 (clog detection), G380 (move to a stop), G39, G39.3 and G39.4,
# G29.2 and G29.4 (bed levelling) and G2814. Each makes the X, Y and commanded Z unknown
# until the next absolute ones, as G28 does. Its words must be finite plain numbers, with
# no E word, and its X and Y within plate.within_bound. Any other G-command outside
# G_COMMANDS is refused, there as everywhere.
FIRMWARE_G_COMMANDS = frozenset({"G392", "G380", "G39", "G39.3", "G39.4", "G29.2", "G29.4",
                                 "G2814"})
# The A1 time-lapse code is read as Custom is, between these two comment lines. They are
# not OrcaSlicer's: they are lines 4 and 61 of the 63-line time_lapse_gcode in the pinned
# template "Bambu Lab A1 0.4 nozzle template time_lapse_gcode.json" (sha256 febd4212...,
# profiles/slicers/orcaslicer-2.5.0.yaml), written at each layer change with no FEATURE line.
# Inside them the owner's G-code has G392, G39.3 and G39 (research/verification/
# 2026-11-13-a1-profile-include/scan-gcommands.txt) and no E move at all. Since this code
# runs between model layers, a block may not extrude: a G0 to G3 with an E word is refused
# unless the extrusion mode is relative (M83) and E <= 0 (a retraction). A block must not
# hold a FEATURE line, and the two lines must pair; the FEATURE in force is unchanged by it.
# The firmware runs its M622 ... M623 conditional blocks or not, so after every M623, and
# after every SKIPPABLE_END, the X, Y and commanded Z are unknown.
SKIPPABLE_START = "SKIPPABLE_START"
SKIPPABLE_END = "SKIPPABLE_END"
# A word: an upper-case letter and a plain decimal number (no exponent, nan or inf).
WORD = re.compile(r"([A-Z])(-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))")
CONNECTIVITY = "F3.printed_connectivity"
COVERAGE = "F3.edge_coverage"
OVERPRINT = "F3.edge_overprint"
F3_SLICE_CHECK_IDS = (CONNECTIVITY, COVERAGE, OVERPRINT)
# Z_HEIGHT and LAYER_HEIGHT are written with C's %g, six significant digits (OrcaSlicer's
# GCode::process_layer, main branch, read 2026-11-10: sprintf "; Z_HEIGHT: %g" of print_z,
# and the height as a float: print_z on the first layer, else float(print_z) minus the
# previous layer's z kept as a float). So a printed value v is within half a unit of its
# sixth significant digit, and the float height within (|z| + |z_prev| + |h|) * 2^-24 of
# the exact difference. Z_SIG_DIGITS is that format's precision, not a threshold.
Z_SIG_DIGITS = 6
# Model moves as OrcaSlicer writes them: X, Y, Z, I and J with at most 3 decimals and E with
# at most 5 (every model move in the owner's G-code, the bridge controls and the hair
# cases; its GCodeFormatter rounds each axis to a fixed number of digits and drops trailing
# zeros, GCodeWriter.cpp at v2.5.0). So a printed coordinate is within XY_ROUND_MM of the
# slicer's own, and a printed E within E_ROUND_MM. Precision of the format, not thresholds.
XY_ROUND_MM = 0.5e-3
E_ROUND_MM = 0.5e-5
# Bridges are extruded as round beads of the line width (OrcaSlicer v2.5.0
# Flow::mm3_per_mm); every other model feature as a rectangle with round ends.
BRIDGE_FEATURES = frozenset({"Internal Bridge"})
# M-codes that change where plastic goes or how much, none of which the pinned slicer
# writes for this profile: steps per mm (M92), volumetric extrusion (M200), firmware
# retraction settings (M207, M208, M209) and Z babystepping (M290). They make the G-code
# unsupported anywhere. M221 (flow percent) is read only as S100, as the start code
# writes it. G92 may set E only: no real file sets X, Y or Z with it.
REFUSED_M_COMMANDS = frozenset({"M92", "M200", "M207", "M208", "M209", "M290"})
FILAMENT_DIAMETER_KEY = "filament_diameter"
FILAMENT_FLOW_KEY = "filament_flow_ratio"
TOLERANCE_RULE = "acceptance.dimension.tolerance"
ELEPHANT_FOOT_KEY = "elefant_foot_compensation"      # OrcaSlicer's spelling
PRINTABLE_AREA_KEY = "printable_area"
SCOPE = ("The bead model (each extrusion a line of its stated width with round ends) "
         "approximates real plastic. Strength is not judged: a single thin line is printed "
         "but may be fragile. Measured for the pinned OrcaSlicer and A1 profile only.")


class UnsupportedGcode(ValueError):
    """The G-code, or the alignment, has something this module cannot measure."""


@dataclass(frozen=True)
class Plate:
    """The machine profile's printable_area, as its bounding box in bed mm."""
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    def within_bound(self, x: float, y: float) -> bool:
        """Whether (x, y) is at most one plate width (or depth) outside the plate.

        A sanity bound, not a measurement: start code may move beyond the plate (a purge
        or wipe), but never by the plate's own size, so a coordinate beyond that is a
        corrupt or foreign file. It also bounds arcs, so a huge radius cannot make the
        parser split an arc into an unbounded number of chords.
        """
        w, d = self.x1 - self.x0, self.y1 - self.y0
        return self.x0 - w <= x <= self.x1 + w and self.y0 - d <= y <= self.y1 + d

    @property
    def bound_diameter(self) -> float:
        """The diagonal of the within_bound region (three plates wide and deep)."""
        return 3 * math.hypot(self.x1 - self.x0, self.y1 - self.y0)


def plate_from_profile(machine_profile: dict) -> Plate:
    """The Plate from a flattened machine profile's printable_area ("XxY" corner strings).

    Raises ValueError when it is missing, unreadable, not finite or has no area.
    """
    corners = machine_profile.get(PRINTABLE_AREA_KEY)
    if not isinstance(corners, list) or len(corners) < 3:
        raise ValueError(f"machine profile has no {PRINTABLE_AREA_KEY!r} list of corners "
                         f"(it is {corners!r})")
    try:
        points = [tuple(float(v) for v in str(c).split("x")) for c in corners]
    except ValueError:
        raise ValueError(f"machine profile {PRINTABLE_AREA_KEY!r} is not 'XxY' corners: "
                         f"{corners!r}") from None
    if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in points):
        raise ValueError(f"machine profile {PRINTABLE_AREA_KEY!r} is not finite 'XxY' "
                         f"corners: {corners!r}")
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    plate = Plate(min(xs), min(ys), max(xs), max(ys))
    if not (plate.x1 > plate.x0 and plate.y1 > plate.y0):
        raise ValueError(f"machine profile {PRINTABLE_AREA_KEY!r} has no area: {corners!r}")
    return plate


@dataclass(frozen=True)
class Flow:
    """The filament profile's diameter and flow ratio, which set E per mm of bead."""
    filament_diameter_mm: float
    flow_ratio: float

    def e_per_mm(self, width: float, height: float, bridge: bool) -> float:
        """E per mm of move, as OrcaSlicer v2.5.0 computes it.

        Flow::mm3_per_mm: a bridge is a circle of the width, pi w^2 / 4; any other bead a
        rectangle with round ends, h (w - h (1 - pi / 4)). E is that volume over the
        filament's cross-section, times the filament's flow ratio. The pinned process
        profile's other flow ratios (print, first layer and per feature) are all 1, so they
        are not modelled: a profile that changed them would give mismatched E and UNKNOWN.
        Measured on every model move of the owner's G-code and the controls (58,344): the
        ratio of written to computed E has median 1.0000.
        """
        mm3 = (width * width * math.pi / 4 if bridge
               else height * (width - height * (1 - math.pi / 4)))
        area = math.pi * self.filament_diameter_mm ** 2 / 4
        return mm3 / area * self.flow_ratio


def _profile_number(profile: dict, key: str) -> float:
    value = profile.get(key)
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"filament profile {key!r} is {value!r}, not one number") from None
    if not (math.isfinite(number) and number > 0):
        raise ValueError(f"filament profile {key!r} must be finite and above 0, not {value!r}")
    return number


def flow_from_profile(filament_profile: dict) -> Flow:
    """The Flow from a flattened filament profile (values are one-item lists of strings)."""
    return Flow(_profile_number(filament_profile, FILAMENT_DIAMETER_KEY),
                _profile_number(filament_profile, FILAMENT_FLOW_KEY))


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
        found = WORD.fullmatch(word)
        if found is None:
            raise UnsupportedGcode(f"line {lineno}: cannot read {word!r} in {code!r}")
        letter, value = found.group(1), float(found.group(2))
        if not math.isfinite(value):
            raise UnsupportedGcode(f"line {lineno}: {word!r} in {code!r} is not finite")
        words[letter] = value
    return words


def _arc(x, y, nx, ny, words, clockwise, plate: Plate,
         where: str) -> tuple[list[tuple[float, float]], float, float]:
    """The chord ends of a G2/G3 arc in the I/J centre form, ending exactly at (nx, ny),
    with the arc's length and its sweep in radians.

    The sweep follows the usual firmware convention (Marlin's plan_arc): the arc turns
    clockwise for G2 and anticlockwise for G3 from the start to the end angle, and a start
    equal to the end is a full circle.

    Raises UnsupportedGcode when the arc cannot lie within plate.within_bound: a circular
    arc inside a convex region of diameter D is at most pi D long (a major arc holds a
    diameter of its circle, so 2 r <= D; a minor arc is at most pi / 2 times its chord), so
    a longer one is refused before it is split, which also bounds the number of chords; and
    then when any chord end lies outside the bound. Large radii are normal: arc fitting
    gives nearly straight arcs radii of hundreds of mm with small sweeps.
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
    length = abs(a1 - a0) * r
    if length > math.pi * plate.bound_diameter:
        raise UnsupportedGcode(f"{where}: the arc (radius {r:g}, length {length:g}) cannot "
                               "lie within the plate's bound")
    n = max(2, math.ceil(length / ARC_STEP_MM))
    pts = [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cy + r * math.sin(a0 + (a1 - a0) * k / n))
           for k in range(1, n)]
    if not all(plate.within_bound(px, py) for px, py in pts):
        raise UnsupportedGcode(f"{where}: the arc (radius {r:g}) reaches beyond the plate by "
                               "more than its own size")
    return [*pts, (nx, ny)], length, abs(a1 - a0)


def parse_gcode(text: str, plate: Plate, flow: Flow | None = None) -> dict[float, Layer]:
    """{z: Layer} for every "; Z_HEIGHT:" layer, with its extruding moves.

    An extruding move is a G1, G2 or G3 with a positive E that moves in X or Y. Moves in
    FEATURE "Custom", the start and end code, are excluded; on the A1 that includes the
    purge line. Travel, retraction and unretraction (E with no X/Y motion) lay down no
    bead. G90/G91 (absolute and relative X/Y) and G92 are followed; G28 makes the position
    unknown until the next absolute X and Y.

    Raises UnsupportedGcode, outside Custom, for an extruding move: with absolute or unknown
    extrusion mode (M82, or no M83 yet), since E is then a position; before any Z_HEIGHT,
    FEATURE or LINE_WIDTH, or with a width that is not positive; in a feature outside
    MODEL_FEATURES; from an unknown position; as an arc in the R form, with a P (turns)
    word, with neither I nor J, or reaching beyond plate.within_bound. Anywhere, for a word
    that is not a finite number, a position beyond plate.within_bound, and G20 (inches).
    And for G-code with no Z_HEIGHT layer, a layer that has no LAYER_HEIGHT by the end
    (even if it prints nothing), Z_HEIGHT values that do not strictly increase in file
    order, a first layer whose Z is not its LAYER_HEIGHT, or a layer whose Z is not the
    previous Z plus its LAYER_HEIGHT, within the precision those numbers are written with
    (z_tolerance). A layer's height is the first LAYER_HEIGHT after its Z_HEIGHT, as
    OrcaSlicer writes it; later LAYER_HEIGHT lines in the layer are the bead heights of
    single features (a bridge is written 0.4 mm high) and do not change the layer.

    Every line that is not a comment must start with a command matching COMMAND, and a
    G-command must be in G_COMMANDS; anything else is refused, never skipped. The one
    exception is FEATURE "Custom", the start and end code: there one of
    FIRMWARE_G_COMMANDS (the firmware G-commands the A1 template writes) is accepted, and
    it makes X, Y and the commanded Z unknown until the next absolute ones, as G28 does.
    Its words must be finite plain numbers, with no E word, and its X and Y within
    plate.within_bound. Moves in Custom (relative or R-form arcs, G0 with E) are followed
    for the position only; none is analysed. The A1 time-lapse code, between the comment
    lines "; SKIPPABLE_START" and "; SKIPPABLE_END" (SKIPPABLE_START), is read as Custom is
    for G-commands, but must pair, must not hold a FEATURE line, refuses a move with an E
    word unless E <= 0 in relative mode (M83), and leaves the FEATURE in force unchanged;
    its moves set the position only. The firmware's conditional blocks (M622 ... M623, in
    Custom and SKIPPABLE blocks) are read as if every line runs: their moves set the
    position only, and after each M623 and each SKIPPABLE_END the X, Y and commanded Z are
    unknown, so whichever branch the printer takes, a model extrusion needs an absolute X,
    Y and Z after them. M- and
    T-commands are ignored except M82 and M83, which set the extrusion mode, and the
    refused ones below. The others in this G-code set temperatures, speeds, fans,
    progress, sounds, lights, calibrations and the A1's own functions, not where model
    plastic goes. With the generic profile (slice-4): M17, M73, M73.2, M104, M106, M109,
    M140, M190, M201, M201.2, M203, M204, M205, M220, M221, M400, M620-M625, M622.1,
    M970, M971, M974, M981, M991, M1002 and T255. With the A1 template G-code (slice-5;
    research/verification/2026-11-13-a1-profile-include/scan-mt-commands.txt) also M18,
    M211, M412, M500, M620.1, M620.3, M630, M900, M960, M970.2, M970.3, M975, M982.2, M983,
    M984, M1004, M1006, M1007, M9833.2, T0 and T1000. An
    extrusion in "Custom" after the first model extrusion is refused: in all the pinned
    slicer's G-code for this profile (the owner's runs, the controls and the hair cases)
    Custom extrudes only before the model, in the purge line; the end code does not
    extrude.

    What is commanded must be what is analysed: every model extrusion must be at the
    layer's Z_HEIGHT as commanded by Z words (followed through G90/G91; Z-hops on travel
    are fine), within the precision both are written with (_commanded_z_tolerance). G92 may
    set E only, and REFUSED_M_COMMANDS and M221 other than S100 are refused. With flow
    given, as tdmg slice always does, each model extrusion's E must be the amount for its
    stated width and bead height (the latest LAYER_HEIGHT) over its length
    (_check_amount); a move with too little or too much plastic for its bead is refused.
    """
    relative_e = None                      # unknown until M82 or M83
    relative_xy = False
    x = y = z_cmd = None                   # z_cmd: the Z the moves command
    z = width = feature = bead_height = None
    layers: dict[float, Layer] = {}
    model_lines: list[int] = []            # lines of model extrusions
    custom_lines: list[int] = []           # lines of Custom extrusions
    skippable = None                       # the line of an open SKIPPABLE_START
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith(";"):
            tag = line[1:].lstrip()
            if tag == SKIPPABLE_START:
                if skippable is not None:
                    raise UnsupportedGcode(f"line {lineno}: SKIPPABLE_START inside the block "
                                           f"opened at line {skippable}")
                skippable = lineno
            elif tag == SKIPPABLE_END:
                if skippable is None:
                    raise UnsupportedGcode(f"line {lineno}: SKIPPABLE_END without a "
                                           "SKIPPABLE_START")
                skippable = None
                x = y = z_cmd = None           # whether the block ran is not known
            elif tag.startswith("FEATURE:") and skippable is not None:
                raise UnsupportedGcode(f"line {lineno}: a FEATURE inside the SKIPPABLE block "
                                       f"opened at line {skippable}")
            elif tag.startswith("Z_HEIGHT:"):
                new_z = _comment_value(tag, lineno)
                if z is not None and not new_z > z:
                    raise UnsupportedGcode(f"line {lineno}: Z_HEIGHT {new_z:g} does not "
                                           f"increase on the previous {z:g}")
                z = new_z
                layers[z] = Layer(z, math.nan, [])
            elif tag.startswith("LAYER_HEIGHT:") and z is not None:
                height = _comment_value(tag, lineno)
                if not height > 0:
                    raise UnsupportedGcode(f"line {lineno}: layer height {height} is not "
                                           "positive")
                bead_height = height
                if math.isnan(layers[z].height):          # the layer's, not a feature's
                    layers[z] = Layer(z, height, layers[z].segments)
            elif tag.startswith("LINE_WIDTH:"):
                width = _comment_value(tag, lineno)
            elif tag.startswith("FEATURE:"):
                feature = tag.split(":", 1)[1].strip()
            continue
        code = line.split(";", 1)[0].strip()
        if not code:
            continue
        command = code.split()[0]
        if ((feature == CUSTOM or skippable is not None) and command.startswith("G")
                and command not in G_COMMANDS):
            _check_firmware(command, code, lineno, plate)
            x = y = z_cmd = None               # where the firmware leaves it is not known
            continue
        if COMMAND.fullmatch(command) is None:
            raise UnsupportedGcode(f"line {lineno}: {command!r} in {code!r} is not a command "
                                   "as OrcaSlicer writes it")
        if command.startswith("G") and command not in G_COMMANDS:
            raise UnsupportedGcode(f"line {lineno}: {command} is not a G-command this check "
                                   "reads")
        if command in REFUSED_M_COMMANDS:
            raise UnsupportedGcode(f"line {lineno}: {command} changes the extrusion or Z, "
                                   "which this check does not follow")
        if command == "M221" and _words(code, lineno).get("S") != 100:
            raise UnsupportedGcode(f"line {lineno}: {code!r} sets the flow to other than "
                                   "100%")
        if command == "M623":                  # the end of a firmware conditional block
            x = y = z_cmd = None
        elif command == "M82":
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
            x = y = z_cmd = None
        elif command == "G92":
            if set(_words(code, lineno)) - {"E"}:
                raise UnsupportedGcode(f"line {lineno}: {code!r} sets a position other than "
                                       "E, which OrcaSlicer does not write")
        elif command in ("G0", "G1", "G2", "G3"):
            words = _words(code, lineno)
            if relative_xy:
                nx = None if x is None else x + words.get("X", 0.0)
                ny = None if y is None else y + words.get("Y", 0.0)
            else:
                nx, ny = words.get("X", x), words.get("Y", y)
            where = f"line {lineno} ({code!r})"
            _check_bound(where, nx, ny, plate)
            if "Z" in words:
                if relative_xy:
                    z_cmd = None if z_cmd is None else z_cmd + words["Z"]
                else:
                    z_cmd = words["Z"]
            e = words.get("E", 0.0)
            # A move with X or Y from or to an unknown position is a move, not a stay in the
            # same (unknown) place: with E > 0 it is refused below, never dropped.
            moves = ((nx, ny) != (x, y) or (command in ("G2", "G3") and "E" in words)
                     or (("X" in words or "Y" in words) and None in (x, y, nx, ny)))
            if skippable is not None:
                if "E" in words and relative_e is not True:
                    raise UnsupportedGcode(f"{where}: an E word inside a SKIPPABLE block in "
                                           "absolute or unknown extrusion mode")
                if e > 0:
                    raise UnsupportedGcode(f"{where}: an extrusion inside a SKIPPABLE block "
                                           "(the A1 time-lapse code, between model layers)")
                x, y = nx, ny
                continue
            if moves and e != 0.0 and feature != CUSTOM and relative_e is not True:
                raise UnsupportedGcode(f"{where}: absolute extrusion (M82, or no M83 before "
                                       "it): only relative E is supported")
            if moves and e > 0 and feature == CUSTOM:
                custom_lines.append(lineno)
            if moves and e > 0 and feature != CUSTOM:
                model_lines.append(lineno)
                _check_extrusion(where, command, words, (x, y, nx, ny), z, width, feature,
                                 z_cmd, None if z is None else layers[z].height)
                if command == "G1" or command == "G0":
                    pts, length, sweep = [(nx, ny)], math.hypot(nx - x, ny - y), None
                else:
                    pts, length, sweep = _arc(x, y, nx, ny, words, command == "G2", plate,
                                              where)
                if flow is not None:
                    _check_amount(where, e, length, sweep, width, bead_height,
                                  feature in BRIDGE_FEATURES, flow)
                px, py = x, y
                for qx, qy in pts:
                    if (qx, qy) != (px, py):
                        layers[z].segments.append(Segment(px, py, qx, qy, width, feature))
                    px, py = qx, qy
            x, y = nx, ny
    if skippable is not None:
        raise UnsupportedGcode(f"line {skippable}: SKIPPABLE_START without a SKIPPABLE_END "
                               "by the end of the file")
    if not layers:
        raise UnsupportedGcode("no Z_HEIGHT layer: this is not OrcaSlicer G-code with layer "
                               "comments")
    after = [n for n in custom_lines if model_lines and n > model_lines[0]]
    if after:
        raise UnsupportedGcode(f"line {after[0]}: a Custom extrusion after the model began, "
                               "which is not the start code's purge")
    unknown = [z for z, lay in layers.items() if math.isnan(lay.height)]
    if unknown:
        raise UnsupportedGcode(f"layer(s) {', '.join(f'{z:g}' for z in unknown)} have no "
                               "LAYER_HEIGHT")
    previous = 0.0
    for z, lay in layers.items():                        # file order, increasing
        if abs(z - previous - lay.height) > z_tolerance(z, previous, lay.height):
            raise UnsupportedGcode(f"layer {z:g}: Z is not the previous Z ({previous:g}) "
                                   f"plus its LAYER_HEIGHT ({lay.height:g}): a gap or an "
                                   "overlap in the layers")
        previous = z
    return layers


def _half_digit(v: float) -> float:
    """Half a unit in the last digit %g writes for v (Z_SIG_DIGITS significant digits)."""
    if v == 0:
        return 0.0
    return 0.5 * 10.0 ** (math.floor(math.log10(abs(v))) - (Z_SIG_DIGITS - 1))


def z_tolerance(z: float, previous: float, height: float) -> float:
    """How far z - previous - height may be from 0 from how the three were written.

    The %g rounding of each of the three numbers, plus the float rounding of the height
    (see Z_SIG_DIGITS), doubled for the float64 arithmetic here, as flat's STL_COORD_RTOL
    does. For a 0.2 mm layer near z = 3 mm it is about 1e-6 mm: a numerical bound, far
    below any layer height, so a missing or doubled layer cannot pass. tdmg.portability
    uses it for PrusaSlicer's ";Z:" lines, which are written with 6 significant digits too.
    """
    rounding = _half_digit(z) + _half_digit(previous) + _half_digit(height)
    return 2 * (rounding + (abs(z) + abs(previous) + abs(height)) * 2.0 ** -24)


def _commanded_z_tolerance(z: float) -> float:
    """How far a commanded Z word may be from Z_HEIGHT: the 3-decimal rounding of the word
    (XY_ROUND_MM) and the %g rounding of Z_HEIGHT, doubled for float arithmetic."""
    return 2 * (XY_ROUND_MM + _half_digit(z))


def _check_amount(where, e, length, sweep, width, height, bridge, flow: Flow) -> None:
    """Refuse an extrusion whose E is not the amount for its bead over its length.

    The slicer computes E from its own coordinates; the file holds them rounded. A
    straight move's two ends each lie within XY_ROUND_MM * sqrt 2 (u) of the slicer's, so
    its length is within 2 u. An arc's length r theta moves by at most theta |dr| + r |d
    theta|: r changes by at most u (the I/J rounding) and r d theta by at most u at the
    start and 3 u at the end (its own rounding plus the centre's two), so by (4 + theta) u
    in all. So |E - expected| may be E_ROUND_MM plus e_per_mm times that. Measured on the
    58,344 model moves of the owner's G-code and the controls: the implied length error was
    at most 0.0012 mm for lines (bound 0.0014) and 0.0022 mm for arcs (bound at least
    0.0028).
    """
    if height is None:
        raise UnsupportedGcode(f"{where}: an extrusion before any LAYER_HEIGHT")
    per_mm = flow.e_per_mm(width, height, bridge)
    u = XY_ROUND_MM * math.sqrt(2)
    length_error = 2 * u if sweep is None else (4 + sweep) * u
    expected = per_mm * length
    if abs(e - expected) > E_ROUND_MM + per_mm * length_error:
        raise UnsupportedGcode(f"{where}: extrusion amount E{e:g} does not match the stated "
                               f"width {width:g} mm and height {height:g} mm over "
                               f"{length:.3f} mm (expected {expected:.5f})")


def _check_firmware(command: str, code: str, lineno: int, plate: Plate) -> None:
    """Refuse a G-command in Custom or a SKIPPABLE block that is not one of
    FIRMWARE_G_COMMANDS, or has bad words, an E word, or an X or Y beyond
    plate.within_bound."""
    if command not in FIRMWARE_G_COMMANDS:
        raise UnsupportedGcode(f"line {lineno}: {command!r} in {code!r} is not a firmware "
                               "G-command seen in the A1 template G-code, nor one this check "
                               "reads")
    words = _words(code, lineno)
    if "E" in words:
        raise UnsupportedGcode(f"line {lineno}: {code!r} is a firmware command with an E word, "
                               "which this check does not follow")
    cx, cy = plate.centre
    if not plate.within_bound(words.get("X", cx), words.get("Y", cy)):
        raise UnsupportedGcode(f"line {lineno} ({code!r}): an X or Y beyond the plate by "
                               "more than its own size")


def _check_bound(where, x, y, plate: Plate) -> None:
    if (x is not None and y is not None) and not plate.within_bound(x, y):
        raise UnsupportedGcode(f"{where}: position ({x:g}, {y:g}) is beyond the plate by "
                               "more than its own size")


def _check_extrusion(where, command, words, ends, z, width, feature, z_cmd,
                     layer_height) -> None:
    if z is None:
        raise UnsupportedGcode(f"{where}: an extrusion before any Z_HEIGHT")
    if math.isnan(layer_height):
        raise UnsupportedGcode(f"{where}: an extrusion on layer {z:g}, which has no "
                               "LAYER_HEIGHT")
    if feature is None:
        raise UnsupportedGcode(f"{where}: an extrusion before any FEATURE")
    if feature not in MODEL_FEATURES:
        raise UnsupportedGcode(f"{where}: an extrusion in feature {feature!r}, which is not "
                               "one of the model features this check knows")
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
    if z_cmd is None or abs(z_cmd - z) > _commanded_z_tolerance(z):
        raise UnsupportedGcode(f"{where}: an extrusion at commanded Z {z_cmd} on the layer "
                               f"at Z_HEIGHT {z:g}")


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
    """Model x/y to bed x/y: turn by angle (degrees, anticlockwise) about the model's
    bounding-box centre, then move that centre to the plate centre."""
    angle: int
    centre: tuple[float, float]           # the model's bounding-box centre, model mm
    plate_centre: tuple[float, float]     # bed mm

    @property
    def shift(self) -> tuple[float, float]:
        return (self.plate_centre[0] - self.centre[0], self.plate_centre[1] - self.centre[1])

    def apply(self, geometry):
        turned = affinity.rotate(geometry, self.angle, origin=self.centre)
        return affinity.translate(turned, *self.shift)

    def _rotation(self) -> np.ndarray:
        a = math.radians(self.angle)
        return np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])

    def to_bed(self, points: np.ndarray) -> np.ndarray:
        c = np.asarray(self.centre)
        return (np.asarray(points) - c) @ self._rotation().T + np.asarray(self.plate_centre)

    def to_model(self, points: np.ndarray) -> np.ndarray:
        c = np.asarray(self.centre)
        return (np.asarray(points) - np.asarray(self.plate_centre)) @ self._rotation() + c

    def as_dict(self) -> dict:
        return {"angle_deg": self.angle, "model_bbox_centre_mm": list(self.centre),
                "plate_centre_mm": list(self.plate_centre), "shift_mm": list(self.shift)}


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


def _polygons(geometry) -> list:
    return [g for g in getattr(geometry, "geoms", [geometry])
            if isinstance(g, shapely.Polygon) and g.area > 0]


def enclosed_regions(geometry) -> list:
    """The bounded regions geometry encloses but does not cover, as connected polygons."""
    if geometry.is_empty:
        return []
    # Any frame strictly larger than the bounds works; 1 mm is not a measurement.
    x0, y0, x1, y1 = geometry.bounds
    frame = shapely.box(x0 - 1, y0 - 1, x1 + 1, y1 + 1)
    return [r for r in _polygons(frame.difference(geometry)) if not r.intersects(frame.exterior)]


def printed_holes(printed, model_bed) -> list:
    """The footprint's enclosed regions that are not inside the model: the print's holes."""
    regions = enclosed_regions(printed)
    if not regions or model_bed.is_empty:
        return regions
    shapely.prepare(model_bed)
    inside = shapely.contains(model_bed, np.array(regions, dtype=object))
    return [r for r, keep in zip(regions, inside, strict=True) if not keep]


def _overlaps(a: list, b: list) -> tuple[np.ndarray, np.ndarray]:
    """For each item of a and of b, how many items of the other its interior overlaps."""
    na, nb = np.zeros(len(a), dtype=int), np.zeros(len(b), dtype=int)
    if a and b:
        aa, bb = np.array(a, dtype=object), np.array(b, dtype=object)
        ia, ib = shapely.STRtree(bb).query(aa, predicate="intersects")
        keep = shapely.relate_pattern(aa[ia], bb[ib], "T********")   # interiors meet
        np.add.at(na, ia[keep], 1)
        np.add.at(nb, ib[keep], 1)
    return na, nb


def match(model_items: list, printed_items: list, kind: str,
          alignment: Alignment) -> list[dict]:
    """The model and printed items (parts or holes, in bed mm) not matched one to one.

    An item is matched when its interior overlaps exactly one item of the other side's.
    Each unmatched one is listed with how many it overlaps and a point inside it (its
    representative point), in model mm.
    """
    nm, np_ = _overlaps(model_items, printed_items)
    out = []
    for side, items, counts in (("model", model_items, nm), ("printed", printed_items, np_)):
        for item, n in zip(items, counts, strict=True):
            if n != 1:
                p = item.representative_point()
                at = alignment.to_model(np.array([[p.x, p.y]]))[0]
                out.append({"what": f"{side} {kind}", "overlaps": int(n),
                            "at_model_mm": [float(at[0]), float(at[1])]})
    return out


def overprint_points(printed, model_bed, spacing: float = EDGE_SAMPLE_MM) -> np.ndarray:
    """Samples of the plastic printed outside the model: the boundary of printed minus the
    model every spacing, and a grid at spacing inside it.

    The boundary of the footprint alone is not enough: plastic that fills a hole of the
    model has its farthest point inside, away from any edge. Any point of the region is
    within spacing / sqrt 2 of a grid node; if that node is outside the region, the point
    is within that of the region's boundary, which is sampled every spacing. With distance
    1-Lipschitz, the true largest overprint is at most the sampled largest plus
    spacing * (1 / sqrt 2 + 1 / 2), 0.06 mm.
    """
    outside = printed if model_bed.is_empty else printed.difference(model_bed)
    parts = _polygons(outside)
    if not parts:
        return np.empty((0, 2))
    region = shapely.union_all(parts)
    edge = _edge_points(region, spacing)
    x0, y0, x1, y1 = region.bounds
    xs = np.arange(math.ceil(x0 / spacing), math.floor(x1 / spacing) + 1) * spacing
    ys = np.arange(math.ceil(y0 / spacing), math.floor(y1 / spacing) + 1) * spacing
    gx, gy = np.meshgrid(xs, ys)
    grid = np.column_stack([gx.ravel(), gy.ravel()])
    if len(grid):
        shapely.prepare(region)
        grid = grid[shapely.contains_xy(region, grid[:, 0], grid[:, 1])]
    return np.vstack([edge, grid]) if len(grid) else edge


def edge_gaps(section, printed, alignment: Alignment):
    """(model-edge samples in model mm, the same in bed mm, their gaps to the footprint),
    or None when there is no section or nothing printed."""
    if section.is_empty or printed.is_empty:
        return None
    model_pts = _edge_points(section)
    pts = alignment.to_bed(model_pts)
    return model_pts, pts, gaps(pts, printed)


def layer_metrics(section, printed, alignment: Alignment, allowance_mm: float,
                  edges=None) -> dict:
    """One layer: the largest model-edge-to-plastic gap, where it is, and parts and holes.

    section is the model's section in model coordinates, printed the layer's footprint in
    bed coordinates. The gap is the distance from each model-edge sample, every
    EDGE_SAMPLE_MM, to the footprint (0 inside it); share_over_allowance is the share of
    samples whose gap exceeds allowance_mm. With no section, or with nothing printed where
    there is one (nothing_printed, an infinite gap), the gap entries are None. unmatched
    lists the parts and holes of the model and of the print not matched one to one.
    max_over_mm is the largest distance from printed plastic to the model region
    (overprint_points), with where it is; plastic printed where the model has no section
    is printed_without_model, and the overprint entries are then None. score is the mean
    gap plus the mean overprint over their samples (0 for none), for choosing the turn.
    edges is edge_gaps' result for this layer and alignment, when already computed.
    """
    model_bed = alignment.apply(section)
    model_parts, printed_parts = _polygons(model_bed), _polygons(printed)
    model_holes, holes = enclosed_regions(model_bed), printed_holes(printed, model_bed)
    out = {"max_gap_mm": None, "at_bed_mm": None, "at_model_mm": None,
           "share_over_allowance": None,
           "nothing_printed": not model_bed.is_empty and printed.is_empty,
           "parts_model": len(model_parts), "parts_printed": len(printed_parts),
           "holes_model": len(model_holes), "holes_printed": len(holes),
           "unmatched": (match(model_parts, printed_parts, "part", alignment)
                         + match(model_holes, holes, "hole", alignment)),
           "printed_without_model": model_bed.is_empty and not printed.is_empty,
           "max_over_mm": None, "over_at_bed_mm": None, "over_at_model_mm": None,
           "score": 0.0}
    if not printed.is_empty and not model_bed.is_empty:
        over = overprint_points(printed, model_bed)
        if len(over):
            d = gaps(over, model_bed)
            j = int(np.argmax(d))
            out.update(max_over_mm=float(d[j]), over_at_bed_mm=[float(v) for v in over[j]],
                       over_at_model_mm=[float(v) for v in alignment.to_model(over[j:j + 1])[0]])
            out["score"] += float(d.mean())
        else:
            out["max_over_mm"] = 0.0
    if model_bed.is_empty or printed.is_empty:
        return out
    model_pts, pts, d = edges if edges is not None else edge_gaps(section, printed, alignment)
    i = int(np.argmax(d))
    out.update(max_gap_mm=float(d[i]), at_bed_mm=[float(v) for v in pts[i]],
               share_over_allowance=float((d > allowance_mm).mean()),
               at_model_mm=[float(v) for v in model_pts[i]])
    out["score"] += float(d.mean())
    return out


# --- Choosing the turn ------------------------------------------------------------------

# How far a layer score (a mean of sampled distances) can be from the same mean taken over
# the continuous edge and plastic: each sample stands for the points it is nearest to, and
# distance is 1-Lipschitz, so an edge sample is within EDGE_SAMPLE_MM / 2 of them and an
# overprint sample within EDGE_SAMPLE_MM (1 / sqrt 2 + 1 / 2) (overprint_points). Two turns
# whose scores differ by no more than twice this cannot be told apart by the scores.
SCORE_BOUND_MM = EDGE_SAMPLE_MM / 2 + EDGE_SAMPLE_MM * (1 / math.sqrt(2) + 0.5)
COVERAGE_BOUND_MM = EDGE_SAMPLE_MM / 2
OVERPRINT_BOUND_MM = EDGE_SAMPLE_MM * (1 / math.sqrt(2) + 0.5)


@dataclass(frozen=True)
class Turn:
    """One quarter turn: its alignment, its layers' metrics and its score.

    score is the mean over layers of each layer's score. complete is False when the turn
    was dropped early because its partial score already exceeded the best turn's by more
    than 2 * SCORE_BOUND_MM; score is then a lower bound and layers is partial.
    """
    alignment: Alignment
    layers: list[dict]
    score: float
    complete: bool


@dataclass(frozen=True)
class Analysis:
    turns: list[Turn]              # complete turns by score (the best first), then dropped
    layer_count: int               # Z_HEIGHT layers in the G-code
    last_z: float                  # the highest Z_HEIGHT
    last_height: float             # its LAYER_HEIGHT
    model_top: float               # the model's highest z


def analyse(text: str, stl: bytes | trimesh.Trimesh, plate: Plate, allowance_first_mm: float,
            allowance_mm: float, flow: Flow | None = None) -> Analysis:
    """Every quarter turn's metrics, the turns ordered by their two-sided score.

    The placement is known: OrcaSlicer centres the model's bounding box on the plate
    (measured: on layers above the first, the outer walls' box centre was within 0.004 mm of
    the plate centre for Roadie and Oddie, and their models' box centres came out at
    (128.0007, 128.0013) and (127.995, 128.002) on the A1's 256 mm plate). A fitted shift
    could absorb a one-sided error, such as a long side printed short; the known one cannot.
    Only the quarter turn is chosen (the bridge controls were turned 90 degrees), by a
    score over all layers: the mean model-edge-to-plastic gap plus the mean distance of
    plastic outside the model to the model. A wrong turn leaves edges unprinted and puts
    plastic outside, even where a one-sided median of edge distances ties (a square with an
    off-centre hole). Turns are measured in the order of their first layer's mean edge gap;
    before each layer, a turn whose score so far plus that layer's mean edge gap (a lower
    bound, since scores only grow) already exceeds the best complete turn's by more than
    2 * SCORE_BOUND_MM is dropped, so a clearly wrong turn costs one layer's edge gaps. If
    the slicer ever placed the part elsewhere, the gaps would grow and the checks would
    FAIL: the safe direction.

    The first layer is the lowest Z_HEIGHT; it gets allowance_first_mm and the others
    allowance_mm. Raises UnsupportedGcode as parse_gcode does, and when the model has no
    section at the first layer.
    """
    layers = parse_gcode(text, plate, flow)
    mesh = load_mesh(stl)
    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    zs = sorted(layers)
    sections = [model_section(mesh, layers[z].mid_z) for z in zs]
    if sections[0].is_empty:
        raise UnsupportedGcode("the model has no section at the first layer")
    printed = [footprint(layers[z].segments) for z in zs]
    centre = (float(bounds[0, 0] + bounds[1, 0]) / 2, float(bounds[0, 1] + bounds[1, 1]) / 2)
    n = len(zs)

    def edge_mean(edges):
        return 0.0 if edges is None else float(edges[2].mean())

    firsts = []
    for angle in QUARTER_TURNS:
        alignment = Alignment(angle, centre, plate.centre)
        edges = edge_gaps(sections[0], printed[0], alignment)
        firsts.append((edge_mean(edges), angle, alignment, edges))
    firsts.sort(key=lambda f: (f[0], f[1]))
    complete, dropped = [], []
    for _, _, alignment, first_edges in firsts:
        done, total = [], 0.0
        best = min((t.score for t in complete), default=None)
        for i in range(n):
            edges = first_edges if i == 0 else edge_gaps(sections[i], printed[i], alignment)
            if best is not None and (total + edge_mean(edges)) / n > best + 2 * SCORE_BOUND_MM:
                total += edge_mean(edges)
                break
            allowance = allowance_first_mm if i == 0 else allowance_mm
            done.append({"z": zs[i], "allowance_mm": allowance,
                         **layer_metrics(sections[i], printed[i], alignment, allowance,
                                         edges)})
            total += done[-1]["score"]
        turn = Turn(alignment, done, total / n, len(done) == n)
        (complete if turn.complete else dropped).append(turn)
    complete.sort(key=lambda t: (t.score, t.alignment.angle))
    return Analysis(complete + dropped, n, zs[-1], layers[zs[-1]].height,
                    float(bounds[1, 2]))


# --- F3 checks for tdmg slice ----------------------------------------------------------


@dataclass(frozen=True)
class Setup:
    """What the F3 checks need beyond the G-code and the STL, from the profiles and rules."""
    plate: Plate
    flow: Flow
    tolerance_mm: float               # acceptance.dimension.tolerance
    elephant_foot_mm: float           # the process profile's elefant_foot_compensation
    allowed_layers: frozenset[int]    # the layer counts the model's thickness allows (F6)


def _place(point) -> str:
    return "(" + ", ".join(f"{v:.2f}" for v in point) + ")"


def _unknown_all(reason: str, threshold: dict) -> list[CheckResult]:
    return [CheckResult(CONNECTIVITY, "UNKNOWN", None, None, None, f"not measured: {reason}"),
            CheckResult(COVERAGE, "UNKNOWN", None, threshold, TOLERANCE_RULE,
                        f"not measured: {reason}"),
            CheckResult(OVERPRINT, "UNKNOWN", None, threshold, TOLERANCE_RULE,
                        f"not measured: {reason}")]


def f3_checks(gcode: bytes | None, stl: bytes, setup: Setup,
              not_measured: str | None = None) -> tuple[list[CheckResult], dict]:
    """The three F3 checks (F3.printed_connectivity, F3.edge_coverage, F3.edge_overprint)
    and the record's "printed" entry.

    The rules (the plan, Decisions 2 and 2a):
    - F3.printed_connectivity PASSes when on every layer the parts and holes of the
      footprint match those of the model section one to one; otherwise it FAILs, naming
      the layers and where the unmatched parts or holes are.
    - F3.edge_coverage measures the model-edge-to-plastic gap against the allowance:
      setup.tolerance_mm (acceptance.dimension.tolerance), plus setup.elephant_foot_mm (the
      profile's elefant_foot_compensation) on the first layer, where the slicer shrinks the
      outline on purpose. It also FAILs when the G-code's own layer count is not one the
      model's thickness allows (setup.allowed_layers, as F6.layer_count), or when the model
      goes on more than half a layer above the last printed layer, naming the unprinted
      heights.
    - F3.edge_overprint is the reverse (Decision 2a): the distance of printed plastic
      outside the model to the model region, against the same allowance. Plastic on a layer
      where the model has no section FAILs it.
    Coverage and overprint are judged with their sampling bounds: PASS only when the
    sampled largest plus the bound (COVERAGE_BOUND_MM, OVERPRINT_BOUND_MM) is within the
    allowance on every layer, FAIL when the sampled largest exceeds it on any layer, and
    UNKNOWN in between ("within sampling uncertainty").

    The turn with the lowest score is used (analyse). When another complete turn scores
    within 2 * SCORE_BOUND_MM of it and gives a different status for any of the three
    checks, the placement is ambiguous and all three are UNKNOWN; when such turns agree,
    the best one's results stand. The record lists every turn's score.

    All three are UNKNOWN, with the reason, when not_measured is given (the slicer
    failed), when there is no G-code, when the G-code is unsupported, or when the analysis
    raises any other error (an "analysis error", never a PASS).
    """
    tolerance_mm, first_mm = setup.tolerance_mm, setup.tolerance_mm + setup.elephant_foot_mm
    threshold = {"first_layer_mm": first_mm, "other_layers_mm": tolerance_mm}
    record = {"measured": False, "reason": None,
              "allowance_mm": {"first_layer": first_mm, "other_layers": tolerance_mm,
                               "elefant_foot_compensation": setup.elephant_foot_mm},
              "edge_sample_mm": EDGE_SAMPLE_MM, "layer_count": None, "alignment": None,
              "layers": []}
    reason = not_measured or (None if gcode else "no G-code was written")
    if reason is None:
        try:
            analysis = analyse(gcode.decode("utf-8"), stl, setup.plate, first_mm,
                               tolerance_mm, setup.flow)
        except UnicodeDecodeError as err:
            reason = f"the G-code is not UTF-8 text: {err}"
        except UnsupportedGcode as err:
            reason = f"the G-code cannot be measured: {err}"
        except Exception as err:     # noqa: BLE001 - any failure is UNKNOWN, never a PASS
            reason = f"analysis error: {type(err).__name__}: {err}"
    if reason is not None:
        record["reason"] = reason
        return _unknown_all(reason, threshold), record
    complete = [t for t in analysis.turns if t.complete]
    best = complete[0]
    tied = [t for t in complete if t.score - best.score <= 2 * SCORE_BOUND_MM]
    judged = [(_connectivity(t.layers, t.alignment), _coverage(t.layers, t.alignment, threshold),
               _overprint(t.layers, t.alignment, threshold)) for t in tied]
    checks = list(judged[0])
    record.update(measured=True, layer_count=analysis.layer_count,
                  alignment={**best.alignment.as_dict(),
                             "tied_angles_deg": [t.alignment.angle for t in tied],
                             "scores": [{"angle_deg": t.alignment.angle, "score": t.score,
                                         "complete": t.complete} for t in analysis.turns]},
                  layers=[{"z": m["z"], "max_gap_mm": m["max_gap_mm"],
                           "parts": [m["parts_model"], m["parts_printed"]],
                           "holes": [m["holes_model"], m["holes_printed"]],
                           "max_over_mm": m["max_over_mm"],
                           "unmatched": len(m["unmatched"])} for m in best.layers])
    statuses = {tuple(c.status for c in j) for j in judged}
    if len(statuses) > 1:
        detail = "; ".join(f"turn {t.alignment.angle} (score {t.score:.4f}): "
                           + ", ".join(f"{c.id} {c.status}" for c in j)
                           for t, j in zip(tied, judged, strict=True))
        reason = ("placement ambiguous: these turns score within the scores' sampling bound "
                  f"({2 * SCORE_BOUND_MM:.3f} mm) but give different verdicts: {detail}")
        record["reason"] = reason
        return _unknown_all(reason, threshold), record
    short = _truncation(analysis, setup.allowed_layers, threshold)
    if short is not None:
        checks[1] = short
    return checks, record


def _truncation(analysis: Analysis, allowed: frozenset[int],
                threshold: dict) -> CheckResult | None:
    """F3.edge_coverage FAIL when the G-code stops short of the model (or goes beyond it)."""
    n, last_z, top = analysis.layer_count, analysis.last_z, analysis.model_top
    unprinted = top - last_z > analysis.last_height / 2 + z_tolerance(top, last_z, 0.0)
    if n in allowed and not unprinted:
        return None
    measured = {"layers_printed": n, "layers_allowed": sorted(allowed), "last_z_mm": last_z,
                "model_top_mm": top}
    why = [] if n in allowed else [f"the G-code has {n} layers, not one of {sorted(allowed)}"]
    if unprinted:
        why.append(f"the model from z = {last_z:g} to {top:g} mm is not printed")
    return CheckResult(COVERAGE, "FAIL", measured, threshold, TOLERANCE_RULE,
                       "; ".join(why) + ": the print stops short of the model. " + SCOPE)


def _judged(layers, key, bound) -> tuple[str, list, list]:
    """(status, layers over the allowance, layers within the sampling bound of it)."""
    over = [m for m in layers if m[key] > m["allowance_mm"]]
    near = [m for m in layers if m[key] + bound > m["allowance_mm"] >= m[key]]
    return ("FAIL" if over else "UNKNOWN" if near else "PASS"), over, near


def _connectivity(layers: list[dict], alignment: Alignment) -> CheckResult:
    bad = [m for m in layers if m["unmatched"]]
    measured = {"layers": len(layers), "layers_mismatched": len(bad),
                "angle_deg": alignment.angle}
    how = ("Parts and holes of the printed footprint matched one to one with the model "
           "section's, per layer; a void inside the model (sparse infill) is not a hole. ")
    if not bad:
        return CheckResult(CONNECTIVITY, "PASS", measured, None, None,
                           how + "Every layer matches. " + SCOPE)
    m = bad[0]
    listed = m["unmatched"][:UNMATCHED_LISTED]
    measured.update(mismatched_z=[b["z"] for b in bad], first_z=m["z"],
                    parts_model=m["parts_model"], parts_printed=m["parts_printed"],
                    holes_model=m["holes_model"], holes_printed=m["holes_printed"],
                    unmatched=listed, largest_gap_at_model_mm=m["at_model_mm"])
    items = "; ".join(f"a {u['what']} overlapping {u['overlaps']} at model "
                      f"{_place(u['at_model_mm'])} mm" for u in listed)
    more = len(m["unmatched"]) - len(listed)
    gap = ("" if m["at_model_mm"] is None else
           f"; the layer's largest edge gap is at model {_place(m['at_model_mm'])} mm")
    return CheckResult(
        CONNECTIVITY, "FAIL", measured, None, None,
        how + f"{len(bad)} of {len(layers)} layers differ; the first, z = {m['z']:g} mm, has "
        f"{m['parts_printed']} printed part(s) for the model's {m['parts_model']} and "
        f"{m['holes_printed']} printed hole(s) for its {m['holes_model']}. Unmatched: "
        f"{items}" + (f" and {more} more" if more > 0 else "") + gap
        + ": a connection or a hole of the model is not printed as such. " + SCOPE)


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
    status, over, near = _judged(measured_layers, "max_gap_mm", COVERAGE_BOUND_MM)
    measured = {"worst_z": worst["z"], "max_gap_mm": worst["max_gap_mm"],
                "allowance_mm": worst["allowance_mm"], "at_bed_mm": worst["at_bed_mm"],
                "at_model_mm": worst["at_model_mm"],
                "share_over_allowance": worst["share_over_allowance"],
                "layers_over": len(over), "layers_within_sampling_bound": len(near),
                "sampling_bound_mm": COVERAGE_BOUND_MM, "angle_deg": alignment.angle}
    how = (f"The largest distance from a model-edge sample (every {EDGE_SAMPLE_MM:g} mm; the "
           f"true largest is at most {COVERAGE_BOUND_MM:g} mm more) to printed plastic, "
           "with the model's bounding box centred on the plate as the slicer places it, "
           "against the tolerance, plus the profile's elefant_foot_compensation on the "
           "first layer. ")
    summary = (f"The worst layer, z = {worst['z']:g} mm, leaves {worst['max_gap_mm']:.3f} mm "
               f"against {worst['allowance_mm']:g} mm, at bed {_place(worst['at_bed_mm'])}, "
               f"model {_place(worst['at_model_mm'])} mm"
               + (f"; {len(over)} layer(s) are over. " if over else
                  f"; within sampling uncertainty on {len(near)} layer(s). " if near
                  else ". "))
    return CheckResult(COVERAGE, status, measured, threshold, TOLERANCE_RULE,
                       how + summary + SCOPE)


def _overprint(layers: list[dict], alignment: Alignment, threshold: dict) -> CheckResult:
    without = [m["z"] for m in layers if m["printed_without_model"]]
    if without:
        return CheckResult(
            OVERPRINT, "FAIL", {"printed_without_model_z": without,
                                "angle_deg": alignment.angle},
            threshold, TOLERANCE_RULE,
            f"{len(without)} layer(s), the first at z = {without[0]:g} mm, print where the "
            "model has no section. " + SCOPE)
    measured_layers = [m for m in layers if m["max_over_mm"] is not None]
    if not measured_layers:
        return CheckResult(OVERPRINT, "UNKNOWN", None, threshold, TOLERANCE_RULE,
                           "not measured: no layer prints where the model has a section")
    worst = max(measured_layers, key=lambda m: m["max_over_mm"] - m["allowance_mm"])
    status, over, near = _judged(measured_layers, "max_over_mm", OVERPRINT_BOUND_MM)
    measured = {"worst_z": worst["z"], "max_over_mm": worst["max_over_mm"],
                "allowance_mm": worst["allowance_mm"], "at_bed_mm": worst["over_at_bed_mm"],
                "at_model_mm": worst["over_at_model_mm"], "layers_over": len(over),
                "layers_within_sampling_bound": len(near),
                "sampling_bound_mm": OVERPRINT_BOUND_MM, "angle_deg": alignment.angle}
    how = (f"The largest distance from printed plastic outside the model to the model region "
           f"(sampled every {EDGE_SAMPLE_MM:g} mm on and inside that plastic; the true largest "
           f"is at most {OVERPRINT_BOUND_MM:.3f} mm more), with the model's bounding box "
           "centred on the plate, against the tolerance, plus the profile's "
           "elefant_foot_compensation on the first layer. ")
    where = ("" if worst["over_at_bed_mm"] is None else
             f", at bed {_place(worst['over_at_bed_mm'])}, model "
             f"{_place(worst['over_at_model_mm'])} mm")
    summary = (f"The worst layer, z = {worst['z']:g} mm, prints {worst['max_over_mm']:.3f} mm "
               f"outside against {worst['allowance_mm']:g} mm{where}"
               + (f"; {len(over)} layer(s) are over. " if over else
                  f"; within sampling uncertainty on {len(near)} layer(s). " if near
                  else ". "))
    return CheckResult(OVERPRINT, status, measured, threshold, TOLERANCE_RULE,
                       how + summary + SCOPE)

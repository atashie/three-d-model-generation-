"""The multicolor G-code reader and its gate checks (docs/plans/2026-11-13-color-slicing.md,
Decision 4 as amended after Task 2, and Task 5).

Why a module of its own: tdmg.printed is R1's reader, and its guarantees are about one
model printed by one tool; tdmg.color_checks gates the colored geometry and the 3MF files.
This module reads what only a multicolor G-code has (which tool prints what, the tool
changes, the flush and the prime tower) and judges it against the gated bodies
(tdmg.threemf.Shell, in shell order: the base first, then the inlays by palette index).

The reader (read_multicolor) has two passes over the same text, and refuses
(UnsupportedGcode) what either cannot read, so the checks are UNKNOWN, never PASS:
- the geometry: tdmg.printed.parse_gcode(prime_tower=True), R1's strict reader, which
  keeps the prime tower apart from the model and gives each segment its line;
- the structure (_structure): the blocks, every T command, the M620 S<n>A ... M621 S<n>A
  pairs, the "; CP TOOLCHANGE START" ... "END" blocks, the "; FLUSH_START" ... "END"
  blocks with their E-only moves, the M620.10 L word, and the header. The markers and the
  counting rules are those Task 2 measured on 16 G-codes
  (research/verification/2026-11-13-color-slicing/README.md, "Markers" and "What the
  amended rules need from a reader"):
  - start: every line before the first "; CHANGE_LAYER"; layer k: from the k-th; end:
    from the first "; FEATURE: Custom" after the layers began (OrcaSlicer writes it before
    the end template);
  - a tool command is T<n>. T1000 (written twice by the A1 start code) is not a filament,
    and is read in the start block only. T255 (the end unload) is read in the end block
    only, inside M620 S255 ... M621 S255. Any other n of 255 or more is refused;
  - the start load is each T<n> (n < 255) in the start block; a change is each T<n>
    (n < 255) in a layer block. Where each one lies (its M620 pair, its CP TOOLCHANGE
    block) is recorded and judged by F6.color_changes; a T<n> in the end block is
    recorded and FAILs it;
  - M620 is read in the forms M620 M (the start code's remap), M620 S<n>A and M620 S255,
    and M621 in the forms M621 S<n>A and M621 S255; the pairs must match and not nest. A
    FLUSH block must lie inside a CP TOOLCHANGE block and hold no move but E-only G0/G1
    (with E and F words only, E > 0, relative E). Anything else of these is refused.
  The two passes must agree: one Z_HEIGHT per CHANGE_LAYER, the same heights, and every
  segment in the block of its layer.
Each segment's tool is the last T<n> (n < 255) before its line.

The checks (color_slice_checks), each with expected values from the bodies alone. Tool n
prints the body at shell position n (tdmg.orca_input.filament_map: filament n + 1). A body
is on a layer when the layer's mid-height (Z_HEIGHT - LAYER_HEIGHT / 2) lies strictly
inside its z range, Task 2's rule (measure_slicing.expected_sets).
- F6.color_changes (gated): (a) each layer's set of tools printing model features equals
  its set of bodies; (b) on each layer each tool prints in one contiguous run (model
  features, in file order, consecutive repeats merged); (c) the change count equals the
  sum over layers of (bodies on the layer - 1), plus the layer boundaries where a layer's
  first tool differs from the previous layer's last (layer 1 against the start load);
  every change lies inside M620 S<n>A ... M621 S<n>A for its own n and inside a CP
  TOOLCHANGE block; no load in the end code; and (amended Decision 2) the start block
  loads exactly one filament, inside its own M620 pair, and it is the first tool printing
  on layer 1. The exact minimum (min_changes) and the statistics' filament_changes are
  recorded as information.
- F6.tool_placement (gated): each tool prints only on its body's layers and within its
  body's section, with R1's bead model (tdmg.printed.footprint) and allowance (rule
  acceptance.dimension.tolerance, plus elefant_foot_compensation on the first layer), as
  F3.edge_overprint judges it (FAIL over the allowance, UNKNOWN within the sampling bound
  OVERPRINT_BOUND_MM of it), at the fixed placement PLACEMENT_ANGLE (the model's
  bounding-box centre on the plate centre, not turned; Task 2's measured placement), so a
  print turned by 90, 180 or 270 degrees FAILs; every body is printed by its own tool on
  each of its layers; no other tool prints model features; and the prime tower's beads
  reach into the silhouette by no more than the same allowance (_tower_depth).
- F6.filaments_used (gated): the filaments loaded and the tools printing model features
  are exactly the plan's, one per body; the header's "; filament:" list is 1..n; the
  config's filament_colour is the plan's colors in filament order.
- F3 (R1's three G-code checks, tdmg.printed.judge_f3): on the silhouette (every tool's
  model extrusion against the union of the bodies' sections; R1's ids), and per tool
  against its own body (ids "<F3 id>.T<n>"), all at the fixed placement. Which are
  required is the owner's decision of 2026-11-13, "Outer edge only" (plan Task 7):
  - required (f3_required_ids): the silhouette's F3.edge_coverage and F3.edge_overprint,
    and each tool's F3.edge_overprint;
  - warnings (f3_warning_ids; recorded, not required): the silhouette's
    F3.printed_connectivity (on the eight Task 2 G-codes it FAILs on every multicolor
    layer: neighbouring bodies' beads meet edge to edge and the bead model leaves gaps of
    up to about 0.03 mm, crosscheck_task5.py in
    research/verification/2026-11-13-color-slicing/), and each tool's
    F3.printed_connectivity and F3.edge_coverage (bands narrower than a bead that the
    slicer skips, such as a kept outline line).
  The F6 checks judge plastic outside a body, not a body left unprinted. Of the three
  partly unprinted fixtures in tests/test_color_gcode.py (re-run 2026-11-13 with this
  set): half the base's first layer is still caught by a required check (the
  silhouette's F3.edge_coverage); half an inlay and only a dot of an inlay now only warn
  (that tool's F3.edge_coverage, and for the dot also the silhouette's
  F3.printed_connectivity), because the other colors' plastic is not checked against
  the missing inlay's edge by a required check. The owner accepted this trade-off; no
  check was added. required_check_ids gives the required set.
- Information only, status UNKNOWN (as R1 keeps F3.thin_regions): F6.color_waste (flush
  from the FLUSH blocks and prime tower from its extrusion, in mm3 with the pinned
  profile's filament diameter, per tool and per change, with the M620.10 L words),
  F6.color_time (the header's times) and F6.color_filament (model filament per tool from
  the G-code), each with the statistics' values beside them.

tdmg.color_slicing runs these checks for each face in tdmg slice (plan Task 6). Every rule
and constant here is part of what its colorslice_id names, through its algorithm label.
"""

from __future__ import annotations

import bisect
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import shapely
import trimesh

from tdmg.checks import CheckResult
from tdmg.orca_input import filament_map
from tdmg.printed import (
    COVERAGE,
    CUSTOM,
    F3_SLICE_CHECK_IDS,
    OVERPRINT,
    OVERPRINT_BOUND_MM,
    TOLERANCE_RULE,
    Alignment,
    Flow,
    Layer,
    Plate,
    Segment,
    Setup,
    UnsupportedGcode,
    _f3_base,
    _words,
    analyse_sections,
    footprint,
    gaps,
    judge_f3,
    model_section,
    overprint_points,
    parse_gcode,
)
from tdmg.threemf import Shell

COLOR_CHANGES = "F6.color_changes"
TOOL_PLACEMENT = "F6.tool_placement"
FILAMENTS_USED = "F6.filaments_used"
COLOR_WASTE = "F6.color_waste"
COLOR_TIME = "F6.color_time"
COLOR_FILAMENT = "F6.color_filament"
GATED_CHECK_IDS = (COLOR_CHANGES, TOOL_PLACEMENT, FILAMENTS_USED)
INFO_CHECK_IDS = (COLOR_WASTE, COLOR_TIME, COLOR_FILAMENT)
INFO_NOTE = "information only, not gated (docs/plans/2026-11-13-color-slicing.md, Decision 4)"
F3_REQUIRED_NOTE = ("Required for PRINTABLE (the owner's decision of 2026-11-13, "
                    "\"Outer edge only\"; docs/plans/2026-11-13-color-slicing.md, Task 7).")
F3_WARNING_NOTE = ("A warning, recorded and not required for PRINTABLE (the owner's "
                   "decision of 2026-11-13, \"Outer edge only\"; "
                   "docs/plans/2026-11-13-color-slicing.md, Task 7).")
NO_FILAMENT = 255          # T255: the end code's unload
NOT_A_FILAMENT = 1000      # T1000: written twice by the A1 start code
# M600 (filament change) and M601 (pause): the pinned slicer writes neither for this
# profile (none in the 16 Task 2 G-codes); after either the printer may hold another color.
REFUSED_M_COMMANDS = frozenset({"M600", "M601"})
# The multicolor placement is fixed: the model's bounding-box centre on the plate centre
# (the centring R1 uses), turned by 0 degrees, with no quarter-turn search. Task 2 measured
# the B_msc input sliced in place on all 16 runs: the centre of the base tool's centreline
# extent within 0.01 mm of the plate centre, each tool's centrelines inside its own body
# with no rotation (research/verification/2026-11-13-color-slicing/README.md, "Placement").
# A search would let a print turned 180 degrees pass where its inlays swap colors, which is
# a colour error (controller decision, 2026-11-13).
PLACEMENT_ANGLE = 0
TOOL = re.compile(r"T(0|[1-9][0-9]*)")
M620_OPEN = re.compile(r"S(0|[1-9][0-9]*)A")
TIME = re.compile(r"(?:(\d+)d\s*)?(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?")
# Display only: how many problems a FAIL lists in its note.
LISTED = 5


def per_tool_id(check_id: str, tool: int) -> str:
    """The id of a per-tool F3 check: "<F3 id>.T<tool>"."""
    return f"{check_id}.T{tool}"


def f3_ids(tools: int) -> tuple[str, ...]:
    """Every F3 check color_slice_checks returns for a plan of this many tools: the
    silhouette's three, then each tool's three."""
    return (*F3_SLICE_CHECK_IDS,
            *(per_tool_id(c, t) for t in range(tools) for c in F3_SLICE_CHECK_IDS))


def f3_required_ids(tools: int) -> tuple[str, ...]:
    """The F3 checks PRINTABLE requires (the owner's "Outer edge only", 2026-11-13): the
    silhouette's F3.edge_coverage and F3.edge_overprint, then each tool's
    F3.edge_overprint."""
    return (COVERAGE, OVERPRINT, *(per_tool_id(OVERPRINT, t) for t in range(tools)))


def f3_warning_ids(tools: int) -> tuple[str, ...]:
    """The F3 checks that are warnings: every F3 check not in f3_required_ids (the
    silhouette's F3.printed_connectivity, each tool's F3.printed_connectivity and
    F3.edge_coverage)."""
    required = set(f3_required_ids(tools))
    return tuple(c for c in f3_ids(tools) if c not in required)


def f3_note(check_id: str) -> str:
    """F3_REQUIRED_NOTE or F3_WARNING_NOTE for this F3 check id (silhouette or per tool)."""
    base = check_id.rsplit(".T", 1)[0] if ".T" in check_id else check_id
    tool = check_id != base
    required = base == OVERPRINT or (base == COVERAGE and not tool)
    return F3_REQUIRED_NOTE if required else F3_WARNING_NOTE


def required_check_ids(tools: int) -> frozenset[str]:
    """Every check of color_slice_checks that PRINTABLE requires, for a plan of this many
    tools: GATED_CHECK_IDS and f3_required_ids. The INFO_CHECK_IDS are not required."""
    return frozenset((*GATED_CHECK_IDS, *f3_required_ids(tools)))


@dataclass(frozen=True)
class ToolLine:
    """One T<n> command: its line, n, its block ("start", "layer" or "end"), its layer
    (1-based; None outside the layers), the n of the M620 S<n>A (or 255 for M620 S255)
    it lies in (None if none), and whether it lies in a CP TOOLCHANGE block."""
    line: int
    tool: int
    block: str
    layer: int | None
    m620: int | None
    in_toolchange: bool

    def as_dict(self) -> dict:
        return {"line": self.line, "tool": self.tool, "block": self.block,
                "layer": self.layer, "m620": self.m620, "in_toolchange": self.in_toolchange}


@dataclass
class ToolChange:
    """One "; CP TOOLCHANGE START" ... "END" block (lines), its layer, the tool before it
    and the tool loaded in it (None if it loads none), its FLUSH blocks' E (E-only moves),
    the other E-only E in it, and the L word of its M620.10 A1 (the template's flush
    length), if any."""
    start: int
    end: int | None
    layer: int | None
    tool_from: int | None
    tool_to: int | None = None
    flush_e_mm: float = 0.0
    flush_blocks: int = 0
    other_e_mm: float = 0.0
    flush_length_l_mm: float | None = None

    def as_dict(self, area: float) -> dict:
        return {"lines": [self.start, self.end], "layer": self.layer,
                "from": self.tool_from, "to": self.tool_to, "flush_blocks": self.flush_blocks,
                "flush_e_mm": self.flush_e_mm, "flush_mm3": self.flush_e_mm * area,
                "flush_length_L_mm": self.flush_length_l_mm,
                "other_e_only_mm": self.other_e_mm}


@dataclass(frozen=True)
class Multicolor:
    """What read_multicolor reads from one multicolor G-code.

    layers: tdmg.printed's layers in file order. model[k] and tower[k]: layer k's model
    and prime-tower segments by tool. orders[k]: the tools printing model features on
    layer k, in file order, consecutive repeats merged. start_loads, changes, end_tools:
    the T<n> commands of the start block (n < 255), of the layers (n < 255) and of the end
    block (any n). model_e_mm, tower_e_mm, flush_e_mm: E per tool (the flush on the tool
    loaded during it). tower_e_by_layer: the prime tower's E per layer. header: the time
    and filament lines (see _header).
    """
    layers: list[Layer]
    model: list[dict[int | None, list[Segment]]]
    tower: list[dict[int | None, list[Segment]]]
    orders: list[list[int | None]]
    start_loads: list[ToolLine]
    changes: list[ToolLine]
    end_tools: list[ToolLine]
    t1000_lines: list[int]
    toolchanges: list[ToolChange]
    model_e_mm: dict[int | None, float]
    tower_e_mm: dict[int | None, float]
    flush_e_mm: dict[int | None, float]
    tower_e_by_layer: list[float]
    header: dict = field(default_factory=dict)


# --- The reader ---------------------------------------------------------------------------


def read_multicolor(text: str, plate: Plate, flow: Flow | None = None) -> Multicolor:
    """Read a multicolor OrcaSlicer G-code (see the module docstring). Raises
    UnsupportedGcode for anything either pass cannot read, or when they disagree."""
    by_z = parse_gcode(text, plate, flow, prime_tower=True)
    layers = list(by_z.values())                       # file order (parse_gcode refuses
    s = _structure(text)                               # Z_HEIGHTs that do not increase)
    if s["layer_z"] != [lay.z for lay in layers]:
        raise UnsupportedGcode(f"the layer blocks (; CHANGE_LAYER, then the first Z_HEIGHT: "
                               f"{s['layer_z']}) do not match the Z_HEIGHT layers "
                               f"({[lay.z for lay in layers]})")
    starts = s["layer_lines"]
    ends = [*starts[1:], s["end_line"] if s["end_line"] is not None else math.inf]
    timeline = s["timeline"]                           # (line, tool), increasing lines
    lines = [ln for ln, _ in timeline]

    def tool_at(line: int) -> int | None:
        i = bisect.bisect_left(lines, line)
        return timeline[i - 1][1] if i else None

    e_of = s["e_of_line"]
    model, tower, orders = [], [], []
    model_e: dict[int | None, float] = {}
    tower_e: dict[int | None, float] = {}
    tower_by_layer = []
    for k, lay in enumerate(layers):
        by_tool: dict[int | None, list[Segment]] = {}
        order: list[int | None] = []
        seen: set[int] = set()
        for seg in lay.segments:
            if not starts[k] < seg.line < ends[k]:
                raise UnsupportedGcode(f"line {seg.line}: an extrusion of the layer at "
                                       f"Z_HEIGHT {lay.z:g} outside that layer's block")
            t = tool_at(seg.line)
            by_tool.setdefault(t, []).append(seg)
            if not order or order[-1] != t:
                order.append(t)
            if seg.line not in seen:
                seen.add(seg.line)
                model_e[t] = model_e.get(t, 0.0) + e_of[seg.line]
        twr: dict[int | None, list[Segment]] = {}
        layer_tower = 0.0
        for seg in lay.tower:
            if not starts[k] < seg.line < ends[k]:
                raise UnsupportedGcode(f"line {seg.line}: a prime-tower extrusion of the "
                                       f"layer at Z_HEIGHT {lay.z:g} outside that layer's "
                                       "block")
            t = tool_at(seg.line)
            twr.setdefault(t, []).append(seg)
            if seg.line not in seen:
                seen.add(seg.line)
                tower_e[t] = tower_e.get(t, 0.0) + e_of[seg.line]
                layer_tower += e_of[seg.line]
        model.append(by_tool)
        tower.append(twr)
        orders.append(order)
        tower_by_layer.append(layer_tower)
    flush: dict[int | None, float] = {}
    for c in s["toolchanges"]:
        if c.flush_e_mm:
            flush[c.tool_to] = flush.get(c.tool_to, 0.0) + c.flush_e_mm
    return Multicolor(layers, model, tower, orders, s["start_loads"], s["changes"],
                      s["end_tools"], s["t1000"], s["toolchanges"], model_e, tower_e, flush,
                      tower_by_layer, _header(text))


def _structure(text: str) -> dict:
    """The structure pass (module docstring): blocks, tool commands, M620 pairs, CP
    TOOLCHANGE and FLUSH blocks, and the E word of every move with E > 0."""
    block, layer = "start", 0
    layer_lines: list[int] = []
    layer_z: list[float] = []
    end_line = None
    tool = None
    timeline: list[tuple[int, int]] = []
    m620 = None                    # (n, line) of the open M620 S<n>A / S255 (n = 255)
    change: ToolChange | None = None
    flush = None                   # the line of an open FLUSH_START
    relative_e = None
    start_loads, changes, end_tools, t1000 = [], [], [], []
    toolchanges: list[ToolChange] = []
    e_of_line: dict[int, float] = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith(";"):
            tag = line[1:].strip()
            if tag == "CHANGE_LAYER":
                if block == "end":
                    raise UnsupportedGcode(f"line {lineno}: a layer after the end code began")
                layer += 1
                block = "layer"
                layer_lines.append(lineno)
            elif tag.startswith("Z_HEIGHT:"):
                if layer == 0:
                    raise UnsupportedGcode(f"line {lineno}: a Z_HEIGHT before the first "
                                           "CHANGE_LAYER")
                if len(layer_z) == layer:
                    raise UnsupportedGcode(f"line {lineno}: a second Z_HEIGHT in layer block "
                                           f"{layer}")
                if len(layer_z) != layer - 1:
                    raise UnsupportedGcode(f"line {lineno}: layer block {layer - 1} has no "
                                           "Z_HEIGHT")
                layer_z.append(float(tag.split(":", 1)[1]))
            elif tag.startswith("FEATURE:") and block == "layer":
                if tag.split(":", 1)[1].strip() == CUSTOM:
                    block, end_line = "end", lineno
            elif tag == "CP TOOLCHANGE START":    # parse_gcode refuses bad pairing
                change = ToolChange(lineno, None, layer if block == "layer" else None, tool)
            elif tag == "CP TOOLCHANGE END":
                if flush is not None:
                    raise UnsupportedGcode(f"line {lineno}: a CP TOOLCHANGE ends inside the "
                                           f"FLUSH block opened at line {flush}")
                change.end = lineno
                toolchanges.append(change)
                change = None
            elif tag == "FLUSH_START":
                if change is None or flush is not None:
                    raise UnsupportedGcode(f"line {lineno}: a FLUSH_START outside a CP "
                                           "TOOLCHANGE block, or inside another FLUSH block")
                flush = lineno
                change.flush_blocks += 1
            elif tag == "FLUSH_END":
                if flush is None:
                    raise UnsupportedGcode(f"line {lineno}: a FLUSH_END without a FLUSH_START")
                flush = None
            continue
        code = line.split(";", 1)[0].strip()
        if not code:
            continue
        command = code.split()[0]
        rest = code.split()[1:]
        if command in REFUSED_M_COMMANDS:
            raise UnsupportedGcode(f"line {lineno}: {command} (a manual filament change or a "
                                   "pause) is not read: the color printed after it is not "
                                   "known")
        if command == "M82":
            relative_e = False
        elif command == "M83":
            relative_e = True
        elif command == "M620":
            m620 = _m620(rest, m620, block, lineno, code)
        elif command == "M621":
            _m621(rest, m620, lineno, code)
            m620 = None
        elif command == "M620.10" and change is not None:
            words = _words(code, lineno)
            if words.get("A") == 1 and "L" in words:
                change.flush_length_l_mm = words["L"]
        elif TOOL.fullmatch(command):
            if rest:
                raise UnsupportedGcode(f"line {lineno}: {code!r}: a tool command with words")
            n = int(command[1:])
            where = ToolLine(lineno, n, block, layer if block == "layer" else None,
                             None if m620 is None else m620[0], change is not None)
            if n == NOT_A_FILAMENT:
                if block != "start":
                    raise UnsupportedGcode(f"line {lineno}: T1000 outside the start code")
                t1000.append(lineno)
            elif n == NO_FILAMENT:
                if block != "end" or where.m620 != NO_FILAMENT:
                    raise UnsupportedGcode(f"line {lineno}: T255 (unload) outside M620 S255 "
                                           "... M621 S255 in the end code")
                end_tools.append(where)
            elif n > NO_FILAMENT:
                raise UnsupportedGcode(f"line {lineno}: {command} is not a filament this "
                                       "check reads")
            else:
                {"start": start_loads, "layer": changes, "end": end_tools}[block].append(where)
                tool = n
                timeline.append((lineno, n))
                if change is not None:
                    change.tool_to = n
        elif command in ("G0", "G1", "G2", "G3"):
            words = _words(code, lineno)
            e = words.get("E", 0.0)
            if e > 0:
                e_of_line[lineno] = e
            e_only = command in ("G0", "G1") and "X" not in words and "Y" not in words
            if flush is not None and (not e_only or set(words) - {"E", "F"} or not e > 0):
                raise UnsupportedGcode(f"line {lineno}: {code!r} in the FLUSH block opened at "
                                       f"line {flush} is not an E-only extrusion")
            if change is not None and e_only and e > 0:
                if relative_e is not True:
                    raise UnsupportedGcode(f"line {lineno}: an E-only move in a tool change "
                                           "in absolute or unknown extrusion mode")
                if flush is not None:
                    change.flush_e_mm += e
                else:
                    change.other_e_mm += e
    if m620 is not None:
        raise UnsupportedGcode(f"line {m620[1]}: an M620 without its M621 by the end")
    if len(layer_z) != layer:
        raise UnsupportedGcode(f"layer block {layer} has no Z_HEIGHT")
    return {"layer_lines": layer_lines, "layer_z": layer_z, "end_line": end_line,
            "timeline": timeline, "start_loads": start_loads, "changes": changes,
            "end_tools": end_tools, "t1000": t1000, "toolchanges": toolchanges,
            "e_of_line": e_of_line}


def _m620(rest: list[str], open_: tuple[int, int] | None, block: str, lineno: int,
          code: str) -> tuple[int, int] | None:
    if rest == ["M"] and block == "start":
        return open_
    found = M620_OPEN.fullmatch(rest[0]) if len(rest) == 1 else None
    if found is not None and int(found.group(1)) < NO_FILAMENT:
        n = int(found.group(1))
    elif rest == ["S255"] and block == "end":
        n = NO_FILAMENT
    else:
        raise UnsupportedGcode(f"line {lineno}: {code!r} is not an M620 form this check reads "
                               "(M620 M in the start code, M620 S<n>A, M620 S255 in the end "
                               "code)")
    if open_ is not None:
        raise UnsupportedGcode(f"line {lineno}: {code!r} inside the M620 opened at line "
                               f"{open_[1]}")
    return (n, lineno)


def _m621(rest: list[str], open_: tuple[int, int] | None, lineno: int,
          code: str) -> None:
    found = M620_OPEN.fullmatch(rest[0]) if len(rest) == 1 else None
    if found is not None and int(found.group(1)) < NO_FILAMENT:
        n = int(found.group(1))
    elif rest == ["S255"]:
        n = NO_FILAMENT
    else:
        raise UnsupportedGcode(f"line {lineno}: {code!r} is not an M621 form this check reads")
    if open_ is None or open_[0] != n:
        raise UnsupportedGcode(f"line {lineno}: {code!r} does not close the open M620 "
                               f"({'none' if open_ is None else f'line {open_[1]}'})")


def _seconds(value: str) -> int | None:
    found = TIME.fullmatch(value.strip())
    if found is None or not any(found.groups()):
        return None
    d, h, m, s = (int(g) if g else 0 for g in found.groups())
    return ((d * 24 + h) * 60 + m) * 60 + s


def _header(text: str) -> dict:
    """Information from the header and the config block, None where absent: the times, the
    "; filament:" list, filament_colour, and the end's "; filament used" lines."""
    out = {"model_printing_time_s": None, "total_estimated_time_s": None, "filament": None,
           "filament_colour": None, "filament_used_mm": None, "filament_used_cm3": None,
           "filament_used_g": None}
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith(";"):
            continue
        found = re.fullmatch(r"; model printing time: (.*); total estimated time: (.*)", line)
        if found and out["model_printing_time_s"] is None:
            out["model_printing_time_s"] = _seconds(found.group(1))
            out["total_estimated_time_s"] = _seconds(found.group(2))
        elif line.startswith("; filament: ") and out["filament"] is None:
            out["filament"] = [v.strip() for v in line.split(":", 1)[1].split(",")]
        elif line.startswith("; filament_colour = ") and out["filament_colour"] is None:
            out["filament_colour"] = [v.strip() for v in line.split("=", 1)[1].split(";")]
        else:
            for unit in ("mm", "cm3", "g"):
                if line.startswith(f"; filament used [{unit}] = "):
                    try:
                        out[f"filament_used_{unit}"] = [
                            float(v) for v in line.split("=", 1)[1].split(",")]
                    except ValueError:
                        out[f"filament_used_{unit}"] = None
    return out


# --- Expected values from the bodies ----------------------------------------------------


def body_z_ranges(shells: Sequence[Shell]) -> list[tuple[float, float]]:
    """Each body's (lowest, highest) z, as stored (float32 widened to float64)."""
    out = []
    for s in shells:
        z = np.asarray(s.vertices, dtype=np.float32).astype(np.float64)[:, 2]
        out.append((float(z.min()), float(z.max())))
    return out


def layer_sets(layers: Sequence[Layer], shells: Sequence[Shell]) -> list[list[int]]:
    """Per layer, the shell positions of the bodies on it: those whose z range holds the
    layer's mid-height strictly inside (Task 2's rule)."""
    ranges = body_z_ranges(shells)
    return [[i for i, (lo, hi) in enumerate(ranges) if lo < lay.mid_z < hi] for lay in layers]


def min_changes(sets: Sequence[Sequence[int]], loaded: int | None) -> int | None:
    """The fewest tool changes that print every layer's set of tools, each tool once per
    layer, starting with `loaded` (exact: a dynamic programme over each layer's last
    tool). None when loaded is None."""
    if loaded is None:
        return None
    best = {loaded: 0}
    for s in sets:
        if not s:
            continue
        nxt: dict[int, int] = {}
        for prev, cost in best.items():
            for last in s:
                if len(s) == 1:
                    c = cost + (0 if prev == last else 1)
                elif prev in s:     # start with prev: len - 1 changes, or len to end on it
                    c = cost + (len(s) - 1 if last != prev else len(s))
                else:
                    c = cost + len(s)
                nxt[last] = min(nxt.get(last, c), c)
        best = nxt
    return min(best.values())


# --- The checks -----------------------------------------------------------------------------


def _unknown(check_id: str, reason: str, threshold=None, rule=None) -> CheckResult:
    return CheckResult(check_id, "UNKNOWN", None, threshold, rule, f"not measured: {reason}")


def _all_unknown(reason: str, n: int, setup: Setup) -> list[CheckResult]:
    threshold, _ = _f3_base(setup)
    f3_rule = {cid: (None, None) if cid == F3_SLICE_CHECK_IDS[0] else (threshold,
                                                                       TOLERANCE_RULE)
               for cid in F3_SLICE_CHECK_IDS}
    out = [_unknown(COLOR_CHANGES, reason), _unknown(TOOL_PLACEMENT, reason, threshold,
                                                     TOLERANCE_RULE),
           _unknown(FILAMENTS_USED, reason)]
    out += [CheckResult(cid, "UNKNOWN", None, *f3_rule[cid],
                        f"not measured: {reason}; {f3_note(cid)}")
            for cid in F3_SLICE_CHECK_IDS]
    out += [CheckResult(per_tool_id(cid, t), "UNKNOWN", None, *f3_rule[cid],
                        f"not measured: {reason}; {f3_note(per_tool_id(cid, t))}")
            for t in range(n) for cid in F3_SLICE_CHECK_IDS]
    out += [CheckResult(cid, "UNKNOWN", None, None, None, f"not measured: {reason}; "
                        + INFO_NOTE) for cid in INFO_CHECK_IDS]
    return out


def color_slice_checks(gcode: bytes | None, shells: Sequence[Shell], setup: Setup,
                       statistics: dict | None = None,
                       not_measured: str | None = None) -> tuple[list[CheckResult], dict]:
    """The multicolor checks for one face's G-code against its bodies, and their record.

    Returns, in order: F6.color_changes, F6.tool_placement, F6.filaments_used; the three
    silhouette F3 checks (R1's ids); the per-tool F3 checks (per tool, R1's order); and
    F6.color_waste, F6.color_time, F6.color_filament (information). The required ones are
    required_check_ids(len(shells)). statistics is the
    parsed plate_1.statistics.json, for information only (None if absent).

    Everything is UNKNOWN, with the reason, when not_measured is given, when there is no
    G-code, when it is not UTF-8, when read_multicolor refuses it, or on any other error
    while reading it. The geometry checks (F6.tool_placement and F3) are UNKNOWN on their
    own when the geometry cannot be measured (the model has no section at the first layer,
    or any error).
    """
    shells = list(shells)
    fmap = filament_map(shells)            # check_shells refuses a malformed plan
    n = len(shells)
    record = {"measured": False, "reason": None, "filaments": fmap,
              "layers": [], "start_loads": [], "changes": [], "end_tools": [],
              "toolchanges": [], "silhouette": None, "tools": {}}
    reason = not_measured or (None if gcode else "no G-code was written")
    mc = None
    if reason is None:
        try:
            mc = read_multicolor(gcode.decode("utf-8"), setup.plate, setup.flow)
        except UnicodeDecodeError as err:
            reason = f"the G-code is not UTF-8 text: {err}"
        except UnsupportedGcode as err:
            reason = f"the G-code cannot be measured: {err}"
        except Exception as err:     # noqa: BLE001 - any failure is UNKNOWN, never a PASS
            reason = f"analysis error: {type(err).__name__}: {err}"
    if reason is not None:
        record["reason"] = reason
        return _all_unknown(reason, n, setup), record
    sets = layer_sets(mc.layers, shells)
    area = math.pi * setup.flow.filament_diameter_mm ** 2 / 4
    record.update(
        measured=True,
        layers=[{"n": k + 1, "z": lay.z, "height": lay.height, "bodies": s,
                 "order": o, "tower_mm3": mc.tower_e_by_layer[k] * area}
                for k, (lay, s, o) in enumerate(zip(mc.layers, sets, mc.orders,
                                                     strict=True))],
        start_loads=[t.as_dict() for t in mc.start_loads],
        changes=[t.as_dict() for t in mc.changes],
        end_tools=[t.as_dict() for t in mc.end_tools], t1000_lines=mc.t1000_lines,
        toolchanges=[c.as_dict(area) for c in mc.toolchanges])
    checks = [_color_changes(mc, sets, statistics), None, _filaments_used(mc, shells)]
    try:
        placement, f3, tool_f3, geometry = _geometry(mc, shells, sets, setup)
    except Exception as err:     # noqa: BLE001 - any failure is UNKNOWN, never a PASS
        why = (f"the G-code cannot be measured: {err}" if isinstance(err, UnsupportedGcode)
               else f"analysis error: {type(err).__name__}: {err}")
        unknown = _all_unknown(why, n, setup)
        placement = unknown[1]
        f3 = unknown[3:6]
        tool_f3 = unknown[6:6 + 3 * n]
        geometry = {"reason": why}
    checks[1] = placement
    record["silhouette"] = geometry.get("silhouette")
    record["tools"] = geometry.get("tools", {})
    record["geometry_reason"] = geometry.get("reason")
    return checks + f3 + tool_f3 + _information(mc, statistics, area), record


def _stat_summary(statistics: dict | None) -> dict:
    """The statistics' values this module reports beside its own (None where absent)."""
    summary = statistics.get("summary") if isinstance(statistics, dict) else None
    if not isinstance(summary, dict):
        return {"filament_changes": None, "time_s": None, "filaments": None}
    filaments = []
    for f in summary.get("filaments") or []:
        if not isinstance(f, dict):
            continue

        def vol(key, f=f):
            v = f.get(key)
            return v.get("volume") if isinstance(v, dict) else None
        filaments.append({"id": f.get("id"), "model_mm3": vol("model"),
                          "prime_tower_mm3": vol("prime_tower"), "flush_mm3": vol("flush")})
    return {"filament_changes": summary.get("filament_changes"),
            "time_s": summary.get("time"), "filaments": filaments}


def _color_changes(mc: Multicolor, sets: list[list[int]],
                   statistics: dict | None) -> CheckResult:
    problems = []
    orders = mc.orders
    for k, (s, o) in enumerate(zip(sets, orders, strict=True)):
        if sorted(set(o), key=lambda t: (t is None, t)) != s:
            problems.append(f"layer {k + 1}: tools {o} print model features where the bodies "
                            f"are {s} (rule a)")
        if len(o) != len(set(o)):
            problems.append(f"layer {k + 1}: a tool prints in more than one run, order {o} "
                            "(rule b)")
    loads = mc.start_loads
    loaded = loads[0].tool if len(loads) == 1 else None
    if len(loads) != 1:
        problems.append(f"the start code loads {len(loads)} filaments "
                        f"({[t.tool for t in loads]}), not exactly one")
    elif loads[0].m620 != loaded:
        problems.append(f"the start load T{loaded} is not inside M620 S{loaded}A ... "
                        f"M621 S{loaded}A")
    first = orders[0][0] if orders and orders[0] else None
    if loaded is not None and loaded != first:
        problems.append(f"the start code loads T{loaded}, but layer 1 starts with T{first}")
    for t in mc.changes:
        if t.m620 != t.tool or not t.in_toolchange:
            problems.append(f"line {t.line}: the change to T{t.tool} is not inside M620 "
                            f"S{t.tool}A ... M621 S{t.tool}A and a CP TOOLCHANGE block")
    loads_at_end = [t for t in mc.end_tools if t.tool < NO_FILAMENT]
    if loads_at_end:
        problems.append(f"the end code loads filament(s) "
                        f"{[t.tool for t in loads_at_end]}")
    formula, prev = 0, loaded
    for s, o in zip(sets, orders, strict=True):
        if not s:
            continue
        formula += len(s) - 1
        if o:
            formula += 1 if o[0] != prev else 0
            prev = o[-1]
    count = len(mc.changes)
    if count != formula:
        problems.append(f"{count} tool changes where the order needs {formula} (rule c)")
    stats = _stat_summary(statistics)
    free = [min_changes(sets, t) for t in (sets[0] if sets else [])]
    measured = {"changes": count, "rule_c_count": formula, "start_load": loaded,
                "layer_1_first_tool": first,
                "orders": [{"layer": k + 1, "bodies": s, "order": o}
                           for k, (s, o) in enumerate(zip(sets, orders, strict=True))
                           if len(s) > 1 or len(o) > 1 or o != s],
                "change_lines": [[t.line, t.layer, t.tool] for t in mc.changes],
                "end_unload": [t.tool for t in mc.end_tools],
                "info_minimum_from_start_load": min_changes(sets, loaded),
                "info_minimum_free_start": min(free) if free else None,
                "info_statistics_filament_changes": stats["filament_changes"]}
    threshold = {"rule": "(a) layer tool sets = body sets; (b) one run per tool per layer; "
                         "(c) changes = sum(bodies - 1) + boundaries where the tool differs; "
                         "one start load, the first tool of layer 1",
                 "rule_c_count": formula}
    how = ("Tool changes: each T<n> (n < 255) in the layers, after the start code. "
           "The exact minimum and the statistics' count are information. ")
    if problems:
        listed = "; ".join(problems[:LISTED]) + (f"; and {len(problems) - LISTED} more"
                                                  if len(problems) > LISTED else "")
        return CheckResult(COLOR_CHANGES, "FAIL", {**measured, "problems": problems},
                           threshold, None, how + listed)
    return CheckResult(COLOR_CHANGES, "PASS", measured, threshold, None,
                       how + f"{count} changes, as the order needs; the start code loads "
                       f"T{loaded}, the first tool of layer 1.")


def _filaments_used(mc: Multicolor, shells: list[Shell]) -> CheckResult:
    n = len(shells)
    expected = list(range(n))
    loaded = sorted({t.tool for t in (*mc.start_loads, *mc.changes)})
    printing = sorted({t for by in mc.model for t in by}, key=lambda t: (t is None, t))
    colours = mc.header.get("filament_colour")
    listed = mc.header.get("filament")
    want_colours = [s.hex.upper() for s in shells]
    measured = {"loaded_tools": loaded, "model_tools": printing, "header_filament": listed,
                "filament_colour": colours}
    threshold = {"tools": expected, "header_filament": [str(i + 1) for i in expected],
                 "filament_colour": want_colours}
    if colours is None or listed is None:
        return CheckResult(FILAMENTS_USED, "UNKNOWN", measured, threshold, None,
                           "not measured: the G-code has no '; filament:' header line or no "
                           "filament_colour in its config")
    problems = []
    if loaded != expected:
        problems.append(f"the G-code loads tools {loaded}, not {expected}")
    if printing != expected:
        problems.append(f"tools {printing} print model features, not {expected}")
    if listed != threshold["header_filament"]:
        problems.append(f"the header lists filaments {listed}, not "
                        f"{threshold['header_filament']}")
    if [c.upper() for c in colours] != want_colours:
        problems.append(f"filament_colour is {colours}, not the plan's {want_colours}")
    how = "One filament per body, tool n for the body at shell position n (filament n + 1). "
    if problems:
        return CheckResult(FILAMENTS_USED, "FAIL", measured, threshold, None,
                           how + "; ".join(problems))
    return CheckResult(FILAMENTS_USED, "PASS", measured, threshold, None,
                       how + f"Exactly the plan's {n} filaments are loaded and print, with "
                       "its colors.")


def _mesh(shell: Shell) -> trimesh.Trimesh:
    v = np.asarray(shell.vertices, dtype=np.float32).astype(np.float64)
    return trimesh.Trimesh(v, np.asarray(shell.faces, dtype=np.int64), process=False)


def _geometry(mc: Multicolor, shells: list[Shell], sets: list[list[int]],
              setup: Setup) -> tuple[CheckResult, list[CheckResult], list[CheckResult], dict]:
    """F6.tool_placement, the silhouette F3, the per-tool F3, and their record."""
    n = len(shells)
    threshold, _ = _f3_base(setup)
    first_mm, tol_mm = threshold["first_layer_mm"], threshold["other_layers_mm"]
    meshes = [_mesh(s) for s in shells]
    allv = np.concatenate([np.asarray(m.vertices) for m in meshes])
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    centre = (float(lo[0] + hi[0]) / 2, float(lo[1] + hi[1]) / 2)
    top = float(hi[2])
    zs = [lay.z for lay in mc.layers]
    sections = [[model_section(meshes[t], lay.mid_z) if t in s else shapely.Polygon()
                 for t in range(n)] for lay, s in zip(mc.layers, sets, strict=True)]
    silhouette = [shapely.union_all([g for g in row if not g.is_empty]) if any(
        not g.is_empty for g in row) else shapely.Polygon() for row in sections]
    if silhouette[0].is_empty:
        raise UnsupportedGcode("the model has no section at the first layer")
    everything = [footprint([s for segs in by.values() for s in sorted_segments(segs)])
                  for by in mc.model]
    last_h = mc.layers[-1].height
    analysis = analyse_sections(zs, silhouette, everything, last_h, centre, top, setup.plate,
                                first_mm, tol_mm, angles=(PLACEMENT_ANGLE,))
    f3, sil_record = judge_f3(analysis, setup)
    f3 = [CheckResult(c.id, c.status, c.measured, c.threshold, c.rule,
                      f"{c.note} {f3_note(c.id)}") for c in f3]
    stray = sorted({t for by in mc.model for t in by if t is None or not 0 <= t < n},
                   key=lambda t: (t is None, t))
    placement, tool_f3, tool_records = _placed(mc, sections, silhouette, sets, zs, last_h,
                                               centre, top, setup, threshold, stray)
    return placement, f3, tool_f3, {"silhouette": sil_record, "tools": tool_records}


def _placed(mc, sections, silhouette, sets, zs, last_h, centre, top, setup, threshold,
            stray):
    """F6.tool_placement and the per-tool F3 checks and records, at the fixed placement
    (PLACEMENT_ANGLE). The prime tower is not a body: its beads may not reach into the
    silhouette by more than a tool may print outside its body (_tower_depth)."""
    n = len(sections[0])
    angle = PLACEMENT_ANGLE
    first_mm, tol_mm = threshold["first_layer_mm"], threshold["other_layers_mm"]
    tool_f3, problems, near, per_tool, records = [], [], [], {}, {}
    for t in range(n):
        printed = [footprint(by.get(t, [])) for by in mc.model]
        body = [row[t] for row in sections]
        an = analyse_sections(zs, body, printed, last_h, centre, top, setup.plate, first_mm,
                              tol_mm, angles=(angle,))
        checks, rec = judge_f3(an, setup, truncation=False)
        tool_f3 += [CheckResult(per_tool_id(c.id, t), c.status, c.measured, c.threshold,
                                c.rule, f"{c.note} {f3_note(per_tool_id(c.id, t))}")
                    for c in checks]
        records[str(t)] = rec
        worst = None
        for k, m in enumerate(an.turns[0].layers):
            on, prints = t in sets[k], bool(mc.model[k].get(t))
            if prints and not on:
                problems.append(f"T{t} prints on layer {k + 1}, where its body is not")
            elif on and not prints:
                problems.append(f"the body of T{t} is on layer {k + 1}, but T{t} does not "
                                "print there")
            elif m["printed_without_model"]:
                problems.append(f"T{t} prints on layer {k + 1}, where its body has no "
                                "section")
            elif m["max_over_mm"] is not None:
                over = m["max_over_mm"]
                if over > m["allowance_mm"]:
                    problems.append(f"T{t} prints {over:.3f} mm outside its body on layer "
                                    f"{k + 1} (allowance {m['allowance_mm']:g} mm), at bed "
                                    f"{m['over_at_bed_mm']}")
                elif over + OVERPRINT_BOUND_MM > m["allowance_mm"]:
                    near.append(f"T{t} layer {k + 1}: {over:.3f} mm")
                if worst is None or over - m["allowance_mm"] > worst[0] - worst[1]:
                    worst = (over, m["allowance_mm"], k + 1)
        per_tool[str(t)] = {"layers": [k + 1 for k in range(len(zs)) if mc.model[k].get(t)],
                            "body_layers": [k + 1 for k in range(len(zs)) if t in sets[k]],
                            "max_outside_mm": None if worst is None else worst[0],
                            "at_allowance_mm": None if worst is None else worst[1],
                            "worst_layer": None if worst is None else worst[2]}
    alignment = Alignment(angle, centre, setup.plate.centre)
    tower_depth = []
    for k, by in enumerate(mc.tower):
        allowance = first_mm if k == 0 else tol_mm
        depth = _tower_depth([s for segs in by.values() for s in segs],
                             alignment.apply(silhouette[k]))
        tower_depth.append(depth)
        if depth is None:
            continue
        if depth > allowance:
            problems.append(f"the prime tower reaches {depth:.3f} mm into the model on layer "
                            f"{k + 1} (allowance {allowance:g} mm)")
        elif depth + OVERPRINT_BOUND_MM > allowance:
            near.append(f"prime tower layer {k + 1}: {depth:.3f} mm into the model")
    if stray:
        problems.insert(0, f"tools {stray} print model features but print no body of the "
                           "plan")
    measured = {"angle_deg": angle, "tools": per_tool, "sampling_bound_mm": OVERPRINT_BOUND_MM,
                "prime_tower_into_model_mm": max((d for d in tower_depth if d is not None),
                                                 default=None),
                "within_sampling_bound": near, "problems": problems}
    how = ("Each tool's model extrusion, as beads of their stated widths, against its own "
           "body's section at each layer's mid-height, the model placed as Task 2 measured "
           "(its bounding-box centre on the plate centre, not turned): "
           "the largest distance of its plastic outside the body to the body, against the "
           "tolerance (plus elefant_foot_compensation on the first layer). ")
    if problems:
        status = "FAIL"
        note = how + "; ".join(problems[:LISTED]) + (
            f"; and {len(problems) - LISTED} more" if len(problems) > LISTED else "")
    elif near:
        status, note = "UNKNOWN", how + "Within sampling uncertainty: " + "; ".join(near)
    else:
        status, note = "PASS", how + "Every tool prints only its own body, on its layers."
    placement = CheckResult(TOOL_PLACEMENT, status, measured, threshold, TOLERANCE_RULE, note)
    return placement, tool_f3, records


def _tower_depth(segments: list[Segment], silhouette_bed) -> float | None:
    """How far the prime tower's beads reach into the model's silhouette (bed mm): the
    largest distance of tower plastic inside it to its outline, sampled as
    tdmg.printed.overprint_points samples plastic outside a region (so the same sampling
    bound, OVERPRINT_BOUND_MM, holds). None when the tower prints nothing inside it."""
    if not segments or silhouette_bed.is_empty:
        return None
    tower = footprint(sorted_segments(segments))
    if not tower.intersects(silhouette_bed):
        return None
    # Any frame strictly larger than both works; 1 mm is not a measurement.
    x0, y0, x1, y1 = shapely.union_all([tower.envelope, silhouette_bed.envelope]).bounds
    outside = shapely.box(x0 - 1, y0 - 1, x1 + 1, y1 + 1).difference(silhouette_bed)
    points = overprint_points(tower, outside)
    return float(gaps(points, outside).max()) if len(points) else None


def sorted_segments(segments: list[Segment]) -> list[Segment]:
    """The segments in G-code order (by line, stably): footprint joins consecutive ones."""
    return sorted(segments, key=lambda s: s.line)


def _information(mc: Multicolor, statistics: dict | None, area: float) -> list[CheckResult]:
    stats = _stat_summary(statistics)
    tools = sorted(set(mc.model_e_mm) | set(mc.tower_e_mm) | set(mc.flush_e_mm),
                   key=lambda t: (t is None, t))

    def per_tool(values: dict) -> list[dict]:
        return [{"tool": t, "mm3": values.get(t, 0.0) * area} for t in tools]
    flush = sum(mc.flush_e_mm.values()) * area
    tower = sum(mc.tower_e_mm.values()) * area
    waste = CheckResult(COLOR_WASTE, "UNKNOWN", {
        "flush_mm3": flush, "prime_tower_mm3": tower,
        "flush_by_tool": per_tool(mc.flush_e_mm), "prime_tower_by_tool": per_tool(mc.tower_e_mm),
        "flush_length_L_mm": [c.flush_length_l_mm for c in mc.toolchanges],
        "other_e_only_in_changes_mm3": sum(c.other_e_mm for c in mc.toolchanges) * area,
        "statistics": [{k: f[k] for k in ("id", "prime_tower_mm3", "flush_mm3")}
                       for f in stats["filaments"] or []]}, None, None,
        "Flush: E-only moves in the FLUSH blocks, on the tool loaded during them; prime "
        "tower: its extrusion; mm3 with the pinned profile's filament diameter. " + INFO_NOTE)
    time = CheckResult(COLOR_TIME, "UNKNOWN", {
        "model_printing_time_s": mc.header.get("model_printing_time_s"),
        "total_estimated_time_s": mc.header.get("total_estimated_time_s"),
        "statistics_time_s": stats["time_s"]}, None, None,
        "The G-code header's times (the slicer's estimates). " + INFO_NOTE)
    filament = CheckResult(COLOR_FILAMENT, "UNKNOWN", {
        "model_by_tool": per_tool(mc.model_e_mm),
        "header_filament_used_mm": mc.header.get("filament_used_mm"),
        "header_filament_used_g": mc.header.get("filament_used_g"),
        "statistics": [{k: f[k] for k in ("id", "model_mm3")}
                       for f in stats["filaments"] or []]}, None, None,
        "Model filament per tool from the G-code's model extrusion (the statistics' model "
        "volume also counts the start code's purge for the start-loaded filament: Task 2). "
        + INFO_NOTE)
    return [waste, time, filament]

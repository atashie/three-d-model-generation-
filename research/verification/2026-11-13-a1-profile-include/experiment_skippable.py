"""Scratch: F3 on the real G-code if the template's SKIPPABLE blocks were read as Custom."""
import json
from pathlib import Path

from tdmg.printed import Setup, f3_checks, plate_from_profile
from tdmg.rules import load_rules
from tdmg.slicing import allowed_layer_counts, elephant_foot_mm, flow_from_profile

prof = Path("artifacts/tools/orcaslicer-2.5.0/profiles-flat")
machine, process, fil = (json.loads((prof / f).read_text(encoding="utf-8")) for f in ("machine.json","process.json","filament.json"))
rules = load_rules()
for sel in ("roadie-tol30", "oddie"):
    stl = Path(f"artifacts/flat-runs/{sel}-60x3-s5/model.stl").read_bytes()
    setup = Setup(plate_from_profile(machine), flow_from_profile(fil),
                  float(rules["acceptance.dimension.tolerance"].default), elephant_foot_mm(process),
                  frozenset(allowed_layer_counts(stl, process)))
    text = Path(f"artifacts/slice-runs/{sel}-60x3-slice5b/plate_1.gcode").read_text(encoding="utf-8")
    out, feat, inblock = [], None, False
    for line in text.splitlines():
        t = line.strip()
        if t.startswith("; FEATURE:"): feat = t
        out.append(line)
        if t == "; SKIPPABLE_START": out.append("; FEATURE: Custom")
        if t == "; SKIPPABLE_END" and feat: out.append(feat)
    for name, g in (("as written", text), ("SKIPPABLE as Custom", "\n".join(out) + "\n")):
        checks, rec = f3_checks(g.encode(), stl, setup)
        print(sel, name, [(c.id, c.status, {k: c.measured.get(k) for k in ("layers_mismatched","max_gap_mm","layers_over")} if isinstance(c.measured, dict) else None) for c in checks], rec.get("reason"))

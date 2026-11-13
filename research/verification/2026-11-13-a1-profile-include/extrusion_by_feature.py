"""Positive E by feature (Custom against the rest) and the header filament lines.

    uv run python -I research/verification/2026-11-13-a1-profile-include/extrusion_by_feature.py GCODE...
"""
import collections
import math
import re
import sys

A = math.pi * (1.75 / 2) ** 2
for f in sys.argv[1:]:
    feat = "none"; pos = collections.Counter(); neg = collections.Counter(); rel = None; tot_rel = 0.0
    for raw in open(f, encoding="utf-8"):
        l = raw.strip()
        if l.startswith("; FEATURE:"): feat = l.split(":", 1)[1].strip()
        c = l.split(";", 1)[0].strip()
        if not c: continue
        cmd = c.split()[0]
        if cmd == "M83": rel = True
        if cmd == "M82": rel = False
        if cmd in ("G0", "G1", "G2", "G3"):
            m = re.search(r"(?:^|\s)E(-?[0-9.]+)", c)
            if m:
                e = float(m.group(1))
                (pos if e > 0 else neg)[feat] += e
    custom = pos["Custom"]
    model = sum(v for k, v in pos.items() if k != "Custom")
    net = sum(pos.values()) + sum(neg.values())
    print(f, f"positive E: Custom {custom:.3f} mm ({custom*A:.2f} mm3), other {model:.3f} mm ({model*A:.2f} mm3); net E {net:.3f} mm ({net*A:.2f} mm3)")
    hdr = [l.strip() for l in open(f, encoding="utf-8") if "filament used" in l or "total filament" in l][:6]
    print("  ", hdr)

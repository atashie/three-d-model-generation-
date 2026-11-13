"""Count G-commands outside G_COMMANDS by feature, and Custom extrusions after the model.

    uv run python -I research/verification/2026-11-13-a1-profile-include/scan_gcommands.py GCODE...
"""
import collections
import re
import sys

G={"G0","G1","G2","G3","G17","G21","G28","G29","G90","G91","G92"}
for f in sys.argv[1:]:
    feat=None; first_model=None; unk=collections.Counter(); custom_e_after=[]; feats_lines=collections.Counter()
    for n,raw in enumerate(open(f,encoding="utf-8"),1):
        l=raw.strip()
        if l.startswith(";"):
            t=l[1:].strip()
            if t.startswith("FEATURE:"): feat=t.split(":",1)[1].strip()
            continue
        c=l.split(";",1)[0].strip()
        if not c: continue
        cmd=c.split()[0]
        if cmd.startswith("G") and cmd not in G: unk[(cmd,feat)]+=1
        if cmd in ("G0","G1","G2","G3"):
            m=re.search(r"\bE(-?[0-9.]+)",c); e=float(m.group(1)) if m else 0
            if e>0 and re.search(r"\b[XYIJ]",c):
                if feat!="Custom" and first_model is None: first_model=n
                if feat=="Custom" and first_model: custom_e_after.append((n,c))
    print(f); print(" unknown G by feature:",dict(unk)); print(" first model extrusion line",first_model)
    print(" Custom XY extrusions after model:",custom_e_after[:20], len(custom_e_after))

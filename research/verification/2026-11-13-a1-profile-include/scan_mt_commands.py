"""Every M- and T-command (outside comments) in G-code files, with counts, and their union.

    uv run python -I research/verification/2026-11-13-a1-profile-include/scan_mt_commands.py \
        GCODE...
"""
import collections
import re
import sys

COMMAND = re.compile(r"^(M(?:0|[1-9][0-9]*)(?:\.[0-9]+)?|T(?:0|[1-9][0-9]*))(?:\s|$)")
union = set()
for path in sys.argv[1:]:
    counts = collections.Counter()
    with open(path, encoding="utf-8") as f:
        for raw in f:
            code = raw.split(";", 1)[0].strip()
            found = COMMAND.match(code)
            if found:
                counts[found.group(1)] += 1


    def key(c):
        return (c[0], [int(p) for p in c[1:].split(".")])
    print(path)
    for c in sorted(counts, key=key):
        print(f"  {c} {counts[c]}")
    union |= set(counts)
print("all:", ", ".join(sorted(union, key=lambda c: (c[0], [int(p) for p in c[1:].split(".")]))))

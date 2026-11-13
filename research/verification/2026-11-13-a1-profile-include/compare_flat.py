"""Compare the old flat machine.json with the new one, key by key.

    uv run python research/verification/2026-11-13-a1-profile-include/compare_flat.py         OLD NEW TEMPLATES

OLD and NEW are machine.json files; TEMPLATES is a folder with the five upstream template
files (machine/Bambu Lab A1 0.4 nozzle template <key>.json). Also checks the condition
under which OrcaSlicer's include (a diff against the collection default) equals a plain
merge: every included value differs from the option's default in PrintConfig.cpp v2.5.0.
"""
import json
import pathlib
import sys

# Defaults of the five options, PrintConfig.cpp at tag v2.5.0 (README.md gives the lines).
DEFAULTS = {
    "machine_start_gcode": "G28 ; home all axes\nG1 Z5 F5000 ; lift nozzle\n",
    "machine_end_gcode": "M104 S0 ; turn off temperature\nG28 X0  ; home X axis\nM84     ; disable motors\n",
    "time_lapse_gcode": "",
    "change_filament_gcode": "",
    "layer_change_gcode": "",
}
old = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
new = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
tdir = pathlib.Path(sys.argv[3])
print(f"keys: old {len(old)}, new {len(new)}")
print(f"only in old: {sorted(set(old) - set(new))}")
print(f"only in new: {sorted(set(new) - set(old))}")
changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
print(f"changed: {changed}")
for key, default in DEFAULTS.items():
    name = f"Bambu Lab A1 0.4 nozzle template {key}.json"
    t = json.loads((tdir / name).read_text(encoding="utf-8"))
    tv = t[key]
    print(f"{key}: template {len(tv)} chars; old flat {len(old[key])}; new flat {len(new[key])}; "
          f"new == template: {new[key] == tv}; template == old: {tv == old[key]}; "
          f"template == default: {tv == default}; template keys: {sorted(t)}")
start = new["machine_start_gcode"].splitlines()
print("new machine_start_gcode, first 5 lines:")
for line in start[:5]:
    print("  " + line)
print(f"M620 lines in new start: {sum('M620' in s for s in start)}")

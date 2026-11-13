"""Flatten the A1 presets with `include` resolved, written apart from scripts/setup_orcaslicer.py.

    uv run python research/verification/2026-11-13-a1-profile-include/flatten_with_include.py OUT

Resolution, as read from OrcaSlicer v2.5.0 PresetBundle::resolve_vendor_preset (README.md):
the parent's resolved config, then each included preset's settings in the order listed,
then the preset's own keys. A template's type, name and instantiation are attributes, not
settings (ConfigBase::load_from_json). The merged dict then loses the pin's drop_keys plus
`include`, and gets the leaf's name and "from": "User", as in the 2026-11-10 record.
Files are written as json.dumps(indent=1, sort_keys=True) with CRLF line ends, the bytes
the pin expects. Prints the chains, includes, hashes and the G-code key lengths.
"""
import hashlib
import json
import pathlib
import sys
import urllib.parse
import urllib.request

TAG = "v2.5.0"
BASE = f"https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/{TAG}/resources/profiles/"
DROP = {"inherits", "include", "from", "instantiation", "setting_id", "description"}
ATTRS = {"type", "name", "instantiation"}


def get(path):
    req = urllib.request.Request(BASE + urllib.parse.quote(path),
                                 headers={"User-Agent": "tdmg-research"})
    return urllib.request.urlopen(req).read()


def dump(obj):
    return json.dumps(obj, indent=1, sort_keys=True).replace("\n", "\r\n").encode("ascii")


index = json.loads(get("BBL.json"))
lists = {k: {e["name"]: e["sub_path"] for e in index.get(k, [])}
         for k in ("machine_list", "process_list", "filament_list", "machine_model_list")}
everything = {n: s for d in lists.values() for n, s in d.items()}
manifest = {}


def load(sub):
    raw = get("BBL/" + sub)
    manifest[sub] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw)


def resolve(name, kind):
    """(resolved dict, chain names, include names) for one preset, recursively."""
    cfg = load(everything[name])
    parent = cfg.get("inherits")
    resolved, chain, incs = resolve(parent, kind) if parent else ({}, [], [])
    names = cfg.get("include", [])
    names = [names] if isinstance(names, str) else names
    for inc in names:
        t = load(lists[kind + "_list"][inc])
        assert not ({"inherits", "include"} & set(t)), inc
        resolved.update({k: v for k, v in t.items() if k not in ATTRS})
    resolved.update(cfg)
    return resolved, chain + [cfg["name"]], incs + names


out = pathlib.Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for leaf, kind, fname in (("Bambu Lab A1 0.4 nozzle", "machine", "machine.json"),
                          ("0.20mm Standard @BBL A1", "process", "process.json"),
                          ("Bambu PLA Basic @BBL A1", "filament", "filament.json")):
    merged, chain, incs = resolve(leaf, kind)
    for k in DROP:
        merged.pop(k, None)
    merged["name"] = leaf
    merged["from"] = "User"
    data = dump(merged)
    (out / fname).write_bytes(data)
    print(f"{leaf} chain: {' <- '.join(chain)} keys {len(merged)}")
    print(f"  includes: {incs}")
    print(f"  {hashlib.sha256(data).hexdigest()} *{fname}")
    for k in sorted(k for k in merged if k.endswith("_gcode")):
        v = merged[k]
        print(f"  {k}: {len(v)} chars, M620 {'yes' if 'M620' in v else 'no'}")
m = dump({"tag": TAG, "files_sha256": manifest})
(out / "source-manifest.json").write_bytes(m)
print(f"{hashlib.sha256(m).hexdigest()} *source-manifest.json")
for sub in sorted(manifest):
    print(f"{manifest[sub]} *{sub}")

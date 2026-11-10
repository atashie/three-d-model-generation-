import json, sys, urllib.parse, urllib.request, pathlib, hashlib
TAG = "v2.5.0"; BASE = f"https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/{TAG}/resources/profiles/"
def get(path):
    req = urllib.request.Request(BASE + urllib.parse.quote(path), headers={"User-Agent": "tdmg-research"})
    return urllib.request.urlopen(req).read()
index = json.loads(get("BBL.json"))
names = {}
for kind in ("machine_list", "process_list", "filament_list", "machine_model_list"):
    for e in index.get(kind, []): names[e["name"]] = e["sub_path"]
out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
manifest = {}
def chain(name):
    raw = get("BBL/" + names[name]); manifest[names[name]] = hashlib.sha256(raw).hexdigest()
    cfg = json.loads(raw); parent = cfg.get("inherits")
    return (chain(parent) if parent else []) + [cfg]
DROP = {"inherits", "from", "instantiation", "setting_id", "description"}
for leaf, fname in (("Bambu Lab A1 0.4 nozzle", "machine.json"), ("0.20mm Standard @BBL A1", "process.json"),
                    ("Bambu PLA Basic @BBL A1", "filament.json")):
    c = chain(leaf); merged = {}
    for cfg in c: merged.update(cfg)
    for k in DROP: merged.pop(k, None)
    merged["name"] = leaf; merged["from"] = "User"
    print(leaf, "chain:", " <- ".join(x["name"] for x in c), "keys", len(merged))
    (out / fname).write_text(json.dumps(merged, indent=1, sort_keys=True))
(out / "source-manifest.json").write_text(json.dumps({"tag": TAG, "files_sha256": manifest}, indent=1, sort_keys=True))

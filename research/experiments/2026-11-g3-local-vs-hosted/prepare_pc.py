"""Record fixed inputs and fetch the owner-approved official checkpoint only."""
import hashlib
import json
from pathlib import Path
import subprocess
import requests

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "artifacts/triposr-data"
OUT.mkdir(parents=True, exist_ok=True)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


inputs = []
for path in [ROOT / "artifacts/TripoSR/examples" / name
             for name in ("chair.png", "hamburger.png", "teapot.png")] + [
                 Path.home() / "Downloads/three-d-test" / name
                 for name in ("oddie.png", "roadie.png")]:
    inputs.append(dict(path=str(path), sha256=sha(path), bytes=path.stat().st_size))
manifest = OUT / "preparation.json"
prior = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else None
endpoint = "https://huggingface.co/api/models/stabilityai/TripoSR"
if prior:
    endpoint += "/revision/" + prior["revision"]
response = requests.get(endpoint, params={"blobs": "true"}, timeout=60)
response.raise_for_status()
revision = response.json()["sha"]
metadata = {item["rfilename"]: item for item in response.json()["siblings"]}
dirty = subprocess.check_output(
    ["git", "-C", str(ROOT / "artifacts/TripoSR"), "status", "--porcelain"], text=True)
if dirty:
    raise RuntimeError("Record/review TripoSR modifications before preparing inputs: " + dirty)
record = dict(inputs=inputs, model="stabilityai/TripoSR", revision=revision,
              code_commit=subprocess.check_output(
                  ["git", "-C", str(ROOT / "artifacts/TripoSR"), "rev-parse", "HEAD"],
                  text=True).strip(), seed=0, timeout_seconds=1800, files=[])
for name in ("config.yaml", "model.ckpt"):
    dest = OUT / name
    if not dest.exists():
        with requests.get(f"https://huggingface.co/stabilityai/TripoSR/resolve/{revision}/{name}",
                          stream=True, timeout=120) as response:
            response.raise_for_status()
            partial = dest.with_suffix(dest.suffix + ".partial")
            with partial.open("wb") as stream:
                for chunk in response.iter_content(1024 * 1024):
                    stream.write(chunk)
            partial.replace(dest)
    digest = sha(dest)
    expected = metadata[name]
    if "lfs" in expected:
        matches = digest == expected["lfs"]["sha256"]
    else:
        content = dest.read_bytes()
        blob_hash = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        matches = blob_hash == expected["blobId"]
    if not matches:
        raise RuntimeError(f"{name} does not match upstream revision {revision}")
    record["files"].append(dict(name=name, sha256=digest, bytes=dest.stat().st_size))
    print(record["files"][-1], flush=True)
manifest.write_text(json.dumps(record, indent=2), encoding="utf-8")
print("Prepared input hashes and checkpoint; no inference performed.")

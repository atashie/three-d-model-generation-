"""Isolated CPU experiment, with a fresh process and 1800-second cap per input."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "artifacts/triposr-data"
OUT = ROOT / "artifacts/triposr-runs"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def worker(index, dest):
    start = time.perf_counter()
    import numpy as np
    import torch
    import trimesh
    from PIL import Image
    from omegaconf import OmegaConf
    sys.path.insert(0, str(ROOT / "artifacts/TripoSR"))
    from tsr.system import TSR
    from tsr.utils import remove_background, resize_foreground

    # Fixed experiment settings: seed from preparation; remaining values are
    # upstream run.py defaults. Threads fixed to the PC's 16 physical cores.
    torch.set_num_threads(16)
    torch.manual_seed(0)
    np.random.seed(0)
    torch.use_deterministic_algorithms(True)
    manifest = json.loads((DATA / "preparation.json").read_text())
    item = manifest["inputs"][index]
    for record in manifest["files"]:
        assert sha(DATA / record["name"]) == record["sha256"]
    auxiliary = json.loads((DATA / "auxiliary-hashes.json").read_text())
    for record in auxiliary:
        assert sha(Path(record["path"])) == record["sha256"]
    code_dir = str(ROOT / "artifacts/TripoSR")
    assert subprocess.check_output(["git", "-C", code_dir, "rev-parse", "HEAD"],
                                   text=True).strip() == manifest["code_commit"]
    assert not subprocess.check_output(["git", "-C", code_dir, "status", "--porcelain"])
    import importlib.metadata
    provenance = dict(preparation=manifest, auxiliary=auxiliary, runner_sha256=sha(Path(__file__)),
                      packages={d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
                      threads=16, resolution=256, chunk_size=8192, foreground_ratio=0.85)
    (dest / "provenance.json").write_text(json.dumps(provenance, indent=2))
    source = Path(item["path"])
    assert sha(source) == item["sha256"]
    cfg = OmegaConf.load(DATA / "config.yaml")
    OmegaConf.resolve(cfg)
    print("Loading model", flush=True)
    model = TSR(cfg)
    model.load_state_dict(torch.load(DATA / "model.ckpt", map_location="cpu", weights_only=True))
    model.eval().to("cpu")
    model.renderer.set_chunk_size(8192)
    print("Preparing input", flush=True)
    image = remove_background(Image.open(source))
    image = resize_foreground(image, 0.85)
    image = np.array(image).astype(np.float32) / 255.0
    image = Image.fromarray(((image[:, :, :3] * image[:, :, 3:4] +
                             (1 - image[:, :, 3:4]) * 0.5) * 255).astype(np.uint8))
    image.save(dest / "input.png")
    print("Generating triplane", flush=True)
    with torch.no_grad():
        codes = model([image], device="cpu")
        print("Extracting mesh at resolution 256", flush=True)
        mesh = model.extract_mesh(codes, has_vertex_color=True, resolution=256)[0]
    target = dest / "mesh.obj"
    pre_export = dict(watertight=bool(mesh.is_watertight), winding_consistent=bool(mesh.is_winding_consistent))
    mesh.export(target)
    wall = time.perf_counter() - start
    print(f"Mesh written in {wall:.2f} seconds", flush=True)
    # Validate the serialized raw mesh without repair or vertex merging.
    mesh = trimesh.load(target, force="mesh", process=False)
    counts = np.bincount(mesh.edges_unique_inverse)
    # A closed manifold vertex has one connected cyclic link graph.
    links = [[] for _ in mesh.vertices]
    for a, b, c in mesh.faces:
        links[a].append((int(b), int(c)))
        links[b].append((int(c), int(a)))
        links[c].append((int(a), int(b)))
    bad = 0
    for edges in links:
        graph = {}
        for a, b in edges:
            graph.setdefault(a, []).append(b)
            graph.setdefault(b, []).append(a)
        if not graph or any(len(n) != 2 for n in graph.values()):
            bad += 1
            continue
        seen, stack = set(), [next(iter(graph))]
        while stack:
            node = stack.pop()
            if node not in seen:
                seen.add(node)
                stack.extend(graph[node])
        bad += len(seen) != len(graph)
    bodies = mesh.split(only_watertight=False, repair=False)
    duplicate_faces = len(mesh.faces) - len(np.unique(np.sort(mesh.faces, axis=1), axis=0))
    zero_area_faces = int(np.count_nonzero(mesh.area_faces == 0))
    result = dict(input=source.name, wall_to_mesh_seconds=wall,
                  pre_export=pre_export,
                  triangles=len(mesh.faces), vertices=len(mesh.vertices),
                  output_bytes=target.stat().st_size, output_sha256=sha(target),
                  watertight=bool(mesh.is_watertight), edge_manifold=bool(np.all(counts == 2)),
                  vertex_manifold=bad == 0, bad_vertices=int(bad),
                  duplicate_faces=int(duplicate_faces), zero_area_faces=zero_area_faces,
                  winding_consistent=bool(mesh.is_winding_consistent),
                  bodies=len(bodies), volume=float(mesh.volume),
                  body_volumes=[float(b.volume) for b in bodies],
                  finite=bool(np.isfinite(mesh.vertices).all()),
                  units="model coordinates; not millimeters", repaired=False)
    import psutil
    own_memory = psutil.Process().memory_info()
    result["worker_peak_working_set_bytes"] = own_memory.peak_wset
    result["worker_peak_commit_bytes"] = own_memory.peak_pagefile
    (dest / "mesh-metrics.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


def supervise(index, label):
    import psutil
    dest = OUT / label
    dest.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
               U2NET_HOME=str(DATA / "rembg"), OMP_NUM_THREADS="16")
    start = time.perf_counter()
    peak_rss = peak_private = 0
    swaps = [psutil.swap_memory().used]
    timed_out = False
    with (dest / "run.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "-u", __file__, "--worker", str(index),
                                    "--label", label], stdout=log, stderr=subprocess.STDOUT, env=env)
        watched = psutil.Process(process.pid)
        while process.poll() is None:
            try:
                memories = [p.memory_info() for p in [watched, *watched.children(recursive=True)]]
                peak_rss = max(peak_rss, sum(m.rss for m in memories))
                peak_private = max(peak_private, sum(m.private for m in memories))
                swaps.append(psutil.swap_memory().used)
            except psutil.NoSuchProcess:
                pass
            if time.perf_counter() - start > 1800:
                try:
                    for child in watched.children(recursive=True):
                        try:
                            child.kill()
                        except psutil.NoSuchProcess:
                            pass
                    process.kill()
                except psutil.NoSuchProcess:
                    pass
                timed_out = True
                break
            time.sleep(min(0.5, max(0, 1800 - (time.perf_counter() - start))))
        process.wait(timeout=10)
    result = dict(exit_code=process.returncode, timed_out=timed_out,
                  total_process_seconds=time.perf_counter()-start,
                  peak_working_set_bytes=peak_rss, peak_commit_bytes=peak_private,
                  system_swap_start_bytes=swaps[0], system_swap_peak_bytes=max(swaps),
                  memory_method="Process-tree working set/private bytes sampled every 0.5s; worker lifetime peaks in mesh metrics; system swap is global")
    (dest / "resources.json").write_text(json.dumps(result, indent=2))
    print(label, json.dumps(result), flush=True)
    return process.returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=int)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    if args.worker is not None:
        worker(args.worker, OUT / args.label)
    else:
        sys.exit(supervise(args.index, args.label))

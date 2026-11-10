"""Hash every file of an extracted OrcaSlicer app folder (README section "Addendum, 2026-11-10").

Usage: uv run python research/verification/2026-11-10-orcaslicer-windows/app_tree_hash.py APP_DIR...

The tree hash is the SHA-256 of the UTF-8 text made of one line per file,
"<relative path with />\t<sha256 of the file>\n", the lines sorted as Python strings.
This is the definition tdmg.slicer.app_tree_sha256 implements.
"""
import hashlib
import pathlib
import sys
import time

for arg in sys.argv[1:]:
    root = pathlib.Path(arg)
    t = time.perf_counter()
    lines = sorted(f"{p.relative_to(root).as_posix()}\t{hashlib.sha256(p.read_bytes()).hexdigest()}"
                   for p in root.rglob("*") if p.is_file())
    tree = hashlib.sha256("".join(line + "\n" for line in lines).encode("utf-8")).hexdigest()
    print(f"{arg}: files {len(lines)}, tree sha256 {tree}, {time.perf_counter() - t:.1f} s")
    for line in lines:
        if line.split("\t")[0] in ("orca-slicer.exe", "OrcaSlicer.dll"):
            print("  " + line.replace("\t", "  "))

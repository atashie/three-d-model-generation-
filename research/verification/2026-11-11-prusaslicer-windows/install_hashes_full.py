"""Hash the PrusaSlicer install's console exe, PrusaSlicer.dll and full app tree.

Usage: uv run python research/verification/2026-11-11-prusaslicer-windows/install_hashes_full.py APP_DIR
APP_DIR is the extracted zip root (the folder containing PrusaSlicer-2.9.7/).
Uses tdmg.slicer.app_tree_sha256 (sorted relpath<TAB>sha256 lines).
"""
import hashlib
import pathlib
import sys

from tdmg.slicer import app_tree_sha256

app = pathlib.Path(sys.argv[1])
for rel in ("PrusaSlicer-2.9.7/prusa-slicer-console.exe", "PrusaSlicer-2.9.7/PrusaSlicer.dll"):
    print(rel, hashlib.sha256((app / rel).read_bytes()).hexdigest())
files = [p for p in app.rglob("*") if p.is_file()]
print("app tree files", len(files), "sha256", app_tree_sha256(app))

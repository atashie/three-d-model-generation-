"""The four previews the owner approved (artifacts/colors-review-3, made with the float32
blur), remade with the float64 blur: labels.png must be identical; how many regions.png
pixels change? Reads and writes git-ignored folders under artifacts/."""
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(sys.argv[1])
RUNS = ROOT / "artifacts" / "colors-runs"
CFG = RUNS / "configs"
CASES = [  # approved preview, approved run, selection, config (None: defaults)
    ("1-roadie-outline-dropped", "roadie-tol30-60-drop-v3", "roadie-tol30", None),
    ("2-roadie-outline-kept", "roadie-tol30-60-keep-v4", "roadie-tol30", "keep.yaml"),
    ("3-oddie-kept-blues-and-greens-merged", "oddie-60-keep-merge-blues-greens-v4", "oddie",
     "keep-merge-blues-greens.yaml"),
    ("4-oddie-dropped-blues-merged", "oddie-60-merge-blues-v3", "oddie", "merge-blues.yaml"),
]
for name, run, sel, cfg in CASES:
    out = RUNS / f"{run}-f64"
    if out.exists():
        shutil.rmtree(out)
    cmd = ["uv", "run", "tdmg", "colors", str(ROOT / "artifacts" / "selection-runs" / sel),
           "--width-mm", "60", "--out", str(out)]
    if cfg:
        cmd += ["--config", str(CFG / cfg)]
    code = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT).returncode
    same_labels = (RUNS / run / "labels.png").read_bytes() == (out / "labels.png").read_bytes()
    a = np.asarray(Image.open(ROOT / "artifacts" / "colors-review-3" / f"{name}.png"))
    b = np.asarray(Image.open(out / "regions.png"))
    diff = int((a != b).any(axis=-1).sum()) if a.shape == b.shape else None
    print(f"{name}: exit {code}; labels.png identical {same_labels}; preview "
          f"{a.shape[1]}x{a.shape[0]}, pixels changed {diff} of {a.shape[0] * a.shape[1]}")

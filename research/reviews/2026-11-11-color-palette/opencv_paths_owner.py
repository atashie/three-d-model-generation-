"""Sigma 2.5 px (flat.smooth.sigma_px). On the owner's colors runs: does the optimisation switch change smooth_labels (float32) or
smooth_outline, and how many fine pixels would float64 fields change?"""
import sys
from pathlib import Path

import cv2
import numpy as np

import tdmg.smoothing as sm
from tdmg.selection import read_selection

ROOT = Path(sys.argv[1])
SEL = ROOT / "artifacts" / "selection-runs"
for d in sorted(p for p in SEL.iterdir() if (p / "selection.json").is_file()):
    v = read_selection(d)
    mask = v.mask
    geoms = []
    for opt in (True, False):
        cv2.setUseOptimized(opt)
        geoms.append(sm.smooth_outline(mask, 2.5).wkb)
    cv2.setUseOptimized(True)
    print(d.name, "smooth_outline wkb equal across switch:", geoms[0] == geoms[1])

# the colors runs' labels
for lp in sorted((ROOT / "artifacts").glob("colors-*/**/labels.png")):
    from PIL import Image
    l8 = np.asarray(Image.open(lp))
    lab = np.where(l8 == 255, -1, l8.astype(np.int32))
    outs = {}
    for opt in (True, False):
        cv2.setUseOptimized(opt)
        outs[opt] = sm.smooth_labels(lab, 2.5, 4).fine
    cv2.setUseOptimized(True)
    print(lp.relative_to(ROOT), "f32 switch diff px:", int((outs[True] != outs[False]).sum()))
    break

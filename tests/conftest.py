"""Shared fixtures: the owner's selections measured in the color-palette Task 1 record
(research/verification/2026-11-11-color-palette/results.txt). The images are git-ignored;
tests that need them skip when they are absent and fail when they differ from the record.
"""

import hashlib
import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research" / "verification" / "2026-11-11-color-palette"
SELECTIONS = ROOT / "artifacts" / "selection-runs"


@pytest.fixture(scope="session")
def research_rows():
    """Parse the kmeans_w rows and palettes from the Task 1 results.txt."""
    text = (RESEARCH / "results.txt").read_text(encoding="utf-8")
    out = {}
    for block in text.split("\n== ")[1:]:
        name = block.split(":", 1)[0]
        m = re.search(r"mask sha256 (\w+), cutout sha256 (\w+)", block)
        rows = {}
        for line in block.splitlines():
            f = line.split()
            if len(f) > 10 and f[0] == "kmeans_w" and f[1].isdigit():
                # columns: method N dE_mean dE_p95 pieces small small_px% times iters
                # identical label_sha256[:16] colors nearest_mean nearest_p95 not_nearest%
                rows[int(f[1])] = {"iters": int(f[8]), "sha": f[10], "not_nearest": f[14]}
            if len(f) > 2 and f[0] == "kmeans_w" and f[1].endswith(":"):
                n = int(f[1][:-1])
                rows[n]["palette"] = re.findall(r"(#[0-9a-f]{6}) ([\d.]+%)", line)
        out[name] = {"mask": m.group(1), "cutout": m.group(2), "rows": rows}
    return out


@pytest.fixture(scope="session")
def owner_selection(research_rows):
    """A function name -> (rgb (H, W, 3) uint8, mask (H, W) bool) for an owner selection.

    It skips when the selection is absent, and fails when its files differ from the
    hashes measured in Task 1 (the fixture would test other images)."""
    def load(name):
        d = SELECTIONS / name
        if not (d / "mask.png").is_file() or not (d / "cutout.png").is_file():
            pytest.skip(f"owner selection {d} is not present (git-ignored owner images)")
        rec = research_rows[name]
        for f, want in (("mask.png", rec["mask"]), ("cutout.png", rec["cutout"])):
            got = hashlib.sha256((d / f).read_bytes()).hexdigest()[:16]
            assert got == want, (f"{d / f} is present but has sha256[:16] {got}, not the "
                                 f"{want} measured in Task 1: the fixture would test other "
                                 "images")
        mask = np.array(Image.open(d / "mask.png")) == 255
        rgb = np.array(Image.open(d / "cutout.png").convert("RGBA"))[..., :3]
        return rgb, mask
    return load

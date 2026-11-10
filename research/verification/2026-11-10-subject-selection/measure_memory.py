"""Time and traced memory of tdmg select stages on a synthetic 4000 x 4000 RGBA image.

Usage: uv run python research/verification/2026-11-10-subject-selection/measure_memory.py OUTDIR
OUTDIR must not exist; write_selection creates it.

tracemalloc counts allocations made through Python's allocator, which includes numpy
arrays. It does not count OpenCV's or zlib's internal buffers, so true process peaks are
higher. Each stage is measured once; times are wall-clock on this machine.
"""

import sys
import time
import tracemalloc

import cv2
import numpy as np

from tdmg.selection import Intake, SelectionSpec, pixels_sha256, select_subject, write_selection

N = 4000
img = np.zeros((N, N, 4), np.uint8)
cv2.circle(img, (N // 2, N // 2), int(N * 0.45), (57, 46, 40, 255), -1)        # disc
cv2.ellipse(img, (N // 2, N // 2), (N // 5, N // 8), 0, 0, 360, (230, 20, 20, 255), -1)
intake = Intake(img, "0" * 64, pixels_sha256(img), False, "synthetic.png")
spec = SelectionSpec(remove_at=((N // 2 - int(N * 0.4), N // 2),), keep_at=((N // 2, N // 2),))


def measure(label, fn):
    tracemalloc.start()
    t0 = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t0
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    print(f"{label}: {dt:.2f} s, traced peak {peak / 2**20:.0f} MiB")
    return out


sel = measure("select_subject", lambda: select_subject(intake, spec))
print("status", sel.result["status"], "selected_px", sel.result["selected_px"])
measure("write_selection", lambda: write_selection(intake, sel, sys.argv[1]))

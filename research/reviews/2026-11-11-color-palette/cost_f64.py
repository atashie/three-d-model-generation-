"""smooth_labels' cost after the float64 change (flat-3), for its docstring: a 2000 x 2000
map with 4 colors inside a disc of radius 990 px (quarters of the disc), OUTSIDE around it,
sigma 2.5, s 4 (an 8000 x 8000 fine map). Best of 3 wall times; the tracemalloc peak of
one call (numpy and Python allocations, not OpenCV's own buffers)."""
import time
import tracemalloc

import numpy as np

from tdmg.color import OUTSIDE
from tdmg.smoothing import smooth_labels

n = 2000
r, c = np.indices((n, n))
labels = (2 * (r >= n // 2) + (c >= n // 2)).astype(np.int32)
labels[(r - n / 2 + 0.5) ** 2 + (c - n / 2 + 0.5) ** 2 > 990 ** 2] = OUTSIDE

times = []
for _ in range(3):
    t = time.perf_counter()
    smooth_labels(labels, 2.5, 4)
    times.append(time.perf_counter() - t)
tracemalloc.start()
smooth_labels(labels, 2.5, 4)
peak = tracemalloc.get_traced_memory()[1]
tracemalloc.stop()
print(f"best of 3: {min(times):.2f} s; tracemalloc peak {peak / 2 ** 20:.0f} MiB")

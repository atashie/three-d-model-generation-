import sys, numpy as np, cv2
from PIL import Image
a = np.asarray(Image.open(sys.argv[1]).convert("RGBA")); al = a[..., 3]
for t in (1, 64, 128, 192, 255):
    fg = (al >= t).astype(np.uint8); n, l, st, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    ar = sorted(st[1:, 4].tolist(), reverse=True); print("alpha>=", t, "px", int(fg.sum()), "components", n - 1, "largest", ar[:4])

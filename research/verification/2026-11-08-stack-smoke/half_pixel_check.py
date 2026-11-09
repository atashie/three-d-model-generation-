"""Does cv2.findContours bias shapes inward by ~0.5 px? Compare raw vs +/-0.5 px offset, and vtracer."""
import math, sys, hashlib, subprocess
import numpy as np, cv2
from shapely.geometry import Polygon
for scale_label, R_out, R_in in [("high-res", 150, 60), ("low-res", 15, 6)]:
    N = R_out * 3
    img = np.zeros((N, N), np.uint8); c = (N // 2, N // 2)
    cv2.circle(img, c, R_out, 255, -1); cv2.circle(img, c, R_in, 0, -1)
    px_area = int((img > 0).sum())                       # ground truth = filled pixel count
    cs, h = cv2.findContours(img, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE); h = h[0]
    outer = [i for i in range(len(cs)) if h[i][3] == -1][0]
    holes = [cs[j][:, 0, :] for j in range(len(cs)) if h[j][3] == outer]
    poly = Polygon(cs[outer][:, 0, :], holes)
    # outer boundary should move out 0.5 px, hole boundary should move in 0.5 px -> buffer(+0.5) does both
    fixed = poly.buffer(0.5, join_style="mitre")
    print(f"{scale_label:9s} pixel_area={px_area:6d}  raw_contour={poly.area:9.1f} ({(poly.area-px_area)/px_area:+.2%})"
          f"  buffered+0.5px={fixed.area:9.1f} ({(fixed.area-px_area)/px_area:+.2%})")

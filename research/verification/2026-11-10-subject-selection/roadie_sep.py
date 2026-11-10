import sys, numpy as np, cv2
from PIL import Image
a = np.asarray(Image.open(sys.argv[1]).convert("RGBA")).astype(int)
rgb, al = a[..., :3], a[..., 3]
ref = np.array([57, 46, 40])
d = np.sqrt(((rgb - ref) ** 2).sum(-1))
op = al == 255
print("disc-like pixel counts by distance from (57,46,40):")
for t in (5, 10, 20, 30, 40, 60):
    print(f"  <= {t}: {int(((d <= t) & op).sum())}")
# bird = opaque and far from ref
bird_core = op & (d > 60)
n, lab, stats, _ = cv2.connectedComponentsWithStats(bird_core.astype(np.uint8), connectivity=8)
order = np.argsort(-stats[1:, cv2.CC_STAT_AREA]) + 1
print("components of far-from-disc pixels (largest 8):", [(int(i), int(stats[i, cv2.CC_STAT_AREA])) for i in order[:8]])
# fringe: pixels within 3 px of largest component, not in it, opaque
big = (lab == order[0]).astype(np.uint8)
ring = cv2.dilate(big, np.ones((7, 7), np.uint8)).astype(bool) & ~big.astype(bool) & op
print("fringe pixels:", int(ring.sum()), "distance-to-disc percentiles 10/50/90/99:", np.percentile(d[ring], [10, 50, 90, 99]).round(1))
dark = op & (rgb.sum(-1) < 60)
print("very dark (sum<60) opaque pixels:", int(dark.sum()))
# disc colour spread far from bird
far = op & ~cv2.dilate(big, np.ones((41, 41), np.uint8)).astype(bool) & (d < 60)
print("disc spread (far from bird) distance percentiles 50/99/99.9:", np.percentile(d[far], [50, 99, 99.9]).round(1))

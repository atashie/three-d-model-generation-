import sys, time, tracemalloc, numpy as np, cv2, shapely, contourpy
from shapely import affinity
from PIL import Image
from tdmg.flat import mask_outline, _sampled_hausdorff
print("contourpy", contourpy.__version__)
with Image.open(sys.argv[1]) as im: m = np.asarray(im) == 255
sig = 2.5
def blurred(m):
    return cv2.GaussianBlur(m.astype(np.float32), (0, 0), sig, borderType=cv2.BORDER_CONSTANT)
def via_upsample(m, up=4):
    f = blurred(m)
    big = cv2.resize(f, (m.shape[1]*up, m.shape[0]*up), interpolation=cv2.INTER_LINEAR) >= 0.5
    return affinity.scale(mask_outline(big), 1/up, 1/up, origin=(0, 0))
def via_contourpy(m):
    f = np.pad(blurred(m), 1)  # zero border so every contour closes
    gen = contourpy.contour_generator(z=f, fill_type=contourpy.FillType.OuterOffset)
    pts, offs = gen.filled(0.5, np.inf)
    polys = []
    for p, o in zip(pts, offs):
        rings = [p[o[i]:o[i+1]] for i in range(len(o)-1)]
        polys.append(shapely.Polygon(rings[0], rings[1:]))
    g = shapely.union_all(polys)
    # contourpy uses array index coords (x=col, y=row) at pixel CENTRES; our outline uses
    # pixel-cell edges (pixel c spans [c, c+1]) -> shift by +0.5, minus the 1-px pad
    return affinity.translate(g, -0.5, -0.5)
results = {}
for name, fn in (("upsample4", via_upsample), ("contourpy", via_contourpy)):
    tracemalloc.start(); t = time.perf_counter(); g = fn(m); dt = time.perf_counter()-t
    peak = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
    print(f"{name:10s} {dt:.2f}s traced {peak/2**20:.0f} MiB area {g.area:.1f} px2 perim {g.length:.1f} valid {g.is_valid} parts {len(getattr(g,'geoms',[g]))} verts {shapely.get_num_coordinates(g)}")
    results[name] = g
print("hausdorff upsample vs contourpy (px):", round(_sampled_hausdorff(results["upsample4"], results["contourpy"], 0.05), 4))
print("mask area px", int(m.sum()))
# large synthetic: 4000 x 4000 noisy disc
rng = np.random.default_rng(0)
big = np.zeros((4000, 4000), np.uint8); cv2.circle(big, (2000, 2000), 1800, 1, -1)
big = (big.astype(bool) ^ (rng.random(big.shape) < 0.002))
for name, fn in (("contourpy", via_contourpy),):
    tracemalloc.start(); t = time.perf_counter(); g = fn(big); dt = time.perf_counter()-t
    peak = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
    print(f"4000px {name}: {dt:.2f}s traced {peak/2**20:.0f} MiB parts {len(getattr(g,'geoms',[g]))} valid {g.is_valid}")

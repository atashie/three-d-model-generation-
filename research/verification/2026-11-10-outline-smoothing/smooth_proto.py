import sys, time, numpy as np, cv2, shapely
from shapely import affinity
from PIL import Image
from tdmg.flat import mask_outline, to_model, clean, _sampled_hausdorff

with Image.open(sys.argv[1]) as im: m = np.asarray(im) == 255
W = 60.0
base, t = to_model(mask_outline(m), W); s = t["scale_mm_per_px"]
def opening(g, w=0.4): return g.buffer(-w/2, quad_segs=8).buffer(w/2, quad_segs=8)
def closing(g, w): return g.buffer(w/2, quad_segs=8).buffer(-w/2, quad_segs=8)

def A_blur(sigma_px, up=4):
    f = cv2.GaussianBlur(m.astype(np.float32), (0, 0), sigma_px)
    big = cv2.resize(f, (m.shape[1]*up, m.shape[0]*up), interpolation=cv2.INTER_LINEAR) >= 0.5
    g = mask_outline(big)
    g = affinity.scale(g, 1/up, 1/up, origin=(0, 0))
    x0, y1 = t["x0_px"], t["y1_px"]
    return affinity.affine_transform(g, [s, 0, 0, -s, -x0*s, y1*s])
def C_morph(r):  # closing then opening (morphological smoothing) at width 2r
    return opening(closing(base, 2*r), max(0.4, 2*r))
def chaikin(ring, it=3):
    p = np.asarray(ring.coords)[:-1]
    for _ in range(it):
        q = np.roll(p, -1, 0); p = np.stack([0.75*p+0.25*q, 0.25*p+0.75*q], 1).reshape(-1, 2)
    return p
def D_dp_chaikin(tol):
    g = opening(base)
    out = []
    for poly in getattr(g, "geoms", [g]):
        poly = poly.simplify(tol, preserve_topology=True)
        ext = chaikin(poly.exterior); holes = [chaikin(h) for h in poly.interiors]
        out.append(shapely.make_valid(shapely.Polygon(ext, holes)))
    return shapely.union_all(out)

variants = {"current (opening 0.4)": opening(base),
            "A blur s=1.5px": opening(A_blur(1.5)),
            "A blur s=2.5px": opening(A_blur(2.5)),
            "C morph r=0.25mm": C_morph(0.25),
            "C morph r=0.4mm": C_morph(0.4),
            "D DP0.1+Chaikin": D_dp_chaikin(0.1)}
ref = base
print(f"scale {s:.4f} mm/px; base perimeter {base.length:.1f} mm area {base.area:.1f}")
for k, g in variants.items():
    h = _sampled_hausdorff(ref, g, s/4)
    nv = shapely.get_num_coordinates(g)
    print(f"{k:24s} area {g.area:8.1f} ({100*(g.area-ref.area)/ref.area:+.2f}%)  perimeter {g.length:7.1f} mm  vertices {nv:6d}  hausdorff_vs_mask {h:.3f} mm  parts {len(getattr(g,'geoms',[g]))}")
# render crops (tail, beak) at 25 px/mm
R = 25
def render(g, win):
    x0, y0, x1, y1 = win; Wp, Hp = int((x1-x0)*R), int((y1-y0)*R)
    img = np.full((Hp, Wp), 255, np.uint8)
    for poly in getattr(g, "geoms", [g]):
        rings = [poly.exterior, *poly.interiors]
        pts = [np.round((np.asarray(r.coords)[:, :2]-[x0, y1])*[R, -R]).astype(np.int32) for r in rings]
        cv2.fillPoly(img, pts, 60)
    return img
def win_px(xa, xb, ya, yb):  # pixel window -> mm window
    return ((xa-t["x0_px"])*s, (t["y1_px"]-yb)*s, (xb-t["x0_px"])*s, (t["y1_px"]-ya)*s)
wins = [win_px(100, 230, 340, 470), win_px(320, 620, 160, 300)]
rows = []
for k, g in variants.items():
    tiles = [render(g, w) for w in wins]
    hmax = max(x.shape[0] for x in tiles)
    tiles = [np.pad(x, ((0, hmax-x.shape[0]), (0, 10)), constant_values=200) for x in tiles]
    row = np.concatenate(tiles, 1)
    cv2.putText(row, k, (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
    rows.append(np.pad(row, ((0, 10), (0, 0)), constant_values=200))
wmax = max(r.shape[1] for r in rows)
sheet = np.concatenate([np.pad(r, ((0, 0), (0, wmax-r.shape[1])), constant_values=200) for r in rows], 0)
Image.fromarray(sheet).save(sys.argv[2]); print("sheet", sheet.shape)

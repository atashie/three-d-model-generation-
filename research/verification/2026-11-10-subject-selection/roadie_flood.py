import sys, numpy as np, cv2
from PIL import Image
a = np.asarray(Image.open(sys.argv[1]).convert("RGBA")).astype(int)
rgb, al = a[..., :3], a[..., 3]
op = al >= 128
seed = (60, 396)  # x, y: inside disc, left of bird
ref = rgb[seed[1], seed[0]]
print("seed colour", ref.tolist())
d = np.sqrt(((rgb - ref) ** 2).sum(-1))
for tol in (20, 30, 40, 60):
    cand = (op & (d <= tol)).astype(np.uint8)
    n, lab = cv2.connectedComponents(cand, connectivity=4)
    bg = lab == lab[seed[1], seed[0]]
    fg = op & ~bg
    m, lab2, st, _ = cv2.connectedComponentsWithStats(fg.astype(np.uint8), connectivity=8)
    areas = sorted((int(x) for x in st[1:, cv2.CC_STAT_AREA]), reverse=True)
    left_disc = int((op & (d <= tol) & ~bg).sum())
    print(f"tol {tol}: removed {int(bg.sum())}; fg components {m-1}; largest areas {areas[:6]}; small(<50px) {sum(x<50 for x in areas)}; disc-coloured px kept (enclosed) {left_disc}")
    if tol == 40:
        # where is the 2nd largest component? bbox
        order = np.argsort(-st[1:, cv2.CC_STAT_AREA]) + 1
        for i in order[:4]:
            x, y, w, h = st[i, :4]; print("   comp bbox", (int(x), int(y), int(w), int(h)), "area", int(st[i, 4]))
        out = np.zeros((*fg.shape, 3), np.uint8); out[fg] = 255
        Image.fromarray(out).save(sys.argv[2])

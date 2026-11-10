import sys, numpy as np
from PIL import Image
from collections import Counter
for p in sys.argv[1:]:
    im = Image.open(p); print(p, im.mode, im.size, im.info.get("dpi"))
    a = np.asarray(im.convert("RGBA"))
    al = a[...,3]
    print(" alpha unique count", len(np.unique(al)), "transparent frac", (al==0).mean().round(3), "opaque frac", (al==255).mean().round(3), "partial frac", ((al>0)&(al<255)).mean().round(3))
    op = a[al==255][:, :3]
    q = (op//16)*16
    c = Counter(map(tuple, q)); print(" top opaque colors (quantized 16):", [(k, round(v/len(q),3)) for k,v in c.most_common(8)])
    h,w = al.shape
    for name,(y,x) in {"center":(h//2,w//2),"corner":(0,0),"edge-mid-top":(0,w//2),"near-top-in":(int(h*0.08),w//2),"left-in":(h//2,int(w*0.08))}.items():
        print("  ", name, (x,y), a[y,x].tolist())

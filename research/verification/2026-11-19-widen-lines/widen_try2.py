import json, numpy as np, cv2
from PIL import Image
from tdmg import color as C
from tdmg.color_outline import handle_outlines
from tdmg.rules import load_rules
J='jobs/roadie-thanksgiving/'
S=r'out/'
a=np.asarray(Image.open(J+'select/cutout.png').convert('RGBA')); mask=a[...,3]>127
q=C.quantize(a[...,:3],mask,6)
lim=json.load(open(J+'colors/colors.json'))['limits']
limits=C.Limits(**{k:lim[k] for k in C.Limits.__dataclass_fields__})
rules=load_rules()
d,res=handle_outlines(q,outline_color='auto',outlines='drop',limits=limits,rules=rules)
lab=np.asarray(d.labels); print(d.hex)
vis=np.zeros(lab.shape+(3,),np.uint8)
pal=[tuple(int(h[i:i+2],16) for i in (1,3,5)) for h in d.hex]
for i,p in enumerate(pal): vis[lab==i]=[x//3 for x in p]
rows=[]
for c in range(len(d.hex)):
    m=lab==c
    thin=m&~C.open_mask(m,limits.min_width_px)
    n,cc,st,_=cv2.connectedComponentsWithStats(thin.astype(np.uint8),connectivity=8)
    dt=cv2.distanceTransform(m.astype(np.uint8),cv2.DIST_L2,5)
    for i in range(1,n):
        if st[i,4]<15: continue
        cm=cc==i; w=2*np.percentile(dt[cm],90); length=st[i,4]/max(w,1)
        # neighbours: non-c labels in a 2px ring
        ring=cv2.dilate(cm.astype(np.uint8),np.ones((5,5),np.uint8)).astype(bool)&~m
        rl=lab[ring]; vals,cnt=np.unique(rl,return_counts=True)
        nb={ (d.hex[v] if v>=0 else 'out'):round(k/cnt.sum(),2) for v,k in zip(vals,cnt) if k/cnt.sum()>0.1}
        rows.append((d.hex[c],st[i,4],round(w,1),round(length,1),st[i,0]+st[i,2]//2,st[i,1]+st[i,3]//2,nb))
        vis[cm]=(0,255,0) if length>=4 else (255,0,255)
rows.sort(key=lambda r:-r[1])
for r in rows: print(r)
Image.fromarray(vis).save(S+'thin_all.png')

from tdmg.color_outline import stroke_ridge
W=0.5/limits.mm_per_px; print('W px',W)
new=lab.copy(); chosen=[]
for c in range(len(d.hex)):
    m=lab==c
    n,cc,st,_=cv2.connectedComponentsWithStats(m.astype(np.uint8),connectivity=4)
    op=C.open_mask(m,limits.min_width_px)
    dt=cv2.distanceTransform(m.astype(np.uint8),cv2.DIST_L2,5)
    for i in range(1,n):
        cm=cc==i
        if not (cm&~op).any(): continue
        ring=cv2.dilate(cm.astype(np.uint8),np.ones((5,5),np.uint8)).astype(bool)&~m
        rl=lab[ring]; vals,cnt=np.unique(rl,return_counts=True)
        share=cnt.max()/cnt.sum(); host=vals[cnt.argmax()]
        w=2*np.percentile(dt[cm],90); el=st[i,4]/max(w,1)
        if share>=0.9 and host>=0 and el>=3 and w<W:
            chosen.append((d.hex[c],'in',d.hex[host],st[i,4],round(w,1),round(el,1),st[i,0],st[i,1]))
            r=stroke_ridge(cm); ry,rx=np.nonzero(r)
            disc=np.zeros(m.shape,np.uint8); 
            for y,x in zip(ry,rx): cv2.circle(disc,(int(x),int(y)),int(round(W/2)),1,-1)
            new[(disc>0)&(lab==host)]=c
for ch in chosen: print(ch)
q2=C.from_labels(new,d.rgb,iterations=d.iterations,converged=d.converged,n_requested=d.n_requested,n_distinct_colors=d.n_distinct_colors,dropped=d.dropped)
cl,log=C.clean_regions(q2,limits)
cl0,_=C.clean_regions(d,limits)
def show(L):
    v=np.zeros(L.shape+(3,),np.uint8); v[:]=(0,160,255)
    for i,p in enumerate(pal): v[L==i]=p
    return Image.fromarray(v)
box=(620,330,880,460)
a1=show(np.asarray(cl0.labels)).crop(box); a2=show(np.asarray(cl.labels)).crop(box); a0=Image.fromarray(a[...,:3]).crop(box)
o=Image.new('RGB',(260*3+12,130),'black'); o.paste(a0,(0,0)); o.paste(a1,(266,0)); o.paste(a2,(532,0))
o.resize((o.width*3,o.height*3),Image.NEAREST).save(S+'widen_result.png')

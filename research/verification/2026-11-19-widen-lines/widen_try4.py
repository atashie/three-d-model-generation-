import json, numpy as np, cv2
from PIL import Image
from tdmg import color as C
from tdmg.color_outline import handle_outlines, stroke_ridge
from tdmg.rules import load_rules
J='jobs/roadie-thanksgiving/'
S=r'out/'
a=np.asarray(Image.open(J+'select/cutout.png').convert('RGBA')); mask=a[...,3]>127
q=C.quantize(a[...,:3],mask,6)
lim=json.load(open(J+'colors/colors.json'))['limits']
limits=C.Limits(**{k:lim[k] for k in C.Limits.__dataclass_fields__})
d,res=handle_outlines(q,outline_color='auto',outlines='drop',limits=limits,rules=load_rules())
fam=res.family; L0=np.asarray(q.labels); lab=np.asarray(d.labels)
# map q index -> d index
remap=res.remap
# colour view: each family member -> Lab-nearest non-family colour
lab_q=np.asarray(q.lab); nonfam=[i for i in range(len(q.hex)) if i not in fam]
view=L0.copy()
for f in fam:
    nn=nonfam[int(np.argmin(((lab_q[nonfam]-lab_q[f])**2).sum(1)))]; view[L0==f]=nn
    print('family',q.hex[f],'->',q.hex[nn])
W=0.5/limits.mm_per_px; new=lab.copy(); chosen=[]
for c in nonfam:
    m=view==c
    n,cc,st,_=cv2.connectedComponentsWithStats(m.astype(np.uint8),connectivity=4)
    op=C.open_mask(m,limits.min_width_px); dt=cv2.distanceTransform(m.astype(np.uint8),cv2.DIST_L2,5)
    for i in range(1,n):
        comp=cc==i
        if st[i,4]<10: continue
        thinp=comp&~C.open_mask(comp,W)
        n2,c2,s2,_=cv2.connectedComponentsWithStats(thinp.astype(np.uint8),connectivity=8)
        for j in range(1,n2):
            cm=c2==j
            if s2[j,4]<10: continue
            ring=cv2.dilate(cm.astype(np.uint8),np.ones((5,5),np.uint8)).astype(bool)&~m
            rl=view[ring]
            if not len(rl): continue
            vals,cnt=np.unique(rl,return_counts=True)
            share=cnt.max()/cnt.sum(); host=vals[cnt.argmax()]
            w=2*np.percentile(dt[cm],90); el=s2[j,4]/max(w,1)
            if share>=0.9 and host>=0 and el>=3 and w<W:
                chosen.append((q.hex[c],'in',q.hex[host],s2[j,4],round(w,1),round(el,1),s2[j,0],s2[j,1]))
                ry,rx=np.nonzero(stroke_ridge(cm)); disc=np.zeros(m.shape,np.uint8)
                for y,x in zip(ry,rx): cv2.circle(disc,(int(x),int(y)),int(round(W/2)),1,-1)
                new[(disc>0)&(lab==remap[host])]=remap[c]
for ch in chosen: print(ch)
q2=C.from_labels(new,d.rgb,iterations=d.iterations,converged=d.converged,n_requested=d.n_requested,n_distinct_colors=d.n_distinct_colors,dropped=d.dropped)
cl,log=C.clean_regions(q2,limits); cl0,_=C.clean_regions(d,limits)
pal=[tuple(int(h[i:i+2],16) for i in (1,3,5)) for h in d.hex]
def show(Lb):
    v=np.zeros(Lb.shape+(3,),np.uint8); v[:]=(0,160,255)
    for i,p in enumerate(pal): v[Lb==i]=p
    return Image.fromarray(v)
print('changed px vs no-widen', (np.asarray(cl.labels)!=np.asarray(cl0.labels)).sum())
for name,box in [('turkey',(620,330,880,460)),('whole',(120,150,860,780))]:
    a0=Image.fromarray(a[...,:3]).crop(box); a1=show(np.asarray(cl0.labels)).crop(box); a2=show(np.asarray(cl.labels)).crop(box)
    w,h=a0.size; o=Image.new('RGB',(w*3+12,h),'black'); o.paste(a0,(0,0)); o.paste(a1,(w+6,0)); o.paste(a2,(2*w+12,0))
    f=3 if name=='turkey' else 1; o.resize((o.width*f,o.height*f),Image.NEAREST).save(S+'widen4_'+name+'.png')

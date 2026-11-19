import json, sys, numpy as np, cv2
from PIL import Image
from tdmg import color as C
from tdmg.color_outline import handle_outlines, stroke_band
from tdmg.rules import load_rules
J='jobs/roadie-thanksgiving/'; S=sys.argv[1]; Wmm=float(sys.argv[2]); BODY=float(sys.argv[3])
a=np.asarray(Image.open(J+'select/cutout.png').convert('RGBA')); mask=a[...,3]>127
q=C.quantize(a[...,:3],mask,6)
lim=json.load(open(J+'colors/colors.json'))['limits']
limits=C.Limits(**{k:lim[k] for k in C.Limits.__dataclass_fields__})
d,res=handle_outlines(q,outline_color='auto',outlines='drop',limits=limits,rules=load_rules())
fam=res.family; L0=np.asarray(q.labels); lab=np.asarray(d.labels); remap=res.remap
lab_q=np.asarray(q.lab); nonfam=[i for i in range(len(q.hex)) if i not in fam]
view=L0.copy()
for f in fam:
    view[L0==f]=nonfam[int(np.argmin(((lab_q[nonfam]-lab_q[f])**2).sum(1)))]
W=Wmm/limits.mm_per_px; new=lab.copy(); allband=np.zeros(lab.shape,bool); chosen=[]
for c in nonfam:
    m=view==c
    n,cc,st,_=cv2.connectedComponentsWithStats(m.astype(np.uint8),connectivity=4)
    for i in range(1,n):
        comp=cc==i
        if st[i,4]<10: continue
        body=C.open_mask(comp,BODY*W)            # areas: wide enough to be a shape, not a line
        linep=comp&~body
        n2,c2,s2,_=cv2.connectedComponentsWithStats(linep.astype(np.uint8),connectivity=8)
        dt=cv2.distanceTransform(comp.astype(np.uint8),cv2.DIST_L2,5)
        for j in range(1,n2):
            cm=c2==j
            if s2[j,4]<limits.min_area_px: continue
            ring=cv2.dilate(cm.astype(np.uint8),np.ones((5,5),np.uint8)).astype(bool)&~m
            rl=view[ring]
            if not len(rl): continue
            vals,cnt=np.unique(rl,return_counts=True); share=cnt.max()/cnt.sum(); host=vals[cnt.argmax()]
            w=2*np.percentile(dt[cm],90); el=s2[j,4]/max(w,1)
            if share>=0.9 and host>=0 and el>=3:
                chosen.append((q.hex[c],'in',q.hex[host],s2[j,4],round(float(w),1),round(el,1),s2[j,0],s2[j,1]))
                band=stroke_band(cm,np.ones(cm.shape,bool),W)
                band&=(lab==remap[host])|(lab==remap[c])
                new[band]=remap[c]; allband|=band|cm
for ch in chosen: print(ch)
q2=C.from_labels(new,d.rgb,iterations=d.iterations,converged=d.converged,n_requested=d.n_requested,n_distinct_colors=d.n_distinct_colors,dropped=d.dropped)
cl,log=C.clean_regions(q2,limits); cl0,_=C.clean_regions(d,limits)
L2=np.asarray(cl.labels)
line_px=allband&(new==remap[0]); lost=line_px&(L2!=remap[0])
print('W px',round(W,2),'line px',int(line_px.sum()),'erased by cleanup',int(lost.sum()))
pal=[tuple(int(h[i:i+2],16) for i in (1,3,5)) for h in d.hex]
def show(Lb,hl=None):
    v=np.zeros(Lb.shape+(3,),np.uint8); v[:]=(0,160,255)
    for i,p in enumerate(pal): v[Lb==i]=p
    if hl is not None: v[hl]=(0,255,0)
    return Image.fromarray(v)
box=(620,330,880,460)
a0=Image.fromarray(a[...,:3]).crop(box); a1=show(L2).crop(box); a2=show(L2,lost).crop(box)
w_,h_=a0.size; o=Image.new('RGB',(w_*3+12,h_),'black'); o.paste(a0,(0,0)); o.paste(a1,(w_+6,0)); o.paste(a2,(2*w_+12,0))
o.resize((o.width*3,o.height*3),Image.NEAREST).save(S+f'widen5_{Wmm}_{BODY}.png')

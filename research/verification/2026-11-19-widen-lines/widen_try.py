import json, numpy as np, cv2
from PIL import Image
from tdmg import color as C
from tdmg.color_outline import _opened
from tdmg.rules import load_rules
J='jobs/roadie-thanksgiving/'
S=r'out/'
rgb=np.asarray(Image.open(J+'select/cutout.png').convert('RGBA'))
mask=rgb[...,3]>127; rgb=rgb[...,:3]
q=C.quantize(rgb,mask,6)
print(q.hex)
c=json.load(open(J+'colors/colors.json')); lim=c['limits']
class L: pass
from tdmg.color import Limits
limits=Limits(**{k:lim[k] for k in Limits.__dataclass_fields__}) if hasattr(Limits,'__dataclass_fields__') else None
thin,kept=_opened(q,limits)
lab=np.asarray(q.labels)
fam=[i for i,h in enumerate(q.hex) if h in ('#ca2116','#bb4b46')]
strokes=np.zeros(lab.shape,bool)
for f in fam: strokes|=(lab==f)&~kept[f]
n,cc=cv2.connectedComponents(strokes.astype(np.uint8),connectivity=8)
k=np.ones((5,5),np.uint8)
out=[]
vis=np.zeros(lab.shape+(3,),np.uint8); vis[mask]=(90,90,90)
for i in range(1,n):
    m=cc==i; a=m.sum()
    if a<20: continue
    ring=cv2.dilate(m.astype(np.uint8),k).astype(bool)&~m
    rl=lab[ring]; rl=rl[~np.isin(rl,fam)]
    tot=ring.sum(); outside=(rl==C.OUTSIDE).sum() if hasattr(C,'OUTSIDE') else 0
    vals,cnt=np.unique(rl,return_counts=True)
    top=cnt.max()/tot if len(cnt) else 0
    ys,xs=np.nonzero(m)
    out.append((a,round(top,2),q.hex[vals[cnt.argmax()]] if vals[cnt.argmax()]>=0 and vals[cnt.argmax()]<len(q.hex) else 'out',int(xs.mean()),int(ys.mean())))
    vis[m]=(0,255,0) if top>=0.8 else (255,0,255)
out.sort(key=lambda t:-t[0])
for o in out[:25]: print(o)
print('components',len(out))
Image.fromarray(vis).save(S+'widen_classes.png')

# per-pixel: dominant non-family color share in a window around each stroke pixel
K=len(q.hex)
famm=np.isin(lab,fam)
vis2=np.zeros(lab.shape+(3,),np.uint8); vis2[mask]=(90,90,90)
for r in (3,4,5):
    win=np.ones((2*r+1,2*r+1),np.float32)
    counts=[]
    for c_ in list(range(K))+[C.OUTSIDE]:
        if c_ in fam: continue
        counts.append(cv2.filter2D(((lab==c_)).astype(np.float32),-1,win,borderType=cv2.BORDER_CONSTANT))
    counts=np.stack(counts); tot=counts.sum(0)+1e-9
    dom=counts.max(0)/tot
    for thr in (0.85,0.9,0.95):
        inter=strokes&(dom>=thr)
        n2,cc2,st,_=cv2.connectedComponentsWithStats(inter.astype(np.uint8),connectivity=8)
        big=[(st[i,4],st[i,0]+st[i,2]//2,st[i,1]+st[i,3]//2) for i in range(1,n2) if st[i,4]>=10]
        print('r',r,'thr',thr,'interior px',inter.sum(),'of',strokes.sum(),'comps>=10:',sorted(big,reverse=True)[:8])
    if r==4:
        inter=strokes&(dom>=0.9); vis2[strokes]=(255,0,255); vis2[inter]=(0,255,0)
Image.fromarray(vis2).crop((620,330,880,460)).resize((1040,520),Image.NEAREST).save(S+'widen_turkey.png')
Image.fromarray(vis2).save(S+'widen_all.png')

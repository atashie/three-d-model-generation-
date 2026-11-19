# variant A: lines painted after cleanup, then smoothed; measure line width in the fine map
import runpy, sys, numpy as np, cv2
from PIL import Image
sys.argv=[sys.argv[0],sys.argv[1],'0.41','2']
g=runpy.run_path(sys.argv[1]+'widen_try5.py')
C=g['C']; d=g['d']; cl0=g['cl0']; allband=g['allband']; new=g['new']; remap=g['remap']; limits=g['limits']
from tdmg.smoothing import smooth_labels, SUPERSAMPLE
from tdmg.rules import load_rules
from tdmg.color_config import edge_sigma_px
sig,_=edge_sigma_px('smooth',load_rules()); print('sigma',sig,'supersample',SUPERSAMPLE)
L=np.array(cl0.labels); line=allband&(new==remap[0]); L[line]=remap[0]
fine=smooth_labels(L,sig,SUPERSAMPLE).fine
s=SUPERSAMPLE
red=(fine==remap[0])
# width of the turkey lines in the fine map: inscribed width along their ridge (box around turkey)
y0,y1,x0,x1=360*s,445*s,680*s,830*s
sub=red[y0:y1,x0:x1].astype(np.uint8)
lin=cv2.resize(line[360:445,680:830].astype(np.uint8),(sub.shape[1],sub.shape[0]),interpolation=cv2.INTER_NEAREST).astype(bool)
dt=cv2.distanceTransform(sub,cv2.DIST_L2,5)
from tdmg.color_outline import stroke_ridge
def widths(mask_bool, region, scale):
    dtm=cv2.distanceTransform(np.pad(mask_bool,1).astype(np.uint8),cv2.DIST_L2,5)[1:-1,1:-1]
    r=stroke_ridge(mask_bool)&region
    w=2*dtm[r]*scale
    return np.percentile(w,[1,5,10,50]).round(3), r.sum()
mm=limits.mm_per_px
# before smoothing (image pixels)
Lb=L[360:445,680:830]==remap[0]; lb=line[360:445,680:830]
print('pixel map  width mm p1/p5/p10/p50:',*widths(Lb,lb,mm))
print('smoothed   width mm p1/p5/p10/p50:',*widths(sub.astype(bool),lin,mm/s))
pal=[tuple(int(h[i:i+2],16) for i in (1,3,5)) for h in d.hex]
v=np.zeros(fine.shape+(3,),np.uint8)
for i,p in enumerate(pal): v[fine==i]=p
v[np.kron(L<0,np.ones((s,s),bool))]=(0,160,255)
Image.fromarray(v[330*s:460*s,620*s:880*s]).save(sys.argv[1]+'widenA_smoothed.png')

# variant A2: draw the lines on the fine (smoothed) map, after smoothing
from scipy.spatial import cKDTree
fine0=smooth_labels(np.asarray(cl0.labels),sig,s).fine.copy()
W=0.41/mm
strokes=allband & False
# line strokes as detected (the drawn line pieces), from try5: rebuild from 'chosen' masks is not kept; use line pixels' ridge
ridge=stroke_ridge(np.repeat(np.repeat(line,2,0),2,1)); ry,rx=np.nonzero(ridge)
pts=np.stack([(ry+0.5)/2,(rx+0.5)/2],1)               # image px coords of ridge half-pixel centres
H,Wd=fine0.shape; yy,xx=np.mgrid[y0:y1,x0:x1]; cen=np.stack([((yy+0.5)/s).ravel(),((xx+0.5)/s).ravel()],1)
dd,_=cKDTree(pts).query(cen,distance_upper_bound=W/2+1)
paint=(dd<=W/2).reshape(yy.shape)
blk=fine0[y0:y1,x0:x1]; host=remap[2] if False else None
blk[paint & ((blk==remap[0])|(blk==g['remap'][2]))]=remap[0]
red2=fine0[y0:y1,x0:x1]==remap[0]
lin2=paint
print('fine-drawn width mm p1/p5/p10/p50:',*widths(red2,lin2,mm/s))
v=np.zeros(fine0.shape+(3,),np.uint8)
for i,p in enumerate(pal): v[fine0==i]=p
v[np.kron(L<0,np.ones((s,s),bool))]=(0,160,255)
Image.fromarray(v[330*s:460*s,620*s:880*s]).save(sys.argv[1]+'widenA2_fine.png')
from scipy.ndimage import distance_transform_edt
e=distance_transform_edt(np.pad(red2,1))[1:-1,1:-1]
r=stroke_ridge(red2)&lin2
# drop ridge points within W of a line end: ends = ridge pixels with <=1 ridge neighbour
nb=cv2.filter2D(r.astype(np.uint8),-1,np.ones((3,3),np.float32))-r
ends=r&(nb<=1); endzone=cv2.dilate(ends.astype(np.uint8),np.ones((int(W*s),)*2,np.uint8)).astype(bool)
print("ridge",r.sum(),"ends",ends.sum()); w=2*(e[r&~endzone]-0.5)*mm/s
print('exact EDT, ends excluded: n',w.size,'mm p1/p5/p50/p95:',np.percentile(w,[1,5,50,95]).round(3))

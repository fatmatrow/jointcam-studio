"""Two damped liquid modes, advanced only for the beaker avatar."""
import math
from functools import lru_cache


class BeakerWater:
    def __init__(self):
        self.previous=None
        self.velocity=[0.,0.]
        self.height=[0.,0.]
        self.rate=[0.,0.]

    def sample(self,now,pose,body):
        x,y,yaw,roll,pitch=pose[:5]
        position=(x+body[1]-.75*roll+.36*yaw,y+.60*pitch)
        previous=self.previous
        self.previous=(now,position)
        if previous is None or not 0<now-previous[0]<.25:
            self.height[:]=self.rate[:]=self.velocity[:]=[0.,0.]
            return (0.,0.)
        dt=now-previous[0]
        count=max(1,math.ceil(dt*120))
        h=dt/count
        for i in range(2):
            old=self.velocity[i]
            speed=(position[i]-previous[1][i])/dt
            self.velocity[i]=old+(max(-6.,min(6.,speed))-old)*(-math.expm1(-dt/.075))
            acceleration=(self.velocity[i]-old)/dt
            # Lateral slosh and fore/aft rocking have different natural frequencies.
            w=(9.,12.)[i]
            target=(.11*(roll+body[0]),.06*pitch)[i]
            forcing=-min(32.,max(-32.,acceleration))*(1.15,.70)[i]
            for _ in range(count):
                self.rate[i]+=(w*w*(target-self.height[i])-4.6*self.rate[i]+forcing)*h
                self.height[i]+=self.rate[i]*h
            if abs(self.height[i]-target)<.00012 and abs(self.rate[i])<.001:
                self.height[i],self.rate[i]=target,0.
        return tuple(max(-.26,min(.26,v)) for v in self.height)


def water_tile(image,levels):
    """Warp the existing liquid and meniscus inside the chamber in raster mode."""
    import cv2
    import numpy as np
    # Grids are shared across frames. Qt paints only this chamber rectangle.
    grid=_raster_grid()
    x,y,weight,side,bowl,region=grid
    delta=(levels[0]*side*170+levels[1]*bowl*96)*weight
    tile=image[565:799].copy()
    cv2.remap(image,x,y-delta,cv2.INTER_LINEAR,dst=tile[region],borderMode=cv2.BORDER_REPLICATE)
    tile[region][:,:,3]=image[565:799][region][:,:,3]
    return tile


@lru_cache(maxsize=1)
def _raster_grid():
    import numpy as np
    y,x=np.mgrid[565:799,0:534].astype('f4')
    u=np.clip((x-244)/213,-1,1)
    env=np.maximum(0,1-np.abs(y-(651+14*(1-u*u)))/86)
    width=140+(y-540)*.53
    edge=np.clip((width-np.abs(x-244))/18,0,1)
    stem=np.clip((np.abs(x-(322-.67*(y-650)))-14)/9,0,1)
    weight=env*env*(3-2*env)*edge*stem
    rows,cols=np.nonzero(weight)
    region=np.s_[rows.min():rows.max()+1,cols.min():cols.max()+1]
    return tuple(np.ascontiguousarray(a[region]) for a in (x,y,weight,u,1-2*u*u))+(region,)

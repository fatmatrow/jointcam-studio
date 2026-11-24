"""Detect an outward-moving local haze while rejecting whole-frame lighting changes."""
import cv2
import numpy as np
import math

class Breath:
    def __init__(self):
        self.prev=None
        self.near=np.full(8,-100.)
        self.last=self.trigger=-100.
        self.count=self.votes=0
        self.center=None
    def sample(self,rgb,mouth,stamp):
        if mouth is None:return 0.
        h=round(80*rgb.shape[0]/rgb.shape[1])
        im=cv2.resize(rgb,(80,h),interpolation=cv2.INTER_AREA).astype(np.float32)
        lum=.25*im[:,:,0]+.5*im[:,:,1]+.25*im[:,:,2]
        red,green,blue=im[:,:,0],im[:,:,1],im[:,:,2]
        sat=np.maximum(np.maximum(red,green),blue)-np.minimum(np.minimum(red,green),blue)
        values=np.stack((lum,sat),axis=2)
        delta=stamp-self.last;self.last=stamp
        if self.prev is None or self.prev.shape!=values.shape or delta>.85:
            self.prev=values.copy();self.count=self.votes=0;self.near.fill(-100.)
            self.y,self.x=np.mgrid[:h,:80]+.5
        dl=lum-self.prev[:,:,0];dc=self.prev[:,:,1]-sat
        haze=((dl>10)|(dc>12))&((dl>0)|(dc>20))&(sat<np.maximum(45,self.prev[:,:,1]+1))
        dt=np.clip(delta,.012,.25)
        quiet=not haze.any()
        clear_rate=1-np.exp(-dt/.53)
        if quiet:
            self.prev+=(values-self.prev)*np.float64(clear_rate)
        else:
            rate=np.where(haze,1-np.exp(-dt/1.5),clear_rate)
            self.prev+=(values-self.prev)*rate[:,:,None]
        span=max(1.,mouth['span']*80);mx=mouth['x']*80;my=mouth['y']*h

        movement=self.center and math.hypot(mx-self.center[0],my-self.center[1])>span*.18
        self.center=(mx,my);self.count+=1
        reset=self.count<5 or movement or span<3
        if not quiet and not reset:
            dx=(self.x-mx)/span;dy=(self.y-my)/span;dist=np.hypot(dx,dy)
            outside=dist>2.2
            reset=np.count_nonzero(haze & outside)>.27*max(1,np.count_nonzero(outside))
        if reset:
            self.votes=0;self.near.fill(-100.)
        elif quiet:
            self.votes=max(0,self.votes-1)
        else:
            sector=((np.arctan2(dy,dx)+np.pi)*4/np.pi).astype(int)%8
            valid=(dist>.34)&(dist<1.85)&~((np.abs(dx)<.39)&(dy>-.9)&(dy<.62))
            near=valid&(dist<.86);far=valid&~near
            bins=lambda m:np.bincount(sector[m],minlength=8)
            n=bins(near&haze);f=bins(far&haze);age=stamp-self.near
            spread=np.any((age>.038)&(age<.78)&(f>=3)&(f>.055*bins(far)))
            self.near[(n>=2)&(n>.10*bins(near))&(age>.76)]=stamp
            self.votes=self.votes+1 if spread else max(0,self.votes-1)
        if self.votes>=2 and stamp-self.trigger>1.4:self.trigger=stamp;self.votes=0
        a=stamp-self.trigger
        return (1-math.exp(-a*9))*math.exp(-max(0,a-.8)/1.4)

"""Track the pipe's existing whiskers from the top edge of the camera lip matte."""
import numpy as np
from functools import lru_cache
from facetiles import SCALE, TILE_W, TILE_H


def lip_edges(patch):
    if patch is None:
        return None
    # The central halves avoid noise at the outer lip corners.
    S=SCALE
    mask=patch[:,2*TILE_W:3*TILE_W,3]>127
    found=[]
    for region in (mask[:,26*S:47*S],mask[:,49*S:70*S]):
        columns=region.any(axis=0)
        if columns.sum()<4*S:
            return None
        tops=region[:,columns].argmax(axis=0)
        found.append((float(np.median(tops))+.5)/TILE_H-.5)
    return found


def shifts(rig,edges,live):
    height=1.48*rig.gap*rig.aspect
    if edges is None:
        top=-.45 if live else -(.12+.18*rig.opening)
        edges=(top,top)
    # Reference the lower central fringe. Keep a narrow gap above the lip.
    return tuple(max(-132.,min(12.,rig.mouth[1]+height*edge-12.-686.)) for edge in edges)


@lru_cache(maxsize=1)
def raster_maps():
    y,x=np.mgrid[455:756,12:452].astype(np.float32)
    edge=np.clip((np.abs(x[:1]-225)-108)/103,0,1)
    side=np.clip((x[:1]-187)/76,0,1)
    return y,x,1-edge*edge*(3-2*edge),side


def warp_raster(source,shift):
    import cv2
    y,x,weight,side=raster_maps()
    d=weight*((1-side)*shift[0]+side*shift[1])
    lo=635+d
    hi=722+d
    sy=np.where(y<lo,455+(y-455)*180/(lo-455),
                np.where(y<hi,y-d,722+(y-hi)*34/(756-hi)))
    return cv2.remap(source,x,sy,cv2.INTER_LINEAR)

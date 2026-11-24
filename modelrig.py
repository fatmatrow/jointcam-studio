"""Height-weighted character rig in illustration pixels and 960 by 540 stage coordinates."""
import json
import math
from pathlib import Path
from struct import Struct

_GPU_POSE=Struct("=17f")

ART=Path(__file__).resolve().parent/"assets"/"avatars"
DEPTHS=json.loads((ART/"depths.json").read_text())


class CharacterRig:
    def __init__(self,key,size,landmarks,pose,body,zoom,pan,torso=(0.,0.,0.)):
        self.torso=torso
        self.water=(0.,0.)
        self.key=key
        self.width,self.height=size
        self.eye,self.gap,self.mouth,self.hat=landmarks
        x,y,yaw,roll,pitch,self.opening,aspect=pose
        self.aspect=max(.12,min(1.2,aspect))
        self.angles=(pitch,yaw,.78*roll+body[0])
        self.pan=pan
        self.zoom=zoom
        self.lean=(108*zoom*(x+body[1]),-108*zoom*y)
        self.chest=(self.eye[0],self.mouth[1]+95)

    def gpu_pose(self,live):
        # Uniforms reach OpenGL as 32-bit floats. The live lip uses the camera tile.
        return _GPU_POSE.pack(*self.angles,*self.lean,*self.pan,self.zoom,self.aspect,
                              0. if live else self.opening,*self.whiskers,*self.torso,*self.water)

    def project(self,x,y,z=0.):
        h=self.height
        u=max(0.,min(1.,(1-y/h-.18)/.4))
        weight=u*u*(3-2*u)
        # Broad lower-trunk bend blends out before the rigid upper section.
        v=max(0.,min(1.,(1-y/h-.15)/.35))
        trunk=v*v*(3-2*v)*(1-weight)
        pitch,yaw,roll=(head*weight+lower*trunk for head,lower in zip(self.angles,self.torso))
        x-=self.eye[0]
        y=h*.62-y
        y,z=y*math.cos(pitch)-z*math.sin(pitch),y*math.sin(pitch)+z*math.cos(pitch)
        x,z=x*math.cos(yaw)+z*math.sin(yaw),-x*math.sin(yaw)+z*math.cos(yaw)
        x,y=x*math.cos(roll)-y*math.sin(roll),x*math.sin(roll)+y*math.cos(roll)
        perspective=h*2.8/(h*2.8-z)
        x*=perspective
        y*=perspective
        scale=387*self.zoom/h
        return [480+480*self.pan[0]+x*scale+self.lean[0]*weight,
                322.92-270*self.pan[1]+(-y+h*.62-self.eye[1])*scale+self.lean[1]*weight]

    def anchors(self,volume):
        depths=DEPTHS[self.key] if volume else (0.,)*4
        points=(self.eye,self.mouth,self.hat,self.chest)
        out={name:self.project(*p,z) for name,p,z in zip(("eye","mouth","hat","chest"),points,depths)}
        ex,ey=out["eye"];rx,ry=self.project(self.eye[0]+self.gap,self.eye[1],depths[0])
        out.update(angle=math.atan2(ry-ey,rx-ex),scale=math.hypot(rx-ex,ry-ey)/42)
        return out

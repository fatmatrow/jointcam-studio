import ctypes as C
import os
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np

MAP={33:36,160:37,158:38,133:39,153:40,144:41,362:42,385:43,387:44,263:45,373:46,380:47,
     61:48,40:49,37:50,0:51,267:52,270:53,291:54,321:55,314:56,17:57,84:58,91:59,
     78:60,81:61,13:62,311:63,308:64,402:65,14:66,178:67,1:30}
class NativeFace:
    def __init__(self):
        self.state=None
        if os.name!="nt":return
        try:
            self.api=C.CDLL(str(Path(__file__).parent/"assets/face-ar.dll"))
        except OSError:
            return
        self.api.nvopen.argtypes=[C.c_void_p]
        self.api.nvclose.argtypes=[C.c_void_p]
        self.api.nvface.argtypes=[C.c_void_p,C.c_uint,C.c_uint,C.c_void_p,C.c_void_p]
        self.state=C.create_string_buffer(self.api.nvsize())
        self.rgba=None
        self.points=[SimpleNamespace(x=0.,y=0.) for _ in range(468)]
        self.xy=np.zeros((68,2),np.float32)
        if not self.api.nvopen(self.state):self.close()
    def detect(self,rgb):
        self.rgba=cv2.cvtColor(rgb,cv2.COLOR_RGB2RGBA,dst=self.rgba)
        rgba=self.rgba
        result=self.api.nvface(self.state,rgba.shape[1],rgba.shape[0],rgba.ctypes.data,self.xy.ctypes.data)
        # No face is a normal observation. Keep the RTX session ready for the next frame.
        if result<0:self.close()
        if result!=1:return None
        for i,j in MAP.items():
            point=self.points[i]
            point.x,point.y=map(float,self.xy[j])
        return self.points
    def close(self):
        if self.state is not None:self.api.nvclose(self.state);self.state=None

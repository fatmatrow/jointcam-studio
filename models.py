"""GPU-skinned closed meshes with surface-mapped live eyes and lips."""
import moderngl as gl
import numpy as np
from PIL import Image
from modelrig import ART


class Models:
    def __init__(self,ctx):
        self.ctx=ctx
        self.shader=ctx.program(vertex_shader=(ART/"body.vert").read_text(),
                                fragment_shader=(ART/"body.frag").read_text())
        self.shader["art"].value=0
        self.shader["webcam"].value=1
        self.cache={}
        self.uniform_values={}

    def load(self,key):
        with np.load(ART/(key+".npz")) as data:
            vertices=self.ctx.buffer(data["vertices"].tobytes())
            normals=self.ctx.buffer(data["normals"].tobytes())
            indices=self.ctx.buffer(data["indices"].tobytes())
        mesh=self.ctx.vertex_array(self.shader,[(vertices,"4f","vertex"),(normals,"3f","vertexNormal")],indices,index_element_size=2)
        with Image.open(ART/(key+".png")) as im:
            tex=self.ctx.texture(im.size,4,im.tobytes())
        tex.repeat_x=tex.repeat_y=False
        tex.build_mipmaps()
        tex.filter=(gl.LINEAR_MIPMAP_LINEAR,gl.LINEAR)
        if self.ctx.max_anisotropy>=1:tex.anisotropy=min(16.,self.ctx.max_anisotropy)
        return mesh,tex

    def draw(self,stage,rig,patch):
        if rig.key not in self.cache:self.cache[rig.key]=self.load(rig.key)
        mesh,texture=self.cache[rig.key]
        texture.use(0)
        webcam=stage.textures[1]
        webcam.use(1)
        if patch is not None and patch is not stage.last_patch:
            webcam.write(patch)
            stage.last_patch=patch
        p=self.shader
        # Glasses end at .346 gap above/below the eyes. Lips span .74 gap times aspect.
        face_band=(min(rig.eye[1]-.36*rig.gap,rig.mouth[1]-.75*rig.gap*rig.aspect),
                   max(rig.eye[1]+.36*rig.gap,rig.mouth[1]+.75*rig.gap*rig.aspect))
        for name,val in (("faceBand",face_band),("artSize",(rig.width,rig.height)),("pan",rig.pan),("eye",rig.eye),
                         ("mouth",rig.mouth),("angles",rig.angles),("torso",rig.torso),("lean",rig.lean),("gap",rig.gap),
                         ("material",{"bong":0,"lighter":1,"pipe":2}[rig.key]),("water",rig.water),("zoom",rig.zoom),("lipAspect",rig.aspect),("opening",rig.opening),
                         ("whiskers",rig.whiskers),("live",patch is not None),("glasses",stage.glasses)):
            if self.uniform_values.get(name)!=val:
                p[name].value=val
                self.uniform_values[name]=val
        self.ctx.enable_only(gl.DEPTH_TEST)
        self.ctx.depth_func="<="
        mesh.render()
        self.ctx.enable_only(gl.BLEND)

"""Desktop OpenGL rendering of the JointCam Stage mesh and materials."""
import math
import os
from pathlib import Path
import moderngl as gl
import numpy as np
from PIL import Image
from facetiles import PATCH_W, TILE_H

ASSETS = Path(__file__).resolve().parent / "assets"
QUAD = np.array([[-1,-1],[1,-1],[1,1],[-1,-1],[1,1],[-1,1]], np.float32)


class Renderer:
    def __init__(self, width, height, transparent=False, glasses=True, context=None, target=None):
        self.ctx = ctx = context or gl.create_standalone_context(**({"backend":"egl"} if os.name != "nt" else {}))
        self.target = target or ctx.simple_framebuffer((width,height), components=4)
        self.target.use()
        self.size = (width,height)
        self.pixels = None
        self.last_patch = None
        self.transparent, self.glasses = transparent, glasses

        def program(name):
            return ctx.program(vertex_shader=(ASSETS/f"vs{name}.glsl").read_text(),
                               fragment_shader=(ASSETS/f"fs{name}.glsl").read_text())
        self.body = program("Body")
        self.particles = program("Particles")
        self.mesh_vertices = ctx.buffer((ASSETS/"mesh.bin").read_bytes())
        self.mesh_indices = ctx.buffer((ASSETS/"triangles.bin").read_bytes())
        self.mesh = ctx.vertex_array(self.body, [(self.mesh_vertices,"3f 2f 1f 1f","p","uv","front","wrap")],
            self.mesh_indices,index_element_size=2)
        self.emissive = self.emissive_mesh = None
        self.uniform_state = {}
        self.body_count = int((ASSETS/"body-count.txt").read_text())
        self.textures = []
        for slot, name, uniform in [(0,"face.png","photo"),(1,None,"webcam"),(2,"paper.jpg","paper")]:
            if name:
                with Image.open(ASSETS/name) as src:
                    img = src.convert("RGB")
                    tex = ctx.texture(img.size,3,img.tobytes())
                    tex.build_mipmaps()
                    tex.filter = (gl.LINEAR_MIPMAP_LINEAR,gl.LINEAR)
                    tex.anisotropy = min(16.,ctx.max_anisotropy) if ctx.max_anisotropy>=1 else 1.
            else:
                tex = ctx.texture((PATCH_W,TILE_H),4)
                tex.filter = (gl.LINEAR,gl.LINEAR)
            tex.repeat_x = tex.repeat_y = False
            tex.use(slot)
            self.textures.append(tex)
            self.body[uniform].value = slot
        self.points = np.empty((37,6),np.float32)
        self.stream = ctx.buffer(reserve=self.points.nbytes,dynamic=True)
        self.sprites = ctx.vertex_array(self.particles,[
            (ctx.buffer(QUAD),"2f","pt"),
            (self.stream,"4f 2f /i","instance","state")])
        self.history = np.empty((192,3),np.float64)
        self.indices = np.arange(37)
        self.seeds = (self.indices*.61803399+.17)%1
        self.age_offsets = self.indices/37
        self.points[:,5] = self.seeds
        self.wind_phase=float(np.random.default_rng().uniform(0,2*math.pi))
        self.opening=.25
        self.heat=0.
        self.backdrop=False
        self.hcount = 0
        self.zoom=1.0
        self.pan=(0.,0.)

    def resize_target(self, target, size):
        self.size = size
        self.pixels = None
        self.target = target

    def plume(self,t):
        age = (t/2.6 + self.age_offsets) % 1
        sec = 2.6*age
        phase=self.wind_phase
        wind=.33*np.sin((t-sec)*.71+phase)+.22*np.sin((t-sec)*1.37-phase)
        earlier=np.maximum(0,np.searchsorted(self.history[:self.hcount,0],t-sec-.14,side="right")-1)
        idx = np.maximum(0, np.searchsorted(self.history[:self.hcount,0], t-sec, side="right")-1)
        x = self.history[idx,1] + .225*(.12*np.sin((t-sec)*1.9+age*4)+.39*age*np.sin((t-sec)*1.4+age*6)+.15*age)
        drift=np.clip((self.history[idx,1]-self.history[earlier,1])/.14,-.8,.8)
        x+=age*(wind*.15-drift*.24)+.018*age*np.sin(phase+age*(5+4*self.opening))
        y = self.history[idx,2] + (.19+.05*self.opening)*sec
        radius = .40*(.05+.31*age)*(1+.9*self.heat)*self.zoom
        self.points[:,0] = x
        self.points[:,1] = y
        self.points[:,2] = radius
        self.points[:,3] = self.seeds*5+age*3
        self.points[:,4] = age
        self.particles["clock"].value=t
        self.stream.write(self.points)
        self.sprites.render(vertices=6,instances=len(self.points))

    def draw_model(self,rig,patch):
        if not hasattr(self,"models"):
            from models import Models
            self.models=Models(self.ctx)
        self.models.draw(self,rig,patch)

    def clear_stage(self,alpha):
        self.target.use()
        self.ctx.viewport=(0,0,*self.size)
        self.target.clear(*((.31,.29,.27,1) if self.backdrop else (0,0,0,0) if alpha else (0,1,0,1)))

    def draw(self,t,face,body=(0.,0.),alpha=False,paint=True):
        c,p = self.ctx,self.body
        x,y,yaw,roll,pitch,opening,aspect = face["pose"] if face else (0,0,0,0,0,.58,.49)
        tilt,shift = body
        scale=.40*self.zoom
        place=(x+shift+self.pan[0]/(.5625*scale),y,scale,-.12+self.pan[1])
        # Match the vertex shader's X/Y/Z rotation and neck pivot.
        ty,tz=2.965*math.cos(pitch),2.965*math.sin(pitch)
        tx=-.19*math.cos(yaw)+tz*math.sin(yaw)
        tx,ty=tx*math.cos(roll)-ty*math.sin(roll),tx*math.sin(roll)+ty*math.cos(roll)-1.05
        tx,ty=tx*math.cos(tilt)-ty*math.sin(tilt),tx*math.sin(tilt)+ty*math.cos(tilt)
        if self.hcount==len(self.history):
            self.history[:-1]=self.history[1:]
        else:
            self.hcount+=1
        self.history[self.hcount-1]=(t,(tx+place[0])*.5625*scale,(ty+y)*scale+place[3])
        ox,oy=self.history[self.hcount-1,1:]
        self.tip=((1+ox)/2,(1-oy)/2)
        if not paint:return
        self.target.use()
        c.viewport = (0, 0, *self.size)
        for slot, texture in enumerate(self.textures):
            texture.use(slot)
        if face and face["patch"] is not None and face["patch"] is not self.last_patch:
            self.textures[1].write(face["patch"])
            self.last_patch = face["patch"]
        state = self.uniform_state
        state.update(body=(0.,0.,tilt),head=(pitch,yaw,roll),place=place,heat=.12+.88*self.heat,
                     opening=opening,articulation=(max(0,opening-.08),0.,0.),lipAspect=aspect,clock=t,
                     manual=float(face is not None and face["patch"] is not None))
        for name,value in state.items():
            p[name].value = value
        self.target.clear(*( (.31,.29,.27,1) if self.backdrop else (0,0,0,0) if self.transparent else (0,1,0,1) ))
        c.blend_func=(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA,gl.ONE,gl.ONE_MINUS_SRC_ALPHA)
        c.enable_only(gl.BLEND)
        self.opening=opening
        self.plume(t)
        c.enable_only(gl.DEPTH_TEST)
        c.depth_func="<="
        self.mesh.render(vertices=-1 if self.glasses else self.body_count)
        c.enable_only(gl.BLEND)

    def draw_emissive(self, target, size):
        """Render only the coal and ember emission of the last drawn pose into target.

        The glow pass multiplies the stage by this mask, so warm-colored artwork, props and
        costume pieces never bloom. Only light the ember actually gives off does.
        """
        ctx = self.ctx
        if self.emissive is None:
            source = (ASSETS/"fsBody.glsl").read_text()
            for old, new in (
                ("fragment=vec4(base+vec3(.54,.53,.49)*studio+vec3(.44,.116,.028)*fire*glint,1.);return;", "fragment=vec4(0.);return;"),
                ("fragment=vec4(rgb*(.89+.11*max(f,0.)),1.);return;", "fragment=vec4(0.);return;"),
                ("fragment=vec4(rgb,1.);}", "fragment=vec4(clamp(fissure*embers*(.58+.33*heat)+coal*heat*.9+hot*pulse*.5,0.,1.));}"),
            ):
                if old not in source:
                    raise RuntimeError("Stage shader layout changed. Ember glow unavailable.")
                source = source.replace(old, new)
            self.emissive = ctx.program(vertex_shader=(ASSETS/"vsBody.glsl").read_text(), fragment_shader=source)
            for slot, name in enumerate(("photo","webcam","paper")):
                if name in self.emissive:
                    self.emissive[name].value = slot
            self.emissive_mesh = ctx.vertex_array(self.emissive, [(self.mesh_vertices,"3f 2f 1f 1f","p","uv","front","wrap")],
                                                  self.mesh_indices, index_element_size=2)
        program = self.emissive
        for name, value in self.uniform_state.items():
            if name in program:
                program[name].value = value
        target.use()
        ctx.viewport = (0, 0, *size)
        target.clear(0., 0., 0., 0., depth=1.)
        ctx.enable_only(gl.DEPTH_TEST)
        ctx.depth_func = "<="
        self.emissive_mesh.render(vertices=-1 if self.glasses else self.body_count)
        ctx.enable_only(gl.BLEND)
        self.target.use()
        ctx.viewport = (0, 0, *self.size)

    def read_frame(self, alpha=False, target=None):
        target = self.target if target is None else target
        target.use()
        if self.pixels is None:
            w,h=self.size
            self.pixels=np.empty((h,w,4),np.uint8)
        target.read_into(self.pixels,components=4,alignment=1)
        if alpha:
            # Particle blending accumulates premultiplied color. DirectShow ARGB
            # consumers expect straight color at partially transparent pixels.
            opacity=self.pixels[:,:,3]
            edge=(opacity>0)&(opacity<255)
            if edge.any():
                a=opacity[edge].astype(np.uint16)[:,None]
                rgb=self.pixels[:,:,:3][edge].astype(np.uint16)
                self.pixels[:,:,:3][edge]=np.minimum(255,(rgb*255+a//2)//a)
        out=self.pixels[::-1]
        return np.ascontiguousarray(out if alpha else out[:,:,:3])

    def close(self):
        self.ctx.release()

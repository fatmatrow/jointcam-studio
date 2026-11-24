"""Stage's rig and particle simulation, hosted by Qt's native JavaScript engine."""
from karate import KarateCostume
from avatars import Cutout
import json
try:
    from orjson import dumps as native_encode, loads as decode_commands
except ImportError:
    decode_commands=json.loads
    native_encode=None


def encode_state(payload):
    if native_encode is not None:
        try:
            return native_encode(payload).decode("utf-8")
        except TypeError:
            pass
    return json.dumps(payload,separators=(",",":"),allow_nan=False)

import sys
import math
from pathlib import Path
from functools import lru_cache
import numpy as np
from PySide6.QtCore import Qt,QRectF,QPointF
from PySide6.QtGui import QPixmap,QPainter,QColor,QPen,QImage,QLinearGradient,QPainterPath,QFont
from PySide6.QtQml import QJSEngine
from PySide6.QtOpenGL import QOpenGLPaintDevice

ROOT=Path(__file__).resolve().parent
@lru_cache(maxsize=512)
def color(s):
    if s.startswith("rgba("):
        r,g,b,a=map(float,s[5:-1].split(","))
        return QColor(int(r),int(g),int(b),round(255*a))
    return QColor(s)

def path_ops(ops):
    path=QPainterPath()
    for action,*a in ops:
        if action=="rect": path.addRect(*a)
        elif action=="closePath": path.closeSubpath()
        else: getattr(path,action)(*a)
    path.setFillRule(Qt.OddEvenFill)
    return path

@lru_cache(maxsize=256)
def puff_color(alpha):
    return QColor(220,226,225,alpha)


def particle_paths(kind,size):
    # Geometry is local to the particle. Translation, spin and opacity stay live.
    path=QPainterPath()
    if kind==1:
        path.moveTo(-size*2,0)
        path.quadTo(size*.42,-size*.43,size*.55,0)
        path.quadTo(size*.42,size*.43,-size*2,0)
    elif kind==2:
        for j in range(8):
            angle=j*math.pi/4
            radius=size*(.23 if j%2 else 1.4)
            path.lineTo(math.cos(angle)*radius,math.sin(angle)*radius)
        path.closeSubpath()
    else:
        w,h=size*.58,size*.26
        path.moveTo(-w,-h*.4)
        path.lineTo(-w*.2,-h)
        path.lineTo(w,h*.2)
        path.lineTo(w*.15,h)
        path.closeSubpath()
        highlight=QPainterPath()
        highlight.moveTo(-w*.2,-h)
        highlight.lineTo(w,h*.2)
        highlight.lineTo(w*.06,0)
        highlight.closeSubpath()
        return path,highlight
    return path,None


# The raster backend can reuse local paths. Qt OpenGL may reuse tessellation
# from an earlier transform, so give that backend fresh paths for each draw.
cached_particle_paths=lru_cache(maxsize=256)(particle_paths)


class Effects:
    def __init__(self,settings):
        self.settings=settings
        self.js=QJSEngine()
        source="\n".join((ROOT/"rig"/(n+".js")).read_text(encoding="utf-8") for n in "bridge stage grip stage-items float-art floating ninjas arms atmosphere run".split())
        result=self.js.evaluate(source,"stage-rig.js")
        if result.isError(): raise RuntimeError(result.property("stack").toString()+result.toString())
        self.run=self.js.evaluate("renderOverlay")
        self.js.evaluate("restoreFloatingHomes").call([settings.value("floating-homes","[]")])
        self.js.evaluate("floatingProps.restoreExclusions").call([settings.value("prop-exclusions","{}")])
        self.prop_layout=json.loads((ROOT/"assets/prop-atlas/layout.json").read_text())
        self.prop_scale=0
        self.prop_atlas=None
        self.sent_stamps=(None,None)
        self.cutout=Cutout()
        self.impact_audio=True
        self.karate_costume=None
        self.ninja_sprites=None
        self.fx=[]

    def prepare_props(self,scale):
        tier=next((n for n in (1,2,4,6) if n>=scale-1e-6),6)
        if self.prop_scale==tier:return
        atlas=QPixmap(str(ROOT/f"assets/prop-atlas/{tier}.png"))
        if atlas.isNull():raise RuntimeError("Could not load prop artwork")
        self.prop_rects=[(QRectF(left,top,w,h),QRectF(x*tier,y*tier,w*tier,h*tier))
                         for x,y,w,h,left,top in self.prop_layout]
        self.prop_atlas=atlas
        self.prop_scale=tier

    def reset(self):
        self.sent_stamps=(None,None)
        self.js.evaluate("resetTrackingRig").call([])

    def ninja_sound(self,cue):
        if sys.platform=="win32" and cue in ("kick","punch","blade","strike","strike2","miss"):
            import winsound
            try:
                winsound.PlaySound(str(ROOT/"assets"/("ninja-"+cue+".wav")),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
            except RuntimeError:
                pass

    def play_impact(self):
        if self.impact_audio and sys.platform=="win32":
            import winsound
            try:
                winsound.PlaySound(str(ROOT/"assets/impact.wav"),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
            except RuntimeError:
                pass

    def advance(self,s,paint=True):
        s["fx"],self.fx=self.fx,[]
        body=s.get("bodyStamp",s["stamp"])
        hand=s.get("handStamp",s["stamp"])
        payload=s.copy()
        if not paint:payload["soundOnly"]=True
        if body==self.sent_stamps[0]:
            payload.pop("shoulders",None)
        elif len(payload.get("shoulders",[]))>17:
            # The arm rig reads pose landmarks 11–16 by their original indices.
            payload["shoulders"]=[None]*11+payload["shoulders"][11:17]
        if hand==self.sent_stamps[1]:payload.pop("hands",None)
        result=self.run.call([encode_state(payload)])
        if result.isError(): raise RuntimeError(result.toString()+" "+result.property("stack").toString())
        self.sent_stamps=(body,hand)
        commands,homes,exclusions=decode_commands(result.toString())
        if exclusions is not None:self.settings.setValue("prop-exclusions",json.dumps(exclusions))
        if homes is not None:self.settings.setValue("floating-homes",json.dumps(homes))
        return commands

    def composite(self,frame,s,device=None,patch=None,commands=None):
        if commands is None:
            commands=self.advance(s)
        paint_cutout=s.get("cutout") and not s.get("mesh")
        if not commands and not paint_cutout: return frame
        if device is None:
            # Pillow's array view may be backed by immutable Python bytes.
            if not frame.flags.writeable:frame=frame.copy()
            ch=frame.shape[2]
            device=QImage(frame.data,frame.shape[1],frame.shape[0],frame.strides[0],QImage.Format_RGBA8888 if ch==4 else QImage.Format_RGB888)
        if s["floaters"]:
            self.prepare_props(s["pose"]["scale"]*(1.525 if s["closeup"] else 1.)*device.height()/540)
        p=QPainter(device)
        make_particle_paths=cached_particle_paths
        if isinstance(device,QOpenGLPaintDevice):
            make_particle_paths=particle_paths
            # The avatar and output passes bind textures outside Qt. Invalidate
            # Qt's cached bindings before its painter samples the prop atlas.
            p.beginNativePainting()
            p.endNativePainting()
        p.scale(device.width()/960, device.height()/540)
        p.setRenderHints(QPainter.Antialiasing|QPainter.SmoothPixmapTransform)
        stack=[];stroke=QColor("black");fill=QColor("black");width=1.;path=QPainterPath();textfont=12
        try:
            if paint_cutout:
                self.cutout.paint(p,patch,s["wardrobe"].get("eyewear")=="classic")
            for act,*a in commands:
                if act=="ninjaSound":
                    self.ninja_sound(a[0])
                elif act=="karateCostume":
                    if self.karate_costume is None:self.karate_costume=KarateCostume()
                    self.karate_costume.draw(p,*a)
                elif act=="ninjaSprite":
                    if self.ninja_sprites is None:
                        self.ninja_sprites=QPixmap(str(ROOT/"assets/ninja-strip.png"))
                    x,y,side,step,fly,tilt,span=a
                    p.save()
                    p.translate(x,y)
                    p.scale(side,1)
                    p.rotate(tilt-fly*360)
                    p.setOpacity(min(1.,max(0.,(.52-fly)*5)))
                    p.drawPixmap(QRectF(-span/2,-span/2,span,span),self.ninja_sprites,
                                 QRectF((step%4)*320,(step//4)*320,320,320))
                    p.restore()
                elif act=="gripFront":
                    outline,fingers,weight=a
                    front=path_ops(fingers)
                    p.save()
                    p.setClipPath(path_ops(outline),Qt.IntersectClip)
                    p.save()
                    p.translate(.65,1.35)
                    p.strokePath(front,QPen(color("rgba(43,24,18,.23)"),weight+3,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
                    p.restore()
                    for tint,thickness in (("#201a18",weight+2.2),("#e6ac8b",weight)):
                        p.strokePath(front,QPen(color(tint),thickness,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
                    p.restore()
                elif act=="impactSound":
                    self.play_impact()
                elif act=="save": stack.append((stroke,fill,width,textfont));p.save()
                elif act=="restore": stroke,fill,width,textfont=stack.pop();p.restore()
                elif act=="beginPath": path=QPainterPath()
                elif act=="closePath": path.closeSubpath()
                elif act in ("moveTo","lineTo"): getattr(path,act)(*a)
                elif act=="roundRect": path.addRoundedRect(QRectF(*a[:4]),a[4],a[4],Qt.AbsoluteSize)
                elif act=="arc": path.addEllipse(QPointF(*a[:2]),a[2],a[2])
                elif act=="quadraticCurveTo": path.quadTo(*a)
                elif act=="bezierCurveTo": path.cubicTo(*a)
                elif act=="fillStyle":
                    if isinstance(a[0],dict):
                        fill=QLinearGradient(*a[0]["xy"])
                        for pos,c in a[0]["stops"]: fill.setColorAt(pos,color(c))
                    else: fill=color(a[0])
                elif act=="strokeStyle": stroke=color(a[0])
                elif act=="lineWidth": width=a[0]
                elif act=="stroke":
                    p.strokePath(path if a[0] is None else path_ops(a[0]),QPen(stroke,width,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
                elif act=="fill": p.fillPath(path,fill)
                elif act=="fillRect": p.fillRect(QRectF(*a),fill)
                elif act=="clip": p.setClipPath(path_ops(a[0]),Qt.IntersectClip)
                elif act=="globalAlpha": p.setOpacity(a[0])
                elif act=="rotate": p.rotate(math.degrees(a[0]))
                elif act in ("translate","scale"): getattr(p,act)(*a)
                elif act=="stageParticle":
                    kind,x,y,spin,alpha,stretch,turn,tint,size=a
                    p.save()
                    p.translate(x,y)
                    p.rotate(math.degrees(spin))
                    p.setOpacity(alpha)
                    if kind==1:p.rotate(math.degrees(turn))
                    if kind==0 or kind>=3:p.scale(stretch,1)
                    if kind==0:
                        p.fillRect(QRectF(-size,-size*.5,2*size,size),color(tint))
                    else:
                        shape,highlight=make_particle_paths(kind,size)
                        p.fillPath(shape,color(tint))
                        if highlight is not None:p.fillPath(highlight,color("#c9c2b5"))
                    p.restore()
                elif act=="breathPuff":
                    tint=puff_color(round(255*a[0]))
                    for i in (1,4,7):
                        path=QPainterPath()
                        path.addEllipse(QPointF(a[i],a[i+1]),a[i+2],a[i+2])
                        p.fillPath(path,tint)
                elif act=="floatSprite":
                    target,source=self.prop_rects[a[0]*3+a[1]]
                    p.drawPixmap(target,self.prop_atlas,source)
                elif act=="font": textfont=int(a[0].split("px")[0])
                elif act in ("fillText","strokeText"):
                    text,x,y=a;f=QFont();f.setPixelSize(textfont)
                    line=QPainterPath();line.addText(0,0,f,text);line.translate(x-line.boundingRect().width()/2,y)
                    if act=="fillText": p.fillPath(line,fill)
                    else: p.strokePath(line,QPen(stroke,width))
        finally: p.end()
        return frame

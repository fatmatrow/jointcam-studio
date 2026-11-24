"""Face-mounted costume rendered in stage coordinates by either painter backend."""
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen, QPixmap

# Left edge, front and right edge of the forehead strip in artwork coordinates.
FOREHEAD = {
    "bong": ((146,440,8),(243,440,81),(340,440,10)),
    "lighter": ((8,425,34),(149,425,73),(286,425,54)),
    "pipe": ((88,430,41),(232,430,127),(376,430,47)),
}


def mesh_mounts(rig, volume):
    def project(point):
        x,y,z=point
        return rig.project(x,y,z if volume else 0.)
    from modelrig import DEPTHS
    x,y=rig.mouth
    depth=DEPTHS[rig.key][1]
    return [project(p) for p in (*FOREHEAD[rig.key],(x,y,depth),
            (x+rig.gap*.42,y,depth-(4 if rig.key=="pipe" else 0)))]


def joint_mounts(renderer, pose, body):
    x,y,yaw,roll,pitch,opening,_=pose
    tilt,shift=body
    unit=108*renderer.zoom
    def project(px,py,pz,jaw=0.):
        # Same jaw displacement, neck weight and rotation order as vsBody.glsl.
        u=min(1.,max(0.,(py+1.34)/.99))
        w=u*u*(3-2*u)
        jaw*=max(0.,opening-.08)
        px*=1+.10*jaw
        py-=.14*jaw
        pz+=.11*jaw
        ry=(py+1.05)*math.cos(pitch)-pz*math.sin(pitch)
        rz=(py+1.05)*math.sin(pitch)+pz*math.cos(pitch)
        rx=px*math.cos(yaw)+rz*math.sin(yaw)
        ax=px+(rx*math.cos(roll)-ry*math.sin(roll)-px)*w
        ay=py+(rx*math.sin(roll)+ry*math.cos(roll)-1.05-py)*w
        return (480+480*renderer.pan[0]+unit*(x+shift+ax*math.cos(tilt)-ay*math.sin(tilt)),
                302.4-270*renderer.pan[1]-unit*(y+ax*math.sin(tilt)+ay*math.cos(tilt)))
    return [project(*p) for p in ((-.435,.18,.04),(.024,.18,.435),(.475,.18,.04),
                                  (.075,-.558,.42,.90),(.203,-.558,.39,.90))]


class KarateCostume:
    def __init__(self):
        self.stubble=QPixmap(str(Path(__file__).parent/"assets/karate-stubble.png"))

    def draw(self,p,mounts,opening,pitch,now):
        left,front,right,mouth,corner=mounts
        dx,dy=right[0]-left[0],right[1]-left[1]
        width=math.hypot(dx,dy)
        if width<2:return
        angle=math.atan2(dy,dx)
        cx=(front[0]-left[0])*math.cos(angle)+(front[1]-left[1])*math.sin(angle)
        cy=-(front[0]-left[0])*math.sin(angle)+(front[1]-left[1])*math.cos(angle)
        half=max(1,min(width*.12,math.dist(mouth,corner)*.46))
        cx=min(width-half,max(half,cx))
        p.save()
        p.translate(*left);p.rotate(math.degrees(angle))
        p.setPen(Qt.NoPen)
        tail=QPainterPath(QPointF(1,0))
        tail.cubicTo(-half*2,-half*2,-half*3.8,half*2,-half*6,half*.8)
        tail.lineTo(-half*4.9,half*2.4);tail.quadTo(-half*3.3,half*3.1,0,half*.4)
        p.fillPath(tail,QColor("#a52333"))
        band=QPainterPath(QPointF(0,-half*.75))
        band.quadTo(cx,cy-half*1.35,width,-half*.75)
        band.lineTo(width,half*.65);band.quadTo(cx,cy+half*1.75,0,half*.65);band.closeSubpath()
        p.fillPath(band,QColor("#ca2637"))
        # The patch sits on the front of the wrap as the face turns.
        center=cy*.5
        p.setBrush(QColor("#fff7e8"))
        p.drawRoundedRect(QRectF(cx-1.34*half,center-.86*half,2.68*half,1.72*half),half*.12,half*.12)
        p.setBrush(QColor("#bd1739"));p.drawEllipse(QPointF(cx,center),half*.54,half*.54)
        p.restore()

        dx,dy=corner[0]-mouth[0],corner[1]-mouth[1]
        scale=math.hypot(dx,dy)/18
        if scale<.08:return
        p.save();p.translate(*mouth);p.rotate(math.degrees(math.atan2(dy,dx)));p.scale(scale,scale)
        p.drawPixmap(QRectF(-37,-5,74,40),self.stubble,QRectF(self.stubble.rect()))
        p.translate(18,1+2*opening)
        p.rotate(18+15*min(1,max(0,opening))+7*math.sin(pitch))
        p.setPen(Qt.NoPen)
        def tube(x,w,h,col):
            p.setBrush(QColor(col));p.drawRoundedRect(QRectF(x,-h/2,w,h),.7,.7)
        tube(0,27,4.2,"#65584b");tube(.4,25.3,3.4,"#e9dfcb");tube(0,7,3.8,"#c49764")
        tube(24,3.6,4,"#82776f");tube(26.3,1.8,3.8,"#dd532c")
        p.setBrush(QColor(255,round(154+38*math.sin(now*5)),57))
        p.drawEllipse(QPointF(27.6,-.4),.85,1.2)
        p.translate(27.6,-2);p.rotate(-23)
        wisp=QPainterPath(QPointF(0,0));sway=math.sin(now*2.4)
        wisp.cubicTo(4,-5,-4+sway*3,-8,sway*2,-14)
        p.strokePath(wisp,QPen(QColor(202,207,207,98),.85))
        p.restore()

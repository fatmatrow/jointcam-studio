"""Cutout character artwork, registered to the eyes and mouth in stage coordinates."""
from modelrig import CharacterRig
from water import water_tile
from whiskers import lip_edges, shifts, warp_raster
from PIL import Image
from facetiles import TILE_W, TILE_H, PATCH_W
from functools import lru_cache
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPen, QPainter, QPolygonF, QPixmap, QTransform

CHOICES = (("The Joint", "joint"), ("Beaker Bong", "bong"),
           ("Pocket Lighter", "lighter"), ("Scruffy Crack Pipe", "pipe"))
# Eye midpoint, separation, mouth center, top attachment, all in source pixels.
LANDMARKS = {
    "bong": ((220, 511), 118, (220, 605), (243, 34)),
    "lighter": ((149, 488), 104, (149, 586), (116, 25)),
    "pipe": ((225, 498), 110, (225, 655), (221, 35)),
}
ART = Path(__file__).resolve().parent / "assets" / "avatars"
yy, xx = np.mgrid[-1:1:TILE_H*1j, -1:1:TILE_W*1j]
eye_mask = np.rint(255*np.clip((1-np.hypot(xx, yy))/.23, 0, 1)).astype(np.uint8)


@lru_cache(maxsize=3)
def artwork(key):
    image = QPixmap(str(ART / (key + ".png")))
    if image.isNull():
        raise RuntimeError("Could not load avatar artwork: " + key)
    return image


@lru_cache(maxsize=3)
def artwork_size(key):
    with Image.open(ART / (key + ".png")) as image:
        return image.size


class Cutout:
    def __init__(self):
        self.previous = self.face_image = None
        self.lip_patch=self.lip_edges=None
        self.bong_pixels=None
        self.pipe_pixels=None
        self.whisker_shift=None
        self.whisker_image=None

    def place(self,key,pose,body,zoom,pan,volume=False,patch=None,torso=(0.,0.,0.)):
        self.key=key
        if volume:
            size=artwork_size(key)
        else:
            self.image=artwork(key)
            size=(self.image.width(),self.image.height())
        self.rig=CharacterRig(key,size,LANDMARKS[key],pose,body,zoom,pan,torso)
        if key=="pipe":
            if patch is not self.lip_patch:
                self.lip_patch=patch
                self.lip_edges=lip_edges(patch)
            self.rig.whiskers=shifts(self.rig,self.lip_edges,patch is not None)
        else:
            self.rig.whiskers=(0.,0.)
            self.lip_patch=self.lip_edges=None
        self.aspect=self.rig.aspect
        self.opening=self.rig.opening
        return self.rig.anchors(volume)

    def paint(self,painter,patch,glasses):
        # Raster compatibility uses the same base weights, without a depth buffer.
        key=(self.key,id(patch),glasses,self.aspect,self.opening if patch is None else 0.)
        if self.key=="bong":key+=tuple(round(v,3) for v in self.rig.water)
        if key!=getattr(self,"sprite_key",None):
            sprite=self.image.copy()
            ink=QPainter(sprite)
            try:
                ink.setRenderHints(QPainter.Antialiasing|QPainter.SmoothPixmapTransform)
                if self.key=="bong" and any(self.rig.water):
                    if self.bong_pixels is None:
                        with Image.open(ART/"bong.png") as art:self.bong_pixels=np.array(art.convert("RGBA"))
                    tile=water_tile(self.bong_pixels,self.rig.water)
                    ink.save()
                    ink.setCompositionMode(QPainter.CompositionMode_Source)
                    ink.drawImage(0,565,QImage(tile.data,tile.shape[1],tile.shape[0],tile.strides[0],QImage.Format_RGBA8888))
                    ink.restore()
                if self.key=="pipe":
                    if self.pipe_pixels is None:
                        with Image.open(ART/"pipe.png") as art:
                            self.pipe_pixels=np.array(art.convert("RGBA"))
                    if self.whisker_shift!=self.rig.whiskers:
                        tile=warp_raster(self.pipe_pixels,self.rig.whiskers)
                        self.whisker_image=QImage(tile.data,tile.shape[1],tile.shape[0],
                                                  tile.strides[0],QImage.Format_RGBA8888).copy()
                        self.whisker_shift=self.rig.whiskers
                    ink.save()
                    ink.setCompositionMode(QPainter.CompositionMode_Source)
                    ink.drawImage(12,455,self.whisker_image)
                    ink.restore()
                self.paint_face(ink,patch,glasses)
            finally:
                ink.end()
            self.sprite_key,self.sprite=key,sprite
        sprite=self.sprite
        rig=self.rig
        geometry=(rig.key,rig.angles,rig.torso,rig.pan,rig.zoom,rig.lean)
        if geometry!=getattr(self,"strip_geometry",None):
            self.strips=self.projected_strips()
            self.strip_geometry=geometry
        for src,transform in self.strips:
            painter.save()
            painter.setWorldTransform(transform,True)
            painter.drawPixmap(src,sprite,src)
            painter.restore()

    def projected_strips(self):
        strips=[]
        w,h=self.rig.width,self.rig.height
        x0,y0=self.rig.project(0,0)
        x1,y1=self.rig.project(w,0)
        for y in range(0,h,32):
            height=min(32,h-y)
            x2,y2=self.rig.project(0,y+height)
            x3,y3=self.rig.project(w,y+height)
            src=QRectF(0,y,w,height)
            quad=QPolygonF([QPointF(x0,y0),QPointF(x1,y1),QPointF(x3,y3),QPointF(x2,y2)])
            t=QTransform()
            source=QPolygonF([src.topLeft(),src.topRight(),src.bottomRight(),src.bottomLeft()])
            if QTransform.quadToQuad(source,quad,t):
                strips.append((src,t))
            x0,y0,x1,y1=x2,y2,x3,y3
        return strips

    def paint_face(self, painter, patch, glasses):
        eye, gap, mouth, _ = LANDMARKS[self.key]
        if patch is not self.previous:
            self.previous = patch
            self.face_image = None
            if patch is not None:
                masked = patch.copy()
                for start in (0,TILE_W):
                    tile = masked[:,start:start+TILE_W,3]
                    np.minimum(tile, eye_mask, out=tile)
                self.face_image = QImage(masked.data,PATCH_W,TILE_H,masked.strides[0],QImage.Format_RGBA8888).copy()
        painter.save()
        try:
            centers = [(eye[0]-gap/2,eye[1]),(eye[0]+gap/2,eye[1]),mouth]
            for i,(cx,cy) in enumerate(centers):
                w = gap*(.91 if i<2 else 1.48)
                h = w*(.61 if i<2 else self.aspect)
                rect = QRectF(cx-w/2,cy-h/2,w,h)
                if self.face_image is not None:
                    painter.drawImage(rect,self.face_image,QRectF(i*TILE_W,0,TILE_W,TILE_H))
                elif i<2:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor("#eae0c8"))
                    painter.drawEllipse(rect.adjusted(5,6,-5,-6))
                    painter.setBrush(QColor("#31251c"))
                    painter.drawEllipse(QPointF(cx,cy),w*.14,h*.32)
                else:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor("#482c27"))
                    painter.drawEllipse(QPointF(cx,cy),w*.34,h*(.12+.18*self.opening))
            if glasses:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor("#40382e"),gap*.05))
                for cx,cy in centers[:2]:
                    painter.drawRoundedRect(QRectF(cx-gap*.48,cy-gap*.32,gap*.96,gap*.64),gap*.2,gap*.2)
                painter.drawLine(QPointF(eye[0]-gap*.035,eye[1]),QPointF(eye[0]+gap*.035,eye[1]))
        finally:
            painter.restore()

"""Compatibility preview and output for PCs without a working OpenGL context."""
import math
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw

def composite_ellipses(image,shapes):
    boxes=[tuple(map(int,box)) for box,_,_ in shapes]
    left=max(0,min(box[0] for box in boxes))
    top=max(0,min(box[1] for box in boxes))
    right=min(image.width,max(box[2] for box in boxes)+1)
    bottom=min(image.height,max(box[3] for box in boxes)+1)
    if left>=right or top>=bottom:return
    tile=Image.new("RGBA",(right-left,bottom-top))
    ink=ImageDraw.Draw(tile)
    for (x0,y0,x1,y1),(_,color,width) in zip(boxes,shapes):
        bounds=(x0-left,y0-top,x1-left,y1-top)
        if width:ink.ellipse(bounds,outline=color,width=width)
        else:ink.ellipse(bounds,fill=color)
    image.alpha_composite(tile,(left,top))


class SoftwareRenderer:
    def __init__(self,width,height):
        self.size=(width,height)
        self.wind_phase=float(np.random.default_rng().uniform(0,2*math.pi))
        self.last_tip=None
        self.wind=0.
        self.heat=0.
        self.backdrop=False
        self.zoom=1.
        self.pan=(0.,0.)
        self.glasses=True
        self.transparent=False
        assets=Path(__file__).resolve().parent/"assets"
        with Image.open(assets/"face.png") as source:
            self.base=source.convert("RGBA").crop((394,202,616,984))
        # The original mesh rings project onto the photo's paper and ash silhouette.
        vertices=np.fromfile(assets/"mesh.bin",dtype="<f4").reshape(-1,7)[:121*97].reshape(121,97,7)
        left,right=[],[]
        for ring in vertices:
            uv=ring[:,3:5]*1024
            y=int(round(uv[0,1]))-202
            left.append((int(uv[:,0].min())-394,y))
            right.append((int(uv[:,0].max())-394,y))
        mask=Image.new("L",self.base.size)
        ImageDraw.Draw(mask).polygon(left+right[::-1],fill=255)
        pixels=np.asarray(self.base).copy()
        yy,xx=np.mgrid[:pixels.shape[0],:pixels.shape[1]]
        ash=np.clip((101-yy)/16,0,1)*(.08+.16*np.maximum(0,np.sin(yy*.21+1.8*np.sin(xx*.13))))
        rng=np.random.default_rng(421)
        grain=rng.normal(0.,1.,ash.shape)
        phase=yy*.24+1.8*np.sin(xx*.12)+.5*np.sin(xx*.31+yy*.04)
        split=np.exp(-14*np.abs(np.sin(phase)))*np.clip((106-yy)/18,0,1)
        tone=174+10*grain+13*np.sin(phase)
        ash_rgb=np.stack([tone,tone-6,tone-15],axis=2)
        pixels[:,:,:3]=np.clip((pixels[:,:,:3]*(1-ash[:,:,None])+ash_rgb*ash[:,:,None])*(1-.36*split[:,:,None]),0,255)
        self.base=Image.fromarray(pixels)
        self.base.putalpha(mask)
        with Image.open(assets/"paper.jpg") as im:
            self.paper=im.convert("RGB").resize((149,187))
        cover=Image.new("L",self.paper.size)
        ImageDraw.Draw(cover).rounded_rectangle((0,0,148,186),radius=28,fill=255)
        self.paper_base=self.base.copy()
        self.paper_base.paste(self.paper,(55,359),cover)
        self.sprite_key=self.cached_sprite=None
        from facetiles import SCALE, TILE_W, TILE_H
        self.feather=Image.new("L",(TILE_W,TILE_H))
        ImageDraw.Draw(self.feather).ellipse((2*SCALE,3*SCALE,TILE_W-3*SCALE,TILE_H-4*SCALE),fill=255)

    def clear_stage(self,alpha):
        w,h=self.size
        color=(79,74,69) if self.backdrop else (0,0,0) if alpha else (0,255,0)
        frame=np.empty((h,w,4 if alpha else 3),np.uint8)
        frame[:]=(*color,255 if self.backdrop else 0) if alpha else color
        return frame

    def draw(self,t,face,body,alpha,paint=True):
        w,h=self.size
        x,y,yaw,roll,pitch,opening,aspect=face["pose"] if face else (0,0,0,0,0,.58,.49)
        patch=face["patch"] if face else None
        scale=h*.001*self.zoom
        sw=max(1,round(self.base.width*scale*(1-.20*abs(yaw))))
        sh=max(1,round(self.base.height*scale))
        ang=(roll*.72+body[0])*180/math.pi
        cx=w/2+w*self.pan[0]/2+(x+body[1])*h*.20*self.zoom
        cy=h*.56-h*self.pan[1]/2-y*h*.20*self.zoom
        rad=math.radians(ang)
        topx=cx-sh*.48*math.sin(rad)-sw*.10
        topy=cy-sh*.48*math.cos(rad)
        if self.last_tip:
            x0,t0=self.last_tip
            dt=max(.001,t-t0)
            self.wind+=(float(np.clip((topx-x0)/dt,-w*.4,w*.4))-self.wind)*(1-math.exp(-dt*5))
        self.last_tip=(topx,t)
        self.tip=(topx/w,topy/h)
        def anchor(px,py):
            dx=(px/222-.5)*sw;dy=(py/782-.5)*sh
            return [(cx+dx*math.cos(rad)+dy*math.sin(rad))*960/w,
                    (cy-dx*math.sin(rad)+dy*math.cos(rad))*540/h]
        self.overlay_anchors=dict(eye=anchor(117,426),hat=anchor(90,32),
                                  chest=anchor(113,580),mouth=anchor(128,503),
                                  scale=sw*540/h/120,angle=-rad)
        if getattr(self,"fight_costume",False) and paint:
            self.karate_mounts=[anchor(*p) for p in ((8,368),(113,368),(212,368),(128,503),(150,503))]
        if not paint:return
        key=(id(patch),aspect,self.glasses)
        if key!=self.sprite_key:
            sprite=(self.paper_base if patch is not None else self.base).copy()
            if patch is not None:
                for i,(cx,cy,width,height) in enumerate([(82,426,58,35),(152,426,58,35),(128,503,104,round(104*aspect))]):
                    from facetiles import tile as patch_tile
                    tile=Image.fromarray(patch_tile(patch,i).copy())
                    if i<2: tile.putalpha(self.feather)
                    tile=tile.resize((width,height),Image.Resampling.LANCZOS)
                    sprite.alpha_composite(tile,(cx-width//2,cy-height//2))
            ink=ImageDraw.Draw(sprite)
            if self.glasses:
                for cx in (82,152):
                    ink.rounded_rectangle((cx-31,405,cx+31,448),radius=19,outline="#393531",width=4)
                ink.line([(112,425),(118,421),(123,425)],fill="#806f58",width=3)
                ink.line([(49,423),(33,432)],fill="#62584b",width=3)
                ink.line([(185,423),(200,432)],fill="#62584b",width=3)
            self.cached_sprite=sprite
            self.sprite_key=key
            self.cached_patch=patch
        sprite=self.cached_sprite
        sprite=sprite.resize((sw,sh),Image.Resampling.BILINEAR).rotate(ang,Image.Resampling.BILINEAR,expand=True)
        img=Image.new("RGBA",(w,h),(79,74,69,255) if self.backdrop else (0,0,0,0) if alpha else (0,255,0,255))
        # Pillow truncates floating coordinates toward zero before rasterizing.
        # Keep those pixel coordinates while compositing only the affected area.
        shapes=[]
        for i in range(24):
            age=(t*.34+i/24)%1
            px=topx+math.sin((5+opening*3)*age+t+self.wind_phase)*age*sw*.4-self.wind*age*.22
            py=topy-age*sh*.28
            radius=(2+11*age)*self.zoom*(1+self.heat)
            shapes.append(((px-radius,py-radius,px+radius,py+radius),(235,226,214,int(45*(1-age))),2))
        if self.heat>.015:
            g=13*self.zoom
            shapes.append(((topx-g,topy,topx+g,topy+g),(255,69,8,int(195*self.heat)),0))
        composite_ellipses(img,shapes)
        img.alpha_composite(sprite,(round(cx-sprite.width/2),round(cy-sprite.height/2)))
        if self.heat>.015:
            g=10*self.zoom
            composite_ellipses(img,[((topx-g,topy+g,topx+g,topy+2*g),(255,63,6,int(128*self.heat)),0)])
        return np.ascontiguousarray(np.asarray(img if alpha else img.convert("RGB")))
    def close(self):
        pass

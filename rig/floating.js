'use strict';
const floatingProps = (() => {
 const lastPinch=[-1e5,-1e5],closedAt=[-1e5,-1e5],openingAt=[null,null];
 const impacts=[],chips=[],particles=[], pieces=[], pinching=[false,false];
 const homes=[[310,345],[645,340],[360,230],[610,225],[480,450],[155,300],[785,315],[245,180],[710,180]].map(([x,y],id)=>({x,y,angle:0,flip:x>480?-1:1,placed:false}));
 const chambers={
  1:{outline:[[-11,13],[9,13],[29,34],[26,39],[1,42],[-27,37],[-28,34]],y:27},
  7:{outline:[[-8,-2],[7,-2],[21,9],[25,22],[20,33],[7,40],[-11,38],[-22,29],[-26,17],[-20,6]],y:23},
  8:{outline:[[-15,-10],[8,-10],[8,30],[-15,30]],y:16}
 };
 const due=homes.map(()=>0),blocked=[false,false];
 const exploded=new Set(),drops=[];
 let exclusionsChanged=false;
 let propMode='off',nextFly=0,last=null,dirty=false;
 function setMode(value){
  if(value===propMode)return;
  propMode=value;exploded.clear();exclusionsChanged=true;reset()
 }
 const distance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
 function reset(){
  nextFly=0;drops.length=0;impacts.length=0;chips.length=0;pieces.length=0;particles.length=0;pinching.fill(false);lastPinch.fill(-1e5);closedAt.fill(-1e5);openingAt.fill(null);blocked.fill(false);due.fill(0);last=null
 }
 function restore(json){
  let saved;try{saved=JSON.parse(json)}catch(e){return}
  if(!Array.isArray(saved))return;
  homes.forEach((home,id)=>{
   const p=saved[id];
   if(p&&p.placed&&[p.x,p.y,p.angle].every(Number.isFinite))
    Object.assign(home,{x:clamp(p.x,32,928),y:clamp(p.y,28,512),angle:p.angle,flip:p.flip===-1?-1:1,placed:true})
  })
 }
 function changes(){if(!dirty)return null;dirty=false;return homes}
 function spawn(id,t){
  const h=Object.assign({},homes[id]);
  const fly=propMode==='occasional',dir=Math.random()<.5?1:-1;
  if(fly){h.x=dir>0?-64:1024;h.y=180+Math.random()*210;h.placed=false}
  pieces.push(Object.assign({},h,{id,part:0,grips:[],history:[],born:t,phase:id*1.65,
   fly,dir,fill:1,drip:0,slosh:0,sloshSpeed:0,waterX:h.x,waterV:0,lane:h.y,flight:false,warmth:0,seal:0,contact:0,nextPuff:0,latched:false,armedUntil:0,closedAt:null,wideAt:null}))
 }
 function world(s,p,u){
  const x=p.x*s.flip*u,y=p.y*u,c=Math.cos(s.angle),n=Math.sin(s.angle);
  return {x:s.x+x*c-y*n,y:s.y+x*n+y*c}
 }
 function local(s,p,u){
  const x=(p.x-s.x)/u,y=(p.y-s.y)/u,c=Math.cos(s.angle),n=Math.sin(s.angle);
  return {x:(x*c+y*n)*s.flip,y:-x*n+y*c}
 }
 const bounds=floatArt.map(art=>art.contours.map(loop=>{
  const xs=loop.map(p=>p[0]),ys=loop.map(p=>p[1]);
  return [Math.min(...xs),Math.max(...xs),Math.min(...ys),Math.max(...ys)]
 }));
 function closest(s,point,u,part=s.part,limit=Infinity){
  const p=local(s,point,u), loop=floatArt[s.id].contours[part];
  const [left,right,top,bottom]=bounds[s.id][part];
  if(p.x<left-limit||p.x>right+limit||p.y<top-limit||p.y>bottom+limit)return {gap:Infinity};
  let best=Infinity,anchor=null,inside=false;
  for(let i=0,j=loop.length-1;i<loop.length;j=i++){
   const [x,y]=loop[j],[bx,by]=loop[i],dx=bx-x,dy=by-y;
   const f=clamp(((p.x-x)*dx+(p.y-y)*dy)/(dx*dx+dy*dy||1),0,1);
   const q={x:x+f*dx,y:y+f*dy},d=distance(q,p);
   if(d<best){best=d;anchor=q}
   if((y>p.y)!==(by>p.y)&&p.x<(bx-x)*(p.y-y)/(by-y)+x)inside=!inside
  }
  return inside?{gap:0,p}:{gap:best,p:anchor}
 }
 function sample(a,h,i,t,k,off,offset){
  if(!a?.wrist||!h||t-a.time>200||t-h.time>190)return null;
  const p=h.points,gesture=h.gesture||p;
  const metric=(j,l)=>Math.hypot(gesture[j].x-gesture[l].x,(gesture[j].y-gesture[l].y)/a.aspect,
   .45*((gesture[j].z??0)-(gesture[l].z??0)));
  const palm=Math.max(.008,metric(5,17),metric(0,9)*.75);
  const ratio=metric(4,8)/palm;
  if(!Number.isFinite(ratio))return null;
  if(h.time!==lastPinch[i]){
   if(h.time-lastPinch[i]>210){pinching[i]=false;openingAt[i]=null}
   if(!pinching[i]&&ratio<.44){pinching[i]=true;closedAt[i]=h.time}
   if(pinching[i]&&ratio>.67){
    if(openingAt[i]===null)openingAt[i]=h.time;
    if(ratio>.92||h.time-openingAt[i]>=32)pinching[i]=false
   }else openingAt[i]=null;
   lastPinch[i]=h.time
  }
  const mid={x:(p[4].x+p[8].x)/2,y:(p[4].y+p[8].y)/2};
  mid.z=(p[4].z+p[8].z)/2;
  const hand=stageItems.finger(canvas,a,h,mid,k,off,offset);
  return Object.assign(hand,{time:h.time,canCatch:t-closedAt[i]<175&&t-h.time<110,closed:pinching[i],roll:Math.hypot(p[9].x-p[0].x,(p[9].y-p[0].y)/a.aspect)>.015?Math.atan2(-(p[9].x-p[0].x)*a.aspect,p[0].y-p[9].y):null,tilt:gripLight.orientation(i)?.tilt||0})
 }
 function region(s,point,u){
  return closest(s,point,u,1).gap<=closest(s,point,u,2).gap?1:2
 }
 function attach(s,i,hand,anchor){
  s.grips.push({i,anchor,region:region(s,world(s,anchor,1),1),roll:hand.roll,tilt:hand.tilt,angle:s.angle,seen:hand.time});
  s.fly=false;s.thrown=false;s.flight=false;s.latched=false;s.armedUntil=0;s.closedAt=null;s.placed=false;s.history=[];
  if(s.grips.length===2){s.rest=null;s.strain=0}
 }
 function own(s,g,p,u){
  const q=world(s,g.anchor,u);s.x+=p.x-q.x;s.y+=p.y-q.y
 }
 function release(s,t,u,lost){
  s.flight=true;s.released=t;
  const a=s.history[0],b=s.history[s.history.length-1],dt=b&&a?(b.time-a.time)/1000:0;
  const v=!lost&&dt>.014&&t-b.time<180?1/dt:0;
  s.vx=v?clamp((b.x-a.x)*v,-1000*u,1000*u):0;
  s.vy=v?clamp((b.y-a.y)*v,-1000*u,1000*u):0;s.spin=clamp((v?Math.atan2(Math.sin(b.angle-a.angle),Math.cos(b.angle-a.angle))*v:0)+s.vx/(180*u),-9,9)
  s.thrown=!lost&&Math.hypot(s.vx,s.vy)>=200*u;
  if(!s.part && !s.thrown){
   s.flight=false;s.placed=true;s.x=clamp(s.x,32,928);s.y=clamp(s.y,28,512);
   if(!lost&&propMode==="always"){Object.assign(homes[s.id],{x:s.x,y:s.y,angle:s.angle,flip:s.flip,placed:true});dirty=true}
  }
 }
 function stepFree(s,dt,t,u){
  if(s.flight){
   const art=floatArt[s.id], glass=art.material==='glass';
   const center=art.centers[s.part],pivot={x:center[0],y:center[1]};
   const steps=Math.max(1,Math.ceil(dt*90)),h=dt/steps;
   for(let i=0;i<steps;i++){
    const previous=world(s,pivot,u);
    s.vy+=(glass?690:420)*u*h;
    s.vx*=Math.exp(-h*(glass?.18:.85));
    s.angle+=s.spin*h;
    const rotated=world(s,pivot,u);
    s.x+=previous.x-rotated.x+s.vx*h;s.y+=previous.y-rotated.y+s.vy*h;
    const cosine=Math.cos(s.angle)*u,sine=Math.sin(s.angle)*u;
    let bottom=-Infinity,hit=null;
    for(const [x,y] of art.contours[s.part]){
     const qx=s.x+x*s.flip*cosine-y*sine,qy=s.y+x*s.flip*sine+y*cosine;
     bottom=Math.max(bottom,qy);
     if(s.thrown&&!hit){
      if(qx<=0&&s.vx<0)hit=[0,clamp(qy,0,canvas.height),1,0];
      else if(qx>=canvas.width&&s.vx>0)hit=[canvas.width,clamp(qy,0,canvas.height),-1,0];
      else if(qy<=0&&s.vy<0)hit=[clamp(qx,0,canvas.width),0,0,1];
      else if(qy>=canvas.height-3*u&&s.vy>0)hit=[clamp(qx,0,canvas.width),canvas.height-3*u,0,-1]
     }
    }
    if(hit){
     burst(s,hit,t,u);
     return true
    }
    const depth=bottom-(canvas.height-3*u);
    if(depth>0){
     s.y-=depth;
     if(s.vy>0)s.vy=s.vy>58*u?-s.vy*(glass?.28:.14):0;
     s.vx*=Math.exp(-h*9);s.spin*=Math.exp(-h*13)
     if(!s.part && !s.vy && Math.abs(s.vx)<3*u && Math.abs(s.spin)<.12){s.flight=false;s.placed=true;break}
    }
   }
  }else if(s.fly){
   s.x+=s.dir*118*dt;s.y=s.lane+14*Math.sin((t-s.born)*.0018);
   s.angle=.11*Math.sin((t-s.born)*.0024)
  }else if(!s.placed){
   s.y=s.lane+3*u*Math.sin((t-s.born)*.0012+s.phase);
   s.angle=.045*Math.sin((t-s.born)*.0016+s.phase)
  }
 }
 function burst(s,hit,t,u){
  const [x,y,nx,ny]=hit, art=floatArt[s.id];
  const [left,right,top,bottom]=bounds[s.id][s.part];
  const span=Math.max(right-left,bottom-top)*u;
  const radius=.60*span;
  impacts.push({x,y,nx,ny,t,radius,phase:Math.random()*6});
  commands.push(['impactSound']);
  const index=pieces.indexOf(s);
  pieces.splice(index,1);
  exploded.add(s.id);exclusionsChanged=true;spill(s,x,y,t,u,nx,ny);
  for(let j=0;j<12;j++){
   const a=Math.atan2(ny,nx)+(Math.random()-.5)*2.9,v=(45+Math.random()*135)*u;
   chips.push({x,y,dx:Math.cos(a)*v,dy:Math.sin(a)*v-25*u,angle:a,spin:(Math.random()-.5)*14,
    born:t,u,glass:art.material==='glass',size:1+Math.random()*2})
  }
 }
 function impactCloud(c,e,age){
  const R=e.radius,flash=Math.min(1,age/.26);
  const spread=Math.min(1,flash*1.6);
  const cx=e.x+(clamp(e.x,R,canvas.width-R)-e.x)*spread;
  const cy=e.y+(clamp(e.y,R,canvas.height-R)-e.y)*spread;
  c.save();
  if(flash<1){
   const a=(1-flash);
   c.globalAlpha=a*.94;c.fillStyle='#ffd478';
   c.beginPath();c.arc(cx,cy,R*(.08+.43*flash),0,Math.PI*2);c.fill();
   c.strokeStyle='#ff9954';c.lineWidth=R*(.04+.07*a);
   c.beginPath();c.arc(cx,cy,R*(.16+.84*spread),0,Math.PI*2);c.stroke()
  }
  const rise=1-Math.exp(-4.6*age),fade=Math.min(1,age*16)*Math.min(1,(1-age)*2.2);
  const baseX=clamp(e.x+e.nx*R*.22,.62*R,canvas.width-.62*R);
  const baseY=clamp(e.y+e.ny*R*.22,1.3*R,canvas.height-.16*R);
  const capY=baseY-R*(.15+.82*rise),width=R*(.16+.48*rise);
  c.globalAlpha=fade*.82;c.fillStyle='#907e75';
  c.beginPath();c.moveTo(baseX-R*.22,baseY);
  c.bezierCurveTo(baseX+R*.02,baseY-R*.2,baseX-R*.19,capY+R*.15,baseX-R*.14,capY);
  c.lineTo(baseX+R*.16,capY);
  c.bezierCurveTo(baseX+R*.06,capY+R*.3,baseX+R*.01,baseY-R*.12,baseX+R*.25,baseY);
  c.closePath();c.fill();
  for(let j=-3;j<=3;j++){
   const h=1-Math.abs(j)/4,px=baseX+j*width*.24,py=capY-h*width*.18;
   c.fillStyle=j%2?'#aa9688':'#b8a498';c.beginPath();
   c.arc(px,py,(.23+h*.09)*width,0,Math.PI*2);c.fill()
  }
  c.restore()
 }
 function split(s,hands,t,u){
  const art=floatArt[s.id],f=art.seam,origin=world(s,{x:f[0],y:f[1]},u);
  const glass=art.material==='glass';
  for(let i=0;i<(glass?7:12);i++){
   const a=Math.random()*Math.PI*2,v=(25+Math.random()*83)*u;
   chips.push({x:origin.x,y:origin.y,dx:Math.cos(a)*v,dy:Math.sin(a)*v-45*u,
    angle:a,spin:(Math.random()-.5)*17,born:t,u,glass,size:.8+Math.random()*1.7})
  }
  spill(s,origin.x,origin.y,t,u,0,-1);
  if(propMode==='occasional'){pieces.splice(pieces.indexOf(s),1);return}
  const result=s.grips.map(g=>{
   const part=g.region;
   const piece=Object.assign({},s,{part,grips:[Object.assign({},g,{angle:s.angle,tilt:hands[g.i].tilt})],history:[],contact:0,strain:0,rest:null,seal:0,tension:0,kick:(part===1?-1:1)*(glass?.16:.23),snapped:t,
    warmth:part===1?s.warmth:0});
   own(piece,g,hands[g.i],u);return piece
  });
  due[s.id]=t+3000;
  pieces.splice(pieces.indexOf(s),1,...result)
 }
 function moveHeld(s,hands,t,u){
  const g=s.grips[0],a=hands[g.i];
  if(!a){s.strain=0;return}
  if(s.grips.length===2){
   const other=s.grips[1],b=hands[other.i];if(!b){s.strain=0;return}
   const d=distance(a,b);
   if(s.rest===null)s.rest=d;
   const localAngle=Math.atan2(other.anchor.y-g.anchor.y,(other.anchor.x-g.anchor.x)*s.flip);
   s.angle=Math.atan2(b.y-a.y,b.x-a.x)-localAngle;
   own(s,{anchor:{x:(g.anchor.x+other.anchor.x)/2,y:(g.anchor.y+other.anchor.y)/2}}, {x:(a.x+b.x)/2,y:(a.y+b.y)/2},u);
   const pull=Math.max(0,d-s.rest),threshold=Math.max(24*u,s.rest*.35);
   s.tension=clamp(pull/threshold,0,1);
   if(pull>threshold){
    if(!s.strain)s.strain=t;
    if(t-s.strain>=90 && Math.min(a.time,b.time)>=s.strain){split(s,hands,t,u);return}
   }else s.strain=0
  }else{
   const recoil=s.snapped?(s.kick||0)*Math.exp(-(t-s.snapped)/140)*Math.sin((t-s.snapped)/48):0;
   s.tension=0;
   if(chambers[s.id]&&!s.part){
    if(a.roll!=null&&g.roll!=null)s.angle+=Math.atan2(Math.sin(a.roll-g.roll),Math.cos(a.roll-g.roll));
    g.roll=a.roll
   }else s.angle=g.angle+a.tilt-g.tilt+recoil;
   own(s,g,a,u)
  }
  if(!s.history.length||a.time>s.history[s.history.length-1].time){
   s.history.push({x:s.x,y:s.y,angle:s.angle,time:a.time});
   while(s.history.length>1&&a.time-s.history[0].time>150)s.history.shift()
  }
 }
 function spill(s,x,y,t,u,nx,ny){
  if(!chambers[s.id]||s.part)return;
  const count=Math.ceil(18*s.fill);s.fill=0;
  for(let i=0;i<count;i++){
   const angle=Math.random()*6.283,v=(35+Math.random()*100)*u;
   drops.push({x,y,t,vx:Math.cos(angle)*v+75*u*nx,vy:Math.sin(angle)*v+65*u*ny-55*u,u})
  }
 }
 function water(c,s,dt,u,t){
  const tank=chambers[s.id];if(!tank||s.part||s.fill<=0)return;
  const flow=clamp((-Math.cos(s.angle)-.12)/.88,0,1);
  if(flow>0){
   const amount=Math.min(s.fill,flow*dt*.74);
   s.fill-=amount;s.drip+=amount*52;
   const mouth=floatArt[s.id].mouth,lip=world(s,{x:mouth[0],y:mouth[1]},u);
   while(s.drip>=1){
    s.drip--;drops.push({x:lip.x,y:lip.y,t,u,jet:true,
     vx:(Math.sin(s.angle)*33+(Math.random()-.5)*5)*u,vy:(42+15*flow)*u})
   }
  }
  if(s.fill<=0)return;
  const h=Math.max(.008,dt),velocity=(s.x-s.waterX)/h;
  const impulse=clamp((velocity-s.waterV)*.017/u,-9,9);
  s.waterX=s.x;s.waterV=velocity;
  s.sloshSpeed+=impulse*s.flip;
  s.sloshSpeed+=(-45*s.slosh-6*s.sloshSpeed)*dt;
  s.slosh=clamp(s.slosh+s.sloshSpeed*dt,-7,7);
  const pts=tank.outline;
  if(!tank.mask){
   tank.mask=new Path2D();tank.mask.moveTo(...pts[0]);
   for(let i=1;i<pts.length;i++)tank.mask.lineTo(...pts[i]);
   tank.mask.closePath()
  }
  c.save();c.clip(tank.mask);
  // Counter-rotate the liquid about the chamber center to keep its surface level.
  c.translate(0,tank.y);c.rotate(-s.flip*s.angle+clamp(s.slosh*.14,-.55,.55));
  const tilt=s.flip*s.angle-clamp(s.slosh*.14,-.55,.55);
  if(s.fill<1){
   const sn=Math.sin(tilt),cs=Math.cos(tilt);
   const bottom=Math.max(...pts.map(([x,y])=>x*sn+(y-tank.y)*cs));
   c.translate(0,bottom*(1-s.fill))
  }
  c.fillStyle='rgba(35,135,155,.80)';c.fillRect(-75,0,150,95);
  c.strokeStyle='#a7ebe7';c.lineWidth=1.5;c.beginPath();c.moveTo(-55,0);
  c.quadraticCurveTo(-14,s.slosh,0,0);c.quadraticCurveTo(15,-s.slosh,55,0);c.stroke();c.restore()
 }
 function puff(point,t,u,exhale=false){
  if(exhale&&!mouthSmoke)return;
  if(particles.length>=32)particles.shift();
  particles.push(Object.assign({},point,{time:t,u,phase:Math.random()*6,exhale}))
 }
 function mouthHold(s,t,u,lip,hands){
  const tracked=mode==='auto'&&lastMouth&&lastFace>0&&t-lastFace<210;
  const tip=floatArt[s.id].mouth;
  const anchor={x:tip[0],y:tip[1]},open=expression[2];
  if(s.latched){
   if(!tracked){s.wideAt=null;return}
   s.angle=s.biteAngle+pose.headRoll-s.biteRoll;
   own(s,{anchor},lip,u);
   if(open>=.75){
    if(s.wideAt===null)s.wideAt=lastFace;
    if(lastFace-s.wideAt>=55){
     s.latched=false;s.flight=true;s.placed=false;s.released=t;s.vx=0;s.vy=35*u;s.spin=s.flip*.6;
     s.contact=0;s.seal=0;s.wideAt=null;s.armedUntil=0;s.closedAt=null
    }
   }else s.wideAt=null;
   return
  }
  if(!tracked||s.part||s.grips.length!==1||pieces.some(p=>p.latched)){
   s.armedUntil=0;s.closedAt=null;return
  }
  const i=s.grips[0].i;
  if(!hands[i]||distance(world(s,anchor,u),lip)>32*u){s.closedAt=null;s.armedUntil=0;return}
  if(open>=.20){s.armedUntil=t+750;s.closedAt=null}
  else if(open<=.13&&t<s.armedUntil){
   if(s.closedAt===null)s.closedAt=lastFace;
   if(lastFace-s.closedAt>=45){
    s.latched=true;s.biteAngle=s.angle;s.biteRoll=pose.headRoll;s.wideAt=null;
    blocked[i]=true;s.grips=[];s.history=[];s.seal=0;own(s,{anchor},lip,u)
   }
  }else s.closedAt=null
 }
 function paintProp(s,c,t,dt,u,lip,offsets,hands){
  const art=floatArt[s.id],end=world(s,{x:art.mouth[0],y:art.mouth[1]},u);
  const valid=s.part===0&&s.grips.length===1&&hands[s.grips[0].i]&&lastMouth&&t-lastFace<210;
  const near=(s.latched&&lastMouth&&t-lastFace<210)||valid&&distance(end,lip)<(s.contact?30:21)*u;
  if(near){if(!s.contact)s.contact=t}
  else{
   if(s.contact&&t-s.contact>450&&s.warmth>.45&&lastMouth)puff(lip,t,u,true);
   s.contact=0
  }
  s.seal+=(Number(Boolean(near))-s.seal)*(1-Math.exp(-18*dt));
  const x=s.x,y=s.y;
  if(valid&&s.seal>.01){
   const dx=clamp(lip.x-end.x,-28*u,28*u)*s.seal,dy=clamp(lip.y-end.y,-28*u,28*u)*s.seal;
   s.x+=dx;s.y+=dy;
   const i=s.grips[0].i,old=offsets[i];offsets[i]={x:(old?.x||0)+dx,y:(old?.y||0)+dy}
  }
  const drawing=s.contact&&t-s.contact>140;
  s.warmth+=((drawing?1:0)-s.warmth)*(1-Math.exp(-dt*(drawing?5.8:.98)));
  const opacity=s.flight&&s.part?clamp((6000-(t-s.released))/600,0,1):clamp((t-s.born+32)/200,0,1);
  c.save();c.globalAlpha=opacity;c.translate(s.x,s.y);c.rotate(s.angle);c.scale(s.flip*u,u);
  if(!s.part&&s.tension>.35&&art.material!=='glass'){
   const bend=(s.tension-.35)*.21,fx=art.seam[0],fy=art.seam[1];
   for(const part of [1,2]){
    c.save();c.translate(fx,fy);c.rotate(part===1?bend:-bend);c.translate(-fx,-fy);
    c.floatSprite(s.id,part);c.restore()
   }
  }else c.floatSprite(s.id,s.part);
  water(c,s,dt,u,t);
  if(drawing && ((s.id===1&&s.fill>.1)||s.id===3)){
   const baseX=s.id===1?-2:-17,baseY=s.id===1?35:27;
   for(let i=0;i<4;i++){
    const rise=(t*.0018+i*.27)%1;
    c.strokeStyle='rgba(207,246,240,'+(.68*s.warmth*Math.sin(Math.PI*rise))+')';
    c.lineWidth=.7;c.beginPath();
    c.arc(baseX+(i-1.5)*2+Math.sin(i+rise*5),baseY-rise*8,.8+rise*.9,0,Math.PI*2);c.stroke()
   }
  }
  if(s.part!==2&&s.warmth>.04){
   const [hx,hy]=art.heat,roll=s.id===2||s.id===4;
   const light=s.warmth*(.92+.08*Math.sin(t*.021+s.phase));
   for(let j=0;j<3;j++){
    c.save();c.translate(hx,hy);c.scale(roll?.58:1,roll?1:.53);
    c.fillStyle='rgba('+(j===2?'255,211,109,':j===1?'255,87,18,':'245,61,6,')+light*[.18,.76,.95][j]+')';
    c.beginPath();c.arc(0,0,[12,7,3.4][j],0,Math.PI*2);c.fill();c.restore()
   }
   if(t>=s.nextPuff){puff(world(s,{x:hx,y:hy},u),t,u);s.nextPuff=t+(drawing?105:190)/Math.max(.25,s.warmth)}
  }
  c.restore();
  if(s.grips.length){
   const loop=[];for(const [px,py] of art.contours[s.part])loop.push(24+s.flip*px,24+py);
   for(const g of s.grips)gripLight.record(g.i,[loop],s.x,s.y,48*u,s.angle)
  }
  s.x=x;s.y=y
 }
 function smoke(c,t){
  while(particles.length&&t-particles[0].time>1350)particles.shift();
  if(!particles.length)return;
  c.save();
  for(const p of particles){
   if(p.exhale&&!mouthSmoke)continue;
   const life=(t-p.time)/1350,u=p.u,spread=(p.exhale?2:1),r=(2+life*7)*u*spread;
   const x=p.x+u*life*(9+8*Math.sin(p.phase+life*4)),y=p.y-u*life*(p.exhale?39:54);
   c.beginPath();c.moveTo(x-r*.4,y+r);c.bezierCurveTo(x+r*1.6,y+r*.3,x-r*1.3,y-r*.3,x+r*.2,y-r);
   c.lineWidth=(1.4+3.8*life)*u*spread;c.strokeStyle='rgba(216,224,228,'+(.40*(1-life))+')';c.stroke()
  }
  c.restore()
 }
 function draw(c,canvas,arms,detections,t,k,off,offsets){
  const dt=last===null?0:clamp((t-last)/1000,0,.1),u=k/.4;last=t;
  const lip=stageItems.mouth(canvas,k,off);
  const hands=[0,1].map(i=>sample(arms[i],detections[i],i,t,k,off,offsets[i]));
  if(propMode==='always'){
   for(let id=0;id<homes.length;id++){
    if(!exploded.has(id)&&t>=due[id]&&!pieces.some(s=>s.id===id&&!s.part))spawn(id,t)
   }
  }else if(propMode==='occasional'&&!pieces.length){
   if(!nextFly)nextFly=t+1300;
   if(t>=nextFly){
    const available=homes.map((_,id)=>id).filter(id=>!exploded.has(id));
    if(available.length)spawn(available[Math.floor(Math.random()*available.length)],t);
    nextFly=t+10000+Math.random()*6000
   }
  }
  for(let i=0;i<2;i++)if(hands[i]&&!hands[i].closed)blocked[i]=false;
  for(const s of pieces){
   const had=s.grips.length;
   if(!had)continue;
   const opened=s.grips.some(g=>hands[g.i]&&!hands[g.i].closed);
   s.grips=s.grips.filter(g=>{
    const h=hands[g.i];
    if(h){g.seen=h.time;return h.closed}
    return t-g.seen<210
   });
   if(had===2&&s.grips.length===1){
    const g=s.grips[0];g.angle=s.angle;g.roll=hands[g.i]?.roll;g.tilt=hands[g.i]?.tilt||0;s.history=[]
   }
   if(had&&!s.grips.length)release(s,t,u,!opened)
  }
  for(let i=0;i<2;i++){
   const h=hands[i];
   if(blocked[i]||!h?.closed||!h.canCatch||pieces.some(s=>s.grips.some(g=>g.i===i)))continue;
   let best=null;
   for(const s of pieces){
    const hit=closest(s,h,u,s.part,8);
    if(hit.gap>8||s.grips.length>=2||(s.part&&s.grips.length))continue;
    if(s.grips.length){
     const a=s.grips[0].anchor;
     if(region(s,h,u)===s.grips[0].region||distance(a,hit.p)<20)continue
    }
    if(!best||hit.gap<=best.hit.gap)best={s,hit}
   }
   if(best)attach(best.s,i,h,best.hit.p)
  }
  for(const s of pieces.slice()){
   if(s.grips.length)moveHeld(s,hands,t,u);
   else if(!s.latched&&stepFree(s,dt,t,u))continue;
   mouthHold(s,t,u,lip,hands);
   const edgeMargin=Math.max(80,100*u);
   const offstage=s.x < -edgeMargin || s.x>canvas.width+edgeMargin;
   if(!s.latched&&!s.grips.length&&(offstage||(s.part&&s.flight&&t-s.released>6000))){
    pieces.splice(pieces.indexOf(s),1);if(!s.part)due[s.id]=t+950
   }
  }
  for(const s of pieces)paintProp(s,c,t,dt,u,lip,offsets,hands);
  for(let i=chips.length-1;i>=0;i--){
   const q=chips[i],age=(t-q.born)/1000;
   if(age>.7){chips.splice(i,1);continue}
   c.save();c.translate(q.x+q.dx*age,q.y+q.dy*age+200*q.u*age*age);
   c.rotate(q.angle+age*q.spin);c.scale(q.u*q.size,q.u*q.size);
   c.globalAlpha=clamp((.7-age)*3,0,1);
   c.fillStyle=q.glass?(i%2?'#d3e8ea':'#86b5bb'):(i%2?'#796342':'#ac9154');
   c.beginPath();c.moveTo(-1.6,-.6);c.lineTo(q.glass?2.5:1.3,0);c.lineTo(-.5,1);c.closePath();c.fill();c.restore()
  }
  for(let i=impacts.length-1;i>=0;i--){
   const e=impacts[i],age=(t-e.t)/800;
   if(age>=1){impacts.splice(i,1);continue}
   impactCloud(c,e,Math.max(0,age))
  }
  for(let i=drops.length-1;i>=0;i--){
   const d=drops[i],age=(t-d.t)/1000;
   if(age>.75){drops.splice(i,1);continue}
   c.save();c.globalAlpha=1-age/.75;c.fillStyle="#86d8e4";
   const x=d.x+d.vx*age,y=d.y+d.vy*age+230*d.u*age*age;
   c.beginPath();
   if(d.jet){
    const tail=Math.min(age,.033);
    c.moveTo(x-tail*d.vx,y-tail*(d.vy+460*d.u*age));c.lineTo(x,y);
    c.lineWidth=(2.5-age)*d.u;c.strokeStyle='#83cbdb';c.stroke()
   }else{c.arc(x,y,2*d.u,0,6.283);c.fill()}c.restore()
  }
  smoke(c,t);return pieces.length>0||particles.length>0||chips.length>0||impacts.length>0
 }
 function restoreExclusions(json){
  try{
   const saved=JSON.parse(json);
   if(!['off','always','occasional'].includes(saved.mode)||!Array.isArray(saved.ids))return;
   setMode(saved.mode);
   for(const id of saved.ids)if(Number.isInteger(id)&&id>=0&&id<homes.length)exploded.add(id);
   exclusionsChanged=false
  }catch(e){return}
 }
 function exclusions(){
  if(!exclusionsChanged)return null;
  exclusionsChanged=false;return {mode:propMode,ids:Array.from(exploded)}
 }
 return {draw,reset,restore,changes,setMode,restoreExclusions,exclusions}
})();

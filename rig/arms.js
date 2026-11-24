'use strict';
const doodles=(()=>{
 const canvas=document.getElementById('arms'),ctx=canvas.getContext('2d');
 let enabled=false,showArms=false,showFloating=false,arms=[null,null],hands=[null,null],painted=false;
 const visible=p=>p&&Number.isFinite(p.x+p.y)&&p.x>=0&&p.x<=1&&p.y>=0&&p.y<=1;
 const confident=p=>visible(p)&&(p.visibility??0)>=.65;
 let stability=.65,previousArms=[null,null],previousHands=[null,null];
 function reset(){ninjaFight.reset();if(typeof floatingProps!=="undefined")floatingProps.reset();arms=[null,null];hands=[null,null];previousArms=[null,null];previousHands=[null,null]}
 function toggle(armsOn,floatingOn=false,percent=65){
  stability=Math.max(0,Math.min(100,percent))/100;
  if(armsOn===showArms&&floatingOn===showFloating)return;
  showArms=armsOn;showFloating=floatingOn;enabled=showArms||showFloating;reset()
 }
 function smooth(p,old,dt,span,aspect){
  if(!p||!old||dt<=0||dt>180)return p;
  const speed=Math.hypot(p.x-old.x,(p.y-old.y)/aspect)/span/(dt/1000);
  const rate=21+Math.min(165,95*speed);
  const distance=speed*dt*.001;
  // Small deviations get a longer time constant. Large reaches keep the original response.
  const quiet=Math.max(0,1-distance/.15);
  const gain=-Math.expm1(-dt*.001*rate/(1+7*stability*quiet*quiet));
  // Attenuate sub-palm tremor; deliberate reaches retain their high gain.
  const steady=1-stability*.87*Math.exp(-Math.pow(distance/.058,2));
  const q=Object.assign({},p,{x:old.x+(p.x-old.x)*gain*steady,y:old.y+(p.y-old.y)*gain*steady});
  if(stability && Number.isFinite(p.z) && Number.isFinite(old.z)){
   const depthGain=Math.max(gain,Math.min(1,Math.abs(p.z-old.z)/(span*.25)));
   q.z=p.z+stability*(old.z-p.z)*(1-depthGain)
  }
  return q
 }
 function observe(points,aspect,time){
  if(!enabled)return;
  const shoulders=[points?.[11],points?.[12]];
  const paired=shoulders.every(confident);
  const measured=paired?Math.hypot(shoulders[0].x-shoulders[1].x,(shoulders[0].y-shoulders[1].y)/aspect):0;
  previousArms=arms;
  arms=shoulders.map((root,i)=>{
   const prev=arms[i],dt=time-(prev?.time??0);
   const recent=prev&&dt>=0&&dt<160;
   const accept=(p,old)=>visible(p)&&(p.visibility??0)>=((recent && old) ? .45 : .60);
   const elbow=points?.[13+i],wrist=points?.[15+i];
   const e=accept(elbow,prev?.elbow),w=accept(wrist,prev?.wrist);
   if(!accept(root,prev?.root)||(!e&&!w)){
    if(recent)return prev;
    hands[i]=null;return null
   }
   let span=measured>=.065?measured:(prev?.span??.30);
   if(stability&&recent&&measured>=.065){
    const gain=-Math.expm1(-dt/(110*stability));
    span=prev.span+(span-prev.span)*gain
   }
   const elbowTime=e?time:(prev?.elbowTime??-1000);
   const heldElbow=stability&&prev?.elbow&&time-elbowTime<120*stability?prev.elbow:null;
   const side=measured>=.065?(root.x<shoulders[1-i].x?1:-1):(prev?.side??(i===0?1:-1));
   const wristTime=w?time:(prev?.wristTime??-1000);
   const carry=!w&&prev?.wrist&&time-wristTime<180;

   return {root:smooth(root,prev?.root,dt,span,aspect),elbow:e?smooth(elbow,prev?.elbow,dt,span,aspect):heldElbow,elbowTime,wrist:w?smooth(wrist,prev?.wrist,dt,span,aspect):(carry?prev.wrist:null),wristTime,
    side,span,aspect,time}
  })
 }
 function match(detections,time){
  const previous=hands;previousHands=hands;hands=[null,null];
  if(!enabled)return;
  const valid=detections.filter(h=>h?.length===21&&visible(h[0])).slice(0,2);
  // Choose a one-to-one assignment, even when the wrists cross in the image.
  let best=Infinity,assignment=[-1,-1];
  for(let i=-1;i<valid.length;i++)for(let j=-1;j<valid.length;j++){
   if(i>=0&&i===j)continue;
   const pair=[i,j];let cost=0;
   for(let side=0;side<2;side++){
    if(pair[side]<0){cost+=1;continue}
    const a=arms[side],p=valid[pair[side]][0];
    if(!a||Math.abs(a.time-time)>200){cost=Infinity;break}
    const old=previous[side],recent=old&&time-old.time<160;
    let ref=a.wrist;
    if(!ref&&recent)ref=old.points[0];
    if(!ref&&a.elbow)ref={x:a.elbow.x+.65*(a.elbow.x-a.root.x),y:a.elbow.y+.65*(a.elbow.y-a.root.y)};
    if(!ref){cost=Infinity;break}
    const d=Math.hypot(p.x-ref.x,(p.y-ref.y)/a.aspect)/a.span;
    if(d>(a.wrist ? .65 : .90)){cost=Infinity;break}cost+=d;
    if(recent)cost+=.25*Math.min(1,Math.hypot(p.x-old.points[0].x,(p.y-old.points[0].y)/a.aspect)/a.span)
   }
   if(cost<best){best=cost;assignment=pair}
  }
  hands=assignment.map((index,side)=>{
   const old=previous[side],arm=arms[side];
   if(index<0)return arm&&old&&time-old.time<105&&!valid.some(p=>Math.hypot(p[0].x-old.points[0].x,(p[0].y-old.points[0].y)/arm.aspect)<arm.span*.30)?old:null;
   const points=valid[index].map((p,j)=>visible(p)?smooth(p,old?.points[j],time-(old?.time??0),arm.span,arm.aspect):p);
   if(!arm.wrist||time-arm.wristTime>65){
    arm.wrist={x:points[0].x,y:points[0].y,z:arm.elbow?.z??arm.root.z};arm.wristTime=time
   }
   return {points,time}
  })
 }
 function curve(a,b,bow){
  const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy);
  if(len<.01)return;
  ctx.quadraticCurveTo((a.x+b.x)/2-bow*dy/len,(a.y+b.y)/2+bow*dx/len,b.x,b.y)
 }
 function ink(width){ctx.lineJoin='round';ctx.lineCap='round';ctx.lineWidth=width+2.2;ctx.strokeStyle='#201a18';ctx.stroke();ctx.lineWidth=width;ctx.strokeStyle='#e6ac8b';ctx.stroke()}
 function between(a,b,f){
  if(!a||!b||f>=1)return b;
  return Object.assign({},b,{x:a.x+(b.x-a.x)*f,y:a.y+(b.y-a.y)*f,z:Number.isFinite(a.z)&&Number.isFinite(b.z)?a.z+(b.z-a.z)*f:b.z})
 }
 function draw(now,fight,paint=true){
  if(!enabled)return;
  const blend=(a,b)=>a&&b&&b.time>a.time&&b.time-a.time<135&&stability?
   clamp(.20+(now-b.time)/Math.min(32*stability,b.time-a.time),0,1):1;
  const drawArms=arms.map((b,i)=>{
   const a=previousArms[i],f=blend(a,b);
   return f===1?b:Object.assign({},b,{root:between(a.root,b.root,f),elbow:between(a.elbow,b.elbow,f),wrist:between(a.wrist,b.wrist,f)})
  });
  const drawHands=hands.map((b,i)=>{
   const a=previousHands[i],f=blend(a,b);
   return f===1?b:Object.assign({},b,{points:b.points.map((p,j)=>between(a.points[j],p,f)),gesture:b.points})
  });
  drawPose(now,fight,paint,drawArms,drawHands)
 }
 function drawPose(now,fight,paint,arms,hands){
  if(painted){ctx.clearRect(0,0,canvas.width,canvas.height);painted=false}
  if(!enabled&&!showFloating)return;
  const close=el('framing').selectedIndex===1,k=pose.scale*(close?.61:.40),off=close?.04:-.12;
  gripLight.begin(hands,now);
  
  const offsets=[];
  if(showFloating&&floatingProps.draw(ctx,canvas,arms,hands,now,k,off,offsets))painted=true;
  if(fight){
   const points=arms.map((a,i)=>{
    if(!a?.wrist||now-a.wristTime>190)return null;
    const h=hands[i],usePalm=h&&now-h.time<175&&visible(h.points[9]);
    const p=usePalm?stageItems.finger(canvas,a,h,h.points[9],k,off):stageItems.point(canvas,a,a.wrist,k,off);
    if(offsets[i]){p.x+=offsets[i].x;p.y+=offsets[i].y}
    p.source=usePalm?1:0;p.stamp=usePalm?h.time:a.wristTime;
    return p
   });
   ninjaFight.step(now,points,stageItems.mouth(canvas,k,off))
  }
  if(!showArms||!paint)return;
  for(let i=0;i<2;i++){
   const a=arms[i];if(!a||now-a.time>200)continue;
   const shoulder=rotate([a.side*.38,-1.12,.06],pose.pitch,pose.yaw,pose.roll);
   const root={x:canvas.width/2+(pose.x+shoulder[0])*k*canvas.height/2,y:(1-off-(pose.y+shoulder[1])*k)*canvas.height/2};
   const point=p=>stageItems.point(canvas,a,p,k,off);
   const palm=hands[i];
   const w=a.wrist&&(palm&&now-palm.time<190?stageItems.finger(canvas,a,palm,palm.points[0],k,off):point(a.wrist));if(w&&offsets?.[i]){w.x+=offsets[i].x;w.y+=offsets[i].y}
   const surfaces=gripLight.surfaces[i];
   if(surfaces.length){ctx.save();for(const surface of surfaces)ctx.clip(surface.outside,'evenodd')}
   if(a.elbow){const e=point(a.elbow);ctx.beginPath();ctx.moveTo(root.x,root.y);if(w){
    const before={x:e.x+(root.x-e.x)*.09,y:e.y+(root.y-e.y)*.09};
    const after={x:e.x+(w.x-e.x)*.09,y:e.y+(w.y-e.y)*.09};
    curve(root,before,i?1:-1);ctx.quadraticCurveTo(e.x,e.y,after.x,after.y);curve(after,w,i?-1:1)
   }else curve(root,e,1);ink((close?9:7)*pose.scale);painted=true}
   else if(w){
    ctx.beginPath();ctx.moveTo(root.x,root.y);
    curve(root,w,a.side*Math.min(15,Math.hypot(w.x-root.x,w.y-root.y)*.12));
    ink((close?9:7)*pose.scale);painted=true
   }
   const h=hands[i];if(!w||!h||now-h.time>190){if(surfaces.length)ctx.restore();continue}
   const projected=[];
   const finger=id=>projected[id]||(projected[id]=stageItems.finger(canvas,a,h,h.points[id],k,off,offsets[i]));
   const palmIds=[0,5,9,13,17];
   if(palmIds.every(id=>visible(h.points[id]))){
    ctx.beginPath();
    for(const [j,id] of palmIds.entries()){
     const q=finger(id);if(j)ctx.lineTo(q.x,q.y);else ctx.moveTo(q.x,q.y)
    }
    ctx.closePath();ctx.fillStyle='#e6ac8b';ctx.fill()
   }
   ctx.beginPath();
   for(const chain of [[0,5,9,13,17,0],[0,1,2,3,4],[5,6,7,8],[9,10,11,12],[13,14,15,16],[17,18,19,20]]){
    let prev=null;for(const id of chain){const p=h.points[id];if(!visible(p)){prev=null;continue}
     const q=finger(id);if(prev){ctx.quadraticCurveTo(prev.x,prev.y,(prev.x+q.x)/2,(prev.y+q.y)/2)}else ctx.moveTo(q.x,q.y);prev=q}if(prev)ctx.lineTo(prev.x,prev.y)
   }
   const width=(close?4.3:3.6)*pose.scale;ink(width);painted=true;
   if(surfaces.length){
    ctx.restore();
    // Compare fingertip depth to the palm plane. Only the closer phalanges
    // reappear across the object. The same silhouette clips their shadow.
    const pts=h.points,palm=(pts[5].z+pts[9].z+pts[17].z)/3;
    const span=Math.max(.008,Math.hypot(pts[5].x-pts[17].x,pts[5].y-pts[17].y));
    const front=new Path2D();let count=0;
    for(const tip of [4,8,12,16,20]){
     for(let j=tip-1;j<=tip;j++){
      const u=pts[j-1],v=pts[j];if(!visible(u)||!visible(v)||(u.z+v.z)*.5>palm-.035*span||!Number.isFinite(v.z+u.z))continue;
      const a=finger(j-1),b=finger(j);front.moveTo(a.x,a.y);front.lineTo(b.x,b.y);count++
     }
    }
    if(count)for(const surface of surfaces){
     commands.push(['gripFront',surface.path.ops,front.ops,width])
    }
   }
  }
 }
 return {toggle,reset,observe,match,draw}
})();

// Fight positions and hand sweeps use the same 960 x 540 stage as the arm ink.
const ninjaFight=(()=>{
 let enemies=[],previous=[null,null],last=0,next=0,hits=0,active=false;
 function reset(){
  enemies=[];previous=[null,null];last=next=hits=0;active=false
 }
 function swept(a,b,x,y){
  const dx=b.x-a.x,dy=b.y-a.y,len=dx*dx+dy*dy;
  const u=len?clamp(((x-a.x)*dx+(y-a.y)*dy)/len,0,1):0;
  return Math.hypot(a.x+u*dx-x,a.y+u*dy-y)
 }
 function step(now,points,target){
  if(!active){active=true;next=.2;last=now}
  const dt=clamp((now-last)/1000,0,.075);last=now;
  const tracked=points.some(Boolean);
  const swings=points.map((p,i)=>{
   const old=previous[i];
   if(!p){previous[i]=null;return null}
   if(old&&old.stamp===p.stamp)return null;
   previous[i]=p;
   if(!old||old.source!==p.source)return null;
   const gap=p.stamp-old.stamp,d=Math.hypot(p.x-old.x,p.y-old.y);
   return gap>0&&gap<=200&&d>=5&&d<260&&d*1000/gap>=130?[old,p]:null
  });
  if(tracked){
   next-=dt;
   if(next<=0&&enemies.length<3){
    const side=Math.random()<.5?1:-1;
    const kind=Math.floor(Math.random()*3);
    enemies.push({x:side===1?-70:1030,y:clamp(target.y+45+Math.random()*60,95,464),
     side,kind,age:0,jump:-1,fly:0,step:0,tilt:0,span:135});
    next=1.6+Math.random()*.85
   }
  }
  const tx=clamp(target.x,85,875),ty=clamp(target.y+15,75,465);
  enemies=enemies.filter(e=>{
   if(e.fly){
    e.fly+=dt;e.x-=e.side*460*dt;e.y+=(-275+640*e.fly)*dt;
    if(e.fly>.52)return false
   }else if(tracked){
    e.age+=dt;
    if(e.jump<0){
     const dx=tx-e.x,dy=ty+28-e.y,dist=Math.max(1,Math.hypot(dx,dy));
     const stride=Math.min(dist,dt*(165+Math.min(40,hits*2)));
     e.x+=dx/dist*stride;e.y+=dy/dist*stride;
     e.step=Math.floor(e.age*6)%2;e.tilt=3*Math.sin(e.age*12);
     if(dist<215){
      e.jump=0;e.fromX=e.x;e.fromY=e.y;e.toX=tx;e.toY=ty;
      commands.push(['ninjaSound',['kick','punch','blade'][e.kind]])
     }
    }
    if(e.jump>=0){
     e.jump=Math.min(1,e.jump+dt/(e.kind===2?.81:.72));
     const u=e.jump,arc=Math.sin(Math.PI*u);
     e.x=e.fromX+(e.toX-e.fromX)*u;e.y=e.fromY+(e.toY-e.fromY)*u-(e.kind===0?81:53)*arc;
     e.span=135+21*arc;e.tilt=(e.kind===2?-9:5)*arc;
     e.step=2+2*e.kind+(u>.35?1:0)
    }
    const extended=e.jump>.35;
    if(swings.some(s=>s&&(swept(s[0],s[1],e.x,e.y)<e.span*.30||
       (extended&&swept(s[0],s[1],e.x+e.side*e.span*.30,e.y)<e.span*.17)))){
     hits++;e.fly=.001;commands.push(['ninjaSound',hits%2?'strike':'strike2'])
    }else if(e.jump===1){
     commands.push(['ninjaSound','miss']);return false
    }
   }
   commands.push(['ninjaSprite',e.x,e.y,e.side,e.step,e.fly,e.tilt,e.span]);return true
  })
 }
 return {step,reset}
})();

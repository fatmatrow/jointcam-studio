'use strict';
const gripLight=(()=>{
 const surfaces=[[],[]],angles=[null,null];
 let poses,clock;
 function begin(hands,time){poses=hands;clock=time;for(const list of surfaces)list.length=0}
 function orientation(owner){
  const h=poses?.[owner],p=h?.points;
  if(!p||clock-h.time>190){angles[owner]=null;return null}
  const width=Math.hypot(p[5].x-p[17].x,p[5].y-p[17].y);
  if(width<.009||!Number.isFinite(p[5].z+p[17].z))return null;
  const spin=Math.max(-1,Math.min(1,(p[17].z-p[5].z)/width));
  const tilt=Math.max(-.72,Math.min(.72,Math.atan2(p[0].x-p[9].x,Math.max(.015,p[0].y-p[9].y))));
  const prev=angles[owner],gain=prev?1-Math.exp(-Math.max(0,clock-prev.t)*.045):1;
  return angles[owner]={t:clock,spin:prev?prev.spin+gain*(spin-prev.spin):spin,tilt:prev?prev.tilt+gain*(tilt-prev.tilt):tilt}
 }
 function record(owner,loops,x,y,size,angle){
  if(!poses?.[owner]||clock-poses[owner].time>190)return;
  const path=new Path2D(),c=Math.cos(angle)*size/48,s=Math.sin(angle)*size/48;
  for(const loop of loops){
   for(let j=0;j<loop.length;j+=2){const u=loop[j]-24,v=loop[j+1]-24;
    if(j)path.lineTo(x+c*u-s*v,y+s*u+c*v);else path.moveTo(x+c*u-s*v,y+s*u+c*v)
   }path.closePath()
  }
  const outside=new Path2D();outside.rect(-10,-10,980,560);outside.addPath(path);
  surfaces[owner].push({path,outside})
 }
 return {begin,orientation,record,surfaces}
})();

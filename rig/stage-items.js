'use strict';
let avatarMouth=null;
const stageItems=(()=>{
 // All projected fingers on an arm share the same shoulder transform.
 let lastArm=null, transform=null;
 function point(canvas,a,p,k,off){
  let tr=transform;
  if(a!==lastArm||!tr||tr.pose!==pose||tr.k!==k||tr.off!==off||tr.canvas!==canvas){
   const unit=k*canvas.height/2,r=rotate([a.side*.38,-1.12,.06],pose.pitch,pose.yaw,pose.roll);
   tr={pose,k,off,canvas,s:unit*1.12/Math.max(.12,a.span),x:canvas.width/2+(pose.x+r[0])*unit,
       y:(1-off)*canvas.height/2-(pose.y+r[1])*unit,
       ca:Math.cos(pose.cameraAngle||0),sa:Math.sin(pose.cameraAngle||0),
       ct:Math.cos(pose.cameraTilt||0),st:Math.sin(pose.cameraTilt||0)};
   lastArm=a;transform=tr
  }
  const angle=pose.cameraAngle||0,dx=p.x-a.root.x,dz=(p.z??a.wrist?.z??a.root.z)-a.root.z;
  const reach=angle?(dx*tr.ca+(Number.isFinite(dz)?dz:0)*tr.sa)*tr.ca:dx;
  const tilt=pose.cameraTilt||0,dy=(p.y-a.root.y)/a.aspect;
  const vertical=tilt&&Number.isFinite(dz)?dy*tr.ct+dz*tr.st:dy;
  return {x:tr.x-reach*tr.s,y:tr.y+vertical*tr.s}
 }
 // The hand detector and pose detector can disagree on wrist position.
 // Both interaction and ink use this same wrist-relative projection.
 function finger(canvas,a,h,p,k,off,offset){
  const wrist=a.wrist||h.points[0],base=h.points[0];
  const q=point(canvas,a,{x:.30*wrist.x+.70*base.x+p.x-base.x,y:.30*wrist.y+.70*base.y+p.y-base.y,z:wrist.z+(p.z??base.z)-base.z},k,off);
  if(offset){q.x+=offset.x;q.y+=offset.y}
  return q
 }
 function mouth(canvas,k,off){
  if(avatarMouth)return {x:avatarMouth[0],y:avatarMouth[1]};
  const jaw=Math.max(0,expression[2]-.08),head=rotate([.075,.485-.12*jaw,.43+.09*jaw],pose.headPitch,pose.headYaw,pose.headRoll);
  const p=rotate([head[0],head[1]-1.05,head[2]],pose.pitch,pose.yaw,pose.roll),unit=k*canvas.height/2;
  return {x:canvas.width/2+(p[0]+pose.x)*unit,y:(1-off)*canvas.height/2-(p[1]+pose.y)*unit}
 }
 return {point,finger,mouth}
})();

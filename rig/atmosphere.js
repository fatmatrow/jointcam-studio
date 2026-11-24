// Accessories share the head and shoulder transforms used by the avatar.
const breathPuffs=[];
let nextExhale=0,priorLip=null;
function drawAtmosphere(s){
 const c=context,k=pose.scale*(closeup?.61:.40),off=closeup?.04:-.12,unit=k*270;
 const style=s.wardrobe||{},lip=s.anchors?{x:s.anchors.mouth[0],y:s.anchors.mouth[1]}:stageItems.mouth(canvas,k,off);
 const project=(x,y,z,head)=>{
  let v=head?rotate([x,y+1.05,z],pose.headPitch,pose.headYaw,pose.headRoll):[x,y,z];
  if(head)v[1]-=1.05;
  v=rotate(v,pose.pitch,pose.yaw,pose.roll);
  return [480+(pose.x+v[0])*unit,(1-off)*270-(pose.y+v[1])*unit]
 };
 function place(x,y,z,head,key){
  if(s.anchors){
   c.translate(...s.anchors[key]);c.rotate(s.anchors.angle);c.scale(s.anchors.scale,s.anchors.scale);return
  }
  c.translate(...project(x,y,z,head));c.rotate(-pose.roll-(head?pose.headRoll:0));
  c.scale(unit/106*(head?Math.max(.65,Math.cos(pose.headYaw)):1),unit/106)
 }
 function polygon(points,fill,edge){
  c.beginPath();c.moveTo(...points[0]);for(const point of points.slice(1))c.lineTo(...point);
  c.closePath();c.fillStyle=fill;c.fill();if(edge){c.strokeStyle=edge;c.lineWidth=1.6;c.stroke()}
 }
 function disc(x,y,r,color){c.fillStyle=color;c.beginPath();c.arc(x,y,r,0,Math.PI*2);c.fill()}
 if(!s.soundOnly){
 const beat=s.time*.003;
 if(style.eyewear==='googly'||style.eyewear==='pixel'){
  c.save();place(.024,-.19,.41,true,"eye");
  c.fillStyle='#29272a';c.fillRect(-43,-5,86,6);
  for(const x of [-21,21]){
   if(style.eyewear==='googly'){
    disc(x,0,18,'#33363c');disc(x,0,15,'#f5f2e6');
    const dx=5*Math.sin(beat+x*.03)+3*Math.sin(pose.headRoll*3);
    disc(x+dx,3+3*Math.cos(beat*1.1),7,'#201e24');disc(x+dx-2,2,2,'#ffffff')
   }else{
    polygon([[x-20,-9],[x+19,-9],[x+19,1],[x+14,1],[x+14,6],[x+9,6],[x+9,10],[x-10,10],[x-10,6],[x-16,6],[x-16,1],[x-20,1]],'#181926');
    c.fillStyle='#d7eaf1';for(let j=0;j<3;j++)c.fillRect(x-13+j*4,-7+j*4,4,4)
   }
  }c.restore()
 }
 if(style.hat==='propeller'||style.hat==='cone'){
  c.save();place(-.12,1.78,.10,true,"hat");
  if(style.hat==='cone'){
   polygon([[-32,3],[-4,-58],[5,-58],[32,3]],'#fa7236','#713727');
   polygon([[-19,-24],[19,-24],[14,-35],[-14,-35]],'#fff1d0');
   polygon([[-43,3],[33,-1],[44,7],[-32,12]],'#e35825','#713727')
  }else{
   c.beginPath();c.moveTo(-36,5);c.bezierCurveTo(-36,-37,36,-37,36,5);c.closePath();c.fillStyle='#f8bf3f';c.fill();
   polygon([[-14,4],[-7,-19],[0,-25],[6,-19],[13,4]],'#e15a48');
   c.fillStyle='#328889';c.fillRect(-36,1,72,8);c.fillStyle='#59454a';c.fillRect(-2,-36,4,13);
   c.save();c.translate(0,-36);c.scale(1,.30);c.rotate(beat*3);
   for(const col of ['#79cce4','#f45e69']){polygon([[0,0],[20,-8],[37,-3],[27,4],[5,4]],col);c.rotate(Math.PI)}c.restore();disc(0,-36,3,'#ffe687')
  }c.restore()
 }
 if(style.jewelry==='bow'||style.jewelry==='pizza'){
  c.save();place(0,-.98,.4,false,"chest");
  if(style.jewelry==='bow'){
   c.translate(0,9);c.rotate(beat*1.5);for(let j=0;j<2;j++){
    polygon([[0,0],[23,-12],[26,12]],'#dc4775','#643044');disc(17,-2,2,'#ffdb9e');c.rotate(Math.PI)
   }disc(0,0,5,'#f6bf51')
  }else{
   c.strokeStyle='#cba157';c.lineWidth=2;c.beginPath();c.moveTo(-33,0);c.quadraticCurveTo(-2,40,33,0);c.stroke();
   polygon([[-13,19],[14,18],[4,46]],'#ffce53','#8c4c2f');polygon([[-15,15],[15,14],[15,21],[-13,23]],'#bd793f');
   for(const [x,y] of [[-6,25],[6,28],[2,36]])disc(x,y,2.7,'#bd4b36')
  }c.restore()
 }
 if(['round','aviators'].includes(style.eyewear)){
  c.save();place(.024,-.19,.41,true,"eye");
  const round=style.eyewear==='round';c.strokeStyle=round?'#dbbe80':'#bea475';c.lineWidth=2.1;
  for(const x of [-21,21]){
   c.beginPath();if(round)c.arc(x,0,15,0,6.283);else c.roundRect(x-18,-11,36,25,9);
   c.fillStyle=round?'rgba(92,135,145,.15)':'rgba(109,65,31,.73)';c.fill();c.stroke()
  }
  c.beginPath();c.moveTo(-6,-2);c.quadraticCurveTo(0,-8,6,-2);c.stroke();c.restore()
 }
 if(['cap','beanie'].includes(style.hat)){
  const cap=style.hat==='cap';c.save();place(-.12,1.78,.10,true,"hat");
  c.fillStyle=cap?'#273844':'#725247';c.strokeStyle='#332f31';c.lineWidth=2;
  c.beginPath();c.moveTo(-38,3);c.bezierCurveTo(-38,-52,34,-53,38,4);c.closePath();c.fill();c.stroke();
  c.beginPath();c.roundRect(-39,-4,78,14,4);c.fillStyle=cap?'#354c56':'#926e5c';c.fill();c.stroke();
  if(cap){c.beginPath();c.moveTo(1,5);c.quadraticCurveTo(44,0,57,10);c.quadraticCurveTo(46,18,1,10);c.fill();c.stroke()}
  else{c.strokeStyle='#654b40';c.lineWidth=1;for(let x=-34;x<38;x+=6){c.beginPath();c.moveTo(x,-2);c.lineTo(x+1,7);c.stroke()}}
  c.restore()
 }
 if(['chain','pendant'].includes(style.jewelry)){
  c.save();place(0,-.98,.4,false,"chest");const silver=style.jewelry==='pendant';
  c.strokeStyle=silver?'#dce3e3':'#d3aa59';c.lineWidth=silver?2:3.7;
  c.beginPath();c.moveTo(-36,0);c.quadraticCurveTo(-4,47,36,0);c.stroke();
  if(silver){c.beginPath();c.roundRect(-4,22,8,12,2);c.fillStyle='#a4bcc2';c.fill()}c.restore()
 }
 if(s.costume)commands.push(['karateCostume',s.costume,s.open,pose.headPitch,s.time/1000]);
 }
 if(!mouthSmoke){breathPuffs.length=0;priorLip=null;return}
 if(s.mouth&&s.breath>.16&&s.time>=nextExhale){
  const elapsed=priorLip?Math.max(16,s.time-priorLip.t):33;
  const motion=priorLip?clamp((lip.x-priorLip.x)*1000/elapsed,-150,150):0;
  const openness=clamp(s.open,0,1);
  breathPuffs.push({x:lip.x,y:lip.y,t:s.time,dx:motion*.30+pose.headYaw*50+(Math.random()-.5)*16,
   rise:19+Math.random()*17+openness*20,phase:Math.random()*6,size:unit*(.045+.07*openness),power:s.breath});
  nextExhale=s.time+75+Math.random()*55
 }
 priorLip={x:lip.x,t:s.time};
 for(let i=breathPuffs.length-1;i>=0;i--){
  const p=breathPuffs[i],age=(s.time-p.t)/1200;if(age>=1){breathPuffs.splice(i,1);continue}
  if(s.soundOnly)continue;
  const x=p.x+p.dx*age+Math.sin(age*5+p.phase)*age*9,y=p.y-p.rise*age,r=p.size*(.3+age*1.9);
  const circles=[];
  for(let j=0;j<3;j++)circles.push(x+Math.sin(p.phase+j)*r*.45,y+Math.cos(p.phase+j)*r*.3,r*(1-.18*j));
  commands.push(['breathPuff',.12*p.power*(1-age),...circles])
 }
}

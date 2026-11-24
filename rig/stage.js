const stageFX=(()=>{
 const canvas=document.getElementById('fx'),ctx=canvas.getContext('2d'),pool=[];let running=false,last=0;
 const colors=['#ffc448','#ff617b','#67e8d6','#8b78ff','#fff2cc'];
 function start(type){if(!Number.isInteger(type)||type<0||type>4)return;
  const n=[104,52,48,2+Math.floor(Math.random()*6),14+Math.floor(Math.random()*14)][type],now=performance.now()/1000;
  const origin=typeof smokeOrigin==='function'?smokeOrigin():[.5,.25];
  if(pool.length+n>230)pool.splice(0,pool.length+n-230);
  for(let i=0;i<n;i++){let r=Math.random(),angle=Math.random()*Math.PI*2;
   let x,y,dx,dy;if(type===0){x=i%2?-.02:1.02;y=.83;dx=(i%2?1:-1)*(.16+.42*r);dy=-.56-Math.random()*.81}
   else if(type===1){[x,y]=origin;dx=Math.cos(angle)*(.08+.21*r);dy=-.20-Math.random()*.45}
   else if(type>=3){
    [x,y]=origin;
    const force=type===4?1:.36;
    dx=(Math.random()-.5)*.41*force;dy=-(.018+Math.random()*.23)*force
   }
   else{x=Math.random();y=-.03-Math.random()*.28;dx=-.08-.12*r;dy=.22+.30*r}
   pool.push({type,x,y,dx,dy,age:0,life:type>=3?.65+Math.random()*1.25:type===1?.48+.75*r:2.0+1.35*r,spin:angle,speed:(r-.5)*12,size:type===1?1.5+2*r:3+4*r,color:type>=3?(type===4&&r>.82?'#ff9950':['#a4998b','#746e68','#c2b8a8'][Math.floor(Math.random()*3)]):type===1?(i%2?'#ff944d':'#ffe9ae'):colors[i%5]})}
  if(!running){running=true;last=now;requestAnimationFrame(draw)}
 }
 function draw(ms){let t=ms/1000,dt=Math.max(0,t-last);last=t;ctx.clearRect(0,0,canvas.width,canvas.height);
  for(let i=pool.length-1;i>=0;i--){let p=pool[i];p.age+=dt;if(p.age>=p.life){pool.splice(i,1);continue}
   if(p.type>=3)p.dx+=Math.sin(t*5+p.speed)*.019*dt;
   p.dy+=dt*(p.type>=3?.26:p.type===0?.64:p.type===1?.38:.035);p.x+=p.dx*dt;p.y+=p.dy*dt;p.spin+=p.speed*dt;
   if(!paintEffects)continue;
   const alpha=Math.min(1,(p.life-p.age)*2.7);
   const stretch=p.type===0?Math.cos(p.spin):p.type>=3?.45+.55*Math.abs(Math.cos(p.spin)):1;
   const turn=p.type===1?Math.atan2(p.dy*canvas.height,p.dx*canvas.width)-p.spin:0;
   const tint=p.type===1?(p.age<p.life*.25?'#ffda8b':p.age<p.life*.62?'#ff943c':'#c2582c'):p.color;
   commands.push(['stageParticle',p.type,p.x*canvas.width,p.y*canvas.height,p.spin,alpha,stretch,turn,tint,p.size])}

  if(pool.length)requestAnimationFrame(draw);else running=false
 }
 return {start};
})();

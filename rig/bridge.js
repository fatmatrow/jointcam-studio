// Record vector operations for the native Qt painter. Pictures stay on the host.
let mouthSmoke=true;
let commands=[],nowMS=0,queue=[],pose={},lastFace=-1000,lastMouth=null,mode="auto",expression=[1,1,.5],origin=[.5,.2];
const performance={now:()=>nowMS},requestAnimationFrame=f=>queue.push(f);
const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
const smokeOrigin=()=>origin;
const rotate=([x,y,z],p,a,r)=>{const u=y*Math.cos(p)-z*Math.sin(p),v=z*Math.cos(p)+y*Math.sin(p),w=x*Math.cos(a)+v*Math.sin(a);return [w*Math.cos(r)-u*Math.sin(r),u*Math.cos(r)+w*Math.sin(r),v*Math.cos(a)-x*Math.sin(a)]};
class Path2D {
 constructor(){this.ops=[]}
 addPath(p){this.ops.push(...p.ops)}
}
for(const op of ['rect','moveTo','lineTo','closePath'])Path2D.prototype[op]=function(...a){this.ops.push([op,...a])};
let context={};
// The native painter fixes joins and caps to round and centers text itself.
for(const name of ['lineWidth','strokeStyle','fillStyle','globalAlpha','font']){
 Object.defineProperty(context,name,{set(v){commands.push([name,v])}})
}
for(const name of ['beginPath','closePath','moveTo','lineTo','roundRect','arc','quadraticCurveTo','bezierCurveTo','fill','fillRect','fillText','strokeText','translate','rotate','scale','save','restore'])
 context[name]=(...args)=>commands.push([name,...args]);
context.stroke=p=>commands.push(['stroke',p?p.ops:null]);
context.clip=p=>commands.push(['clip',p.ops]);
context.clearRect=()=>{};
context.floatSprite=(row,part)=>commands.push(['floatSprite',row,part]);
const canvas={width:960,height:540,getContext:()=>context};
let closeup=false;
const document={getElementById:()=>canvas},el=id=>({selectedIndex:closeup?1:0});

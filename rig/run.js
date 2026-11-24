let paintEffects=true;
let lastBody=-1,lastHand=-1,fighting=false;
function renderOverlay(state){
 const s=JSON.parse(state);paintEffects=!s.soundOnly;avatarMouth=s.cutout?s.anchors.mouth:null;nowMS=s.time;closeup=s.closeup;pose=s.pose;mode=s.manual?'manual':'auto';
 mouthSmoke=s.mouthSmoke!==false;lastMouth=s.mouth;lastFace=lastMouth?s.stamp:-1e5;expression[2]=s.open;origin=s.tip;
 if(fighting&&!s.ninjas)ninjaFight.reset();
 fighting=!!s.ninjas;
 floatingProps.setMode(s.propMode||"off");
 doodles.toggle(s.arms,s.floaters,s.armStability);
  const body=s.bodyStamp??s.stamp,hand=s.handStamp??s.stamp;
  if(body!==lastBody){doodles.observe(s.shoulders,s.aspect,body);lastBody=body}
  if(hand!==lastHand){doodles.match(s.hands,hand);lastHand=hand}
 commands=[];drawAtmosphere(s);doodles.draw(nowMS,s.ninjas,!s.soundOnly);
 for(const fx of s.fx)stageFX.start(fx);
 const pending=queue;queue=[];for(const f of pending)f(nowMS);
 const result=JSON.stringify([!s.soundOnly&&s.ninjaAudio!==false?commands:commands.filter(op=>(!s.soundOnly||op[0]==="impactSound"||op[0]==="ninjaSound")&&(s.ninjaAudio!==false||op[0]!=="ninjaSound")),floatingProps.changes(),floatingProps.exclusions()]);return result
}
function resetTrackingRig(){breathPuffs.length=0;priorLip=null;doodles.reset();lastBody=lastHand=-1}


function restoreFloatingHomes(json){floatingProps.restore(json)}

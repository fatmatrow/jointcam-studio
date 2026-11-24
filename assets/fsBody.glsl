#version 330
out vec4 fragment;


uniform sampler2D photo,webcam,paper;uniform float heat,lipAspect,opening;uniform float clock,manual;
in vec2 tc;in float f;in vec2 materialUV;in vec3 normal;in float metal;
float band(float y,float a,float b,float c,float d){return smoothstep(a,b,y)*(1.-smoothstep(c,d,y));}
vec2 eyelid(vec2 px,vec2 center,float amount){float dx=(px.x-center.x)/31.;float lid=center.y-9.+3.*dx*dx;float y=px.y-lid;
 float reach=max(0.,1.-dx*dx);float drop=32.*(1.-amount)*reach;
 if(y>0.&&y<drop&&drop>.01)px.y=lid-1.-(drop-y)*.40;
 else if(y>=drop&&y<38.)px.y=lid+38.*(y-drop)/max(1.,38.-drop);return px;}
void main(){
 float fire=(.36+.64*heat)*(.90+.10*sin(clock*3.1));
 if(metal>3.){
  vec3 N=normalize(normal);
  float studio=pow(max(0.,dot(N,vec3(.32,.56,.76))),8.);
  float glint=pow(max(0.,dot(normalize(vec3(tc,f)),vec3(-.12,.79,.60))),9.);
  vec3 base=metal>4.5?vec3(.34,.23,.11):vec3(.063,.068,.072);
  fragment=vec4(base+vec3(.54,.53,.49)*studio+vec3(.44,.116,.028)*fire*glint,1.);return;
 }
 vec2 px=tc*1024.;vec2 src=px;
 if(manual<.5){float region=band(px.y,565.,578.,664.,675.)*(1.-smoothstep(67.,80.,abs(px.x-511.)))*smoothstep(.05,.45,f);
 src+=region*mix(vec2(19.,6.),vec2(13.,-5.),smoothstep(503.,519.,px.x));}
 src=eyelid(src,vec2(495.,631.),1.);src=eyelid(src,vec2(559.,619.),1.);
 float mx=clamp(1.-pow(abs((px.x-524.)/59.),2.),0.,1.);
 float lip=691.-.002*(px.x-520.)*(px.x-520.);
 float newHeight=mix(4.,49.,opening);float yy=px.y-lip;
 if(yy>0.&&yy<74.){float raw=yy<newHeight?yy*37./newHeight:37.+(yy-newHeight)*37./(74.-newHeight);src.y+=mx*(raw-yy);}
 vec2 photoUV=src/1024.;
 vec2 photoDx=dFdx(photoUV),photoDy=dFdy(photoUV);
 float angle=materialUV.x*6.283185;
 float edge=308.+9.*sin(angle+.7)+3.*sin(5.*angle)+1.6*sin(17.*angle);
 float burn=px.y-edge;
 float paperCoverage=smoothstep(-4.,7.,burn);
 vec2 mat=vec2(materialUV.x,materialUV.y*.97);vec3 fiber=texture(paper,mat).rgb;
 vec3 light=normalize(vec3(.48,.57,.68));float diffuse=.56+.54*max(0.,dot(normalize(normal),light));
 float seamDist=abs(fract(mat.x+.22*mat.y-.06)-.5);float seam=.065*exp(-seamDist*220.)-.08*exp(-abs(seamDist-.004)*420.);
 vec2 texel=vec2(.0016,0.);
 float relief=dot(texture(paper,mat+texel).rgb-texture(paper,mat+texel.yx).rgb,vec3(.30,.52,.18));
 vec3 wrapColor=(fiber*vec3(1.,.995,.985)+seam)*clamp(diffuse+relief*.75,.49,1.17);
 wrapColor+=vec3(.045,.052,.057)*pow(1.-clamp(normalize(normal).z,0.,1.),3.);
 float scorch=(1.-smoothstep(0.,18.,burn))*smoothstep(-9.,1.,burn);
 // The char line is the source. Short-range amber spill follows the burn around the circumference.
 float distanceToCoal=max(0.,burn)*.035;
 float spill=fire*(.68+.32*cos(angle*3.+.7))/(1.+distanceToCoal*distanceToCoal);
 wrapColor+=vec3(.21,.060,.009)*spill*(.6+.4*fiber.r);
 wrapColor*=mix(vec3(1.),vec3(.48,.31,.19),scorch);
 float browShape=max(1.-smoothstep(.74,1.,length((px-vec2(483.,551.))/vec2(30.,18.))),1.-smoothstep(.74,1.,length((px-vec2(562.,543.))/vec2(29.,17.))));
 float eyes=max(1.-smoothstep(.88,1.,length((px-vec2(476.,620.))/vec2(39.,53.))),1.-smoothstep(.88,1.,length((px-vec2(546.,620.))/vec2(35.,53.))));
 float lips=1.-smoothstep(.87,1.,length((px-vec2(523.,704.))/vec2(60.,46.)));
 float features=(1.-manual)*max(eyes,lips);
 float detail=max(features,browShape)*smoothstep(.06,.48,f);
 float wrapWeight=paperCoverage*(1.-detail);
 vec3 rgb=wrapColor;
 if(wrapWeight<1.)rgb=mix(textureGrad(photo,photoUV,photoDx,photoDy).rgb,wrapColor,wrapWeight);
 if(manual>.5&&f>0.&&px.y>=min(552.,705.-57.*lipAspect)&&px.y<=max(756.,705.+57.*lipAspect)){
 float cover=(1.-smoothstep(66.,78.,abs(px.x-527.)))*band(px.y,552.,568.,746.,756.);
 rgb=mix(rgb,fiber*vec3(1.,.995,.985)*diffuse,cover*smoothstep(.03,.22,f));
 for(int i=0;i<3;i++){vec2 cent=i==0?vec2(476.,628.):i==1?vec2(546.,628.):vec2(522.,705.);vec2 radius=i==2?vec2(57.,57.*lipAspect):vec2(32.,21.);
 vec2 off=(px-cent)/radius;float mask=(1.-smoothstep(.70,1.,length(off)))*smoothstep(.08,.5,f);
 if(max(abs(off.x),abs(off.y))>=1.)continue;
 vec4 sampleFace=texture(webcam,vec2((float(i)+clamp(off.x*.5+.5,.002,.998))/3.,clamp(off.y*.5+.5,.002,.998)));if(i==2)mask=(1.-smoothstep(.92,1.,max(abs(off.x),abs(off.y))))*smoothstep(.08,.5,f);if(i==2&&max(abs(off.x),abs(off.y))<1.){
  vec2 under=clamp(off*.5+.5-vec2(.004,.025),.002,.998);
  float raised=texture(webcam,vec2((2.+under.x)/3.,under.y)).a;
  rgb*=1.-.20*raised*(1.-sampleFace.a)*smoothstep(.08,.5,f);
 }rgb=mix(rgb,sampleFace.rgb,sampleFace.a*mask);}}
 vec2 ashTex=vec2(materialUV.x*5.,px.y*.006);
 vec2 ashDx=dFdx(ashTex),ashDy=dFdy(ashTex);
 // At y >= 550 even the highest ember ridge is over 220 texels away.
 // The fissure exponential underflows and coal is zero across this region.
 if(px.y>=550.){fragment=vec4(rgb*(.89+.11*max(f,0.)),1.);return;}
 float coal=1.-smoothstep(295.,320.,px.y+6.*sin(px.x*.09));float hot=smoothstep(.08,.33,rgb.r-rgb.b)*coal;
 // Fine pale flakes follow irregular layers around the charred tip.
 if(burn < -2. && coal > .10){
 vec2 ashUV=vec2(angle*8.,px.y*.21);
 float ridge=sin(ashUV.y+1.7*sin(ashUV.x*.7)+.65*sin(ashUV.x*2.3));
 float grain=textureGrad(paper,fract(ashTex),ashDx,ashDy).g;
 float crust=smoothstep(.12,.89,ridge)*smoothstep(.23,.75,grain);
 float charMask=(1.-smoothstep(-16.,-2.,burn))*smoothstep(.10,.8,coal);
 rgb=mix(rgb,vec3(.68,.66,.61)*diffuse,charMask*(.12+.38*crust));
 float strata=ashUV.y+2.3*grain+.8*sin(angle*7.+grain*3.);
 float seamAsh=abs(fract(strata*.23)-.5);
 float splitAsh=abs(sin(angle*13.+2.8*grain+px.y*.035));
 float crack=max(1.-smoothstep(.012,.075,seamAsh),.75*(1.-smoothstep(.012,.10,splitAsh)));
 float fleck=smoothstep(.34,.78,grain)*smoothstep(-.55,.68,ridge);
 rgb=mix(rgb,vec3(.76,.74,.68)*diffuse,charMask*fleck*.39);
 rgb*=1.-charMask*(.16*smoothstep(.76,.99,-ridge)+.52*crack);
 rgb+=charMask*crack*smoothstep(.48,.84,grain)*heat*vec3(.55,.11,.013);
 }
 float pulse=.58+.42*sin(clock*3.1+px.x*.11+sin(px.y*.13+clock));
 float fissure=exp(-abs(burn+1.3*sin(px.x*.58))*.52);
 float embers=.28+.72*smoothstep(-.3,.8,sin(angle*11.+sin(angle*3.))+sin(angle*29.)*.42);
 rgb=mix(rgb,vec3(.95,.21,.034),fissure*embers*(.58+.33*heat+.08*pulse));
 rgb+=coal*heat*(vec3(.38,.019,.003)+hot*vec3(.52,.081,.005));rgb+=vec3(.25,.085,.014)*hot*pulse;rgb*=.89+.11*max(f,0.);fragment=vec4(rgb,1.);}
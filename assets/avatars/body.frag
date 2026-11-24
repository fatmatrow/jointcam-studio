#version 330
uniform sampler2D art,webcam;
uniform vec2 artSize,eye,mouth,whiskers;
in vec3 shadingNormal;
uniform int material;
uniform vec2 water;
uniform float gap,lipAspect,opening;
uniform vec2 faceBand;
uniform bool live,glasses;
in vec2 uv;in float front;in vec3 surface;
out vec4 pixel;
void main(){
 vec2 texel=uv;
 if(front>.99 && any(notEqual(whiskers,vec2(0.))) && uv.y>455. && uv.y<756. && abs(uv.x-225.)<211.){
   float d=(1.-smoothstep(108.,211.,abs(uv.x-225.)))*mix(whiskers.x,whiskers.y,clamp((uv.x-187.)/76.,0.,1.));
   float lo=635.+d,hi=722.+d;
   texel.y=uv.y<lo?455.+(uv.y-455.)*180./(lo-455.):uv.y<hi?uv.y-d:722.+(uv.y-hi)*34./(756.-hi);
 }
 vec4 base=texture(art,clamp(texel/artSize,0.,1.));
 if(base.a<.28)discard;
 if(material==0 && uv.y>565. && uv.y<799.){
  float side=clamp((uv.x-244.)/213.,-1.,1.);
  float envelope=clamp(1.-abs(uv.y-(651.+14.*(1.-side*side)))/86.,0.,1.);
  float edge=clamp((140.+(uv.y-540.)*.53-abs(uv.x-244.))/18.,0.,1.);
  edge*=clamp((abs(uv.x-(322.-.67*(uv.y-650.)))-14.)/9.,0.,1.);
  float displacement=(water.x*side*170.+water.y*(1.-2.*side*side)*96.)*
                     smoothstep(0.,1.,envelope)*edge;
  base.rgb=texture(art,(uv-vec2(0.,displacement))/artSize).rgb;
 }
 vec3 normal=normalize(shadingNormal);
 if(normal.z<0.)normal=-normal;
 vec3 light=normalize(vec3(-.62,.52,.75));
 vec3 viewDir=normalize(vec3(-surface.xy,artSize.y*2.8-surface.z));
 float lambert=max(0.,dot(normal,light));
 float edgeLight=pow(1.-clamp(dot(normal,viewDir),0.,1.),3.);
 float glint=max(0.,dot(normal,normalize(light+viewDir)));
 float gloss=material==0?70.:(material==1?32.:48.);
 float shine=pow(glint,gloss);
 vec3 rgb=base.rgb*(.66+.44*lambert)+vec3(.80,.92,1.)*
          (shine*(material==0?.24:.13)+edgeLight*(material==0?.12:.06));
 if(front>.99 && uv.y>=faceBand.x && uv.y<=faceBand.y){
 for(int i=0;i<3;i++){
 vec2 center=i==2?mouth:eye+vec2((float(i)-.5)*gap,0.);
 float w=gap*(i==2?1.48:.91);
 vec2 q=(uv-center)/vec2(w*.5,w*.5*(i==2?lipAspect:.61));
 if(max(abs(q.x),abs(q.y))<1.){
 float mask=1.-smoothstep(.76,1.,length(q));
 if(live){
 vec4 tile=texture(webcam,vec2((float(i)+clamp(q.x*.5+.5,.006,.994))/3.,clamp(q.y*.5+.5,.008,.992)));
 rgb=mix(rgb,tile.rgb,tile.a*(i==2?1.:mask));
 }else if(i<2){rgb=mix(rgb,vec3(.92,.88,.77),mask);rgb=mix(rgb,vec3(.14,.10,.07),1.-smoothstep(.38,.45,length(q)));}
 else rgb=mix(rgb,vec3(.24,.12,.11),1.-smoothstep(.72,.82,length(q/vec2(1.,.25+.3*opening))));
 }
 if(glasses&&i<2){
 vec2 d=abs((uv-center)/gap)-vec2(.32,.16);
 float dist=length(max(d,0.))+min(max(d.x,d.y),0.)-.15;
 rgb=mix(rgb,vec3(.19,.16,.13),1.-smoothstep(.018,.036,abs(dist)));
 }
 }
 if(glasses&&abs(uv.x-eye.x)<gap*.065&&abs(uv.y-eye.y)<gap*.021)rgb=vec3(.19,.16,.13);
 }
 pixel=vec4(rgb,1.);
}

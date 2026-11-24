#version 330


in vec3 p;in vec2 uv;in float front,wrap;
uniform vec3 body,head;uniform vec3 articulation;uniform vec4 place;out vec2 tc;out float f;out vec2 materialUV;out vec3 normal;out float metal;
vec3 rot(vec3 p,vec3 a){float s=sin(a.x),c=cos(a.x);p.yz=mat2(c,s,-s,c)*p.yz;s=sin(a.y);c=cos(a.y);p.xz=mat2(c,-s,s,c)*p.xz;s=sin(a.z);c=cos(a.z);p.xy=mat2(c,s,-s,c)*p.xy;return p;}
void main(){vec3 pivot=vec3(0.,-1.05,0.);vec3 shaped=p;
 if(wrap<=1.){float taper=1.-.16*smoothstep(.72,.95,uv.y);shaped.x*=taper;shaped.z*=taper;}
 float cheek=wrap>3.?0.:smoothstep(0.,.65,front);
 float jaw=exp(-pow(abs(uv.y-.713)/.078,2.))*cheek*articulation.x;
 shaped.y-=.14*jaw;shaped.z+=.11*jaw;shaped.x*=1.+.10*jaw;
 float lift=mix(articulation.y,articulation.z,smoothstep(.49,.55,uv.x));
 shaped.y+=.075*lift*exp(-pow(abs(uv.y-.546)/.041,2.))*cheek;
 vec3 v=mix(shaped,rot(shaped-pivot,head)+pivot,smoothstep(-1.34,-.35,p.y));v=rot(v,body);v.xy+=place.xy;
float k=place.z;gl_Position=vec4(v.x*k*.5625,v.y*k+place.w,-v.z*.18,1.);tc=uv;f=front;metal=wrap;materialUV=vec2(wrap,uv.y);vec3 n=wrap>3.?vec3(uv,front):vec3(sin((wrap-.5)*6.283185),.06,front);
 normal=rot(mix(n,rot(n,head),smoothstep(-1.34,-.35,p.y)),body);}
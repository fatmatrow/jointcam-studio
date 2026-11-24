#version 330
out vec4 fragment;
in vec2 uv;in vec2 vState;uniform float clock;
float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.545);}
float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+1.),f.x),f.y);}
void main(){float life=vState.x,seed=vState.y;
 vec2 q=uv;float n=noise(q*3.1+seed*12.+clock*.22);float r=length(vec2(q.x+.18*sin(q.y*4.+seed*6.),q.y*.74))+.31*(n-.5);
 float curl=exp(-13.*abs(r-(.48+.13*sin(q.y*3.+seed*8.+clock*.45))));
 float density=(.24*exp(-3.9*r*r)+.26*curl)*(1.-smoothstep(.65,1.,r));
 float a=density*(1.-smoothstep(.4,1.,life))*smoothstep(0.,.12,life)*.74;fragment=vec4(.94,.91,.86,a);}
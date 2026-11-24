#version 330
in vec2 pt;in vec4 instance;in vec2 state;out vec2 uv;out vec2 vState;
void main(){float s=sin(instance.w),c=cos(instance.w);vec2 q=mat2(c,s,-s,c)*pt;gl_Position=vec4(instance.xy+q*instance.z*vec2(.5625,1.),0.,1.);uv=pt;vState=state;}
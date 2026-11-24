#version 330
in vec4 vertex;
in vec3 vertexNormal;
out vec3 shadingNormal;
uniform vec2 artSize, eye, pan, lean;
uniform vec3 angles, torso;
uniform float zoom;
out vec2 uv;
out float front;
out vec3 surface;
void main(){
 float weight=smoothstep(.18,.58,1.-vertex.y/artSize.y);
 vec3 p=vec3(vertex.x-eye.x,artSize.y*.62-vertex.y,vertex.z);
 float trunk=smoothstep(.15,.50,1.-vertex.y/artSize.y)*(1.-weight);
 vec3 a=angles*weight+torso*trunk;
 vec3 n=vertexNormal;
 float s=sin(a.x),c=cos(a.x);p.yz=mat2(c,s,-s,c)*p.yz;n.yz=mat2(c,s,-s,c)*n.yz;
 s=sin(a.y);c=cos(a.y);p.xz=mat2(c,-s,s,c)*p.xz;n.xz=mat2(c,-s,s,c)*n.xz;
 s=sin(a.z);c=cos(a.z);p.xy=mat2(c,s,-s,c)*p.xy;n.xy=mat2(c,s,-s,c)*n.xy;
 vec2 screen=vec2(480.,322.92)+vec2(480.,-270.)*pan;
 float scale=387.*zoom/artSize.y;
 float perspective=artSize.y*2.8/(artSize.y*2.8-p.z);
 screen+=((vec2(p.x,-p.y)*perspective)+vec2(0.,artSize.y*.62-eye.y))*scale+lean*weight;
 shadingNormal=n;
 gl_Position=vec4(screen.x/480.-1.,1.-screen.y/270.,-p.z/1500.,1.);
 uv=vertex.xy;front=vertex.w;surface=p;
}

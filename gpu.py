"""A Qt-owned OpenGL surface for the stage, its finishing passes and live preview.

Frame flow (all on the GPU until the optional virtual-camera readback):

  stage + overlays -> MSAA buffer (output size x render scale)
                   -> resolve
                   -> finish: Lanczos downsample, optional ember glow  -> output texture
                   -> Spout2 shares the output texture directly
                   -> virtual camera: convert to NV12 / straight RGBA on the GPU, then one readback
                   -> preview draws the output texture
"""
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat, QOpenGLPaintDevice
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtGui import QSurfaceFormat
import numpy as np

# key: (label, MSAA samples, render scale, ember glow)
QUALITY = {
    "efficient": ("Efficient · 4× MSAA", 4, 1.0, False),
    "high": ("High · 8× MSAA", 8, 1.0, True),
    "cinema": ("Cinema · 8× MSAA + 1.5× supersampling", 8, 1.5, True),
    "ultra": ("Ultra · 8× MSAA + 2× supersampling", 8, 2.0, True),
}
DEFAULT_QUALITY = "cinema"

FULLSCREEN = """#version 330
void main() {
    vec2 corner = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(corner * 2.0 - 1.0, 0.0, 1.0);
}"""

# Lanczos-2 resampling, widened by the downscale ratio so it also acts as the
# anti-aliasing filter. Optional glow is composited as premultiplied light.
FINISH = """#version 330
uniform sampler2D src;
uniform sampler2D glow;
uniform vec2 ratio;
uniform vec2 outSize;
uniform float glowStrength;
out vec4 color;
float sinc(float x) { x *= 3.14159265; return abs(x) < 1e-4 ? 1.0 : sin(x) / x; }
float lanczos(float x) { return abs(x) < 2.0 ? sinc(x) * sinc(x * 0.5) : 0.0; }
void main() {
    ivec2 limit = textureSize(src, 0) - 1;
    vec4 c;
    if (ratio.x < 1.0001 && ratio.y < 1.0001) {
        c = texelFetch(src, min(ivec2(gl_FragCoord.xy), limit), 0);
    } else {
        vec2 center = gl_FragCoord.xy * ratio;
        vec2 radius = 2.0 * ratio;
        ivec2 lo = ivec2(floor(center - radius));
        ivec2 hi = ivec2(ceil(center + radius));
        vec4 sum = vec4(0.0);
        float total = 0.0;
        for (int y = lo.y; y <= hi.y; y++) {
            float wy = lanczos((float(y) + 0.5 - center.y) / ratio.y);
            if (wy == 0.0) continue;
            for (int x = lo.x; x <= hi.x; x++) {
                float w = wy * lanczos((float(x) + 0.5 - center.x) / ratio.x);
                if (w == 0.0) continue;
                sum += w * texelFetch(src, clamp(ivec2(x, y), ivec2(0), limit), 0);
                total += w;
            }
        }
        c = sum / total;
    }
    if (glowStrength > 0.0) {
        vec3 g = texture(glow, gl_FragCoord.xy / outSize).rgb * glowStrength;
        float coverage = clamp(max(g.r, max(g.g, g.b)), 0.0, 1.0);
        c.rgb += g;
        c.a += (1.0 - c.a) * coverage;
    }
    c = clamp(c, 0.0, 1.0);
    // Keep valid premultiplied color after the kernel's small negative lobes.
    c.rgb = min(c.rgb, vec3(c.a));
    color = c;
}"""

# Glow takes warm, saturated pixels that the ember shader marked as emissive.
# White paper, skin, orange artwork and costume colors stay out of it.
GLOW_PREFILTER = """#version 330
uniform sampler2D src;
uniform sampler2D mask;
uniform vec2 dstSize;
uniform float threshold;
out vec4 color;
void main() {
    vec2 uv = gl_FragCoord.xy / dstSize;
    vec2 foot = 1.0 / dstSize;
    vec3 acc = vec3(0.0);
    for (int j = 0; j < 4; j++) for (int i = 0; i < 4; i++) {
        vec3 c = texture(src, uv + (vec2(i, j) - 1.5) * 0.25 * foot).rgb;
        float hi = max(c.r, max(c.g, c.b));
        float lo = min(c.r, min(c.g, c.b));
        float key = (hi - lo) * smoothstep(0.25, 0.65, c.r - c.b);
        acc += c * smoothstep(threshold, threshold + 0.25, key);
    }
    // The emissive mask comes from the ember shader. A hand or prop in front of the
    // ember fails the warm-color key, so occluders do not glow either.
    color = vec4(acc / 16.0 * texture(mask, uv).r, 1.0);
}"""

GLOW_DOWN = """#version 330
uniform sampler2D src;
uniform vec2 dstSize;
out vec4 color;
void main() {
    vec2 uv = gl_FragCoord.xy / dstSize;
    vec2 o = 1.0 / vec2(textureSize(src, 0));
    vec3 sum = texture(src, uv).rgb * 4.0;
    sum += texture(src, uv - o).rgb + texture(src, uv + o).rgb;
    sum += texture(src, uv + vec2(o.x, -o.y)).rgb + texture(src, uv - vec2(o.x, -o.y)).rgb;
    color = vec4(sum / 8.0, 1.0);
}"""

GLOW_UP = """#version 330
uniform sampler2D src;
uniform vec2 dstSize;
out vec4 color;
void main() {
    vec2 uv = gl_FragCoord.xy / dstSize;
    vec2 o = 1.0 / vec2(textureSize(src, 0));
    vec3 sum = texture(src, uv + vec2(-2.0 * o.x, 0.0)).rgb + texture(src, uv + vec2(2.0 * o.x, 0.0)).rgb;
    sum += texture(src, uv + vec2(0.0, 2.0 * o.y)).rgb + texture(src, uv + vec2(0.0, -2.0 * o.y)).rgb;
    sum += 2.0 * (texture(src, uv + vec2(-o.x, o.y)).rgb + texture(src, uv + vec2(o.x, o.y)).rgb);
    sum += 2.0 * (texture(src, uv + vec2(o.x, -o.y)).rgb + texture(src, uv + vec2(-o.x, -o.y)).rgb);
    color = vec4(sum / 12.0, 1.0);
}"""

# One pass writes a complete top-down NV12 image (Y plane, then interleaved UV) into an
# R8 target of width x 1.5 height. BT.601 limited range with 2x2 chroma averaging is
# the same conversion pyvirtualcam applies to RGB frames, so colors match 1.0.
NV12 = """#version 330
uniform sampler2D src;
uniform ivec2 size;
out float value;
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    int h = size.y;
    if (p.y < h) {
        vec3 c = texelFetch(src, ivec2(p.x, h - 1 - p.y), 0).rgb;
        value = (16.0 + dot(c, vec3(65.481, 128.553, 24.966))) / 255.0;
    } else {
        int k = p.y - h;
        ivec2 s = ivec2((p.x >> 1) * 2, h - 1 - 2 * k);
        vec3 c = 0.25 * (texelFetch(src, s, 0).rgb + texelFetch(src, s + ivec2(1, 0), 0).rgb
                       + texelFetch(src, s - ivec2(0, 1), 0).rgb + texelFetch(src, s + ivec2(1, -1), 0).rgb);
        value = (p.x & 1) == 0 ? (128.0 + dot(c, vec3(-37.797, -74.203, 112.0))) / 255.0
                               : (128.0 + dot(c, vec3(112.0, -93.786, -18.214))) / 255.0;
    }
}"""

CAMERA_RGBA = """#version 330
uniform sampler2D stage;
uniform bool straightAlpha;
uniform ivec2 size;
out vec4 pixel;
void main() {
    vec4 c = texelFetch(stage, ivec2(gl_FragCoord.x, size.y - 1 - int(gl_FragCoord.y)), 0);
    if (straightAlpha && c.a > 0.) c.rgb /= c.a;
    pixel = c;
}"""


class Finisher:
    """Turn the resolved stage into the output texture. Skipped when it would be a copy."""
    LEVELS = 5

    def __init__(self, ctx):
        import moderngl
        self.gl = moderngl
        self.ctx = ctx
        self.finish = ctx.program(vertex_shader=FULLSCREEN, fragment_shader=FINISH)
        self.prefilter = ctx.program(vertex_shader=FULLSCREEN, fragment_shader=GLOW_PREFILTER)
        self.down = ctx.program(vertex_shader=FULLSCREEN, fragment_shader=GLOW_DOWN)
        self.up = ctx.program(vertex_shader=FULLSCREEN, fragment_shader=GLOW_UP)
        self.nv12 = ctx.program(vertex_shader=FULLSCREEN, fragment_shader=NV12)
        self.rgba = ctx.program(vertex_shader=FULLSCREEN, fragment_shader=CAMERA_RGBA)
        self.passes = {name: ctx.vertex_array(prog, []) for name, prog in
                       (("finish", self.finish), ("prefilter", self.prefilter), ("down", self.down),
                        ("up", self.up), ("nv12", self.nv12), ("rgba", self.rgba))}
        self.finish["src"].value = 0
        self.finish["glow"].value = 1
        self.output = self.output_fbo = None
        self.glow_levels = []
        self.mask = self.mask_depth = self.mask_fbo = None
        self.readback = {}
        self.size = None
        self.glow_strength = .85

    def allocate(self, size, glow):
        self.release_targets()
        ctx = self.ctx
        self.size = size
        self.output = ctx.texture(size, 4)
        self.output.filter = (self.gl.LINEAR, self.gl.LINEAR)
        self.output.repeat_x = self.output.repeat_y = False
        self.output_fbo = ctx.framebuffer([self.output])
        if glow:
            w, h = size
            for level in range(1, self.LEVELS+1):
                dims = (max(1, w >> level), max(1, h >> level))
                tex = ctx.texture(dims, 4, dtype="f2")
                tex.filter = (self.gl.LINEAR, self.gl.LINEAR)
                tex.repeat_x = tex.repeat_y = False
                self.glow_levels.append((tex, ctx.framebuffer([tex]), dims))
            dims = self.glow_levels[0][2]
            self.mask = ctx.texture(dims, 1)
            self.mask.filter = (self.gl.LINEAR, self.gl.LINEAR)
            self.mask.repeat_x = self.mask.repeat_y = False
            self.mask_depth = ctx.depth_renderbuffer(dims)
            self.mask_fbo = ctx.framebuffer([self.mask], self.mask_depth)

    def release_targets(self):
        for tex, fbo, _ in self.glow_levels:
            fbo.release()
            tex.release()
        self.glow_levels = []
        if self.mask_fbo is not None:
            self.mask_fbo.release()
            self.mask_depth.release()
            self.mask.release()
        self.mask = self.mask_depth = self.mask_fbo = None
        if self.output_fbo is not None:
            self.output_fbo.release()
            self.output.release()
        self.output = self.output_fbo = None
        self.release_readback()

    def release_readback(self):
        for tex, fbo, _ in self.readback.values():
            fbo.release()
            tex.release()
        self.readback = {}

    def render(self, source, source_size, glow):
        ctx = self.ctx
        ctx.enable_only(0)
        source.use(0)
        strength = 0.
        if glow and self.glow_levels:
            self.prefilter["src"].value = 0
            self.prefilter["mask"].value = 2
            self.mask.use(2)
            self.prefilter["threshold"].value = .38
            tex0, fbo0, dims0 = self.glow_levels[0]
            fbo0.use()
            ctx.viewport = (0, 0, *dims0)
            self.prefilter["dstSize"].value = dims0
            self.passes["prefilter"].render(vertices=3)
            self.down["src"].value = 0
            for (src, _, _), (_, fbo, dims) in zip(self.glow_levels, self.glow_levels[1:]):
                src.use(0)
                fbo.use()
                ctx.viewport = (0, 0, *dims)
                self.down["dstSize"].value = dims
                self.passes["down"].render(vertices=3)
            # Add each blurred level back into the next larger one.
            ctx.enable_only(self.gl.BLEND)
            ctx.blend_func = (self.gl.ONE, self.gl.ONE)
            self.up["src"].value = 0
            for (_, fbo, dims), (src, _, _) in reversed(list(zip(self.glow_levels, self.glow_levels[1:]))):
                src.use(0)
                fbo.use()
                ctx.viewport = (0, 0, *dims)
                self.up["dstSize"].value = dims
                self.passes["up"].render(vertices=3)
            ctx.enable_only(0)
            ctx.blend_func = (self.gl.SRC_ALPHA, self.gl.ONE_MINUS_SRC_ALPHA, self.gl.ONE, self.gl.ONE_MINUS_SRC_ALPHA)
            tex0.use(1)
            source.use(0)
            strength = self.glow_strength/self.LEVELS
        self.output_fbo.use()
        ctx.viewport = (0, 0, *self.size)
        self.finish["ratio"].value = (source_size[0]/self.size[0], source_size[1]/self.size[1])
        self.finish["outSize"].value = self.size
        self.finish["glowStrength"].value = strength
        self.passes["finish"].render(vertices=3)

    def read(self, texture, size, mode, out):
        """Convert on the GPU and read once. mode: 'nv12', 'rgba' (straight) or 'rgb'."""
        ctx = self.ctx
        w, h = size
        target_size = (w, h*3//2) if mode == "nv12" else (w, h)
        components = 1 if mode == "nv12" else 4
        entry = self.readback.get(mode)
        if entry is None or entry[2] != target_size:
            if entry is not None:
                entry[1].release()
                entry[0].release()
            tex = ctx.texture(target_size, components)
            entry = self.readback[mode] = (tex, ctx.framebuffer([tex]), target_size)
        _, fbo, _ = entry
        fbo.use()
        ctx.viewport = (0, 0, *target_size)
        ctx.enable_only(0)
        texture.use(0)
        if mode == "nv12":
            self.nv12["src"].value = 0
            self.nv12["size"].value = size
            self.passes["nv12"].render(vertices=3)
            fbo.read_into(out, components=1, alignment=1)
        else:
            self.rgba["stage"].value = 0
            self.rgba["straightAlpha"].value = mode == "rgba"
            self.rgba["size"].value = size
            self.passes["rgba"].render(vertices=3)
            fbo.read_into(out, components=4 if mode == "rgba" else 3, alignment=1)
        return out

    def release(self):
        self.release_targets()


class StageSurface(QOpenGLWidget):
    moved = Signal(float, float)

    def __init__(self, quality=DEFAULT_QUALITY):
        super().__init__()
        fmt = QSurfaceFormat()
        fmt.setRenderableType(QSurfaceFormat.OpenGL)
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setSwapInterval(0)
        self.setFormat(fmt)
        self.setMinimumSize(360, 210)
        self.setCursor(Qt.OpenHandCursor)
        self.setAccessibleName("Live avatar preview. Drag to position the avatar.")
        self.anchor = None
        self.stage = None
        self.preview_target = None
        self.preview_key = None
        self.camera_pixels = None
        self.finisher = None
        self.quality = quality if quality in QUALITY else DEFAULT_QUALITY
        self.glow_allowed = True
        self.output_size = None
        self.internal_size = None
        self.finished = False
        self.emissive_ready = False
        self.glow_failed = False

    @property
    def samples(self):
        return QUALITY[self.quality][1]

    @property
    def render_scale(self):
        return QUALITY[self.quality][2]

    @property
    def glow(self):
        return QUALITY[self.quality][3] and self.glow_allowed and not self.glow_failed

    def describe(self):
        samples = max(1, self.draw_buffer.format().samples())
        scale = self.internal_size[0]/self.output_size[0]
        text = f"GPU · {samples}× MSAA"
        if scale > 1.001:
            text += f" · {scale:g}× SSAA"
        return text

    def open_stage(self, size):
        import moderngl
        from renderer import Renderer
        self.makeCurrent()
        if not self.isValid():
            raise RuntimeError("OpenGL preview surface unavailable")
        moderngl.init_context()
        ctx = moderngl.get_context()
        self.finisher = Finisher(ctx)
        target = self.configure_target(ctx, size)
        program = ctx.program(vertex_shader=FULLSCREEN, fragment_shader="""#version 330
            uniform sampler2D stage;
            uniform vec4 area;
            out vec4 pixel;
            void main() {
                vec4 c = texture(stage, (gl_FragCoord.xy - area.xy) / area.zw);
                float tile = mod(floor(gl_FragCoord.x / 12.) + floor(gl_FragCoord.y / 12.), 2.);
                pixel = vec4(c.rgb + (1.-c.a) * mix(vec3(.16,.18,.19),vec3(.20,.22,.23),tile), 1.);
            }""")
        self.preview_program = program
        self.quad = ctx.vertex_array(program, [])
        self.stage = Renderer(*self.internal_size, context=ctx, target=target)
        return self.stage

    def configure_target(self, ctx, size):
        self.makeCurrent()
        scale = self.render_scale
        internal = (int(round(size[0]*scale/2))*2, int(round(size[1]*scale/2))*2)
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        fmt.setSamples(min(self.samples, ctx.max_samples))
        draw_buffer = QOpenGLFramebufferObject(*internal, fmt)
        if not draw_buffer.isValid():
            draw_buffer = QOpenGLFramebufferObject(*internal, QOpenGLFramebufferObject.CombinedDepthStencil)
        buffer = QOpenGLFramebufferObject(*internal) if draw_buffer.format().samples() else draw_buffer
        if not buffer.isValid() or not draw_buffer.isValid() or not draw_buffer.bind():
            raise RuntimeError("Could not allocate the stage texture")
        target = ctx.detect_framebuffer(draw_buffer.handle())
        resolved = ctx.detect_framebuffer(buffer.handle()) if buffer is not draw_buffer else target
        texture = ctx.external_texture(buffer.texture(), internal, 4, 0, "f1")
        # Qt creates FBO textures with nearest filtering. The glow prefilter and the
        # preview scale this texture, so sample it bilinearly.
        texture.filter = (self.finisher.gl.LINEAR, self.finisher.gl.LINEAR)
        device = QOpenGLPaintDevice(*internal)
        self.output_size, self.internal_size = tuple(size), internal
        self.finisher.allocate(self.output_size, QUALITY[self.quality][3])
        if self.stage is not None:
            self.stage.resize_target(target, internal)
        self.draw_buffer, self.resolved = draw_buffer, resolved
        self.buffer, self.texture, self.device = buffer, texture, device
        self.camera_pixels = None
        self.finished = False
        return target

    def set_quality(self, quality):
        if quality not in QUALITY or quality == self.quality:
            return False
        previous = self.quality
        self.quality = quality
        if self.stage is not None:
            try:
                self.configure_target(self.stage.ctx, self.output_size)
            except Exception:
                self.quality = previous
                self.configure_target(self.stage.ctx, self.output_size)
                raise
        return True

    def draw_emissive(self, renderer):
        """Ask the stage renderer for this frame's ember mask. Call after its draw."""
        if self.glow and self.finisher.mask_fbo is not None:
            try:
                renderer.draw_emissive(self.finisher.mask_fbo, self.finisher.glow_levels[0][2])
                self.emissive_ready = True
            except Exception:
                import traceback
                traceback.print_exc()
                self.glow_failed = True
                renderer.target.use()

    def resolve(self):
        self.camera_read_valid = False
        if self.draw_buffer is not self.buffer:
            QOpenGLFramebufferObject.blitFramebuffer(self.buffer, self.draw_buffer)
        glow = self.glow and self.emissive_ready
        self.emissive_ready = False
        self.finished = self.internal_size != self.output_size or glow
        if self.finished:
            self.finisher.render(self.texture, self.internal_size, glow)

    def output_texture(self):
        return self.finisher.output if self.finished else self.texture

    def output_handles(self):
        """GL texture name, FBO name and size of the finished frame, for Spout."""
        if self.finished:
            return self.finisher.output.glo, self.finisher.output_fbo.glo, self.output_size
        return self.buffer.texture(), self.buffer.handle(), self.output_size

    def release_camera_buffer(self):
        if self.finisher is not None:
            self.finisher.release_readback()
        self.camera_pixels = None

    def camera_frame(self, mode, repeat=False):
        """Read the finished frame for a virtual camera. mode: 'nv12', 'rgba' or 'rgb'."""
        w, h = self.output_size
        shape = (h*3//2, w) if mode == "nv12" else (h, w, 4 if mode == "rgba" else 3)
        if repeat and getattr(self, "camera_read_valid", False) and self.camera_pixels is not None and self.camera_pixels.shape == shape:
            return self.camera_pixels
        if self.camera_pixels is None or self.camera_pixels.shape != shape:
            self.camera_pixels = np.empty(shape, np.uint8)
        self.finisher.read(self.output_texture(), self.output_size, mode, self.camera_pixels)
        self.camera_read_valid = True
        return self.camera_pixels

    def paintGL(self):
        if self.stage is None:
            return
        ctx = self.stage.ctx
        key = (self.defaultFramebufferObject(), self.width(), self.height(), self.devicePixelRatioF())
        if key != self.preview_key:
            self.preview_target = ctx.detect_framebuffer(key[0])
            self.preview_key = key
        self.preview_target.use()
        dpr = self.devicePixelRatioF()
        w, h = round(self.width()*dpr), round(self.height()*dpr)
        vw = min(w, round(h*16/9))
        vh = round(vw*9/16)
        # The opaque fullscreen triangle overwrites every pixel in its viewport.
        if vw != w or vh != h:
            self.preview_target.clear(.06, .07, .08, 1.)
        x, y = (w-vw)//2, (h-vh)//2
        ctx.viewport = (x, y, vw, vh)
        ctx.enable_only(0)
        texture = self.output_texture()
        texture.use(0)
        self.preview_program["area"].value = (x, y, vw, vh)
        self.quad.render(vertices=3)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.anchor = event.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            point = event.position()
            delta = point - self.anchor
            self.anchor = point
            w = min(self.width(), self.height()*16/9)
            self.moved.emit(2*delta.x()/w, -2*delta.y()/(w*9/16))

    def mouseReleaseEvent(self, event):
        self.anchor = None
        self.setCursor(Qt.OpenHandCursor)


class SpoutOutput:
    device = "JointCam Studio"

    def __init__(self):
        import SpoutGL
        self.sender = SpoutGL.SpoutSender()
        self.sender.setSenderName(self.device)
        self.sender.setAutoShare(False)
        self.sender.setCPUshare(False)

    def publish(self, surface):
        texture, fbo, (width, height) = surface.output_handles()
        if not self.sender.sendTexture(texture, 0x0DE1, width, height, True, fbo):
            raise RuntimeError("Spout could not share the stage texture. Check the graphics adapter.")
        if self.sender.getCPU():
            raise RuntimeError("GPU sharing is unavailable. Set OBS and JointCam to the same GPU.")

    def close(self):
        self.sender.releaseSender()

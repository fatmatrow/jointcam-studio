import math
import threading
import time
import cv2
import numpy as np
import perf
from facetiles import SCALE, TILE_W, TILE_H, PATCH_SHAPE

# Contours run around the visible eyelids and external lip boundary.
OUTLINES = (
    [33,160,158,133,153,144],
    [362,385,387,263,373,380],
    [61,40,37,0,267,270,291,321,314,17,84,91],
)


FACE_POINTS = sorted({p for outline in OUTLINES for p in outline} | {1,78,81,13,311,308,402,14,178})

_mediapipe_lock = threading.Lock()


def solution(name):
    """Import a MediaPipe solution module. The workers start together, and MediaPipe's
    package initialisation is not safe to run from two threads at once."""
    import importlib
    with _mediapipe_lock:
        return importlib.import_module("mediapipe.python.solutions."+name)


# Detector input widths. Face landmarks are located on a small frame and the tiles are
# then sampled from the full camera frame. Hand landmarks are cropped by MediaPipe from
# the frame it receives, so a larger frame gives the finger model more real pixels.
FACE_WIDTH = 480
POSE_WIDTH = 480
HAND_WIDTH = 640


class OneEuro:
    """One Euro filter (Casiez, Roussel and Vogel, CHI 2012).

    Smooths hard while a signal is still and follows it almost instantly while it moves,
    which is what landmark jitter needs: steady tiles at rest, no lag on a real movement.
    Works on scalars or numpy arrays. The speed term is divided by `scale` so `beta` is in
    eye spans per second, independent of how large the face is in the frame.
    """
    def __init__(self, min_cutoff, beta, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.value = self.speed = None

    @staticmethod
    def _alpha(cutoff, dt):
        return 1.0/(1.0+1.0/(2*math.pi*cutoff*dt))

    def __call__(self, x, dt, scale=1.0):
        x = np.asarray(x, dtype=np.float64)
        if self.value is None or not 0 < dt < .25:
            # First sample, or the face was away long enough that the old state is stale.
            self.value, self.speed = x.copy(), np.zeros_like(x)
            return x.copy()
        raw = (x-self.value)/dt
        self.speed = self.speed+self._alpha(self.d_cutoff, dt)*(raw-self.speed)
        cutoff = self.min_cutoff+self.beta*np.abs(self.speed)/max(scale, 1e-6)
        self.value = self.value+self._alpha(cutoff, dt)*(x-self.value)
        return self.value.copy()


def tile_sharpness(rgb_tile):
    """Variance of the Laplacian: high for a crisp tile, low for motion blur or defocus."""
    return float(cv2.Laplacian(cv2.cvtColor(np.ascontiguousarray(rgb_tile), cv2.COLOR_RGB2GRAY), cv2.CV_32F).var())


def eye_openness(pts):
    """Eye aspect ratio of the less open eye (Soukupova and Cech, 2016)."""
    def ratio(a, b, c, d, e, f):
        width = max(1., float(np.linalg.norm(pts[d]-pts[a])))
        return float(np.linalg.norm(pts[b]-pts[f])+np.linalg.norm(pts[c]-pts[e]))/(2*width)
    return min(ratio(33, 160, 158, 133, 153, 144), ratio(362, 385, 387, 263, 373, 380))


class FaceMeasure:
    """Turn face landmarks into the eye/eye/lip patch, the pose and the mouth opening.

    1.2 keeps state between frames:
      * Each tile's crop (centre, angle, size) is One Euro filtered, so the live eyes and
        lips no longer wobble, zoom or rotate with landmark noise. The lip mask is drawn
        from the current landmarks inside that steady crop, so it always matches the pixels.
      * The lip tile grows instantly when the mouth opens and shrinks smoothly, so a fast
        opening is never clipped at the tile edge.
      * Mouth opening is measured against the eye span (steady) instead of the mouth width
        (which changes with smiles and rounded vowels), relative to a learned closed-mouth
        level, so the avatar's mouth closes fully when yours does.
      * Every frame is graded for the held capture used when the face is lost: eyes count
        as good when facing the camera, open and sharp; the mouth when facing the camera,
        relaxed and sharp.
    """
    def __init__(self):
        self.stamp = None
        self.crops = [OneEuro(1.0, 6.0, d_cutoff=3.0) for _ in range(3)]
        self.span = OneEuro(.8, 2.0)
        self.opening = OneEuro(3.0, 1.5)
        self.lip_height = None
        self.lip_reach = None
        self.baseline = None
        self.yaw_ref = self.pitch_ref = self.ear_ref = None
        self.sharp_ref = [None, None]

    def upper_lip(self, rgb_tile, lip, lips, reach, dt):
        """Alpha for the skin and lip just above the outer lip line, stopping at facial hair.

        Each column scans up from the lip line to `reach` tile pixels (tapered towards the
        corners) and stops at the first pixel that reads as hair: clearly darker than this
        person's lips (dark hair) or much greyer than them (grey or white hair). The reach of
        each column retracts at once when hair comes closer and grows back smoothly.
        """
        upper = lip[:7]
        order = np.argsort(upper[:, 0])
        ux, uy = upper[order, 0], upper[order, 1]
        x0, x1 = int(math.ceil(ux[0])), int(math.floor(ux[-1]))
        if x1-x0 < 8 or not np.any(lips):
            return None
        H, W = rgb_tile.shape[:2]
        x0, x1 = max(0, x0), min(W-1, x1)
        xs = np.arange(x0, x1+1)
        y0 = np.interp(xs, ux, uy)
        half = max(1., (ux[-1]-ux[0])*.5)
        t = np.clip((xs-(ux[0]+ux[-1])*.5)/half, -1, 1)
        limit = y0-reach*np.clip(1-t*t, 0, 1)**.6
        lab = cv2.cvtColor(np.ascontiguousarray(rgb_tile), cv2.COLOR_RGB2LAB).astype(np.float32)
        L = lab[:, :, 0]
        C = np.hypot(lab[:, :, 1]-128, lab[:, :, 2]-128)
        lip_l = float(np.median(L[lips]))
        lip_c = max(8., float(np.median(C[lips])))
        dark = np.clip((lip_l-18-L)/25, 0, 1)
        grey = np.clip((.5*lip_c-C)/(.25*lip_c), 0, 1)
        # Wide horizontal smoothing makes a sparse fringe of hairs count as hair.
        hair = cv2.blur(np.maximum(dark, grey), (7, 3))[:, xs]
        rows = np.arange(H, dtype=np.float32)[:, None]
        hit = (rows < y0[None, :]) & (rows >= limit[None, :]) & (hair > .4)
        nearest = H-1-np.argmax(hit[::-1], axis=0)
        top = np.where(hit.any(axis=0), nearest+1., np.maximum(limit, 0.))
        extent = np.clip(y0-top, 0, None)/max(reach, 1e-3)
        # No column reaches higher than its neighbours allow, so hair cannot show through
        # a gap between strands that one column happened to slip through.
        if len(extent) >= 7:
            extent = np.lib.stride_tricks.sliding_window_view(np.pad(extent, 3, mode="edge"), 7).min(axis=1)
        slots = np.interp(np.linspace(-1, 1, 32), t, extent)
        if self.lip_reach is None or not 0 < dt < .25:
            self.lip_reach = slots
        else:
            grow = slots > self.lip_reach
            self.lip_reach = np.where(grow, self.lip_reach+(slots-self.lip_reach)*(1-math.exp(-dt/.15)), slots)
        extent = np.interp(t, np.linspace(-1, 1, 32), self.lip_reach)*reach
        extent = np.convolve(np.pad(extent, 2, mode="edge"), np.ones(5)/5, mode="valid")
        top = y0-extent
        # Overlap into the lip so the two soft edges leave no see-through seam.
        # Everything inside the outer lip line is visible anyway, so a deep overlap is free.
        bottom = y0+4*SCALE
        polygon = np.concatenate([np.stack([xs, top], 1), np.stack([xs[::-1], bottom[::-1]], 1)])
        alpha = np.zeros((H, W), np.uint8)
        cv2.fillPoly(alpha, [np.int32(np.round(polygon*16))], 255, lineType=cv2.LINE_AA, shift=4)
        # A softer top edge blends the lip into the avatar without a visible line.
        return cv2.GaussianBlur(alpha, (0, 0), sigmaX=.65*SCALE, sigmaY=1.5*SCALE)

    def _ema(self, ref, value, dt, tau=3.):
        return value if ref is None else ref+(value-ref)*(1-math.exp(-min(dt, .25)/tau))

    def __call__(self, rgb, landmarks, stamp, matte=False, sensor=None, lip_reach=100):
        height, width = rgb.shape[:2]
        pts = np.empty((max(FACE_POINTS)+1, 2), np.float32)
        for i in FACE_POINTS:
            point = landmarks[i]
            pts[i] = (point.x*width, point.y*height)
        dt = stamp-self.stamp if self.stamp is not None else 0.
        self.stamp = stamp
        l, r = pts[33], pts[263]
        eye_span_raw = max(1., float(np.linalg.norm(r-l)))
        eye_span = float(self.span(eye_span_raw, dt, scale=eye_span_raw))
        patch = np.empty(PATCH_SHAPE, np.uint8)
        S = SCALE
        aspect = .5
        sharp = []
        for i, outline in enumerate(OUTLINES):
            contour = pts[outline]
            left, right = contour[0], pts[[133, 263, 291][i]]
            axis = right-left
            span = float(np.linalg.norm(axis))
            if span < 2:
                return None
            unit = axis/span
            vertical = np.array([-unit[1], unit[0]])
            center = (left+right)/2
            if i == 2:
                projected = contour@vertical
                center = center+vertical*((projected.max()+projected.min())*.5-center@vertical)
            cx, cy, angle, span = self.crops[i]([center[0], center[1], math.atan2(unit[1], unit[0]), span], dt, scale=eye_span)
            center = np.array([cx, cy], np.float32)
            unit = np.array([math.cos(angle), math.sin(angle)], np.float32)
            vertical = np.array([-unit[1], unit[0]], np.float32)
            width_px = span*(1.12 if i == 2 else 1.38)
            height_px = span*.70
            # The filter may trail a fast head movement by a few pixels. Never let it trail
            # the content: shift the crop just enough to keep every contour point inside it.
            along = (contour-center)@unit
            room = width_px*.5*(.90 if i == 2 else .80)
            shift = max(0., float(along.max())-room)+min(0., float(along.min())+room)
            if i < 2:
                across = (contour-center)@vertical
                vroom = height_px*.5*.80
                vshift = max(0., float(across.max())-vroom)+min(0., float(across.min())+vroom)
            else:
                vshift = 0.
            if shift or vshift:
                center = center+unit*shift+vertical*vshift
                self.crops[i].value[:2] = center
            if i == 2:
                # The current lips must fit the steady crop: size the tile around them, with
                # room above the upper lip for the upper-lip reach. The room is added on both
                # sides so the lips stay centred in the tile and on the avatar.
                offsets = (contour-center)@vertical
                reach_img = max(0., lip_reach)/100*.12*span
                needed = max(span*.20, 2*max(float(offsets.max()), reach_img-float(offsets.min())))*1.12
                if self.lip_height is None or dt <= 0 or dt >= .25 or needed > self.lip_height:
                    self.lip_height = needed
                else:
                    self.lip_height += (needed-self.lip_height)*(1-math.exp(-dt/.12))
                height_px = min(max(self.lip_height, needed), width_px*.95)
            matrix = cv2.getAffineTransform(np.float32([center, center+unit*width_px/2, center+vertical*height_px/2]),
                                            np.float32([[48*S, 32*S], [96*S, 32*S], [48*S, 64*S]]))
            tile = patch[:, TILE_W*i:TILE_W*(i+1)]
            if sensor is None:
                rgb_tile = cv2.warpAffine(rgb, matrix, (TILE_W, TILE_H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
                cv2.cvtColor(rgb_tile, cv2.COLOR_RGB2RGBA, dst=tile)
            else:
                # Map each destination tile directly into the unmirrored sensor image.
                # Resize uses pixel centers. Include the half-pixel offset in both axes.
                inverse = cv2.invertAffineTransform(matrix)
                sx, sy = sensor.shape[1]/width, sensor.shape[0]/height
                inverse[0] *= -sx
                inverse[0, 2] += sensor.shape[1]-.5-.5*sx
                inverse[1] *= sy
                inverse[1, 2] += .5*sy-.5
                bgr = cv2.warpAffine(sensor, inverse, (TILE_W, TILE_H), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
                                     borderMode=cv2.BORDER_REPLICATE)
                cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA, dst=tile)
                rgb_tile = tile[:, :, :3]
            sharp.append(tile_sharpness(rgb_tile))
            if i == 2:
                lip = cv2.transform(contour[None], matrix)[0]
                mask = np.zeros((TILE_H, TILE_W), np.uint8)
                cv2.fillPoly(mask, [np.int32(np.round(lip*16))], 255, lineType=cv2.LINE_AA, shift=4)
                inside = cv2.transform(pts[[78, 81, 13, 311, 308, 402, 14, 178]][None], matrix)[0]
                tissue = mask.copy()
                cv2.fillPoly(tissue, [np.int32(np.round(inside*16))], 0, lineType=cv2.LINE_AA, shift=4)
                selected = tissue > 180
                upper = None
                if lip_reach > 0:
                    reach_tile = max(0., lip_reach)/100*.12*span*(64*S/height_px)
                    upper = self.upper_lip(rgb_tile, lip, selected, reach_tile, dt)
                if matte:
                    if np.any(selected):
                        pixels = rgb_tile[selected]
                        # Every other lip pixel gives the same median tone at half the sort cost.
                        tone = np.median(pixels[::2] if len(pixels) > 512 else pixels, axis=0).astype(np.float32)
                        level = cv2.GaussianBlur(tissue, (6*S+1, 6*S+1), 2*S).astype(np.float32)*(.16/255)+.86
                        tint = level[:, :, None]*(tone*.91+tone.mean()*.09)
                        blended = cv2.addWeighted(rgb_tile.astype(np.float32), .30, tint, .70, 0)
                        np.copyto(tile[:, :, :3], np.clip(blended, 0, 255).astype(np.uint8), where=selected[:, :, None])
                alpha = cv2.GaussianBlur(mask, (2*S+1, 2*S+1), .65*S)
                tile[:, :, 3] = alpha if upper is None else np.maximum(alpha, upper)
                aspect = float(np.clip(height_px/width_px, .16, .95))
        mid = (l+r)*.5
        yaw = float(np.clip((pts[1, 0]-mid[0])/eye_span_raw*2, -.9, .9))
        pitch = float(np.clip(((pts[1, 1]-mid[1])/eye_span_raw-.46)*1.25, -.5, .5))
        roll = -math.atan2(r[1]-l[1], r[0]-l[0])
        # Inner-lip aperture across the mouth, measured perpendicular to the mouth line.
        mouth_axis = pts[291]-pts[61]
        normal = np.array([-mouth_axis[1], mouth_axis[0]])/max(1., float(np.linalg.norm(mouth_axis)))
        gaps = [abs(float((pts[b]-pts[a])@normal)) for a, b in [(81, 178), (13, 14), (311, 402)]]
        aperture = (gaps[1]*.6+min(gaps[0], gaps[2])*.4)/eye_span
        # Closed-mouth level: follows the smallest recent aperture and drifts up slowly, so a
        # person whose lips never quite meet in the landmarks still reads as closed.
        # It starts at a typical closed level so a session that begins mid-sentence still
        # reads open, and it can never learn a wide-open mouth as closed.
        if self.baseline is None:
            self.baseline = min(aperture, .03)
        else:
            self.baseline = min(aperture, self.baseline+max(0., dt)*.01, .05)
        opening = float(np.clip(self.opening(np.clip((aperture-self.baseline-.008)/.24, 0, 1), dt), 0, 1))
        # Grade this frame for the held capture, against this person's own typical pose,
        # eye openness and tile sharpness.
        ear = eye_openness(pts)
        eye_sharp = (sharp[0]+sharp[1])*.5
        frontal = (self.yaw_ref is not None and abs(yaw-self.yaw_ref) < .25 and abs(pitch-self.pitch_ref) < .20)
        good_eyes = bool(frontal and self.ear_ref is not None and ear > .75*self.ear_ref
                         and eye_sharp > .5*self.sharp_ref[0])
        good_mouth = bool(frontal and opening < .25 and self.sharp_ref[1] is not None and sharp[2] > .5*self.sharp_ref[1])
        self.yaw_ref = self._ema(self.yaw_ref, yaw, dt)
        self.pitch_ref = self._ema(self.pitch_ref, pitch, dt)
        if self.ear_ref is None or ear > .7*self.ear_ref:  # blinks do not lower the open-eye level
            self.ear_ref = self._ema(self.ear_ref, ear, dt)
        self.sharp_ref = [self._ema(self.sharp_ref[0], eye_sharp, dt), self._ema(self.sharp_ref[1], sharp[2], dt)]
        return {"pose": (float((mid[0]/width-.5)*1.9), float((.43-mid[1]/height)*1.3), yaw, roll, pitch, opening, aspect),
                "patch": patch, "good": (good_eyes, good_mouth)}


def measure(rgb, landmarks, matte=False, sensor=None):
    """Single-frame measurement without temporal filtering (tools and tests)."""
    return FaceMeasure()(rgb, landmarks, 0., matte, sensor)


class Mirror:
    """Downscale and mirror a BGR camera frame into a reusable RGB buffer.

    Reversing a row of BGR bytes mirrors the pixels and gives RGB order in one pass.
    Each worker owns its own instance, so detector calls never race on a buffer.
    """
    def __init__(self, width):
        self.width = width
        self.small = None
        self.buffer = None

    def __call__(self, raw):
        if raw.shape[1] > self.width:
            size = (self.width, round(raw.shape[0]*self.width/raw.shape[1]))
            if self.small is None or self.small.shape[:2] != size[::-1]:
                self.small = None
            self.small = cv2.resize(raw, size, dst=self.small, interpolation=cv2.INTER_AREA)
            raw = self.small
        height, width = raw.shape[:2]
        rows = raw.reshape(height, width*3)
        if self.buffer is not None and self.buffer.shape != rows.shape:
            self.buffer = None
        self.buffer = cv2.flip(rows, 1, dst=self.buffer)
        rgb = self.buffer.reshape(height, width, 3)
        rgb.flags.writeable = False
        return rgb


def wants(live):
    arms = not live.get("faceOnly") and any(live.get(k) for k in ("arms","floaters","ninjas"))
    torso = bool(live.get("torso") and not live.get("faceOnly"))
    return arms, torso


class Rig:
    """Latest result from each worker. Composed into one snapshot under the frame lock."""
    def __init__(self, shared):
        self.shared = shared
        # Face worker
        self.stamp = 0.
        self.data = None
        self.backend = "Starting tracker"
        self.mouth = None
        self.heat = 0.
        self.aspect = 4/3
        # Pose worker
        self.body_stamp = self.body_ready = 0.
        self.skeleton = []
        self.shoulder = (0., 0.)
        self.pose_needed = False
        # Hand worker
        self.hand_stamp = self.hand_ready = 0.
        self.fingers = []

    def publish(self, **changes):
        shared = self.shared
        with shared.condition:
            for key, value in changes.items():
                setattr(self, key, value)
            if not self.stamp:
                return
            # The body sample is current when it came from a frame within the pose cadence.
            complete = not self.pose_needed or (self.body_stamp and abs(self.stamp-self.body_stamp) <= .15)
            # Replace the snapshot. Published arrays/lists are read-only to the producers
            # until replaced by the next observation.
            shared.rig = dict(body_ready=self.body_ready, hand_ready=self.hand_ready, stamp=self.stamp,
                              body_stamp=self.body_stamp, hand_stamp=self.hand_stamp, breath=self.heat,
                              shoulders=self.skeleton, hands=self.fingers, mouth=self.mouth, aspect=self.aspect,
                              tracking_complete=bool(complete))
            shared.result = (self.stamp, self.data, self.shoulder, self.backend)


class Frames:
    """Wait for camera frames newer than the last one this worker processed."""
    def __init__(self, shared, stop, cfg):
        self.shared, self.stop, self.cfg = shared, stop, cfg
        self.seen = 0

    def next(self, timeout=.25):
        shared = self.shared
        with shared.condition:
            shared.condition.wait_for(lambda: shared.sequence != self.seen or self.stop.is_set(), timeout=timeout)
            if self.stop.is_set() or shared.sequence == self.seen or shared.image is None:
                return None
            self.seen = shared.sequence
            return shared.image, shared.timestamp, shared.live_options or self.cfg


def pose_worker(shared, stop, cfg, rig):
    perf.name_thread("JointCam pose")
    frames = Frames(shared, stop, cfg)
    mirror = Mirror(POSE_WIDTH)
    body = None
    next_body = 0.
    try:
        while not stop.is_set():
            frame = frames.next()
            if frame is None:
                continue
            raw, stamp, live = frame
            arms, torso_active = wants(live)
            pose_needed = arms or torso_active
            if not pose_needed:
                if body is not None:
                    body.close()
                    body = None
                if rig.pose_needed or rig.skeleton:
                    rig.publish(pose_needed=False, skeleton=[], shoulder=(0., 0.), body_stamp=0., body_ready=0.)
                next_body = 0.
                continue
            if not rig.pose_needed:
                rig.publish(pose_needed=True)
            if not torso_active and rig.shoulder != (0., 0.):
                rig.publish(shoulder=(0., 0.))
            if stamp < next_body:
                continue
            next_body = stamp+(1/24 if arms else .10)
            rgb = mirror(raw)
            if body is None:
                body = solution("pose").Pose(model_complexity=1, enable_segmentation=False)
            pose = body.process(rgb).pose_landmarks
            shoulder = (0., 0.)
            # Calibration and hand scheduling use original pose indices 11 through 16.
            skeleton = ([None]*11+[dict(x=1-q.x, y=q.y, z=q.z, visibility=q.visibility)
                                   for q in pose.landmark[11:17]]) if pose else []
            if pose and torso_active:
                a, b = sorted([pose.landmark[11], pose.landmark[12]], key=lambda p: p.x)
                if min(a.visibility, b.visibility) > .6:
                    shoulder = (-math.atan2((b.y-a.y)*rgb.shape[0], (b.x-a.x)*rgb.shape[1])*.65,
                                ((a.x+b.x)*.5-.5)*.55)
            rig.publish(body_stamp=stamp, body_ready=time.monotonic(), skeleton=skeleton, shoulder=shoulder)
    finally:
        if body is not None:
            body.close()


def hand_worker(shared, stop, cfg, rig):
    perf.name_thread("JointCam hands")
    frames = Frames(shared, stop, cfg)
    mirror = Mirror(HAND_WIDTH)
    hands = None
    hand_complexity = None
    hand_usage = -100.
    next_hands = 0.
    try:
        while not stop.is_set():
            frame = frames.next()
            if frame is None:
                continue
            raw, stamp, live = frame
            arms, _ = wants(live)
            if not arms:
                if hands is not None:
                    hands.close()
                    hands = None
                if rig.fingers or rig.hand_stamp:
                    rig.publish(fingers=[], hand_stamp=0., hand_ready=0.)
                next_hands = 0.
                hand_usage = -100.
                continue
            if stamp < next_hands:
                continue
            next_hands = stamp+1/40
            skeleton = rig.skeleton
            visible = any(skeleton[i]["visibility"] > .48 and 0 < skeleton[i]["x"] < 1 and 0 < skeleton[i]["y"] < 1
                          for i in (15, 16)) if skeleton else False
            elbow_visible = any(p["visibility"] > .55 and 0 < p["x"] < 1 and 0 < p["y"] < 1 for p in skeleton[13:15])
            if not visible and not elbow_visible and hands is not None and stamp-hand_usage > 15:
                hands.close()
                hands = None
            if not visible:
                next_hands = stamp+(.08 if elbow_visible else .12)
            fingers = []
            if visible or elbow_visible:
                complexity = int(live.get("fullHands", True))
                if hands is not None and hand_complexity != complexity:
                    hands.close()
                    hands = None
                if visible:
                    hand_usage = stamp
                if hands is None:
                    hand_complexity = complexity
                    hands = solution("hands").Hands(model_complexity=complexity, max_num_hands=2,
                                                    min_detection_confidence=.55, min_tracking_confidence=.55)
                found = hands.process(mirror(raw)).multi_hand_landmarks or []
                if found:
                    hand_usage = stamp
                    next_hands = stamp+1/40
                fingers = [[dict(x=1-q.x, y=q.y, z=q.z) for q in hand.landmark] for hand in found]
            rig.publish(hand_stamp=stamp, hand_ready=time.monotonic(), fingers=fingers)
    finally:
        if hands is not None:
            hands.close()


def track(shared, stop, torso):
    """Run face tracking on this thread and pose/hand models on their own threads.

    1.0 ran all three detectors in sequence for each camera frame, so a face update waited
    behind pose and hand inference. The face path now runs at the full camera rate while
    the body models work in parallel on the newest frame each time they become free.
    The NVIDIA runtime stays on this thread, as before, because its CUDA state is per thread.
    """
    cfg = torso if isinstance(torso, dict) else {"torso": torso}
    perf.name_thread("JointCam face")
    rig = Rig(shared)
    errors = []

    def guarded(fn):
        try:
            fn(shared, stop, cfg, rig)
        except Exception as exc:
            errors.append(exc)
            stop.set()
            with shared.condition:
                shared.condition.notify_all()

    workers = [threading.Thread(target=guarded, args=(fn,), daemon=True) for fn in (pose_worker, hand_worker)]
    for worker in workers:
        worker.start()
    try:
        with perf.mmcss("Capture"):
            face_loop(shared, stop, cfg, rig)
    finally:
        stop.set()
        with shared.condition:
            shared.condition.notify_all()
        for worker in workers:
            worker.join()
    if errors:
        raise errors[0]


def face_loop(shared, stop, cfg, rig):
    from nativeface import NativeFace
    from breath import Breath
    native = face = None
    breath = Breath()
    S = SCALE
    lip_mask = np.zeros((TILE_H, TILE_W), np.uint8)
    cv2.ellipse(lip_mask, (48*S, 32*S), (42*S, 23*S), 0, 0, 360, 255, -1, cv2.LINE_AA)
    frames = Frames(shared, stop, cfg)
    mirror = Mirror(FACE_WIDTH)
    measurer = FaceMeasure()
    try:
        while not stop.is_set():
            frame = frames.next()
            if frame is None:
                continue
            raw, stamp, live = frame
            manual = live.get("manual", False)
            if manual and native is not None:
                native.close()
                if face is not None:
                    face.close()
                native = face = None
            elif not manual and native is None:
                native = NativeFace()
            rgb = mirror(raw)
            mouth = None
            if manual:
                # Cut fixed tiles from the full camera frame. The frame is unmirrored BGR,
                # so mirror the centre, then flip each cut and reverse its channels.
                H, W = raw.shape[:2]
                x, ey, my, d = [live.get(k, cfg[k])/100 for k in ("centerX", "eyeY", "mouthY", "spacing")]
                patch = np.empty(PATCH_SHAPE, np.uint8)
                for i, (cx, cy, sx, sy) in enumerate(((x-d/2, ey, .62, .39), (x+d/2, ey, .62, .39), (x, my, .94, .61))):
                    cut = cv2.getRectSubPix(raw, (max(2, int(W*d*sx)), max(2, int(W*d*sy))), ((1-cx)*W, cy*H))
                    tile = patch[:, i*TILE_W:(i+1)*TILE_W]
                    tile[:, :, :3] = cv2.resize(np.ascontiguousarray(cut[:, ::-1, ::-1]), (TILE_W, TILE_H),
                                                interpolation=cv2.INTER_AREA if cut.shape[1] > TILE_W else cv2.INTER_CUBIC)
                    tile[:, :, 3] = lip_mask if i == 2 else 255
                data = {"pose": (0., 0., 0., 0., 0., .5, .5), "patch": patch}
                mouth = {"x": x, "y": my, "span": d}
            else:
                landmarks = None
                if native.state is not None:
                    landmarks = native.detect(rgb)
                if native.state is None:
                    if face is None:
                        face = solution("face_mesh").FaceMesh(max_num_faces=1, refine_landmarks=True,
                                                              min_detection_confidence=.55, min_tracking_confidence=.6)
                    result = face.process(rgb)
                    landmarks = result.multi_face_landmarks[0].landmark if result.multi_face_landmarks else None
                # Tiles come from the full-resolution frame for every camera.
                data = measurer(rgb, landmarks, stamp, live.get("matte", cfg.get("matte", False)), raw,
                                live.get("lipReach", cfg.get("lipReach", 100))) if landmarks else None
                if landmarks:
                    mouth = {"x": (landmarks[13].x+landmarks[14].x)/2, "y": (landmarks[13].y+landmarks[14].y)/2,
                             "span": abs(landmarks[33].x-landmarks[263].x)}
            heat = breath.sample(rgb, mouth, stamp)
            if mouth:
                mouth["x"] = 1-mouth["x"]
            backend = "Manual placement" if manual else "NVIDIA RTX" if native.state is not None else "CPU fallback"
            rig.publish(stamp=stamp, data=data, backend=backend, mouth=mouth, heat=heat,
                        aspect=rgb.shape[1]/rgb.shape[0])
    finally:
        if face is not None:
            face.close()
        if native is not None:
            native.close()

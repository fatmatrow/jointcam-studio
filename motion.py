import math
from facetiles import TILE_W

# When the camera loses the face, show the held capture after this long. Brief dropouts
# (a hand passing, one missed frame) would otherwise flicker between live and held.
HOLD_AFTER = .10
# Keep the head where it was through a short dropout, then ease it back to rest.
POSE_HOLD = .50
REST_EXPRESSION = [.58, .49]


class Motion:
    """Filter head and shoulder movement on the render clock; keep lip timing live.

    It also keeps the held capture: the latest good eye tiles and the latest good mouth tile,
    chosen by the tracker's per-frame grading (facing the camera, eyes open, mouth relaxed,
    sharp). When the face is lost the avatar keeps those instead of falling back to the
    cartoon face. Only a session that has never seen a face shows the cartoon face.
    """
    def __init__(self, held=None):
        self.values = [0.] * 7
        self.torso = (0., 0., 0.)
        self.patch = None
        self.seen = self.previous = float("-inf")
        self.target = [0.] * 7
        self.expression = list(REST_EXPRESSION)
        self.held = held          # (patch, [opening, lip aspect]) or None
        self.remembered = None    # camera stamp of the last sample offered to the hold
        self.holding = False

    def remember(self, face, stamp):
        """Fold one new tracker sample into the held capture."""
        if stamp == self.remembered or face.get("patch") is None:
            return
        self.remembered = stamp
        patch = face["patch"]
        if self.held is None:
            # First face of the session: keep it until a frame that grades as good arrives.
            self.held = (patch.copy(), list(face["pose"][5:]))
            return
        eyes, mouth = face.get("good", (False, False))
        if not (eyes or mouth):
            return
        # A new array each time, so renderers that cache by identity upload the change.
        held, expression = self.held[0].copy(), self.held[1]
        if eyes:
            held[:, :2*TILE_W] = patch[:, :2*TILE_W]
        if mouth:
            held[:, 2*TILE_W:] = patch[:, 2*TILE_W:]
            expression = list(face["pose"][5:])
        self.held = (held, expression)

    def sample(self, now, stamp, face, body, strength):
        dt = min(.08, max(0., now - self.previous))
        self.previous = now
        if face:
            self.seen = stamp
            self.holding = False
            self.patch = face["patch"]
            self.expression = face["pose"][5:]
            self.target[:5] = face["pose"][:5]
            self.remember(face, stamp)
        else:
            lost = now - self.seen
            if lost > HOLD_AFTER:
                if self.held is not None:
                    self.holding = True
                    self.patch = self.held[0]
                    self.expression = list(self.held[1])
                else:
                    self.patch = None
                    self.expression = list(REST_EXPRESSION)
            if lost > POSE_HOLD:
                self.target[:5] = [0.] * 5
        self.target[5:] = body
        for i, target in enumerate(self.target):
            delta = target - self.values[i]
            if delta==0.:continue
            if i == 3:
                delta = math.atan2(math.sin(delta), math.cos(delta))
            # Low gain on small fluctuations, faster response to a deliberate move.
            tau = (.012 + .16 / (1 + 28*abs(delta))) * strength/100
            fraction = -math.expm1(-dt/tau) if tau else 1.
            self.values[i] += fraction * delta
        pose = self.values[:5] + list(self.expression)
        # Head turns lead. The trunk picks up a smaller share on a separate clock.
        x, y, yaw, roll, pitch = pose[:5]
        targets = (.48*pitch + .16*y, .46*yaw, .55*roll - .24*x)
        blend = -math.expm1(-dt/.115)
        def follow(previous, target):
            target = max(-.55, min(.55, target))
            return target if abs(target-previous) < .0001 else previous + blend*(target-previous)
        self.torso = tuple(follow(previous, target) for previous, target in zip(self.torso, targets))
        return {"pose": pose, "patch": self.patch}, tuple(self.values[5:])

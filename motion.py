import math


class Motion:
    """Filter head and shoulder movement on the render clock; keep lip timing live."""
    def __init__(self):
        self.values = [0.] * 7
        self.torso = (0., 0., 0.)
        self.patch = None
        self.seen = self.previous = float("-inf")
        self.target = [0.] * 7
        self.expression = [.58, .49]

    def sample(self, now, stamp, face, body, strength):
        dt = min(.08, max(0., now - self.previous))
        self.previous = now
        if face:
            self.seen = stamp
            self.patch = face["patch"]
            self.expression = face["pose"][5:]
            self.target[:5] = face["pose"][:5]
        elif now - self.seen > .18:
            self.patch = None
            self.expression = [.58, .49]
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

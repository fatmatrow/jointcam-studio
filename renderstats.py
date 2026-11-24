"""Sample the current GL command stream without waiting for unfinished work."""
from collections import deque
from math import ceil
from statistics import median
from time import perf_counter_ns
from PySide6.QtOpenGL import QOpenGLTimerQuery


class RenderStats:
    stages = ("Avatar", "Overlays", "Resolve", "Spout")
    labels = {"Resolve": "Resolve + finish"}

    def __init__(self):
        self.queries = {}
        self.pending = set()
        self.history = {}
        self.next_sample = 0.
        self.failed = False

    def sample(self, now):
        if self.failed or now < self.next_sample:
            return False
        self.next_sample = now + .1
        if not self.queries:
            for stage in self.stages:
                pair = (QOpenGLTimerQuery(), QOpenGLTimerQuery())
                self.queries[stage] = pair
                if not all(q.create() for q in pair):
                    self.close()
                    self.failed = True
                    return False
        for stage in tuple(self.pending):
            start, end = self.queries[stage]
            if start.isResultAvailable() and end.isResultAvailable():
                elapsed = end.waitForResult() - start.waitForResult()
                if elapsed >= 0:
                    self.add(stage, elapsed)
                self.pending.remove(stage)
        return not self.pending

    def add(self, name, nanos):
        if name not in self.history:
            self.history[name] = deque(maxlen=120)
        self.history[name].append(nanos / 1e6)

    def begin(self, name):
        self.queries[name][0].recordTimestamp()

    def end(self, name):
        self.queries[name][1].recordTimestamp()
        self.pending.add(name)

    def cpu_call(self, name, func, *args):
        start = perf_counter_ns()
        try:
            return func(*args)
        finally:
            self.add(name, perf_counter_ns() - start)

    def report(self):
        if self.failed:
            return "The graphics driver did not provide GPU timers."
        lines = []
        for name in (*self.stages, "Overlay prep (CPU)", "Spout call (CPU)", "Readback (CPU)"):
            values = self.history.get(name)
            if values:
                high = sorted(values)[ceil(.95 * len(values)) - 1]
                lines.append(f"{self.labels.get(name, name)}   {median(values):.2f} / {high:.2f} ms   (n={len(values)})")
        return "\n".join(lines) or "Waiting for rendered frames…"

    def close(self):
        for pair in self.queries.values():
            for q in pair:
                if q.isCreated():
                    q.destroy()
        self.queries.clear()
        self.pending.clear()

import math
import time

import numpy as np


class Loudness:
    def __init__(self):
        self.db = self.floor = -65.
        self.duration = 0.
        self.last_yell = -100.
        self.armed = True

    def sample(self, mono, rate, sensitivity, now):
        duration = len(mono)/rate
        power = float(np.mean(mono * mono))
        self.db = max(-80., 10*math.log10(max(power, 1e-8)))
        threshold = max(-24., min(-10., self.floor+14.)) - 12*math.log2(sensitivity/100)
        if self.db >= threshold:
            self.duration = min(.16, self.duration + duration)
            if self.armed and self.duration >= .12 and now-self.last_yell > .85:
                self.last_yell = now
                self.armed = False
        else:
            self.duration = max(0., self.duration-2*duration)
            if not self.duration and self.db < threshold-3:
                self.armed = True
            self.floor += (max(-65., self.db)-self.floor) * (-math.expm1(-duration/2))


class Microphone:
    def __init__(self):
        self.api = self.stream = None
        self.sensitivity = 100
        self.signal = Loudness()
        self.received = 0.
        self.error = ""

    def backend(self):
        import pyaudiowpatch as pa
        if self.api is None:
            self.api = pa.PyAudio()
        return self.api

    def devices(self):
        import pyaudiowpatch as pa
        api = self.backend()
        devices = []
        for adapter, suffix in ((pa.paWASAPI, ""), (pa.paMME, " · MME")):
            try:
                entries = list(api.get_device_info_generator_by_host_api(host_api_type=adapter))
            except (OSError, ValueError):
                continue
            for device in entries:
                if device["maxInputChannels"]:
                    kind = "Playback" if device.get("isLoopbackDevice") else "Microphone"
                    label = f"{kind} · {device['name']}{suffix}"
                    if any(name == label for name, _ in devices):
                        label += f" (device {device['index']})"
                    devices.append((label, device))
        return devices

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        if self.api is not None:
            self.api.terminate()
            self.api = None
        self.signal = Loudness()
        self.received = 0.
        self.error = ""

    def open(self, key):
        self.close()
        if not key:
            return
        import pyaudiowpatch as pa
        try:
            api = self.backend()
            if key == "default-mic":
                try:
                    device = api.get_default_wasapi_device(d_in=True)
                except (OSError, ValueError):
                    device = api.get_default_input_device_info()
            elif key == "default-playback":
                device = api.get_default_wasapi_loopback()
            else:
                device = dict(self.devices()).get(key)
                if device is None:
                    raise OSError("The selected Windows audio device is unavailable.")
            rate = round(device["defaultSampleRate"])
            channels = int(device["maxInputChannels"])
            if channels < 1:
                raise OSError("The selected device has no input channels.")
            # Shared endpoints can advertise a float or a PCM mix format.
            candidates = [(channels,pa.paFloat32), (channels,pa.paInt16)]
            if channels>1 and not device.get("isLoopbackDevice"):
                candidates.extend([(1,pa.paFloat32),(1,pa.paInt16)])
            for count, fmt in candidates:
                try:
                    api.is_format_supported(rate,input_device=device["index"],
                                            input_channels=count,input_format=fmt)
                    channels = count
                    break
                except ValueError:
                    continue
            else:
                raise OSError("This device rejected its default format. Try another microphone or MME input.")
            dtype = np.float32 if fmt==pa.paFloat32 else np.int16
            def samples(data, frames, timing, status):
                try:
                    block = np.frombuffer(data, dtype=dtype).reshape(-1, channels)
                    if dtype==np.int16: block=block.astype(np.float32)/32768.
                    if len(block):
                        channel = int(np.argmax(np.sum(block*block, axis=0))) if channels>1 else 0
                        mono = block[:, channel]
                        now = time.monotonic()
                        self.signal.sample(mono, rate, self.sensitivity, now)
                        self.received = now
                except Exception as exc:
                    self.error = str(exc)
                    return None, pa.paAbort
                return None, pa.paContinue
            self.stream = api.open(format=fmt, channels=channels, rate=rate,
                input=True, input_device_index=device["index"], frames_per_buffer=max(128,rate//50),
                stream_callback=samples)
        except Exception:
            self.close()
            raise

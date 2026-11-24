"""Read the tracked camera timestamp back from a visible OBS source projector."""
import ctypes as C
from ctypes import wintypes as W
import math
import os
import time
import zlib
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter

# A sync byte, a 32-bit monotonic millisecond timestamp, and a checksum.
CELL = 12
LEFT = (960 - 48 * CELL) // 2
TOP = 18


def marker(stamp):
    payload = b'\xd3' + (round(stamp * 1000) & 0xffffffff).to_bytes(4, 'big')
    return payload + bytes([zlib.crc32(payload) & 255])


def draw_marker(device, stamp):
    painter = QPainter(device)
    painter.scale(device.width()/960, device.height()/540)
    try:
        for i, byte in enumerate(marker(stamp)):
            for bit in range(8):
                color = Qt.white if byte & (128 >> bit) else Qt.black
                painter.fillRect(LEFT + CELL*(8*i+bit), TOP, CELL, CELL, color)
    finally:
        painter.end()


def decode(levels, now):
    if len(levels) != 48 or any(55 < level < 200 for level in levels):
        return None
    code = sum((int(level >= 200) << (47-i)) for i, level in enumerate(levels)).to_bytes(6, 'big')
    if code[0] != 0xd3 or (zlib.crc32(code[:5]) & 255) != code[5]:
        return None
    return (round(now*1000) - int.from_bytes(code[1:5], 'big')) & 0xffffffff


def obs_windows():
    if os.name != "nt":
        return {}
    user, kernel = C.windll.user32, C.windll.kernel32
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenProcess.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    result = {}
    @C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def visit(hwnd, _):
        if not user.IsWindowVisible(W.HWND(hwnd)):
            return True
        pid = W.DWORD()
        user.GetWindowThreadProcessId(W.HWND(hwnd), C.byref(pid))
        handle = kernel.OpenProcess(0x1000, False, pid.value)
        if handle:
            try:
                path = C.create_unicode_buffer(1024)
                length = W.DWORD(len(path))
                if kernel.QueryFullProcessImageNameW(handle, 0, path, C.byref(length)) and os.path.basename(path.value).lower() in ('obs64.exe','obs32.exe'):
                    title = C.create_unicode_buffer(512)
                    if user.GetWindowTextW(W.HWND(hwnd), title, len(title)):
                        result[f"{title.value}  [{hwnd:X}]"] = hwnd
            finally:
                kernel.CloseHandle(handle)
        return True
    user.EnumWindows(visit, 0)
    return result


def measure_projector(hwnd, stop):
    import mss
    user = C.windll.user32
    handle = W.HWND(hwnd)
    ages = []
    attempts = 0
    start = time.monotonic()
    with mss.mss() as screen:
        while time.monotonic() - start < 30 and not stop.is_set():
            rect, origin = W.RECT(), W.POINT()
            if not user.GetClientRect(handle, C.byref(rect)) or not user.ClientToScreen(handle, C.byref(origin)):
                raise RuntimeError("The selected projector closed.")
            attempts += 1
            scale = min(rect.right/960, rect.bottom/540)
            if scale >= .25 and not user.IsIconic(handle):
                x = origin.x + (rect.right - 960*scale)/2
                y = origin.y + (rect.bottom - 540*scale)/2
                xs = [round(x + (LEFT + CELL*(i+.5))*scale) for i in range(48)]
                top = round(y+(TOP+CELL/2)*scale)
                before = time.monotonic()
                strip = screen.grab((xs[0], top, xs[-1]+1, top+1))
                now = (before + time.monotonic())/2
                age = decode([strip.raw[(px-xs[0])*4+1] for px in xs], now)
                if age is not None:
                    ages.append(age)
            stop.wait(.034)
    if stop.is_set():
        return ""
    coverage = f"{len(ages)}/{attempts} samples decoded"
    if not ages or len(ages) < attempts*.90:
        return f"Inconclusive ({coverage}). Check camera tracking and keep the entire OBS source projector visible."
    ages.sort()
    percentile = lambda q: ages[math.ceil(q*len(ages))-1]
    return f"OBS projector age · median {percentile(.50)} ms · p95 {percentile(.95)} ms · maximum {max(ages)} ms ({coverage})"

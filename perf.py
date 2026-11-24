"""Process and thread scheduling for a capture/render workload that shares the PC with a game.

Everything here is best effort. Each call returns quietly on systems that lack the API,
so startup never depends on it.
"""
import os
import sys
import threading

WINDOWS = sys.platform == "win32"
_state = {"timer": False, "affinity": None, "ccd_masks": None}


_kernel32 = None


def _kernel():
    """kernel32 with explicit 64-bit prototypes. Handles must not pass through as C int."""
    global _kernel32
    if _kernel32 is None:
        import ctypes
        from ctypes import wintypes as W
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = W.HANDLE
        k32.GetCurrentProcess.argtypes = []
        k32.SetProcessInformation.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD]
        k32.SetProcessInformation.restype = W.BOOL
        k32.SetPriorityClass.argtypes = [W.HANDLE, W.DWORD]
        k32.SetPriorityClass.restype = W.BOOL
        k32.SetProcessAffinityMask.argtypes = [W.HANDLE, ctypes.c_size_t]
        k32.SetProcessAffinityMask.restype = W.BOOL
        k32.GetProcessAffinityMask.argtypes = [W.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
        k32.GetProcessAffinityMask.restype = W.BOOL
        k32.GetLogicalProcessorInformationEx.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(W.DWORD)]
        k32.GetLogicalProcessorInformationEx.restype = W.BOOL
        _kernel32 = k32
    return _kernel32


def configure_libraries():
    """Keep library thread pools from oversubscribing the CPU.

    The tracking workers already run face, pose and hand models in parallel. OpenCV's own
    parallel_for would otherwise start one thread per logical processor for tiny
    per-frame operations (resize, flip, warp) and spend more time waking them up than working.
    """
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    try:
        import cv2
        cv2.setNumThreads(4)
        cv2.setUseOptimized(True)
    except Exception:
        pass


def tune_process():
    """Call once at startup before the first window opens."""
    if not WINDOWS:
        return
    import ctypes
    from ctypes import wintypes as W
    try:
        # 1 ms scheduler granularity keeps the 60 FPS stage timer on its deadline.
        if ctypes.WinDLL("winmm").timeBeginPeriod(1) == 0:
            _state["timer"] = True
    except OSError:
        pass
    k32 = _kernel()
    process = k32.GetCurrentProcess()
    try:
        # Opt out of EcoQoS. Windows 11 otherwise throttles the CPU clock and ignores the
        # timer resolution for minimized or covered windows - exactly how JointCam runs
        # during a match - which shows up as stutter in the OBS feed.
        class PowerThrottling(ctypes.Structure):
            _fields_ = [("Version", W.ULONG), ("ControlMask", W.ULONG), ("StateMask", W.ULONG)]
        EXECUTION_SPEED, IGNORE_TIMER_RESOLUTION = 0x1, 0x4
        state = PowerThrottling(1, EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION, 0)
        if not k32.SetProcessInformation(process, 4, ctypes.byref(state), ctypes.sizeof(state)):
            # Windows 10 before 21H2 rejects the timer flag. Keep the execution-speed opt-out.
            state.ControlMask = EXECUTION_SPEED
            k32.SetProcessInformation(process, 4, ctypes.byref(state), ctypes.sizeof(state))
    except (AttributeError, OSError):
        pass
    try:
        k32.SetPriorityClass(process, 0x8000)  # ABOVE_NORMAL_PRIORITY_CLASS
    except OSError:
        pass


def shutdown():
    if WINDOWS and _state["timer"]:
        import ctypes
        try:
            ctypes.WinDLL("winmm").timeEndPeriod(1)
        except OSError:
            pass
        _state["timer"] = False


def l3_groups():
    """Logical-processor masks that share an L3 cache (one per CCD on Ryzen 5000)."""
    if _state["ccd_masks"] is not None:
        return _state["ccd_masks"]
    masks = []
    if WINDOWS:
        import ctypes
        from ctypes import wintypes as W
        try:
            k32 = _kernel()
            length = W.DWORD(0)
            k32.GetLogicalProcessorInformationEx(2, None, ctypes.byref(length))  # RelationCache
            buffer = ctypes.create_string_buffer(length.value)
            if k32.GetLogicalProcessorInformationEx(2, buffer, ctypes.byref(length)):
                raw = buffer.raw
                offset = 0
                while offset < length.value:
                    size = int.from_bytes(raw[offset+4:offset+8], "little")
                    level = raw[offset+8]
                    group = int.from_bytes(raw[offset+48:offset+50], "little")
                    mask = int.from_bytes(raw[offset+40:offset+48], "little")
                    if level == 3 and group == 0 and mask:
                        masks.append(mask)
                    if size <= 0:
                        break
                    offset += size
        except (AttributeError, OSError, ValueError):
            masks = []
    masks = sorted(set(masks))
    _state["ccd_masks"] = masks
    return masks


def multi_ccd():
    return len(l3_groups()) >= 2


def isolate_on_last_ccd(enabled):
    """Keep JointCam's threads on the last CCD so a game keeps the first CCD's cache.

    Windows schedules games onto the preferred cores of the first CCD. Holding the tracker,
    renderer and audio threads on the other die avoids L3 contention and cross-die hops.
    Returns a short description of the active placement.
    """
    if not WINDOWS:
        return "Windows only"
    import ctypes
    k32 = _kernel()
    process = k32.GetCurrentProcess()
    groups = l3_groups()
    current, system = ctypes.c_size_t(), ctypes.c_size_t()
    if not k32.GetProcessAffinityMask(process, ctypes.byref(current), ctypes.byref(system)):
        return "CPU placement unavailable"
    if enabled and len(groups) >= 2:
        mask = groups[-1] & system.value
        if mask and k32.SetProcessAffinityMask(process, mask):
            _state["affinity"] = mask
            return f"Running on CPU die {len(groups)} of {len(groups)} ({bin(mask).count('1')} threads)"
    if _state["affinity"] is not None or not enabled:
        k32.SetProcessAffinityMask(process, system.value)
        _state["affinity"] = None
    return "Windows schedules all cores" if len(groups) >= 2 else "Single CPU die detected"


class mmcss:
    """Register the calling thread with the Multimedia Class Scheduler for its lifetime."""
    def __init__(self, task="Capture"):
        self.task = task
        self.handle = None

    def __enter__(self):
        if WINDOWS:
            import ctypes
            from ctypes import wintypes as W
            try:
                avrt = ctypes.WinDLL("avrt")
                avrt.AvSetMmThreadCharacteristicsW.restype = W.HANDLE
                avrt.AvSetMmThreadCharacteristicsW.argtypes = [W.LPCWSTR, ctypes.POINTER(W.DWORD)]
                avrt.AvRevertMmThreadCharacteristics.argtypes = [W.HANDLE]
                self.avrt = avrt
                index = W.DWORD(0)
                self.handle = avrt.AvSetMmThreadCharacteristicsW(self.task, ctypes.byref(index))
            except OSError:
                self.handle = None
        return self

    def __exit__(self, *exc):
        if self.handle:
            try:
                self.avrt.AvRevertMmThreadCharacteristics(self.handle)
            except OSError:
                pass
            self.handle = None
        return False


def name_thread(name):
    threading.current_thread().name = name

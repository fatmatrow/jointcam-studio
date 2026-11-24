import threading
import time
import perf

# Camera stream formats. Compressed MJPEG is the only way most USB 2 webcams reach
# 1080p60. Uncompressed YUY2 avoids the JPEG decode at low resolutions.
CODECS=("auto","mjpg","yuy2","nv12","driver")


def fourcc_text(value):
    value=int(value)
    text="".join(chr((value>>(8*i))&255) for i in range(4)).strip("\0 ")
    return text if text.isprintable() and text else ""


def choose_codec(codec,size,fps):
    if codec=="auto":
        pixels=size[0]*size[1] if size else 0
        return "mjpg" if pixels>640*480 or (fps or 0)>30 else None
    return None if codec=="driver" else codec

class Frames:
    def __init__(self):
        self.condition=threading.Condition()
        self.sequence=0
        self.timestamp=0.
        self.capture_rate=0.
        self.image=None
        self.result=(0.,None,(0.,0.),"Starting tracker")
        self.rig={}
        self.live_options={}
        self.driver_request=threading.Event()
        self.driver_message=""
        self.codec=""


def capture(shared,stop,index,size,fps,codec="auto"):
    import cv2
    perf.name_thread("JointCam capture")
    cam=cv2.VideoCapture(index,cv2.CAP_DSHOW)
    mm=perf.mmcss("Capture").__enter__()
    try:
        if not cam.isOpened():
            raise RuntimeError(f"Camera {index} could not be opened. Deactivate the physical camera in OBS, then select it again here.")
        requested=choose_codec(codec,size,fps)
        if requested:
            # DirectShow negotiates the media type when the size is applied. Request
            # the subtype first so the driver offers its compressed high-rate modes.
            cam.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*requested.upper()))
        if size:
            cam.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
            cam.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        if fps:cam.set(cv2.CAP_PROP_FPS,fps)
        with shared.condition:
            shared.codec=fourcc_text(cam.get(cv2.CAP_PROP_FOURCC)).upper()
        failures=0
        delivered=0
        start=time.monotonic()
        while not stop.is_set():
            if shared.driver_request.is_set():
                shared.driver_request.clear()
                try:
                    opened = cam.set(cv2.CAP_PROP_SETTINGS, 1)
                except cv2.error:
                    opened = False
                if not opened:
                    with shared.condition:
                        shared.driver_message = "The driver did not confirm a settings panel."
            ok,img=cam.read()
            if not ok:
                failures+=1
                if failures>=30:
                    raise RuntimeError("Camera stopped delivering frames. Check the device and restart JointCam.")
                stop.wait(.05)
                continue
            failures=0
            with shared.condition:
                shared.image=img
                shared.timestamp=time.monotonic()
                delivered+=1
                elapsed=shared.timestamp-start
                if elapsed>=1:
                    shared.capture_rate=delivered/elapsed
                    delivered=0
                    start=shared.timestamp
                shared.sequence+=1
                shared.condition.notify_all()
    finally:
        mm.__exit__(None,None,None)
        cam.release()


class CameraSession:
    """Serialize device changes so two captures never fight over a webcam."""
    def __init__(self):
        self.condition=threading.Condition()
        self.request=(None,False)
        self.revision=0
        self.closed=False
        self.shared=None
        self.message="Avatar preview"
        self.stop=None
        self.thread=threading.Thread(target=self._run,daemon=True)
        self.thread.start()

    def select(self,index,torso):
        with self.condition:
            self.request=(index,torso)
            self.revision+=1
            if self.stop: self.stop.set()
            self.shared=None
            self.message="Opening camera…" if index is not None else "Avatar preview"
            self.condition.notify_all()

    def set_tracking_option(self,key,value):
        # Update the pending request as well as the running worker. A camera may
        # still be opening when the user edits several placement fields.
        with self.condition:
            index,options=self.request
            if not isinstance(options,dict):return
            self.request=(index,dict(options,**{key:value}))
            if self.shared is not None:
                with self.shared.condition:
                    self.shared.live_options=dict(self.shared.live_options,**{key:value})

    def _run(self):
        seen=0
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.closed or self.revision!=seen)
                if self.closed: return
                seen=self.revision
                index,torso=self.request
                if index is None: continue
                stop=self.stop=threading.Event()
                shared=self.shared=Frames()
                shared.live_options=torso.copy()
            def guarded(fn,*args):
                try:
                    fn(shared,stop,*args)
                except Exception as exc:
                    with self.condition:
                        if self.revision==seen:
                            self.message=str(exc)
                    stop.set()
            def inference(shared,stop,torso):
                from tracking import track
                track(shared,stop,torso)
            threads=[threading.Thread(target=guarded,args=(fn,*args),daemon=True)
                     for fn,args in [(capture,(index,torso.get("input_size"),torso["fps"],torso.get("codec","auto"))),(inference,(torso,))]]
            for th in threads: th.start()
            stop.wait()
            with shared.condition: shared.condition.notify_all()
            for th in threads: th.join()
            with self.condition:
                if self.revision==seen: self.shared=None

    def request_driver_panel(self):
        with self.condition:
            if self.shared is None or self.stop.is_set():
                return False
            with self.shared.condition:
                self.shared.driver_message = ""
            self.shared.driver_request.set()
            return True

    def video_info(self):
        with self.condition:
            shared = self.shared
            message = self.message
        if shared is None:
            return message
        with shared.condition:
            if shared.image is None:
                return "Waiting for the first camera frame…"
            h, w = shared.image.shape[:2]
            rate = shared.capture_rate
            message = shared.driver_message
            codec = shared.codec
        return (f"Receiving {w} × {h}" + (f" · {rate:.1f} FPS" if rate else "") + (f" · {codec}" if codec else "")
                + (" · "+message if message else ""))

    def sample(self):
        with self.condition:
            shared,message=self.shared,self.message
        if shared is None: return None,(0.,0.),message,0.,{}
        with shared.condition:
            stamp,face,body,backend=shared.result
            rig=shared.rig
        if time.monotonic()-stamp>.55:
            state = backend+" · waiting for fresh input" if stamp else message
            return None,(0.,0.),state,stamp,{}
        state = "tracking" if face else "looking for your face"
        return face,body,backend+" · "+state,stamp,rig

    def close(self):
        with self.condition:
            self.closed=True
            if self.stop: self.stop.set()
            self.condition.notify_all()

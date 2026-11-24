import sys
import math
import numpy as np
import ctypes
from effects import Effects
from options import Options
from avatars import CHOICES
from microphone import Microphone
from water import BeakerWater
from karate import mesh_mounts,joint_mounts
from motion import Motion
import random
import json
import hashlib
from statistics import median
import threading
import time
from PySide6.QtCore import Qt, QRectF, QTimer, Signal, QSettings
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QBrush
from PySide6.QtWidgets import (QApplication,QButtonGroup,QMainWindow,QWidget,QFrame,QLabel,QPushButton,
                               QMessageBox,QComboBox,QSlider,QCheckBox,QHBoxLayout,QVBoxLayout,QSizePolicy)
from camera import CameraSession
from video import kiyo_identity, INPUT_MODES, INPUT_RATES, OUTPUT_MODES, dimensions, display_mode


class Monitor(QWidget):
    moved=Signal(float,float)
    def __init__(self):
        super().__init__()
        self.image=QImage()
        self.area=QRectF()
        self.anchor=None
        tile=QPixmap(24,24)
        tile.fill(QColor("#282d31"))
        p=QPainter(tile)
        p.fillRect(0,0,12,12,QColor("#303639"))
        p.fillRect(12,12,12,12,QColor("#303639"))
        p.end()
        self.checker=QBrush(tile)
        self.setMinimumSize(360,210)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setCursor(Qt.OpenHandCursor)
        self.setAccessibleName("Avatar preview. Drag to position the avatar.")

    def display(self,frame):
        h,w,ch=frame.shape
        fmt=QImage.Format_RGB888 if ch==3 else QImage.Format_RGBA8888
        self.frame_buffer=frame  # Keep the compatibility renderer buffer alive through paintEvent.
        self.image=QImage(frame.data,w,h,frame.strides[0],fmt)
        self.update()

    def paintEvent(self,event):
        p=QPainter(self)
        p.fillRect(self.rect(),QColor("#101315"))
        w=min(self.width(),self.height()*16/9)
        self.area=QRectF((self.width()-w)/2,(self.height()-w*9/16)/2,w,w*9/16)
        if self.image.hasAlphaChannel(): p.fillRect(self.area,self.checker)
        if not self.image.isNull():
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(self.area,self.image)
        p.end()

    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton and self.area.contains(e.position()):
            self.anchor=e.position()
            self.setCursor(Qt.ClosedHandCursor)
    def mouseMoveEvent(self,e):
        if self.anchor is not None:
            delta=e.position()-self.anchor
            self.anchor=e.position()
            self.moved.emit(2*delta.x()/self.area.width(),-2*delta.y()/self.area.height())
    def mouseReleaseEvent(self,e):
        self.anchor=None
        self.setCursor(Qt.OpenHandCursor)


class Studio(QMainWindow):
    scanned=Signal(object,str)
    benchmark_done=Signal(object,str)
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JointCam Studio • 1.3.0")
        self.resize(1100,635)
        self.settings=QSettings("JointCam","Standalone Studio")
        self.fps = 60 if str(self.settings.value("video/fps",30))=="60" else 30
        self.capture_modes={}
        for kiyo,default_size,default_rate in ((False,"640x480",self.fps),(True,"1920x1080",60)):
            size_key,rate_key=self.capture_keys(kiyo)
            size=self.settings.value(size_key,default_size)
            rate=str(self.settings.value(rate_key,default_rate))
            rate=next((n for n in INPUT_RATES if str(n)==rate),default_rate)
            self.capture_modes[kiyo]=(size if size in INPUT_MODES else default_size,rate)
            if not self.settings.contains(rate_key):self.settings.setValue(rate_key,rate)
        self.output_mode = self.settings.value("video/output", "960x540")
        if self.output_mode not in OUTPUT_MODES: self.output_mode = "960x540"
        self.cam=CameraSession()
        self.effects=Effects(self.settings)
        self.microphone=Microphone()
        self.motion=Motion()
        self.ash_pose=None
        self.next_motion_ash=0.
        self.next_ash=time.monotonic()+random.uniform(1.5,6.)
        self.last_yell_fx=-100.
        self.neutral=None
        self.camera_angle=0.
        self.pending_center=False
        self.render=self.output=None
        self.closed=False
        self.started=time.monotonic()
        self.pan=[self.settings.value(k,0.,float) for k in ("panX","panY")]
        root=QWidget()
        self.setCentralWidget(root)
        base=QVBoxLayout(root)
        base.setContentsMargins(22,18,22,18)
        base.setSpacing(12)
        title=QLabel("JointCam Studio")
        title.setObjectName("title")
        base.addWidget(title)
        row=QHBoxLayout()
        base.addLayout(row,1)
        rail=QFrame()
        rail.setObjectName("panel")
        row.addWidget(rail)
        avatars=QVBoxLayout(rail)
        avatars.setContentsMargins(12,15,12,15)
        avatars.setSpacing(8)
        avatars.addWidget(QLabel("Avatar"))
        self.avatar_group=QButtonGroup(self)
        self.avatar_group.setExclusive(True)
        saved=self.settings.value("stage/character","joint")
        for label,key in CHOICES:
            button=QPushButton(label)
            button.setCheckable(True)
            button.setProperty("character",key)
            self.avatar_group.addButton(button)
            avatars.addWidget(button)
            if key==saved:button.setChecked(True)
        if self.avatar_group.checkedButton() is None:
            self.avatar_group.buttons()[0].setChecked(True)
        avatars.addSpacing(8)
        left=QVBoxLayout()
        row.addLayout(left,1)
        self.preview_info=QLabel("Live preview")
        preview_row=QHBoxLayout()
        preview_row.addWidget(self.preview_info,1)
        self.preview_switch=QCheckBox("Show live preview")
        self.preview_switch.setChecked(self.settings.value("showLivePreview",True,bool))
        self.preview_switch.setToolTip("Show the local monitor while sending the same frames to OBS.")
        preview_row.addWidget(self.preview_switch)
        left.addLayout(preview_row)
        from gpu import StageSurface
        self.left = left
        self.monitor = StageSurface(self.settings.value("video/quality","cinema"))
        self.output_format = None
        self.gpu = False
        self.test_stop = None
        self.render_stats=None
        self.model_frame_key=None
        self.model_frame_patch=None
        self.model_commands=None
        self.benchmark_done.connect(self.finish_benchmark)
        left.addWidget(self.monitor,1)
        self.preview_paused=QLabel("Local preview off")
        self.preview_paused.setAlignment(Qt.AlignCenter)
        self.preview_paused.hide()
        left.addWidget(self.preview_paused,1)
        self.drag_hint=QLabel("Drag the avatar to position it.")
        left.addWidget(self.drag_hint)
        self.preview_switch.toggled.connect(self.set_live_preview)
        self.age = QLabel("")
        self.age.setWordWrap(True)
        left.addWidget(self.age)
        self.test = QPushButton("Measure OBS frame age…")
        self.test.clicked.connect(self.test_projector)
        left.addWidget(self.test)
        self.monitor.moved.connect(self.move_avatar)
        panel=QFrame()
        panel.setFixedWidth(284)
        panel.setObjectName("panel")
        row.addWidget(panel)
        side=QVBoxLayout(panel)
        side.setContentsMargins(16,15,16,15)
        side.setSpacing(10)
        side.addWidget(QLabel("Camera input"))
        self.input=QComboBox()
        self.input.addItem("Avatar only",None)
        side.addWidget(self.input)
        self.scan=QPushButton("Refresh cameras")
        side.addWidget(self.scan)
        self.calibration_button=QPushButton("Calibrate camera position")
        self.calibration_button.clicked.connect(self.calibrate)
        side.addWidget(self.calibration_button)
        self.calibration_note=QLabel()
        self.calibration_note.setWordWrap(True)
        self.calibration_note.hide()
        side.addWidget(self.calibration_note)
        self.camera_state=QLabel("Avatar preview")
        self.camera_state.setWordWrap(True)
        side.addWidget(self.camera_state)
        from wardrobe import Wardrobe
        self.wardrobe=Wardrobe(self,self.settings)
        appearance=QPushButton("Avatar wardrobe…")
        appearance.clicked.connect(self.wardrobe.show)
        self.torso=QCheckBox("Track shoulders")
        self.torso.setChecked(self.settings.value("torso",False,bool))
        avatars.addWidget(appearance)
        avatar_settings=QPushButton("Avatar settings…")
        avatar_settings.clicked.connect(self.open_avatar_options)
        avatars.addWidget(avatar_settings)
        side.addWidget(self.torso)
        self.scale_label=QLabel()
        avatars.addWidget(self.scale_label)
        self.zoom=QSlider(Qt.Horizontal)
        self.zoom.setAccessibleName("Avatar size")
        self.zoom.setRange(50,180)
        self.zoom.setValue(self.settings.value("scale",100,int))
        avatars.addWidget(self.zoom)
        self.reset=QPushButton("Reset framing")
        avatars.addWidget(self.reset)
        avatars.addSpacing(6)
        avatars.addWidget(QLabel("Karate"))
        self.options=Options(self)
        self.karate_switches={}
        for key,label in (("ninjas","Ninja fight overlay"),("karateCostume","Karate costume"),("ninjaAudio","Fight sounds")):
            original=self.options.box[key]
            switch=QCheckBox(label)
            switch.setChecked(original.isChecked())
            switch.setEnabled(original.isEnabled())
            switch.setToolTip(original.text() if not original.toolTip() else original.toolTip())
            switch.toggled.connect(original.setChecked)
            original.toggled.connect(switch.setChecked)
            self.karate_switches[key]=switch
            avatars.addWidget(switch)
        self.options.box["faceOnly"].toggled.connect(self.karate_switches["ninjas"].setDisabled)
        avatars.addStretch()
        self.avatar_group.buttonClicked.connect(lambda btn:self.options.change("character",btn.property("character")))
        self.microphone.sensitivity=self.options.cfg["sensitivity"]
        controls=QPushButton("Stage controls…")
        controls.clicked.connect(self.open_options)
        side.addWidget(controls)
        side.addSpacing(6)
        side.addWidget(QLabel("Output to OBS"))
        self.backend=QComboBox()
        self.backend.addItem("Spout2 · GPU texture","spout")
        self.backend.addItem("OBS Virtual Camera · green","obs")
        self.backend.addItem("Unity Video Capture · alpha","unitycapture")
        self.backend.setCurrentIndex(max(0,self.backend.findData(self.settings.value("backend","spout"))))
        side.addWidget(self.backend)
        self.send=QPushButton("Start output")
        self.send.setObjectName("primary")
        self.send.setEnabled(False)
        side.addWidget(self.send)
        self.status=QLabel("Opening the avatar…")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        side.addWidget(self.status)
        side.addStretch()
        guide=QPushButton("Connect to OBS…")
        side.addWidget(guide)
        guide.clicked.connect(self.help_obs)
        self.scanned.connect(self.show_cameras)
        self.scan.clicked.connect(self.discover)
        self.startup_camera_pending=True
        self.input.activated.connect(self.camera_chosen)
        self.input.currentIndexChanged.connect(self.select_camera)
        self.torso.toggled.connect(self.set_shoulder_tracking)
        self.zoom.valueChanged.connect(self.scale_changed)
        self.reset.clicked.connect(self.recenter)
        self.backend.currentIndexChanged.connect(self.output_changed)
        self.send.clicked.connect(self.toggle_output)
        self.scale_changed()
        self.timer=QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.tick)
        self.rate_since=time.monotonic()
        self.rate_frames=0
        self.previous_tick=None
        self.next_camera_info=0.
        self.long_intervals=0
        self.reused_frames=0
        QTimer.singleShot(0,self.start_preview)
        QTimer.singleShot(100,self.discover)

    def camera_chosen(self,index):
        self.startup_camera_pending=False

    def discover(self):
        if not self.scan.isEnabled():return
        self.scan.setEnabled(False)
        def devices():
            cameras=[]
            error=""
            try:
                import cv2
                from cv2_enumerate_cameras import enumerate_cameras
                cameras=[(c.name,c.index,c.vid,c.pid) for c in enumerate_cameras(cv2.CAP_DSHOW)
                         if c.name.casefold() not in ("obs virtual camera","unity video capture")]
            except Exception as exc: error=str(exc)
            if not self.closed: self.scanned.emit(cameras,error)
        threading.Thread(target=devices,daemon=True).start()

    def show_cameras(self,cameras,error):
        old=self.input.currentData()
        prior_camera=self.input.currentText(),self.kiyo_identity()
        if error and old is not None:
            # A failed enumeration says nothing about the currently streaming device.
            self.scan.setToolTip(error)
            self.scan.setEnabled(True)
            return
        self.input.blockSignals(True)
        self.input.clear()
        self.input.addItem("Avatar only",None)
        preferred=[]
        for name,index,*ids in cameras:
            identity=kiyo_identity(name,*ids)
            label="Razer Kiyo Pro (USB Video Device)" if identity=="confirmed" and name.casefold().strip()=="usb video device" else name
            self.input.addItem(label,index)
            usb=" ".join(name.casefold().split())=="usb video device"
            if usb or identity=="confirmed":
                preferred.append((0 if usb and identity=="confirmed" else 1 if usb else 2,self.input.count()-1))
            self.input.setItemData(self.input.count()-1,identity,Qt.UserRole+1)
        if not cameras:
            for i in range(4): self.input.addItem(f"Try camera {i+1}",i)
            self.scan.setToolTip(error or "No named camera found. Use a camera slot or reconnect and refresh.")
        else:
            self.scan.setToolTip("Refresh the camera list")
        selected=self.input.findData(old) if old is not None else 0
        if old is not None and not prior_camera[0].startswith("Try camera "):
            matches=[i for i in range(1,self.input.count())
                     if self.input.itemText(i)==prior_camera[0]
                     and self.input.itemData(i,Qt.UserRole+1)==prior_camera[1]]
            if selected not in matches:selected=matches[0] if len(matches)==1 else 0
        if self.startup_camera_pending and old is None and preferred:
            selected=min(preferred)[1]
        self.startup_camera_pending=False
        self.input.setCurrentIndex(max(0,selected))
        self.input.blockSignals(False)
        if old!=self.input.currentData() or prior_camera!=(self.input.currentText(),self.kiyo_identity()): self.select_camera()
        self.scan.setEnabled(True)

    def kiyo_identity(self):
        stored=self.input.currentData(Qt.UserRole+1)
        return kiyo_identity(self.input.currentText()) if stored is None else stored

    def kiyo_mount(self):
        identity=self.kiyo_identity()
        return identity=="confirmed" or (identity=="generic" and self.options.kiyo.isChecked())

    @staticmethod
    def capture_keys(kiyo):
        if kiyo:return "video/kiyoInput","video/kiyoInputFps"
        return "video/input","video/inputFps"

    def set_shoulder_tracking(self,enabled):
        self.settings.setValue("torso",enabled)
        self.cam.set_tracking_option("torso",enabled)

    def select_camera(self):
        self.settings.setValue("torso",self.torso.isChecked())
        matched=bool(self.kiyo_identity())
        self.options.sync_kiyo(matched)
        self.options.down_tilt.setEnabled(self.kiyo_mount())
        kiyo=matched and self.options.kiyo.isChecked()
        input_size,input_fps=self.capture_modes[kiyo]
        cfg=dict(self.options.cfg,torso=self.torso.isChecked(),
                 input_size=dimensions(input_size),
                 fps=input_fps,kiyo=kiyo,codec=self.settings.value("video/codec","auto"))
        if cfg["floaters"] and not cfg["faceOnly"]:
            height=dimensions(self.output_mode)[1]
            self.effects.prepare_props(self.zoom.value()/100*(1.525 if cfg["closeup"] else 1)*height/540)
        self.effects.reset()
        self.calibration_note.hide()
        self.pending_center=False
        self.neutral=None
        self.camera_angle=0.
        key=self.profile_key()
        if key:
            try:
                profile=json.loads(self.settings.value(key,"null"))
                if profile and len(profile)==8 and all(math.isfinite(v) for v in profile):
                    self.neutral=profile[:7];self.camera_angle=profile[7]
            except (TypeError,ValueError):
                pass
        self.motion=Motion()
        self.ash_pose=None
        self.cam.select(self.input.currentData(),cfg)

    def scale_changed(self):
        self.scale_label.setText(f"Avatar size   {self.zoom.value()}%")
        self.settings.setValue("scale",self.zoom.value())

    def move_avatar(self,x,y):
        for i,(v,key) in enumerate(((x,"panX"),(y,"panY"))):
            self.pan[i]=max(-1.,min(1.,self.pan[i]+v))
            self.settings.setValue(key,self.pan[i])

    def recenter(self):
        self.move_avatar(-self.pan[0],-self.pan[1])
        self.zoom.setValue(100)

    def set_live_preview(self,visible):
        self.settings.setValue("showLivePreview",visible)
        if self.render is None:return
        self.monitor.setVisible(visible)
        self.preview_paused.setVisible(not visible)
        self.drag_hint.setVisible(visible)

    def start_preview(self):
        try:
            try:
                self.render=self.monitor.open_stage(dimensions(self.output_mode))
                self.gpu=True
                self.renderer_name=str(self.render.ctx.info.get("GL_RENDERER","OpenGL"))
            except Exception:
                import traceback
                traceback.print_exc()
                old = self.monitor
                self.monitor = Monitor()
                self.left.replaceWidget(old, self.monitor)
                old.hide()
                old.deleteLater()
                self.monitor.moved.connect(self.move_avatar)
                spout_index = self.backend.findData("spout")
                # A session-specific graphics fallback should preserve the user's
                # saved Spout preference for the next successful OpenGL startup.
                previous=self.backend.blockSignals(True)
                try:
                    self.backend.removeItem(spout_index)
                finally:
                    self.backend.blockSignals(previous)
                from software import SoftwareRenderer
                self.render=SoftwareRenderer(*dimensions(self.output_mode))
                self.setWindowTitle("JointCam Studio 1.3.0 • Compatibility renderer")
            self.set_live_preview(self.preview_switch.isChecked())
            self.deadline=time.monotonic()
            self.timer.start(0)
            self.status.setText("Preview only · "+display_mode(self.output_mode))
            self.send.setEnabled(True)
        except Exception as exc:
            self.status.setText(f"Could not open the avatar. Run the installer again and reopen JointCam.\n{exc}")

    def set_quality(self, key):
        self.settings.setValue("video/quality", key)
        if not self.gpu:
            return "Rendering quality applies to the OpenGL renderer."
        try:
            self.monitor.makeCurrent()
            if self.render_stats is not None:
                self.profile_changed(False)
                self.profile_changed(True)
            self.monitor.set_quality(key)
        except Exception as exc:
            return f"Could not allocate that quality level. {exc}"
        self.model_frame_key = None
        return self.monitor.describe()

    def set_cpu_placement(self, enabled):
        import perf
        self.settings.setValue("perf/isolateCcd", enabled)
        try:
            return perf.isolate_on_last_ccd(enabled)
        except Exception as exc:
            return f"CPU placement unavailable. {exc}"

    def profile_changed(self, enabled):
        if self.render_stats is not None:
            self.monitor.makeCurrent()
            self.render_stats.close()
            self.render_stats=None
        if enabled and self.gpu:
            from renderstats import RenderStats
            self.render_stats=RenderStats()
            self.options.profile_result.setText("Waiting for rendered frames…")
        else:
            self.options.profile_result.setText("GPU timing requires the OpenGL renderer." if enabled else "")

    def tick(self):
        if self.frame() is False or self.closed: return
        now=time.monotonic()
        if self.previous_tick is not None and now-self.previous_tick>1.5/self.fps:
            self.long_intervals+=1
        self.previous_tick=now
        self.rate_frames+=1
        elapsed=now-self.rate_since
        if elapsed>=1:
            graphics=self.monitor.describe() if self.gpu else "Compatibility renderer"
            if self.render_stats is not None:
                self.options.profile_result.setText(self.render_stats.report())
            self.preview_info.setText(f"Stage · {self.rate_frames/elapsed:.1f} / {self.fps} FPS · {graphics}")
            self.preview_info.setToolTip(f"{self.renderer_name if self.gpu else graphics}\nStage intervals over {1500/self.fps:.0f} ms in the last {elapsed:.1f} s: {self.long_intervals}\nIdentical 3D frames reused: {self.reused_frames} / {self.rate_frames}")
            self.long_intervals=0
            self.reused_frames=0
            self.rate_since=now
            self.rate_frames=0
        period=1/self.fps
        self.deadline+=period
        if self.deadline<now:
            self.deadline=now
        self.timer.start(max(0,round((self.deadline-now)*1000)))

    def apply_video(self):
        selected = self.options.output_mode.currentData()
        fps=self.options.fps.currentData()
        rate_changed=fps!=self.fps
        if rate_changed or selected != self.output_mode:
            size = dimensions(selected)
            resume = self.output is not None
            try:
                if self.gpu and selected != self.output_mode:
                    self.monitor.configure_target(self.render.ctx, size)
                elif self.render and not self.gpu:
                    self.render.size = size
            except Exception as exc:
                self.options.output_mode.setCurrentIndex(self.options.output_mode.findData(self.output_mode))
                self.options.note.setText(f"Could not allocate the selected output size. {exc}")
                return
            if resume:
                self.stop_output()
            self.fps=fps
            self.deadline=time.monotonic()
            self.settings.setValue("video/fps",fps)
            self.output_mode = selected
            self.settings.setValue("video/output", selected)
            if resume:
                self.toggle_output()
            else:
                self.status.setText("Preview only · "+display_mode(selected))
        kiyo=self.options.capture_profile
        requested=(self.options.input_mode.currentData(),self.options.input_rate.currentData())
        codec=self.options.codec.currentData()
        codec_changed=codec!=self.settings.value("video/codec","auto")
        if requested!=self.capture_modes[kiyo] or codec_changed:
            self.capture_modes[kiyo]=requested
            for key,value in zip(self.capture_keys(kiyo),requested):
                self.settings.setValue(key,value)
            self.settings.setValue("video/codec",codec)
            if self.test_stop: self.test_stop.set()
            self.select_camera()
        if self.options.cfg["floaters"] and not self.options.cfg["faceOnly"]:
            self.effects.prepare_props(self.zoom.value()/100*(1.525 if self.options.cfg["closeup"] else 1)*dimensions(self.output_mode)[1]/540)
        self.options.note.setText(self.status.text())

    def driver_controls(self):
        if self.cam.request_driver_panel():
            self.options.note.setText("Requested the active webcam’s driver controls.")
        else:
            self.options.note.setText("Choose a physical webcam in Camera input, then open its driver controls.")

    def windows_camera_settings(self):
        if sys.platform != "win32": return
        if sys.getwindowsversion().build < 22000:
            self.driver_controls()
            return
        import os
        try:
            os.startfile("ms-settings:camera")
        except OSError as exc:
            self.options.note.setText(f"Windows could not open Cameras settings. {exc}")

    def open_avatar_options(self):
        self.options.tabs.setCurrentIndex(0)
        self.open_options()

    def open_options(self):
        self.options.show();self.options.raise_();self.options.activateWindow()

    def profile_key(self):
        if self.input.currentData() is None:return None
        device=f"{self.input.currentText()}|{self.input.currentData()}"
        if self.kiyo_mount():
            if self.input.currentText()=="Razer Kiyo Pro (USB Video Device)":
                device=f"Razer Kiyo Pro|{self.input.currentData()}"
            device+="|top-center"
        return "rig-calibration/"+hashlib.sha256(device.encode()).hexdigest()

    def calibration_message(self,text):
        self.calibration_note.setText(text)
        self.calibration_note.show()

    def calibrate(self):
        if not self.profile_key() or self.options.cfg["manual"]:
            self.calibration_message("Select a webcam and use automatic face tracking first.")
            return
        self.pending_center=True
        self.center_samples=[]
        self.side_samples=[]
        self.center_stamp=-1
        self.center_deadline=time.monotonic()+8
        self.calibration_message("Look at the center of your screen and keep both shoulders visible.")

    def sample_center(self, now, stamp, face, body, rig):
        if now>self.center_deadline:
            self.pending_center=False
            self.calibration_message("Calibration timed out. Face the center of your screen and try again.")
            return
        if not face or stamp<=self.center_stamp:return
        self.center_stamp=stamp
        self.center_samples.append(list(face["pose"][:5])+list(body))
        pts=rig.get("shoulders",[])
        if len(pts)>12:
            a,b=sorted(pts[11:13],key=lambda p:p["x"])
            if min(a["visibility"],b["visibility"])>.6 and b["x"]-a["x"]>.065:
                angle=math.atan2(b["z"]-a["z"],b["x"]-a["x"])
                self.side_samples.append(max(-.60,min(.60,angle)))
        if len(self.center_samples)>=9:
            self.neutral=list(map(median,zip(*self.center_samples)))
            if self.kiyo_mount():self.camera_angle=0.
            elif self.side_samples:self.camera_angle=median(self.side_samples)
            self.settings.setValue(self.profile_key(),json.dumps(self.neutral+[self.camera_angle]))
            self.pending_center=False
            # Recalibrating keeps the held capture of this person's eyes and mouth.
            self.motion=Motion(held=self.motion.held)
            self.ash_pose=None
            self.calibration_message("Calibrated face and arm reach for this webcam." if self.side_samples else
                "Face center saved. Enable arms and show both shoulders to calibrate reach.")

    def nativeEvent(self,kind,message):
        if sys.platform=="win32":
            from ctypes.wintypes import MSG
            msg=MSG.from_address(int(message))
            if msg.message==0x312 and msg.wParam==803:
                self.calibrate()
                return True,0
            if msg.message==0x312 and 800<=msg.wParam<=802:
                self.effects.fx.append(int(msg.wParam)-800)
                return True,0
        return super().nativeEvent(kind,message)

    def help_obs(self):
        if self.backend.currentData()=="spout":
            QMessageBox.information(self,"Spout2 output","Install the Spout2 Capture plugin for OBS (the JointCam setup offers it, or run JointCam Studio add-ons from the Start menu) and restart OBS. Click Start output here. In OBS, add a Spout2 Capture source and choose JointCam Studio. Use the premultiplied alpha composite mode if available. Both apps should run on the same GPU.")
            return
        alpha=self.backend.currentData()=="unitycapture"
        instructions=("Install Unity Capture and choose Unity Video Capture with ARGB video format in OBS. "
                      "The checkerboard represents transparency." if alpha else
                      "Leave OBS’s own Start Virtual Camera button off. Choose OBS Virtual Camera in OBS and add a green Chroma Key effect filter.")
        QMessageBox.information(self,"Connect JointCam to OBS","1. Deactivate the physical webcam in OBS so JointCam can use it.\n\n"
            f"2. Click Start output here. In OBS, add a Video Capture Device at {display_mode(self.output_mode)} and {self.fps} FPS.\n\n3. "+instructions)

    def output_changed(self):
        self.settings.setValue("backend",self.backend.currentData())
        self.status.setText("Preview only · "+display_mode(self.output_mode))

    def stop_output(self):
        if self.test_stop: self.test_stop.set()
        if self.gpu: self.monitor.makeCurrent()
        if self.gpu: self.monitor.release_camera_buffer()
        out,self.output=self.output,None
        try:
            if out: out.close()
        finally:
            self.backend.setEnabled(True)
            self.send.setText("Start output")

    def toggle_output(self):
        if self.output:
            self.stop_output()
            self.status.setText("Preview only · "+display_mode(self.output_mode))
            return
        backend=self.backend.currentData()
        try:
            if backend == "spout":
                from gpu import SpoutOutput
                self.monitor.makeCurrent()
                self.output = SpoutOutput()
            else:
                import pyvirtualcam as vc
                width, height = dimensions(self.output_mode)
                self.output=None
                if backend=="obs" and self.gpu:
                    # The OBS virtual camera carries NV12. Converting on the GPU halves the
                    # readback and removes pyvirtualcam's per-frame CPU conversion.
                    try:
                        self.output=vc.Camera(width=width,height=height,fps=self.fps,backend=backend,fmt=vc.PixelFormat.NV12)
                        self.output_format="nv12"
                    except Exception:
                        self.output=None
                if self.output is None:
                    self.output=vc.Camera(width=width,height=height,fps=self.fps,backend=backend,
                        fmt=vc.PixelFormat.RGB if backend=="obs" else vc.PixelFormat.RGBA)
                    self.output_format="rgb" if backend=="obs" else "rgba"
            self.backend.setEnabled(False)
            self.send.setText("Stop output")
            self.status.setText(f"Sending to {self.output.device} · {display_mode(self.output_mode)} · {self.fps} FPS")
        except Exception as exc:
            hint="Stop OBS’s own virtual camera output and try again." if backend=="obs" else "Install Unity Capture or select OBS Virtual Camera."
            if backend=="spout": hint="Select a virtual camera to use a different output."
            self.status.setText(f"Output unavailable. {hint}\n{exc}")

    def test_projector(self):
        from benchmark import obs_windows, measure_projector
        from PySide6.QtWidgets import QInputDialog
        if self.test_stop:
            self.test_stop.set()
            return
        if not self.output or self.input.currentData() is None:
            self.age.setText("Choose your webcam and start output before measuring.")
            return
        windows = obs_windows()
        if not windows:
            self.age.setText("In OBS, right-click the JointCam source and open a windowed source projector.")
            return
        title, ok = QInputDialog.getItem(self, "30-second OBS frame age test",
            "Select the OBS projector showing only JointCam. Keep it visible while playing. A timing strip will appear in your output for 30 seconds.",
            sorted(windows, key=lambda name: "projector" not in name.lower()), 0, False)
        if not ok: return
        stop = self.test_stop = threading.Event()
        self.test.setText("Cancel measurement")
        self.age.setText("Measuring the visible OBS projector for 30 seconds…")
        def run():
            try:
                message = measure_projector(windows[title], stop)
            except Exception as exc:
                message = f"Could not sample the projector: {exc}"
            if not self.closed: self.benchmark_done.emit(stop, message)
        threading.Thread(target=run, daemon=True).start()

    def finish_benchmark(self, stop, message):
        if self.test_stop is stop:
            self.test_stop = None
            self.test.setText("Measure OBS frame age…")
            self.age.setText("Measurement canceled." if stop.is_set() else message)

    def frame(self):
        try:
            face,body,state,camera_stamp,rig=self.cam.sample()
            now=time.monotonic()
            if self.options.received.isVisible() and now>=self.next_camera_info:
                self.next_camera_info=now+.25
                video_info=self.cam.video_info()
                if self.options.received.text()!=video_info:self.options.received.setText(video_info)
            r=self.render
            cfg=self.options.cfg
            pose=list(face["pose"]) if face else [0.,0.,0.,0.,0.,.58,.49]
            if face and camera_stamp and not self.pending_center and (self.ash_pose is None or camera_stamp!=self.ash_pose[0]):
                previous=self.ash_pose
                self.ash_pose=(camera_stamp,tuple(pose[:5]))
                if previous:
                    dt=camera_stamp-previous[0]
                    if .008<dt<.2:
                        turn=math.dist(pose[:5],previous[1])/dt
                        chance=-math.expm1(-min(6.,max(0.,turn-.65)*1.7)*dt)
                        if now>=self.next_motion_ash and random.random()<chance:
                            self.effects.fx.append(4 if turn>3.2 else 3)
                            self.next_motion_ash=now+random.uniform(.65,1.6)
            elif not face:self.ash_pose=None
            if self.pending_center and rig.get("tracking_complete",True):
                self.sample_center(now,camera_stamp,face,body,rig)
            neutral=self.neutral or [0.]*7
            gain=cfg["gain"]/100.
            if face:
                pose[:5]=[(pose[i]-neutral[i])*gain for i in range(5)]
                face=dict(face,pose=pose)
            body=tuple((b-neutral[i+5])*gain for i,b in enumerate(body)) if self.torso.isChecked() and not cfg["faceOnly"] else (0.,0.)
            face,body=self.motion.sample(now,camera_stamp,face,body,cfg["smoothing"])
            if self.motion.holding:state+=" · showing your last good capture"
            if self.camera_state.text()!=state:self.camera_state.setText(state)
            pose=face["pose"]
            r.zoom=self.zoom.value()/100*(1.525 if cfg["closeup"] else 1.)
            r.pan=(self.pan[0],self.pan[1]+(.16 if cfg["closeup"] else 0))
            r.glasses=self.wardrobe.selection["eyewear"]=="classic"
            r.transparent=self.backend.currentData() in ("unitycapture","spout")
            r.backdrop=cfg["backdrop"]
            if self.gpu:
                # Glow is light over transparent or studio backgrounds. On the green-screen
                # feed it would tint the key color, and it must not touch the timing strip.
                self.monitor.glow_allowed=(r.transparent or r.backdrop) and not self.test_stop
            r.heat=0.
            # Keep capture timestamps for latency measurements. Give each completed
            # landmark sample its own display window after inference finishes.
            if now-rig.get("stamp",0)>.55:rig={}
            r.heat=max(r.heat,rig.get("breath",0.))
            yell=self.microphone.signal.last_yell
            if 0<=now-yell<1.2:
                r.heat=max(r.heat,.96*math.exp(-(now-yell)*2.1))
                if yell!=self.last_yell_fx:
                    self.effects.fx.extend((4,1))
                    self.last_yell_fx=yell
                    self.next_ash=now+random.uniform(2.,8.)
            if now>=self.next_ash:
                self.effects.fx.append(3)
                self.next_ash=now+random.uniform(2.5,10.)
            show_preview=self.preview_switch.isChecked() and not self.isMinimized()
            visible_frame=bool(self.output or show_preview or self.test_stop)
            if self.gpu and visible_frame:self.monitor.makeCurrent()
            stats=self.render_stats
            probe=stats is not None and visible_frame and stats.sample(now)
            character=cfg["character"]
            cutout=character!="joint"
            if character=="bong":
                if getattr(self,"beaker_water",None) is None:self.beaker_water=BeakerWater()
                water=self.beaker_water.sample(now,pose,body)
            else:
                self.beaker_water=None
                water=(0.,0.)
            if cutout:
                frame=None
                anchors=self.effects.cutout.place(character,pose,body,r.zoom,r.pan,self.gpu,face["patch"],self.motion.torso)
                self.effects.cutout.rig.water=water
                tip=(anchors["hat"][0]/960,anchors["hat"][1]/540)
            else:
                # Transfer part of a lean to the joint's existing lower-body pivot.
                # Counter-rotate the neck to keep the live face pointed at its target.
                trunk_roll=.48*self.motion.torso[2]
                body=(body[0]+trunk_roll,body[1])
                pose=list(pose)
                pose[3]-=trunk_roll
                face=dict(face,pose=pose)
                self.model_frame_key=self.model_frame_patch=self.model_commands=None
                if not self.gpu:r.fight_costume=cfg["karateCostume"]
                if not visible_frame:
                    r.draw(now-self.started,face,body,r.transparent,paint=False)
                    frame=None
                else:
                    if probe:stats.begin("Avatar")
                    frame=r.draw(now-self.started,face,body,r.transparent)
                    if self.gpu:self.monitor.draw_emissive(r)
                    if probe:stats.end("Avatar")
                anchors=getattr(r,"overlay_anchors",None)
                tip=r.tip
            costume=None
            if cfg["karateCostume"] and visible_frame:
                if cutout:
                    costume=mesh_mounts(self.effects.cutout.rig,self.gpu)
                elif self.gpu:
                    costume=joint_mounts(r,pose,body)
                else:
                    costume=r.karate_mounts
            stamp=rig.get("stamp",0)*1000
            state=dict(costume=costume,time=now*1000,stamp=stamp,bodyStamp=rig.get("body_ready",0)*1000,handStamp=rig.get("hand_ready",0)*1000,aspect=rig.get("aspect",4/3),
                       shoulders=rig.get("shoulders",[]),hands=rig.get("hands",[]),mouth=rig.get("mouth"),
                       open=pose[5],manual=cfg["manual"],closeup=cfg["closeup"],
                       armStability=cfg["armStability"],ninjas=cfg["ninjas"] and not cfg["faceOnly"],ninjaAudio=cfg["ninjaAudio"],arms=(cfg["arms"] or cfg["ninjas"]) and not cfg["faceOnly"],
                       floaters=cfg["floaters"] and not cfg["faceOnly"],
                       propMode=cfg["propMode"],wardrobe=self.wardrobe.selection,anchors=anchors,cutout=cutout,mesh=cutout and self.gpu,breath=rig.get("breath",0.),mouthSmoke=cfg["mouthSmoke"],
                       pose=dict(cameraTilt=math.radians(self.options.down_tilt.value()) if self.options.down_tilt.isEnabled() else 0.,cameraAngle=self.camera_angle,x=pose[0]+body[1]+self.pan[0]/(.225*r.zoom),y=pose[1]+self.pan[1]/(.4*r.zoom),
                                 headYaw=pose[2],headRoll=pose[3],headPitch=pose[4],roll=body[0],pitch=0,yaw=0,scale=self.zoom.value()/100),
                       tip=tip)
            device = self.monitor.device if self.gpu else None
            commands=stats.cpu_call("Overlay prep (CPU)",self.effects.advance,state,visible_frame) if probe else self.effects.advance(state,visible_frame)
            if not visible_frame:
                for command in commands:
                    if command[0]=="impactSound":self.effects.play_impact()
                    elif command[0]=="ninjaSound":self.effects.ninja_sound(command[1])
                self.model_frame_key=self.model_frame_patch=self.model_commands=None
                return
            reuse=False
            if cutout:
                if self.gpu:
                    key=(character,r.target,self.effects.cutout.rig.gpu_pose(face["patch"] is not None),
                         r.transparent,r.backdrop,r.glasses)
                    cacheable=not self.test_stop and not any(cmd[0] in ("impactSound","ninjaSound") for cmd in commands)
                    reuse=(cacheable and key==self.model_frame_key and commands==self.model_commands)
                    if reuse and face["patch"] is not self.model_frame_patch:
                        # Camera samples own independent buffers even when all pixels are identical.
                        reuse=(face["patch"] is not None and self.model_frame_patch is not None
                               and np.array_equal(face["patch"],self.model_frame_patch))
                    if reuse:self.reused_frames+=1
                    self.model_frame_key=key if cacheable else None
                    self.model_frame_patch=face["patch"]
                    self.model_commands=commands
                if not reuse:
                    if probe:stats.begin("Avatar")
                    frame=r.clear_stage(r.transparent)
                    if self.gpu:r.draw_model(self.effects.cutout.rig,face["patch"])
                    if probe:stats.end("Avatar")
            if not reuse:
                if probe:stats.begin("Overlays")
                frame=self.effects.composite(frame,state,device,face["patch"] if cutout else None,commands)
                if probe:stats.end("Overlays")
            face_stamp=self.motion.seen
            if self.test_stop and face["patch"] is not None and 0<=now-face_stamp<=.55:
                from benchmark import draw_marker
                if device is None:
                    if not frame.flags.writeable:frame=frame.copy()
                    ch=frame.shape[2]
                    device=QImage(frame.data,frame.shape[1],frame.shape[0],frame.strides[0],QImage.Format_RGBA8888 if ch==4 else QImage.Format_RGB888)
                draw_marker(device,face_stamp)
            if self.gpu:
                if not reuse:
                    if probe:stats.begin("Resolve")
                    self.monitor.resolve()
                    if probe:stats.end("Resolve")
                if self.output and self.backend.currentData() != "spout":
                    if probe:
                        frame = stats.cpu_call("Readback (CPU)",self.monitor.camera_frame,self.output_format,reuse)
                    else:
                        frame = self.monitor.camera_frame(self.output_format,repeat=reuse)
                if show_preview and not reuse:self.monitor.update()
            elif show_preview:
                self.monitor.display(frame)
        except Exception as exc:
            self.timer.stop()
            self.stop_output()
            self.send.setEnabled(False)
            self.status.setText(f"Preview stopped. Reopen JointCam to retry.\n{exc}")
            return False
        if self.output:
            try:
                if self.backend.currentData() == "spout":
                    if probe:
                        stats.begin("Spout")
                        try:
                            stats.cpu_call("Spout call (CPU)",self.output.publish,self.monitor)
                        finally:
                            stats.end("Spout")
                    else:
                        self.output.publish(self.monitor)
                else:
                    self.output.send(frame)
            except Exception as exc:
                self.stop_output()
                self.status.setText(f"Output interrupted. Preview is active.\n{exc}")

    def closeEvent(self,event):
        self.closed=True
        self.timer.stop()
        self.options.unbind()
        self.microphone.close()
        self.cam.close()
        self.stop_output()
        if self.render_stats is not None:self.profile_changed(False)
        if self.render: self.render.close()
        super().closeEvent(event)


STYLE="""
QWidget { background:#191d21; color:#ecf0ed; font: 14px 'Segoe UI'; }
QLabel#title { font-size:28px; font-weight:600; }
QFrame#panel, QFrame#panel QLabel, QFrame#panel QCheckBox { background:#24292e; }
QFrame#panel { border-radius:9px; }
QComboBox,QPushButton { background:#333b40; padding:7px; border:1px solid #57636a; border-radius:5px; }
QPushButton:checked { background:#305944; border:1px solid #96d8ae; color:#ffffff; }
QPushButton:hover { background:#46524f; }
QPushButton#primary { background:#a7e8bd; color:#12291d; font-weight:600; }
QPushButton:disabled { color:#8f9696; }
QComboBox QAbstractItemView { selection-background-color:#356344; }
QSlider::groove:horizontal { height:4px; background:#515c5c; }
QSlider::handle:horizontal { width:14px; margin:-5px 0; background:#a7e8bd; border-radius:6px; }
"""
def launch():
    from PySide6.QtGui import QSurfaceFormat
    # The stage keeps its own clock. A vsync-blocked swap of the preview window would stall
    # the GUI thread for up to a refresh interval and delay the next OBS frame.
    fmt=QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.OpenGL)
    fmt.setVersion(3,3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setSwapInterval(0)
    QSurfaceFormat.setDefaultFormat(fmt)
    app=QApplication(sys.argv)
    from PySide6.QtGui import QIcon
    from pathlib import Path
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent/"assets"/"jointcam.png")))
    app.setApplicationDisplayName("JointCam Studio")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window=Studio()
    window.show()
    return app.exec()

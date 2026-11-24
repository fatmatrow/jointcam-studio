from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog,QTabWidget,QVBoxLayout,QWidget,QFormLayout,QCheckBox,QPushButton,
                               QProgressBar,QSpinBox,QComboBox,QLabel,QKeySequenceEdit)
import sys
import ctypes
import time

FLAGS={"ninjas":"Ninja fight overlay","faceOnly":"Low memory · face tracking only","arms":"Doodle arms, hands and fingers",
       "matte":"Natural matte lips","manual":"Fixed facial placement",
       "closeup":"Streamer close-up","backdrop":"Studio backdrop"}
RANGES={"smoothing":("Motion smoothing",0,100,65),"armStability":("Arm stability",0,100,65),"gain":("Motion sensitivity",0,170,100),"centerX":("Fixed face center X",10,90,50),
        "eyeY":("Fixed eyes Y",5,90,40),"mouthY":("Fixed mouth Y",10,95,58),"spacing":("Fixed eye spacing",3,35,12),
        "sensitivity":("Audio sensitivity",25,200,100),"lipReach":("Upper lip reach",0,300,100)}
EFFECTS=("Confetti","Ember sparks","Star shower")
class Options(QDialog):
    def __init__(self,studio):
        super().__init__(studio)
        self.host=studio
        self.setWindowTitle("Stage controls")
        self.resize(465,500)
        self.cfg={}
        self.box={}
        self.keys=[]
        self.setModal(False)
        base=QVBoxLayout(self)
        self.tabs=QTabWidget();base.addWidget(self.tabs)
        self.note=QLabel();self.note.setWordWrap(True);base.addWidget(self.note)
        def page(name):
            w=QWidget();self.tabs.addTab(w,name);return QFormLayout(w)
        def flag(layout,key):
            c=QCheckBox(FLAGS[key]);c.setChecked(studio.settings.value('stage/'+key,False,bool))
            self.cfg[key]=c.isChecked();self.box[key]=c;layout.addRow(c)
            c.toggled.connect(lambda value,k=key:self.change(k,value))
        def number(layout,key):
            title,low,high,default=RANGES[key]
            c=QSpinBox();c.setRange(low,high);c.setSuffix(" %");c.setValue(studio.settings.value('stage/'+key,default,int))
            self.cfg[key]=c.value();self.box[key]=c;layout.addRow(title,c)
            c.valueChanged.connect(lambda value,k=key:self.change(k,value))
        def button(layout,title,action):
            b=QPushButton(title);layout.addRow(b);b.clicked.connect(action)
        f=page("Avatar")
        self.cfg["character"]=studio.avatar_group.checkedButton().property("character")
        for k in ["faceOnly","closeup","backdrop","matte"]:flag(f,k)
        number(f,"lipReach")
        self.box["lipReach"].setToolTip("How far the live mouth reaches above your upper lip. It stops at a mustache "
                                        "automatically. Raise it to show more upper lip; 0% shows only the lips.")
        number(f,"gain")
        number(f,"smoothing")
        self.down_tilt=QSpinBox()
        self.down_tilt.setRange(0,45)
        self.down_tilt.setSuffix("°")
        self.down_tilt.setValue(studio.settings.value("rig/kiyoTopTilt",15,int))
        self.down_tilt.setToolTip("Estimated angle below horizontal for the top-center Kiyo Pro.")
        f.addRow("Kiyo Pro downward tilt",self.down_tilt)
        self.down_tilt.setEnabled(False)
        self.down_tilt.valueChanged.connect(lambda degrees:studio.settings.setValue("rig/kiyoTopTilt",degrees))
        flag(f,"manual")
        for k in ["centerX","eyeY","mouthY","spacing"]:number(f,k)
        f=page("Hands & props")
        flag(f,"arms")
        flag(f,"ninjas")
        costume=QCheckBox("Karate costume")
        costume.setChecked(studio.settings.value("stage/karateCostume",self.cfg["ninjas"],bool))
        self.cfg["karateCostume"]=costume.isChecked()
        studio.settings.setValue("stage/karateCostume",costume.isChecked())
        costume.toggled.connect(lambda on:self.change("karateCostume",on))
        self.box["karateCostume"]=costume
        f.addRow(costume)
        self.box["ninjas"].setToolTip("Swipe at approaching ninjas with either doodle hand. The fight pauses when your wrists leave view.")
        audio=QCheckBox("Karate yells and fight sounds")
        audio.setChecked(studio.settings.value("stage/ninjaAudio",True,bool))
        self.cfg["ninjaAudio"]=audio.isChecked()
        audio.toggled.connect(lambda on:self.change("ninjaAudio",on))
        self.box["ninjaAudio"]=audio
        f.addRow(audio)
        detailed=QCheckBox("Use full hand tracking model")
        detailed.setChecked(studio.settings.value("stage/fullHands",True,bool))
        self.cfg["fullHands"]=detailed.isChecked()
        detailed.toggled.connect(lambda on:self.change("fullHands",on))
        detailed.setToolTip("Use the larger palm and finger models. Uncheck for the lighter tracking path.")
        f.addRow(detailed)
        number(f,"armStability")
        self.box["armStability"].setToolTip("Steady small movements of the arms and hands. Set to 0% for the previous response.")
        self.prop_mode=QComboBox()
        for label,key in [("Off","off"),("Always present","always"),("Occasional flybys","occasional")]:
            self.prop_mode.addItem(label,key)
        default="always" if studio.settings.value("stage/floaters",False,bool) else "off"
        idx=self.prop_mode.findData(studio.settings.value("stage/propMode",default))
        self.prop_mode.setCurrentIndex(max(0,idx))
        self.cfg["propMode"]=self.prop_mode.currentData()
        self.cfg["floaters"]=self.cfg["propMode"]!="off"
        self.prop_mode.currentIndexChanged.connect(self.set_props)
        f.addRow("Cannabis props",self.prop_mode)
        guide=QLabel("Pinch to catch. Close your lips around a mouthpiece to hold it. Pull with both hands to break it, or flick it into an edge to make it disappear. Change prop mode to bring exploded items back.")
        guide.setWordWrap(True)
        f.addRow(guide)
        f=page("Audio & ash")
        smoke=QCheckBox("Show mouth smoke")
        smoke.setChecked(studio.settings.value("stage/mouthSmoke",True,bool))
        self.cfg["mouthSmoke"]=smoke.isChecked()
        smoke.toggled.connect(lambda enabled:self.change("mouthSmoke",enabled))
        f.addRow(smoke)
        impact_audio=QCheckBox("Play prop impact sound")
        impact_audio.setChecked(studio.settings.value("stage/impactSound",True,bool))
        studio.effects.impact_audio=impact_audio.isChecked()
        def sound_changed(on):
            studio.effects.impact_audio=on
            studio.settings.setValue("stage/impactSound",on)
        impact_audio.toggled.connect(sound_changed)
        f.addRow(impact_audio)
        self.mic=QComboBox();f.addRow("Listen to",self.mic)
        self.mic.addItem("Off",None)
        self.mic.addItem("Windows default microphone","default-mic")
        self.mic.addItem("Windows desktop audio (playback)","default-playback")
        self.mic.currentIndexChanged.connect(self.audio)
        button(f,"Refresh Windows audio devices",self.scan_audio)
        self.meter=QProgressBar();self.meter.setRange(0,60);self.meter.setTextVisible(False)
        f.addRow("Input level",self.meter)
        self.audio_status=QLabel("Audio is off.");self.audio_status.setWordWrap(True);f.addRow(self.audio_status)
        number(f,"sensitivity")
        hint=QLabel("Use the microphone for your voice or desktop audio for sounds playing through Windows. Louder sustained sounds shake loose more ash.")
        hint.setWordWrap(True);f.addRow(hint)
        self.meter_timer=QTimer(self);self.meter_timer.timeout.connect(self.update_meter);self.meter_timer.setInterval(150)
        self.audio_scanned=False
        f=page("Effects & shortcuts")
        for i,name in enumerate(EFFECTS):
            b=QPushButton(name);keys=QKeySequenceEdit()
            keys.setMaximumSequenceLength(1)
            keys.setKeySequence(QKeySequence(studio.settings.value('hotkey/'+str(i),f"Ctrl+Alt+F{i+9}")))
            self.keys.append(keys);f.addRow(b,keys)
            b.clicked.connect(lambda checked=False,j=i:studio.effects.fx.append(j))
            keys.editingFinished.connect(self.register)
        calibration_key=QKeySequenceEdit()
        calibration_key.setMaximumSequenceLength(1)
        calibration_key.setKeySequence(QKeySequence(studio.settings.value("hotkey/3","Ctrl+Alt+C")))
        self.keys.append(calibration_key)
        f.addRow("Calibrate camera",calibration_key)
        calibration_key.editingFinished.connect(self.register)
        hint=QLabel("Assign the same shortcuts to Stream Deck Hotkey actions. Shortcuts operate while the game is focused.");hint.setWordWrap(True);f.addRow(hint)
        from video import INPUT_MODES, INPUT_RATES, OUTPUT_MODES, display_mode
        video = page("Camera & video")
        def mode_picker(modes, selected):
            picker = QComboBox()
            for mode in modes:
                picker.addItem(display_mode(mode), mode)
            picker.setCurrentIndex(picker.findData(selected))
            return picker
        self.kiyo=QCheckBox("Use Kiyo Pro tracking profile")
        self.kiyo.setChecked(studio.settings.value("video/kiyo",True,bool))
        self.kiyo.setEnabled(False)
        video.addRow(self.kiyo)
        def update_kiyo(enabled):
            studio.settings.setValue("video/kiyo",enabled)
            studio.select_camera()
        self.kiyo.toggled.connect(update_kiyo)
        self.capture_profile=False
        size,rate=studio.capture_modes[False]
        self.input_mode=mode_picker(INPUT_MODES,size)
        self.input_rate=QComboBox()
        for fps in INPUT_RATES:
            self.input_rate.addItem(f"{fps} FPS" if fps else "Device default",fps)
        self.input_rate.setCurrentIndex(self.input_rate.findData(rate))
        self.output_mode = mode_picker(OUTPUT_MODES, studio.output_mode)
        video.addRow("Camera input resolution", self.input_mode)
        video.addRow("Camera input frame rate",self.input_rate)
        self.codec=QComboBox()
        for label,key in (("Automatic (MJPEG for HD or 60 FPS)","auto"),("MJPEG · compressed","mjpg"),
                          ("YUY2 · uncompressed","yuy2"),("NV12 · uncompressed","nv12"),("Driver default","driver")):
            self.codec.addItem(label,key)
        self.codec.setCurrentIndex(max(0,self.codec.findData(studio.settings.value("video/codec","auto"))))
        self.codec.setToolTip("USB webcams usually need MJPEG to deliver 1080p at 60 FPS. "
                              "Uncompressed formats avoid JPEG artifacts at lower resolutions.")
        video.addRow("Camera stream format",self.codec)
        self.received = QLabel("Avatar preview")
        self.received.setWordWrap(True)
        video.addRow("Actual camera input", self.received)
        video.addRow("Output resolution", self.output_mode)
        self.fps = QComboBox()
        for rate in (30,60): self.fps.addItem(f"{rate} FPS",rate)
        self.fps.setCurrentIndex(self.fps.findData(studio.fps))
        video.addRow("Output frame rate",self.fps)
        button(video, "Apply video settings", studio.apply_video)
        button(video, "Windows camera settings…", studio.windows_camera_settings)
        button(video, "Webcam driver controls…", studio.driver_controls)
        hint = QLabel("Apply to request the selected camera resolution and frame rate. Actual camera input shows what the driver delivers. Output settings control the stream independently.")
        hint.setWordWrap(True)
        video.addRow(hint)
        perf=page("Performance")
        from gpu import QUALITY, DEFAULT_QUALITY
        self.quality=QComboBox()
        for key,(label,*_) in QUALITY.items():
            self.quality.addItem(label,key)
        self.quality.setCurrentIndex(max(0,self.quality.findData(studio.settings.value("video/quality",DEFAULT_QUALITY))))
        self.quality.setToolTip("Supersampling renders the stage above the output resolution and filters it down. "
                                "Glow adds light around The Joint's burning ember on transparent and studio-backdrop output.")
        perf.addRow("Rendering quality",self.quality)
        self.quality_note=QLabel()
        self.quality_note.setWordWrap(True)
        perf.addRow(self.quality_note)
        self.quality.currentIndexChanged.connect(lambda _:self.quality_note.setText(studio.set_quality(self.quality.currentData())))
        import perf as tuning
        self.ccd=QCheckBox("Keep JointCam on the second CPU die")
        self.ccd.setToolTip("On Ryzen processors with two CCDs, games run on the first die. Keeping the tracker and "
                            "renderer on the other die avoids sharing its L3 cache with the game.")
        multi=tuning.multi_ccd()
        self.ccd.setEnabled(multi)
        self.ccd.setChecked(multi and studio.settings.value("perf/isolateCcd",True,bool))
        perf.addRow(self.ccd)
        self.ccd_note=QLabel(studio.set_cpu_placement(self.ccd.isChecked()) if multi else "Single CPU die detected.")
        self.ccd_note.setWordWrap(True)
        perf.addRow(self.ccd_note)
        self.ccd.toggled.connect(lambda on:self.ccd_note.setText(studio.set_cpu_placement(on)))
        self.profile=QCheckBox("Measure rendering times")
        perf.addRow(self.profile)
        details=QLabel("Samples up to ten frames per second. Values show median and 95th percentile for the last 120 samples of each active stage. GPU times include scheduling waits. The Spout CPU time includes waits inside the sender.")
        details.setWordWrap(True)
        perf.addRow(details)
        self.profile_result=QLabel()
        self.profile_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        perf.addRow(self.profile_result)
        self.profile.toggled.connect(studio.profile_changed)
        self.bindings={}
        self.tabs.currentChanged.connect(lambda idx:self.scan_audio() if idx==2 and not self.audio_scanned else None)
        self.register()
        self.sync()
        self.tabs.currentChanged.connect(self.sync_meter)

    def sync_meter(self,*_):
        if self.meter.isVisible():
            self.update_meter()
            self.meter_timer.start()
        else:
            self.meter_timer.stop()

    def showEvent(self,event):
        super().showEvent(event)
        self.sync_meter()

    def hideEvent(self,event):
        self.meter_timer.stop()
        super().hideEvent(event)

    def sync_kiyo(self,matched):
        self.down_tilt.setEnabled(matched)
        self.kiyo.setEnabled(matched)
        active=matched and self.kiyo.isChecked()
        if active!=self.capture_profile:
            self.capture_profile=active
            size,rate=self.host.capture_modes[active]
            self.input_mode.setCurrentIndex(self.input_mode.findData(size))
            self.input_rate.setCurrentIndex(self.input_rate.findData(rate))

    def sync(self):
        self.box["arms"].setEnabled(not self.cfg["faceOnly"])
        self.box["ninjas"].setEnabled(not self.cfg["faceOnly"])
        self.prop_mode.setEnabled(not self.cfg["faceOnly"])
        for k in ["centerX","eyeY","mouthY","spacing"]:self.box[k].setEnabled(self.cfg["manual"])
        self.host.torso.setEnabled(not self.cfg["faceOnly"])
    def change(self,k,value):
        self.cfg[k]=value;self.host.settings.setValue("stage/"+k,value)
        self.sync()
        if k in ("matte","lipReach","centerX","eyeY","mouthY","spacing","faceOnly","arms","manual","ninjas","fullHands"):
            self.host.cam.set_tracking_option(k,value)
        if k=="manual" and value and self.host.pending_center:
            self.host.pending_center=False
            self.host.calibration_message("Calibration paused. Switch to automatic face tracking to calibrate.")
        self.host.microphone.sensitivity=self.cfg["sensitivity"]
    def set_props(self):
        mode=self.prop_mode.currentData()
        self.cfg["propMode"]=mode
        self.host.settings.setValue("stage/propMode",mode)
        self.host.settings.remove("prop-exclusions")
        active=mode!="off"
        self.cfg["floaters"]=active
        self.host.effects.js.evaluate("floatingProps.setMode").call([mode])
        self.host.cam.set_tracking_option("floaters",active)
    def scan_audio(self):
        old=self.mic.currentData()
        mic=self.host.microphone
        mic.close()
        self.mic.blockSignals(True)
        while self.mic.count()>3:self.mic.removeItem(3)
        try:
            for label,device in mic.devices():
                self.mic.addItem(label,label)
            self.audio_scanned=True
        except Exception as exc:
            self.audio_status.setText("Could not list Windows audio devices. "+str(exc))
            self.mic.setCurrentIndex(0)
            return
        finally:
            self.mic.blockSignals(False)
        idx=self.mic.findData(old) if old else 0
        self.mic.blockSignals(True);self.mic.setCurrentIndex(max(0,idx));self.mic.blockSignals(False)
        if old and idx<0:self.audio_status.setText("Device disconnected. Choose another source.")
        else:self.audio()

    def audio(self):
        try:
            self.host.microphone.open(self.mic.currentData())
            self.audio_status.setText("Waiting for audio…" if self.mic.currentData() else "Audio is off.")
        except Exception as exc:
            self.mic.blockSignals(True);self.mic.setCurrentIndex(0);self.mic.blockSignals(False)
            self.audio_status.setText("Could not open audio. Check the Windows sound device and microphone access, then refresh. "+str(exc))

    def update_meter(self):
        if not self.meter.isVisible():return
        mic=self.host.microphone
        now=time.monotonic()
        fresh=mic.stream is not None and now-mic.received<1.
        self.meter.setValue(round(max(0.,min(60.,mic.signal.db+60))) if fresh else 0)
        if mic.error:self.audio_status.setText("Audio stopped. Refresh devices. "+mic.error)
        elif fresh:
            label="Loud burst detected" if now-mic.signal.last_yell<.75 else "Listening"
            self.audio_status.setText(f"{label} · {mic.signal.db:.0f} dBFS")
        elif mic.stream is not None:self.audio_status.setText("Waiting for audio. Speak or play sound on the selected device.")

    def unbind(self):
        if sys.platform=="win32":
            for i in self.bindings:ctypes.windll.user32.UnregisterHotKey(ctypes.c_void_p(int(self.host.winId())),800+i)
        self.bindings.clear()
    def register(self):
        self.unbind()
        failures=[]
        for i,edit in enumerate(self.keys):
            seq=edit.keySequence()
            self.host.settings.setValue("hotkey/"+str(i),seq.toString())
            if seq.isEmpty():continue
            combo=seq[0];key=int(combo.key());mods=combo.keyboardModifiers()
            vk=key if 48<=key<=57 or 65<=key<=90 else 112+key-int(Qt.Key_F1) if Qt.Key_F1<=key<=Qt.Key_F24 else 0
            if not vk:failures.append((EFFECTS+("Calibrate camera",))[i]);continue
            bits=sum(n for mask,n in [(Qt.ControlModifier,2),(Qt.AltModifier,1),(Qt.ShiftModifier,4),(Qt.MetaModifier,8)] if mods&mask)
            if sys.platform=="win32" and not ctypes.windll.user32.RegisterHotKey(ctypes.c_void_p(int(self.host.winId())),800+i,0x4000|bits,vk):
                failures.append((EFFECTS+("Calibrate camera",))[i]);continue
            self.bindings[i]=vk
        shortcut=self.keys[3].keySequence().toString()
        tooltip=f"Global shortcut: {shortcut}" if 3 in self.bindings else "Set a global shortcut in Stage controls → Effects & shortcuts."
        self.host.calibration_button.setToolTip(tooltip)
        self.note.setText("Choose another shortcut for "+", ".join(failures) if failures else "")

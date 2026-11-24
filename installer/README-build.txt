Building the JointCam Studio installer
=======================================

    python installer/build_installer.py

produces dist/JointCam-Studio-1.2.0-Setup.exe: one self-contained 64-bit setup file with the
app, the official CPython 3.12.10 runtime (Python Software Foundation NuGet package), every
Python package as a hash-pinned Windows wheel, and the native launcher.

Works on Windows or Linux. Needs:
  * Python with pip. Use Python 3.12 so the bundled code is precompiled for a fast first launch.
  * NSIS 3 (makensis).  Windows: https://nsis.sourceforge.io   Linux: apt install nsis
  * Optional, to rebuild the launcher: mingw-w64 (x86_64-w64-mingw32-gcc, windres).
    Without it the prebuilt launcher/JointCam Studio.exe is used.

Options:  --stage-only (prepare build/stage only)   --package-only (rerun NSIS on build/stage)
          --out DIR (where the setup .exe goes)

Files
  build_installer.py         downloads (cached in build/cache, hash-checked), stages, trims, packages
  requirements-windows.txt   pinned Windows wheels with SHA-256 hashes
  installer.nsi              NSIS script: per-user install, Start menu/desktop shortcuts,
                             Add/Remove Programs entry, exact-file uninstall
  launcher/launcher.c        "JointCam Studio.exe": hosts Python in its own process, so the taskbar
                             and Task Manager show JointCam Studio with its icon. No C runtime.
  launcher/launcher.rc       icon, version information and manifest

What the build trims (verified by dependency analysis of the PE import tables)
  * Qt: only the libraries reachable from QtCore/Gui/Widgets/Qml/OpenGL/OpenGLWidgets and the
    platform/style/image plugins are kept, plus the software-OpenGL fallback (~61 MB saved).
  * MediaPipe's jax, jaxlib, scipy, sentencepiece and sounddevice dependencies are not imported
    by the face mesh, pose and hand solutions and are left out (~150 MB saved).
  * OpenCV's FFmpeg video-file library and Haar cascades, package test suites, pip, C headers.

Runtime layout after install
  JointCam Studio.exe, boot.py, studio.py, ... , assets\, rig\
  runtime\python312.dll + python312._pth   (isolated: ignores PYTHONPATH, PYTHONHOME, the
                                            registry and user site-packages)
  runtime\Lib\site-packages\...            (all packages)
  runtime\msvcp140*.dll, vcruntime140*.dll (shared Visual C++ runtime for every module)

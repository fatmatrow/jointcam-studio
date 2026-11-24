JointCam Studio 1.1.0 - Windows installer
==========================================

1. Extract this ZIP (right-click it, Extract All).
2. Double-click Join-JointCam-Setup.cmd. It joins the five pieces into
   JointCam-Studio-1.1.0-Setup.exe, checks its SHA-256 fingerprint and starts it.
3. If Windows shows "Windows protected your PC", click More info, then Run anyway.
   The setup is not code-signed.

If Windows blocks the .cmd file, open this folder, type cmd in the address bar, press Enter and run:

copy /b JointCam-Studio-1.1.0-Setup.exe.part1+JointCam-Studio-1.1.0-Setup.exe.part2+JointCam-Studio-1.1.0-Setup.exe.part3+JointCam-Studio-1.1.0-Setup.exe.part4+JointCam-Studio-1.1.0-Setup.exe.part5 JointCam-Studio-1.1.0-Setup.exe

Setup SHA-256: 9afcf2d72be713a13a289c0628e7534685aa7bdada7976f836f674c2e627407e
Source code: branch jointcam-studio-1.1.0 of this repository.

JointCam Studio 1.2.0 - Windows installer
==========================================

1. Extract this ZIP (right-click it, Extract All).
2. Double-click Join-JointCam-Setup.cmd. It joins the five pieces into
   JointCam-Studio-1.2.0-Setup.exe, checks its SHA-256 fingerprint and starts it.
3. If Windows shows "Windows protected your PC", click More info, then Run anyway.
   The setup is not code-signed.

Installing 1.2.0 over 1.1.0 updates it in place and keeps your settings.

If Windows blocks the .cmd file, open this folder, type cmd in the address bar, press Enter and run:

copy /b JointCam-Studio-1.2.0-Setup.exe.part1+JointCam-Studio-1.2.0-Setup.exe.part2+JointCam-Studio-1.2.0-Setup.exe.part3+JointCam-Studio-1.2.0-Setup.exe.part4+JointCam-Studio-1.2.0-Setup.exe.part5 JointCam-Studio-1.2.0-Setup.exe

Setup SHA-256: 58c626d2fa7c6dc908d3cac36e2202141bb000b7304448948e5b7768420a124c
Source code: branch jointcam-studio-1.2.0 of this repository.

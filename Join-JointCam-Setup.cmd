@echo off
rem Rebuilds JointCam-Studio-1.1.0-Setup.exe from its 5 parts and checks it.
rem Put this file in the same folder as the parts, then double-click it.
pushd "%~dp0"
copy /b "JointCam-Studio-1.1.0-Setup.exe.part1"+"JointCam-Studio-1.1.0-Setup.exe.part2"+"JointCam-Studio-1.1.0-Setup.exe.part3"+"JointCam-Studio-1.1.0-Setup.exe.part4"+"JointCam-Studio-1.1.0-Setup.exe.part5" "JointCam-Studio-1.1.0-Setup.exe" >nul
if errorlevel 1 (echo A part is missing. Download all 5 parts into this folder. & pause & exit /b 1)
certutil -hashfile "JointCam-Studio-1.1.0-Setup.exe" SHA256 | findstr /i "9afcf2d72be713a13a289c0628e7534685aa7bdada7976f836f674c2e627407e" >nul
if errorlevel 1 (echo The parts did not combine correctly. Download them again. & del "JointCam-Studio-1.1.0-Setup.exe" & pause & exit /b 1)
echo Setup rebuilt and verified. Starting it now...
start "" "JointCam-Studio-1.1.0-Setup.exe"

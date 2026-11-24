@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "diagdir=%LOCALAPPDATA%\JointCam Studio"
if not exist "%diagdir%" mkdir "%diagdir%"
set "report=%diagdir%\loader-report.txt"
> "%report%" echo JointCam Studio 1.2.0 Windows loader check
>> "%report%" ver
call :probe "Python runtime" "import sys; print(sys.version)"
if errorlevel 1 goto done
call :probe "Qt widgets and platform plugin" "from PySide6.QtWidgets import QApplication; app=QApplication([]); print(app.platformName())"
call :probe "Qt scripting" "from PySide6.QtQml import QJSEngine"
call :probe "OpenCV and NumPy" "import cv2,numpy"
call :probe "Impact sound module" "import winsound"
call :probe "Runtime tuning" "import perf; perf.configure_libraries(); print(perf.l3_groups())"
call :probe "Studio entry point" "import studio"
:done
popd
start "" notepad.exe "%report%"
exit /b
:probe
>> "%report%" echo.
>> "%report%" echo %~1
"runtime\python.exe" -X faulthandler -c "%~2" >> "%report%" 2>&1
set "result=%errorlevel%"
>> "%report%" echo Exit code %result%
exit /b %result%

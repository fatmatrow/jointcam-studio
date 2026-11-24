; JointCam Studio installer. Built by installer/build_installer.py, which passes:
;   VERSION, STAGE (staged program folder), OUTFILE, ICON, UNINSTALL_LIST, INSTALLED_KB
; Installs per user (no administrator prompt) into %LOCALAPPDATA%\Programs.

; 64-bit installer for a 64-bit program. It refuses to start on 32-bit Windows.
Target amd64-unicode
ManifestDPIAware true
SetCompressor /SOLID lzma
SetCompressorDictSize 64
RequestExecutionLevel user

!include "MUI2.nsh"
!include "LogicLib.nsh"

!define APPNAME "JointCam Studio"
!define EXE "JointCam Studio.exe"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\JointCamStudioStandalone"

Name "${APPNAME} ${VERSION}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APPNAME} Standalone"
InstallDirRegKey HKCU "${UNINSTALL_KEY}" "InstallLocation"
BrandingText "${APPNAME} ${VERSION}"
ShowInstDetails show
ShowUninstDetails nevershow

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME} Setup"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "${APPNAME}"

!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Install ${APPNAME} ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "This installs ${APPNAME}, a live animated webcam avatar for OBS.$\r$\n$\r$\nEverything it needs is included: no Python, Qt or other runtime has to be installed separately. Administrator rights are not required.$\r$\n$\r$\nClose ${APPNAME} before continuing."
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APPNAME}"
!define MUI_FINISHPAGE_SHOWREADME ""
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Create a desktop shortcut"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION DesktopShortcut
!define MUI_FINISHPAGE_LINK "Open the Quick-start guide"
!define MUI_FINISHPAGE_LINK_LOCATION "$INSTDIR\Quick-start.txt"

!define MUI_COMPONENTSPAGE_SMALLDESC
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function DesktopShortcut
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0
FunctionEnd

; A running copy keeps its program files locked. Ask the user to close it first.
!macro WaitForAppToClose
  ${Do}
    ${IfNot} ${FileExists} "$INSTDIR\${EXE}"
      ${Break}
    ${EndIf}
    ClearErrors
    FileOpen $0 "$INSTDIR\${EXE}" a
    ${IfNot} ${Errors}
      FileClose $0
      ${Break}
    ${EndIf}
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "${APPNAME} is running. Close it, then click Retry." /SD IDCANCEL IDRETRY retry_after_close
    Abort
    retry_after_close:
  ${Loop}
!macroend

Section "JointCam Studio" SecApp
  SectionIn RO
  SetShellVarContext current
  !insertmacro WaitForAppToClose
  ; Replace the previous version's runtime completely so no stale package files remain.
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\__pycache__"
  SetOutPath "$INSTDIR"
  File /r "${STAGE}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateShortcut "$SMPROGRAMS\${APPNAME}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0
  CreateShortcut "$SMPROGRAMS\${APPNAME} add-ons.lnk" "$INSTDIR\runtime\python.exe" '"$INSTDIR\addons.py" --all --pause' "$INSTDIR\${EXE}" 0
  ${If} ${Silent}
    Call DesktopShortcut
  ${EndIf}

  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\${EXE},0"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "${APPNAME}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "EstimatedSize" ${INSTALLED_KB}
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
SectionEnd

; Components fetched from their official sources while installing (see addons.py). Each one is
; skipped when already present, and each one's own installer asks for administrator rights.
SectionGroup /e "Download and install add-ons" SecAddons
  Section "OBS Studio (only if not installed)" SecObs
  SectionEnd
  Section "OBS Spout2 plugin" SecSpout
  SectionEnd
  Section "NVIDIA AR SDK runtime" SecNvidia
  SectionEnd
SectionGroupEnd

Section "-Run add-ons"
  ${If} ${Silent}
    Return
  ${EndIf}
  StrCpy $1 ""
  ${If} ${SectionIsSelected} ${SecObs}
    StrCpy $1 "$1 --obs"
  ${EndIf}
  ${If} ${SectionIsSelected} ${SecSpout}
    StrCpy $1 "$1 --spout"
  ${EndIf}
  ${If} ${SectionIsSelected} ${SecNvidia}
    StrCpy $1 "$1 --nvidia"
  ${EndIf}
  ${If} $1 != ""
    DetailPrint "Checking and installing add-ons. This needs an internet connection."
    nsExec::ExecToLog '"$INSTDIR\runtime\python.exe" -u "$INSTDIR\addons.py"$1'
    Pop $0
  ${EndIf}
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecApp} "The app with everything it needs to run: Python, Qt, OpenCV, MediaPipe and the Visual C++ runtime are included."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecAddons} "Downloaded from their official sources and checked before they run. Already-installed components are skipped. Windows asks for administrator approval for each one."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecObs} "The streaming app JointCam sends to. Downloaded from the OBS Project's GitHub releases only if OBS is not installed."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecSpout} "Lets OBS receive JointCam's transparent GPU texture (Spout2 output). From Off-World Live's GitHub releases."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecNvidia} "NVIDIA RTX face tracking. The build for this PC's GPU generation, from NVIDIA, checked for NVIDIA's code signature. Skipped on PCs without an RTX GPU."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  SetShellVarContext current
  !insertmacro WaitForAppToClose
  Delete "$SMPROGRAMS\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME} add-ons.lnk"
  Delete "$DESKTOP\${APPNAME}.lnk"
  ; Remove only what the installer put here, then the folder if it is empty.
  !include "${UNINSTALL_LIST}"
  RMDir /r "$INSTDIR\__pycache__"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  ; Settings (registry) and %LOCALAPPDATA%\JointCam Studio\startup.log are kept for a reinstall.
SectionEnd

"""Build the JointCam Studio Windows installer (a single self-contained setup .exe).

The installer carries everything the app needs: the official CPython 3.12 Windows runtime
(from the Python Software Foundation's NuGet package), every Python package as a
hash-pinned Windows wheel, the native launcher and the app itself. Nothing else needs
to be installed on the PC.

Runs on Windows or Linux:
    python installer/build_installer.py

Requirements on the build machine
    * Python 3.8+ with pip. Python 3.12 additionally precompiles the bundled code so the
      first launch is fast. Other versions skip that step and Windows compiles on first run.
    * NSIS 3 (makensis). Windows: https://nsis.sourceforge.io  Linux: apt install nsis
    * To rebuild the launcher: x86_64-w64-mingw32-gcc and windres (apt install mingw-w64,
      or MSYS2 on Windows). Without them the prebuilt installer/launcher/JointCam Studio.exe is used.

Downloads are cached in build/cache and checked against pinned SHA-256 hashes.
"""
import argparse
import compileall
import hashlib
import os
import py_compile
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "1.3.0"
PYTHON_VERSION = "3.12.10"
PYTHON_URL = f"https://api.nuget.org/v3-flatcontainer/python/{PYTHON_VERSION}/python.{PYTHON_VERSION}.nupkg"
PYTHON_SHA256 = "0eb85c2dfccccf1b17352de4c397f69194035b7d37149eacc16f1147d93de3b8"

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUILD = ROOT / "build"
CACHE = BUILD / "cache"
STAGE = BUILD / "stage" / "JointCam Studio"
RUNTIME = STAGE / "runtime"
SITE = RUNTIME / "Lib" / "site-packages"
LAUNCHER_NAME = "JointCam Studio.exe"

# App files that are not part of the installed program.
APP_EXCLUDE = {"installer", "build", "dist", ".git", "__pycache__", "JointCam.exe"}
APP_EXCLUDE_SUFFIX = (".pyc", ".zip", "-Code.txt", ".diff")

# Qt modules the app imports. Everything else in PySide6 is unreachable.
QT_MODULES = ("QtCore", "QtGui", "QtWidgets", "QtQml", "QtOpenGL", "QtOpenGLWidgets")
QT_PLUGIN_DIRS = ("platforms", "styles", "imageformats", "iconengines", "generic", "platforminputcontexts")
# Qt's 20 MB software OpenGL (opengl32sw.dll) is not shipped: without a working OpenGL driver
# JointCam already falls back to its own compatibility renderer.
QT_DYNAMIC = set()
VC_RUNTIME = re.compile(r"^(msvcp140.*|vcruntime140.*|concrt140|vcomp140)\.dll$", re.I)


def log(text):
    print(text, flush=True)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url, target, expected):
    if target.exists() and sha256(target) == expected:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    log(f"Downloading {url}")
    partial = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(url) as response, open(partial, "wb") as out:
        shutil.copyfileobj(response, out)
    actual = sha256(partial)
    if actual != expected:
        partial.unlink()
        raise SystemExit(f"Hash mismatch for {url}\n expected {expected}\n got      {actual}")
    partial.replace(target)
    return target


def download_wheels():
    wheels = CACHE / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    log("Downloading Windows wheels (hash-checked)")
    subprocess.run([sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "--quiet",
                    "--no-deps", "--only-binary=:all:", "--platform", "win_amd64",
                    "--python-version", "3.12", "--implementation", "cp", "--require-hashes",
                    "-r", str(HERE / "requirements-windows.txt"), "-d", str(wheels)], check=True)
    pinned = {}
    for line in (HERE / "requirements-windows.txt").read_text().splitlines():
        match = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)", line)
        if match:
            pinned[re.sub(r"[-_.]+", "_", match.group(1)).lower()] = match.group(2)
    selected = []
    for wheel in sorted(wheels.glob("*.whl")):
        name, version = wheel.name.split("-")[:2]
        if pinned.get(name.lower()) == version:
            selected.append(wheel)
    missing = set(pinned) - {w.name.split("-")[0].lower() for w in selected}
    if missing:
        raise SystemExit(f"Missing wheels: {sorted(missing)}")
    return selected


# ---------------------------------------------------------------------------- PE helpers

def pe_imports(path):
    """DLL names imported (directly or delay-loaded) by a Windows PE file."""
    data = Path(path).read_bytes()
    if data[:2] != b"MZ":
        return set()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe+4] != b"PE\0\0":
        return set()
    sections, optional_size = struct.unpack_from("<H", data, pe+6)[0], struct.unpack_from("<H", data, pe+20)[0]
    optional = pe+24
    directories = optional + (112 if struct.unpack_from("<H", data, optional)[0] == 0x20B else 96)
    table = []
    for i in range(sections):
        virtual_size, address, raw_size, raw = struct.unpack_from("<IIII", data, optional+optional_size+i*40+8)
        table.append((address, max(virtual_size, raw_size), raw))

    def offset(rva):
        for address, size, raw in table:
            if address <= rva < address+size:
                return rva-address+raw
        return None

    def text(at):
        return data[at:data.index(b"\0", at)].decode("ascii", "replace")

    names = set()
    for entry, stride, name_at in ((1, 20, 12), (13, 32, 4)):
        rva = struct.unpack_from("<I", data, directories+8*entry)[0]
        at = offset(rva) if rva else None
        while at is not None and at+stride <= len(data):
            name_rva = struct.unpack_from("<I", data, at+name_at)[0]
            if not name_rva or offset(name_rva) is None:
                break
            names.add(text(offset(name_rva)))
            at += stride
    return names


def file_version(path):
    data = Path(path).read_bytes()
    at = data.find(b"\xbd\x04\xef\xfe")
    if at < 0:
        return (0, 0, 0, 0)
    ms, ls = struct.unpack_from("<II", data, at+8)
    return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)


# ---------------------------------------------------------------------------- staging

def stage_app():
    log("Staging app files")
    for item in sorted(ROOT.iterdir()):
        if item.name in APP_EXCLUDE or item.name.endswith(APP_EXCLUDE_SUFFIX) or item.name.startswith("."):
            continue
        target = STAGE / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(item, target)


def stage_python(package):
    log(f"Staging CPython {PYTHON_VERSION}")
    skip_dirs = ("Lib/site-packages/", "include/", "libs/", "Lib/ensurepip/", "Lib/lib2to3/",
                 "Lib/idlelib/", "Lib/tkinter/", "Lib/turtledemo/", "Lib/test/")
    skip_files = re.compile(r"(^|/)(_tkinter\.pyd|tcl\d+t\.dll|tk\d+t\.dll)$", re.I)
    with zipfile.ZipFile(package) as archive:
        for info in archive.infolist():
            if not info.filename.startswith("tools/") or info.is_dir():
                continue
            relative = info.filename[len("tools/"):]
            if relative.startswith(skip_dirs) or "__pycache__/" in relative or skip_files.search(relative):
                continue
            target = RUNTIME / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)
    # Self-contained path configuration. Relative to runtime\. ".." is the app folder.
    (RUNTIME / "python312._pth").write_text("Lib\nDLLs\nLib\\site-packages\n..\nimport site\n", encoding="ascii")


def keep_wheel_member(name):
    parts = name.split("/")
    top = parts[0]
    if "__pycache__" in parts:
        return False
    if top == "cv2" and len(parts) > 1 and parts[1] == "data":
        return False  # Haar cascade XML files. JointCam uses MediaPipe and the NVIDIA runtime.
    if top == "cv2" and re.match(r"opencv_videoio_ffmpeg.*\.dll$", parts[-1], re.I):
        return False  # FFmpeg reads video files. Webcams use DirectShow.
    if top in ("numpy", "matplotlib", "contourpy", "kiwisolver", "fontTools", "PIL") and "tests" in parts[1:-1]:
        return False
    if top == "matplotlib" and "sample_data" in parts:
        return False
    if top == "PySide6" and len(parts) > 1:
        second = parts[1]
        if second in ("translations", "qml", "metatypes", "include", "typesystems", "glue", "resources",
                      "scripts", "doc", "examples"):
            return False
        if second == "plugins" and len(parts) > 2 and parts[2] not in QT_PLUGIN_DIRS:
            return False
        if len(parts) == 2 and second.endswith(".exe"):
            return False
    return True


def stage_wheels(wheels):
    log(f"Installing {len(wheels)} packages into the runtime")
    SITE.mkdir(parents=True, exist_ok=True)
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            for info in archive.infolist():
                name = info.filename
                if info.is_dir():
                    continue
                # Wheel .data/purelib|platlib map into site-packages. Scripts and headers are not needed.
                data = re.match(r"^[^/]+\.data/(purelib|platlib)/(.+)$", name)
                if data:
                    name = data.group(2)
                elif re.match(r"^[^/]+\.data/", name):
                    continue
                if not keep_wheel_member(name):
                    continue
                target = SITE / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out)


def prune_qt():
    """Delete Qt DLLs that no kept module or plugin can reach."""
    qt = SITE / "PySide6"
    local = {p.name.lower(): p for p in list(qt.glob("*.dll")) + list((SITE / "shiboken6").glob("*.dll"))}
    roots = [qt / f"{m}.pyd" for m in QT_MODULES]
    for folder in QT_PLUGIN_DIRS:
        roots += list((qt / "plugins" / folder).glob("*.dll"))
    needed, stack = set(QT_DYNAMIC), list(roots)
    while stack:
        for name in pe_imports(stack.pop()):
            key = name.lower()
            if key in local and key not in needed:
                needed.add(key)
                stack.append(local[key])
    removed = 0
    for key, path in local.items():
        if path.parent == qt and key not in needed and not VC_RUNTIME.match(key):
            removed += path.stat().st_size
            path.unlink()
    # Bindings import each other at the Python level (QtQml imports QtNetwork), which the PE
    # graph cannot see. Keep every binding whose Qt library survived, remove the rest.
    for binding in list(qt.glob("Qt*.pyd")) + list(qt.glob("Qt*.pyi")):
        library = "qt6" + binding.stem[2:].lower() + ".dll"
        if library not in needed:
            removed += binding.stat().st_size
            binding.unlink()
    # A plugin that links a Qt library no longer present would fail every time Qt scans
    # its folder (for example the PDF image reader and the virtual keyboard).
    present = {p.name.lower() for p in qt.glob("*.dll")}
    for folder in QT_PLUGIN_DIRS:
        for plugin in (qt / "plugins" / folder).glob("*.dll"):
            missing = [n for n in pe_imports(plugin) if n.lower().startswith("qt6") and n.lower() not in present]
            if missing:
                removed += plugin.stat().st_size
                plugin.unlink()
    log(f"  Qt: kept {len([k for k in local if k in needed])} libraries, removed {removed/1e6:.0f} MB")


def lazy_matplotlib():
    """MediaPipe imports matplotlib.pyplot at module level for one 3-D plotting helper that
    JointCam never calls. Make that import lazy so matplotlib and its dependencies (about
    50 MB) need not be bundled, and MediaPipe starts noticeably faster."""
    path = SITE / "mediapipe" / "python" / "solutions" / "drawing_utils.py"
    source = path.read_text(encoding="utf-8")
    line = "import matplotlib.pyplot as plt\n"
    if source.count(line) != 1:
        raise SystemExit("MediaPipe's drawing_utils.py changed: review the lazy matplotlib patch.")
    lazy = ("class _LazyPyplot:  # JointCam build: matplotlib loads only if plot_landmarks is called.\n"
            "  def __getattr__(self, name):\n"
            "    import matplotlib.pyplot as pyplot\n"
            "    return getattr(pyplot, name)\n"
            "plt = _LazyPyplot()\n")
    path.write_text(source.replace(line, lazy), encoding="utf-8")


def share_vc_runtime():
    """Give every module the newest Visual C++ runtime, even without the VC++ redistributable."""
    for source in (SITE / "PySide6").glob("*.dll"):
        if VC_RUNTIME.match(source.name):
            target = RUNTIME / source.name
            if not target.exists() or file_version(source) > file_version(target):
                shutil.copy2(source, target)


def check_dependencies():
    """List DLL imports that nothing in the runtime provides and that are not Windows system DLLs."""
    system = re.compile(r"^(api-ms-win-.*|ext-ms-.*|kernel32|kernelbase|user32|gdi32|gdiplus|advapi32|shell32|"
                        r"shlwapi|ole32|oleaut32|comdlg32|comctl32|ws2_32|wsock32|winmm|version|imm32|uxtheme|"
                        r"dwmapi|opengl32|glu32|d3d9|d3d11|d3d12|dxgi|dcomp|d3dcompiler_47|setupapi|cfgmgr32|"
                        r"shcore|userenv|netapi32|crypt32|bcrypt|ncrypt|secur32|iphlpapi|dnsapi|wtsapi32|psapi|"
                        r"dbghelp|mf|mfplat|mfreadwrite|mfuuid|mfplay|evr|strmiids|quartz|ksuser|avrt|"
                        r"propsys|rpcrt4|wintrust|ntdll|msvcrt|ucrtbase|mpr|authz|normaliz|winhttp|wininet|"
                        r"urlmon|hid|dinput8|xinput1_4|dxva2|mfsensorgroup|oleacc|usp10|dwrite|d2d1|"
                        r"windowscodecs|wldap32|powrprof|winspool\.drv|winspool|comsvcs|nvcuda|cabinet|msi|"
                        r"uiautomationcore|imagehlp|mscms|icuuc|icuin|icu|"
                        r"python3|python312)\.dll$", re.I)
    available = {p.name.lower() for p in RUNTIME.rglob("*.dll")} | {p.name.lower() for p in RUNTIME.rglob("*.pyd")}
    problems = {}
    for binary in list(RUNTIME.rglob("*.pyd")) + list(RUNTIME.rglob("*.dll")):
        for name in pe_imports(binary):
            if not system.match(name) and name.lower() not in available:
                problems.setdefault(name, []).append(str(binary.relative_to(RUNTIME)))
    for name, users in sorted(problems.items()):
        log(f"  note: {name} not bundled (used by {users[0]}{' and others' if len(users) > 1 else ''})")


def precompile():
    if sys.version_info[:2] != (3, 12):
        log("Skipping precompile (needs Python 3.12). Windows compiles on first launch.")
        return
    log("Precompiling bytecode")
    # The runtime never changes after install: skip per-import source checks.
    compileall.compile_dir(str(RUNTIME / "Lib"), quiet=1, workers=0,
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    # App code is validated by content hash, so edited .py files are always picked up.
    for source in STAGE.glob("*.py"):
        py_compile.compile(str(source), cfile=str(STAGE / "__pycache__" / f"{source.stem}.cpython-312.pyc"),
                           doraise=True, invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)


def build_launcher():
    folder = HERE / "launcher"
    prebuilt = folder / LAUNCHER_NAME
    gcc, windres = shutil.which("x86_64-w64-mingw32-gcc"), shutil.which("x86_64-w64-mingw32-windres")
    if gcc and windres:
        log("Compiling launcher")
        resources = BUILD / "launcher_res.o"
        subprocess.run([windres, "launcher.rc", "-O", "coff", "-o", str(resources)], cwd=folder, check=True)
        # No C runtime: Python's UCRT must be the only CRT in the process (see launcher.c).
        subprocess.run([gcc, "-O2", "-Wall", "-Wextra", "-s", "-mwindows", "-nostdlib", "-ffreestanding",
                        "-fno-stack-protector", "-fno-asynchronous-unwind-tables", "-e", "start",
                        "-o", str(prebuilt), "launcher.c", str(resources),
                        "-lkernel32", "-luser32", "-lshell32"], cwd=folder, check=True)
    elif not prebuilt.exists():
        raise SystemExit("No launcher: install mingw-w64 or provide installer/launcher/JointCam Studio.exe")
    shutil.copy2(prebuilt, STAGE / LAUNCHER_NAME)


def write_uninstall_list():
    """Exact list of installed top-level entries, so uninstall removes only JointCam's files."""
    lines = []
    for item in sorted(STAGE.iterdir()):
        if item.is_dir():
            lines.append(f'RMDir /r "$INSTDIR\\{item.name}"')
        else:
            lines.append(f'Delete "$INSTDIR\\{item.name}"')
    (BUILD / "uninstall_files.nsh").write_text("\n".join(lines) + "\n", encoding="utf-8")


def size_of(path):
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())


def run_nsis(out_dir):
    makensis = shutil.which("makensis") or shutil.which("makensis.exe")
    if not makensis:
        for guess in (r"C:\Program Files (x86)\NSIS\makensis.exe", r"C:\Program Files\NSIS\makensis.exe"):
            if Path(guess).exists():
                makensis = guess
    if not makensis:
        raise SystemExit("NSIS (makensis) not found.")
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / f"JointCam-Studio-{VERSION}-Setup.exe"
    log("Building installer")
    flag = "/" if os.name == "nt" else "-"
    subprocess.run([makensis, f"{flag}V2", f"{flag}DVERSION={VERSION}", f"{flag}DSTAGE={STAGE}",
                    f"{flag}DOUTFILE={output}", f"{flag}DICON={ROOT / 'assets' / 'jointcam.ico'}",
                    f"{flag}DUNINSTALL_LIST={BUILD / 'uninstall_files.nsh'}",
                    f"{flag}DINSTALLED_KB={size_of(STAGE)//1024}", str(HERE / "installer.nsi")], check=True)
    log(f"Installer: {output} ({output.stat().st_size/1e6:.0f} MB)")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist", help="output folder for the setup .exe")
    parser.add_argument("--stage-only", action="store_true", help="prepare build/stage without running NSIS")
    parser.add_argument("--package-only", action="store_true", help="run NSIS on an existing build/stage")
    args = parser.parse_args()
    if args.package_only:
        build_launcher()
        write_uninstall_list()
        run_nsis(args.out)
        return

    package = download(PYTHON_URL, CACHE / f"python.{PYTHON_VERSION}.nupkg", PYTHON_SHA256)
    wheels = download_wheels()
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    stage_app()
    stage_python(package)
    stage_wheels(wheels)
    prune_qt()
    lazy_matplotlib()
    share_vc_runtime()
    check_dependencies()
    precompile()
    build_launcher()
    write_uninstall_list()
    log(f"Staged {size_of(STAGE)/1e6:.0f} MB in {STAGE}")
    if not args.stage_only:
        run_nsis(args.out)


if __name__ == "__main__":
    main()

"""Download and install the components JointCam Studio uses from outside its own folder.

    OBS Studio               the streaming app JointCam sends to (only if it is not installed)
    OBS Spout2 plugin        lets OBS receive JointCam's GPU texture (Spout2 output)
    NVIDIA AR SDK runtime    NVIDIA RTX face tracking (the build for this PC's GPU generation)

The JointCam installer runs this after copying the program. It can be run again at any time
from the Start menu entry "JointCam Studio add-ons", or:

    runtime\\python.exe addons.py --all           install whatever is missing
    runtime\\python.exe addons.py --check         report only

Everything is checked before it runs: GitHub downloads against the SHA-256 digest GitHub
publishes for the release file, NVIDIA's installer against a valid NVIDIA Corporation code
signature. Each component's own installer asks Windows for administrator rights.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

USER_AGENT = "JointCam-Studio-Addons/1.3"
DOWNLOADS = Path(tempfile.gettempdir()) / "JointCam Studio add-ons"
NVIDIA_PAGE = "https://www.nvidia.com/en-us/geforce/broadcasting/broadcast-sdk/resources/"
SPOUT_REPO = "Off-World-Live/obs-spout2-plugin"
OBS_REPO = "obsproject/obs-studio"
WINDOWS = sys.platform == "win32"


def say(text=""):
    print(text, flush=True)


# --------------------------------------------------------------------------- downloads

def fetch(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def latest_release(repo):
    data = fetch(f"https://api.github.com/repos/{repo}/releases/latest")
    return json.loads(data.decode("utf-8"))


def pick_asset(release, patterns):
    """First release file whose name matches one of the patterns, in order of preference."""
    for pattern in patterns:
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            # This PC runs 64-bit Intel/AMD Windows: never pick an ARM build.
            if re.search(pattern, name, re.I) and not re.search(r"arm64|aarch64", name, re.I):
                return asset
    return None


def download(url, name, expected_sha256=None, expected_size=None):
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    target = DOWNLOADS / name
    partial = target.with_name(target.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, open(partial, "wb") as out:
        total = int(response.headers.get("Content-Length") or expected_size or 0)
        done, shown = 0, -10
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            out.write(block)
            digest.update(block)
            done += len(block)
            if total:
                percent = int(done * 100 / total)
                if percent >= shown + 10:
                    shown = percent - percent % 10
                    say(f"    {percent:3d}%  ({done / 1048576:.1f} of {total / 1048576:.1f} MB)")
    if expected_size and done != expected_size:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"incomplete download ({done} of {expected_size} bytes)")
    if expected_sha256 and digest.hexdigest() != expected_sha256.lower():
        partial.unlink(missing_ok=True)
        raise RuntimeError("the download does not match the fingerprint GitHub publishes for it")
    partial.replace(target)
    return target


def asset_digest(asset):
    value = asset.get("digest") or ""
    return value.split(":", 1)[1] if value.startswith("sha256:") else None


def signature(path):
    """(status, signer subject) of a file's Authenticode signature, via Windows PowerShell."""
    if not WINDOWS:
        return "NotWindows", ""
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $env:JC_FILE; "
              "Write-Output $s.Status; Write-Output $s.SignerCertificate.Subject")
    try:
        output = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=60,
                                env=dict(os.environ, JC_FILE=str(path)),
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return "Unknown", ""
    return (output[0].strip() if output else "Unknown"), (output[1].strip() if len(output) > 1 else "")


def run_installer(path, arguments=""):
    """Start an installer through the Windows shell (so its own administrator prompt appears)
    and wait for it. Returns its exit code, or None when the user declined the prompt."""
    if not WINDOWS:
        raise RuntimeError("installers run on Windows only")
    import ctypes
    from ctypes import wintypes as W

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [("cbSize", W.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", W.HWND), ("lpVerb", W.LPCWSTR),
                    ("lpFile", W.LPCWSTR), ("lpParameters", W.LPCWSTR), ("lpDirectory", W.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", W.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", W.LPCWSTR), ("hkeyClass", W.HKEY), ("dwHotKey", W.DWORD),
                    ("hIconOrMonitor", W.HANDLE), ("hProcess", W.HANDLE)]
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "open"
    info.lpFile = str(path)
    info.lpParameters = arguments or None
    info.lpDirectory = str(Path(path).parent)
    info.nShow = 1
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = W.BOOL
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        if ctypes.get_last_error() == 1223:  # ERROR_CANCELLED: the administrator prompt was declined
            return None
        raise ctypes.WinError(ctypes.get_last_error())
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
    kernel32.CloseHandle.argtypes = [W.HANDLE]
    if not info.hProcess:
        return 0
    kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
    code = W.DWORD(0)
    kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(info.hProcess)
    return code.value


def open_page(url):
    if WINDOWS:
        os.startfile(url)  # noqa: S606 - opens the user's browser on an https page


# --------------------------------------------------------------------------- detection

def registry_value(root_name, path, name=""):
    if not WINDOWS:
        return None
    import winreg
    root = getattr(winreg, root_name)
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_READ | view) as key:
                return winreg.QueryValueEx(key, name)[0]
        except OSError:
            continue
    return None


def obs_folder():
    candidates = []
    for root in ("HKEY_LOCAL_MACHINE", "HKEY_CURRENT_USER"):
        value = registry_value(root, r"SOFTWARE\OBS Studio")
        if value:
            candidates.append(Path(value))
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), r"C:\Program Files"):
        if base:
            candidates.append(Path(base) / "obs-studio")
    for folder in candidates:
        if (folder / "bin" / "64bit" / "obs64.exe").exists():
            return folder
    return None


def spout_plugin_installed(obs):
    places = []
    if obs:
        places.append(obs / "obs-plugins" / "64bit" / "win-spout.dll")
    program_data = os.environ.get("ProgramData")
    if program_data:
        places.append(Path(program_data) / "obs-studio" / "plugins" / "win-spout" / "bin" / "64bit" / "win-spout.dll")
    return next((p for p in places if p.exists()), None)


def nvidia_gpu():
    """(name, architecture label) of the first NVIDIA GPU, or None."""
    if not WINDOWS:
        return None
    smi = None
    for candidate in (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe",
                      Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"):
        if candidate.exists():
            smi = candidate
            break
    if smi is None:
        return None
    name, capability = "", None
    for query in ("name,compute_cap", "name"):
        try:
            line = subprocess.run([str(smi), f"--query-gpu={query}", "--format=csv,noheader"], capture_output=True,
                                  text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                  ).stdout.strip().splitlines()
        except (OSError, subprocess.SubprocessError):
            continue
        if line and "not a valid field" not in line[0].lower() and "error" not in line[0].lower():
            parts = [p.strip() for p in line[0].split(",")]
            name = parts[0]
            if len(parts) > 1 and re.match(r"^\d+\.\d+$", parts[1]):
                major, minor = map(int, parts[1].split("."))
                capability = (major, minor)
            break
    return (name, architecture(name, capability)) if name else None


def architecture(name, capability=None):
    if capability:
        if capability[0] >= 10:
            return "Blackwell"
        if capability >= (8, 9):
            return "Ada"
        if capability >= (8, 0):
            return "Ampere"
        if capability >= (7, 5):
            return "Turing"
        return None
    upper = name.upper()
    if re.search(r"RTX\s*50\d\d|RTX PRO \d+ BLACKWELL", upper):
        return "Blackwell"
    if re.search(r"RTX\s*40\d\d|RTX \d000 ADA|L4\b|L40", upper):
        return "Ada"
    if re.search(r"RTX\s*30\d\d|RTX A\d|A10|A40|A100", upper):
        return "Ampere"
    if re.search(r"RTX\s*20\d\d|TITAN RTX|QUADRO RTX|T4\b|GTX\s*16\d\d", upper):
        return "Turing"
    return None


def nvidia_ar_installed():
    places = []
    if os.environ.get("NV_AR_SDK_PATH"):
        places.append(Path(os.environ["NV_AR_SDK_PATH"]))
    places.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation" / "NVIDIA AR SDK")
    return next((p for p in places if (p / "nvARPose.dll").exists()), None)


def nvidia_installer_links(html, label):
    """AR SDK installer links for one GPU generation on NVIDIA's Broadcast SDK resources page."""
    links = re.findall(r"https?://[^\"'\s<>]+?\.exe", html)
    wanted = [u for u in links if re.search(r"ar[_-]?sdk", u, re.I) and re.search(label, u, re.I)]
    # Newest first, by the version number in the path when there is one.
    def version(url):
        found = re.search(r"/v?(\d+(?:\.\d+)+)/", url)
        return tuple(int(x) for x in found.group(1).split(".")) if found else ()
    return sorted(dict.fromkeys(wanted), key=version, reverse=True)


# --------------------------------------------------------------------------- components

def install_github(repo, patterns, title, check_only):
    say(f"  Looking up the latest {title} release on GitHub...")
    release = latest_release(repo)
    asset = pick_asset(release, patterns)
    if asset is None:
        say(f"  No Windows installer was attached to {title} {release.get('tag_name', '')}.")
        open_page(f"https://github.com/{repo}/releases/latest")
        return False
    say(f"  {title} {release.get('tag_name', '')}: {asset['name']} ({asset.get('size', 0) / 1048576:.1f} MB)")
    if check_only:
        return True
    digest = asset_digest(asset)
    path = download(asset["browser_download_url"], asset["name"], digest, asset.get("size"))
    say("  Verified against GitHub's SHA-256 fingerprint." if digest else
        "  GitHub published no fingerprint for this file; its size matches the release.")
    say(f"  Starting the {title} installer. Approve the Windows prompt and follow its steps.")
    code = run_installer(path)
    if code is None:
        say(f"  The administrator prompt was declined. {title} was not installed.")
        return False
    say(f"  {title} installer finished" + (f" (exit code {code})." if code else "."))
    return code == 0


def do_obs(check_only):
    say("OBS Studio")
    folder = obs_folder()
    if folder:
        say(f"  Already installed: {folder}")
        return True
    say("  Not found.")
    return install_github(OBS_REPO, [r"Windows-x64-Installer\.exe$", r"Full-Installer-x64\.exe$",
                                     r"Windows-Installer\.exe$", r"Installer.*\.exe$"], "OBS Studio", check_only)


def do_spout(check_only):
    say("OBS Spout2 plugin")
    obs = obs_folder()
    found = spout_plugin_installed(obs)
    if found:
        say(f"  Already installed: {found}")
        return True
    if obs is None:
        say("  OBS Studio is not installed, so the plugin has nowhere to go. Install OBS first, then run")
        say("  \"JointCam Studio add-ons\" from the Start menu.")
        return False
    say(f"  Not installed in {obs}.")
    return install_github(SPOUT_REPO, [r"installer.*\.exe$", r"\.exe$"], "OBS Spout2 plugin", check_only)


def do_nvidia(check_only):
    say("NVIDIA AR SDK runtime (RTX face tracking)")
    found = nvidia_ar_installed()
    if found:
        say(f"  Already installed: {found}")
        return True
    gpu = nvidia_gpu()
    if gpu is None:
        say("  No NVIDIA GPU found. JointCam uses its built-in CPU face tracker instead.")
        return True
    name, label = gpu
    if label is None:
        say(f"  {name} has no RTX tensor cores. JointCam uses its built-in CPU face tracker instead.")
        return True
    say(f"  {name}: needs the {label} build.")
    try:
        links = nvidia_installer_links(fetch(NVIDIA_PAGE).decode("utf-8", "replace"), label)
    except Exception as exc:  # noqa: BLE001 - any network failure ends in the same manual step
        say(f"  Could not read NVIDIA's download page ({exc}).")
        links = []
    if not links:
        say(f"  Opening NVIDIA's Broadcast SDK page. Download \"AR SDK\" for {label} and run it.")
        if not check_only:
            open_page(NVIDIA_PAGE)
        return False
    url = links[0]
    say(f"  Found {url.rsplit('/', 1)[-1]}")
    if check_only:
        return True
    path = download(url, url.rsplit("/", 1)[-1])
    status, signer = signature(path)
    if status != "Valid" or "NVIDIA Corporation" not in signer:
        path.unlink(missing_ok=True)
        say(f"  The file is not validly signed by NVIDIA (status {status}). It was deleted and not run.")
        open_page(NVIDIA_PAGE)
        return False
    say("  Signature verified: NVIDIA Corporation.")
    say("  Starting NVIDIA's installer. Approve the Windows prompt and follow its steps.")
    code = run_installer(path)
    if code is None:
        say("  The administrator prompt was declined. The NVIDIA AR SDK was not installed.")
        return False
    say("  NVIDIA AR SDK installer finished" + (f" (exit code {code})." if code else "."))
    return code == 0


def main():
    parser = argparse.ArgumentParser(description="Install the components JointCam Studio uses.")
    parser.add_argument("--obs", action="store_true", help="OBS Studio, if it is not installed")
    parser.add_argument("--spout", action="store_true", help="the OBS Spout2 plugin")
    parser.add_argument("--nvidia", action="store_true", help="the NVIDIA AR SDK runtime for this GPU")
    parser.add_argument("--all", action="store_true", help="everything above")
    parser.add_argument("--check", action="store_true", help="report what is installed; download nothing")
    parser.add_argument("--pause", action="store_true", help="wait for Enter before closing")
    args = parser.parse_args()
    steps = [(args.obs or args.all, do_obs), (args.spout or args.all, do_spout), (args.nvidia or args.all, do_nvidia)]
    if not any(on for on, _ in steps):
        steps = [(True, step) for _, step in steps]
    results = []
    for enabled, step in steps:
        if not enabled:
            continue
        try:
            results.append(step(args.check))
        except Exception as exc:  # noqa: BLE001 - report and continue with the next component
            say(f"  Could not complete this step: {exc}")
            results.append(False)
        say()
    if all(results):
        say("Add-ons: everything JointCam uses is in place." if not args.check else "Add-ons check complete.")
    else:
        say("Add-ons: some steps did not finish. JointCam Studio works without them; run \"JointCam Studio add-ons\""
            " from the Start menu to try again.")
    shutil.rmtree(DOWNLOADS, ignore_errors=True)
    if args.pause:
        try:
            input("Press Enter to close.")
        except EOFError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Windowed entry point. Keep native startup diagnostics available after failures."""
import os
from pathlib import Path
import sys
import traceback

def run():
    root=Path(__file__).resolve().parent
    os.chdir(root)
    local=Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"JointCam Studio"
    local.mkdir(exist_ok=True,parents=True)
    log=local/"startup.log"
    with log.open("w",encoding="utf-8",buffering=1) as stream:
        sys.stdout=sys.stderr=stream
        # A crash inside a native library (graphics driver, camera driver) bypasses Python's
        # exception handling. Record its stack in the log instead of closing silently.
        import faulthandler
        faulthandler.enable(stream,all_threads=True)
        print(f"JointCam Studio starting · Python {sys.version.split()[0]} · {sys.executable}")
        print("A 'Windows fatal exception' entry matters only if JointCam closed unexpectedly. "
              "Drivers can raise and handle these internally.")
        try:
            qt=root/"runtime"/"Lib"/"site-packages"/"PySide6"
            dll_handle=os.add_dll_directory(str(qt))
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"]=str(qt/"plugins"/"platforms")
            # MediaPipe imports matplotlib. Keep it on its headless backend so it never
            # probes the Qt bindings JointCam already loaded.
            os.environ["MPLBACKEND"]="Agg"
            import perf
            perf.configure_libraries()
            perf.tune_process()
            try:
                from studio import launch
                return launch()
            finally:
                perf.shutdown()
        except Exception:
            traceback.print_exc()
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,"JointCam could not start. Run the JointCam Studio setup again to repair the installation.\n\n"+traceback.format_exc().splitlines()[-1]+"\n\nDetails: "+str(log),"JointCam Studio",0x10)
            return 1

if __name__=="__main__":
    sys.exit(run())

import ctypes
import logging
import sys
from pathlib import Path

_INSTANCE = None

_SOURCE = Path(__file__).resolve().parent
if not getattr(sys, "frozen", False):
    _REPO = _SOURCE.parents[1]
    sys.path[:0] = [str(_REPO / "packages" / "core"), str(_SOURCE)]

from openctrl.deskapp import notify, run_app
from openctrl.paths import data_directory
from openctrl.logutil import configure_logging
from openctrl_windows.desktop import Desktop
from openctrl_windows.startup import apply_login


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("This OpenCtrl app runs on Windows, in the desktop session you want to control.")
    _app = data_directory(_SOURCE)
    configure_logging(_app)
    if not _single_instance():
        logging.error("OpenCtrl is already running in this Windows session.")
        notify("OpenCtrl", "OpenCtrl is already running.")
        raise SystemExit(1)
    run_app(_app, Desktop, apply_login)


def _single_instance() -> bool:
    global _INSTANCE
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\OpenCtrl")
    error = ctypes.get_last_error()
    _INSTANCE = handle
    return bool(handle) and error != 183


if __name__ == "__main__":
    main()

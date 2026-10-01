import ctypes
import logging
import sys
from pathlib import Path

_INSTANCE = None

_APP = Path(__file__).resolve().parent
_REPO = _APP.parents[1]
sys.path[:0] = [str(_REPO / "packages" / "core"), str(_APP)]

from openctrl.bot import serve
from openctrl.config import load_settings
from openctrl.llm import OpenRouter
from openctrl.logutil import configure_logging
from openctrl_windows.desktop import Desktop
from openctrl_windows.startup import ensure_login_shortcut
import asyncio


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("This OpenCtrl app runs on Windows, in the desktop session you want to control.")
    settings = load_settings(_APP)
    configure_logging(settings.root)
    if not _single_instance():
        logging.error("OpenCtrl is already running in this Windows session.")
        raise SystemExit(1)
    if not settings.allowed_user_ids:
        logging.warning("TELEGRAM_ALLOWED_USER_IDS is empty. /start will show your id, and work stays blocked.")
    if settings.start_with_windows:
        logging.info(ensure_login_shortcut(settings.root))
    desktop = Desktop()
    llm = OpenRouter(settings)
    try:
        asyncio.run(serve(settings, desktop, llm))
    except KeyboardInterrupt:
        pass


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

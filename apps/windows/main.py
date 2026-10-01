import ctypes
import logging
import sys
from pathlib import Path

_INSTANCE = None

from openctrl.config import load_settings
from openctrl.desktop import Desktop
from openctrl.llm import OpenRouter


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("OpenCtrl runs on Windows, in the desktop session you want to control.")
    settings = load_settings()
    log_dir = Path(settings.root) / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "openctrl.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    if not _single_instance():
        logging.error("OpenCtrl is already running in this Windows session.")
        raise SystemExit(1)
    if not settings.allowed_user_ids:
        logging.warning("TELEGRAM_ALLOWED_USER_IDS is empty. /start will show your id, and work stays blocked.")
    if settings.start_with_windows:
        from openctrl.startup import ensure_login_shortcut

        logging.info(ensure_login_shortcut(settings.root))
    from openctrl.bot import serve
    import asyncio

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

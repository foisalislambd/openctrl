import asyncio
import logging
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent
_REPO = _APP.parents[1]
sys.path[:0] = [str(_REPO / "packages" / "core"), str(_APP)]

from openctrl.bot import serve
from openctrl.config import load_settings
from openctrl.instance import hold
from openctrl.llm import OpenRouter
from openctrl.logutil import configure_logging
from openctrl_linux.desktop import Desktop
from openctrl_linux.startup import ensure_login


def main() -> None:
    if not sys.platform.startswith("linux"):
        raise SystemExit("This OpenCtrl app runs on Linux, in the desktop session you want to control.")
    settings = load_settings(_APP)
    configure_logging(settings.root)
    if not hold(settings.root):
        logging.error("OpenCtrl is already running in this session.")
        raise SystemExit(1)
    if not settings.allowed_user_ids:
        logging.warning("TELEGRAM_ALLOWED_USER_IDS is empty. /start will show your id, and work stays blocked.")
    if settings.start_with_windows:
        logging.info(ensure_login(settings.root))
    desktop = Desktop()
    llm = OpenRouter(settings)
    try:
        asyncio.run(serve(settings, desktop, llm))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

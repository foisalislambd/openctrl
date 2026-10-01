import logging
import sys
from pathlib import Path

from openagent.config import load_settings
from openagent.desktop import Desktop
from openagent.llm import OpenRouter


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("OpenAgent runs on Windows, in the desktop session you want to control.")
    settings = load_settings()
    log_dir = Path(settings.root) / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "openagent.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    if not settings.allowed_user_ids:
        logging.warning("TELEGRAM_ALLOWED_USER_IDS is empty. /start will show your id, and work stays blocked.")
    from openagent.bot import serve
    import asyncio

    desktop = Desktop()
    llm = OpenRouter(settings)
    try:
        asyncio.run(serve(settings, desktop, llm))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

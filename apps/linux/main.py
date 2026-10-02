import logging
import sys
from pathlib import Path

_SOURCE = Path(__file__).resolve().parent
if not getattr(sys, "frozen", False):
    _REPO = _SOURCE.parents[1]
    sys.path[:0] = [str(_REPO / "packages" / "core"), str(_SOURCE)]

from openctrl.deskapp import notify, run_app
from openctrl.instance import hold
from openctrl.paths import data_directory
from openctrl.logutil import configure_logging
from openctrl_linux.desktop import Desktop
from openctrl_linux.startup import apply_login


def main() -> None:
    if not sys.platform.startswith("linux"):
        raise SystemExit("This OpenCtrl app runs on Linux, in the desktop session you want to control.")
    _app = data_directory(_SOURCE)
    configure_logging(_app)
    if not hold(_app):
        logging.error("OpenCtrl is already running in this session.")
        notify("OpenCtrl", "OpenCtrl is already running.")
        raise SystemExit(1)
    run_app(_app, Desktop, apply_login)


if __name__ == "__main__":
    main()

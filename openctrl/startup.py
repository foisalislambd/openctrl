"""Start OpenCtrl when this Windows user logs on. It stays a normal desktop program."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ensure_login_shortcut(root: Path) -> str:
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return "APPDATA is missing, so the login shortcut was not created."
    startup = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup.mkdir(parents=True, exist_ok=True)
    old = startup / "OpenAgent.lnk"
    if old.is_file():
        old.unlink()
    link = startup / "OpenCtrl.lnk"
    bat = (root / "run.bat").resolve()
    if not bat.is_file():
        return f"run.bat was not found at {bat}."
    script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$sc = $shell.CreateShortcut('{_ps(link)}'); "
        f"$sc.TargetPath = '{_ps(bat)}'; "
        f"$sc.WorkingDirectory = '{_ps(root.resolve())}'; "
        "$sc.WindowStyle = 7; "
        "$sc.Description = 'OpenCtrl Telegram desktop agent'; "
        "$sc.Save()"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        creationflags=_CREATE_NO_WINDOW,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return f"Could not create the login shortcut: {detail[:300]}"
    return f"OpenCtrl will start at login via {link}."


def _ps(path: Path) -> str:
    return str(path).replace("'", "''")

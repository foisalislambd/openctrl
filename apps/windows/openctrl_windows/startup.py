"""Start OpenCtrl when this Windows user logs on. It stays a normal desktop program."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from openctrl.paths import launch_command

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def apply_login(root: Path, enabled: bool) -> str:
    startup = _startup_dir()
    if startup is None:
        return "APPDATA is missing, so the login shortcut was not changed."
    old = startup / "OpenAgent.lnk"
    if old.is_file():
        old.unlink()
    link = startup / "OpenCtrl.lnk"
    if not enabled:
        if link.is_file():
            link.unlink()
        return "OpenCtrl will not start when you log in."
    return ensure_login_shortcut(root)


def ensure_login_shortcut(root: Path) -> str:
    startup = _startup_dir()
    if startup is None:
        return "APPDATA is missing, so the login shortcut was not created."
    startup.mkdir(parents=True, exist_ok=True)
    old = startup / "OpenAgent.lnk"
    if old.is_file():
        old.unlink()
    link = startup / "OpenCtrl.lnk"
    launch = _launch(root)
    if launch is None:
        return f"Could not find OpenCtrl.exe, pythonw.exe, or run.bat in {root}."
    target, arguments, work = launch
    argument_line = f"$sc.Arguments = '{arguments}'; " if arguments else ""
    script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$sc = $shell.CreateShortcut('{_ps(link)}'); "
        f"$sc.TargetPath = '{_ps(target)}'; "
        f"{argument_line}"
        f"$sc.WorkingDirectory = '{_ps(work)}'; "
        "$sc.WindowStyle = 1; "
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


def _startup_dir() -> Path | None:
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _launch(root: Path) -> tuple[Path, str, Path] | None:
    found = launch_command(root)
    if found is None:
        return None
    command, work = found
    return Path(command[0]), " ".join(command[1:]), work


def _ps(path: Path) -> str:
    return str(path).replace("'", "''")

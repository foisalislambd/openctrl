"""Data folder for a source checkout, and the program login should start."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def data_directory(source_dir: Path) -> Path:
    if not getattr(sys, "frozen", False):
        return source_dir
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / "OpenCtrl"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "OpenCtrl"
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / "openctrl"
    path.mkdir(parents=True, exist_ok=True)
    return path


def launch_command(source_dir: Path) -> tuple[list[str], Path] | None:
    """Argv and working directory for the login item."""
    if getattr(sys, "frozen", False):
        program = Path(sys.executable).resolve()
        return [str(program)], program.parent
    source_dir = source_dir.resolve()
    if sys.platform == "win32":
        pythonw = source_dir / ".venv" / "Scripts" / "pythonw.exe"
        if pythonw.is_file():
            return [str(pythonw), "main.py"], source_dir
        bat = source_dir / "run.bat"
        if bat.is_file():
            return [str(bat)], source_dir
        return None
    script = source_dir / "run.sh"
    if script.is_file():
        return ["/bin/sh", str(script)], source_dir
    return None

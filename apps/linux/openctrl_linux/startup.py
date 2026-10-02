"""Open OpenCtrl when this Linux desktop session starts."""

from __future__ import annotations

import shlex
from pathlib import Path

from openctrl.paths import launch_command


def apply_login(root: Path, enabled: bool) -> str:
    entry = Path.home() / ".config" / "autostart" / "openctrl.desktop"
    if not enabled:
        if entry.is_file():
            entry.unlink()
        return "OpenCtrl will not start when you log in."
    return ensure_login(root)


def ensure_login(root: Path) -> str:
    autostart = Path.home() / ".config" / "autostart"
    autostart.mkdir(parents=True, exist_ok=True)
    found = launch_command(root)
    if found is None:
        return "Could not find the OpenCtrl program to start at login."
    command, work = found
    entry = autostart / "openctrl.desktop"
    entry.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=OpenCtrl",
                "Comment=Telegram desktop agent",
                f"Exec={' '.join(shlex.quote(part) for part in command)}",
                f"Path={work}",
                "X-GNOME-Autostart-enabled=true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return f"OpenCtrl will start at login via {entry}."

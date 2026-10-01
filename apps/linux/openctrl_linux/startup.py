"""Open OpenCtrl when this Linux desktop session starts."""

from __future__ import annotations

from pathlib import Path


def ensure_login(root: Path) -> str:
    autostart = Path.home() / ".config" / "autostart"
    autostart.mkdir(parents=True, exist_ok=True)
    script = (root / "run.sh").resolve()
    if not script.is_file():
        return f"run.sh was not found at {script}."
    entry = autostart / "openctrl.desktop"
    entry.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=OpenCtrl",
                "Comment=Telegram desktop agent",
                f"Exec=/bin/sh {script}",
                f"Path={root.resolve()}",
                "X-GNOME-Autostart-enabled=true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return f"OpenCtrl will start at login via {entry}."

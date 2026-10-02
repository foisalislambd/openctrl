"""Open OpenCtrl when this Mac user logs in."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from openctrl.paths import launch_command


def apply_login(root: Path, enabled: bool) -> str:
    plist = Path.home() / "Library" / "LaunchAgents" / "com.openctrl.desktop.plist"
    if not enabled:
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(plist)], capture_output=True, text=True)
        if plist.is_file():
            plist.unlink()
        return "OpenCtrl will not start when you log in."
    return ensure_login(root)


def ensure_login(root: Path) -> str:
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / "com.openctrl.desktop.plist"
    found = launch_command(root)
    if found is None:
        return "Could not find the OpenCtrl program to start at login."
    command, work = found
    arguments = "\n".join(f"    <string>{_xml(part)}</string>" for part in command)
    uid = os.getuid()
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.openctrl.desktop</string>
  <key>ProgramArguments</key>
  <array>
{arguments}
  </array>
  <key>RunAtLoad</key><true/>
  <key>WorkingDirectory</key><string>{_xml(str(work))}</string>
</dict>
</plist>
"""
    plist.write_text(body, encoding="utf-8")
    domain = f"gui/{uid}"
    subprocess.run(["launchctl", "bootout", domain, str(plist)], capture_output=True, text=True)
    completed = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return f"Could not install the login item: {detail[:300]}"
    return f"OpenCtrl will start at login via {plist}."


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;")

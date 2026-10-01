"""Open OpenCtrl when this Mac user logs in."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def ensure_login(root: Path) -> str:
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / "com.openctrl.desktop.plist"
    script = (root / "run.sh").resolve()
    if not script.is_file():
        return f"run.sh was not found at {script}."
    uid = os.getuid()
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.openctrl.desktop</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>{script}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>WorkingDirectory</key><string>{root.resolve()}</string>
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

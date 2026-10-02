"""Incoming Telegram files land in the inbox. Outgoing files must not be secrets."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_BLOCKED = {".env", "credentials.json", "id_rsa", "id_ed25519", "openctrl.db"}


def save_upload(inbox: Path, filename: str, data: bytes) -> Path:
    inbox.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    clean = _SAFE.sub("_", os.path.basename(filename)).strip("._") or "file"
    if len(clean) > 80:
        clean = clean[:80]
    path = inbox / f"{stamp}-{clean}"
    counter = 1
    while path.exists():
        path = inbox / f"{stamp}-{counter}-{clean}"
        counter += 1
    path.write_bytes(data)
    return path


def resolve_send_path(raw: str, inbox: Path) -> tuple[str | None, str | None]:
    text = os.path.expandvars(os.path.expanduser(raw.strip().strip('"').strip("'")))
    if not text:
        return None, "send_file needs a path."
    found = _find(text, inbox)
    if not found:
        return None, f"File not found: {text}"
    if _is_secret(os.path.basename(found)):
        return None, "That file looks like a secret. It will not be sent."
    return found, None


def _is_secret(name: str) -> bool:
    lowered = name.lower()
    if lowered in _BLOCKED or lowered.startswith("openctrl.db") or lowered.endswith((".pem", ".key")):
        return True
    if lowered == ".env.example":
        return False
    return lowered == ".env" or lowered.startswith(".env.")


def _find(text: str, inbox: Path) -> str | None:
    if os.path.isfile(text):
        return os.path.abspath(text)
    home = os.path.expanduser("~")
    roots = [
        inbox,
        os.path.join(home, "Desktop"),
        os.path.join(home, "OneDrive", "Desktop"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Downloads"),
        home,
    ]
    if not os.path.isabs(text):
        for root in roots:
            candidate = os.path.join(root, text)
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)
    return None

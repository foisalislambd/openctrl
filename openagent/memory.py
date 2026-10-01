"""Short notes that survive a new task. Not a transcript of the chat."""

from __future__ import annotations

import json
import re
from pathlib import Path

_KEY = re.compile(r"^[a-z0-9_]{1,40}$")
_MAX_KEYS = 40
_MAX_VALUE = 2000


class Memory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._notes: dict[str, str] = {}
        self._load()

    def snapshot(self, limit: int = 1800) -> str:
        if not self._notes:
            return ""
        lines = [f"{key}: {value}" for key, value in sorted(self._notes.items())]
        text = "\n".join(lines)
        if len(text) <= limit:
            return text
        return text[: limit - 1] + "…"

    def read(self, key: str) -> str:
        name = key.strip().lower()
        if not name:
            return self.snapshot() or "No notes saved."
        if name not in self._notes:
            return f"No note named {name}."
        return f"{name}: {self._notes[name]}"

    def write(self, key: str, value: str) -> str:
        name = key.strip().lower().replace(" ", "_").replace("-", "_")
        if not _KEY.match(name):
            return "Note names are lowercase letters, numbers, and underscores, up to 40 characters."
        text = " ".join(value.split())
        if not text:
            self._notes.pop(name, None)
            self._save()
            return f"Forgot {name}."
        if len(text) > _MAX_VALUE:
            text = text[:_MAX_VALUE]
        if name not in self._notes and len(self._notes) >= _MAX_KEYS:
            return f"Already storing {_MAX_KEYS} notes. Clear one by writing an empty value."
        self._notes[name] = text
        self._save()
        return f"Remembered {name}."

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        notes = raw.get("notes") if isinstance(raw, dict) else None
        if not isinstance(notes, dict):
            return
        for key, value in notes.items():
            if isinstance(key, str) and isinstance(value, str) and _KEY.match(key):
                self._notes[key] = value[:_MAX_VALUE]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"notes": self._notes}, ensure_ascii=False, indent=2)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(self.path)

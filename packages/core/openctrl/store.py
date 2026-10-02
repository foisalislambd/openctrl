"""Local settings database. Tokens stay in this file, not in the environment."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_ENV_KEYS = {
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "TELEGRAM_ALLOWED_USER_IDS": "telegram_allowed_user_ids",
    "OPENROUTER_API_KEY": "openrouter_api_key",
    "OPENROUTER_MODEL": "openrouter_model",
    "OPENROUTER_PROVIDER_SORT": "openrouter_provider_sort",
    "OPENROUTER_TRANSCRIBE_MODEL": "openrouter_transcribe_model",
    "MAX_STEPS": "max_steps",
    "MAX_OUTPUT_TOKENS": "max_output_tokens",
    "MAX_TASK_COST": "max_task_cost",
    "START_WITH_WINDOWS": "start_with_windows",
}


class SettingsStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.path = self.root / "data" / "openctrl.db"

    def read(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        conn = self._connect()
        try:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        finally:
            conn.close()
        return {key: value for key, value in rows}

    def write(self, values: dict[str, str]) -> None:
        conn = self._connect()
        try:
            for key, value in values.items():
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
            conn.commit()
        finally:
            conn.close()

    def import_env_once(self) -> bool:
        current = self.read()
        if current.get("telegram_bot_token") or current.get("openrouter_api_key"):
            return False
        env_path = self.root / ".env"
        if not env_path.is_file():
            return False
        mapped = _env_file(env_path)
        if not mapped.get("telegram_bot_token") and not mapped.get("openrouter_api_key"):
            return False
        self.write(mapped)
        self.write({"imported_from_env": "1"})
        return True

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.commit()
        if os.name != "nt":
            os.chmod(self.path, 0o600)
        return conn


def _env_file(path: Path) -> dict[str, str]:
    try:
        from dotenv import dotenv_values
    except ImportError:
        return _parse_env(path)
    raw = dotenv_values(path)
    mapped: dict[str, str] = {}
    for env_name, key in _ENV_KEYS.items():
        value = (raw.get(env_name) or "").strip()
        if value:
            mapped[key] = value
    return mapped


def _parse_env(path: Path) -> dict[str, str]:
    mapped: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return mapped
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        name, value = text.split("=", 1)
        key = _ENV_KEYS.get(name.strip())
        value = value.strip().strip('"').strip("'")
        if key and value:
            mapped[key] = value
    return mapped

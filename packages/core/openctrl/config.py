from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    allowed_user_ids: frozenset[int]
    openrouter_api_key: str
    model: str
    provider_sort: str
    max_steps: int
    max_output_tokens: int
    max_task_cost: float
    transcribe_model: str
    start_with_windows: bool
    root: Path


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not token or not api_key:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN and OPENROUTER_API_KEY are required.\n"
            "Copy .env.example to .env and fill them in."
        )
    allowed: set[int] = set()
    raw_ids = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "")
    for part in raw_ids.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise SystemExit(f"TELEGRAM_ALLOWED_USER_IDS has a non-numeric id: {part}")
        allowed.add(int(part))
    return Settings(
        telegram_token=token,
        allowed_user_ids=frozenset(allowed),
        openrouter_api_key=api_key,
        model=os.environ.get("OPENROUTER_MODEL", "openai/gpt-6-luna-pro").strip()
        or "openai/gpt-6-luna-pro",
        provider_sort=os.environ.get("OPENROUTER_PROVIDER_SORT", "exacto").strip(),
        max_steps=_int_env("MAX_STEPS", 30, low=5, high=80),
        max_output_tokens=_int_env("MAX_OUTPUT_TOKENS", 12000, low=1000, high=32000),
        max_task_cost=_float_env("MAX_TASK_COST", 0.50, low=0.0, high=50.0),
        transcribe_model=os.environ.get("OPENROUTER_TRANSCRIBE_MODEL", "openai/whisper-large-v3").strip()
        or "openai/whisper-large-v3",
        start_with_windows=_bool_env("START_WITH_WINDOWS", True),
        root=ROOT,
    )


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float, low: float, high: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(low, min(high, value))


def _int_env(name: str, default: int, low: int, high: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(low, min(high, value))

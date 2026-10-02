"""Settings loaded from the local SQLite database."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openctrl.store import SettingsStore

_DEFAULT_MODEL = "openai/gpt-6-luna-pro"
_DEFAULT_TRANSCRIBE = "openai/whisper-large-v3"


class SettingsError(ValueError):
    pass


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
    agent_autostart: bool
    root: Path

    @property
    def configured(self) -> bool:
        return bool(self.telegram_token and self.openrouter_api_key)


def read_settings(root: Path) -> Settings:
    root = root.resolve()
    store = SettingsStore(root)
    store.import_env_once()
    return settings_from_values(root, store.read())


def load_settings(root: Path) -> Settings:
    settings = read_settings(root)
    if not settings.configured:
        raise SystemExit(
            "OpenCtrl needs a Telegram bot token and an OpenRouter API key.\n"
            "Start the app and fill them in. They are saved in data/openctrl.db."
        )
    return settings


def save_settings(root: Path, values: dict[str, str]) -> Settings:
    root = root.resolve()
    settings = settings_from_values(root, values, strict_ids=True)
    if not settings.configured:
        raise SettingsError("A Telegram bot token and an OpenRouter API key are required.")
    SettingsStore(root).write(values_from_settings(settings))
    return read_settings(root)


def values_from_settings(settings: Settings) -> dict[str, str]:
    return {
        "telegram_bot_token": settings.telegram_token,
        "telegram_allowed_user_ids": ",".join(str(item) for item in sorted(settings.allowed_user_ids)),
        "openrouter_api_key": settings.openrouter_api_key,
        "openrouter_model": settings.model,
        "openrouter_provider_sort": settings.provider_sort,
        "openrouter_transcribe_model": settings.transcribe_model,
        "max_steps": str(settings.max_steps),
        "max_output_tokens": str(settings.max_output_tokens),
        "max_task_cost": f"{settings.max_task_cost:g}",
        "start_with_windows": "1" if settings.start_with_windows else "0",
        "agent_autostart": "1" if settings.agent_autostart else "0",
    }


def settings_from_values(root: Path, raw: dict[str, str], *, strict_ids: bool = False) -> Settings:
    if "openrouter_provider_sort" in raw:
        provider_sort = raw.get("openrouter_provider_sort", "").strip()
    else:
        provider_sort = "exacto"
    return Settings(
        telegram_token=raw.get("telegram_bot_token", "").strip(),
        allowed_user_ids=_parse_ids(raw.get("telegram_allowed_user_ids", ""), strict=strict_ids),
        openrouter_api_key=raw.get("openrouter_api_key", "").strip(),
        model=(raw.get("openrouter_model") or "").strip() or _DEFAULT_MODEL,
        provider_sort=provider_sort,
        max_steps=_int_value(raw, "max_steps", 30, 5, 80),
        max_output_tokens=_int_value(raw, "max_output_tokens", 12000, 1000, 32000),
        max_task_cost=_float_value(raw, "max_task_cost", 0.50, 0.0, 50.0),
        transcribe_model=(raw.get("openrouter_transcribe_model") or "").strip() or _DEFAULT_TRANSCRIBE,
        start_with_windows=_bool_value(raw, "start_with_windows", True),
        agent_autostart=_bool_value(raw, "agent_autostart", True),
        root=root.resolve(),
    )


def _parse_ids(text: str, *, strict: bool) -> frozenset[int]:
    allowed: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            if strict:
                raise SettingsError(f"Allowed Telegram ids must be numbers. This is not: {part}")
            continue
        allowed.add(int(part))
    return frozenset(allowed)


def _bool_value(raw: dict[str, str], key: str, default: bool) -> bool:
    text = raw.get(key, "").strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "on"}


def _float_value(raw: dict[str, str], key: str, default: float, low: float, high: float) -> float:
    text = raw.get(key, "").strip()
    if not text:
        return default
    try:
        value = float(text)
    except ValueError:
        return default
    return max(low, min(high, value))


def _int_value(raw: dict[str, str], key: str, default: int, low: int, high: int) -> int:
    text = raw.get(key, "").strip()
    if not text:
        return default
    try:
        value = int(text)
    except ValueError:
        return default
    return max(low, min(high, value))

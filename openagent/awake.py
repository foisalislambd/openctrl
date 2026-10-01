"""Keep the PC awake only while a task is running."""

from __future__ import annotations

import ctypes
import threading

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002
_lock = threading.Lock()
_held = 0


def push_awake() -> None:
    global _held
    with _lock:
        _held += 1
        if _held == 1:
            _state(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED)


def pop_awake() -> None:
    global _held
    with _lock:
        _held = max(0, _held - 1)
        if _held == 0:
            _state(_ES_CONTINUOUS)


def _state(flags: int) -> None:
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass

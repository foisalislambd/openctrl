"""One running copy per desktop session. Windows uses its own mutex."""

from __future__ import annotations

import sys
from pathlib import Path

_HELD = None


def hold(root: Path) -> bool:
    if sys.platform == "win32":
        raise RuntimeError("Windows keeps a named mutex in the Windows app.")
    import fcntl

    global _HELD
    root.mkdir(parents=True, exist_ok=True)
    handle = open(root / ".instance.lock", "a", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return False
    _HELD = handle
    return True

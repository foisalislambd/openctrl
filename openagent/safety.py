"""Confirm only commands that can wreck the machine. Ordinary work runs immediately."""

import re

_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bformat(?:\.com)?\s+[a-z]:", re.I), "formats a disk"),
    (re.compile(r"\bformat-volume\b", re.I), "formats a volume"),
    (re.compile(r"\bdiskpart\b", re.I), "opens diskpart"),
    (re.compile(r"\bclear-disk\b", re.I), "clears a disk"),
    (re.compile(r"\bcipher\s+/w\b", re.I), "wipes free space"),
    (re.compile(r"\bbcdedit\b", re.I), "edits boot configuration"),
    (re.compile(r"\b(shutdown|stop-computer|restart-computer)\b", re.I), "shuts down or restarts the PC"),
    (re.compile(r"\breg(\.exe)?\s+delete\b", re.I), "deletes registry keys"),
    (re.compile(r"\b(del|erase|rd|rmdir)\b[^\n]*/s\b", re.I), "bulk-deletes files"),
]

_RECURSE = re.compile(r"remove-item\b", re.I)
_RECURSE_FLAG = re.compile(r"-recurse\b|-r\b", re.I)
_BROAD_PATH = re.compile(
    r"\\windows|\\program files|\\programdata|[a-z]:\\?\s*$",
    re.I,
)


def danger_reason(command: str) -> str | None:
    text = command or ""
    for pattern, reason in _RULES:
        if pattern.search(text):
            return reason
    if _RECURSE.search(text) and _RECURSE_FLAG.search(text) and _BROAD_PATH.search(text):
        return "recursively deletes a system or drive-root path"
    return None

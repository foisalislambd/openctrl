"""Confirm only commands that can wreck the machine. Ordinary work runs immediately."""

import re
import sys

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


_UNIX: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(shutdown|reboot|poweroff|halt)\b", re.I), "shuts down or restarts the computer"),
    (re.compile(r"\bmkfs(\.\w+)?\b", re.I), "formats a filesystem"),
    (re.compile(r"\bdd\b[^\n]*\bof=/dev/", re.I), "writes over a disk"),
    (re.compile(r"\bdiskutil\b[^\n]*\berase", re.I), "erases a disk"),
    (re.compile(r"\bwipefs\b", re.I), "wipes filesystem signatures"),
    (re.compile(r"\bshred\b", re.I), "shreds a file"),
]

_RM = re.compile(r"\brm\b", re.I)
_RM_FORCE = re.compile(r"(?:^|\s)--recursive|(?:^|\s)-[a-z]*r[a-z]*", re.I)
_RM_BROAD = re.compile(
    r"(?:^|\s)(?:~/?|/\*?|/(?:usr|bin|etc|boot|System|Users|home|var|opt)(?:/\S*)?)(?=\s|$)",
    re.I,
)


def danger_reason(command: str, system: str | None = None) -> str | None:
    which = (system or sys.platform).lower()
    if which == "darwin" or which.startswith("linux"):
        return _unix(command or "")
    return _windows(command or "")


def _windows(text: str) -> str | None:
    for pattern, reason in _RULES:
        if pattern.search(text):
            return reason
    if _RECURSE.search(text) and _RECURSE_FLAG.search(text) and _BROAD_PATH.search(text):
        return "recursively deletes a system or drive-root path"
    return None


def _unix(text: str) -> str | None:
    for pattern, reason in _UNIX:
        if pattern.search(text):
            return reason
    if _RM.search(text) and _RM_FORCE.search(text) and _RM_BROAD.search(text):
        return "recursively deletes a system or home path"
    return None

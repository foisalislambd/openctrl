"""The release version lives in the VERSION file at the repository root."""

from __future__ import annotations

import re
import sys
from pathlib import Path

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


class VersionError(ValueError):
    pass


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.match(text.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def require_version(text: str) -> tuple[int, int, int]:
    parsed = parse_version(text)
    if parsed is None:
        raise VersionError(f"Version must be major.minor.patch, got {text.strip()!r}.")
    return parsed


def format_version(version: tuple[int, int, int]) -> str:
    return f"{version[0]}.{version[1]}.{version[2]}"


def is_newer(current: str, tags: list[str]) -> bool:
    """True when current is a valid version greater than every release tag."""
    this = require_version(current)
    released = [parsed for tag in tags if (parsed := parse_version(tag)) is not None]
    if not released:
        return True
    return this > max(released)


def changelog_notes(text: str, version: str) -> str:
    marker = f"## {format_version(require_version(version))}"
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == marker:
            start = index + 1
            break
    if start is None:
        return f"OpenCtrl {format_version(require_version(version))}"
    body: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        body.append(line)
    notes = "\n".join(body).strip()
    return notes or f"OpenCtrl {format_version(require_version(version))}"


def current_version() -> str:
    for path in _version_files():
        if not path.is_file():
            continue
        parsed = parse_version(path.read_text(encoding="utf-8"))
        if parsed is not None:
            return format_version(parsed)
    return "0.0.0"


def _version_files():
    if getattr(sys, "frozen", False):
        yield Path(sys.executable).resolve().parent / "VERSION"
        bundled = getattr(sys, "_MEIPASS", None)
        if bundled:
            yield Path(bundled) / "VERSION"
        return
    here = Path(__file__).resolve()
    for parent in here.parents:
        yield parent / "VERSION"

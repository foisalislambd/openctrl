"""Print the changelog section for the version in VERSION."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "packages" / "core"))

from openctrl.version import changelog_notes, format_version, require_version


def main() -> int:
    version = format_version(require_version((_ROOT / "VERSION").read_text(encoding="utf-8")))
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    print(changelog_notes(changelog, version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

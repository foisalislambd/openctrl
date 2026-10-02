"""Tell GitHub Actions whether VERSION should become a release."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "packages" / "core"))

from openctrl.version import VersionError, format_version, is_newer, require_version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version-file", type=Path, default=_ROOT / "VERSION")
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    try:
        current = require_version(args.version_file.read_text(encoding="utf-8"))
    except (OSError, VersionError) as exc:
        print(exc, file=sys.stderr)
        return 1
    completed = subprocess.run(
        ["gh", "release", "list", "--repo", args.repo, "--limit", "200", "--json", "tagName"],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        print(detail or "Could not list GitHub releases.", file=sys.stderr)
        return completed.returncode or 1
    tags = [item.get("tagName", "") for item in json.loads(completed.stdout or "[]")]
    version = format_version(current)
    release = is_newer(version, tags)
    print(f"version={version}")
    print(f"release={'true' if release else 'false'}")
    if release:
        print(f"OpenCtrl {version} is newer than the latest release.", file=sys.stderr)
    else:
        print(f"OpenCtrl {version} is not newer than the latest release. Skipping.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

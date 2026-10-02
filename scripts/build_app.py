"""Build the OpenCtrl app for the OS running this script."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if sys.platform == "win32":
        platform = "windows"
        package = "openctrl_windows"
    elif sys.platform == "darwin":
        platform = "macos"
        package = "openctrl_macos"
    elif sys.platform.startswith("linux"):
        platform = "linux"
        package = "openctrl_linux"
    else:
        print(f"Unsupported platform: {sys.platform}", file=sys.stderr)
        return 1

    entry = _ROOT / "apps" / platform / "main.py"
    version_file = _ROOT / "VERSION"
    if not entry.is_file() or not version_file.is_file():
        print("The app entry point or VERSION file is missing.", file=sys.stderr)
        return 1

    dist = _ROOT / "build" / "dist"
    work = _ROOT / "build" / "work"
    if dist.exists():
        shutil.rmtree(dist)
    if work.exists():
        shutil.rmtree(work)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "OpenCtrl",
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--specpath",
        str(_ROOT / "build"),
        "--paths",
        str(_ROOT / "packages" / "core"),
        "--paths",
        str(_ROOT / "apps" / platform),
        "--add-data",
        f"{version_file}{os.pathsep}.",
        "--collect-submodules",
        "openctrl",
        "--collect-submodules",
        package,
        "--collect-all",
        "aiogram",
        "--collect-all",
        "certifi",
        "--hidden-import",
        "dotenv",
        str(entry),
    ]
    if platform == "windows":
        command.extend(["--collect-all", "uiautomation", "--collect-all", "comtypes"])
    completed = subprocess.run(command)
    if completed.returncode != 0:
        return completed.returncode

    if platform == "macos":
        bundle = dist / "OpenCtrl.app"
        if not bundle.is_dir():
            print("PyInstaller did not produce OpenCtrl.app.", file=sys.stderr)
            return 1
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(bundle)], check=False)
        base = "OpenCtrl.app"
    else:
        folder = dist / "OpenCtrl"
        program = folder / ("OpenCtrl.exe" if platform == "windows" else "OpenCtrl")
        if not program.is_file():
            print(f"PyInstaller did not produce {program}.", file=sys.stderr)
            return 1
        shutil.copyfile(version_file, folder / "VERSION")
        base = "OpenCtrl"

    output = _ROOT / "dist" / f"OpenCtrl-{platform}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    archive = shutil.make_archive(str(output.with_suffix("")), "zip", root_dir=dist, base_dir=base)
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

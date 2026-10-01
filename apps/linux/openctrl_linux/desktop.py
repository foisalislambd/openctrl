"""Linux desktop. X11 uses xdotool and wmctrl. Wayland is reported when those cannot see the session."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from PIL import Image

from openctrl.commands import run_cancellable, run_text
from openctrl.screen import Shot, image_to_screen, to_jpeg


class Desktop:
    shell_name = "bash"

    def __init__(self) -> None:
        self._capture: dict | None = None
        self._held = 0
        self._inhibit: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def push_awake(self) -> None:
        with self._lock:
            self._held += 1
            if self._held == 1 and shutil.which("systemd-inhibit"):
                self._inhibit = subprocess.Popen(
                    [
                        "systemd-inhibit",
                        "--what=idle:sleep",
                        "--who=OpenCtrl",
                        "--why=task",
                        "sleep",
                        "infinity",
                    ]
                )

    def pop_awake(self) -> None:
        with self._lock:
            self._held = max(0, self._held - 1)
            if self._held == 0 and self._inhibit is not None:
                self._inhibit.terminate()
                self._inhibit = None

    def screen_locked(self) -> str | None:
        session = os.environ.get("XDG_SESSION_ID", "")
        if not session:
            return None
        code, text = run_text(["loginctl", "show-session", session, "-p", "LockedHint"], timeout=8)
        if code == 0 and "yes" in text.lower():
            return "The desktop is locked. Unlock it, then send the task again."
        return None

    def run_shell(self, command: str, cancel: threading.Event, timeout: float, cwd: str | None) -> str:
        return run_cancellable(["/bin/bash", "-lc", command], cancel, timeout, cwd)

    def list_windows(self) -> str:
        missing = _need("wmctrl")
        if missing:
            return missing
        code, text = run_text(["wmctrl", "-lx"])
        return text or "No titled windows."

    def foreground(self) -> str:
        missing = _need("xdotool")
        if missing:
            return missing
        code, wid = run_text(["xdotool", "getactivewindow"])
        if code != 0:
            return _session_hint(wid)
        _, name = run_text(["xdotool", "getwindowname", wid.strip()])
        _, pid = run_text(["xdotool", "getwindowpid", wid.strip()])
        return f"{name} pid {pid}".strip()

    def focus_window(self, title: str) -> str:
        if not title.strip():
            return "focus_window needs a title."
        missing = _need("xdotool")
        if missing:
            return missing
        code, text = run_text(["xdotool", "search", "--name", title, "windowactivate"])
        if code != 0:
            return _session_hint(text) or f"No window title contains {title}."
        return f"Focused a window matching {title}."

    def ui_tree(self, title: str | None, max_depth: int, max_nodes: int) -> str:
        windows = self.list_windows()
        return (
            windows
            + "\nThe accessibility tree is not available from this session. "
            "Use screenshot, then click with coordinate_space image."
        )

    def click_control(self, name: str, window: str | None, control_type: str | None) -> str:
        return (
            f"Named click for {name!r} needs an accessibility tree, which this Linux session does not expose. "
            "Use screenshot and click."
        )

    def type_text(self, text: str, window: str | None, control_name: str | None, clear: bool) -> str:
        if window:
            focused = self.focus_window(window)
            if focused.startswith("No window") or focused.startswith("xdotool"):
                return focused
        if clear:
            self.press_keys("ctrl+a")
        return _paste(text)

    def press_keys(self, keys: str) -> str:
        missing = _need("xdotool")
        if missing:
            return missing
        if _blocked(keys):
            return "That chord was not sent."
        sent = []
        for chunk in [part.strip() for part in keys.split(",") if part.strip()]:
            chord = _xdo(chunk)
            code, text = run_text(["xdotool", "key", "--clearmodifiers", chord])
            if code != 0:
                return _session_hint(text) or f"Could not press {chord}."
            sent.append(chord)
        return "Pressed " + ", ".join(sent) + "."

    def launch(self, target: str, args: str) -> str:
        name = target.strip()
        extra = args.strip()
        if not name:
            return "launch needs a target."
        if name.lower() == "cursor":
            return _open_cursor(extra)
        if name.startswith("http://") or name.startswith("https://"):
            opener = "xdg-open"
            code, text = run_text([opener, name])
            return text or f"Opened {name}."
        path = Path(name).expanduser()
        if path.exists():
            code, text = run_text(["xdg-open", str(path)])
            return text or f"Opened {path}."
        if shutil.which(name):
            subprocess.Popen([name] + ([extra] if extra else []), start_new_session=True)
            return f"Opened {name}."
        code, text = run_text(["gtk-launch", name])
        if code != 0:
            return text or f"Could not open {name}."
        return f"Opened {name}."

    def screenshot(self, window: str | None) -> Shot:
        path = Path("/tmp/openctrl-shot.png")
        origin = (0, 0)
        if window and shutil.which("import") and shutil.which("xdotool"):
            code, wid = run_text(["xdotool", "search", "--name", window])
            first = (wid.split() or [""])[0]
            if code == 0 and first:
                geo = _window_geometry(first)
                shot = run_text(["import", "-window", first, str(path)], timeout=15)
                if shot[0] == 0 and path.is_file() and geo is not None:
                    return _store_shot(self, path, geo[0], geo[1], geo[2], geo[3], window)
        if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
            tool = "grim" if shutil.which("grim") else ""
            if not tool:
                return Shot("Wayland screenshot needs grim.", b"", 0, 0)
            code, text = run_text([tool, str(path)], timeout=15)
        else:
            if shutil.which("import"):
                code, text = run_text(["import", "-window", "root", str(path)], timeout=15)
            elif shutil.which("scrot"):
                code, text = run_text(["scrot", str(path)], timeout=15)
            else:
                return Shot("Screenshot needs ImageMagick import, scrot, or grim.", b"", 0, 0)
        if code != 0 or not path.is_file():
            return Shot(text or "Screenshot failed.", b"", 0, 0)
        note = window or "the desktop"
        if window:
            note = f"the desktop. A crop of {window!r} was not available"
        return _store_shot(self, path, origin[0], origin[1], 0, 0, note)

    def click(self, x: int, y: int, button: str, coordinate_space: str) -> str:
        missing = _need("xdotool")
        if missing:
            return missing
        sx, sy = self._to_screen(x, y, coordinate_space)
        which = {"left": "1", "right": "3", "middle": "2", "double": "1"}.get(button, "1")
        repeat = ["click", "--repeat", "2", which] if button == "double" else ["click", which]
        code, text = run_text(["xdotool", "mousemove", str(sx), str(sy), *repeat])
        if code != 0:
            return _session_hint(text)
        return f"Clicked {button} at {sx},{sy}."

    def scroll(self, direction: str, amount: int, x: int | None, y: int | None, coordinate_space: str) -> str:
        missing = _need("xdotool")
        if missing:
            return missing
        if x is not None and y is not None:
            sx, sy = self._to_screen(x, y, coordinate_space)
            run_text(["xdotool", "mousemove", str(sx), str(sy)])
        button = "4" if direction == "up" else "5"
        lines = max(1, min(int(amount), 12))
        code, text = run_text(["xdotool", "click", "--repeat", str(lines), button])
        if code != 0:
            return _session_hint(text)
        return f"Scrolled {direction} {lines}."

    def drag(self, x1: int, y1: int, x2: int, y2: int, coordinate_space: str) -> str:
        missing = _need("xdotool")
        if missing:
            return missing
        a = self._to_screen(x1, y1, coordinate_space)
        b = self._to_screen(x2, y2, coordinate_space)
        code, text = run_text(
            ["xdotool", "mousemove", str(a[0]), str(a[1]), "mousedown", "1", "mousemove", str(b[0]), str(b[1]), "mouseup", "1"]
        )
        if code != 0:
            return _session_hint(text)
        return f"Dragged from {a[0]},{a[1]} to {b[0]},{b[1]}."

    def clipboard_get(self) -> str:
        tool = "xclip" if shutil.which("xclip") else "wl-paste" if shutil.which("wl-paste") else ""
        if not tool:
            return "Clipboard needs xclip or wl-paste."
        args = [tool, "-selection", "clipboard", "-o"] if tool == "xclip" else [tool]
        code, text = run_text(args)
        return text or "Clipboard is empty."

    def clipboard_set(self, text: str) -> str:
        if shutil.which("xclip"):
            code, _ = run_text(["xclip", "-selection", "clipboard"], stdin=text)
        elif shutil.which("wl-copy"):
            code, _ = run_text(["wl-copy"], stdin=text)
        else:
            return "Clipboard needs xclip or wl-copy."
        if code != 0:
            return "Could not set the clipboard."
        return f"Copied {len(text)} characters."

    def cursor_prompt(self, folder: str, text: str, send: bool) -> str:
        opened = _open_cursor(folder)
        time.sleep(1.2)
        self.focus_window("Cursor")
        self.press_keys("ctrl+i")
        time.sleep(0.4)
        pasted = _paste(text)
        if send:
            self.press_keys("enter")
        return f"{opened} {pasted}"

    def window_action(self, title: str, action: str, monitor: int) -> str:
        missing = _need("wmctrl")
        if missing:
            return missing
        code, listing = run_text(["wmctrl", "-lx"])
        window_id = ""
        for line in listing.splitlines():
            if title.lower() in line.lower():
                window_id = line.split()[0]
                break
        if not window_id:
            return f"No window title contains {title}."
        act = action.strip().lower()
        if act == "minimize":
            code, text = run_text(["wmctrl", "-ir", window_id, "-b", "add,hidden"])
        elif act == "maximize":
            code, text = run_text(["wmctrl", "-ir", window_id, "-b", "add,maximized_vert,maximized_horz"])
        elif act == "restore":
            code, text = run_text(["wmctrl", "-ir", window_id, "-b", "remove,hidden,maximized_vert,maximized_horz"])
        elif act == "move":
            origin = _monitor_origin(monitor)
            code, text = run_text(["wmctrl", "-ir", window_id, "-e", f"0,{origin[0]},{origin[1]},1200,800"])
        else:
            return "action must be minimize, maximize, restore, or move."
        if code != 0:
            return text or "wmctrl failed."
        return f"Updated the window matching {title}."

    def _to_screen(self, x: int, y: int, coordinate_space: str) -> tuple[int, int]:
        if coordinate_space != "image":
            return int(x), int(y)
        if not self._capture:
            raise RuntimeError("No screenshot yet. Call screenshot, then click with coordinate_space image.")
        return image_to_screen(x, y, self._capture)


def _store_shot(desktop: Desktop, path: Path, ox: int, oy: int, rw: int, rh: int, label: str) -> Shot:
    image = Image.open(path)
    jpeg, width, height = to_jpeg(image)
    desktop._capture = {
        "ox": ox,
        "oy": oy,
        "rw": rw or width,
        "rh": rh or height,
        "iw": width,
        "ih": height,
    }
    return Shot(
        f"Screenshot of {label}. Image {width}x{height}. "
        "Click with coordinate_space image. (0, 0) is the top-left of this image.",
        jpeg,
        width,
        height,
    )


def _window_geometry(window_id: str) -> tuple[int, int, int, int] | None:
    code, text = run_text(["xdotool", "getwindowgeometry", window_id])
    if code != 0:
        return None
    position = (0, 0)
    size = (0, 0)
    for line in text.splitlines():
        if "Position:" in line:
            pair = line.split(":", 1)[1].strip().split()[0]
            left, _, top = pair.partition(",")
            if left.lstrip("-").isdigit() and top.lstrip("-").isdigit():
                position = (int(left), int(top))
        if "Geometry:" in line:
            pair = line.split(":", 1)[1].strip().split()[0]
            width, _, height = pair.partition("x")
            if width.isdigit() and height.isdigit():
                size = (int(width), int(height))
    if size[0] < 1 or size[1] < 1:
        return None
    return position[0], position[1], size[0], size[1]


def _need(tool: str) -> str:
    if shutil.which(tool):
        return ""
    return (
        f"{tool} is not installed. On Debian or Ubuntu: sudo apt install xdotool wmctrl scrot xclip. "
        "Wayland often blocks these tools. An X11 session can use them."
    )


def _session_hint(text: str) -> str:
    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        return "This is a Wayland session, so synthetic clicks and keys are blocked. Log in with an X11 session."
    return text


def _blocked(keys: str) -> bool:
    return keys.lower().replace(" ", "") in {"ctrl+alt+delete", "ctrl+alt+backspace"}


def _xdo(spec: str) -> str:
    bits = [part.strip().lower() for part in spec.split("+") if part.strip()]
    mapped = []
    for bit in bits:
        if bit in {"win", "super", "meta"}:
            mapped.append("super")
        elif bit == "control":
            mapped.append("ctrl")
        elif bit == "option":
            mapped.append("alt")
        elif bit == "escape":
            mapped.append("Escape")
        elif bit == "esc":
            mapped.append("Escape")
        elif bit == "return":
            mapped.append("Return")
        else:
            mapped.append(bit)
    return "+".join(mapped)


def _paste(text: str) -> str:
    if shutil.which("xclip"):
        _, previous = run_text(["xclip", "-selection", "clipboard", "-o"])
        code, _ = run_text(["xclip", "-selection", "clipboard"], stdin=text)
        if code != 0:
            return "Could not put the text on the clipboard."
        run_text(["xdotool", "key", "--clearmodifiers", "ctrl+v"])
        time.sleep(0.3)
        run_text(["xclip", "-selection", "clipboard"], stdin=previous)
        return f"Pasted {len(text)} characters."
    if shutil.which("wl-copy"):
        code, _ = run_text(["wl-copy"], stdin=text)
        if code != 0:
            return "Could not put the text on the clipboard."
        return f"Copied {len(text)} characters. Paste them in the focused window."
    return "Paste needs xclip or wl-copy."


def _open_cursor(folder_arg: str) -> str:
    binary = shutil.which("cursor") or shutil.which("cursor.AppImage")
    if not binary:
        return "cursor is not on PATH."
    folder = _resolve_folder(folder_arg) if folder_arg else ""
    if folder_arg and not folder:
        return f"Could not find folder {folder_arg!r}."
    subprocess.Popen([binary] + ([folder] if folder else []), start_new_session=True)
    if folder:
        return f"Opened Cursor in {folder}."
    return "Opened Cursor."


def _resolve_folder(raw: str) -> str:
    path = Path(raw).expanduser()
    if path.is_dir():
        return str(path)
    home = Path.home()
    for root in (home / "Desktop", home / "Documents", home):
        candidate = root / raw
        if candidate.is_dir():
            return str(candidate)
    return ""


def _monitor_origin(index: int) -> tuple[int, int]:
    code, text = run_text(["xrandr", "--listmonitors"])
    rows = [line for line in text.splitlines() if "+" in line]
    number = max(1, int(index)) - 1
    if number < len(rows):
        tail = rows[number].rsplit("+", 2)
        if len(tail) == 3 and tail[1].isdigit() and tail[2].isdigit():
            return int(tail[1]), int(tail[2])
    return 40, 40

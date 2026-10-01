"""macOS desktop. Accessibility through System Events, pixels through CoreGraphics."""

from __future__ import annotations

import ctypes
import subprocess
import threading
import time
from pathlib import Path

from PIL import Image

from openctrl.commands import run_cancellable, run_text
from openctrl.screen import Shot, image_to_screen, to_jpeg

_CODES = {
    "enter": 36,
    "return": 36,
    "esc": 53,
    "escape": 53,
    "tab": 48,
    "space": 49,
    "delete": 117,
    "backspace": 51,
    "up": 126,
    "down": 125,
    "left": 123,
    "right": 124,
    "home": 115,
    "end": 119,
    "pageup": 116,
    "pagedown": 121,
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 103,
    "f12": 111,
}


class Desktop:
    shell_name = "zsh"

    def __init__(self) -> None:
        self._capture: dict | None = None
        self._held = 0
        self._caffeine: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def push_awake(self) -> None:
        with self._lock:
            self._held += 1
            if self._held == 1:
                self._caffeine = subprocess.Popen(["caffeinate", "-dims"])

    def pop_awake(self) -> None:
        with self._lock:
            self._held = max(0, self._held - 1)
            if self._held == 0 and self._caffeine is not None:
                self._caffeine.terminate()
                self._caffeine = None

    def screen_locked(self) -> str | None:
        code, text = run_text(
            ["osascript", "-e", 'tell application "System Events" to get name of first process whose frontmost is true'],
            timeout=8,
        )
        if code == 0 and text.strip().lower() in {"loginwindow", "screensaverengine"}:
            return "The desktop is locked. Unlock the Mac, then send the task again."
        return None

    def run_shell(self, command: str, cancel: threading.Event, timeout: float, cwd: str | None) -> str:
        return run_cancellable(["/bin/zsh", "-lc", command], cancel, timeout, cwd)

    def list_windows(self) -> str:
        script = """
tell application "System Events"
  set out to ""
  repeat with p in (every process whose background only is false)
    set pname to name of p
    try
      repeat with w in windows of p
        set out to out & pname & " | " & (name of w as text) & linefeed
      end repeat
    end try
  end repeat
  return out
end tell
"""
        return _osa(script) or "No titled windows."

    def foreground(self) -> str:
        script = """
tell application "System Events"
  set p to first process whose frontmost is true
  set title to ""
  try
    set title to name of window 1 of p
  end try
  return (name of p) & " | " & title
end tell
"""
        return _osa(script)

    def focus_window(self, title: str) -> str:
        if not title.strip():
            return "focus_window needs a title."
        script = f"""
tell application "System Events"
  repeat with p in (every process whose background only is false)
    try
      repeat with w in windows of p
        if (name of w as text) contains "{_aq(title)}" then
          set frontmost of p to true
          perform action "AXRaise" of w
          return (name of p) & " | " & (name of w as text)
        end if
      end repeat
    end try
  end repeat
end tell
return "No window title contains {_aq(title)}"
"""
        return _osa(script)

    def ui_tree(self, title: str | None, max_depth: int, max_nodes: int) -> str:
        nodes = max(20, min(int(max_nodes), 120))
        which = _aq(title or "")
        script = f"""
tell application "System Events"
  if "{which}" is "" then
    set p to first process whose frontmost is true
    set w to window 1 of p
  else
    set w to missing value
    set p to missing value
    repeat with proc in (every process whose background only is false)
      try
        repeat with candidate in windows of proc
          if (name of candidate as text) contains "{which}" then
            set w to candidate
            set p to proc
          end if
        end repeat
      end try
    end repeat
    if w is missing value then return "No window title contains {which}"
  end if
  set out to (name of p) & " | " & (name of w as text) & linefeed
  set n to 0
  repeat with e in entire contents of w
    set n to n + 1
    if n > {nodes} then exit repeat
    set label to ""
    try
      set label to name of e as text
    end try
    set out to out & (role of e as text) & " " & label & linefeed
  end repeat
  return out
end tell
"""
        return _osa(script, timeout=25)

    def click_control(self, name: str, window: str | None, control_type: str | None) -> str:
        if not name.strip():
            return "click_control needs a name."
        role = _aq(control_type or "")
        script = f"""
tell application "System Events"
  set p to first process whose frontmost is true
  if "{_aq(window or "")}" is not "" then
    repeat with proc in (every process whose background only is false)
      try
        repeat with candidate in windows of proc
          if (name of candidate as text) contains "{_aq(window or "")}" then set p to proc
        end repeat
      end try
    end repeat
    set frontmost of p to true
  end if
  set target to missing value
  repeat with e in entire contents of window 1 of p
    set label to ""
    try
      set label to name of e as text
    end try
    if label contains "{_aq(name)}" then
      if "{role}" is "" or (role of e as text) contains "{role}" then
        set target to e
        exit repeat
      end if
    end if
  end repeat
  if target is missing value then return "No control named {_aq(name)}"
  click target
  return "Clicked " & (name of target as text)
end tell
"""
        return _osa(script, timeout=30)

    def type_text(self, text: str, window: str | None, control_name: str | None, clear: bool) -> str:
        if window:
            focused = self.focus_window(window)
            if focused.startswith("No window"):
                return focused
        if control_name:
            clicked = self.click_control(control_name, window, None)
            if clicked.startswith("No control"):
                return clicked
        return _paste(text, clear)

    def press_keys(self, keys: str) -> str:
        if _blocked(keys):
            return "That chord is a secure attention sequence. It was not sent."
        messages = []
        for chunk in [part.strip() for part in keys.split(",") if part.strip()]:
            messages.append(_keystroke(chunk))
        return " ".join(messages)

    def launch(self, target: str, args: str) -> str:
        name = target.strip()
        extra = args.strip()
        if not name:
            return "launch needs a target."
        if name.lower() == "cursor":
            return _open_cursor(extra)
        if name.startswith("http://") or name.startswith("https://") or name.startswith("file:"):
            code, text = run_text(["open", name])
            return text or f"Opened {name}."
        path = Path(name).expanduser()
        if path.exists():
            code, text = run_text(["open", str(path)])
            return text or f"Opened {path}."
        code, text = run_text(["open", "-a", name] + ([extra] if extra else []))
        if code != 0:
            return text or f"Could not open {name}."
        return f"Opened {name}."

    def screenshot(self, window: str | None) -> Shot:
        path = Path("/tmp/openctrl-shot.jpg")
        origin = (0, 0)
        logical = (0, 0)
        if window:
            bounds = _window_bounds(window)
            if bounds is None:
                return Shot(f"No window title contains {window}.", b"", 0, 0)
            x, y, w, h = bounds
            origin = (x, y)
            logical = (w, h)
            code, text = run_text(["screencapture", "-x", "-t", "jpg", "-R", f"{x},{y},{w},{h}", str(path)], timeout=15)
        else:
            code, text = run_text(["screencapture", "-x", "-t", "jpg", str(path)], timeout=15)
            logical = _desktop_points()
        if code != 0 or not path.is_file():
            return Shot(text or "screencapture failed.", b"", 0, 0)
        image = Image.open(path)
        jpeg, width, height = to_jpeg(image)
        point_w = logical[0] or width
        point_h = logical[1] or height
        self._capture = {"ox": origin[0], "oy": origin[1], "rw": point_w, "rh": point_h, "iw": width, "ih": height}
        label = window or "the desktop"
        return Shot(
            f"Screenshot of {label}. Image {width}x{height}. "
            "Click with coordinate_space image. (0, 0) is the top-left of this image.",
            jpeg,
            width,
            height,
        )

    def click(self, x: int, y: int, button: str, coordinate_space: str) -> str:
        sx, sy = self._to_screen(x, y, coordinate_space)
        _mouse(sx, sy, button)
        return f"Clicked {button} at {sx},{sy}."

    def scroll(self, direction: str, amount: int, x: int | None, y: int | None, coordinate_space: str) -> str:
        if x is not None and y is not None:
            sx, sy = self._to_screen(x, y, coordinate_space)
            _mouse(sx, sy, "move")
        lines = max(1, min(int(amount), 12))
        delta = lines if direction == "up" else -lines
        _scroll(delta)
        return f"Scrolled {direction} {lines}."

    def drag(self, x1: int, y1: int, x2: int, y2: int, coordinate_space: str) -> str:
        a = self._to_screen(x1, y1, coordinate_space)
        b = self._to_screen(x2, y2, coordinate_space)
        _drag(a, b)
        return f"Dragged from {a[0]},{a[1]} to {b[0]},{b[1]}."

    def clipboard_get(self) -> str:
        code, text = run_text(["pbpaste"])
        return text or "Clipboard is empty."

    def clipboard_set(self, text: str) -> str:
        code, _ = run_text(["pbcopy"], stdin=text)
        if code != 0:
            return "Could not set the clipboard."
        return f"Copied {len(text)} characters."

    def cursor_prompt(self, folder: str, text: str, send: bool) -> str:
        opened = _open_cursor(folder)
        time.sleep(1.2)
        self.focus_window("Cursor")
        self.press_keys("ctrl+i")
        time.sleep(0.4)
        pasted = _paste(text, False)
        if send:
            self.press_keys("enter")
        return f"{opened} {pasted}"

    def window_action(self, title: str, action: str, monitor: int) -> str:
        name = _aq(title)
        act = action.strip().lower()
        if act == "minimize":
            body = "set miniaturized of w to true"
        elif act == "maximize":
            body = "set value of attribute \"AXFullScreen\" of w to true"
        elif act == "restore":
            body = "set miniaturized of w to false"
        elif act == "move":
            frame = _display(monitor)
            if frame is None:
                return f"Monitor {monitor} was not found."
            x, y = int(frame[0]) + 40, int(frame[1]) + 40
            body = f"set position of w to {{{x}, {y}}}"
        else:
            return "action must be minimize, maximize, restore, or move."
        script = f"""
tell application "System Events"
  repeat with p in (every process whose background only is false)
    try
      repeat with w in windows of p
        if (name of w as text) contains "{name}" then
          {body}
          return "Updated " & (name of w as text)
        end if
      end repeat
    end try
  end repeat
end tell
return "No window title contains {name}"
"""
        return _osa(script)

    def _to_screen(self, x: int, y: int, coordinate_space: str) -> tuple[int, int]:
        if coordinate_space != "image":
            return int(x), int(y)
        if not self._capture:
            raise RuntimeError("No screenshot yet. Call screenshot, then click with coordinate_space image.")
        return image_to_screen(x, y, self._capture)


def _aq(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace('"', '\\"')


def _osa(script: str, timeout: float = 20) -> str:
    code, text = run_text(["osascript", "-"], timeout=timeout, stdin=script)
    if code != 0:
        return text or "osascript failed. Grant Accessibility permission to the terminal that runs OpenCtrl."
    return text or "Done."


def _paste(text: str, clear: bool) -> str:
    _, previous = run_text(["pbpaste"])
    code, _ = run_text(["pbcopy"], stdin=text)
    if code != 0:
        return "Could not put the text on the clipboard."
    if clear:
        _keystroke("ctrl+a")
    _keystroke("ctrl+v")
    time.sleep(0.3)
    run_text(["pbcopy"], stdin=previous)
    return f"Pasted {len(text)} characters."


def _blocked(keys: str) -> bool:
    flat = keys.lower().replace(" ", "")
    return flat in {"ctrl+alt+delete", "command+option+escape", "ctrl+option+escape"}


def _keystroke(spec: str) -> str:
    bits = [part.strip().lower() for part in spec.split("+") if part.strip()]
    if not bits:
        return "Empty key."
    key = bits[-1]
    mods = bits[:-1]
    using = []
    for mod in mods:
        if mod in {"ctrl", "control", "cmd", "command", "win", "super"}:
            using.append("command down")
        elif mod in {"alt", "option"}:
            using.append("option down")
        elif mod == "shift":
            using.append("shift down")
    suffix = ""
    if using:
        suffix = " using {" + ", ".join(using) + "}"
    if key in _CODES:
        script = f'tell application "System Events" to key code {_CODES[key]}{suffix}'
    elif len(key) == 1:
        script = f'tell application "System Events" to keystroke "{_aq(key)}"{suffix}'
    else:
        return f"Unknown key {key}."
    return _osa(script, timeout=8)


def _open_cursor(folder_arg: str) -> str:
    folder = _resolve_folder(folder_arg) if folder_arg else ""
    if folder_arg and not folder:
        return f"Could not find folder {folder_arg!r}."
    args = ["open", "-a", "Cursor"] + ([folder] if folder else [])
    code, text = run_text(args)
    if code != 0:
        return text or "Cursor was not found. Install it or open it once from the Applications folder."
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


def _desktop_points() -> tuple[int, int]:
    code, text = run_text(["osascript", "-e", 'tell application "Finder" to get bounds of window of desktop'], timeout=8)
    parts = [part.strip() for part in text.split(",")]
    if code != 0 or len(parts) != 4:
        return 0, 0
    try:
        width = int(parts[2]) - int(parts[0])
        height = int(parts[3]) - int(parts[1])
    except ValueError:
        return 0, 0
    if width < 1 or height < 1:
        return 0, 0
    return width, height


def _window_bounds(title: str) -> tuple[int, int, int, int] | None:
    script = f"""
tell application "System Events"
  repeat with p in (every process whose background only is false)
    try
      repeat with w in windows of p
        if (name of w as text) contains "{_aq(title)}" then
          set b to position of w
          set s to size of w
          return (item 1 of b as text) & "," & (item 2 of b as text) & "," & (item 1 of s as text) & "," & (item 2 of s as text)
        end if
      end repeat
    end try
  end repeat
end tell
return ""
"""
    text = _osa(script)
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 4 or not all(part.lstrip("-").isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def _cg():
    return ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


def _mouse(x: int, y: int, button: str) -> None:
    cg = _cg()
    point = _Point(float(x), float(y))
    cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, _Point, ctypes.c_uint32]
    cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    if button == "move":
        event = cg.CGEventCreateMouseEvent(None, 5, point, 0)
        cg.CGEventPost(0, event)
        return
    pairs = {"left": (1, 2, 0), "right": (3, 4, 1), "middle": (25, 26, 2), "double": (1, 2, 0)}
    down, up, which = pairs.get(button, pairs["left"])
    repeats = 2 if button == "double" else 1
    for _ in range(repeats):
        cg.CGEventPost(0, cg.CGEventCreateMouseEvent(None, down, point, which))
        time.sleep(0.04)
        cg.CGEventPost(0, cg.CGEventCreateMouseEvent(None, up, point, which))
        time.sleep(0.06)


def _scroll(lines: int) -> None:
    cg = _cg()
    cg.CGEventCreateScrollWheelEvent.restype = ctypes.c_void_p
    cg.CGEventCreateScrollWheelEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32]
    cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    cg.CGEventPost(0, cg.CGEventCreateScrollWheelEvent(None, 1, 1, int(lines)))


def _drag(start: tuple[int, int], end: tuple[int, int]) -> None:
    cg = _cg()
    cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, _Point, ctypes.c_uint32]
    cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    begin = _Point(float(start[0]), float(start[1]))
    finish = _Point(float(end[0]), float(end[1]))
    cg.CGEventPost(0, cg.CGEventCreateMouseEvent(None, 1, begin, 0))
    time.sleep(0.05)
    cg.CGEventPost(0, cg.CGEventCreateMouseEvent(None, 6, finish, 0))
    time.sleep(0.05)
    cg.CGEventPost(0, cg.CGEventCreateMouseEvent(None, 2, finish, 0))


def _display(index: int) -> tuple[float, float, float, float] | None:
    try:
        cg = _cg()
        ids = (ctypes.c_uint32 * 16)()
        count = ctypes.c_uint32()
        cg.CGGetOnlineDisplayList.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
        if cg.CGGetOnlineDisplayList(16, ids, ctypes.byref(count)) != 0:
            return None

        class _Rect(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("w", ctypes.c_double), ("h", ctypes.c_double)]

        cg.CGDisplayBounds.restype = _Rect
        cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        number = max(1, int(index)) - 1
        if number >= count.value:
            return None
        rect = cg.CGDisplayBounds(ids[number])
        return rect.x, rect.y, rect.w, rect.h
    except Exception:
        return None

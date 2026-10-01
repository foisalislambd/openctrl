"""Windows desktop control. Accessibility tree first, pixels only when a tool asks."""

from __future__ import annotations

import ctypes
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from io import BytesIO

def _enable_dpi() -> None:
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_enable_dpi()

import uiautomation as auto
from PIL import Image, ImageGrab

from openagent.hotkeys import blocks_secure_attention, to_sendkeys

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class Shot:
    text: str
    jpeg: bytes
    width: int
    height: int


class Desktop:
    def __init__(self) -> None:
        self._jobs: queue.Queue = queue.Queue()
        self._capture: dict | None = None
        self._thread = threading.Thread(target=self._worker, name="openagent-desktop", daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        with auto.UIAutomationInitializerInThread():
            while True:
                job = self._jobs.get()
                if job is None:
                    return
                fn, event, box = job
                try:
                    box["value"] = fn()
                except Exception as exc:
                    box["error"] = exc
                finally:
                    event.set()

    def run(self, fn, timeout: float = 60):
        event = threading.Event()
        box: dict = {}
        self._jobs.put((fn, event, box))
        if not event.wait(timeout):
            raise TimeoutError("The desktop did not answer in time. A window may be frozen.")
        if "error" in box:
            raise box["error"]
        return box["value"]

    def list_windows(self) -> str:
        return self.run(self._list_windows, 25)

    def foreground(self) -> str:
        return self.run(self._foreground, 20)

    def focus_window(self, title: str) -> str:
        return self.run(lambda: self._focus_window(title), 20)

    def ui_tree(self, title: str | None, max_depth: int, max_nodes: int) -> str:
        depth = max(1, min(int(max_depth), 8))
        nodes = max(20, min(int(max_nodes), 220))
        return self.run(lambda: self._ui_tree(title, depth, nodes), 40)

    def click_control(self, name: str, window: str | None, control_type: str | None) -> str:
        return self.run(lambda: self._click_control(name, window, control_type), 40)

    def type_text(self, text: str, window: str | None, control_name: str | None, clear: bool) -> str:
        return self.run(lambda: self._type_text(text, window, control_name, clear), 40)

    def press_keys(self, keys: str) -> str:
        chord = to_sendkeys(keys)
        return self.run(lambda: self._press_keys(chord), 20)

    def launch(self, target: str, args: str) -> str:
        return self.run(lambda: self._launch(target, args), 20)

    def screenshot(self, window: str | None) -> Shot:
        return self.run(lambda: self._screenshot(window), 25)

    def click(self, x: int, y: int, button: str, coordinate_space: str) -> str:
        return self.run(lambda: self._click(int(x), int(y), button, coordinate_space), 20)

    def scroll(self, direction: str, amount: int, x: int | None, y: int | None, coordinate_space: str) -> str:
        return self.run(
            lambda: self._scroll(direction, amount, x, y, coordinate_space),
            20,
        )

    def drag(self, x1: int, y1: int, x2: int, y2: int, coordinate_space: str) -> str:
        return self.run(lambda: self._drag(int(x1), int(y1), int(x2), int(y2), coordinate_space), 25)

    def clipboard_get(self) -> str:
        return self.run(self._clipboard_get, 15)

    def _locked(self) -> str | None:
        try:
            if auto.IsDesktopLocked():
                return "The Windows desktop is locked. Unlock the PC and tell me to continue."
        except Exception:
            return None
        return None

    def _list_windows(self) -> str:
        locked = self._locked()
        if locked:
            return locked
        lines = []
        for child in auto.GetRootControl().GetChildren():
            name = _safe(lambda: child.Name) or ""
            name = " ".join(name.split())
            if not name:
                continue
            hwnd = _safe(lambda: child.NativeWindowHandle) or 0
            minimized = bool(hwnd and auto.IsIconic(hwnd))
            pid = _safe(lambda: child.ProcessId) or 0
            process = _process_name(int(pid))
            state = "minimized" if minimized else "open"
            lines.append(f"[{state}] {name}  ·  {process or 'pid ' + str(pid)}")
            if len(lines) >= 40:
                lines.append("... only the first 40 windows are listed. Use focus_window with part of the title.")
                break
        if not lines:
            return "No titled windows."
        return "Open windows:\n" + "\n".join(lines)

    def _foreground(self) -> str:
        locked = self._locked()
        if locked:
            return locked
        focused = auto.GetFocusedControl()
        window = focused.GetTopLevelControl() if focused else None
        if window is None:
            window = auto.GetForegroundControl()
        title = _safe(lambda: window.Name) if window else ""
        pid = _safe(lambda: window.ProcessId) if window else 0
        process = _process_name(int(pid or 0))
        focused_name = _safe(lambda: focused.Name) if focused else ""
        focused_type = _safe(lambda: focused.ControlTypeName) if focused else ""
        return (
            f"Foreground: {title or '(untitled)'}\n"
            f"Process: {process or 'unknown'}\n"
            f"Focused control: {focused_type or 'unknown'} {focused_name!r}"
        )

    def _focus_window(self, title: str) -> str:
        locked = self._locked()
        if locked:
            return locked
        matches = _top_matches(title)
        if not matches:
            return f"No window title contains {title!r}.\n" + self._list_windows()
        window = matches[0]
        brought_forward = _activate(window)
        extra = ""
        if len(matches) > 1:
            names = "\n".join(f"- {_safe(lambda m=item: m.Name) or ''}" for item in matches[1:6])
            extra = "\nOther matches:\n" + names
        title_now = _safe(lambda: window.Name) or title
        if not brought_forward:
            return f"Could not bring this window to the front: {title_now}.{extra}"
        return f"Focused: {title_now}{extra}"

    def _ui_tree(self, title: str | None, max_depth: int, max_nodes: int) -> str:
        locked = self._locked()
        if locked:
            return locked
        root, label = _resolve_root(title)
        if root is None:
            return label
        lines = [label]
        shown = 0
        for control, depth in _walk(root, max_depth, max_nodes * 3):
            if shown >= max_nodes:
                lines.append(f"... stopped at {max_nodes} controls. Pass a deeper look or a tighter window title.")
                break
            name = " ".join((_safe(lambda c=control: c.Name) or "").split())[:100]
            ctype = _safe(lambda c=control: c.ControlTypeName) or "Control"
            aid = _safe(lambda c=control: c.AutomationId) or ""
            if depth > 1 and not name and not aid:
                continue
            rect = _safe(lambda c=control: c.BoundingRectangle)
            box = ""
            if rect is not None:
                box = f" @{rect.left},{rect.top} {rect.width()}x{rect.height()}"
            ident = f" id={aid}" if aid else ""
            lines.append(f"{'  ' * depth}{ctype}: {name}{ident}{box}")
            shown += 1
        if shown <= 1:
            lines.append("No named controls inside this window. A screenshot is required to see or click it.")
        return "\n".join(lines)

    def _click_control(self, name: str, window: str | None, control_type: str | None) -> str:
        locked = self._locked()
        if locked:
            return locked
        root, label = _resolve_root(window)
        if root is None:
            return label
        if window:
            _activate(root)
        wanted = name.strip().lower()
        if not wanted:
            return "click_control needs a control name from ui_tree."
        kind = (control_type or "").strip().lower()
        exact = None
        partials = []
        for control, _depth in _walk(root, 12, 2000):
            cname = " ".join((_safe(lambda c=control: c.Name) or "").split())
            if not cname or wanted not in cname.lower():
                continue
            ctype = (_safe(lambda c=control: c.ControlTypeName) or "")
            if kind and kind not in ctype.lower():
                continue
            if cname.lower() == wanted:
                exact = (control, ctype, cname)
                break
            if len(partials) < 8:
                partials.append((control, ctype, cname))
        if exact:
            control, ctype, cname = exact
        elif len(partials) == 1:
            control, ctype, cname = partials[0]
        elif len(partials) > 1:
            listing = "\n".join(f"- {ctype}: {cname}" for _c, ctype, cname in partials)
            return f"Several controls match {name!r}. Pass control_type or a longer name.\n{listing}"
        else:
            return f"No control matching {name!r}. Read ui_tree, or take a screenshot if the control has no name."
        try:
            scroll = control.GetScrollItemPattern()
            if scroll:
                scroll.ScrollIntoView(waitTime=0.05)
        except Exception:
            pass
        point = control.MoveCursorToInnerPos(simulateMove=True)
        if not point:
            return f"{ctype} {cname!r} has no clickable area."
        _pointer(button="left")
        return f"Clicked {ctype} {cname!r}."

    def _type_text(self, text: str, window: str | None, control_name: str | None, clear: bool) -> str:
        locked = self._locked()
        if locked:
            return locked
        if window:
            focused = self._focus_window(window)
            if not focused.startswith("Focused"):
                return focused
        if control_name:
            clicked = self._click_control(control_name, None, None)
            if not clicked.startswith("Clicked"):
                return clicked
        previous = None
        try:
            previous = auto.GetClipboardText()
        except Exception:
            previous = None
        if not auto.SetClipboardText(text):
            return "Could not put the text on the clipboard."
        time.sleep(0.1)
        if clear:
            auto.SendKeys("{Ctrl}a", interval=0.01, waitTime=0.05)
        auto.SendKeys("{Ctrl}v", interval=0.01, waitTime=0.05)
        # The target app reads the clipboard when it handles the paste. Restoring too early pastes the old text.
        time.sleep(0.4)
        if previous is not None:
            try:
                auto.SetClipboardText(previous)
            except Exception:
                pass
        target = control_name or "the focused control"
        return f"Pasted {len(text)} characters into {target}. The mouse and caret should have moved."

    def _press_keys(self, chord: str) -> str:
        locked = self._locked()
        if locked:
            return locked
        if blocks_secure_attention(chord):
            return "Windows blocks simulated Ctrl+Alt+Delete. Ask the user to press it."
        auto.SendKeys(chord, interval=0.01, waitTime=0.05)
        return f"Pressed {chord}."

    def _launch(self, target: str, args: str) -> str:
        target = target.strip().strip('"')
        if not target:
            return "launch needs a program, file, folder, or URL."
        if _is_cursor(target):
            return _open_cursor(args)
        try:
            if args.strip():
                subprocess.Popen(["cmd", "/c", "start", "", target, args], shell=False)
            else:
                os.startfile(target)
        except OSError as exc:
            return f"Could not open {target}: {exc}"
        return f"Opened {target}." + (f" Arguments: {args}" if args.strip() else "")

    def _screenshot(self, window: str | None) -> Shot:
        locked = self._locked()
        if locked:
            raise RuntimeError(locked)
        if window:
            matches = _top_matches(window)
            if not matches:
                raise RuntimeError(f"No window title contains {window!r}.")
            rect = matches[0].BoundingRectangle
            if rect.width() < 5 or rect.height() < 5:
                raise RuntimeError("That window has no visible area. Focus it first.")
            bbox = (rect.left, rect.top, rect.right, rect.bottom)
            origin = (rect.left, rect.top)
            label = _safe(lambda: matches[0].Name) or window
        else:
            monitors = auto.GetMonitorsRect()
            if not monitors:
                width, height = auto.GetScreenSize()
                bbox = (0, 0, width, height)
                origin = (0, 0)
            else:
                left = min(item.left for item in monitors)
                top = min(item.top for item in monitors)
                right = max(item.right for item in monitors)
                bottom = max(item.bottom for item in monitors)
                bbox = (left, top, right, bottom)
                origin = (left, top)
            label = "full desktop"
        image = ImageGrab.grab(bbox=bbox, all_screens=True)
        region_w, region_h = image.size
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        if image.mode != "RGB":
            image = image.convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=68, optimize=True)
        jpeg = buffer.getvalue()
        self._capture = {
            "ox": origin[0],
            "oy": origin[1],
            "rw": region_w,
            "rh": region_h,
            "iw": image.width,
            "ih": image.height,
        }
        text = (
            f"Screenshot of {label}.\n"
            f"Image size: {image.width}x{image.height}.\n"
            "The image is attached. For click, drag, and scroll, use coordinate_space \"image\". "
            "(0, 0) is the top-left of this image."
        )
        return Shot(text=text, jpeg=jpeg, width=image.width, height=image.height)

    def _click(self, x: int, y: int, button: str, coordinate_space: str) -> str:
        locked = self._locked()
        if locked:
            return locked
        sx, sy = self._to_screen(x, y, coordinate_space)
        kind = button if button in {"left", "right", "middle", "double"} else "left"
        double = kind == "double"
        real = "left" if double else kind
        auto.MoveTo(sx, sy, moveSpeed=1, waitTime=0.02)
        _pointer(real, double=double)
        return f"Clicked {kind} at screen ({sx}, {sy})."

    def _scroll(self, direction: str, amount: int, x: int | None, y: int | None, coordinate_space: str) -> str:
        locked = self._locked()
        if locked:
            return locked
        if x is not None and y is not None:
            sx, sy = self._to_screen(int(x), int(y), coordinate_space)
            auto.MoveTo(sx, sy, moveSpeed=1.4, waitTime=0.02)
        times = max(1, min(int(amount), 12))
        if direction.lower() in {"up", "left"}:
            auto.WheelUp(wheelTimes=times, interval=0.04, waitTime=0.05)
        else:
            auto.WheelDown(wheelTimes=times, interval=0.04, waitTime=0.05)
        return f"Scrolled {direction} {times} notches."

    def _drag(self, x1: int, y1: int, x2: int, y2: int, coordinate_space: str) -> str:
        locked = self._locked()
        if locked:
            return locked
        sx1, sy1 = self._to_screen(x1, y1, coordinate_space)
        sx2, sy2 = self._to_screen(x2, y2, coordinate_space)
        auto.MoveTo(sx1, sy1, moveSpeed=1, waitTime=0.02)
        auto.mouse_event(auto.MouseEventFlag.LeftDown, 0, 0, 0, 0)
        time.sleep(0.05)
        auto.MoveTo(sx2, sy2, moveSpeed=1, waitTime=0.02)
        auto.mouse_event(auto.MouseEventFlag.LeftUp, 0, 0, 0, 0)
        return f"Dragged from screen ({sx1}, {sy1}) to ({sx2}, {sy2})."

    def _clipboard_get(self) -> str:
        try:
            text = auto.GetClipboardText()
        except Exception as exc:
            return f"Could not read the clipboard: {exc}"
        if not text:
            return "Clipboard has no text."
        if len(text) > 4000:
            return text[:4000] + "\n... truncated"
        return text

    def _to_screen(self, x: int, y: int, coordinate_space: str) -> tuple[int, int]:
        if coordinate_space != "image":
            return x, y
        capture = self._capture
        if not capture:
            raise RuntimeError("No screenshot yet. Call screenshot, then click with coordinate_space image.")
        return image_to_screen(x, y, capture)


def run_powershell(command: str, cancel: threading.Event, timeout: float, cwd: str | None) -> str:
    if cwd and not os.path.isdir(cwd):
        return f"Working directory does not exist: {cwd}"
    wrapped = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "$ProgressPreference = 'SilentlyContinue'; "
        + command
    )
    process = subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", wrapped],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd or None,
        creationflags=_CREATE_NO_WINDOW,
    )
    stdout: list[str] = []
    stderr: list[str] = []

    def _read(pipe, sink: list[str]) -> None:
        try:
            data = pipe.read()
        except Exception as exc:
            sink.append(str(exc).encode("utf-8", errors="replace"))
            return
        sink.append(data or b"")

    threads = [
        threading.Thread(target=_read, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=_read, args=(process.stderr, stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    started = time.time()
    while process.poll() is None:
        if cancel.is_set() or time.time() - started > timeout:
            timed_out = not cancel.is_set()
            _stop_process(process)
            for thread in threads:
                thread.join(timeout=2)
            if timed_out:
                return f"Timed out after {int(timeout)} seconds."
            return "Cancelled."
        time.sleep(0.2)
    for thread in threads:
        thread.join(timeout=2)
    out = _decode(stdout[0] if stdout else b"")
    err = _decode(stderr[0] if stderr else b"")
    text = (out + ("\n" + err if err else "")).strip()
    if len(text) > 8000:
        text = text[:8000] + "\n... truncated"
    if not text:
        text = f"Exit code {process.returncode}. No output."
    else:
        text = f"Exit code {process.returncode}.\n{text}"
    return text


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
        capture_output=True,
        creationflags=_CREATE_NO_WINDOW,
    )
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _decode(data: bytes) -> str:
    if not data:
        return ""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16").strip()
    sample = data[:80]
    if sample.count(b"\x00") > len(sample) // 4:
        try:
            return data.decode("utf-16-le").strip()
        except UnicodeDecodeError:
            pass
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").strip()


def _is_cursor(target: str) -> bool:
    name = os.path.basename(target).lower()
    return name in {"cursor", "cursor.exe", "cursor.cmd"}


def _cursor_exe() -> str | None:
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = []
    if local:
        candidates.append(os.path.join(local, "Programs", "cursor", "Cursor.exe"))
    found = shutil.which("cursor")
    if found:
        base = found
        for _ in range(5):
            base = os.path.dirname(base)
            exe = os.path.join(base, "Cursor.exe")
            if os.path.isfile(exe):
                candidates.insert(0, exe)
                break
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _desktop_roots() -> list[str]:
    home = os.path.expanduser("~")
    return [
        os.path.join(home, "Desktop"),
        os.path.join(home, "OneDrive", "Desktop"),
        os.path.join(home, "Documents"),
        home,
    ]


def _resolve_folder(raw: str) -> str | None:
    text = os.path.expandvars(os.path.expanduser(raw.strip().strip('"').strip("'")))
    if not text or text == ".":
        return os.getcwd()
    if os.path.isabs(text) and os.path.isdir(text):
        return os.path.abspath(text)
    if not os.path.isabs(text):
        for root in _desktop_roots():
            candidate = os.path.join(root, text)
            if os.path.isdir(candidate):
                return os.path.abspath(candidate)
        cwd_candidate = os.path.abspath(text)
        if os.path.isdir(cwd_candidate):
            return cwd_candidate
    name = os.path.basename(text).lower()
    matches = []
    for root in _desktop_roots():
        if not os.path.isdir(root):
            continue
        try:
            entries = os.listdir(root)
        except OSError:
            continue
        for entry in entries:
            if entry.lower() == name and os.path.isdir(os.path.join(root, entry)):
                matches.append(os.path.abspath(os.path.join(root, entry)))
    if len(matches) == 1:
        return matches[0]
    return None


def _open_cursor(folder_arg: str) -> str:
    exe = _cursor_exe()
    if not exe:
        return "Cursor.exe was not found under Local AppData or on PATH."
    folder_arg = folder_arg.strip()
    if not folder_arg:
        subprocess.Popen([exe])
        return "Opened Cursor."
    folder = _resolve_folder(folder_arg)
    if not folder:
        return (
            f"Could not find folder {folder_arg!r}. "
            "Pass a full path, or the folder name as it appears on the Desktop."
        )
    subprocess.Popen([exe, folder])
    return f"Opened Cursor in {folder}."


def image_to_screen(x: int, y: int, capture: dict) -> tuple[int, int]:
    width = max(int(capture["iw"]), 1)
    height = max(int(capture["ih"]), 1)
    x = max(0, min(int(x), width - 1))
    y = max(0, min(int(y), height - 1))
    sx = int(capture["ox"]) + int(round(x * int(capture["rw"]) / width))
    sy = int(capture["oy"]) + int(round(y * int(capture["rh"]) / height))
    return sx, sy


def _pointer(button: str = "left", double: bool = False) -> None:
    pairs = {
        "left": (auto.MouseEventFlag.LeftDown, auto.MouseEventFlag.LeftUp),
        "right": (auto.MouseEventFlag.RightDown, auto.MouseEventFlag.RightUp),
        "middle": (auto.MouseEventFlag.MiddleDown, auto.MouseEventFlag.MiddleUp),
    }
    down, up = pairs[button]
    for _ in range(2 if double else 1):
        auto.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.04)
        auto.mouse_event(up, 0, 0, 0, 0)
        time.sleep(0.08)


def _activate(window) -> bool:
    hwnd = int(_safe(lambda: window.NativeWindowHandle) or 0)
    if hwnd and auto.IsIconic(hwnd):
        auto.ShowWindow(hwnd, auto.SW.Restore)
        time.sleep(0.15)
    if hwnd:
        _force_foreground(hwnd)
    try:
        window.SetFocus()
    except Exception:
        pass
    if not hwnd:
        return False
    time.sleep(0.05)
    fg = int(_USER32.GetForegroundWindow() or 0)
    return (fg & 0xFFFFFFFF) == (hwnd & 0xFFFFFFFF)


def _force_foreground(hwnd: int) -> None:
    """Let this thread take the foreground lock from whatever window is in front."""
    user32 = _USER32
    kernel32 = _KERNEL32
    current = kernel32.GetCurrentThreadId()
    foreground = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    attached = False
    if foreground_thread and current != foreground_thread:
        attached = bool(user32.AttachThreadInput(current, foreground_thread, True))
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if attached:
        user32.AttachThreadInput(current, foreground_thread, False)


def _user32():
    library = ctypes.WinDLL("user32", use_last_error=True)
    library.GetForegroundWindow.restype = ctypes.c_void_p
    library.GetWindowThreadProcessId.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    library.GetWindowThreadProcessId.restype = ctypes.c_uint32
    library.AttachThreadInput.argtypes = (ctypes.c_uint32, ctypes.c_uint32, ctypes.c_bool)
    library.AttachThreadInput.restype = ctypes.c_bool
    library.SetForegroundWindow.argtypes = (ctypes.c_void_p,)
    library.SetForegroundWindow.restype = ctypes.c_bool
    library.BringWindowToTop.argtypes = (ctypes.c_void_p,)
    library.BringWindowToTop.restype = ctypes.c_bool
    return library


def _kernel32():
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.GetCurrentThreadId.restype = ctypes.c_uint32
    return library


_USER32 = _user32()
_KERNEL32 = _kernel32()


def _top_matches(title: str) -> list:
    needle = title.strip().lower()
    exact = []
    partial = []
    for child in auto.GetRootControl().GetChildren():
        name = " ".join((_safe(lambda c=child: c.Name) or "").split())
        if not name:
            continue
        lowered = name.lower()
        if lowered == needle:
            exact.append(child)
        elif needle and needle in lowered:
            partial.append(child)
    return exact or partial


def _resolve_root(title: str | None):
    if title:
        matches = _top_matches(title)
        if not matches:
            return None, f"No window title contains {title!r}."
        window = matches[0]
        return window, f"Window: {_safe(lambda: window.Name) or title}"
    focused = auto.GetFocusedControl()
    window = focused.GetTopLevelControl() if focused else None
    if window is None:
        window = auto.GetForegroundControl()
    if window is None:
        return None, "No foreground window."
    return window, f"Foreground: {_safe(lambda: window.Name) or '(untitled)'}"


def _walk(root, max_depth: int, max_nodes: int):
    stack = [(root, 0)]
    seen = 0
    while stack and seen < max_nodes:
        control, depth = stack.pop()
        seen += 1
        yield control, depth
        if depth >= max_depth:
            continue
        try:
            children = control.GetChildren()
        except Exception:
            continue
        for child in reversed(children):
            stack.append((child, depth + 1))


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def _process_name(pid: int) -> str:
    if not pid:
        return ""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
    kernel32.QueryFullProcessImageNameW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_ulong),
    )
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        size = ctypes.c_ulong(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return os.path.basename(buffer.value)
    finally:
        kernel32.CloseHandle(handle)

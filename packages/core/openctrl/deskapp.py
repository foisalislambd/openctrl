"""Desktop window for setup, agent controls, and the local log."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from openctrl import __version__
from openctrl.config import Settings, SettingsError, read_settings, save_settings, values_from_settings
from openctrl.driver import Desktop
from openctrl.llm import OpenRouter
from openctrl.service import AgentService
from openctrl.store import SettingsStore

log = logging.getLogger("openctrl.deskapp")

LoginHook = Callable[[Path, bool], str]
DesktopFactory = Callable[[], Desktop]

_TEXT_FIELDS = (
    ("telegram_bot_token", "Telegram bot token", True),
    ("openrouter_api_key", "OpenRouter API key", True),
    ("telegram_allowed_user_ids", "Allowed Telegram ids", False),
    ("openrouter_model", "Model", False),
    ("openrouter_provider_sort", "Provider sort", False),
    ("openrouter_transcribe_model", "Voice model", False),
    ("max_steps", "Max steps", False),
    ("max_output_tokens", "Max reply tokens", False),
    ("max_task_cost", "Cost limit ($)", False),
)

_STATUS = {
    "stopped": ("Agent is stopped", "#5c6570"),
    "starting": ("Agent is starting", "#8a5a00"),
    "running": ("Agent is running", "#1b7f4a"),
    "stopping": ("Agent is stopping", "#8a5a00"),
    "error": ("Agent hit an error", "#a12622"),
}


def notify(title: str, text: str) -> None:
    try:
        root = tk.Tk()
    except tk.TclError:
        log.error("%s", text)
        return
    root.withdraw()
    messagebox.showinfo(title, text)
    root.destroy()


def run_app(root: Path, desktop_factory: DesktopFactory, apply_login: LoginHook) -> None:
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        raise SystemExit(f"OpenCtrl needs a desktop session to show its window. {exc}") from exc
    app = DeskApp(window, root.resolve(), desktop_factory, apply_login)
    app.build()
    window.after(200, app.boot)
    try:
        window.mainloop()
    except KeyboardInterrupt:
        app.service.stop()


class DeskApp:
    def __init__(
        self,
        window: tk.Tk,
        root: Path,
        desktop_factory: DesktopFactory,
        apply_login: LoginHook,
    ) -> None:
        self.window = window
        self.app_root = root
        self.desktop_factory = desktop_factory
        self.apply_login = apply_login
        self.service = AgentService()
        self.settings = read_settings(root)
        self._entries: dict[str, ttk.Entry] = {}
        self._secrets: list[ttk.Entry] = []
        self._show_secrets = tk.BooleanVar(value=False)
        self._autostart = tk.BooleanVar(value=self.settings.agent_autostart)
        self._login = tk.BooleanVar(value=self.settings.start_with_windows)
        self._status: ttk.Label | None = None
        self._detail: ttk.Label | None = None
        self._note_label: ttk.Label | None = None
        self._log: scrolledtext.ScrolledText | None = None

    def build(self) -> None:
        self.window.title(f"OpenCtrl {__version__}")
        self.window.minsize(680, 720)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(self.window)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        frame = ttk.Frame(self.window, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="OpenCtrl", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            frame,
            text="Set up the agent here. It runs on this computer and answers your Telegram chat.",
            wraplength=640,
        ).grid(row=1, column=0, sticky="w", pady=(2, 12))

        self._status = ttk.Label(frame, text="Agent is stopped", font=("Segoe UI", 12, "bold"))
        self._status.grid(row=2, column=0, sticky="w")
        self._detail = ttk.Label(frame, text="")
        self._detail.grid(row=3, column=0, sticky="w", pady=(0, 8))

        controls = ttk.LabelFrame(frame, text="Controls", padding=12)
        controls.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        buttons = ttk.Frame(controls)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Start agent", command=self.start_clicked).pack(side="left")
        ttk.Button(buttons, text="Stop agent", command=self.stop_clicked).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Open inbox", command=lambda: open_folder(self.app_root / "inbox")).pack(
            side="left", padx=(16, 0)
        )
        ttk.Button(buttons, text="Open logs", command=lambda: open_folder(self.app_root / "logs")).pack(
            side="left", padx=(8, 0)
        )
        ttk.Checkbutton(
            controls,
            text="Start the agent when this app opens",
            variable=self._autostart,
        ).pack(anchor="w", pady=(10, 0))
        ttk.Checkbutton(
            controls,
            text="Start OpenCtrl when I log in",
            variable=self._login,
        ).pack(anchor="w", pady=(4, 0))

        setup = ttk.LabelFrame(frame, text="Setup", padding=12)
        setup.grid(row=5, column=0, sticky="ew")
        setup.columnconfigure(1, weight=1)
        for row, (key, label, secret) in enumerate(_TEXT_FIELDS):
            ttk.Label(setup, text=label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
            entry = ttk.Entry(setup, show="•" if secret else "")
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            self._entries[key] = entry
            if secret:
                self._secrets.append(entry)
        ttk.Checkbutton(setup, text="Show tokens", variable=self._show_secrets, command=self._toggle_secrets).grid(
            row=len(_TEXT_FIELDS), column=1, sticky="w", pady=(4, 0)
        )
        ttk.Label(
            setup,
            text="Send /start to your bot, then paste the id it shows. Separate extra ids with commas.",
            wraplength=460,
        ).grid(row=len(_TEXT_FIELDS) + 1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(setup, text="Save and apply", command=self.save_clicked).grid(
            row=len(_TEXT_FIELDS) + 2, column=1, sticky="e", pady=(8, 0)
        )

        self._note_label = ttk.Label(frame, text="", wraplength=640)
        self._note_label.grid(row=6, column=0, sticky="w", pady=(8, 4))

        log_frame = ttk.LabelFrame(frame, text="Activity", padding=8)
        log_frame.grid(row=7, column=0, sticky="nsew", pady=(4, 0))
        frame.rowconfigure(7, weight=1)
        self._log = scrolledtext.ScrolledText(log_frame, height=8, state="disabled", wrap="word")
        self._log.pack(fill="both", expand=True)
        self._fill(self.settings)
        self.window.after(400, self._poll_status)
        self.window.after(600, self._poll_log)

    def boot(self) -> None:
        try:
            note = self.apply_login(self.app_root, self.settings.start_with_windows)
        except Exception as exc:
            note = str(exc)[:300]
            log.exception("Could not update the login item")
        else:
            log.info("%s", note)
        imported = SettingsStore(self.app_root).read().get("imported_from_env") == "1"
        if not self.settings.configured:
            self._note("Add your Telegram bot token and OpenRouter key, then click Save and apply.")
            return
        parts = []
        if imported:
            parts.append("Keys were copied from .env into the app database. You can delete that .env file.")
        if not self.settings.allowed_user_ids:
            parts.append("Send /start to the bot, paste your Telegram id, then click Save and apply.")
        if note:
            parts.append(note)
        self._note(" ".join(parts))
        if self.settings.agent_autostart:
            self._start_agent()

    def start_clicked(self) -> None:
        self._start_agent()

    def stop_clicked(self) -> None:
        self.service.stop()
        self._note("Stop requested.")

    def save_clicked(self) -> None:
        was_running = self.service.running()
        try:
            settings = save_settings(self.app_root, self._form_values())
        except SettingsError as exc:
            self._note(str(exc))
            return
        self.settings = settings
        self._fill(settings)
        try:
            note = self.apply_login(self.app_root, settings.start_with_windows)
        except Exception as exc:
            note = str(exc)[:300]
        if was_running:
            self.service.stop()
        if self.service.running():
            self._note("Saved, but the agent is still shutting down. " + note)
            return
        if was_running or settings.agent_autostart:
            if self._start_agent():
                self._note("Saved. The agent is starting. " + note)
            else:
                self._note("Saved. The previous agent is still running, so the new settings wait until you stop it. " + note)
            return
        self._note("Saved. The agent stays stopped until you click Start agent. " + note)

    def close(self) -> None:
        state, _detail = self.service.snapshot()
        if state in {"starting", "running", "stopping"}:
            if not messagebox.askokcancel("Quit OpenCtrl", "The agent is running. Quit and stop it?"):
                return
        self.service.stop()
        self.window.destroy()

    def _start_agent(self) -> bool:
        if not self.settings.configured:
            self._note("Add the Telegram bot token and OpenRouter key, then click Save and apply.")
            return False
        if self.service.running():
            return False
        try:
            desktop = self.desktop_factory()
            llm = OpenRouter(self.settings)
        except Exception as exc:
            log.exception("Could not start the agent")
            self._note(str(exc)[:300])
            return False
        return self.service.start(self.settings, desktop, llm)

    def _form_values(self) -> dict[str, str]:
        values = {key: entry.get().strip() for key, entry in self._entries.items()}
        values["agent_autostart"] = "1" if self._autostart.get() else "0"
        values["start_with_windows"] = "1" if self._login.get() else "0"
        return values

    def _fill(self, settings: Settings) -> None:
        values = values_from_settings(settings)
        for key, entry in self._entries.items():
            entry.delete(0, "end")
            entry.insert(0, values.get(key, ""))
        self._autostart.set(settings.agent_autostart)
        self._login.set(settings.start_with_windows)

    def _toggle_secrets(self) -> None:
        show = "" if self._show_secrets.get() else "•"
        for entry in self._secrets:
            entry.configure(show=show)

    def _note(self, text: str) -> None:
        if self._note_label is not None:
            self._note_label.configure(text=text)

    def _poll_status(self) -> None:
        if not self._window_open():
            return
        state, detail = self.service.snapshot()
        label, color = _STATUS.get(state, _STATUS["stopped"])
        if self._status is not None:
            self._status.configure(text=label, foreground=color)
        if self._detail is not None:
            self._detail.configure(text=detail)
        self.window.after(400, self._poll_status)

    def _window_open(self) -> bool:
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def _poll_log(self) -> None:
        if not self._window_open():
            return
        path = self.app_root / "logs" / "openctrl.log"
        text = ""
        if path.is_file():
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = []
            text = "\n".join(lines[-80:])
        if self._log is not None:
            self._log.configure(state="normal")
            self._log.delete("1.0", "end")
            self._log.insert("1.0", text)
            self._log.configure(state="disabled")
            self._log.see("end")
        if self._window_open():
            self.window.after(1500, self._poll_log)


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    target = str(path)
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
        return
    command = ["open", target] if sys.platform == "darwin" else ["xdg-open", target]
    subprocess.run(command, check=False)

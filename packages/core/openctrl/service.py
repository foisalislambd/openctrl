"""Runs the Telegram agent on a background thread so the desktop window stays usable."""

from __future__ import annotations

import asyncio
import logging
import threading

from openctrl.bot import serve
from openctrl.config import Settings
from openctrl.driver import Desktop
from openctrl.llm import OpenRouter

log = logging.getLogger("openctrl.service")


class AgentService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown: asyncio.Event | None = None
        self._stop_request = threading.Event()
        self._state = "stopped"
        self._detail = ""

    def snapshot(self) -> tuple[str, str]:
        with self._lock:
            return self._state, self._detail

    def running(self) -> bool:
        state, _detail = self.snapshot()
        return state in {"starting", "running", "stopping"}

    def start(self, settings: Settings, desktop: Desktop, llm: OpenRouter) -> bool:
        with self._lock:
            if self._state in {"starting", "running", "stopping"}:
                return False
            if self._thread and self._thread.is_alive():
                return False
            self._stop_request.clear()
            self._state = "starting"
            self._detail = ""
            self._thread = threading.Thread(
                target=self._thread_main,
                args=(settings, desktop, llm),
                name="openctrl-agent",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self, timeout: float = 12) -> None:
        self._stop_request.set()
        loop = self._loop
        if loop is not None and loop.is_running():
            self._set("stopping", "")
            loop.call_soon_threadsafe(self._signal_stop)
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout)
        if thread and thread.is_alive():
            self._set("error", "The agent did not stop. Quit OpenCtrl and start it again.")

    def _signal_stop(self) -> None:
        if self._shutdown is not None:
            self._shutdown.set()

    def _set(self, state: str, detail: str = "") -> None:
        with self._lock:
            self._state = state
            self._detail = detail

    def _thread_main(self, settings: Settings, desktop: Desktop, llm: OpenRouter) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._run(settings, desktop, llm))
        except Exception as exc:
            log.exception("Agent stopped")
            self._set("error", str(exc)[:300])
        else:
            state, _detail = self.snapshot()
            if state != "error":
                self._set("stopped", "")
        finally:
            self._shutdown = None
            self._loop = None
            loop.close()

    async def _run(self, settings: Settings, desktop: Desktop, llm: OpenRouter) -> None:
        shutdown = asyncio.Event()
        self._shutdown = shutdown
        if self._stop_request.is_set():
            await llm.close()
            return
        self._set("running", settings.model)
        await serve(settings, desktop, llm, shutdown=shutdown)

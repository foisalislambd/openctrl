"""Run a short command and keep the text."""

from __future__ import annotations

import os
import subprocess
import threading
import time


def run_text(args: list[str], timeout: float = 20, stdin: str | None = None) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            args,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return 127, f"{args[0]} is not installed."
    except subprocess.TimeoutExpired:
        return 124, "The command timed out."
    text = (completed.stdout or "").strip()
    err = (completed.stderr or "").strip()
    if err and text:
        text = f"{text}\n{err}"
    elif err:
        text = err
    return completed.returncode, text


def run_cancellable(args: list[str], cancel: threading.Event, timeout: float, cwd: str | None) -> str:
    if cwd and not os.path.isdir(cwd):
        return f"Working directory does not exist: {cwd}"
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd or None,
    )
    stdout: list[bytes] = []
    stderr: list[bytes] = []

    def _read(pipe, sink: list[bytes]) -> None:
        try:
            sink.append(pipe.read() or b"")
        except Exception as exc:
            sink.append(str(exc).encode("utf-8", errors="replace"))

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
            process.kill()
            for thread in threads:
                thread.join(timeout=2)
            if timed_out:
                return f"Timed out after {int(timeout)} seconds."
            return "Cancelled."
        time.sleep(0.2)
    for thread in threads:
        thread.join(timeout=2)
    out = (stdout[0] if stdout else b"").decode("utf-8", errors="replace").strip()
    err = (stderr[0] if stderr else b"").decode("utf-8", errors="replace").strip()
    text = (out + ("\n" + err if err else "")).strip()
    if len(text) > 8000:
        text = text[:8000] + "\n... truncated"
    if not text:
        return f"Exit code {process.returncode}. No output."
    return f"Exit code {process.returncode}.\n{text}"

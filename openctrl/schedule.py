"""Tasks that should run later, while OpenAgent is open in this desktop session."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

MAX_DELAY = 24 * 60 * 60
MIN_DELAY = 15


@dataclass
class Job:
    id: str
    user_id: int
    chat_id: int
    instruction: str
    run_at: float


class Schedule:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._jobs: list[Job] = []
        self._load()

    def add(self, user_id: int, chat_id: int, instruction: str, delay_seconds: int) -> str:
        text = " ".join(instruction.split())
        if not text:
            return "schedule needs an instruction."
        if len(text) > 2000:
            text = text[:2000]
        delay = max(MIN_DELAY, min(int(delay_seconds), MAX_DELAY))
        job = Job(
            id=uuid.uuid4().hex[:8],
            user_id=user_id,
            chat_id=chat_id,
            instruction=text,
            run_at=time.time() + delay,
        )
        self._jobs.append(job)
        self._save()
        return f"Scheduled {job.id} in {delay} seconds: {text}"

    def cancel(self, job_id: str) -> str:
        token = job_id.strip().lower()
        kept = [job for job in self._jobs if job.id != token]
        if len(kept) == len(self._jobs):
            return f"No scheduled task {token}."
        self._jobs = kept
        self._save()
        return f"Cancelled {token}."

    def listing(self) -> str:
        if not self._jobs:
            return "Nothing is scheduled."
        now = time.time()
        lines = []
        for job in sorted(self._jobs, key=lambda item: item.run_at):
            left = max(0, int(job.run_at - now))
            lines.append(f"{job.id}  in {left}s  {job.instruction}")
        return "Scheduled:\n" + "\n".join(lines)

    def due(self, now: float | None = None) -> list[Job]:
        moment = time.time() if now is None else now
        ready = [job for job in self._jobs if job.run_at <= moment]
        if not ready:
            return []
        ready_ids = {job.id for job in ready}
        self._jobs = [job for job in self._jobs if job.id not in ready_ids]
        self._save()
        return ready

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, list):
            return
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                self._jobs.append(
                    Job(
                        id=str(item["id"]),
                        user_id=int(item["user_id"]),
                        chat_id=int(item["chat_id"]),
                        instruction=str(item["instruction"])[:2000],
                        run_at=float(item["run_at"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "id": job.id,
                "user_id": job.user_id,
                "chat_id": job.chat_id,
                "instruction": job.instruction,
                "run_at": job.run_at,
            }
            for job in self._jobs
        ]
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

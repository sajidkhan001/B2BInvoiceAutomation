from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from b2bdoc.models import ProcessingStatus, ReviewTask
from b2bdoc.pipeline import PipelineResult


PollCallback = Callable[[], list[PipelineResult]]
EventCallback = Callable[["SchedulerEvent"], None]


@dataclass(frozen=True, slots=True)
class SchedulerEvent:
    created_at: datetime
    level: str
    message: str
    status: ProcessingStatus | None = None


@dataclass
class AutomationScheduler:
    poll_callback: PollCallback
    interval_seconds: int = 60
    event_callback: EventCallback | None = None
    review_tasks: list[ReviewTask] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None
        self.last_status: str = "Stopped"

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_paused(self) -> bool:
        return self._pause.is_set()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="b2bdoc-scheduler", daemon=True)
        self._thread.start()
        self._emit("info", "Automation started")

    def pause(self) -> None:
        self._pause.set()
        self.last_status = "Paused"
        self._emit("info", "Automation paused")

    def resume(self) -> None:
        self._pause.clear()
        self.last_status = "Running"
        self._emit("info", "Automation resumed")

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self.last_status = "Stopped"
        self._emit("info", "Automation stopped")

    def run_once(self) -> list[PipelineResult]:
        results = self.poll_callback()
        for result in results:
            if result.review_task is not None:
                self.review_tasks.append(result.review_task)
                self._emit("warning", "Document needs review", result.status)
            else:
                self._emit("info", f"Processed document: {result.status.value}", result.status)
        return results

    def _run(self) -> None:
        self.last_status = "Running"
        while not self._stop.is_set():
            if self._pause.is_set():
                self._stop.wait(1.0)
                continue
            try:
                self.run_once()
                self.last_error = None
            except Exception as exc:
                self.last_error = f"{exc.__class__.__name__}: {exc}"
                self.last_status = "Error"
                self._emit("error", self.last_error)
            self._stop.wait(max(1, self.interval_seconds))

    def _emit(self, level: str, message: str, status: ProcessingStatus | None = None) -> None:
        if self.event_callback:
            self.event_callback(
                SchedulerEvent(
                    created_at=datetime.now(timezone.utc),
                    level=level,
                    message=message,
                    status=status,
                )
            )

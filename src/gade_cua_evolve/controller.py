"""Thread-safe control and event channel shared by loops and the TUI."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

CompletionDecision = Literal["accept", "continue", "evaluate", "stop"]


@dataclass(slots=True)
class RunEvent:
    kind: str
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RunController:
    """Coordinate optional human steering without coupling loops to Textual."""

    def __init__(self, *, interactive: bool = False) -> None:
        self.interactive = interactive
        self.events: queue.Queue[RunEvent] = queue.Queue()
        self._feedback: queue.Queue[str] = queue.Queue()
        self._condition = threading.Condition()
        self._paused = False
        self._cancelled = False
        self._completion_decision: CompletionDecision | None = None

    def emit(self, kind: str, message: str = "", **payload: Any) -> None:
        self.events.put(RunEvent(kind=kind, message=message, payload=payload))

    def add_feedback(self, feedback: str) -> None:
        if feedback.strip():
            self._feedback.put(feedback.strip())
            self.emit("human_feedback", feedback.strip())

    def drain_feedback(self) -> list[str]:
        values: list[str] = []
        while True:
            try:
                values.append(self._feedback.get_nowait())
            except queue.Empty:
                return values

    def pause(self) -> None:
        with self._condition:
            self._paused = True
            self.emit("paused", "Execution paused")

    def resume(self) -> None:
        with self._condition:
            self._paused = False
            self._condition.notify_all()
            self.emit("resumed", "Execution resumed")

    def cancel(self) -> None:
        with self._condition:
            self._cancelled = True
            self._paused = False
            self._condition.notify_all()
            self.emit("cancelled", "Execution cancellation requested")

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def checkpoint(self) -> bool:
        with self._condition:
            while self._paused and not self._cancelled:
                self._condition.wait(timeout=0.5)
            return not self._cancelled

    def decide_completion(self, decision: CompletionDecision) -> None:
        with self._condition:
            self._completion_decision = decision
            self._condition.notify_all()

    def request_completion(self, message: str) -> CompletionDecision:
        if not self.interactive:
            return "accept"
        with self._condition:
            self._completion_decision = None
            self.emit("completion_requested", message)
            while self._completion_decision is None and not self._cancelled:
                self._condition.wait(timeout=0.5)
            return self._completion_decision or "stop"

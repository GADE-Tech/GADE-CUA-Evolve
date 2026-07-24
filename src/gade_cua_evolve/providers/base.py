"""Base interfaces for computer environment providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentObservation:
    """Snapshot of the current computer environment state."""

    screenshot: bytes | None = None
    text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionResult:
    """Result returned after executing controlled pyautogui code."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseComputerProvider(ABC):
    """Abstract interface for providers that expose a controllable computer."""

    @abstractmethod
    def observe(self) -> AgentObservation:
        """Return the latest observable state from the computer environment."""
        raise NotImplementedError

    @abstractmethod
    def execute_pyautogui(self, code: str) -> ExecutionResult:
        """Execute a controlled Python snippet that uses pyautogui."""
        raise NotImplementedError

    @abstractmethod
    def reset(self, task: str | None = None) -> None:
        """Reset the provider state before starting or retrying a task."""
        raise NotImplementedError

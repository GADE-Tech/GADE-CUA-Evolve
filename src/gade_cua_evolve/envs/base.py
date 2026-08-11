"""Environment adaptor contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from gade_cua_evolve.config import TaskSpec


@dataclass(slots=True)
class Observation:
    screenshot: bytes | None = None
    accessibility_tree: str | None = None
    terminal: str | None = None
    instruction: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StepOutcome:
    observation: Observation
    reward: float = 0.0
    done: bool = False
    info: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InspectionResult:
    language: str
    status: str
    output: str = ""
    error: str = ""
    returncode: int | None = None


@dataclass(slots=True)
class CodeExecutionResult:
    """Result of mutable code execution inside an isolated environment."""

    language: str
    status: str
    output: str = ""
    error: str = ""
    returncode: int | None = None


class EnvAdapter(ABC):
    """Normalize an external desktop runtime for agent loops."""

    @abstractmethod
    def reset(self, task: TaskSpec) -> Observation: ...

    @abstractmethod
    def step(self, action: str, pause: float = 2.0) -> StepOutcome: ...

    @abstractmethod
    def observe(self) -> Observation: ...

    def evaluate(self) -> float:
        return 0.0

    def inspect_gui(self, action: str, pause: float = 0.3) -> StepOutcome:
        """Execute a verifier navigation action through the environment boundary."""
        return self.step(action, pause)

    def run_inspection(
        self, language: str, code: str, timeout: int = 60
    ) -> InspectionResult:
        raise NotImplementedError(f"{type(self).__name__} does not support VM code inspection")

    def run_code(self, language: str, code: str, timeout: int = 30) -> CodeExecutionResult:
        """Run mutable code inside the isolated environment, never on the host."""
        raise NotImplementedError(f"{type(self).__name__} does not support VM code execution")

    def close(self) -> None:
        pass

    def start_recording(self) -> None:
        pass

    def stop_recording(self, dest: str) -> None:
        pass

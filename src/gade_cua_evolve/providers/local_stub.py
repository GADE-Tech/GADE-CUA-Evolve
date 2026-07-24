"""Local no-op provider for tests, examples, and dry runs."""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import AgentObservation, BaseComputerProvider, ExecutionResult


@dataclass(slots=True)
class LocalStubComputerProvider(BaseComputerProvider):
    """A provider that records actions without controlling the host machine."""

    task: str | None = None
    executed_code: list[str] = field(default_factory=list)
    observations: list[AgentObservation] = field(default_factory=list)

    def observe(self) -> AgentObservation:
        """Return a deterministic observation suitable for tests and README examples."""
        observation = AgentObservation(
            text="Local stub provider: no real machine is controlled.",
            metadata={
                "provider": "local_stub",
                "task": self.task,
                "executions": len(self.executed_code),
            },
        )
        self.observations.append(observation)
        return observation

    def execute_pyautogui(self, code: str) -> ExecutionResult:
        """Record pyautogui code and report success without executing it."""
        self.executed_code.append(code)
        return ExecutionResult(
            success=True,
            stdout="Local stub recorded pyautogui code without executing it.",
            metadata={
                "provider": "local_stub",
                "executions": len(self.executed_code),
            },
        )

    def reset(self, task: str | None = None) -> None:
        """Clear recorded actions and optionally set the current task."""
        self.task = task
        self.executed_code.clear()
        self.observations.clear()

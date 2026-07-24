"""Base interfaces for computer providers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionResult:
    """Result returned after attempting to execute an action."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class BaseComputerProvider:
    """Base class for providers that can execute generated computer actions."""

    def execute_pyautogui(self, action_code: str) -> ExecutionResult:
        """Execute generated `pyautogui` action code.

        Safety constraints:
        - Treat `action_code` as untrusted code.
        - Execute real actions only in an isolated VM or disposable sandbox, never on a
          personal or primary host machine.
        - Implementations that perform real execution must enforce a timeout, capture
          stdout and stderr, write an action audit log, and run with the minimum
          permissions required for the task.
        - Implementations should optionally validate actions with an allowlist before
          execution when the deployment can define safe imports, APIs, or statements.
        """

        raise NotImplementedError

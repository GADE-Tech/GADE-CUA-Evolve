"""VM-backed provider for executing generated `pyautogui` actions."""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from .base import BaseComputerProvider, ExecutionResult

LOGGER = logging.getLogger(__name__)
AllowlistCheck = Callable[[str], bool]


class VMComputerProvider(BaseComputerProvider):
    """Execute `pyautogui` actions in a controlled VM environment.

    The caller is responsible for ensuring this provider runs inside an isolated VM or
    equivalent disposable sandbox. The provider adds basic guardrails around the
    subprocess execution path: timeout enforcement, stdout/stderr capture, action
    logging, and optional allowlist validation.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        python_executable: str | None = None,
        action_log_path: str | Path | None = None,
        allowlist: Iterable[str] | AllowlistCheck | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.python_executable = python_executable or sys.executable
        self.action_log_path = Path(action_log_path) if action_log_path else None
        self.allowlist = allowlist

    def execute_pyautogui(self, action_code: str) -> ExecutionResult:
        """Execute action code with timeout, output capture, logging, and checks."""

        self._validate_allowlist(action_code)
        self._log_action(action_code)

        try:
            completed = subprocess.run(
                [self.python_executable, "-c", action_code],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = self._decode_output(exc.stdout)
            stderr = self._decode_output(exc.stderr)
            LOGGER.warning("pyautogui action timed out after %.2f seconds", self.timeout_seconds)
            return ExecutionResult(
                returncode=-1,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
            )

        LOGGER.info(
            "pyautogui action finished with return code %s", completed.returncode
        )
        if completed.stdout:
            LOGGER.debug("pyautogui stdout:\n%s", completed.stdout)
        if completed.stderr:
            LOGGER.debug("pyautogui stderr:\n%s", completed.stderr)
        return ExecutionResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _validate_allowlist(self, action_code: str) -> None:
        if self.allowlist is None:
            return
        if callable(self.allowlist):
            allowed = self.allowlist(action_code)
        else:
            allowed = any(token in action_code for token in self.allowlist)
        if not allowed:
            raise PermissionError("pyautogui action rejected by allowlist")

    def _log_action(self, action_code: str) -> None:
        LOGGER.info("pyautogui action code:\n%s", action_code)
        if self.action_log_path is None:
            return
        self.action_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.action_log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(action_code)
            log_file.write("\n---\n")

    @staticmethod
    def _decode_output(output: str | bytes | None) -> str:
        if output is None:
            return ""
        if isinstance(output, bytes):
            return output.decode(errors="replace")
        return output

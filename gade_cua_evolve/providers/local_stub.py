"""Safe local stub provider.

This provider intentionally never executes generated `pyautogui` code. It is useful
for development flows that need to inspect or log proposed actions without granting
control of the local machine.
"""

from __future__ import annotations

import logging

from .base import BaseComputerProvider, ExecutionResult

LOGGER = logging.getLogger(__name__)


class LocalStubComputerProvider(BaseComputerProvider):
    """Provider that records action code instead of executing it."""

    def execute_pyautogui(self, action_code: str) -> ExecutionResult:
        """Print and log action code without running it."""

        message = "local_stub refused to execute generated pyautogui action"
        print(f"{message}:\n{action_code}")
        LOGGER.info("%s:\n%s", message, action_code)
        return ExecutionResult(returncode=0, stdout=action_code)

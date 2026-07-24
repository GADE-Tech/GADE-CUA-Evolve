"""Volcengine VM provider placeholder.

This module reserves the integration boundary for a Volcengine-hosted VM. The
provider reads endpoint, token, and instance id from arguments or environment
variables, and will submit controlled pyautogui code to a remote execution API
when the integration is enabled.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .base import AgentObservation, BaseComputerProvider, ExecutionResult


@dataclass(slots=True)
class VolcengineComputerProvider(BaseComputerProvider):
    """Provider shell for controlling a Volcengine VM through a remote API."""

    endpoint: str | None = None
    token: str | None = None
    instance_id: str | None = None

    def __post_init__(self) -> None:
        self.endpoint = self.endpoint or os.getenv("VOLCENGINE_CUA_ENDPOINT")
        self.token = self.token or os.getenv("VOLCENGINE_CUA_TOKEN")
        self.instance_id = self.instance_id or os.getenv("VOLCENGINE_CUA_INSTANCE_ID")

    def observe(self) -> AgentObservation:
        """Fetch the latest remote VM observation.

        The concrete HTTP contract is intentionally left for the Volcengine
        adapter implementation.
        """
        raise NotImplementedError("Volcengine observation API is not implemented yet.")

    def execute_pyautogui(self, code: str) -> ExecutionResult:
        """Submit controlled pyautogui code to the remote execution endpoint."""
        raise NotImplementedError("Volcengine remote pyautogui execution is not implemented yet.")

    def reset(self, task: str | None = None) -> None:
        """Reset or prepare the remote VM instance for a task."""
        raise NotImplementedError("Volcengine VM reset API is not implemented yet.")

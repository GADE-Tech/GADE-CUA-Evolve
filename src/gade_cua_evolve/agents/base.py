"""Base abstractions for UI-control agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence


class BaseAgent(ABC):
    """Common interface for agents that build prompts and parse LLM replies."""

    def __init__(self, llm_client: Any, system_prompt: str = "", max_history: int = 10) -> None:
        self.llm_client = llm_client
        self.system_prompt = system_prompt
        self.max_history = max_history

    @abstractmethod
    def build_messages(
        self,
        task: str,
        observation: str | None = None,
        screenshot: Any | None = None,
        history: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Build provider-agnostic chat messages for the LLM."""

    @abstractmethod
    def parse_response(self, response: str) -> dict[str, Any]:
        """Parse a raw model response into an executable agent decision."""

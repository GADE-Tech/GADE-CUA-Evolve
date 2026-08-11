"""Provider-neutral multimodal model client contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    """One provider-neutral function call returned by a model."""

    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    reasoning: str | None = None
    model: str | None = None
    tool_calls: Sequence[ToolCall] = field(default_factory=tuple)
    usage: Mapping[str, Any] = field(default_factory=dict)
    raw: Any = None


class Client(ABC):
    """Hide provider SDK types behind one synchronous generation interface."""

    @abstractmethod
    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        **overrides: Any,
    ) -> LLMResponse:
        """Generate one response from provider-neutral chat messages."""

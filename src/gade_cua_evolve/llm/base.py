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
    thought_signature: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    reasoning: str | None = None
    model: str | None = None
    tool_calls: Sequence[ToolCall] = field(default_factory=tuple)
    usage: Mapping[str, Any] = field(default_factory=dict)
    raw: Any = None


def serialize_tool_calls(response: LLMResponse) -> list[dict[str, Any]]:
    """Serialize tool calls for a provider-neutral assistant history turn."""

    serialized: list[dict[str, Any]] = []
    for call in response.tool_calls:
        value: dict[str, Any] = {
            "id": call.id,
            "name": call.name,
            "arguments": dict(call.arguments),
        }
        if call.thought_signature:
            value["thought_signature"] = call.thought_signature
        serialized.append(value)
    return serialized


class Client(ABC):
    """Hide provider SDK types behind one synchronous generation interface."""

    @abstractmethod
    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        **overrides: Any,
    ) -> LLMResponse:
        """Generate one response from provider-neutral chat messages."""

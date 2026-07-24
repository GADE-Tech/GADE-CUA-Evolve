"""Shared abstractions for LLM clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class LLMMessage:
    """A provider-neutral chat message."""

    role: str
    content: str
    name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    """A provider-neutral model response."""

    content: str
    model: str | None = None
    provider: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    raw_response: Any | None = None


class BaseLLMClient(ABC):
    """Abstract base class for model providers."""

    @abstractmethod
    def generate(
        self,
        messages: Sequence[LLMMessage | Mapping[str, Any]],
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a response for a list of provider-neutral messages."""

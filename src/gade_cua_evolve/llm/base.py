"""Base LLM client protocol."""

from __future__ import annotations

from typing import Any, Protocol, Sequence


class BaseLLMClient(Protocol):
    """Minimal protocol expected by agents when calling an LLM."""

    def complete(self, messages: Sequence[dict[str, Any]], **kwargs: Any) -> str:
        """Return a model response for the supplied messages."""

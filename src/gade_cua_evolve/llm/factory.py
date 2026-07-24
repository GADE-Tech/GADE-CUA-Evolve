"""Factory helpers for constructing LLM clients from configuration."""

from __future__ import annotations

from typing import Any, Mapping

from .base import BaseLLMClient


def create_llm_client(config: Mapping[str, Any]) -> BaseLLMClient:
    """Create an LLM client using the provider field from a config mapping."""
    provider = str(config.get("provider", "")).lower()
    kwargs = {key: value for key, value in config.items() if key != "provider"}

    if provider == "openai":
        from .openai_client import OpenAILLMClient

        return OpenAILLMClient(**kwargs)
    if provider == "google":
        from .google_client import GoogleLLMClient

        return GoogleLLMClient(**kwargs)

    raise ValueError(f"Unsupported LLM provider: {provider!r}")

"""Factory helpers for constructing LLM clients from configuration."""

from __future__ import annotations

from gade_cua_evolve.config import LLMConfig, resolve_env

from .base import Client


def build_llm_client(config: LLMConfig) -> Client:
    kwargs = {
        "model": resolve_env(config.model_env) or config.model,
        "api_key": resolve_env(config.api_key_env, required=True),
        "temperature": config.temperature,
        "top_p": config.top_p,
        "max_tokens": config.max_tokens,
        "max_retries": config.max_retries,
        **config.extra,
    }

    if config.provider == "openai":
        from .openai_client import OpenAICompatClient

        return OpenAICompatClient(
            base_url=config.base_url or resolve_env(config.base_url_env),
            **kwargs,
        )
    if config.provider == "google":
        from .google_client import GoogleGenAIClient

        return GoogleGenAIClient(**kwargs)

    raise ValueError(f"Unsupported LLM provider: {config.provider!r}")

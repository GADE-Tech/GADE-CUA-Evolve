"""OpenAI implementation of the LLM client abstraction."""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from openai import OpenAI

from .base import BaseLLMClient, LLMMessage, LLMResponse


class OpenAILLMClient(BaseLLMClient):
    """LLM client backed by OpenAI chat completions."""

    def __init__(
        self,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        api_key: str | None = None,
        **client_kwargs: Any,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        resolved_api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not resolved_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI LLM client")
        self.client = OpenAI(api_key=resolved_api_key, **client_kwargs)

    def generate(
        self,
        messages: Sequence[LLMMessage | Mapping[str, Any]],
        **kwargs: Any,
    ) -> LLMResponse:
        request: dict[str, Any] = {
            "model": kwargs.pop("model", self.model),
            "messages": [self._to_openai_message(message) for message in messages],
        }
        temperature = kwargs.pop("temperature", self.temperature)
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        if temperature is not None:
            request["temperature"] = temperature
        if max_tokens is not None:
            request["max_tokens"] = max_tokens
        request.update(kwargs)

        response = self.client.chat.completions.create(**request)
        choice = response.choices[0] if response.choices else None
        content = choice.message.content if choice and choice.message else ""
        return LLMResponse(
            content=content or "",
            model=response.model,
            provider="openai",
            usage=response.usage.model_dump() if response.usage else {},
            raw_response=response,
        )

    @staticmethod
    def _to_openai_message(message: LLMMessage | Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(message, LLMMessage):
            payload: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.name:
                payload["name"] = message.name
            return payload
        return {key: value for key, value in message.items() if key in {"role", "content", "name"}}

"""Google Gemini implementation of the LLM client abstraction."""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from google import genai
from google.genai import types

from .base import BaseLLMClient, LLMMessage, LLMResponse


class GoogleLLMClient(BaseLLMClient):
    """LLM client backed by the Google GenAI SDK."""

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
        resolved_api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not resolved_api_key:
            raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY is required for Google LLM client")
        self.client = genai.Client(api_key=resolved_api_key, **client_kwargs)

    def generate(
        self,
        messages: Sequence[LLMMessage | Mapping[str, Any]],
        **kwargs: Any,
    ) -> LLMResponse:
        model = kwargs.pop("model", self.model)
        temperature = kwargs.pop("temperature", self.temperature)
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        config = kwargs.pop("config", None) or types.GenerateContentConfig()
        if temperature is not None:
            config.temperature = temperature
        if max_tokens is not None:
            config.max_output_tokens = max_tokens

        response = self.client.models.generate_content(
            model=model,
            contents=self._to_gemini_contents(messages),
            config=config,
            **kwargs,
        )
        return LLMResponse(
            content=response.text or "",
            model=model,
            provider="google",
            usage=response.usage_metadata.model_dump() if response.usage_metadata else {},
            raw_response=response,
        )

    @staticmethod
    def _to_gemini_contents(
        messages: Sequence[LLMMessage | Mapping[str, Any]],
    ) -> list[types.Content]:
        contents: list[types.Content] = []
        for message in messages:
            role = message.role if isinstance(message, LLMMessage) else str(message.get("role", "user"))
            content = message.content if isinstance(message, LLMMessage) else str(message.get("content", ""))
            gemini_role = "model" if role == "assistant" else "user"
            if role == "system":
                content = f"System instruction: {content}"
            contents.append(
                types.Content(role=gemini_role, parts=[types.Part.from_text(text=content)])
            )
        return contents

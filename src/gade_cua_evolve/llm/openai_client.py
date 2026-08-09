"""OpenAI-compatible multimodal client."""

from __future__ import annotations

import json
import ssl
from collections.abc import Mapping, Sequence
from typing import Any

import backoff

from .base import Client, LLMResponse, ToolCall


class OpenAICompatClient(Client):
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        temperature: float = 0.0,
        top_p: float = 0.9,
        max_tokens: int = 32768,
        max_retries: int = 5,
        **client_kwargs: Any,
    ) -> None:
        try:
            import openai
        except ImportError as exc:
            raise RuntimeError(
                "Install OpenAI support with: pip install 'gade-cua-evolve[openai]'"
            ) from exc
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.retry_errors = (
            openai.RateLimitError,
            openai.InternalServerError,
            openai.APIConnectionError,
            ssl.SSLError,
        )
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url, **client_kwargs)

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        **overrides: Any,
    ) -> LLMResponse:
        request: dict[str, Any] = {
            "model": overrides.pop("model", self.model),
            "messages": self._to_messages(messages),
            "temperature": overrides.pop("temperature", self.temperature),
            "top_p": overrides.pop("top_p", self.top_p),
            "max_tokens": overrides.pop("max_tokens", self.max_tokens),
        }
        tools = overrides.pop("tools", None)
        if tools:
            request["tools"] = [
                item
                if "function" in item
                else {
                    "type": "function",
                    "function": {
                        "name": item.get("name"),
                        "description": item.get("description"),
                        "parameters": item.get("parameters"),
                    },
                }
                for item in tools
            ]
        response_schema = overrides.pop("response_schema", None)
        if response_schema is not None:
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": response_schema},
            }
        request.update(overrides)

        @backoff.on_exception(backoff.expo, self.retry_errors, max_tries=self.max_retries)
        def call() -> Any:
            return self.client.chat.completions.create(**request)

        response = call()
        choice = response.choices[0] if response.choices else None
        message = choice.message if choice else None
        text = message.content if message else ""
        reasoning = getattr(message, "reasoning_content", None) if message else None
        tool_calls = tuple(
            ToolCall(
                id=call.id,
                name=call.function.name,
                arguments=json.loads(call.function.arguments or "{}"),
            )
            for call in (message.tool_calls or [])
        ) if message else ()
        return LLMResponse(
            text=text or "",
            reasoning=reasoning,
            tool_calls=tool_calls,
            model=response.model,
            usage=response.usage.model_dump() if response.usage else {},
            raw=response,
        )

    @staticmethod
    def _to_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Translate provider-neutral tool history to Chat Completions wire shapes."""
        translated: list[dict[str, Any]] = []
        for source in messages:
            role = str(source.get("role", "user"))
            message: dict[str, Any] = {"role": role}
            content = source.get("content", "")
            if role == "tool":
                message["tool_call_id"] = str(source.get("tool_call_id", ""))
                message["content"] = content if isinstance(content, str) else json.dumps(content)
            else:
                message["content"] = content
            calls = source.get("tool_calls", []) or []
            if calls:
                message["tool_calls"] = []
                for call in calls:
                    function = call.get("function") if isinstance(call, Mapping) else None
                    if isinstance(function, Mapping):
                        name = function.get("name", "")
                        arguments = function.get("arguments", "{}")
                    else:
                        name = call.get("name", "")
                        arguments = call.get("arguments", {})
                    if not isinstance(arguments, str):
                        arguments = json.dumps(arguments)
                    message["tool_calls"].append(
                        {
                            "id": str(call.get("id", "")),
                            "type": "function",
                            "function": {"name": str(name), "arguments": arguments},
                        }
                    )
            translated.append(message)
        return translated

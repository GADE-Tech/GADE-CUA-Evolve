"""Google GenAI ``generateContent`` multimodal client."""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import backoff

from .base import Client, LLMResponse, ToolCall


class GoogleGenAIClient(Client):
    """Translate neutral chat/tool messages to the Google GenAI SDK."""

    def __init__(
        self,
        model: str,
        api_key: str,
        temperature: float = 0.0,
        top_p: float = 0.9,
        max_tokens: int = 32768,
        max_retries: int = 5,
        **client_kwargs: Any,
    ) -> None:
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError(
                "Install Google support with: pip install 'gade-cua-evolve[google]'"
            ) from exc
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.client = genai.Client(api_key=api_key, **client_kwargs)

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        **overrides: Any,
    ) -> LLMResponse:
        from google.genai import types

        model = overrides.pop("model", self.model)
        supplied_config = overrides.pop("config", None)
        system_instruction, contents = self._to_contents(messages)
        config_values: dict[str, Any] = {
            "temperature": overrides.pop("temperature", self.temperature),
            "top_p": overrides.pop("top_p", self.top_p),
            "max_output_tokens": overrides.pop("max_tokens", self.max_tokens),
        }
        if system_instruction:
            config_values["system_instruction"] = system_instruction
        tools = overrides.pop("tools", None)
        if tools:
            config_values["tools"] = self._to_tools(tools)
            config_values["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
                disable=True
            )
        response_schema = overrides.pop("response_schema", None)
        if response_schema is not None:
            config_values["response_mime_type"] = "application/json"
            config_values["response_json_schema"] = response_schema
        if supplied_config is None:
            config = types.GenerateContentConfig(**config_values)
        elif isinstance(supplied_config, Mapping):
            config = types.GenerateContentConfig(**{**supplied_config, **config_values})
        else:
            config = supplied_config.model_copy(update=config_values)

        @backoff.on_exception(backoff.expo, Exception, max_tries=self.max_retries)
        def call() -> Any:
            return self.client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
                **overrides,
            )

        response = call()
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        candidate = response.candidates[0] if response.candidates else None
        parts = candidate.content.parts if candidate and candidate.content else []
        for part in parts or []:
            if part.function_call:
                function_call = part.function_call
                tool_calls.append(
                    ToolCall(
                        id=function_call.id or f"call_{uuid.uuid4().hex}",
                        name=function_call.name or "",
                        arguments=dict(function_call.args or {}),
                    )
                )
            elif part.text:
                if part.thought:
                    reasoning_parts.append(part.text)
                else:
                    text_parts.append(part.text)
        usage = response.usage_metadata
        return LLMResponse(
            text="".join(text_parts),
            reasoning="\n".join(reasoning_parts) or None,
            model=getattr(response, "model_version", None) or model,
            tool_calls=tuple(tool_calls),
            usage=usage.model_dump(mode="json") if usage else {},
            raw=response,
        )

    @staticmethod
    def _to_tools(tools: Sequence[Mapping[str, Any]]) -> list[Any]:
        from google.genai import types

        declarations = []
        for item in tools:
            function = item.get("function") if item.get("type") == "function" else None
            definition = function if isinstance(function, Mapping) else item
            declarations.append(
                types.FunctionDeclaration(
                    name=str(definition.get("name", "")),
                    description=str(definition.get("description", "")),
                    parameters_json_schema=definition.get("parameters")
                    or {"type": "object", "properties": {}},
                )
            )
        return [types.Tool(function_declarations=declarations)]

    @classmethod
    def _to_contents(
        cls, messages: Sequence[Mapping[str, Any]]
    ) -> tuple[str | None, list[Any]]:
        from google.genai import types

        systems: list[str] = []
        contents: list[Any] = []
        for message in messages:
            role = str(message.get("role", "user"))
            if role == "system":
                systems.extend(cls._text_values(message.get("content", "")))
                continue
            if role == "tool":
                value = message.get("content", {})
                if not isinstance(value, Mapping):
                    try:
                        value = json.loads(str(value))
                    except json.JSONDecodeError:
                        value = {"result": str(value)}
                part = types.Part.from_function_response(
                    name=str(message.get("name", "tool")), response=dict(value)
                )
                # Gemini generateContent represents function responses as a user turn.
                # Some endpoints reject the SDK-documented ``tool`` role outright.
                contents.append(types.Content(role="user", parts=[part]))
                continue

            parts = cls._content_parts(message.get("content", ""))
            for call in message.get("tool_calls", []) or []:
                parts.append(
                    types.Part.from_function_call(
                        name=str(call.get("name", "")),
                        args=dict(call.get("arguments", {})),
                    )
                )
            if parts:
                contents.append(
                    types.Content(role="model" if role == "assistant" else "user", parts=parts)
                )
        return "\n\n".join(systems) or None, contents

    @staticmethod
    def _text_values(content: Any) -> list[str]:
        if isinstance(content, str):
            return [content]
        if not isinstance(content, Sequence):
            return [str(content)]
        return [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, Mapping) and part.get("type") in {"text", "input_text", "output_text"}
        ]

    @staticmethod
    def _content_parts(content: Any) -> list[Any]:
        from google.genai import types

        normalized = content if isinstance(content, list) else [{"type": "text", "text": content}]
        parts: list[Any] = []
        for item in normalized:
            if not isinstance(item, Mapping):
                parts.append(types.Part.from_text(text=str(item)))
                continue
            part_type = item.get("type")
            if part_type in {"text", "input_text", "output_text"}:
                parts.append(types.Part.from_text(text=str(item.get("text", ""))))
            elif part_type in {"image", "image_url", "input_image"}:
                image = item.get("image") or item.get("image_url", "")
                uri = image.get("url", "") if isinstance(image, Mapping) else image
                if not isinstance(uri, str) or not uri.startswith("data:") or "," not in uri:
                    raise ValueError("GoogleGenAIClient only accepts base64 data URLs for images")
                header, encoded = uri.split(",", 1)
                mime = header.removeprefix("data:").split(";", 1)[0]
                parts.append(types.Part.from_bytes(data=base64.b64decode(encoded), mime_type=mime))
        return parts

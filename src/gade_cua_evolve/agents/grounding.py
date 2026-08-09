"""Provider-neutral, self-verifying GUI grounding."""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw

from gade_cua_evolve.config import GrounderConfig
from gade_cua_evolve.llm import Client, LLMResponse, ToolCall

GROUNDING_SYSTEM_PROMPT = """# Role
You are a precise GUI grounding model. Locate one GUI element in a desktop screenshot.
You may make exactly one tool call per turn.

# Procedure
1. Call `locate` with x/y coordinates normalized to the 0-1000 plane.
2. You will receive a zoomed crop with a red circle marking that point.
3. Call `confirm(status="success")` only if the circle is accurately centered on the target.
4. Call `confirm(status="continue")` when another locate attempt is needed.
5. Call `confirm(status="failed", feedback=...)` when the requested element is not visible.

Coordinates use (0,0) at the top-left and (1000,1000) at the bottom-right. Never guess an
invisible target and never return multiple tool calls."""

GROUNDING_TOOLS = [
    {
        "name": "locate",
        "description": "Locate the requested GUI element on a normalized 1000x1000 plane.",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "minimum": 0, "maximum": 1000},
                "y": {"type": "integer", "minimum": 0, "maximum": 1000},
            },
            "required": ["x", "y"],
            "additionalProperties": False,
        },
    },
    {
        "name": "confirm",
        "description": "Confirm or reject the most recently located point.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["success", "continue", "failed"]},
                "feedback": {"type": "string"},
            },
            "required": ["status"],
            "additionalProperties": False,
        },
    },
]


class GroundingError(RuntimeError):
    """Raised when a target cannot be grounded with sufficient confidence."""


class Grounder(ABC):
    @abstractmethod
    def locate(self, screenshot: bytes, description: str) -> tuple[float, float]:
        """Return an x/y point normalized to 0-1."""


def _data_url(image: bytes) -> str:
    encoded = base64.b64encode(image).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _assistant_message(response: LLMResponse) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": response.text,
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": dict(call.arguments)}
            for call in response.tool_calls
        ],
    }


class ToolCallingGrounder(Grounder):
    """Run the reference locate/crop/confirm protocol through any neutral Client."""

    def __init__(self, llm: Client, config: GrounderConfig) -> None:
        self.llm = llm
        self.config = config

    def locate(self, screenshot: bytes, description: str) -> tuple[float, float]:
        last_error: Exception | None = None
        for _ in range(self.config.semantic_retries):
            try:
                return self._locate_once(screenshot, description)
            except Exception as exc:  # noqa: BLE001 - semantic retries include malformed output
                last_error = exc
        raise GroundingError(
            f"Grounding failed for {description!r}: {last_error or 'unknown error'}"
        ) from last_error

    def _locate_once(self, screenshot: bytes, description: str) -> tuple[float, float]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": GROUNDING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"User instruction: {description}"},
                    {"type": "image_url", "image_url": {"url": _data_url(screenshot)}},
                ],
            },
        ]
        located: tuple[float, float] | None = None
        for _ in range(self.config.max_turns):
            response = self.llm.complete(
                messages,
                tools=GROUNDING_TOOLS,
                max_tokens=self.config.max_tokens,
                temperature=0.0,
            )
            if len(response.tool_calls) != 1:
                raise GroundingError(
                    f"Grounder returned {len(response.tool_calls)} tool calls; expected one"
                )
            call = response.tool_calls[0]
            messages.append(_assistant_message(response))
            if call.name == "locate":
                located = self._parse_point(call)
                messages.append(self._tool_result(call, {"located": True}))
                crop = self._annotated_crop(screenshot, located)
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "Zoomed verification crop. The red circle marks your point. "
                                    "Now call confirm, or call locate again to refine it."
                                ),
                            },
                            {"type": "image_url", "image_url": {"url": _data_url(crop)}},
                        ],
                    }
                )
                continue
            if call.name == "confirm":
                status = str(call.arguments.get("status", "")).lower()
                if status == "success":
                    if located is None:
                        raise GroundingError("Grounder confirmed before locating a point")
                    return located[0] / 1000.0, located[1] / 1000.0
                if status == "failed":
                    raise GroundingError(
                        f"Element not found: {call.arguments.get('feedback', 'no feedback')}"
                    )
                if status == "continue":
                    messages.append(self._tool_result(call, {"continue": True}))
                    continue
                raise GroundingError(f"Unknown confirmation status: {status!r}")
            raise GroundingError(f"Unknown grounding tool: {call.name!r}")
        raise GroundingError(f"Grounder exceeded {self.config.max_turns} turns")

    @staticmethod
    def _parse_point(call: ToolCall) -> tuple[float, float]:
        try:
            x = min(1000.0, max(0.0, float(call.arguments["x"])))
            y = min(1000.0, max(0.0, float(call.arguments["y"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise GroundingError(f"Invalid locate arguments: {dict(call.arguments)!r}") from exc
        return x, y

    @staticmethod
    def _tool_result(call: ToolCall, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": call.id,
            "name": call.name,
            "content": result,
        }

    def _annotated_crop(self, screenshot: bytes, point: tuple[float, float]) -> bytes:
        with Image.open(BytesIO(screenshot)) as source:
            image = source.convert("RGB")
        width, height = image.size
        x = round(point[0] / 1000.0 * max(width - 1, 0))
        y = round(point[1] / 1000.0 * max(height - 1, 0))
        radius = self.config.crop_radius
        left, top = max(0, x - radius), max(0, y - radius)
        right, bottom = min(width, x + radius), min(height, y + radius)
        crop = image.crop((left, top, right, bottom))
        draw = ImageDraw.Draw(crop)
        cx, cy = x - left, y - top
        ring = max(5, min(crop.size) // 30)
        draw.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), outline="red", width=3)
        output = BytesIO()
        crop.save(output, format="PNG")
        return output.getvalue()

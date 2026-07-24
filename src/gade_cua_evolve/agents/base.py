"""Base abstractions for computer-use agents.

This module intentionally avoids binding the agent contract to any single model
provider. Concrete implementations (Qwen, OpenAI, Gemini, etc.) can override the
prompt construction, history handling, tool descriptions, screenshot conversion,
and response parsing hooks independently.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(slots=True)
class AgentObservation:
    """Information available to an agent for one decision step.

    Attributes:
        screenshot: Optional screenshot payload. This may be raw bytes, a local
            path, a provider-specific image object, a base64 string, or any other
            representation understood by a concrete agent.
        image: Alias-style image payload for callers that do not model their
            visual input as a screenshot.
        text: Textual observation describing the current environment state.
        task: Current task instruction for the agent.
        metadata: Optional structured context such as window size, URL,
            timestamp, environment identifiers, or provider-specific fields.
    """

    text: str
    task: str
    screenshot: bytes | str | Path | object | None = None
    image: bytes | str | Path | object | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass(slots=True)
class AgentAction:
    """Parsed action returned by an agent.

    Attributes:
        raw_response: Original model response before provider-specific parsing.
        thought: Natural-language reasoning or concise rationale extracted from
            the model response.
        action_code: Executable action payload, for example pyautogui Python
            code, or another code-like command representation.
        stop: Whether the agent should stop interacting with the environment.
        done: Whether the task is considered complete.
        metadata: Optional structured parsing details for downstream consumers.
    """

    raw_response: Any
    thought: str = ""
    action_code: str = ""
    stop: bool = False
    done: bool = False
    metadata: Mapping[str, Any] | None = None


class BaseAgent(ABC):
    """Provider-neutral base class for computer-use agents.

    Subclasses typically override provider-facing hooks such as
    :meth:`system_prompt`, :meth:`tool_description`, :meth:`format_screenshot`,
    :meth:`format_observation`, :meth:`call_model`, and :meth:`parse_response`.
    The default :meth:`act` implementation wires those hooks together while
    keeping message history in a simple OpenAI-style list of dictionaries.
    """

    def __init__(
        self,
        *,
        system_prompt: str | None = None,
        tool_description: str | None = None,
        keep_history: bool = True,
    ) -> None:
        self._system_prompt = system_prompt
        self._tool_description = tool_description
        self.keep_history = keep_history
        self.task: str | None = None
        self.history: list[dict[str, Any]] = []

    def reset(self, task: str | None = None) -> None:
        """Clear conversational state and optionally set a new task."""

        self.task = task
        self.history.clear()

    def act(self, observation: AgentObservation) -> AgentAction:
        """Build messages, call the model, parse the response, and update history."""

        if observation.task:
            self.task = observation.task

        messages = self.build_messages(observation)
        raw_response = self.call_model(messages, observation=observation)
        action = self.parse_response(raw_response)

        if self.keep_history:
            self.update_history(messages, raw_response, action)

        return action

    def build_messages(self, observation: AgentObservation) -> list[dict[str, Any]]:
        """Build provider-agnostic chat messages for the next model call."""

        messages: list[dict[str, Any]] = []
        prompt = self.system_prompt()
        if prompt:
            messages.append({"role": "system", "content": prompt})

        if self.keep_history:
            messages.extend(self.history_messages())

        messages.append(
            {
                "role": "user",
                "content": self.format_observation(observation),
            }
        )
        return messages

    def system_prompt(self) -> str:
        """Return the high-level prompt used to steer the agent."""

        if self._system_prompt is not None:
            return self._system_prompt
        return (
            "You are a computer-use agent. Inspect the observation, decide the "
            "next step, and return a concise thought plus executable action code."
        )

    def tool_description(self) -> str:
        """Return tool or action-space instructions for the model."""

        if self._tool_description is not None:
            return self._tool_description
        return (
            "Available action format: provide Python code that can be executed "
            "with pyautogui to interact with the current desktop."
        )

    def history_messages(self) -> Sequence[dict[str, Any]]:
        """Return messages from prior turns that should be included in context."""

        return tuple(self.history)

    def format_observation(self, observation: AgentObservation) -> list[dict[str, Any]]:
        """Convert an observation into message content parts.

        The list-of-parts shape is intentionally generic and easy for provider
        adapters to transform into their native schema.
        """

        parts: list[dict[str, Any]] = [
            {"type": "text", "text": f"Task: {observation.task}"},
            {"type": "text", "text": f"Observation: {observation.text}"},
            {"type": "text", "text": self.tool_description()},
        ]

        screenshot = self.format_screenshot(observation)
        if screenshot is not None:
            parts.append(screenshot)

        if observation.metadata:
            parts.append({"type": "metadata", "metadata": dict(observation.metadata)})

        return parts

    def format_screenshot(self, observation: AgentObservation) -> dict[str, Any] | None:
        """Format screenshot or image data for inclusion in a model message."""

        image = observation.screenshot if observation.screenshot is not None else observation.image
        if image is None:
            return None
        return {"type": "image", "image": image}

    def update_history(
        self,
        messages: Sequence[dict[str, Any]],
        raw_response: Any,
        action: AgentAction,
    ) -> None:
        """Persist the latest user message and parsed assistant action."""

        if not messages:
            return

        latest_message = messages[-1]
        self.history.append(dict(latest_message))
        self.history.append(
            {
                "role": "assistant",
                "content": self.format_action_for_history(raw_response, action),
            }
        )

    def format_action_for_history(self, raw_response: Any, action: AgentAction) -> Any:
        """Return the assistant content stored in history after an action."""

        if isinstance(raw_response, str):
            return raw_response
        return {
            "thought": action.thought,
            "action_code": action.action_code,
            "stop": action.stop,
            "done": action.done,
            "raw_response": raw_response,
        }

    @abstractmethod
    def call_model(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        observation: AgentObservation,
    ) -> Any:
        """Call the underlying model provider and return its raw response."""

    @abstractmethod
    def parse_response(self, response: Any) -> AgentAction:
        """Parse a raw model response into an :class:`AgentAction`."""

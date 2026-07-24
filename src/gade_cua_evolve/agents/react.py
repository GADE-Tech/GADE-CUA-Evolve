"""ReACT-style agent for computer-use automation."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from gade_cua_evolve.agents.base import BaseAgent
from gade_cua_evolve.llm.base import BaseLLMClient


_SAFE_NOOP_ACTION = """import pyautogui\npyautogui.sleep(0)"""


class ReactAgent(BaseAgent):
    """Agent that asks an LLM for ReACT thought/action/done decisions.

    The model is prompted to reason in a short ``Thought`` section, emit a
    Python ``pyautogui`` action in a fenced code block, and state whether the
    task is complete with ``Done: true`` or ``Done: false``.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        system_prompt: str = "",
        max_history: int = 10,
    ) -> None:
        super().__init__(llm_client=llm_client, system_prompt=system_prompt, max_history=max_history)

    def build_messages(
        self,
        task: str,
        observation: str | None = None,
        screenshot: Any | None = None,
        history: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Build chat messages containing task, observation, screenshot, and history."""
        messages: list[dict[str, Any]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        sections = [
            "You are a ReACT computer-use agent. Produce exactly this structure:",
            "Thought: <brief reasoning about the next step>",
            "Action:",
            "```python",
            "# pyautogui code for the next safe UI action",
            "```",
            "Done: true/false",
            "",
            f"Task:\n{task}",
            "",
            f"Observation:\n{observation or 'No textual observation provided.'}",
            "",
            f"Screenshot:\n{self._format_screenshot(screenshot)}",
        ]

        formatted_history = self._format_history(history or [])
        if formatted_history:
            sections.extend(["", "History (most recent last):", formatted_history])

        messages.append({"role": "user", "content": "\n".join(sections)})
        return messages

    def parse_response(self, response: str) -> dict[str, Any]:
        """Parse Thought, fenced Python action code, and Done flag from a model reply.

        If parsing fails, return a safe no-op action and preserve the raw response
        for diagnostics.
        """
        try:
            thought_match = re.search(
                r"Thought\s*:\s*(.*?)(?=\n\s*Action\s*:|\Z)",
                response,
                flags=re.IGNORECASE | re.DOTALL,
            )
            action_match = re.search(
                r"Action\s*:\s*```(?:python|py)?\s*\n(.*?)```",
                response,
                flags=re.IGNORECASE | re.DOTALL,
            )
            done_match = re.search(r"Done\s*:\s*(true|false)", response, flags=re.IGNORECASE)

            if not thought_match or not action_match or not done_match:
                raise ValueError("Response does not contain Thought, fenced Action code, and Done flag.")

            action = action_match.group(1).strip()
            if not action:
                raise ValueError("Action code block is empty.")

            return {
                "thought": thought_match.group(1).strip(),
                "action": action,
                "done": done_match.group(1).lower() == "true",
                "raw_response": response,
                "parse_error": None,
            }
        except Exception as exc:  # Keep malformed LLM output from causing unsafe execution.
            return {
                "thought": "Failed to parse model response; using safe no-op action.",
                "action": _SAFE_NOOP_ACTION,
                "done": False,
                "raw_response": response,
                "parse_error": str(exc),
            }

    def _format_history(self, history: Sequence[Mapping[str, Any]]) -> str:
        recent_history = history[-self.max_history :] if self.max_history > 0 else []
        entries: list[str] = []
        for index, item in enumerate(recent_history, start=1):
            thought = item.get("thought", "")
            action = item.get("action", "")
            result = item.get("result", item.get("observation", ""))
            entries.append(
                f"{index}. Thought: {thought}\n"
                f"   Action: {action}\n"
                f"   Result: {result}"
            )
        return "\n".join(entries)

    @staticmethod
    def _format_screenshot(screenshot: Any | None) -> Any:
        if screenshot is None:
            return "No screenshot provided."
        if isinstance(screenshot, str):
            return screenshot
        if isinstance(screenshot, Mapping):
            description = screenshot.get("description") or screenshot.get("text")
            image = screenshot.get("image") or screenshot.get("content") or screenshot.get("data")
            if description and image:
                return {"description": description, "image": image}
            if description:
                return description
            if image:
                return image
        return screenshot

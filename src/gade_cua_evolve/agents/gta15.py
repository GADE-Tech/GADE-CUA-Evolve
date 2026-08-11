"""Gemini generateContent port of OSWorld's GTA1.5 computer-use agent."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from gade_cua_evolve.config import AgentConfig
from gade_cua_evolve.envs import Observation, StepOutcome
from gade_cua_evolve.llm import Client, LLMResponse, ToolCall

from .base import Agent, AgentStep
from .coder import CodeExecutor, CoderAgent, CoderResult
from .grounding import Grounder
from .gta15_prompts import CUA_SYSTEM_PROMPT, DEFAULT_REPLY, START_MESSAGE
from .gta15_tools import CODE_AGENT_TOOL, CUA_TOOLS, GTA15ActionRenderer


def _image_part(screenshot: bytes) -> dict[str, Any]:
    encoded = base64.b64encode(screenshot).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}


def _assistant_message(response: LLMResponse) -> dict[str, Any]:
    content = []
    if response.text:
        content.append({"type": "text", "text": response.text})
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": dict(call.arguments)}
            for call in response.tool_calls
        ],
    }


class GTA15Agent(Agent):
    """Own the GTA1.5 conversation, grounding, and tool rendering."""

    def __init__(
        self,
        llm: Client,
        config: AgentConfig,
        grounder: Grounder,
        client_password: str = "",
        coder: CoderAgent | None = None,
        code_executor: CodeExecutor | None = None,
    ) -> None:
        super().__init__(llm, config)
        self.grounder = grounder
        self.renderer = GTA15ActionRenderer(self.grounder, platform=config.platform)
        self.client_password = client_password
        self.coder = coder
        self.code_executor = code_executor
        self.tools = [*CUA_TOOLS, CODE_AGENT_TOOL] if coder is not None else CUA_TOOLS
        self._instruction: str | None = None
        self._pending_call: ToolCall | None = None
        self._pending_output: str | None = None
        self._feedback_cursor = 0

    def reset(self, logger=None) -> None:
        super().reset(logger)
        self._instruction = None
        self._pending_call = None
        self._pending_output = None
        self._feedback_cursor = 0

    def predict(self, instruction: str, obs: Observation) -> AgentStep:
        if not obs.screenshot:
            raise ValueError("GTA15Agent requires a screenshot observation")
        self._ensure_task(instruction, obs.screenshot)
        self._append_action_result(obs.screenshot)
        self._append_feedback()

        response: LLMResponse | None = None
        for retry in range(self.config.internal_retries):
            response = self.llm.complete(self.state.messages, tools=self.tools)
            if len(response.tool_calls) <= 1 and (response.tool_calls or self._terminal(response.text)):
                break
            reminder = DEFAULT_REPLY.format(instruction=instruction)
            if len(response.tool_calls) > 1:
                reminder += "\nYou returned multiple tool calls. Return exactly one."
            elif retry + 1 < self.config.internal_retries:
                reminder += "\nNo executable call or terminal status was returned; try again."
            self.state.messages.append(_assistant_message(response))
            self.state.messages.append({"role": "user", "content": reminder})

        assert response is not None
        self.state.messages.append(_assistant_message(response))
        self.state.responses.append(response.text)
        self.logger.info("GTA15 output: %s; calls=%s", response.text, response.tool_calls)
        self._dump_messages()

        terminal = self._terminal(response.text)
        if terminal:
            action = "DONE" if terminal == "TERMINATE" else "FAIL"
            return AgentStep(
                raw_response=response.text,
                thought=response.reasoning or response.text,
                low_level_instruction=terminal,
                actions=[action],
                done=True,
                metadata={"terminal": terminal},
            )
        if not response.tool_calls:
            return AgentStep(
                raw_response=response.text,
                thought=response.reasoning or response.text,
                low_level_instruction="No valid tool call; wait and retry from a fresh screenshot.",
                actions=["WAIT"],
                metadata={"error": "missing_tool_call"},
            )

        call = response.tool_calls[0]
        if call.name == "call_code_agent":
            return self._delegate_to_coder(response, call, instruction, obs)
        action, tool_output = self.renderer.execute(call, obs.screenshot)
        self._pending_call = call
        self._pending_output = tool_output
        self.state.actions.append(f"{call.name}({json.dumps(dict(call.arguments))})")
        return AgentStep(
            raw_response=response.text,
            thought=response.reasoning or response.text,
            low_level_instruction=f"{call.name}({json.dumps(dict(call.arguments))})",
            actions=[action],
            metadata={
                "tool_call": {"id": call.id, "name": call.name, "arguments": dict(call.arguments)},
                "tool_output": tool_output,
            },
        )

    def _delegate_to_coder(
        self,
        response: LLMResponse,
        call: ToolCall,
        instruction: str,
        obs: Observation,
    ) -> AgentStep:
        task = str(call.arguments.get("task", "")).strip()
        if self.coder is None or self.code_executor is None:
            result = CoderResult(
                completion_reason="UNAVAILABLE",
                summary="Coder execution is not configured for this environment.",
                rounds=0,
                error_cause="coder_unavailable",
            )
        elif not task:
            result = CoderResult(
                completion_reason="INVALID_TASK",
                summary="The planner did not provide a non-empty coding subtask.",
                rounds=0,
                error_cause="empty_subtask",
            )
        else:
            try:
                result = self.coder.execute(
                    original_task=instruction,
                    subtask=task,
                    screenshot=obs.screenshot,
                    executor=self.code_executor,
                )
            except Exception as exc:  # noqa: BLE001 - return delegated failures to planner
                result = CoderResult(
                    completion_reason="ERROR",
                    summary="Coder execution failed before it could return a verified report.",
                    rounds=0,
                    error_cause=type(exc).__name__,
                )
        tool_output = result.planner_report()
        self._pending_call = call
        self._pending_output = tool_output
        self.state.actions.append(f"{call.name}({json.dumps(dict(call.arguments))})")
        return AgentStep(
            raw_response=response.text,
            thought=response.reasoning or response.text,
            low_level_instruction=f"{call.name}({json.dumps(dict(call.arguments))})",
            actions=["WAIT"],
            metadata={
                "tool_call": {"id": call.id, "name": call.name, "arguments": dict(call.arguments)},
                "tool_output": tool_output,
                "coder": result.metadata(),
            },
        )

    def on_action_result(self, step: AgentStep, action: str, outcome: StepOutcome) -> None:
        if self._pending_call is None:
            return
        result = self._pending_output or "Action (tool call) was executed."
        if outcome.info:
            result += f" Environment info: {json.dumps(outcome.info, default=str)}"
        if action == "WAIT" and "Error:" not in result:
            result += " The environment waited without a GUI action."
        self._pending_output = result

    def on_feedback(self, feedback: str) -> None:
        super().on_feedback(feedback)

    def _append_feedback(self) -> None:
        for feedback in self.state.feedbacks[self._feedback_cursor :]:
            self.state.messages.append(
                {
                    "role": "user",
                    "content": (
                        "Feedback from a human or verifier. Treat it as evidence, verify it "
                        f"against the current screenshot, and fix actionable issues:\n{feedback.strip()}"
                    ),
                }
            )
        self._feedback_cursor = len(self.state.feedbacks)

    def _ensure_task(self, instruction: str, screenshot: bytes) -> None:
        if self._instruction is None:
            self._instruction = instruction
            self.state.messages.extend(
                [
                    {
                        "role": "system",
                        "content": CUA_SYSTEM_PROMPT.format(
                            CLIENT_PASSWORD=self.client_password
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": START_MESSAGE.format(instruction=instruction)},
                            _image_part(screenshot),
                        ],
                    },
                ]
            )
            return
        if instruction != self._instruction:
            raise ValueError("GTA15Agent must be reset before starting another task")

    def _append_action_result(self, screenshot: bytes) -> None:
        if self._pending_call is None:
            return
        self.state.messages.append(
            {
                "role": "tool",
                "tool_call_id": self._pending_call.id,
                "name": self._pending_call.name,
                "content": {"result": self._pending_output or "Action was executed."},
            }
        )
        self.state.messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Screenshot after the tool call was executed."},
                    _image_part(screenshot),
                ],
            }
        )
        self._pending_call = None
        self._pending_output = None
        self._prune_images()

    def _prune_images(self) -> None:
        image_messages = []
        for index, message in enumerate(self.state.messages):
            content = message.get("content")
            if isinstance(content, list) and any(
                isinstance(part, dict) and part.get("type") in {"image_url", "input_image"}
                for part in content
            ):
                image_messages.append(index)
        if len(image_messages) <= self.config.history_n + 1:
            return
        keep = {image_messages[0], *image_messages[-self.config.history_n :]}
        for index in reversed([value for value in image_messages if value not in keep]):
            content = self.state.messages[index]["content"]
            self.state.messages[index]["content"] = [
                part for part in content if part.get("type") not in {"image_url", "input_image"}
            ]

    def _dump_messages(self) -> None:
        if not self.config.dump_messages:
            return
        directory = Path(self.config.output_dir or "results") / "messages"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"step_{len(self.state.responses):04d}.json"
        path.write_text(json.dumps(self.state.messages, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _terminal(text: str) -> str | None:
        upper = (text or "").upper()
        if "INFEASIBLE" in upper:
            return "INFEASIBLE"
        if "TERMINATE" in upper:
            return "TERMINATE"
        return None

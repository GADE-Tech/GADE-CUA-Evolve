"""Qwen3-VL computer-use agent."""

from __future__ import annotations

import json
from pathlib import Path

from gade_cua_evolve.config import AgentConfig
from gade_cua_evolve.envs import Observation
from gade_cua_evolve.llm import Client

from .base import Agent, AgentStep
from .image import process_image
from .parsing import parse_response
from .prompts import instruction_prompt, system_prompt


class Qwen3VLAgent(Agent):
    def __init__(self, llm: Client, config: AgentConfig) -> None:
        super().__init__(llm, config)

    def _messages(
        self,
        instruction: str,
        current_image: str,
        processed_size: tuple[int, int],
    ) -> list[dict]:
        messages: list[dict] = [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": system_prompt(self.config.coordinate_type, *processed_size),
                    }
                ],
            }
        ]
        task_prompt = instruction_prompt(instruction, self.state.actions, self.state.feedbacks)
        history = self.state.history_window(self.config.history_n)
        for index, (image, response) in enumerate(history):
            content: list[dict] = [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image}"},
                }
            ]
            if index == 0:
                content.append({"type": "text", "text": task_prompt})
            messages.append({"role": "user", "content": content})
            messages.append(
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": response}],
                }
            )
        current_content: list[dict] = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{current_image}"},
            }
        ]
        if not history:
            current_content.append({"type": "text", "text": task_prompt})
        messages.append({"role": "user", "content": current_content})
        return messages

    def predict(self, instruction: str, obs: Observation) -> AgentStep:
        if not obs.screenshot:
            raise ValueError("Qwen3VLAgent requires a screenshot observation")
        encoded, original_w, original_h, processed_w, processed_h = process_image(
            obs.screenshot, self.config.image
        )
        self.state.screenshots.append(encoded)
        messages = self._messages(instruction, encoded, (processed_w, processed_h))
        if self.config.dump_messages:
            directory = Path(self.config.output_dir or "results") / "messages"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"step_{len(self.state.responses):04d}.json"
            path.write_text(json.dumps(messages), encoding="utf-8")
        result = self.llm.complete(messages)
        response = (
            f"<think>\n{result.reasoning}\n</think>\n\n{result.text}"
            if result.reasoning
            else result.text
        )
        step = parse_response(
            response,
            self.config.coordinate_type,
            (original_w, original_h),
            (processed_w, processed_h),
        )
        self.state.responses.append(response)
        self.state.actions.append(step.low_level_instruction)
        self.logger.info("Qwen3VL output: %s", response)
        return step

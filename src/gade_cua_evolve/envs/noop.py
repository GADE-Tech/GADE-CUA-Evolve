"""Safe environment used for tests and dry runs."""

from __future__ import annotations

import logging
from io import BytesIO

from PIL import Image

from gade_cua_evolve.config import EnvConfig, TaskSpec

from .base import EnvAdapter, Observation, StepOutcome


class NoopEnv(EnvAdapter):
    def __init__(self, config: EnvConfig) -> None:
        self.config = config
        self.actions: list[str] = []
        self._observation = Observation(screenshot=self._blank_png())

    def _blank_png(self) -> bytes:
        buffer = BytesIO()
        Image.new("RGB", self.config.screen_size, "white").save(buffer, "PNG")
        return buffer.getvalue()

    def reset(self, task: TaskSpec) -> Observation:
        self.actions.clear()
        self._observation = Observation(screenshot=self._blank_png(), instruction=task.instruction)
        return self._observation

    def observe(self) -> Observation:
        return self._observation

    def step(self, action: str, pause: float = 2.0) -> StepOutcome:
        self.actions.append(action)
        logging.getLogger(__name__).info("Noop action: %s", action)
        done = action in {"DONE", "FAIL"}
        info = {"done": True} if action == "DONE" else {"fail": True} if action == "FAIL" else {}
        return StepOutcome(self._observation, done=done, info=info)

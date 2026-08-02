"""Adaptor for OSWorld's DesktopEnv."""

from __future__ import annotations

import time
from typing import Any

from dotenv import load_dotenv

from gade_cua_evolve.config import EnvConfig, TaskSpec

from .base import EnvAdapter, Observation, StepOutcome


class OSWorldEnv(EnvAdapter):
    def __init__(self, config: EnvConfig) -> None:
        # OSWorld cloud providers read credentials directly from os.environ.
        load_dotenv(override=False)
        try:
            from desktop_env.desktop_env import DesktopEnv
        except ImportError as exc:
            raise RuntimeError(
                "OSWorld is unavailable. Run: pip install -e '/path/to/OSWorld'"
            ) from exc
        self.config = config
        self.env = DesktopEnv(
            provider_name=config.provider_name,
            region=config.region,
            path_to_vm=config.path_to_vm,
            snapshot_name=config.snapshot_name,
            action_space=config.action_space,
            screen_size=config.screen_size,
            headless=config.headless,
            require_a11y_tree=config.require_a11y_tree,
            require_terminal=config.require_terminal,
            os_type=config.os_type,
            client_password=config.client_password,
        )

    @staticmethod
    def _normalize(obs: dict[str, Any]) -> Observation:
        known = {"screenshot", "accessibility_tree", "terminal", "instruction"}
        return Observation(
            screenshot=obs.get("screenshot"),
            accessibility_tree=obs.get("accessibility_tree"),
            terminal=obs.get("terminal"),
            instruction=obs.get("instruction"),
            extra={key: value for key, value in obs.items() if key not in known},
        )

    def reset(self, task: TaskSpec) -> Observation:
        task_config = task.as_osworld_config()
        task_config.setdefault("evaluator", {"func": "infeasible"})
        self.env.reset(task_config=task_config)
        if self.config.boot_wait_seconds:
            time.sleep(self.config.boot_wait_seconds)
        return self.observe()

    def observe(self) -> Observation:
        return self._normalize(self.env._get_obs())

    def step(self, action: str, pause: float = 2.0) -> StepOutcome:
        obs, reward, done, info = self.env.step(action, pause)
        return StepOutcome(self._normalize(obs), float(reward), bool(done), dict(info))

    def evaluate(self) -> float:
        return float(self.env.evaluate())

    def close(self) -> None:
        self.env.close()

    def start_recording(self) -> None:
        self.env.controller.start_recording()

    def stop_recording(self, dest: str) -> None:
        self.env.controller.end_recording(dest)

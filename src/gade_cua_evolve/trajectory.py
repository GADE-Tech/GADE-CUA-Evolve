"""Durable run trajectory output."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gade_cua_evolve.config import RunConfig, TaskSpec
from gade_cua_evolve.envs import Observation


class TrajectoryRecorder:
    def __init__(self, root: Path, task: TaskSpec, config: RunConfig | None = None) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.directory = root / f"{task.id}-{stamp}"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.task = task
        self.config = config
        self.trajectory_path = self.directory / "traj.jsonl"
        self.action_count = 0

    def record_initial(self, observation: Observation) -> None:
        """Persist the post-reset state that the first model request observes."""
        if observation.screenshot:
            (self.directory / "initial_screenshot.png").write_bytes(observation.screenshot)

    def record(
        self,
        *,
        predict_step: int,
        agent_name: str,
        raw_response: str,
        thought: str,
        low_level_instruction: str,
        agent_metadata: dict[str, Any],
        action: str,
        observation: Observation,
        done: bool,
        info: dict[str, Any],
    ) -> None:
        self.action_count += 1
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "predict_step": predict_step,
            "action_step": self.action_count,
            "agent": agent_name,
            "raw_response": raw_response,
            "thought": thought,
            "low_level_instruction": low_level_instruction,
            "agent_metadata": agent_metadata,
            "action": action,
            "done": done,
            "info": info,
        }
        with self.trajectory_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
        if observation.screenshot:
            (self.directory / f"step_{self.action_count:04d}.png").write_bytes(
                observation.screenshot
            )

    def finish(self, *, score: float, done: bool, predict_steps: int) -> None:
        result = {
            "task": self.task.model_dump(mode="json"),
            "score": score,
            "done": done,
            "predict_steps": predict_steps,
            "action_steps": self.action_count,
            "config": self.config.model_dump(mode="json") if self.config else None,
        }
        (self.directory / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

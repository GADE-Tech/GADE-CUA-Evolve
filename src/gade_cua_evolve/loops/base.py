"""Scheduling abstraction for one or more agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gade_cua_evolve.agents import Agent
from gade_cua_evolve.config import LoopConfig, TaskSpec
from gade_cua_evolve.controller import RunController
from gade_cua_evolve.envs import EnvAdapter, Observation
from gade_cua_evolve.trajectory import TrajectoryRecorder

if TYPE_CHECKING:
    from gade_cua_evolve.reward import AgenticRewardModel


@dataclass(slots=True)
class RunResult:
    task: TaskSpec
    score: float | None
    done: bool
    predict_steps: int
    action_steps: int
    output_dir: str | None = None
    status: str = "finished"
    arm_verdict: str | None = None
    arm_feedback: list[str] | None = None
    episodes: int = 1


class AgentLoop(ABC):
    """High-level task lifecycle and multi-agent scheduling boundary."""

    def __init__(
        self,
        agents: Mapping[str, Agent],
        env: EnvAdapter,
        config: LoopConfig,
        recorder: TrajectoryRecorder | None = None,
        *,
        controller: RunController | None = None,
        reward_model: AgenticRewardModel | None = None,
        evaluate_at_end: bool = False,
    ) -> None:
        if not agents:
            raise ValueError("At least one agent is required")
        self.agents = dict(agents)
        self.env = env
        self.config = config
        self.recorder = recorder
        self.controller = controller or RunController()
        self.reward_model = reward_model
        self.evaluate_at_end = evaluate_at_end

    def select_agent(self, step_idx: int, obs: Observation) -> tuple[str, Agent]:
        return next(iter(self.agents.items()))

    @abstractmethod
    def run(self, task: TaskSpec) -> RunResult: ...

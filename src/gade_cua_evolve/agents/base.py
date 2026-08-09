"""Agent interface and step result."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from gade_cua_evolve.config import AgentConfig
from gade_cua_evolve.envs import Observation
from gade_cua_evolve.llm import Client

from .state import AgentState


@dataclass(slots=True)
class AgentStep:
    raw_response: str
    thought: str = ""
    low_level_instruction: str = ""
    actions: list[str] = field(default_factory=list)
    done: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class Agent(ABC):
    """Agent-owned prompt, context, and action-generation boundary."""

    action_space = "pyautogui"
    observation_type = "screenshot"

    def __init__(self, llm: Client, config: AgentConfig) -> None:
        self.llm = llm
        self.config = config
        self.state = AgentState()
        self.logger = logging.getLogger(type(self).__module__)

    def reset(self, logger: logging.Logger | None = None) -> None:
        self.state.clear()
        if logger is not None:
            self.logger = logger

    @abstractmethod
    def predict(self, instruction: str, obs: Observation) -> AgentStep: ...

    def on_action_result(self, step: AgentStep, action: str, outcome: Any) -> None:
        """Receive an executed action result; stateful agents may override this hook."""

    def on_feedback(self, feedback: str) -> None:
        """Receive human or verifier guidance before the next prediction."""
        if feedback.strip():
            self.state.feedbacks.append(feedback.strip())

"""Agent loop orchestration for GADE CUA experiments.

This module provides a small, dependency-light ReACT loop that connects a
``BaseAgent``-like object to an environment/provider capable of returning
observations and executing PyAutoGUI snippets.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(slots=True)
class AgentLoopConfig:
    """Configuration for :class:`AgentLoop`.

    Attributes:
        max_steps: Maximum number of agent/environment interaction steps.
        sleep_after_action: Seconds to sleep after each action execution.
        stop_on_done: Stop the loop when the provider reports ``done=True``.
        save_trajectory: Whether to save a ReACT trajectory as JSONL.
        trajectory_dir: Directory where trajectory JSONL files are written.
    """

    max_steps: int = 50
    sleep_after_action: float = 0.0
    stop_on_done: bool = True
    save_trajectory: bool = True
    trajectory_dir: str | Path = "trajectories"


@dataclass(slots=True)
class AgentLoopStep:
    """One ReACT interaction step captured for debugging/replay."""

    step: int
    thought: Any
    action: Any
    observation: Any
    result: Any
    done: bool = False


@dataclass(slots=True)
class AgentLoopResult:
    """Result returned by :meth:`AgentLoop.run`."""

    task: str
    steps: list[AgentLoopStep] = field(default_factory=list)
    done: bool = False
    final_observation: Any = None
    trajectory_path: str | None = None


@runtime_checkable
class BaseAgent(Protocol):
    """Minimal protocol expected from an agent used by :class:`AgentLoop`."""

    def reset(self) -> None:
        """Reset the agent state before a new task."""

    def act(self, observation: Any) -> Any:
        """Return the next action for the current observation."""


class AgentLoop:
    """Run a BaseAgent against an environment/provider.

    The provider is intentionally duck-typed so different CUA backends can be
    used. It may expose any of the following observation methods:
    ``reset(task=...)``, ``reset(task)``, ``get_observation()``, ``observe()``,
    or an ``observation`` attribute. To execute an action, it may expose
    ``execute_pyautogui(code)``, ``run_pyautogui(code)``, ``execute(code)``, or
    ``run(code)``.
    """

    def __init__(
        self,
        agent: BaseAgent,
        environment: Any | None = None,
        config: AgentLoopConfig | None = None,
        *,
        provider: Any | None = None,
    ) -> None:
        self.agent = agent
        self.provider = provider if provider is not None else environment
        if self.provider is None:
            raise ValueError("AgentLoop requires an environment/provider.")
        self.config = config or AgentLoopConfig()

    def run(self, task: str) -> AgentLoopResult:
        """Run the agent until done or ``max_steps`` is reached."""

        self._reset_agent()
        observation = self._reset_or_observe(task)
        steps: list[AgentLoopStep] = []
        done = False
        trajectory_path = self._new_trajectory_path() if self.config.save_trajectory else None

        for step_idx in range(self.config.max_steps):
            action = self.agent.act(observation)
            thought = self._extract_value(action, "thought")
            pyautogui_code = self._extract_pyautogui_code(action)
            execution_result = self._execute_pyautogui(pyautogui_code)
            done = self._extract_done(execution_result)

            next_observation = self._observe()
            if done is False:
                done = self._extract_done(next_observation)

            step = AgentLoopStep(
                step=step_idx + 1,
                thought=thought,
                action=action,
                observation=next_observation,
                result=execution_result,
                done=done,
            )
            steps.append(step)
            if trajectory_path is not None:
                self._append_trajectory(trajectory_path, step)

            observation = next_observation
            if self.config.sleep_after_action > 0:
                time.sleep(self.config.sleep_after_action)
            if self.config.stop_on_done and done:
                break

        return AgentLoopResult(
            task=task,
            steps=steps,
            done=done,
            final_observation=observation,
            trajectory_path=str(trajectory_path) if trajectory_path is not None else None,
        )

    def _reset_agent(self) -> None:
        reset = getattr(self.agent, "reset", None)
        if callable(reset):
            reset()

    def _reset_or_observe(self, task: str) -> Any:
        reset = getattr(self.provider, "reset", None)
        if callable(reset):
            try:
                observation = reset(task=task)
            except TypeError:
                try:
                    observation = reset(task)
                except TypeError:
                    observation = reset()
            if observation is not None:
                return observation
        return self._observe()

    def _observe(self) -> Any:
        for method_name in ("get_observation", "observe"):
            method = getattr(self.provider, method_name, None)
            if callable(method):
                return method()
        if hasattr(self.provider, "observation"):
            return getattr(self.provider, "observation")
        raise AttributeError(
            "Provider must define get_observation(), observe(), or an observation attribute."
        )

    def _execute_pyautogui(self, code: str) -> Any:
        for method_name in ("execute_pyautogui", "run_pyautogui", "execute", "run"):
            method = getattr(self.provider, method_name, None)
            if callable(method):
                return method(code)
        raise AttributeError(
            "Provider must define execute_pyautogui(), run_pyautogui(), execute(), or run()."
        )

    def _new_trajectory_path(self) -> Path:
        trajectory_dir = Path(self.config.trajectory_dir)
        trajectory_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return trajectory_dir / f"agent_loop_{timestamp}.jsonl"

    def _append_trajectory(self, path: Path, step: AgentLoopStep) -> None:
        with path.open("a", encoding="utf-8") as trajectory_file:
            trajectory_file.write(json.dumps(self._to_jsonable(step), ensure_ascii=False) + "\n")

    def _extract_pyautogui_code(self, action: Any) -> str:
        for key in ("pyautogui", "pyautogui_code", "code", "action"):
            value = self._extract_value(action, key)
            if isinstance(value, str):
                return value
        if isinstance(action, str):
            return action
        raise ValueError("Agent action must contain PyAutoGUI code as a string.")

    def _extract_done(self, value: Any) -> bool:
        done = self._extract_value(value, "done")
        return bool(done) if done is not None else False

    def _extract_value(self, value: Any, key: str) -> Any:
        if isinstance(value, Mapping):
            return value.get(key)
        if is_dataclass(value):
            return asdict(value).get(key)
        return getattr(value, key, None)

    def _to_jsonable(self, value: Any) -> Any:
        if is_dataclass(value):
            return {k: self._to_jsonable(v) for k, v in asdict(value).items()}
        if isinstance(value, Mapping):
            return {str(k): self._to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._to_jsonable(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return repr(value)

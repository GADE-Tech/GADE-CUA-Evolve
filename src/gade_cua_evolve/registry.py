"""Small explicit component registries."""

from __future__ import annotations

from typing import Any

from gade_cua_evolve.agents import GTA15Agent, Qwen3VLAgent
from gade_cua_evolve.agents.grounding import ToolCallingGrounder
from gade_cua_evolve.config import GrounderConfig, RunConfig
from gade_cua_evolve.controller import RunController
from gade_cua_evolve.envs import NoopEnv, OSWorldEnv
from gade_cua_evolve.llm import build_llm_client
from gade_cua_evolve.loops import AgenticFeedbackLoop, ReActLoop
from gade_cua_evolve.reward import AgenticRewardModel
from gade_cua_evolve.trajectory import TrajectoryRecorder

AGENTS = {"gta15": GTA15Agent, "qwen3vl": Qwen3VLAgent}
ENVS = {"noop": NoopEnv, "osworld": OSWorldEnv}
LOOPS = {"react": ReActLoop, "feedback": AgenticFeedbackLoop}


def build_components(
    config: RunConfig,
    recorder: TrajectoryRecorder,
    *,
    controller: RunController | None = None,
    arm_enabled: bool = False,
    evaluate_at_end: bool = False,
) -> tuple[Any, Any, Any]:
    try:
        agent_type = AGENTS[config.agent.name]
        env_type = ENVS[config.env.name]
        loop_type = (
            AgenticFeedbackLoop
            if arm_enabled or (controller and controller.interactive)
            else LOOPS[config.loop.name]
        )
    except KeyError as exc:
        raise ValueError(f"Unknown component name: {exc.args[0]}") from exc
    llm = build_llm_client(config.llm)
    grounder = None
    if agent_type is GTA15Agent or arm_enabled:
        grounder_config = config.grounder or GrounderConfig.model_validate(
            {**config.llm.model_dump(), "max_tokens": 512}
        )
        grounder = ToolCallingGrounder(build_llm_client(grounder_config), grounder_config)
    agent_config = config.agent.model_copy(update={"output_dir": recorder.directory})
    if agent_type is GTA15Agent:
        assert grounder is not None
        password = config.env.client_password or (
            "osworld-public-evaluation" if config.env.provider_name == "aws" else "password"
        )
        agent = agent_type(llm, agent_config, grounder, client_password=password)
    else:
        agent = agent_type(llm, agent_config)
    env = env_type(config.env)
    reward_model = None
    if arm_enabled:
        if config.arm is None:
            raise ValueError("ARM mode requires an 'arm' configuration section")
        assert grounder is not None
        reward_model = AgenticRewardModel(build_llm_client(config.arm.llm), grounder, config.arm)
    loop = loop_type(
        {"primary": agent},
        env,
        config.loop,
        recorder,
        controller=controller,
        reward_model=reward_model,
        evaluate_at_end=evaluate_at_end,
    )
    return agent, env, loop

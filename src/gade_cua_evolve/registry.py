"""Small explicit component registries."""

from __future__ import annotations

from typing import Any

from gade_cua_evolve.agents import GTA15Agent, Qwen3VLAgent
from gade_cua_evolve.config import RunConfig
from gade_cua_evolve.envs import NoopEnv, OSWorldEnv
from gade_cua_evolve.llm import build_llm_client
from gade_cua_evolve.loops import ReActLoop
from gade_cua_evolve.trajectory import TrajectoryRecorder

AGENTS = {"gta15": GTA15Agent, "qwen3vl": Qwen3VLAgent}
ENVS = {"noop": NoopEnv, "osworld": OSWorldEnv}
LOOPS = {"react": ReActLoop}


def build_components(config: RunConfig, recorder: TrajectoryRecorder) -> tuple[Any, Any, Any]:
    try:
        agent_type = AGENTS[config.agent.name]
        env_type = ENVS[config.env.name]
        loop_type = LOOPS[config.loop.name]
    except KeyError as exc:
        raise ValueError(f"Unknown component name: {exc.args[0]}") from exc
    llm = build_llm_client(config.llm)
    agent_config = config.agent.model_copy(update={"output_dir": recorder.directory})
    if agent_type is GTA15Agent:
        password = config.env.client_password or (
            "osworld-public-evaluation" if config.env.provider_name == "aws" else "password"
        )
        agent = agent_type(llm, agent_config, client_password=password)
    else:
        agent = agent_type(llm, agent_config)
    env = env_type(config.env)
    loop = loop_type({"primary": agent}, env, config.loop, recorder)
    return agent, env, loop

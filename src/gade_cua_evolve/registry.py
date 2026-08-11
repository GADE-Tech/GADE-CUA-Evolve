"""Small explicit component registries."""

from __future__ import annotations

from typing import Any

from gade_cua_evolve.agents import CoderAgent, GTA15Agent, Qwen3VLAgent
from gade_cua_evolve.agents.grounding import ToolCallingGrounder
from gade_cua_evolve.config import (
    GrounderConfig,
    RunConfig,
    resolve_client_password,
    resolve_env,
)
from gade_cua_evolve.controller import RunController
from gade_cua_evolve.envs import NoopEnv, OSWorldEnv
from gade_cua_evolve.llm import build_llm_client
from gade_cua_evolve.loops import AgenticFeedbackLoop, ReActLoop
from gade_cua_evolve.reward import AgenticRewardModel
from gade_cua_evolve.trajectory import TrajectoryRecorder

AGENTS = {"gta15": GTA15Agent, "qwen3vl": Qwen3VLAgent}
ENVS = {"noop": NoopEnv, "osworld": OSWorldEnv}
LOOPS = {"react": ReActLoop, "feedback": AgenticFeedbackLoop}


def _known_runtime_secrets(config: RunConfig, password: str) -> tuple[str, ...]:
    """Collect values that must never be persisted in delegated-code metadata."""
    names = {
        config.llm.api_key_env,
        config.grounder.api_key_env if config.grounder else None,
        config.coder.llm.api_key_env if config.coder else None,
        config.arm.llm.api_key_env if config.arm else None,
        "VOLCENGINE_ACCESS_KEY_ID",
        "VOLCENGINE_SECRET_ACCESS_KEY",
        "VOLCANO_ENGINE_ACCESS_KEY",
        "VOLCANO_ENGINE_SECRET_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    }
    values = [password]
    values.extend(value for name in names if (value := resolve_env(name)))
    return tuple(dict.fromkeys(value for value in values if value))


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
    password = resolve_client_password(config.env)
    env = env_type(config.env)
    try:
        llm = build_llm_client(config.llm)
        grounder = None
        if agent_type is GTA15Agent or arm_enabled:
            grounder_config = config.grounder or GrounderConfig.model_validate(
                {**config.llm.model_dump(), "max_tokens": 512}
            )
            grounder = ToolCallingGrounder(
                build_llm_client(grounder_config), grounder_config
            )
        coder = None
        if agent_type is GTA15Agent and config.coder is not None:
            coder = CoderAgent(
                build_llm_client(config.coder.llm),
                config.coder,
                secrets=_known_runtime_secrets(config, password),
            )
        reward_model = None
        if arm_enabled:
            if config.arm is None:
                raise ValueError("ARM mode requires an 'arm' configuration section")
            assert grounder is not None
            reward_model = AgenticRewardModel(
                build_llm_client(config.arm.llm), grounder, config.arm
            )

        agent_config = config.agent.model_copy(update={"output_dir": recorder.directory})
        if agent_type is GTA15Agent:
            assert grounder is not None
            agent = agent_type(
                llm,
                agent_config,
                grounder,
                client_password=password,
                coder=coder,
                code_executor=env.run_code if coder is not None else None,
            )
        else:
            agent = agent_type(llm, agent_config)
        loop = loop_type(
            {"primary": agent},
            env,
            config.loop,
            recorder,
            controller=controller,
            reward_model=reward_model,
            evaluate_at_end=evaluate_at_end,
        )
    except Exception:
        env.close()
        raise
    return agent, env, loop

from gade_cua_evolve import registry
from gade_cua_evolve.config import (
    AgentConfig,
    CoderConfig,
    EnvConfig,
    GrounderConfig,
    LLMConfig,
    RunConfig,
    TaskSpec,
)
from gade_cua_evolve.llm import Client, LLMResponse
from gade_cua_evolve.trajectory import TrajectoryRecorder


class FakeClient(Client):
    def complete(self, messages, **overrides):
        return LLMResponse(text="")


def coder_config(model: str) -> CoderConfig:
    return CoderConfig(llm=LLMConfig(model=model))


def test_registry_builds_independent_planner_grounder_and_coder_clients(
    monkeypatch, tmp_path
) -> None:
    built = []

    def fake_build(config):
        client = FakeClient()
        built.append((config.model, client))
        return client

    monkeypatch.setattr(registry, "build_llm_client", fake_build)
    config = RunConfig(
        llm=LLMConfig(model="planner"),
        grounder=GrounderConfig(model="grounder"),
        coder=coder_config("coder"),
        agent=AgentConfig(name="gta15"),
        env=EnvConfig(name="noop"),
    )
    recorder = TrajectoryRecorder(tmp_path, TaskSpec(instruction="test"), config)

    agent, env, _ = registry.build_components(config, recorder)

    assert [model for model, _ in built] == ["planner", "grounder", "coder"]
    assert agent.llm is built[0][1]
    assert agent.coder.llm is built[2][1]
    assert agent.code_executor.__self__ is env


def test_registry_closes_environment_when_component_construction_fails(
    monkeypatch, tmp_path
) -> None:
    state = {"closed": False}

    class TrackedEnv:
        def __init__(self, config):
            pass

        def close(self):
            state["closed"] = True

    monkeypatch.setitem(registry.ENVS, "tracked", TrackedEnv)
    monkeypatch.setattr(
        registry,
        "build_llm_client",
        lambda config: (_ for _ in ()).throw(RuntimeError("invalid client")),
    )
    config = RunConfig(env=EnvConfig(name="tracked"))
    recorder = TrajectoryRecorder(tmp_path, TaskSpec(instruction="test"), config)

    try:
        registry.build_components(config, recorder)
    except RuntimeError:
        pass

    assert state["closed"] is True

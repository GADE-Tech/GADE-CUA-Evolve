import json

import pytest

from gade_cua_evolve.agents import Qwen3VLAgent
from gade_cua_evolve.config import AgentConfig, EnvConfig, LoopConfig, RunConfig, TaskSpec
from gade_cua_evolve.envs import NoopEnv
from gade_cua_evolve.llm import Client, LLMResponse
from gade_cua_evolve.loops import AgenticFeedbackLoop, ReActLoop
from gade_cua_evolve.trajectory import TrajectoryRecorder


class FakeLLM(Client):
    def complete(self, messages, **overrides):
        return LLMResponse(
            text=(
                "Action: Finish the task.\n<tool_call>\n"
                '{"name":"computer_use","arguments":{"action":"terminate","status":"success"}}'
                "\n</tool_call>"
            )
        )


class FailingResetEnv(NoopEnv):
    def reset(self, task: TaskSpec):
        raise RuntimeError("setup failed")


def test_react_loop_end_to_end(tmp_path) -> None:
    task = TaskSpec(id="loop", instruction="Finish")
    recorder = TrajectoryRecorder(tmp_path, task)
    agent = Qwen3VLAgent(FakeLLM(), AgentConfig())
    loop = ReActLoop(
        {"primary": agent},
        NoopEnv(EnvConfig()),
        LoopConfig(max_steps=2, sleep_after_action=0, output_dir=tmp_path),
        recorder,
    )
    result = loop.run(task)
    assert result.done is True
    assert result.predict_steps == 1
    assert result.action_steps == 1
    assert (recorder.directory / "result.json").exists()
    assert (recorder.directory / "traj.jsonl").exists()
    assert (recorder.directory / "initial_screenshot.png").exists()
    trajectory = (recorder.directory / "traj.jsonl").read_text(encoding="utf-8")
    assert '"agent_metadata"' in trajectory
    assert '"low_level_instruction"' in trajectory


def test_result_config_redacts_inline_vm_password(tmp_path) -> None:
    task = TaskSpec(id="redaction", instruction="Finish")
    config = RunConfig(env=EnvConfig(client_password="vm-secret"))
    recorder = TrajectoryRecorder(tmp_path, task, config)

    recorder.finish(score=None, done=False, predict_steps=0)
    result = json.loads((recorder.directory / "result.json").read_text(encoding="utf-8"))

    assert result["config"]["env"]["client_password"] == "<redacted>"
    assert "vm-secret" not in json.dumps(result)


@pytest.mark.parametrize("loop_type", [ReActLoop, AgenticFeedbackLoop])
def test_setup_failure_is_recorded_as_error(tmp_path, loop_type) -> None:
    task = TaskSpec(id="setup-error", instruction="Fail during setup")
    recorder = TrajectoryRecorder(tmp_path, task)
    loop = loop_type(
        {"primary": Qwen3VLAgent(FakeLLM(), AgentConfig())},
        FailingResetEnv(EnvConfig()),
        LoopConfig(max_steps=1, output_dir=tmp_path),
        recorder,
    )

    with pytest.raises(RuntimeError, match="setup failed"):
        loop.run(task)

    result = json.loads((recorder.directory / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "error"
    assert result["done"] is False
    assert result["predict_steps"] == 0

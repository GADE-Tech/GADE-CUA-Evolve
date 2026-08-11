from gade_cua_evolve.agents import Qwen3VLAgent
from gade_cua_evolve.config import AgentConfig, EnvConfig, LoopConfig, TaskSpec
from gade_cua_evolve.envs import NoopEnv
from gade_cua_evolve.llm import Client, LLMResponse
from gade_cua_evolve.loops import ReActLoop
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

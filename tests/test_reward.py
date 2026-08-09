from copy import deepcopy

from gade_cua_evolve.agents import Agent, AgentStep
from gade_cua_evolve.agents.grounding import Grounder
from gade_cua_evolve.config import (
    AgentConfig,
    ARMConfig,
    EnvConfig,
    LLMConfig,
    LoopConfig,
    TaskSpec,
)
from gade_cua_evolve.envs import InspectionResult, NoopEnv
from gade_cua_evolve.llm import Client, LLMResponse, ToolCall
from gade_cua_evolve.loops import AgenticFeedbackLoop
from gade_cua_evolve.reward import (
    AgenticRewardModel,
    TrajectoryItem,
    VerificationPlan,
    VerificationResult,
)
from gade_cua_evolve.trajectory import TrajectoryRecorder


class FakeClient(Client):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, **overrides):
        self.calls.append((deepcopy(messages), deepcopy(overrides)))
        return self.responses.pop(0)


class FakeGrounder(Grounder):
    def locate(self, screenshot: bytes, description: str) -> tuple[float, float]:
        return 0.5, 0.5


class InspectableNoop(NoopEnv):
    def __init__(self):
        super().__init__(EnvConfig(screen_size=(100, 100)))
        self.evaluate_calls = 0

    def run_inspection(self, language, code, timeout=60):
        return InspectionResult(language, "success", output='{"state":"ok"}', returncode=0)

    def evaluate(self):
        self.evaluate_calls += 1
        return 1.0


def tool(name, **arguments):
    return LLMResponse(
        text="",
        tool_calls=(ToolCall(id=f"call-{name}", name=name, arguments=arguments),),
    )


def arm_config(**updates):
    return ARMConfig(
        llm=LLMConfig(model="judge", api_key_env="TEST_KEY"),
        max_judge_steps=5,
        **updates,
    )


def test_full_arm_tools_and_evaluator_ground_truth_privacy(tmp_path) -> None:
    client = FakeClient(
        [
            LLMResponse(text='{"task_understanding":"state is ok","checklist":["state is ok"]}'),
            tool(
                "inspect_with_code",
                language="python",
                code='print({"state":"ok"})',
                rationale="read persisted state",
            ),
            tool("trajectory_check", rationale="confirm actor history"),
            LLMResponse(
                text=(
                    '{"verdict":"success","trajectory_summary":"done",'
                    '"checklist_assessment":"satisfied","rationale":"visible"}'
                )
            ),
            tool("terminate", status="success", rationale="All checklist items have evidence."),
        ]
    )
    env = InspectableNoop()
    task = TaskSpec(
        id="private",
        instruction="Make state ok",
        raw={"evaluator": {"expected": {"secret_ground_truth": "NEVER_SHOW"}}},
    )
    initial = env.reset(task)
    reward = AgenticRewardModel(client, FakeGrounder(), arm_config())
    plan = reward.plan(task.public_view(), initial, tmp_path / "arm")
    result = reward.verify(
        task=task.public_view(),
        plan=plan,
        initial=initial,
        current=initial,
        trajectory=[TrajectoryItem(1, "WAIT", "checking", initial.screenshot)],
        env=env,
        directory=tmp_path / "arm" / "episode_01",
    )

    assert result.verdict == "success"
    assert (tmp_path / "arm" / "episode_01" / "inspections").is_dir()
    assert (tmp_path / "arm" / "episode_01" / "trajectory_checks").is_dir()
    all_messages = repr([messages for messages, _ in client.calls])
    assert "secret_ground_truth" not in all_messages
    assert "NEVER_SHOW" not in all_messages
    assert env.evaluate_calls == 0


class TerminalAgent(Agent):
    def __init__(self):
        super().__init__(FakeClient([]), AgentConfig())
        self.received = []

    def predict(self, instruction, obs):
        return AgentStep(raw_response="done", actions=["DONE"], done=True)

    def on_feedback(self, feedback):
        super().on_feedback(feedback)
        self.received.append(feedback)


class TwoEpisodeReward:
    def __init__(self):
        self.config = arm_config(actor_steps_per_episode=1, max_episodes=3)
        self.calls = 0

    def plan(self, task, initial, directory):
        return VerificationPlan("finish", ["finished"])

    def verify(self, **kwargs):
        self.calls += 1
        verdict = "failed" if self.calls == 1 else "success"
        return VerificationResult(
            verdict=verdict,
            rationale="fix it" if verdict == "failed" else "done",
            feedback="specific feedback" if verdict == "failed" else "complete",
            checklist=["finished"],
            observation=kwargs["current"],
        )


def test_feedback_loop_intercepts_done_and_retries_without_evaluator(tmp_path) -> None:
    task = TaskSpec(
        id="loop",
        instruction="finish",
        raw={"evaluator": {"expected": "hidden"}},
    )
    env = InspectableNoop()
    agent = TerminalAgent()
    reward = TwoEpisodeReward()
    recorder = TrajectoryRecorder(tmp_path, task)
    loop = AgenticFeedbackLoop(
        {"primary": agent},
        env,
        LoopConfig(max_steps=3, sleep_after_action=0, output_dir=tmp_path),
        recorder,
        reward_model=reward,  # type: ignore[arg-type]
    )

    result = loop.run(task)

    assert result.status == "completed"
    assert result.episodes == 2
    assert "specific feedback" in agent.received
    assert env.actions == []  # DONE was intercepted instead of sent to OSWorld
    assert env.evaluate_calls == 0

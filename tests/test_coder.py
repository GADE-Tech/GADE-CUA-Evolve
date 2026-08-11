from copy import deepcopy

import pytest

from gade_cua_evolve.agents import CoderAgent
from gade_cua_evolve.config import CoderConfig, EnvConfig, LLMConfig
from gade_cua_evolve.envs import CodeExecutionResult, NoopEnv, OSWorldEnv
from gade_cua_evolve.llm import Client, LLMResponse, ToolCall


class FakeClient(Client):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, **overrides):
        self.calls.append((deepcopy(list(messages)), deepcopy(overrides)))
        return self.responses.pop(0)


def response(name: str | None = None, **arguments) -> LLMResponse:
    calls = () if name is None else (ToolCall(f"call-{name}", name, arguments),)
    return LLMResponse(text="", tool_calls=calls)


def config(**overrides) -> CoderConfig:
    return CoderConfig(
        llm=LLMConfig(),
        max_rounds=overrides.pop("max_rounds", 5),
        command_timeout=overrides.pop("command_timeout", 7),
        max_output_chars=overrides.pop("max_output_chars", 1000),
        **overrides,
    )


def test_coder_runs_python_and_bash_then_finishes() -> None:
    client = FakeClient(
        [
            response("run_python", code="print('one')"),
            response("run_bash", code="printf two"),
            response("finish", summary="Updated the file", proof="one and two"),
        ]
    )
    executions = []

    def executor(language, code, timeout):
        executions.append((language, code, timeout))
        return CodeExecutionResult(language, "success", output=f"ok:{language}")

    result = CoderAgent(client, config()).execute("original", "subtask", None, executor)

    assert result.completion_reason == "DONE"
    assert result.rounds == 3
    assert [item[0] for item in executions] == ["python", "bash"]
    assert all(item[2] == 7 for item in executions)
    assert "Proof: one and two" in result.summary
    assert client.calls[1][0][-1]["role"] == "tool"
    assert "Never use code to impersonate" in client.calls[0][0][0]["content"]
    assert "task-specific content and transformation" in client.calls[0][0][0]["content"]


def test_invalid_and_failed_calls_are_returned_for_retry() -> None:
    invalid = LLMResponse(
        text="",
        tool_calls=(
            ToolCall("one", "run_python", {"code": "1"}),
            ToolCall("two", "run_bash", {"code": "true"}),
        ),
    )
    client = FakeClient(
        [
            invalid,
            response("unknown", code="x"),
            response("run_python", code="raise RuntimeError()"),
            response("run_python", code="print('recovered')"),
            response("finish", summary="Recovered", proof="verified output"),
        ]
    )

    def executor(language, code, timeout):
        if "raise" in code:
            return CodeExecutionResult(language, "error", error="execution failed")
        return CodeExecutionResult(language, "success", output="recovered")

    result = CoderAgent(client, config()).execute("original", "subtask", None, executor)

    assert result.completion_reason == "DONE"
    assert result.execution_history[0]["status"] == "invalid"
    assert result.execution_history[1]["error"] == "unknown coder tool: unknown"
    assert result.execution_history[2]["result"]["error"] == "execution failed"


def test_coder_redacts_and_truncates_logged_values() -> None:
    secret = "super-secret-password"
    long_output = secret + ("x" * 2000)
    client = FakeClient(
        [
            response("run_bash", code=f"printf {secret}"),
            response("finish", summary=f"used {secret}", proof=long_output),
        ]
    )

    def executor(language, code, timeout):
        return CodeExecutionResult(language, "success", output=long_output)

    result = CoderAgent(client, config(max_output_chars=1000), secrets=(secret,)).execute(
        "original", "subtask", None, executor
    )
    serialized = str(result.metadata())

    assert secret not in serialized
    assert "<redacted>" in serialized
    assert "truncated" in serialized


def test_coder_stops_at_round_limit_without_execution() -> None:
    client = FakeClient([response(), response()])
    result = CoderAgent(client, config(max_rounds=2)).execute(
        "original",
        "subtask",
        None,
        lambda *_: (_ for _ in ()).throw(AssertionError("must not execute")),
    )

    assert result.completion_reason == "MAX_ROUNDS"
    assert result.rounds == 2
    assert result.error_cause == "expected one tool call, received 0"


def test_finish_requires_a_successful_final_check() -> None:
    client = FakeClient(
        [
            response("finish", summary="Claimed done", proof="unverified"),
            response("run_bash", code="test -f /tmp/result"),
            response("finish", summary="Done", proof="test exited successfully"),
        ]
    )

    result = CoderAgent(client, config()).execute(
        "original",
        "subtask",
        None,
        lambda language, *_: CodeExecutionResult(language, "success"),
    )

    assert result.completion_reason == "DONE"
    assert result.rounds == 3
    assert result.execution_history[0]["status"] == "invalid"
    assert "final successful execution" in result.execution_history[0]["error"]


def test_noop_environment_refuses_code_execution() -> None:
    with pytest.raises(NotImplementedError, match="does not support VM code execution"):
        NoopEnv(EnvConfig()).run_code("python", "print('must not run on host')")


def test_osworld_python_execution_uses_bounded_guest_wrapper() -> None:
    calls = []

    class Controller:
        def run_bash_script(self, code, timeout):
            calls.append((code, timeout))
            return {"status": "success", "output": "checked"}

    adapter = object.__new__(OSWorldEnv)
    adapter.env = type("Desktop", (), {"controller": Controller()})()

    result = adapter.run_code("python", "print('inside guest')", timeout=9)

    assert result.status == "success"
    assert result.output == "checked"
    assert calls[0][1] == 14
    assert "setsid python3" in calls[0][0]
    assert "deadline=$((SECONDS + 9))" in calls[0][0]
    assert "print('inside guest')" not in calls[0][0]

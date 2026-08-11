from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image

from gade_cua_evolve.agents import GTA15Agent
from gade_cua_evolve.agents.grounding import Grounder
from gade_cua_evolve.config import AgentConfig
from gade_cua_evolve.envs import Observation, StepOutcome
from gade_cua_evolve.llm import Client, LLMResponse, ToolCall


def screenshot(width: int = 200, height: int = 100) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return output.getvalue()


class FakeGeminiClient(Client):
    model = "gemini-test"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[dict], dict]] = []

    def complete(self, messages, **overrides):
        self.calls.append((deepcopy(list(messages)), deepcopy(overrides)))
        if "response_schema" in overrides:
            return LLMResponse(text='{"x": 500, "y": 250}')
        return self.responses.pop(0)

    @property
    def main_calls(self) -> list[tuple[list[dict], dict]]:
        return [call for call in self.calls if "tools" in call[1]]


class FakeGrounder(Grounder):
    def locate(self, screenshot: bytes, description: str) -> tuple[float, float]:
        return 0.5, 0.25


def gta_agent(client: Client, **config) -> GTA15Agent:
    return GTA15Agent(client, AgentConfig(name="gta15", **config), FakeGrounder())


def call(name: str, **arguments) -> LLMResponse:
    return LLMResponse(
        text="Use the selected tool.",
        tool_calls=(ToolCall(id=f"call-{name}", name=name, arguments=arguments),),
    )


def test_each_valid_decision_uses_one_main_model_request() -> None:
    client = FakeGeminiClient([call("hotkey", keys=["ctrl", "l"])])
    agent = gta_agent(client, internal_retries=3)

    result = agent.predict("Focus the address bar", Observation(screenshot=screenshot()))

    assert len(client.main_calls) == 1
    assert result.actions == ["import pyautogui; pyautogui.hotkey('ctrl', 'l')"]


def test_feedback_before_first_prediction_keeps_system_message_first() -> None:
    client = FakeGeminiClient([call("hotkey", keys=["ctrl", "l"])])
    agent = gta_agent(client)
    agent.on_feedback("Check the exact setting")

    agent.predict("Focus the address bar", Observation(screenshot=screenshot()))

    messages = client.main_calls[0][0]
    assert messages[0]["role"] == "system"
    assert "Check the exact setting" in str(messages[-1]["content"])


def test_grounding_and_action_result_close_the_context_loop() -> None:
    image = screenshot()
    client = FakeGeminiClient(
        [
            call("click", instruction="the button in the center"),
            LLMResponse(text="TERMINATE"),
        ]
    )
    agent = gta_agent(client)

    first = agent.predict("Click the button", Observation(screenshot=image))
    assert "pyautogui.click(100, 25" in first.actions[0]
    assert len(client.main_calls) == 1
    assert len(client.calls) == 1  # grounding uses its own injected model/client

    agent.on_action_result(
        first,
        first.actions[0],
        StepOutcome(Observation(screenshot=image), info={"executed": True}),
    )
    second = agent.predict("Click the button", Observation(screenshot=image))

    assert second.actions == ["DONE"]
    assert len(client.main_calls) == 2
    second_messages = client.main_calls[-1][0]
    assert any(message["role"] == "tool" for message in second_messages)
    assert any(
        message["role"] == "user"
        and isinstance(message["content"], list)
        and any(part.get("type") == "image_url" for part in message["content"])
        for message in second_messages
    )


def test_missing_tool_call_retries_then_waits() -> None:
    client = FakeGeminiClient([LLMResponse(text="not actionable"), LLMResponse(text="still no call")])
    agent = gta_agent(client, internal_retries=2)

    result = agent.predict("Do something", Observation(screenshot=screenshot()))

    assert len(client.main_calls) == 2
    assert result.actions == ["WAIT"]
    assert result.metadata["error"] == "missing_tool_call"


def test_multiple_tool_calls_are_rejected_and_retried() -> None:
    invalid = LLMResponse(
        text="two actions",
        tool_calls=(
            ToolCall(id="one", name="hotkey", arguments={"keys": ["ctrl", "a"]}),
            ToolCall(id="two", name="hotkey", arguments={"keys": ["ctrl", "c"]}),
        ),
    )
    client = FakeGeminiClient([invalid, call("hotkey", keys=["ctrl", "a"])])
    agent = gta_agent(client, internal_retries=2)

    result = agent.predict("Select all", Observation(screenshot=screenshot()))

    assert len(client.main_calls) == 2
    assert result.actions == ["import pyautogui; pyautogui.hotkey('ctrl', 'a')"]
    assert "Return exactly one" in str(client.main_calls[1][0][-1]["content"])


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Task complete. TERMINATE", "DONE"), ("Blocked. INFEASIBLE", "FAIL")],
)
def test_terminal_responses(text: str, expected: str) -> None:
    client = FakeGeminiClient([LLMResponse(text=text)])
    agent = gta_agent(client)

    result = agent.predict("Finish", Observation(screenshot=screenshot()))

    assert len(client.main_calls) == 1
    assert result.actions == [expected]
    assert result.done is True

from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image

from gade_cua_evolve.agents.grounding import GroundingError, ToolCallingGrounder
from gade_cua_evolve.config import GrounderConfig
from gade_cua_evolve.llm import Client, LLMResponse, ToolCall
from gade_cua_evolve.llm.openai_client import OpenAICompatClient


def screenshot(width=200, height=100) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), "white").save(output, "PNG")
    return output.getvalue()


class FakeClient(Client):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, **overrides):
        self.calls.append((deepcopy(messages), deepcopy(overrides)))
        return self.responses.pop(0)


def response(name, **arguments):
    return LLMResponse(
        text="",
        tool_calls=(ToolCall(id=f"call-{name}", name=name, arguments=arguments),),
    )


def config(**updates):
    return GrounderConfig(
        provider="openai",
        model="grounder",
        api_key_env="TEST_KEY",
        semantic_retries=1,
        **updates,
    )


def test_locate_crop_confirm_protocol_is_provider_neutral() -> None:
    client = FakeClient([response("locate", x=500, y=250), response("confirm", status="success")])
    grounder = ToolCallingGrounder(client, config())

    assert grounder.locate(screenshot(), "center button") == (0.5, 0.25)
    assert len(client.calls) == 2
    second_messages = client.calls[1][0]
    assert any(message["role"] == "tool" for message in second_messages)
    assert any(
        message["role"] == "user"
        and isinstance(message["content"], list)
        and any(part.get("type") == "image_url" for part in message["content"])
        for message in second_messages
    )


def test_grounder_can_refine_and_report_missing_element() -> None:
    refine = FakeClient(
        [
            response("locate", x=100, y=100),
            response("confirm", status="continue"),
            response("locate", x=800, y=600),
            response("confirm", status="success"),
        ]
    )
    assert ToolCallingGrounder(refine, config()).locate(screenshot(), "target") == (0.8, 0.6)

    missing = FakeClient(
        [response("locate", x=100, y=100), response("confirm", status="failed", feedback="gone")]
    )
    with pytest.raises(GroundingError, match="gone"):
        ToolCallingGrounder(missing, config()).locate(screenshot(), "target")


def test_openai_translation_normalizes_tool_history() -> None:
    translated = OpenAICompatClient._to_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "x", "name": "locate", "arguments": {"x": 1, "y": 2}}],
            },
            {
                "role": "tool",
                "tool_call_id": "x",
                "name": "locate",
                "content": {"located": True},
            },
        ]
    )
    assert translated[0]["tool_calls"][0]["function"]["arguments"] == '{"x": 1, "y": 2}'
    assert translated[1]["content"] == '{"located": true}'

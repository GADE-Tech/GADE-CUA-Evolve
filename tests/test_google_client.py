import base64
from types import SimpleNamespace

from google.genai import types

from gade_cua_evolve.agents.gta15_tools import CUA_TOOLS
from gade_cua_evolve.llm.google_client import GoogleGenAIClient


class FakeModels:
    def __init__(self) -> None:
        self.request = None

    def generate_content(self, **request):
        self.request = request
        parts = [
            types.Part.from_text(text="Click the requested control."),
            types.Part.from_function_call(name="click", args={"instruction": "the blue button"}),
        ]
        parts[1].thought_signature = b"response-signature"
        return SimpleNamespace(
            candidates=[SimpleNamespace(content=types.Content(role="model", parts=parts))],
            usage_metadata=None,
            model_version="gemini-test-version",
        )


def google_client() -> tuple[GoogleGenAIClient, FakeModels]:
    models = FakeModels()
    client = object.__new__(GoogleGenAIClient)
    client.model = "gemini-test"
    client.temperature = 0.0
    client.top_p = 0.9
    client.max_tokens = 1024
    client.max_retries = 1
    client.client = SimpleNamespace(models=models)
    return client, models


def test_generate_content_translates_tools_and_function_history() -> None:
    client, models = google_client()
    response = client.complete(
        [
            {"role": "system", "content": "Use one GUI tool."},
            {"role": "user", "content": "Click it."},
            {
                "role": "assistant",
                "content": [],
                "tool_calls": [
                    {
                        "id": "old-call",
                        "name": "wait",
                        "arguments": {"time": 1},
                        "thought_signature": base64.b64encode(b"history-signature").decode(),
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "old-call",
                "name": "wait",
                "content": {"result": "finished"},
            },
        ],
        tools=CUA_TOOLS,
    )

    assert models.request is not None
    assert models.request["model"] == "gemini-test"
    assert models.request["config"].system_instruction == "Use one GUI tool."
    assert len(models.request["config"].tools[0].function_declarations) == len(CUA_TOOLS)
    assert [content.role for content in models.request["contents"]] == ["user", "model", "user"]
    assert models.request["contents"][1].parts[0].thought_signature == b"history-signature"
    assert response.text == "Click the requested control."
    assert response.tool_calls[0].name == "click"
    assert response.tool_calls[0].arguments == {"instruction": "the blue button"}
    assert base64.b64decode(response.tool_calls[0].thought_signature) == b"response-signature"


def test_invalid_thought_signature_is_rejected() -> None:
    client, _ = google_client()

    try:
        client.complete(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "bad-call",
                            "name": "wait",
                            "arguments": {},
                            "thought_signature": "not valid base64!",
                        }
                    ],
                }
            ]
        )
    except ValueError as exc:
        assert str(exc) == "Invalid base64 Gemini thought signature"
    else:
        raise AssertionError("Expected invalid thought signature to fail")

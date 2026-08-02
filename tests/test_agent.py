import json

import pytest

from gade_cua_evolve.agents.image import smart_resize
from gade_cua_evolve.agents.parsing import parse_response
from gade_cua_evolve.agents.state import AgentState


def response(action: str, **arguments) -> str:
    payload = {"name": "computer_use", "arguments": {"action": action, **arguments}}
    return f"Action: test\n<tool_call>\n{json.dumps(payload)}\n</tool_call>"


@pytest.mark.parametrize(
    ("action", "arguments", "expected"),
    [
        ("left_click", {"coordinate": [500, 500]}, "pyautogui.click(960, 540)"),
        ("right_click", {"coordinate": [500, 500]}, "pyautogui.rightClick(960, 540)"),
        ("middle_click", {"coordinate": [500, 500]}, "pyautogui.middleClick(960, 540)"),
        ("double_click", {"coordinate": [500, 500]}, "pyautogui.doubleClick(960, 540)"),
        ("mouse_move", {"coordinate": [500, 500]}, "pyautogui.moveTo(960, 540)"),
        ("scroll", {"pixels": -3}, "pyautogui.scroll(-3)"),
        ("key", {"keys": ["ctrl", "a"]}, "pyautogui.hotkey('ctrl', 'a')"),
        ("wait", {}, "WAIT"),
        ("terminate", {}, "DONE"),
    ],
)
def test_parse_relative_actions(action, arguments, expected) -> None:
    step = parse_response(response(action, **arguments), "relative", (1920, 1080), (960, 544))
    assert expected in step.actions


def test_parse_absolute_coordinates() -> None:
    step = parse_response(
        response("left_click", coordinate=[480, 272]),
        "absolute",
        (1920, 1080),
        (960, 544),
    )
    assert step.actions == ["pyautogui.click(960, 540)"]


def test_malformed_response_is_safe() -> None:
    assert parse_response("<tool_call>{bad}</tool_call>", "relative", (1, 1), (1, 1)).actions == []


def test_state_history_alignment() -> None:
    state = AgentState(responses=["r1", "r2"], screenshots=["s1", "s2", "current"])
    assert state.history_window(1) == [("s2", "r2")]
    assert state.history_window(5) == [("s1", "r1"), ("s2", "r2")]


def test_smart_resize_bounds() -> None:
    height, width = smart_resize(1080, 1920, factor=32, max_pixels=1_000_000)
    assert height % 32 == width % 32 == 0
    assert height * width <= 1_000_000

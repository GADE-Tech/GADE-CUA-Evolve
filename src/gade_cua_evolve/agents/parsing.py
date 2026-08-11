"""Parse Qwen tool calls into OSWorld pyautogui actions."""

from __future__ import annotations

import json
import re
from typing import Any

from .base import AgentStep


def _coordinate(
    values: list[float],
    coordinate_type: str,
    original: tuple[int, int],
    processed: tuple[int, int],
) -> tuple[int, int]:
    x, y = values
    original_w, original_h = original
    if coordinate_type == "absolute":
        processed_w, processed_h = processed
        return int(x * original_w / processed_w), int(y * original_h / processed_h)
    return int(x * original_w / 999), int(y * original_h / 999)


def _clean_keys(keys: Any) -> list[str]:
    if not isinstance(keys, list):
        keys = [keys]
    cleaned = []
    for key in keys:
        value = str(key).strip()
        value = re.sub(r"^keys=\[", "", value)
        value = value.strip("[]'\" ")
        if value:
            cleaned.append(value)
    return cleaned


def tool_call_to_actions(
    call: dict[str, Any],
    coordinate_type: str,
    original: tuple[int, int],
    processed: tuple[int, int],
) -> list[str]:
    if call.get("name") != "computer_use":
        return []
    args = call.get("arguments", {})
    action = args.get("action")
    point = lambda: _coordinate(args["coordinate"], coordinate_type, original, processed)
    if action == "left_click":
        return (
            [f"pyautogui.click({point()[0]}, {point()[1]})"]
            if "coordinate" in args
            else ["pyautogui.click()"]
        )
    if action == "right_click":
        return (
            [f"pyautogui.rightClick({point()[0]}, {point()[1]})"]
            if "coordinate" in args
            else ["pyautogui.rightClick()"]
        )
    if action == "middle_click":
        return (
            [f"pyautogui.middleClick({point()[0]}, {point()[1]})"]
            if "coordinate" in args
            else ["pyautogui.middleClick()"]
        )
    if action == "double_click":
        return (
            [f"pyautogui.doubleClick({point()[0]}, {point()[1]})"]
            if "coordinate" in args
            else ["pyautogui.doubleClick()"]
        )
    if action == "mouse_move":
        return [f"pyautogui.moveTo({point()[0]}, {point()[1]})"]
    if action == "left_click_drag":
        x, y = point()
        return [f"pyautogui.dragTo({x}, {y}, duration={args.get('duration', 0.5)})"]
    if action == "scroll":
        return [f"pyautogui.scroll({args.get('pixels', 0)})"]
    if action == "key":
        keys = _clean_keys(args.get("keys", []))
        quoted = ", ".join(repr(key) for key in keys)
        return [f"pyautogui.hotkey({quoted})" if len(keys) > 1 else f"pyautogui.press({quoted})"]
    if action == "type":
        lines = str(args.get("text", "")).split("\n")
        result: list[str] = []
        for index, line in enumerate(lines):
            if line:
                result.append(f"pyautogui.typewrite({line!r}, interval=0.03)")
            if index < len(lines) - 1:
                result.append("pyautogui.press('enter')")
        return result
    if action == "wait":
        return ["WAIT"]
    if action == "terminate":
        return ["DONE" if args.get("status") != "failure" else "FAIL"]
    return []


def parse_response(
    response: str,
    coordinate_type: str,
    original: tuple[int, int],
    processed: tuple[int, int],
) -> AgentStep:
    instruction_match = re.search(r"(?im)^Action:\s*(.+)$", response or "")
    low_level = instruction_match.group(1).strip() if instruction_match else ""
    calls = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", response or "", re.DOTALL)
    if not calls:
        calls = re.findall(r"(?m)^\s*(\{.*\"arguments\".*\})\s*$", response or "")
    actions: list[str] = []
    for raw in calls:
        try:
            actions.extend(
                tool_call_to_actions(json.loads(raw), coordinate_type, original, processed)
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    if not low_level and actions:
        low_level = f"Perform {actions[0]}"
    thought_match = re.search(r"<think>\s*(.*?)\s*</think>", response or "", re.DOTALL)
    thought = thought_match.group(1).strip() if thought_match else ""
    return AgentStep(
        raw_response=response,
        thought=thought,
        low_level_instruction=low_level,
        actions=actions,
        done=any(action in {"DONE", "FAIL"} for action in actions),
    )

from __future__ import annotations

import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "export_blog_trajectory.py"
SPEC = spec_from_file_location("export_blog_trajectory", SCRIPT_PATH)
assert SPEC and SPEC.loader
EXPORTER = module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORTER)
export_run = EXPORTER.export_run
parse_action = EXPORTER.parse_action


def _write_image(path: Path, color: str = "navy") -> None:
    Image.new("RGB", (200, 100), color).save(path)


def _make_run(tmp_path: Path, *, with_arm: bool = True) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    result = {
        "task": {"id": "private-id", "instruction": "Open a settings window.", "raw": {"evaluator": "secret-gt"}},
        "config": {
            "env": {"screen_size": [1000, 500], "client_password": "do-not-export"},
            "llm": {"api_key": "do-not-export"},
        },
        "arm_verdict": "success" if with_arm else None,
        "arm_feedback": ["private feedback"],
        "episodes": 1 if with_arm else 0,
    }
    (run / "result.json").write_text(json.dumps(result), encoding="utf-8")
    rows = [
        {
            "action_step": 1,
            "action": "import pyautogui; pyautogui.click(1200, -25, clicks=1)",
            "low_level_instruction": 'click({"instruction": "Choose Settings"})',
            "thought": "private thought",
            "raw_response": "private response",
        },
        {"action_step": 2, "action": "pyautogui.hotkey('ctrl', 'l')", "low_level_instruction": ""},
        {"action_step": 3, "action": "pyautogui.write('hello')", "low_level_instruction": "Type hello"},
        {"action_step": 4, "action": "WAIT", "low_level_instruction": ""},
    ]
    (run / "traj.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    _write_image(run / "initial_screenshot.png")
    for index in range(1, 5):
        _write_image(run / f"step_{index:04d}.png", color="teal")
    if with_arm:
        (run / "arm" / "episode_01").mkdir(parents=True)
        (run / "arm" / "plan.json").write_text(
            json.dumps({"task_understanding": "private", "checklist": ["Settings is visible."]}),
            encoding="utf-8",
        )
        (run / "arm" / "episode_01" / "judge_traj.jsonl").write_text(
            json.dumps({"tool": "terminate", "rationale": "Settings is visible."}),
            encoding="utf-8",
        )
    return run


def test_parse_action_types_and_normalized_click() -> None:
    click = {"action": "pyautogui.click(250, 125)", "low_level_instruction": "Click item"}
    kind, label, point = parse_action(click, width=1000, height=500)
    assert (kind, label, point) == ("click", "Click item", {"x": 0.25, "y": 0.25})
    assert parse_action({"action": "pyautogui.hotkey('ctrl', 'l')"}, width=1, height=1)[0] == "hotkey"
    assert parse_action({"action": "pyautogui.write('abc')"}, width=1, height=1)[0] == "type"
    assert parse_action({"action": "WAIT"}, width=1, height=1)[0] == "wait"


def test_export_filters_sensitive_fields_and_converts_images(tmp_path: Path) -> None:
    output = export_run(_make_run(tmp_path), "public-case", tmp_path / "out")
    payload = json.loads(output.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    assert set(payload) == {"id", "instruction", "frames", "arm"}
    assert payload["frames"][1]["point"] == {"x": 1.0, "y": 0.0}
    assert [frame["actionType"] for frame in payload["frames"]] == [
        "initial", "click", "hotkey", "type", "wait"
    ]
    assert payload["arm"]["checklist"] == ["Settings is visible."]
    assert payload["arm"]["continue"] is False
    assert "private thought" not in serialized
    assert "private response" not in serialized
    assert "do-not-export" not in serialized
    assert "secret-gt" not in serialized
    assert not any(str(tmp_path) in frame["image"] for frame in payload["frames"])
    assert Image.open(output.parent / "initial.webp").format == "WEBP"


def test_export_without_arm_data(tmp_path: Path) -> None:
    output = export_run(_make_run(tmp_path, with_arm=False), "no-arm", tmp_path / "out")
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "arm" not in payload

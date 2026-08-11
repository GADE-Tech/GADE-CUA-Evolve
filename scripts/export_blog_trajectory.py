"""Export a privacy-filtered trajectory bundle for the static research site."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image

CLICK_RE = re.compile(r"pyautogui\.click\(\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)")
HOTKEY_RE = re.compile(r"pyautogui\.hotkey\((.*?)\)")
TYPE_RE = re.compile(r"pyautogui\.(?:write|typewrite)\((.*?)\)")
WAIT_RE = re.compile(r"(?:time\.)?sleep\((\d+(?:\.\d+)?)\)")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path.name}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _normalize_point(x: float, y: float, width: int, height: int) -> dict[str, float]:
    if width <= 0 or height <= 0:
        raise ValueError("Screen dimensions must be positive")
    return {
        "x": round(max(0.0, min(1.0, x / width)), 10),
        "y": round(max(0.0, min(1.0, y / height)), 10),
    }


def _action_type(action: str) -> str:
    lowered = action.lower()
    if CLICK_RE.search(action):
        return "click"
    if HOTKEY_RE.search(action):
        return "hotkey"
    if TYPE_RE.search(action):
        return "type"
    if action.strip().upper() == "WAIT" or WAIT_RE.search(lowered):
        return "wait"
    if "scroll(" in lowered:
        return "scroll"
    return "action"


def _instruction_label(value: Any, action_type: str) -> str:
    text = str(value or "").strip()
    if text:
        match = re.match(r"\w+\((\{.*\})\)\s*$", text)
        if match:
            try:
                arguments = json.loads(match.group(1))
            except json.JSONDecodeError:
                arguments = None
            if isinstance(arguments, dict):
                instruction = str(arguments.get("instruction", "")).strip()
                if instruction:
                    return instruction
        return text[:240]
    return {
        "click": "Click the indicated point",
        "hotkey": "Press a keyboard shortcut",
        "type": "Type text",
        "wait": "Wait for the interface",
        "scroll": "Scroll the interface",
    }.get(action_type, "Execute an environment action")


def parse_action(
    row: dict[str, Any], *, width: int, height: int
) -> tuple[str, str, dict[str, float] | None]:
    action = str(row.get("action", ""))
    action_type = _action_type(action)
    label = _instruction_label(row.get("low_level_instruction"), action_type)
    point = None
    if action_type == "click" and (match := CLICK_RE.search(action)):
        point = _normalize_point(float(match.group(1)), float(match.group(2)), width, height)
    return action_type, label, point


def _save_webp(source: Path, destination: Path) -> None:
    with Image.open(source) as image:
        image = image.convert("RGB")
        if max(image.size) > 1440:
            image.thumbnail((1440, 1440), Image.Resampling.LANCZOS)
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, "WEBP", quality=78, method=6)


def _arm_payload(run_dir: Path, result: dict[str, Any]) -> dict[str, Any] | None:
    plan_path = run_dir / "arm" / "plan.json"
    verdict = result.get("arm_verdict")
    if not plan_path.exists() and not verdict:
        return None
    plan = _read_json(plan_path) if plan_path.exists() else {}
    episodes = int(result.get("episodes") or 0)
    rationale = ""
    if episodes:
        judge_path = run_dir / "arm" / f"episode_{episodes:02d}" / "judge_traj.jsonl"
        judge_rows = _read_jsonl(judge_path)
        if judge_rows:
            rationale = str(judge_rows[-1].get("rationale", "")).strip()
    if not rationale:
        feedback = result.get("arm_feedback")
        if isinstance(feedback, list) and feedback:
            rationale = str(feedback[-1]).strip()[:1200]
    return {
        "episode": episodes,
        "checklist": [str(item) for item in plan.get("checklist", []) if str(item).strip()],
        "verdict": str(verdict or "unknown"),
        "rationale": rationale,
        "continue": verdict == "failed",
    }


def export_run(run_dir: Path, case_id: str, out_dir: Path) -> Path:
    run_dir = run_dir.resolve()
    result_path = run_dir / "result.json"
    trajectory_path = run_dir / "traj.jsonl"
    if not result_path.exists() or not trajectory_path.exists():
        raise FileNotFoundError("Run directory must contain result.json and traj.jsonl")

    result = _read_json(result_path)
    rows = _read_jsonl(trajectory_path)
    screen_size = result.get("config", {}).get("env", {}).get("screen_size", [1920, 1080])
    width, height = int(screen_size[0]), int(screen_size[1])
    case_dir = out_dir / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    initial_source = run_dir / "initial_screenshot.png"
    if not initial_source.exists():
        raise FileNotFoundError("Run directory is missing initial_screenshot.png")
    _save_webp(initial_source, case_dir / "initial.webp")
    frames: list[dict[str, Any]] = [
        {
            "step": 0,
            "image": "initial.webp",
            "actionType": "initial",
            "actionLabel": "Initial desktop state",
        }
    ]

    for index, row in enumerate(rows, start=1):
        action_step = int(row.get("action_step") or index)
        source = run_dir / f"step_{action_step:04d}.png"
        if not source.exists():
            continue
        filename = f"step-{index:02d}.webp"
        _save_webp(source, case_dir / filename)
        action_type, label, point = parse_action(row, width=width, height=height)
        frame: dict[str, Any] = {
            "step": index,
            "image": filename,
            "actionType": action_type,
            "actionLabel": label,
        }
        if point is not None:
            frame["point"] = point
        frames.append(frame)

    task = result.get("task", {})
    payload: dict[str, Any] = {
        "id": case_id,
        "instruction": str(task.get("instruction", "")).strip(),
        "frames": frames,
    }
    arm = _arm_payload(run_dir, result)
    if arm is not None:
        payload["arm"] = arm
    output = case_dir / "case.json"
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="Trajectory run directory")
    parser.add_argument("--id", required=True, help="Public case identifier")
    parser.add_argument("--out", type=Path, required=True, help="Output trajectories directory")
    args = parser.parse_args()
    print(export_run(args.run, args.id, args.out))


if __name__ == "__main__":
    main()

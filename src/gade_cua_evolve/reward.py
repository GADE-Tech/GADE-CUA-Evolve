"""Agentic reward model with live GUI, VM-code, and trajectory inspection."""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from gade_cua_evolve.agents.grounding import Grounder
from gade_cua_evolve.arm_prompts import (
    JUDGE_SYSTEM_PROMPT,
    PLAN_SYSTEM_PROMPT,
    TRAJECTORY_SYSTEM_PROMPT,
)
from gade_cua_evolve.config import ARMConfig, TaskPublicView
from gade_cua_evolve.envs import EnvAdapter, Observation
from gade_cua_evolve.llm import Client, LLMResponse, ToolCall

Verdict = Literal["success", "failed", "infeasible", "error"]


@dataclass(slots=True)
class VerificationPlan:
    task_understanding: str
    checklist: list[str]


@dataclass(slots=True)
class VerificationResult:
    verdict: Verdict
    rationale: str
    feedback: str
    checklist: list[str]
    evidence: list[dict[str, Any]] = field(default_factory=list)
    judge_steps: int = 0
    observation: Observation | None = None


@dataclass(slots=True)
class TrajectoryItem:
    step: int
    action: str
    thought: str
    screenshot: bytes | None = None


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "task_understanding": {"type": "string"},
        "checklist": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    },
    "required": ["task_understanding", "checklist"],
    "additionalProperties": False,
}

TRAJECTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["success", "failed", "infeasible"]},
        "trajectory_summary": {"type": "string"},
        "checklist_assessment": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "trajectory_summary", "checklist_assessment", "rationale"],
    "additionalProperties": False,
}

JUDGE_TOOLS = [
    {
        "name": "inspect_click",
        "description": "Click a visible element solely to reveal existing verification evidence.",
        "parameters": {
            "type": "object",
            "properties": {"instruction": {"type": "string"}},
            "required": ["instruction"],
        },
    },
    {
        "name": "inspect_scroll",
        "description": "Scroll an existing view to reveal verification evidence.",
        "parameters": {
            "type": "object",
            "properties": {
                "instruction": {"type": "string"},
                "clicks": {"type": "integer"},
            },
            "required": ["instruction", "clicks"],
        },
    },
    {
        "name": "inspect_hotkey",
        "description": "Use a navigation-only keyboard shortcut to reveal existing evidence.",
        "parameters": {
            "type": "object",
            "properties": {"keys": {"type": "array", "items": {"type": "string"}}},
            "required": ["keys"],
        },
    },
    {
        "name": "switch_application",
        "description": "Focus an already-open application by its wmctrl class/name.",
        "parameters": {
            "type": "object",
            "properties": {"app": {"type": "string"}},
            "required": ["app"],
        },
    },
    {
        "name": "wait",
        "description": "Wait briefly for an existing UI state to settle.",
        "parameters": {
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
            "required": ["seconds"],
        },
    },
    {
        "name": "inspect_with_code",
        "description": "Run read-only Python or Bash inside the disposable VM and return stdout.",
        "parameters": {
            "type": "object",
            "properties": {
                "language": {"type": "string", "enum": ["python", "bash"]},
                "code": {"type": "string"},
                "rationale": {"type": "string"},
            },
            "required": ["language", "code", "rationale"],
        },
    },
    {
        "name": "trajectory_check",
        "description": "Run a separate read-only verifier pass over actor trajectory evidence.",
        "parameters": {
            "type": "object",
            "properties": {"rationale": {"type": "string"}},
            "required": ["rationale"],
        },
    },
    {
        "name": "terminate",
        "description": "Return the final verification verdict.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["success", "failed", "infeasible"],
                },
                "rationale": {"type": "string"},
            },
            "required": ["status", "rationale"],
        },
    },
]


def _image_part(image: bytes) -> dict[str, Any]:
    encoded = base64.b64encode(image).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}


def _assistant_message(response: LLMResponse) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": response.text,
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": dict(call.arguments)}
            for call in response.tool_calls
        ],
    }


def _json_value(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.splitlines()[1:-1]).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Response does not contain a JSON object")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise TypeError("Expected a JSON object")
    return value


def _truncate(value: str, limit: int = 8192) -> str:
    if len(value) <= limit:
        return value
    half = limit // 2
    return f"{value[:half]}\n...[truncated {len(value) - limit} chars]...\n{value[-half:]}"


class AgenticRewardModel:
    def __init__(
        self,
        llm: Client,
        grounder: Grounder,
        config: ARMConfig,
    ) -> None:
        self.llm = llm
        self.grounder = grounder
        self.config = config

    def plan(
        self,
        task: TaskPublicView,
        initial: Observation,
        directory: Path,
    ) -> VerificationPlan:
        if not initial.screenshot:
            raise ValueError("ARM planning requires the initial screenshot")
        response = self.llm.complete(
            [
                {"role": "system", "content": PLAN_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Original task:\n{task.instruction}"},
                        _image_part(initial.screenshot),
                    ],
                },
            ],
            response_schema=PLAN_SCHEMA,
            temperature=0.0,
        )
        value = _json_value(response.text)
        checklist = [str(item).strip() for item in value.get("checklist", []) if str(item).strip()]
        if not checklist:
            raise ValueError("ARM planner returned an empty checklist")
        plan = VerificationPlan(str(value.get("task_understanding", "")).strip(), checklist)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "plan.json").write_text(
            json.dumps(asdict(plan), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return plan

    def verify(
        self,
        *,
        task: TaskPublicView,
        plan: VerificationPlan,
        initial: Observation,
        current: Observation,
        trajectory: list[TrajectoryItem],
        env: EnvAdapter,
        directory: Path,
    ) -> VerificationResult:
        if not initial.screenshot or not current.screenshot:
            return self._error(plan, "ARM verification requires screenshots", current)
        directory.mkdir(parents=True, exist_ok=True)
        evidence: list[dict[str, Any]] = []
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": self._judge_instruction(task, plan, trajectory),
                    },
                    {"type": "text", "text": "Initial environment screenshot:"},
                    _image_part(initial.screenshot),
                    {"type": "text", "text": "Current environment screenshot:"},
                    _image_part(current.screenshot),
                ],
            },
        ]
        observation = current
        log_path = directory / "judge_traj.jsonl"
        for step in range(self.config.max_judge_steps):
            response = self.llm.complete(messages, tools=JUDGE_TOOLS, temperature=0.0)
            if len(response.tool_calls) != 1:
                return self._error(
                    plan,
                    f"ARM judge returned {len(response.tool_calls)} tool calls; expected one",
                    observation,
                    evidence,
                    step + 1,
                )
            call = response.tool_calls[0]
            messages.append(_assistant_message(response))
            payload = self._execute_tool(
                call, observation, task, plan, trajectory, env, directory, step
            )
            if payload.get("observation") is not None:
                observation = payload.pop("observation")
            record = {"step": step + 1, "tool": call.name, "arguments": dict(call.arguments), **payload}
            evidence.append(record)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            if call.name == "terminate":
                status = str(call.arguments.get("status", "failed"))
                verdict: Verdict = status if status in {"success", "failed", "infeasible"} else "error"
                rationale = str(call.arguments.get("rationale", "")).strip()
                return VerificationResult(
                    verdict=verdict,
                    rationale=rationale,
                    feedback=self._feedback(verdict, plan, rationale),
                    checklist=plan.checklist,
                    evidence=evidence,
                    judge_steps=step + 1,
                    observation=observation,
                )
            tool_result = {key: value for key, value in payload.items() if key != "screenshot"}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": tool_result,
                }
            )
            if observation.screenshot and payload.get("gui_action"):
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Screenshot after verifier navigation:"},
                            _image_part(observation.screenshot),
                        ],
                    }
                )
        return self._error(
            plan,
            "ARM judge exceeded its step limit without a verdict",
            observation,
            evidence,
            self.config.max_judge_steps,
        )

    def _execute_tool(
        self,
        call: ToolCall,
        observation: Observation,
        task: TaskPublicView,
        plan: VerificationPlan,
        trajectory: list[TrajectoryItem],
        env: EnvAdapter,
        directory: Path,
        step: int,
    ) -> dict[str, Any]:
        args = dict(call.arguments)
        if call.name == "terminate":
            return {"status": args.get("status"), "rationale": args.get("rationale", "")}
        if call.name == "inspect_with_code":
            if not self.config.enable_code_inspection:
                return {"status": "disabled", "error": "Code inspection is disabled"}
            return self._code_inspection(env, directory, step, args)
        if call.name == "trajectory_check":
            if not self.config.enable_trajectory_check:
                return {"status": "disabled", "error": "Trajectory check is disabled"}
            return self._trajectory_check(task, plan, trajectory, directory, step)
        if not observation.screenshot:
            return {"status": "error", "error": "No screenshot for GUI inspection"}
        try:
            action = self._gui_action(call, observation.screenshot)
            outcome = env.inspect_gui(action, self.config.judge_pause)
            return {
                "status": "success",
                "gui_action": action,
                "info": outcome.info,
                "observation": outcome.observation,
            }
        except Exception as exc:  # noqa: BLE001 - errors become verifier evidence
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    def _gui_action(self, call: ToolCall, screenshot: bytes) -> str:
        args = dict(call.arguments)
        if call.name in {"inspect_click", "inspect_scroll"}:
            x_norm, y_norm = self.grounder.locate(screenshot, str(args["instruction"]))
            from io import BytesIO

            from PIL import Image

            with Image.open(BytesIO(screenshot)) as image:
                width, height = image.size
            x, y = round(x_norm * width), round(y_norm * height)
            if call.name == "inspect_click":
                return f"import pyautogui; pyautogui.click({x}, {y})"
            return (
                f"import pyautogui; pyautogui.moveTo({x}, {y}); "
                f"pyautogui.vscroll({int(args['clicks'])})"
            )
        if call.name == "inspect_hotkey":
            keys = ", ".join(repr(str(key)) for key in args.get("keys", []))
            return f"import pyautogui; pyautogui.hotkey({keys})"
        if call.name == "switch_application":
            app = str(args["app"])
            return (
                "import subprocess,difflib; lines=subprocess.check_output(['wmctrl','-lx'])"
                ".decode().splitlines(); titles=[line.split(None,4)[2] for line in lines]; "
                f"matches=difflib.get_close_matches({app!r},titles,n=1,cutoff=0.1); "
                "window_id=next(line.split()[0] for line in lines if matches and matches[0] in line); "
                "subprocess.run(['wmctrl','-ia',window_id])"
            )
        if call.name == "wait":
            return f"import time; time.sleep({min(10.0, max(0.0, float(args['seconds'])))})"
        raise ValueError(f"Unknown verifier GUI tool {call.name!r}")

    def _code_inspection(
        self, env: EnvAdapter, directory: Path, step: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        inspection_dir = directory / "inspections" / f"step_{step + 1:02d}_{uuid.uuid4().hex[:8]}"
        inspection_dir.mkdir(parents=True, exist_ok=True)
        language, code = str(args.get("language", "")), str(args.get("code", ""))
        extension = "py" if language == "python" else "sh"
        (inspection_dir / f"inspection.{extension}").write_text(code, encoding="utf-8")
        started = time.monotonic()
        result = env.run_inspection(language, code, self.config.code_timeout)
        payload = {
            "status": result.status,
            "language": language,
            "rationale": str(args.get("rationale", "")),
            "returncode": result.returncode,
            "stdout": _truncate(result.output),
            "stderr": _truncate(result.error),
            "duration": time.monotonic() - started,
        }
        (inspection_dir / "result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return payload

    def _trajectory_check(
        self,
        task: TaskPublicView,
        plan: VerificationPlan,
        trajectory: list[TrajectoryItem],
        directory: Path,
        step: int,
    ) -> dict[str, Any]:
        sampled = self._sample_trajectory(trajectory)
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    f"Original task:\n{task.instruction}\n\nChecklist:\n"
                    + "\n".join(f"{index + 1}. {item}" for index, item in enumerate(plan.checklist))
                ),
            }
        ]
        for item in sampled:
            content.append(
                {
                    "type": "text",
                    "text": f"Actor step {item.step}: {item.action}\nThought: {item.thought}",
                }
            )
            if item.screenshot:
                content.append(_image_part(item.screenshot))
        response = self.llm.complete(
            [
                {"role": "system", "content": TRAJECTORY_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            response_schema=TRAJECTORY_SCHEMA,
            temperature=0.0,
        )
        payload = _json_value(response.text)
        check_dir = directory / "trajectory_checks" / f"step_{step + 1:02d}"
        check_dir.mkdir(parents=True, exist_ok=True)
        (check_dir / "result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"status": "success", **payload}

    def _sample_trajectory(self, trajectory: list[TrajectoryItem]) -> list[TrajectoryItem]:
        limit = self.config.trajectory_max_images
        if len(trajectory) <= limit:
            return trajectory
        indexes = {0, len(trajectory) - 1}
        for slot in range(1, limit - 1):
            indexes.add(round(slot * (len(trajectory) - 1) / (limit - 1)))
        return [trajectory[index] for index in sorted(indexes)]

    @staticmethod
    def _judge_instruction(
        task: TaskPublicView, plan: VerificationPlan, trajectory: list[TrajectoryItem]
    ) -> str:
        checklist = "\n".join(f"{i + 1}. {item}" for i, item in enumerate(plan.checklist))
        actions = "\n".join(f"{item.step}. {item.action}" for item in trajectory[-30:]) or "None"
        return (
            f"Original task:\n{task.instruction}\n\nVerification checklist:\n{checklist}\n\n"
            f"Recent actor actions:\n{actions}\n\nVerify the current end state."
        )

    @staticmethod
    def _feedback(verdict: Verdict, plan: VerificationPlan, rationale: str) -> str:
        checklist = "\n".join(f"{i + 1}. {item}" for i, item in enumerate(plan.checklist))
        return (
            f"ARM verdict: {verdict}.\n\nVerification checklist:\n{checklist}\n\n"
            f"Verifier rationale:\n{rationale}"
        )

    @classmethod
    def _error(
        cls,
        plan: VerificationPlan,
        message: str,
        observation: Observation,
        evidence: list[dict[str, Any]] | None = None,
        steps: int = 0,
    ) -> VerificationResult:
        return VerificationResult(
            verdict="error",
            rationale=message,
            feedback=cls._feedback("error", plan, message),
            checklist=plan.checklist,
            evidence=evidence or [],
            judge_steps=steps,
            observation=observation,
        )

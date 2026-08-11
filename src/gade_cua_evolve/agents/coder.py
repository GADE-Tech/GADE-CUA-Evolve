"""Bounded coding sub-agent for isolated OSWorld guests."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from gade_cua_evolve.config import CoderConfig
from gade_cua_evolve.envs import CodeExecutionResult
from gade_cua_evolve.llm import Client, LLMResponse

CodeExecutor = Callable[[str, str, int], CodeExecutionResult]

CODER_SYSTEM_PROMPT = """You are a coding sub-agent operating inside a disposable Ubuntu OSWorld VM.

You receive an original user task and one narrow planner subtask. Work only on the planner subtask.
Use code for deterministic backend work such as local file inspection or editing, calculations,
data processing, and structured transformations. Do not take over visual navigation or layout work.

On every turn call exactly one tool: run_python, run_bash, or finish. Commands have a hard timeout,
so keep them targeted and bounded. Never inspect credentials, environment secrets, browser login
state, SSH keys, or unrelated files. If execution fails, inspect the returned error and correct it.
Verify the resulting artifact or state before calling finish. A finish call must include a concise
factual summary and proof copied or paraphrased from the final verification output. The planner will
independently verify your report; your finish call does not complete the overall user task.
"""

CODER_TOOLS = [
    {
        "name": "run_python",
        "description": "Run Python inside the disposable Ubuntu VM.",
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
    {
        "name": "run_bash",
        "description": "Run a bounded Bash script inside the disposable Ubuntu VM.",
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
    {
        "name": "finish",
        "description": "Return control to the planner after verifying the delegated subtask.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "proof": {"type": "string"},
            },
            "required": ["summary", "proof"],
        },
    },
]


@dataclass(slots=True)
class CoderResult:
    completion_reason: str
    summary: str
    rounds: int
    execution_history: list[dict[str, Any]] = field(default_factory=list)
    error_cause: str = ""

    def metadata(self) -> dict[str, Any]:
        return asdict(self)

    def planner_report(self) -> str:
        lines = [f"Coder completion: {self.completion_reason}", self.summary.strip()]
        if self.error_cause:
            lines.append(f"Error cause: {self.error_cause}")
        lines.append(
            "Inspect the current desktop and resulting files yourself before relying on this report."
        )
        return "\n".join(line for line in lines if line)


def _assistant_message(response: LLMResponse) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": response.text,
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": dict(call.arguments)}
            for call in response.tool_calls
        ],
    }


def _image_part(screenshot: bytes) -> dict[str, Any]:
    encoded = base64.b64encode(screenshot).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}


class CoderAgent:
    """Run a model/tool loop whose code executor is supplied by an EnvAdapter."""

    def __init__(
        self,
        llm: Client,
        config: CoderConfig,
        *,
        secrets: tuple[str, ...] = (),
    ) -> None:
        self.llm = llm
        self.config = config
        self.secrets = tuple(value for value in secrets if value)

    def execute(
        self,
        original_task: str,
        subtask: str,
        screenshot: bytes | None,
        executor: CodeExecutor,
    ) -> CoderResult:
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    f"Original user task:\n{original_task}\n\n"
                    f"Planner subtask:\n{subtask}\n\n"
                    "Preserve the user's exact requested values and constraints."
                ),
            }
        ]
        if screenshot:
            content.extend(
                [
                    {"type": "text", "text": "Desktop state when the subtask was delegated:"},
                    _image_part(screenshot),
                ]
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": CODER_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]
        history: list[dict[str, Any]] = []
        last_error = ""
        last_execution_succeeded = False

        for round_index in range(1, self.config.max_rounds + 1):
            response = self.llm.complete(messages, tools=CODER_TOOLS, temperature=0.0)
            calls = list(response.tool_calls)
            record: dict[str, Any] = {"round": round_index}
            messages.append(_assistant_message(response))

            if len(calls) != 1:
                error = f"expected one tool call, received {len(calls)}"
                record.update(status="invalid", error=error)
                history.append(record)
                last_error = error
                messages.append(
                    {
                        "role": "user",
                        "content": "Call exactly one of run_python, run_bash, or finish.",
                    }
                )
                continue

            call = calls[0]
            arguments = dict(call.arguments)
            record.update(tool=call.name, arguments=self._sanitize_value(arguments))
            if call.name == "finish":
                summary = str(arguments.get("summary", "")).strip()
                proof = str(arguments.get("proof", "")).strip()
                if not summary or not proof:
                    error = "finish requires non-empty summary and proof"
                    record.update(status="invalid", error=error)
                    history.append(record)
                    last_error = error
                    messages.append({"role": "user", "content": error})
                    continue
                if not last_execution_succeeded:
                    error = "finish requires proof from a final successful execution check"
                    record.update(status="invalid", error=error)
                    history.append(record)
                    last_error = error
                    messages.append({"role": "user", "content": error})
                    continue
                record.update(status="finished")
                history.append(record)
                return CoderResult(
                    completion_reason="DONE",
                    summary=self._sanitize(f"{summary}\nProof: {proof}"),
                    rounds=round_index,
                    execution_history=history,
                )

            if call.name not in {"run_python", "run_bash"}:
                error = f"unknown coder tool: {call.name}"
                record.update(status="invalid", error=error)
                history.append(record)
                last_error = error
                messages.append(
                    {"role": "user", "content": "Use run_python, run_bash, or finish only."}
                )
                continue

            code = str(arguments.get("code", ""))
            if not code.strip():
                error = f"{call.name} requires non-empty code"
                record.update(status="invalid", error=error)
                history.append(record)
                last_error = error
                messages.append({"role": "user", "content": error})
                continue

            language = "python" if call.name == "run_python" else "bash"
            execution = executor(language, code, self.config.command_timeout)
            payload = {
                "language": execution.language,
                "status": execution.status,
                "output": self._sanitize(execution.output),
                "error": self._sanitize(execution.error),
                "returncode": execution.returncode,
            }
            record.update(status="executed", result=payload)
            history.append(record)
            last_execution_succeeded = (
                execution.status.lower() in {"success", "ok", "completed"}
                and not execution.error
            )
            if not last_execution_succeeded:
                last_error = payload["error"] or f"{language} execution status: {execution.status}"
            else:
                last_error = ""
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": payload,
                }
            )

        return CoderResult(
            completion_reason="MAX_ROUNDS",
            summary="Coder reached its round limit without a verified finish call.",
            rounds=self.config.max_rounds,
            execution_history=history,
            error_cause=self._sanitize(last_error or "max_rounds_exceeded"),
        )

    def _sanitize(self, value: str) -> str:
        cleaned = value
        for secret in self.secrets:
            cleaned = cleaned.replace(secret, "<redacted>")
        limit = self.config.max_output_chars
        if len(cleaned) <= limit:
            return cleaned
        half = limit // 2
        removed = len(cleaned) - limit
        return f"{cleaned[:half]}\n...[truncated {removed} chars]...\n{cleaned[-half:]}"

    def _sanitize_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._sanitize(value)
        if isinstance(value, dict):
            return {str(key): self._sanitize_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._sanitize_value(item) for item in value]
        return value

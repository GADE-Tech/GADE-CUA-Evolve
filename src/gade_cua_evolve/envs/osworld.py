"""Adaptor for OSWorld's DesktopEnv."""

from __future__ import annotations

import base64
import time
from typing import Any

from dotenv import load_dotenv

from gade_cua_evolve.config import EnvConfig, TaskSpec, resolve_client_password

from .base import CodeExecutionResult, EnvAdapter, InspectionResult, Observation, StepOutcome


class OSWorldEnv(EnvAdapter):
    def __init__(self, config: EnvConfig) -> None:
        # OSWorld cloud providers read credentials directly from os.environ.
        load_dotenv(override=False)
        try:
            from desktop_env.desktop_env import DesktopEnv
        except ImportError as exc:
            raise RuntimeError(
                "OSWorld is unavailable. Run: pip install -e '/path/to/OSWorld'"
            ) from exc
        self.config = config
        self.env = DesktopEnv(
            provider_name=config.provider_name,
            region=config.region,
            path_to_vm=config.path_to_vm,
            snapshot_name=config.snapshot_name,
            action_space=config.action_space,
            screen_size=config.screen_size,
            headless=config.headless,
            require_a11y_tree=config.require_a11y_tree,
            require_terminal=config.require_terminal,
            os_type=config.os_type,
            client_password=resolve_client_password(config),
        )

    @staticmethod
    def _normalize(obs: dict[str, Any]) -> Observation:
        known = {"screenshot", "accessibility_tree", "terminal", "instruction"}
        return Observation(
            screenshot=obs.get("screenshot"),
            accessibility_tree=obs.get("accessibility_tree"),
            terminal=obs.get("terminal"),
            instruction=obs.get("instruction"),
            extra={key: value for key, value in obs.items() if key not in known},
        )

    def reset(self, task: TaskSpec) -> Observation:
        task_config = task.as_osworld_config()
        task_config.setdefault("evaluator", {"func": "infeasible"})
        self.env.reset(task_config=task_config)
        if self.config.boot_wait_seconds:
            time.sleep(self.config.boot_wait_seconds)
        return self.observe()

    def observe(self) -> Observation:
        return self._normalize(self.env._get_obs())

    def step(self, action: str, pause: float = 2.0) -> StepOutcome:
        obs, reward, done, info = self.env.step(action, pause)
        return StepOutcome(self._normalize(obs), float(reward), bool(done), dict(info))

    def evaluate(self) -> float:
        return float(self.env.evaluate())

    def run_inspection(
        self, language: str, code: str, timeout: int = 60
    ) -> InspectionResult:
        normalized = language.strip().lower()
        if normalized == "python":
            result = self.env.controller.run_python_script(code)
        elif normalized == "bash":
            result = self.env.controller.run_bash_script(code, timeout=timeout)
        else:
            return InspectionResult(normalized, "error", error="Unsupported language")
        payload = result if isinstance(result, dict) else {}
        return InspectionResult(
            language=normalized,
            status=str(payload.get("status", "error")),
            output=str(payload.get("output", "") or ""),
            error=str(payload.get("error", "") or payload.get("message", "") or ""),
            returncode=payload.get("returncode"),
        )

    def run_code(self, language: str, code: str, timeout: int = 30) -> CodeExecutionResult:
        normalized = language.strip().lower()
        try:
            if normalized == "python":
                encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
                wrapper = f"""set -e
tmp_py=$(mktemp /tmp/gade-coder-XXXXXX.py)
child_pid=
cleanup() {{
    if [ -n \"$child_pid\" ]; then
        kill -TERM -- \"-$child_pid\" 2>/dev/null || true
        kill -KILL -- \"-$child_pid\" 2>/dev/null || true
    fi
    rm -f \"$tmp_py\"
}}
trap cleanup EXIT
printf '%s' '{encoded}' | base64 -d > \"$tmp_py\"
setsid python3 \"$tmp_py\" &
child_pid=$!
deadline=$((SECONDS + {timeout}))
while kill -0 \"$child_pid\" 2>/dev/null; do
    if [ \"$SECONDS\" -ge \"$deadline\" ]; then
        echo 'Coder Python execution timed out after {timeout} seconds' >&2
        exit 124
    fi
    sleep 1
done
wait \"$child_pid\"
"""
                result = self.env.controller.run_bash_script(wrapper, timeout=timeout + 5)
            elif normalized == "bash":
                result = self.env.controller.run_bash_script(code, timeout=timeout)
            else:
                return CodeExecutionResult(normalized, "error", error="Unsupported language")
        except Exception as exc:  # noqa: BLE001 - return failures to the delegated coder
            return CodeExecutionResult(
                normalized,
                "error",
                error=f"{type(exc).__name__}: {exc}",
            )
        payload = result if isinstance(result, dict) else {}
        return CodeExecutionResult(
            language=normalized,
            status=str(payload.get("status", "error")),
            output=str(payload.get("output", "") or ""),
            error=str(payload.get("error", "") or payload.get("message", "") or ""),
            returncode=payload.get("returncode"),
        )

    def close(self) -> None:
        self.env.close()

    def start_recording(self) -> None:
        self.env.controller.start_recording()

    def stop_recording(self, dest: str) -> None:
        self.env.controller.end_recording(dest)

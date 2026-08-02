"""Validated configuration loading for GADE CUA runs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImageConfig(StrictModel):
    factor: int = 32
    min_pixels: int = 56 * 56
    max_pixels: int = 16 * 16 * 4 * 12800
    max_long_side: int = 8192


class LLMConfig(StrictModel):
    provider: Literal["openai", "google"] = "openai"
    model: str = "qwen3-vl-plus"
    model_env: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None
    base_url_env: str | None = "OPENAI_BASE_URL"
    temperature: float = 0.0
    top_p: float = 0.9
    max_tokens: int = 32768
    max_retries: int = 5
    extra: dict[str, Any] = Field(default_factory=dict)


class AgentConfig(StrictModel):
    name: str = "qwen3vl"
    history_n: int = 4
    coordinate_type: Literal["relative", "absolute"] = "relative"
    platform: str = "ubuntu"
    dump_messages: bool = False
    output_dir: Path | None = None
    internal_retries: int = Field(default=3, ge=1, le=10)
    grounding_model: str | None = None
    grounding_max_tokens: int = Field(default=512, ge=64)
    image: ImageConfig = Field(default_factory=ImageConfig)


class EnvConfig(StrictModel):
    name: str = "noop"
    provider_name: str = "vmware"
    region: str | None = None
    path_to_vm: str | None = None
    snapshot_name: str = "init_state"
    action_space: str = "pyautogui"
    screen_size: tuple[int, int] = (1920, 1080)
    headless: bool = True
    require_a11y_tree: bool = False
    require_terminal: bool = False
    os_type: str = "Ubuntu"
    client_password: str = ""
    boot_wait_seconds: float = 0.0


class LoopConfig(StrictModel):
    name: str = "react"
    max_steps: int = 15
    sleep_after_action: float = 2.0
    settle_seconds: float = 0.0
    output_dir: Path = Path("results")
    record_video: bool = False


class TaskSpec(StrictModel):
    id: str = "task"
    instruction: str
    raw: dict[str, Any] = Field(default_factory=dict)

    def as_osworld_config(self) -> dict[str, Any]:
        return {**self.raw, "id": self.id, "instruction": self.instruction}


class RunConfig(StrictModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    env: EnvConfig = Field(default_factory=EnvConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)


def resolve_env(name: str | None, *, required: bool = False) -> str | None:
    value = os.getenv(name) if name else None
    if not value and name:
        value = dotenv_values(".env").get(name)
    if required and not value:
        raise ValueError(f"Required environment variable {name!r} is not set")
    return value


def _parse_override(value: str) -> Any:
    return yaml.safe_load(value)


def apply_overrides(data: dict[str, Any], overrides: list[str] | None) -> dict[str, Any]:
    for item in overrides or []:
        if "=" not in item:
            raise ValueError(f"Override must use key=value syntax: {item!r}")
        dotted_key, raw_value = item.split("=", 1)
        target = data
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            child = target.setdefault(part, {})
            if not isinstance(child, dict):
                raise TypeError(f"Cannot set nested value under {part!r}")
            target = child
        target[parts[-1]] = _parse_override(raw_value)
    return data


def load_config(path: str | Path, overrides: list[str] | None = None) -> RunConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise TypeError("Configuration root must be a mapping")
    return RunConfig.model_validate(apply_overrides(raw, overrides))

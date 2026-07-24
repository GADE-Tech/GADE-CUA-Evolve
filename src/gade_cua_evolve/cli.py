"""Command line interface and small Python API for GADE CUA Evolve."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class RunConfig:
    """Configuration used by a GADE CUA run."""

    llm_provider: str = "openai"
    model_name: str = "gpt-example"
    computer_provider: str = "local_stub"
    max_steps: int = 10
    trajectory_output_dir: str = "trajectories"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RunConfig":
        """Build a config from flat or nested YAML/JSON data."""

        llm = _mapping_value(data, "llm", {})
        computer = _mapping_value(data, "computer", {})
        trajectory = _mapping_value(data, "trajectory", {})

        return cls(
            llm_provider=str(
                _first_present(data, ["llm_provider", "provider"], _mapping_value(llm, "provider", cls.llm_provider))
            ),
            model_name=str(
                _first_present(data, ["model_name", "model"], _mapping_value(llm, "model", cls.model_name))
            ),
            computer_provider=str(
                _first_present(
                    data,
                    ["computer_provider"],
                    _mapping_value(computer, "provider", cls.computer_provider),
                )
            ),
            max_steps=int(
                _first_present(data, ["max_steps"], _mapping_value(data, "maxSteps", cls.max_steps))
            ),
            trajectory_output_dir=str(
                _first_present(
                    data,
                    ["trajectory_output_dir", "trajectory_dir"],
                    _mapping_value(trajectory, "output_dir", cls.trajectory_output_dir),
                )
            ),
        )


def load_config(path: str | Path | None = None) -> RunConfig:
    """Load a run config from YAML or JSON, returning defaults when omitted."""

    if path is None:
        return RunConfig()

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    raw_text = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() == ".json":
        raw_data = json.loads(raw_text)
    elif config_path.suffix.lower() in {".yaml", ".yml"}:
        raw_data = _load_yaml(raw_text)
    else:
        raise ValueError("Config file must use .yaml, .yml, or .json")

    if raw_data is None:
        raw_data = {}
    if not isinstance(raw_data, Mapping):
        raise ValueError("Config file must contain a YAML/JSON object")
    return RunConfig.from_mapping(raw_data)


def run_task(task: str, config: RunConfig | Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Run a task through the configured providers.

    The current implementation is intentionally lightweight and returns a
    structured run summary. Provider-specific execution can be wired in behind
    this function without changing CLI or example code.
    """

    run_config = _coerce_config(config)
    Path(run_config.trajectory_output_dir).mkdir(parents=True, exist_ok=True)
    result = {
        "mode": "run",
        "task": task,
        "llm_provider": run_config.llm_provider,
        "model_name": run_config.model_name,
        "computer_provider": run_config.computer_provider,
        "max_steps": run_config.max_steps,
        "trajectory_output_dir": run_config.trajectory_output_dir,
        "status": "ready",
    }
    print(json.dumps(result, indent=2))
    return result


def dry_run_task(task: str, config: RunConfig | Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate a task and config without creating trajectory output."""

    run_config = _coerce_config(config)
    result = {
        "mode": "dry-run",
        "task": task,
        "llm_provider": run_config.llm_provider,
        "model_name": run_config.model_name,
        "computer_provider": run_config.computer_provider,
        "max_steps": run_config.max_steps,
        "trajectory_output_dir": run_config.trajectory_output_dir,
        "status": "validated",
    }
    print(json.dumps(result, indent=2))
    return result


def build_parser() -> argparse.ArgumentParser:
    """Create the gade-cua argument parser."""

    parser = argparse.ArgumentParser(prog="gade-cua", description="Run GADE CUA Evolve tasks.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a task.")
    run_parser.add_argument("--task", required=True, help="Natural-language task to execute.")
    run_parser.add_argument("--config", help="Path to a YAML or JSON config file.")

    dry_run_parser = subparsers.add_parser("dry-run", help="Validate a task without executing it.")
    dry_run_parser.add_argument("--task", required=True, help="Natural-language task to validate.")
    dry_run_parser.add_argument("--config", help="Optional path to a YAML or JSON config file.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entrypoint for the gade-cua console script."""

    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.command == "run":
        run_task(args.task, config)
    elif args.command == "dry-run":
        dry_run_task(args.task, config)
    else:  # pragma: no cover - argparse prevents this branch.
        parser.error(f"Unknown command: {args.command}")
    return 0


def _load_yaml(raw_text: str) -> Any:
    try:
        import yaml
    except ImportError:
        return _load_simple_yaml(raw_text)
    return yaml.safe_load(raw_text)


def _load_simple_yaml(raw_text: str) -> dict[str, Any]:
    """Parse the simple nested key/value YAML used by example configs.

    PyYAML remains the recommended parser and is declared as a dependency, but
    this fallback keeps JSON configs and basic YAML configs usable in minimal
    source-checkout environments.
    """

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if ":" not in stripped:
            raise ValueError(f"Unsupported YAML syntax on line {line_number}: {raw_line}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]
        if not value:
            nested: dict[str, Any] = {}
            current[key] = nested
            stack.append((indent, nested))
        else:
            current[key] = _parse_scalar(value)
    return root


def _parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def _coerce_config(config: RunConfig | Mapping[str, Any] | None) -> RunConfig:
    if config is None:
        return RunConfig()
    if isinstance(config, RunConfig):
        return config
    return RunConfig.from_mapping(config)


def _mapping_value(data: Any, key: str, default: Any) -> Any:
    if isinstance(data, Mapping):
        return data.get(key, default)
    return default


def _first_present(data: Mapping[str, Any], keys: Sequence[str], default: Any) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return default


if __name__ == "__main__":
    raise SystemExit(main())

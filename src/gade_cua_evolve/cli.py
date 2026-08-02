"""Typer command line interface."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from .config import RunConfig, TaskSpec, load_config
from .logging_utils import configure_logging
from .registry import AGENTS, ENVS, LOOPS, build_components
from .trajectory import TrajectoryRecorder

app = typer.Typer(help="Run composable computer-use agents.")
config_app = typer.Typer(help="Inspect configuration.")
env_app = typer.Typer(help="Inspect environments.")
app.add_typer(config_app, name="config")
app.add_typer(env_app, name="env")

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OSWORLD_ROOT = Path("/Users/bofeizhang/Documents/GADE Projects/OSWorld")
ENV_PROFILES = {
    "osworldv1": REPOSITORY_ROOT / "configs" / "volcengine_gta15_gemini.yaml",
}
TASK_REF_PATTERN = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+$")


def run_task(task: TaskSpec, config: RunConfig):
    recorder = TrajectoryRecorder(config.loop.output_dir, task, config)
    _, _, loop = build_components(config, recorder)
    return loop.run(task)


def load_task(path: Path) -> TaskSpec:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("Task file must contain a JSON object")
    if "raw" in data:
        return TaskSpec.model_validate(data)
    task_id = str(data.pop("id", "task"))
    instruction = str(data.pop("instruction"))
    return TaskSpec(id=task_id, instruction=instruction, raw=data)


def resolve_env_profile(name_or_path: str) -> Path:
    path = ENV_PROFILES.get(name_or_path, Path(name_or_path))
    if not path.is_file():
        choices = ", ".join(sorted(ENV_PROFILES))
        raise typer.BadParameter(
            f"Unknown environment profile {name_or_path!r}; known profiles: {choices}"
        )
    return path


def resolve_osworld_task(task_ref: str, osworld_root: Path | None = None) -> Path:
    if not TASK_REF_PATTERN.fullmatch(task_ref):
        raise typer.BadParameter("Task must use domain/task_id syntax")
    domain, task_id = task_ref.split("/", 1)
    root = osworld_root or Path(os.getenv("OSWORLD_ROOT", DEFAULT_OSWORLD_ROOT))
    path = root / "evaluation_examples" / "examples" / domain / f"{task_id}.json"
    if not path.is_file():
        raise typer.BadParameter(f"OSWorld task does not exist: {task_ref}")
    return path


def run_task_reference(
    env_name: str,
    task_ref: str,
    *,
    overrides: list[str] | None = None,
    output_dir: Path | None = None,
    verbose: bool = False,
) -> None:
    configure_logging(verbose)
    config_path = resolve_env_profile(env_name)
    domain, _ = task_ref.split("/", 1)
    effective_overrides = list(overrides or [])
    result_root = output_dir or Path("results") / env_name / domain
    effective_overrides.append(f"loop.output_dir={json.dumps(str(result_root))}")
    config = load_config(config_path, effective_overrides)
    task = load_task(resolve_osworld_task(task_ref))
    result = run_task(task, config)
    payload = asdict(result)
    payload["task"] = result.task.model_dump(mode="json")
    typer.echo(json.dumps(payload, default=str, indent=2))


@app.callback(invoke_without_command=True)
def main(
    context: typer.Context,
    env_name: Annotated[str | None, typer.Option("--env", help="Environment profile.")] = None,
    task_ref: Annotated[
        str | None, typer.Option("--task", help="OSWorld task as domain/task_id.")
    ] = None,
    overrides: Annotated[list[str] | None, typer.Option("--set")] = None,
    output_dir: Annotated[Path | None, typer.Option("--output-dir")] = None,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
) -> None:
    """Run a task directly when --env and --task are supplied without a subcommand."""
    if context.invoked_subcommand is not None:
        return
    if env_name is None and task_ref is None:
        typer.echo(context.get_help())
        return
    if not env_name or not task_ref:
        raise typer.BadParameter("Provide both --env and --task")
    run_task_reference(
        env_name,
        task_ref,
        overrides=overrides,
        output_dir=output_dir,
        verbose=verbose,
    )


@app.command("run")
def run_command(
    config_path: Annotated[Path, typer.Option("--config", exists=True)] = Path(
        "configs/default.yaml"
    ),
    instruction: Annotated[str | None, typer.Option("--instruction")] = None,
    task_file: Annotated[Path | None, typer.Option("--task-file", exists=True)] = None,
    overrides: Annotated[list[str] | None, typer.Option("--set")] = None,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
) -> None:
    if bool(instruction) == bool(task_file):
        raise typer.BadParameter("Provide exactly one of --instruction or --task-file")
    configure_logging(verbose)
    config = load_config(config_path, overrides)
    task = TaskSpec(instruction=instruction or "") if instruction else load_task(task_file)
    result = run_task(task, config)
    payload = asdict(result)
    payload["task"] = result.task.model_dump(mode="json")
    typer.echo(json.dumps(payload, default=str, indent=2))


@config_app.command("show")
def config_show(
    config_path: Annotated[Path, typer.Option("--config", exists=True)] = Path(
        "configs/default.yaml"
    ),
    overrides: Annotated[list[str] | None, typer.Option("--set")] = None,
) -> None:
    typer.echo(load_config(config_path, overrides).model_dump_json(indent=2))


@env_app.command("probe")
def env_probe(
    config_path: Annotated[Path, typer.Option("--config", exists=True)] = Path(
        "configs/default.yaml"
    ),
    output: Annotated[Path, typer.Option("--output")] = Path("probe.png"),
) -> None:
    config = load_config(config_path)
    env = ENVS[config.env.name](config.env)
    try:
        observation = env.observe()
        if observation.screenshot:
            output.write_bytes(observation.screenshot)
            typer.echo(str(output))
    finally:
        env.close()


@app.command("list")
def list_components(kind: Annotated[str, typer.Argument(help="agents, envs, or loops")]) -> None:
    registries = {"agents": AGENTS, "envs": ENVS, "loops": LOOPS}
    if kind not in registries:
        raise typer.BadParameter("kind must be agents, envs, or loops")
    typer.echo("\n".join(sorted(registries[kind])))

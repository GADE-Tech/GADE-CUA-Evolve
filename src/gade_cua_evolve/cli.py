"""Typer command line interface."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from .batch import BatchOptions, run_batch
from .config import RunConfig, TaskSpec, load_config
from .controller import RunController
from .logging_utils import configure_logging
from .registry import AGENTS, ENVS, LOOPS, build_components
from .trajectory import TrajectoryRecorder

app = typer.Typer(help="Run composable computer-use agents.")
config_app = typer.Typer(help="Inspect configuration.")
env_app = typer.Typer(help="Inspect environments.")
app.add_typer(config_app, name="config")
app.add_typer(env_app, name="env")

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OSWORLD_ROOT = REPOSITORY_ROOT.parent / "OSWorld"
ENV_PROFILES = {
    "osworldv1": REPOSITORY_ROOT / "configs" / "volcengine_gta15_gemini.yaml",
}
TASK_REF_PATTERN = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+$")


def run_task(
    task: TaskSpec,
    config: RunConfig,
    *,
    arm_enabled: bool = False,
    evaluate: bool = False,
    controller: RunController | None = None,
):
    if evaluate and not task.has_native_evaluator:
        raise typer.BadParameter("--evaluate requires an OSWorld task with a native evaluator")
    recorder = TrajectoryRecorder(config.loop.output_dir, task, config)
    _, _, loop = build_components(
        config,
        recorder,
        controller=controller,
        arm_enabled=arm_enabled,
        evaluate_at_end=evaluate,
    )
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
    root = resolve_osworld_root(osworld_root)
    path = root / "evaluation_examples" / "examples" / domain / f"{task_id}.json"
    if not path.is_file():
        raise typer.BadParameter(f"OSWorld task does not exist: {task_ref}")
    return path


def resolve_osworld_root(explicit: Path | None = None) -> Path:
    """Resolve the pinned OSWorld checkout without machine-specific fallbacks."""
    if explicit is not None:
        root = explicit.expanduser().resolve()
    elif os.getenv("OSWORLD_ROOT"):
        root = Path(os.environ["OSWORLD_ROOT"]).expanduser().resolve()
    else:
        root = DEFAULT_OSWORLD_ROOT.resolve()
    if not (root / "evaluation_examples" / "examples").is_dir():
        raise typer.BadParameter(
            "OSWorld v1 checkout not found. Set OSWORLD_ROOT or clone "
            "https://github.com/GADE-Tech/OSWorld next to this repository."
        )
    return root


def run_task_reference(
    env_name: str,
    task_ref: str,
    *,
    overrides: list[str] | None = None,
    output_dir: Path | None = None,
    verbose: bool = False,
    arm_enabled: bool = False,
    evaluate: bool = False,
    osworld_root: Path | None = None,
) -> None:
    configure_logging(verbose)
    config_path = resolve_env_profile(env_name)
    domain, _ = task_ref.split("/", 1)
    effective_overrides = list(overrides or [])
    result_root = output_dir or Path("results") / env_name / domain
    effective_overrides.append(f"loop.output_dir={json.dumps(str(result_root))}")
    config = load_config(config_path, effective_overrides)
    task = load_task(resolve_osworld_task(task_ref, osworld_root))
    result = run_task(task, config, arm_enabled=arm_enabled, evaluate=evaluate)
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
    osworld_root: Annotated[
        Path | None, typer.Option("--osworld-root", help="Explicit OSWorld v1 checkout.")
    ] = None,
    config_path: Annotated[Path, typer.Option("--config", exists=True)] = Path(
        "configs/volcengine_gta15_gemini.yaml"
    ),
    arm_enabled: Annotated[bool, typer.Option("--arm", help="Enable ARM feedback.")] = False,
    evaluate: Annotated[bool, typer.Option("--evaluate", help="Run native evaluator.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
) -> None:
    """Launch the TUI, or run a benchmark task when --env and --task are supplied."""
    if context.invoked_subcommand is not None:
        return
    if env_name is None:
        configure_logging(verbose)
        from .tui import run_tui

        effective_overrides = list(overrides or [])
        if output_dir:
            effective_overrides.append(f"loop.output_dir={json.dumps(str(output_dir))}")
        initial_task = (
            load_task(resolve_osworld_task(task_ref, osworld_root)) if task_ref else None
        )
        run_tui(
            load_config(config_path, effective_overrides),
            arm_enabled=arm_enabled,
            task=initial_task,
        )
        return
    if not task_ref:
        raise typer.BadParameter("Provide both --env and --task")
    run_task_reference(
        env_name,
        task_ref,
        overrides=overrides,
        output_dir=output_dir,
        verbose=verbose,
        arm_enabled=arm_enabled,
        evaluate=evaluate,
        osworld_root=osworld_root,
    )


@app.command("exec")
def exec_command(
    prompt: Annotated[str | None, typer.Argument(help="Free-form desktop task prompt.")] = None,
    config_path: Annotated[Path, typer.Option("--config", exists=True)] = Path(
        "configs/volcengine_gta15_gemini.yaml"
    ),
    env_name: Annotated[str | None, typer.Option("--env")] = None,
    task_ref: Annotated[str | None, typer.Option("--task")] = None,
    overrides: Annotated[list[str] | None, typer.Option("--set")] = None,
    output_dir: Annotated[Path | None, typer.Option("--output-dir")] = None,
    osworld_root: Annotated[
        Path | None, typer.Option("--osworld-root", help="Explicit OSWorld v1 checkout.")
    ] = None,
    arm_enabled: Annotated[bool, typer.Option("--arm")] = False,
    evaluate: Annotated[bool, typer.Option("--evaluate")] = False,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
) -> None:
    """Execute a free-form prompt or an OSWorld task without the TUI."""
    benchmark_mode = bool(env_name or task_ref)
    if bool(prompt) == benchmark_mode:
        raise typer.BadParameter("Provide either PROMPT or both --env and --task")
    if benchmark_mode:
        if not env_name or not task_ref:
            raise typer.BadParameter("Provide both --env and --task")
        run_task_reference(
            env_name,
            task_ref,
            overrides=overrides,
            output_dir=output_dir,
            verbose=verbose,
            arm_enabled=arm_enabled,
            evaluate=evaluate,
            osworld_root=osworld_root,
        )
        return
    configure_logging(verbose)
    effective_overrides = list(overrides or [])
    if output_dir:
        effective_overrides.append(f"loop.output_dir={json.dumps(str(output_dir))}")
    config = load_config(config_path, effective_overrides)
    result = run_task(
        TaskSpec(instruction=prompt or ""),
        config,
        arm_enabled=arm_enabled,
        evaluate=evaluate,
    )
    payload = asdict(result)
    payload["task"] = result.task.model_dump(mode="json")
    typer.echo(json.dumps(payload, default=str, indent=2))


@app.command("batch")
def batch_command(
    manifest: Annotated[
        Path | None,
        typer.Option("--manifest", help="OSWorld domain-to-task manifest JSON."),
    ] = None,
    config_path: Annotated[
        Path | None,
        typer.Option("--config", exists=True, help="Run configuration; overrides --env."),
    ] = None,
    env_name: Annotated[str, typer.Option("--env", help="Environment profile.")] = "osworldv1",
    output_dir: Annotated[Path | None, typer.Option("--output-dir")] = None,
    osworld_root: Annotated[
        Path | None, typer.Option("--osworld-root", help="Explicit OSWorld v1 checkout.")
    ] = None,
    domains: Annotated[
        list[str] | None,
        typer.Option("--domain", help="Domain or comma-separated domains; repeatable."),
    ] = None,
    limit: Annotated[int | None, typer.Option("--limit", min=1)] = None,
    workers: Annotated[int, typer.Option("--workers", min=1)] = 1,
    resume: Annotated[bool, typer.Option("--resume/--no-resume")] = True,
    shard_index: Annotated[int, typer.Option("--shard-index", min=0)] = 0,
    num_shards: Annotated[int, typer.Option("--num-shards", min=1)] = 1,
    infra_retries: Annotated[int, typer.Option("--infra-retries", min=0)] = 1,
    task_timeout: Annotated[
        float,
        typer.Option("--task-timeout", min=0, help="Seconds; 0 disables the timeout."),
    ] = 0,
    overrides: Annotated[list[str] | None, typer.Option("--set")] = None,
    arm_enabled: Annotated[bool, typer.Option("--arm")] = False,
    evaluate: Annotated[bool, typer.Option("--evaluate")] = False,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
) -> None:
    """Run an OSWorld manifest with process isolation, resume, and aggregation."""
    resolved_osworld_root = resolve_osworld_root(osworld_root)
    manifest_path = (
        manifest
        or resolved_osworld_root / "evaluation_examples" / "test_nogdrive.json"
    )
    if not manifest_path.is_file():
        raise typer.BadParameter(f"Batch manifest does not exist: {manifest_path}")
    selected_config = config_path or resolve_env_profile(env_name)
    suffix = "arm" if arm_enabled else "baseline"
    selected_output = output_dir or Path("results") / "batch" / f"{manifest_path.stem}-{suffix}"
    try:
        summary = run_batch(
            BatchOptions(
                manifest=manifest_path,
                config=selected_config,
                osworld_root=resolved_osworld_root,
                output_dir=selected_output,
                domains=tuple(domains or ()),
                limit=limit,
                workers=workers,
                resume=resume,
                shard_index=shard_index,
                num_shards=num_shards,
                infra_retries=infra_retries,
                task_timeout=task_timeout or None,
                arm=arm_enabled,
                evaluate=evaluate,
                overrides=tuple(overrides or ()),
                verbose=verbose,
                workdir=REPOSITORY_ROOT,
            )
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(asdict(summary), indent=2))
    if summary.infra_failed:
        raise typer.Exit(code=1)


@app.command("run")
def run_command(
    config_path: Annotated[Path, typer.Option("--config", exists=True)] = Path(
        "configs/default.yaml"
    ),
    instruction: Annotated[str | None, typer.Option("--instruction")] = None,
    task_file: Annotated[Path | None, typer.Option("--task-file", exists=True)] = None,
    overrides: Annotated[list[str] | None, typer.Option("--set")] = None,
    arm_enabled: Annotated[bool, typer.Option("--arm")] = False,
    evaluate: Annotated[bool, typer.Option("--evaluate")] = False,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
) -> None:
    if bool(instruction) == bool(task_file):
        raise typer.BadParameter("Provide exactly one of --instruction or --task-file")
    configure_logging(verbose)
    config = load_config(config_path, overrides)
    task = TaskSpec(instruction=instruction or "") if instruction else load_task(task_file)
    result = run_task(task, config, arm_enabled=arm_enabled, evaluate=evaluate)
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
    check_code: Annotated[
        bool,
        typer.Option("--check-code", help="Run harmless Python and Bash checks inside the VM."),
    ] = False,
    check_python: Annotated[
        bool, typer.Option("--check-python", help="Run a harmless Python check inside the VM.")
    ] = False,
    check_bash: Annotated[
        bool, typer.Option("--check-bash", help="Run a harmless Bash check inside the VM.")
    ] = False,
    check_services: Annotated[
        bool,
        typer.Option(
            "--check-services",
            help="Check OSWorld control and Chrome DevTools guest ports.",
        ),
    ] = False,
    check_screenshot: Annotated[
        bool,
        typer.Option(
            "--check-screenshot/--no-check-screenshot",
            help="Capture and validate a desktop screenshot.",
        ),
    ] = True,
) -> None:
    config = load_config(config_path)
    env = ENVS[config.env.name](config.env)
    payload: dict[str, object] = {"environment": config.env.name}
    failed = False
    try:
        if check_screenshot:
            observation = env.observe()
            if observation.screenshot:
                output.write_bytes(observation.screenshot)
                payload["screenshot"] = str(output)
            else:
                payload["screenshot"] = None
                failed = True
        checks = []
        if check_code or check_python:
            checks.append(("python", "python", "print('gade-coder-python-ok')"))
        if check_code or check_bash:
            checks.append(("bash", "bash", "printf '%s\\n' gade-coder-bash-ok"))
        if check_services:
            checks.append(
                (
                    "services",
                    "bash",
                    """set -e
python3 - <<'PY'
import socket

for port in (5000, 9222):
    with socket.create_connection(("127.0.0.1", port), timeout=5):
        print(f"guest port {port}: reachable")
PY
if command -v systemctl >/dev/null 2>&1 && \
   systemctl list-unit-files osworld_server.service --no-legend | grep -q osworld_server; then
    systemctl is-active --quiet osworld_server.service
    printf '%s\\n' 'osworld_server.service: active'
fi""",
                )
            )
        for label, language, code in checks:
            try:
                result = env.run_code(language, code, timeout=15)
                payload[label] = asdict(result)
                if (
                    result.status.lower() not in {"success", "ok", "completed"}
                    or result.error
                ):
                    failed = True
            except Exception as exc:  # noqa: BLE001 - report unsupported probe surfaces
                payload[label] = {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
                failed = True
    finally:
        env.close()
    typer.echo(json.dumps(payload, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("list")
def list_components(kind: Annotated[str, typer.Argument(help="agents, envs, or loops")]) -> None:
    registries = {"agents": AGENTS, "envs": ENVS, "loops": LOOPS}
    if kind not in registries:
        raise typer.BadParameter("kind must be agents, envs, or loops")
    typer.echo("\n".join(sorted(registries[kind])))


if __name__ == "__main__":
    app()

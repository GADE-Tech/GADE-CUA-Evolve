"""Resumable, process-isolated OSWorld batch execution."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class BatchTask:
    domain: str
    task_id: str
    path: Path

    @property
    def ref(self) -> str:
        return f"{self.domain}/{self.task_id}"


@dataclass(frozen=True)
class BatchOptions:
    manifest: Path
    config: Path
    osworld_root: Path
    output_dir: Path
    domains: tuple[str, ...] = ()
    limit: int | None = None
    workers: int = 1
    resume: bool = True
    shard_index: int = 0
    num_shards: int = 1
    infra_retries: int = 1
    task_timeout: float | None = None
    arm: bool = False
    evaluate: bool = False
    overrides: tuple[str, ...] = ()
    verbose: bool = False
    workdir: Path = field(default_factory=Path.cwd)


@dataclass
class BatchAttempt:
    task_ref: str
    attempt: int
    outcome: Literal["completed", "infra_failed", "skipped"]
    started_at: str
    duration_seconds: float
    exit_code: int | None = None
    task_status: str | None = None
    done: bool | None = None
    score: float | None = None
    arm_verdict: str | None = None
    result_path: str | None = None
    log_path: str | None = None
    error: str | None = None
    cleanup_status: str | None = None


@dataclass
class BatchSummary:
    selected: int
    completed: int
    skipped: int
    infra_failed: int
    finished: int
    incomplete: int
    scored: int
    mean_score: float | None
    output_dir: str
    duration_seconds: float


TaskExecutor = Callable[[BatchTask, BatchOptions, int], BatchAttempt]
ProgressCallback = Callable[[str], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalized_domains(domains: tuple[str, ...]) -> set[str]:
    return {
        item.strip()
        for value in domains
        for item in value.split(",")
        if item.strip()
    }


def load_batch_tasks(options: BatchOptions) -> list[BatchTask]:
    """Load, validate, filter, and deterministically shard an OSWorld manifest."""
    raw = json.loads(options.manifest.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("Batch manifest must map domains to task ID lists")
    requested_domains = _normalized_domains(options.domains)
    unknown = requested_domains.difference(raw)
    if unknown:
        raise ValueError(f"Unknown manifest domains: {', '.join(sorted(unknown))}")
    if options.workers < 1:
        raise ValueError("workers must be at least 1")
    if options.infra_retries < 0:
        raise ValueError("infra_retries cannot be negative")
    if options.num_shards < 1 or not 0 <= options.shard_index < options.num_shards:
        raise ValueError("shard_index must be in [0, num_shards)")
    if options.limit is not None and options.limit < 1:
        raise ValueError("limit must be at least 1")
    if options.task_timeout is not None and options.task_timeout <= 0:
        raise ValueError("task_timeout must be positive")

    tasks: list[BatchTask] = []
    seen: set[str] = set()
    examples_root = options.osworld_root / "evaluation_examples" / "examples"
    for domain, task_ids in raw.items():
        if requested_domains and domain not in requested_domains:
            continue
        if not isinstance(domain, str) or not isinstance(task_ids, list):
            raise TypeError("Every manifest entry must be a domain and a task ID list")
        for task_id in task_ids:
            if not isinstance(task_id, str) or not task_id:
                raise TypeError(f"Invalid task ID under domain {domain!r}")
            ref = f"{domain}/{task_id}"
            if ref in seen:
                raise ValueError(f"Duplicate task in manifest: {ref}")
            seen.add(ref)
            path = examples_root / domain / f"{task_id}.json"
            if not path.is_file():
                raise FileNotFoundError(f"OSWorld task does not exist: {ref}")
            tasks.append(BatchTask(domain, task_id, path))

    tasks = [
        task for index, task in enumerate(tasks) if index % options.num_shards == options.shard_index
    ]
    if options.limit is not None:
        tasks = tasks[: options.limit]
    return tasks


def _result_candidates(options: BatchOptions, task: BatchTask) -> list[Path]:
    task_root = options.output_dir / "tasks" / task.domain
    return sorted(
        # ``TrajectoryRecorder`` adds its own timestamped task directory below
        # the per-attempt directory, so discover results recursively.
        task_root.rglob("result.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _task_output_dir(options: BatchOptions, task: BatchTask, attempt: int) -> Path:
    """Return an isolated output directory for one task attempt.

    The task ID is part of the directory name so concurrent tasks in the same
    domain cannot overwrite each other's screenshots or ``result.json``.
    """
    return options.output_dir / "tasks" / task.domain / f"{task.task_id}-{attempt:02d}"


def _read_result(path: Path, task: BatchTask) -> dict | None:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(result, dict) or not isinstance(result.get("status"), str):
        return None
    result_task = result.get("task")
    if not isinstance(result_task, dict) or str(result_task.get("id")) != task.task_id:
        return None
    return result


def find_latest_result(options: BatchOptions, task: BatchTask) -> tuple[Path, dict] | None:
    for path in _result_candidates(options, task):
        result = _read_result(path, task)
        if result is not None:
            return path, result
    return None


def _attempt_from_result(
    task: BatchTask,
    *,
    attempt: int,
    started_at: str,
    duration: float,
    path: Path,
    result: dict,
    log_path: Path | None,
    outcome: Literal["completed", "skipped"] = "completed",
) -> BatchAttempt:
    score = result.get("score")
    return BatchAttempt(
        task_ref=task.ref,
        attempt=attempt,
        outcome=outcome,
        started_at=started_at,
        duration_seconds=duration,
        exit_code=0,
        task_status=result.get("status"),
        done=bool(result.get("done")),
        score=float(score) if isinstance(score, (int, float)) else None,
        arm_verdict=result.get("arm_verdict"),
        result_path=str(path.resolve()),
        log_path=str(log_path.resolve()) if log_path else None,
        cleanup_status="loop_closed" if outcome == "completed" else "previous_run",
    )


def _tail_error(path: Path, limit: int = 12) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return str(exc)
    useful = [line.strip() for line in lines if line.strip()]
    return "\n".join(useful[-limit:])[-4000:] or "Child process failed without output"


def _child_command(task: BatchTask, options: BatchOptions, task_output: Path) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "gade_cua_evolve.cli",
        "run",
        "--config",
        str(options.config.resolve()),
        "--task-file",
        str(task.path.resolve()),
        "--set",
        f"loop.output_dir={json.dumps(str(task_output.resolve()))}",
    ]
    for override in options.overrides:
        command.extend(["--set", override])
    if options.arm:
        command.append("--arm")
    if options.evaluate:
        command.append("--evaluate")
    if options.verbose:
        command.append("--verbose")
    return command


def execute_batch_task(task: BatchTask, options: BatchOptions, attempt: int) -> BatchAttempt:
    """Execute one task in a child process so VM and SDK state cannot leak between tasks."""
    started_at = _utc_now()
    started = time.monotonic()
    task_output = _task_output_dir(options, task, attempt)
    log_path = options.output_dir / "logs" / task.domain / f"{task.task_id}-{attempt:02d}.log"
    task_output.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    previous_results = set(_result_candidates(options, task))
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    timed_out = False
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            _child_command(task, options, task_output),
            cwd=options.workdir,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            exit_code = process.wait(timeout=options.task_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                exit_code = process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()
                exit_code = process.wait()

    duration = time.monotonic() - started
    new_results = [path for path in _result_candidates(options, task) if path not in previous_results]
    parsed = next(
        ((path, result) for path in new_results if (result := _read_result(path, task))),
        None,
    )
    if exit_code == 0 and parsed:
        path, result = parsed
        return _attempt_from_result(
            task,
            attempt=attempt,
            started_at=started_at,
            duration=duration,
            path=path,
            result=result,
            log_path=log_path,
        )
    error = "Task exceeded its timeout" if timed_out else _tail_error(log_path)
    return BatchAttempt(
        task_ref=task.ref,
        attempt=attempt,
        outcome="infra_failed",
        started_at=started_at,
        duration_seconds=duration,
        exit_code=exit_code,
        result_path=str(parsed[0].resolve()) if parsed else None,
        log_path=str(log_path.resolve()),
        error=error,
        cleanup_status="child_failed; inspect cloud resources",
    )


def _load_latest_attempts(path: Path) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    if not path.is_file():
        return latest
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and isinstance(record.get("task_ref"), str):
            latest[record["task_ref"]] = record
    return latest


def _resume_result(
    options: BatchOptions, task: BatchTask, latest_attempts: dict[str, dict]
) -> BatchAttempt | None:
    previous = latest_attempts.get(task.ref)
    if previous and previous.get("outcome") == "infra_failed":
        return None
    found = find_latest_result(options, task)
    if not found:
        return None
    path, result = found
    return _attempt_from_result(
        task,
        attempt=0,
        started_at=_utc_now(),
        duration=0.0,
        path=path,
        result=result,
        log_path=None,
        outcome="skipped",
    )


def _summary(outcomes: list[BatchAttempt], options: BatchOptions, duration: float) -> BatchSummary:
    completed = [item for item in outcomes if item.outcome == "completed"]
    skipped = [item for item in outcomes if item.outcome == "skipped"]
    valid = completed + skipped
    scores = [item.score for item in valid if item.score is not None]
    finished = [
        item
        for item in valid
        if item.done and item.task_status in {"completed", "finished"}
    ]
    return BatchSummary(
        selected=len(outcomes),
        completed=len(completed),
        skipped=len(skipped),
        infra_failed=sum(item.outcome == "infra_failed" for item in outcomes),
        finished=len(finished),
        incomplete=len(valid) - len(finished),
        scored=len(scores),
        mean_score=sum(scores) / len(scores) if scores else None,
        output_dir=str(options.output_dir.resolve()),
        duration_seconds=duration,
    )


def run_batch(
    options: BatchOptions,
    *,
    task_executor: TaskExecutor = execute_batch_task,
    progress: ProgressCallback = print,
) -> BatchSummary:
    """Run selected tasks with bounded concurrency and durable attempt records."""
    tasks = load_batch_tasks(options)
    options.output_dir.mkdir(parents=True, exist_ok=True)
    attempts_path = options.output_dir / "attempts.jsonl"
    latest_attempts = _load_latest_attempts(attempts_path)
    write_lock = threading.Lock()
    started = time.monotonic()
    outcomes: list[BatchAttempt] = []
    pending: list[BatchTask] = []

    config_record = {
        "created_at": _utc_now(),
        "manifest": str(options.manifest.resolve()),
        "config": str(options.config.resolve()),
        "domains": sorted(_normalized_domains(options.domains)),
        "workers": options.workers,
        "arm": options.arm,
        "evaluate": options.evaluate,
        "shard_index": options.shard_index,
        "num_shards": options.num_shards,
        "selected": len(tasks),
    }
    (options.output_dir / "batch_config.json").write_text(
        json.dumps(config_record, indent=2) + "\n", encoding="utf-8"
    )

    def record(attempt: BatchAttempt) -> None:
        with write_lock, attempts_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(attempt), ensure_ascii=False) + "\n")

    for task in tasks:
        resumed = _resume_result(options, task, latest_attempts) if options.resume else None
        if resumed:
            outcomes.append(resumed)
            record(resumed)
            progress(f"SKIP {task.ref} ({resumed.task_status})")
        else:
            pending.append(task)

    def run_with_retries(task: BatchTask) -> BatchAttempt:
        last: BatchAttempt | None = None
        for attempt_number in range(1, options.infra_retries + 2):
            progress(f"RUN  {task.ref} attempt={attempt_number}")
            last = task_executor(task, options, attempt_number)
            record(last)
            if last.outcome == "completed":
                return last
            if attempt_number <= options.infra_retries:
                progress(f"RETRY {task.ref} infrastructure failure")
        assert last is not None
        return last

    with ThreadPoolExecutor(max_workers=options.workers, thread_name_prefix="gadecua-batch") as pool:
        futures = {pool.submit(run_with_retries, task): task for task in pending}
        for future in as_completed(futures):
            task = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:  # noqa: BLE001
                outcome = BatchAttempt(
                    task_ref=task.ref,
                    attempt=0,
                    outcome="infra_failed",
                    started_at=_utc_now(),
                    duration_seconds=0.0,
                    error=f"Batch worker crashed: {type(exc).__name__}: {exc}",
                    cleanup_status="worker_crashed; inspect cloud resources",
                )
                record(outcome)
            outcomes.append(outcome)
            label = "DONE" if outcome.outcome == "completed" else "FAIL"
            score = "-" if outcome.score is None else f"{outcome.score:g}"
            progress(f"{label} {task.ref} status={outcome.task_status or '-'} score={score}")

    summary = _summary(outcomes, options, time.monotonic() - started)
    (options.output_dir / "summary.json").write_text(
        json.dumps(asdict(summary), indent=2) + "\n", encoding="utf-8"
    )
    return summary

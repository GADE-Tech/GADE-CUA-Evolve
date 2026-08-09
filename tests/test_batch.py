import json
from collections import Counter
from pathlib import Path

from gade_cua_evolve.batch import (
    BatchAttempt,
    BatchOptions,
    BatchSummary,
    BatchTask,
    _child_command,
    _task_output_dir,
    load_batch_tasks,
    run_batch,
)


def make_batch(tmp_path: Path, manifest_data: dict[str, list[str]], **updates) -> BatchOptions:
    osworld_root = tmp_path / "osworld"
    for domain, task_ids in manifest_data.items():
        for task_id in task_ids:
            task_path = (
                osworld_root
                / "evaluation_examples"
                / "examples"
                / domain
                / f"{task_id}.json"
            )
            task_path.parent.mkdir(parents=True, exist_ok=True)
            task_path.write_text(
                json.dumps({"id": task_id, "instruction": f"Do {task_id}"}),
                encoding="utf-8",
            )
    manifest = osworld_root / "evaluation_examples" / "test.json"
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    values = {
        "manifest": manifest,
        "config": tmp_path / "config.yaml",
        "osworld_root": osworld_root,
        "output_dir": tmp_path / "results",
        "workdir": tmp_path,
    }
    values.update(updates)
    return BatchOptions(**values)


def completed(task: BatchTask, attempt: int, score: float) -> BatchAttempt:
    return BatchAttempt(
        task_ref=task.ref,
        attempt=attempt,
        outcome="completed",
        started_at="2026-01-01T00:00:00+00:00",
        duration_seconds=1,
        exit_code=0,
        task_status="completed",
        done=True,
        score=score,
        cleanup_status="loop_closed",
    )


def test_manifest_filter_shard_and_limit_are_deterministic(tmp_path) -> None:
    options = make_batch(
        tmp_path,
        {"chrome": ["a", "b", "c"], "gimp": ["d", "e"]},
        domains=("chrome,gimp",),
        num_shards=2,
        shard_index=1,
        limit=2,
    )

    assert [task.ref for task in load_batch_tasks(options)] == ["chrome/b", "gimp/d"]


def test_infrastructure_failure_retries_but_zero_score_does_not(tmp_path) -> None:
    options = make_batch(
        tmp_path,
        {"chrome": ["zero", "one"]},
        workers=2,
        infra_retries=2,
    )
    calls: Counter[str] = Counter()

    def fake_executor(task, _options, attempt):
        calls[task.ref] += 1
        if task.task_id == "zero" and attempt == 1:
            return BatchAttempt(
                task_ref=task.ref,
                attempt=attempt,
                outcome="infra_failed",
                started_at="2026-01-01T00:00:00+00:00",
                duration_seconds=1,
                exit_code=1,
                error="TLS error",
            )
        return completed(task, attempt, 0.0 if task.task_id == "zero" else 1.0)

    summary = run_batch(options, task_executor=fake_executor, progress=lambda _: None)

    assert calls == Counter({"chrome/zero": 2, "chrome/one": 1})
    assert summary.completed == 2
    assert summary.infra_failed == 0
    assert summary.scored == 2
    assert summary.mean_score == 0.5
    records = [
        json.loads(line)
        for line in (options.output_dir / "attempts.jsonl").read_text().splitlines()
    ]
    assert [record["outcome"] for record in records].count("infra_failed") == 1


def test_resume_skips_only_a_valid_result(tmp_path) -> None:
    options = make_batch(tmp_path, {"chrome": ["done"]})
    result_path = options.output_dir / "tasks" / "chrome" / "done-stamp" / "result.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps(
            {
                "task": {"id": "done", "instruction": "Do done", "raw": {}},
                "status": "completed",
                "done": True,
                "score": 0.0,
                "arm_verdict": "failed",
            }
        ),
        encoding="utf-8",
    )

    def should_not_run(*_args):
        raise AssertionError("valid result should be resumed")

    summary = run_batch(options, task_executor=should_not_run, progress=lambda _: None)

    assert summary.skipped == 1
    assert summary.completed == 0
    assert summary.scored == 1
    assert summary.mean_score == 0.0


def test_latest_infrastructure_failure_forces_resume_retry(tmp_path) -> None:
    options = make_batch(tmp_path, {"chrome": ["retry"]})
    result_path = options.output_dir / "tasks" / "chrome" / "retry-stamp" / "result.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps(
            {
                "task": {"id": "retry"},
                "status": "completed",
                "done": True,
                "score": 1.0,
            }
        ),
        encoding="utf-8",
    )
    (options.output_dir / "attempts.jsonl").write_text(
        json.dumps({"task_ref": "chrome/retry", "outcome": "infra_failed"}) + "\n",
        encoding="utf-8",
    )
    calls = 0

    def fake_executor(task, _options, attempt):
        nonlocal calls
        calls += 1
        return completed(task, attempt, 1.0)

    summary = run_batch(options, task_executor=fake_executor, progress=lambda _: None)

    assert calls == 1
    assert summary.completed == 1
    assert summary.skipped == 0


def test_child_command_preserves_arm_evaluate_and_overrides(tmp_path) -> None:
    options = make_batch(
        tmp_path,
        {"gimp": ["task"]},
        arm=True,
        evaluate=True,
        verbose=True,
        overrides=("loop.max_steps=7",),
    )
    task = load_batch_tasks(options)[0]

    command = _child_command(task, options, tmp_path / "task-output")

    assert command[1:4] == ["-m", "gade_cua_evolve.cli", "run"]
    assert "--arm" in command
    assert "--evaluate" in command
    assert "--verbose" in command
    assert "loop.max_steps=7" in command


def test_task_attempt_output_directories_are_isolated(tmp_path) -> None:
    options = make_batch(tmp_path, {"chrome": ["a", "b"]})
    tasks = load_batch_tasks(options)

    assert _task_output_dir(options, tasks[0], 1) != _task_output_dir(options, tasks[1], 1)
    assert _task_output_dir(options, tasks[0], 1) != _task_output_dir(options, tasks[0], 2)


def test_summary_json_is_written(tmp_path) -> None:
    options = make_batch(tmp_path, {"chrome": ["a"]})

    summary = run_batch(
        options,
        task_executor=lambda task, _options, attempt: completed(task, attempt, 1.0),
        progress=lambda _: None,
    )

    saved = json.loads((options.output_dir / "summary.json").read_text())
    assert saved == summary.__dict__
    assert BatchSummary(**saved).finished == 1

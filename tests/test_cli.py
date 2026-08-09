import json

import pytest
from typer.testing import CliRunner

from gade_cua_evolve import cli
from gade_cua_evolve.batch import BatchSummary
from gade_cua_evolve.config import RunConfig, TaskSpec
from gade_cua_evolve.loops import RunResult

runner = CliRunner()


def test_short_cli_routes_environment_and_task(monkeypatch) -> None:
    captured = {}

    def fake_run(env_name, task_ref, **options):
        captured.update(env_name=env_name, task_ref=task_ref, **options)

    monkeypatch.setattr(cli, "run_task_reference", fake_run)
    result = runner.invoke(
        cli.app,
        ["--env", "osworldv1", "--task", "chrome/task-id", "--output-dir", "custom"],
    )

    assert result.exit_code == 0
    assert captured["env_name"] == "osworldv1"
    assert captured["task_ref"] == "chrome/task-id"
    assert str(captured["output_dir"]) == "custom"


def test_resolve_osworld_task(tmp_path) -> None:
    task_path = tmp_path / "evaluation_examples" / "examples" / "chrome" / "task-id.json"
    task_path.parent.mkdir(parents=True)
    task_path.write_text(json.dumps({"id": "task-id"}), encoding="utf-8")

    assert cli.resolve_osworld_task("chrome/task-id", tmp_path) == task_path


@pytest.mark.parametrize("task_ref", ["chrome", "../secret", "chrome/a/b"])
def test_resolve_osworld_task_rejects_invalid_reference(task_ref, tmp_path) -> None:
    with pytest.raises(cli.typer.BadParameter):
        cli.resolve_osworld_task(task_ref, tmp_path)


def test_exec_prompt_routes_arm_without_native_evaluation(monkeypatch) -> None:
    captured = {}

    def fake_run(task, config, **options):
        captured.update(task=task, **options)
        return RunResult(task, None, True, 1, 0, status="completed")

    monkeypatch.setattr(cli, "run_task", fake_run)
    result = runner.invoke(
        cli.app,
        ["exec", "Open Chrome", "--config", "configs/default.yaml", "--arm"],
    )
    assert result.exit_code == 0
    assert captured["task"].instruction == "Open Chrome"
    assert captured["arm_enabled"] is True
    assert captured["evaluate"] is False


def test_free_prompt_cannot_request_native_evaluator() -> None:
    with pytest.raises(cli.typer.BadParameter, match="native evaluator"):
        cli.run_task(TaskSpec(instruction="free prompt"), RunConfig(), evaluate=True)


def test_no_args_launches_tui(monkeypatch) -> None:
    from gade_cua_evolve import tui

    captured = {}
    monkeypatch.setattr(tui, "run_tui", lambda config, **kwargs: captured.update(kwargs))
    result = runner.invoke(cli.app, ["--config", "configs/default.yaml", "--arm"])
    assert result.exit_code == 0
    assert captured["arm_enabled"] is True


def test_batch_cli_routes_options(monkeypatch, tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"chrome": []}', encoding="utf-8")
    captured = {}

    def fake_batch(options):
        captured["options"] = options
        return BatchSummary(0, 0, 0, 0, 0, 0, 0, None, str(tmp_path), 0)

    monkeypatch.setattr(cli, "run_batch", fake_batch)
    result = runner.invoke(
        cli.app,
        [
            "batch",
            "--manifest",
            str(manifest),
            "--config",
            "configs/default.yaml",
            "--domain",
            "chrome,gimp",
            "--workers",
            "3",
            "--arm",
            "--evaluate",
            "--no-resume",
        ],
    )

    assert result.exit_code == 0
    options = captured["options"]
    assert options.workers == 3
    assert options.domains == ("chrome,gimp",)
    assert options.arm is True
    assert options.evaluate is True
    assert options.resume is False

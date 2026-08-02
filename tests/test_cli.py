import json

import pytest
from typer.testing import CliRunner

from gade_cua_evolve import cli

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

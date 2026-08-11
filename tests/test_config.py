import pytest
from pydantic import ValidationError

from gade_cua_evolve.cli import load_task
from gade_cua_evolve.config import TaskSpec, load_config, resolve_env


def test_load_config_and_override() -> None:
    config = load_config("configs/default.yaml", ["loop.max_steps=3", "env.headless=false"])
    assert config.loop.max_steps == 3
    assert config.env.headless is False


def test_unknown_config_key_is_rejected(tmp_path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("unknown: true\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(path)


def test_dotenv_secret_loading(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CUSTOM_API_KEY", raising=False)
    (tmp_path / ".env").write_text("CUSTOM_API_KEY=test-key\n", encoding="utf-8")
    assert resolve_env("CUSTOM_API_KEY", required=True) == "test-key"


def test_osworld_task_file_is_normalized(tmp_path) -> None:
    path = tmp_path / "task.json"
    path.write_text(
        '{"id":"x","instruction":"do it","evaluator":{"func":"infeasible"}}',
        encoding="utf-8",
    )
    task = load_task(path)
    assert task.id == "x"
    assert task.raw["evaluator"]["func"] == "infeasible"


def test_three_model_profile_and_public_task_view() -> None:
    config = load_config("configs/volcengine_gta15_gemini.yaml")
    assert config.grounder is not None
    assert config.grounder.max_turns == 5
    assert config.arm is not None
    assert config.arm.enable_trajectory_check is True

    task = TaskSpec(
        id="private",
        instruction="do it",
        raw={"evaluator": {"expected": "secret"}},
    )
    assert task.public_view().model_dump() == {"id": "private", "instruction": "do it"}
    assert task.has_native_evaluator is True

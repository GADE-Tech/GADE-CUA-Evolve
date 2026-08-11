import hashlib
import os
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREPARE = ROOT / "scripts" / "prepare_volcengine_image.sh"
PROVISION = ROOT / "scripts" / "provision_osworld_coder.sh"


def run_prepare(*arguments: str, env: dict[str, str] | None = None):
    return subprocess.run(
        ["bash", str(PREPARE), *arguments],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_image_scripts_have_valid_bash_syntax() -> None:
    for script in (PREPARE, PROVISION):
        result = subprocess.run(
            ["bash", "-n", str(script)], text=True, capture_output=True, check=False
        )
        assert result.returncode == 0, result.stderr


def test_prepare_dry_run_reports_pinned_image(tmp_path: Path) -> None:
    result = run_prepare("--work-dir", str(tmp_path), "--dry-run")
    assert result.returncode == 0
    assert "9600484566f238a9ce57ea32c33567c6044e41d8" in result.stdout
    assert "b795b6cd4c69b252c1b4f10150a347795555032501b60fd031751ed09b896712" in result.stdout


def test_prepare_rejects_checksum_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    source.write_bytes(b"not the expected archive")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    qemu = bin_dir / "qemu-img"
    qemu.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    qemu.chmod(0o755)
    work = tmp_path / "work"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    result = run_prepare(
        "--work-dir",
        str(work),
        "--source-url",
        source.as_uri(),
        "--sha256",
        "0" * 64,
        env=env,
    )

    assert result.returncode == 1
    assert "Checksum mismatch" in result.stderr


def test_prepare_requires_checksum_for_overridden_source(tmp_path: Path) -> None:
    result = run_prepare(
        "--work-dir",
        str(tmp_path / "work"),
        "--source-url",
        (tmp_path / "mirror.zip").as_uri(),
        "--dry-run",
    )

    assert result.returncode == 2
    assert "--sha256 is required" in result.stderr


def test_prepare_validates_and_uploads_fixture(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Ubuntu.qcow2", b"small-qcow-fixture")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "tool.log"
    for name in ("qemu-img", "tosutil"):
        tool = bin_dir / name
        tool.write_text(
            f"#!/usr/bin/env bash\nprintf '%s\\n' \"{name} $*\" >> {str(log)!r}\n",
            encoding="utf-8",
        )
        tool.chmod(0o755)
    work = tmp_path / "work"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "VOLCENGINE_REGION": "ap-southeast-1",
    }

    result = run_prepare(
        "--work-dir",
        str(work),
        "--source-url",
        source.as_uri(),
        "--sha256",
        checksum,
        "--upload",
        "--tos-bucket",
        "test-bucket",
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert (work / "Ubuntu.qcow2").read_bytes() == b"small-qcow-fixture"
    tool_log = log.read_text(encoding="utf-8")
    assert "qemu-img info" in tool_log
    assert "qemu-img check" in tool_log
    assert "tosutil cp" in tool_log
    assert "-vchecksum" in tool_log
    assert "https://test-bucket.tos-ap-southeast-1.volces.com/" in result.stdout

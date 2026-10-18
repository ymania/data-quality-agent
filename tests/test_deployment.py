"""Launcher failure/idempotence tests with a fake CLI; NOT a Docker runtime test."""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def launch(tmp_path, *, failure="", port=None, volumes=""):
    project = tmp_path / "project with spaces"
    project.mkdir(exist_ok=True)
    shutil.copy(ROOT / "start-docker.sh", project)
    (project / "compose.yaml").touch()
    tools = tmp_path / "bin"
    tools.mkdir(exist_ok=True)
    fake = tools / "docker"
    fake.write_text('''#!/bin/bash
if [[ "$1" == info && "$MOCK_FAIL" == info ]]; then exit 1; fi
if [[ "$1" == buildx && "$MOCK_FAIL" == buildx ]]; then exit 1; fi
if [[ "$*" == 'compose up --help' ]]; then echo --wait-timeout; fi
if [[ "$1" == volume ]]; then echo "$MOCK_VOLUMES"; fi
if [[ "$*" == *' up --build '* && "$MOCK_FAIL" == up ]]; then exit 1; fi
exit 0
''')
    fake.chmod(0o755)
    env = {**os.environ, "PATH": str(tools) + ":" + os.environ["PATH"],
           "DQ_NO_BROWSER": "1", "MOCK_FAIL": failure, "MOCK_VOLUMES": volumes}
    result = subprocess.run(["bash", str(project / "start-docker.sh"), *([] if port is None else [port])], env=env, text=True, capture_output=True)
    return project, result


def test_no_config_is_written_when_daemon_unavailable(tmp_path):
    project, result = launch(tmp_path, failure="info")
    assert result.returncode != 0 and not (project / ".docker.env").exists()


def test_missing_buildx_fails_before_generating_credentials(tmp_path):
    project, result = launch(tmp_path, failure="buildx")
    assert result.returncode != 0 and not (project / ".docker.env").exists()
    assert "Buildx" in result.stderr


def test_repeat_start_preserves_credentials_and_changes_port_only(tmp_path):
    project, first = launch(tmp_path)
    assert first.returncode == 0, first.stderr
    config = project / ".docker.env"
    before = config.read_text().splitlines()
    _, second = launch(tmp_path, port="18001")
    assert second.returncode == 0, second.stderr
    after = config.read_text().splitlines()
    assert before[:2] == after[:2]
    assert after[2] == "DQ_HTTP_PORT=18001"
    assert config.stat().st_mode & 0o777 == 0o600


def test_lost_credentials_with_existing_data_does_not_reset(tmp_path):
    project, result = launch(tmp_path, volumes="dq-desktop_dq_mysql")
    assert result.returncode != 0 and not (project / ".docker.env").exists()
    assert "Restore" in result.stderr


def test_failed_build_does_not_report_ready_or_delete_config(tmp_path):
    project, result = launch(tmp_path, failure="up")
    assert result.returncode != 0 and "Ready:" not in result.stdout
    assert (project / ".docker.env").exists()


def test_invalid_port_rejected_before_writing_credentials(tmp_path):
    project, result = launch(tmp_path, port="99999")
    assert result.returncode != 0 and not (project / ".docker.env").exists()

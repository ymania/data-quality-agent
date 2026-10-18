"""Local setup must never expose or overwrite saved secrets by accident."""

import os

import pytest

from app import settings


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ENV_FILE", tmp_path / ".env")
    for key in settings.DEFAULTS:
        monkeypatch.delenv(key, raising=False)
    return settings.ENV_FILE


def test_save_keeps_blank_secrets_and_returns_only_flags(isolated_env):
    first = settings.save_settings({
        "MODEL_NAME": "deepseek-flash", "MODEL_BASE_URL": "https://api.deepseek.com",
        "MODEL_API_KEY": "private-test-key", "MYSQL_PASSWORD": "private-db-password",
    })
    assert first["model_api_key_set"] and first["mysql_password_set"]
    assert "private-test-key" not in str(first)
    assert "private-db-password" not in str(first)
    assert os.stat(isolated_env).st_mode & 0o777 == 0o600
    second = settings.save_settings({"MODEL_NAME": "another-model", "MODEL_API_KEY": "", "MYSQL_PASSWORD": ""})
    assert second["model_name"] == "another-model"
    assert "MODEL_API_KEY=\"private-test-key\"" in isolated_env.read_text()
    assert "MYSQL_PASSWORD=\"private-db-password\"" in isolated_env.read_text()


def test_invalid_values_and_symlink_are_rejected(isolated_env, tmp_path):
    with pytest.raises(ValueError, match="端口"):
        settings.save_settings({"MYSQL_PORT": "70000"})
    with pytest.raises(ValueError, match="格式"):
        settings.save_settings({"MODEL_API_KEY": "line\nbreak"})
    isolated_env.symlink_to(tmp_path / "other")
    with pytest.raises(ValueError, match="符号链接"):
        settings.save_settings({"MODEL_NAME": "safe"})

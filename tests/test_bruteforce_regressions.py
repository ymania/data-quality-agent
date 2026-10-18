"""Regression tests for the 2026-10-17 brute-force round (phase 2 findings)."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import SettingsRequest, app


def _rule_payload(**overrides):
    payload = {"name": "回归：会话ID超长", "table_name": "demo_orders",
               "column_name": "customer_name", "rule_type": "NOT_NULL", "params": {}}
    payload.update(overrides)
    return payload


def test_rule_creation_rejects_session_id_over_64():
    with TestClient(app) as client:
        response = client.post("/api/rules", json=_rule_payload(session_id="s" * 65))
    assert response.status_code == 422  # was 503 with a misleading MySQL error
    assert "session_id" in response.text


def test_rule_run_rejects_session_id_over_64():
    with TestClient(app) as client:
        response = client.post("/api/rules/1/run", json={"session_id": "s" * 65})
    assert response.status_code == 422  # was 503 with a misleading MySQL error


def test_rule_creation_accepts_session_id_64_boundary():
    with TestClient(app) as client:
        response = client.post("/api/rules", json=_rule_payload(
            name="回归：会话ID64边界", session_id="s" * 64))
    assert response.status_code == 200
    assert response.json()["rule_id"] > 0


def test_settings_request_rejects_unknown_keys():
    # was: unknown keys silently dropped and /api/settings returned 200
    with pytest.raises(ValidationError):
        SettingsRequest(foo="bar")


def test_settings_request_still_accepts_known_keys():
    request = SettingsRequest(mysql_port=3306)
    assert request.mysql_port == 3306

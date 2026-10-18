"""Faker generation properties; no database connection required."""

import pytest

pytest.importorskip("faker")

from scripts.generate_orders import Options, preview


def test_seed_repeats_rows_and_quality_counts():
    options = Options(
        rows=1000, seed=20261016, start_id=1001, batch_size=100,
        customer_error_rate=0.03, status_error_rate=0.02, status_null_rate=0.01,
    )
    first = preview(options).as_dict(options)
    second = preview(options).as_dict(options)
    assert first == second
    assert first["rows"] == 1000
    assert first["start_id"] == 1001 and first["end_id"] == 2000
    name = first["customer_not_null"]
    status = first["status_enum"]
    assert name["checked"] == name["passed"] + name["failed"] == 1000
    assert status["checked"] + status["skipped"] == 1000
    assert status["checked"] == status["passed"] + status["failed"]
    assert 0 < name["failed"] < 1000
    assert 0 < status["failed"] < 1000


def test_zero_checked_status_is_reported_as_na():
    options = Options(
        rows=10, seed=1, start_id=1, batch_size=10,
        customer_error_rate=0, status_error_rate=0, status_null_rate=1,
    )
    report = preview(options).as_dict(options)
    assert report["status_enum"] == {
        "checked": 0, "passed": 0, "failed": 0, "skipped": 10, "pass_rate": None,
    }

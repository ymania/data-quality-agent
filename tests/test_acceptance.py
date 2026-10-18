"""Run after sql/schema.sql and sql/seed.sql; these are real MySQL integration tests."""

import json
import uuid

import pytest

from app import quality, settings  # load the configured demo .env before connecting
from app.db import connect


def _insert(order_id, customer_name, order_status):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO demo_orders (order_id,customer_name,order_status,amount,created_at) "
                "VALUES (%s,%s,%s,1.00,'2026-01-02 00:00:00')",
                (order_id, customer_name, order_status),
            )
        conn.commit()


def _delete(order_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM demo_orders WHERE order_id=%s", (order_id,))
        conn.commit()


def test_baseline_counts_and_immutable_history():
    session = "pytest-baseline"
    nonnull = quality.create_rule("验收：客户名非空", "demo_orders", "customer_name", "NOT_NULL", {}, session)
    enum = quality.create_rule("验收：状态值域", "demo_orders", "order_status", "ENUM",
                               {"allowed_values": ["NEW", "PAID", "CANCELLED"]}, session)
    first_name = quality.run_rule(nonnull["rule_id"], session)
    first_status = quality.run_rule(enum["rule_id"], session)
    assert (first_name["total_count"], first_name["checked_count"], first_name["passed_count"],
            first_name["failed_count"], first_name["skipped_count"], first_name["pass_rate"]) == (20, 20, 17, 3, 0, "85.00")
    assert (first_status["total_count"], first_status["checked_count"], first_status["passed_count"],
            first_status["failed_count"], first_status["skipped_count"], first_status["pass_rate"]) == (20, 19, 17, 2, 1, "89.47")
    assert [row["order_id"] for row in first_name["samples"]] == [1, 2, 3]
    assert [row["field_value"] for row in first_name["samples"]] == [None, "", "   "]
    assert [row["order_id"] for row in first_status["samples"]] == [4, 5]
    before = json.dumps(quality.get_result(execution_id=first_name["execution_id"]), sort_keys=True)
    before_status = json.dumps(quality.get_result(execution_id=first_status["execution_id"]), sort_keys=True)
    added_id = 10**15 + (uuid.uuid4().int % 10**12)
    inserted = False
    try:
        _insert(added_id, None, "UNKNOWN")
        inserted = True
        second_name = quality.run_rule(nonnull["rule_id"], session)
        second_status = quality.run_rule(enum["rule_id"], session)
        assert (second_name["total_count"], second_name["failed_count"]) == (21, 4)
        assert (second_status["total_count"], second_status["failed_count"]) == (21, 3)
        assert second_name["execution_id"] != first_name["execution_id"]
        assert json.dumps(quality.get_result(execution_id=first_name["execution_id"]), sort_keys=True) == before
        assert json.dumps(quality.get_result(execution_id=first_status["execution_id"]), sort_keys=True) == before_status
        assert quality.get_result(rule_id=nonnull["rule_id"], latest=True)["execution_id"] == second_name["execution_id"]
    finally:
        if inserted:
            _delete(added_id)


def test_empty_and_all_skipped():
    empty = quality.create_rule("验收：空表", "demo_empty_orders", "customer_name", "NOT_NULL", {})
    result = quality.run_rule(empty["rule_id"])
    assert (result["total_count"], result["checked_count"], result["pass_rate"], result["samples"]) == (0, 0, None, [])
    nulls = quality.create_rule("验收：全部跳过", "demo_null_orders", "order_status", "ENUM",
                                {"allowed_values": ["NEW"]})
    result = quality.run_rule(nulls["rule_id"])
    assert (result["total_count"], result["checked_count"], result["skipped_count"], result["pass_rate"]) == (3, 0, 3, None)


def test_invalid_config_and_ids():
    with pytest.raises(quality.InvalidRule):
        quality.create_rule("非法表", "missing_table", "customer_name", "NOT_NULL", {})
    with pytest.raises(quality.InvalidRule):
        quality.create_rule("非法字段", "demo_orders", "missing_column", "NOT_NULL", {})
    with pytest.raises(quality.InvalidRule):
        quality.create_rule("缺少值域", "demo_orders", "order_status", "ENUM", {})
    with pytest.raises(quality.MissingResource):
        quality.run_rule(999999999)
    with pytest.raises(quality.MissingResource):
        quality.get_result(execution_id=999999999)


def test_enum_is_byte_exact_and_sample_is_capped():
    rule = quality.create_rule("验收：精确值域", "demo_orders", "order_status", "ENUM",
                               {"allowed_values": ["NEW", "PAID", "CANCELLED"]})
    base = 10**15 + (uuid.uuid4().int % 10**12)
    ids = list(range(base, base + 25))
    inserted = []
    try:
        for order_id in ids:
            _insert(order_id, "临时客户", "new" if order_id % 2 else "PAID ")
            inserted.append(order_id)
        result = quality.run_rule(rule["rule_id"])
        assert result["total_count"] == 45
        assert result["failed_count"] == 27
        assert len(result["samples"]) == 20
    finally:
        for order_id in inserted:
            _delete(order_id)

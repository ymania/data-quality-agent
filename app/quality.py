"""Deterministic quality rule service shared by HTTP endpoints and agent tools."""

import json
import re
from decimal import Decimal, ROUND_HALF_UP

from app.db import connect

SUPPORTED_TABLES = {"demo_orders", "demo_empty_orders", "demo_null_orders", "demo_orders_faker", "uploaded_orders"}
STRING_TYPES = {"char", "varchar", "tinytext", "text", "mediumtext", "longtext"}
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class InvalidRule(ValueError):
    pass


class MissingResource(LookupError):
    pass


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _norm(row):
    """MySQL 8 returns information_schema column labels in UPPERCASE; normalize."""
    return {key.lower(): value for key, value in row.items()} if row else row


def _identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise InvalidRule("表名和字段名必须是合法的 SQL 标识符")
    return f"`{value}`"


def _rule(row):
    if not row:
        return None
    return {
        "rule_id": row["id"],
        "dataset_id": row.get("dataset_id"),
        "name": row["name"],
        "table_name": row["table_name"],
        "column_name": row["column_name"],
        "rule_type": row["rule_type"],
        "params": _json(row["params_json"]),
        "created_at": row["created_at"].isoformat(timespec="seconds"),
    }


def describe_schema():
    """Return supported demo tables and columns for the model and page."""
    with connect() as conn:
        with conn.cursor() as cur:
            placeholders = ",".join("%s" for _ in SUPPORTED_TABLES)
            cur.execute(
                "SELECT table_name, column_name, data_type, is_nullable "
                "FROM information_schema.columns WHERE table_schema = DATABASE() "
                f"AND table_name IN ({placeholders}) ORDER BY table_name, ordinal_position",
                tuple(sorted(SUPPORTED_TABLES)),
            )
            return [_norm(row) for row in cur.fetchall()]


def _validate_target(cur, table_name, column_name):
    _identifier(table_name)
    _identifier(column_name)
    if table_name not in SUPPORTED_TABLES:
        raise InvalidRule(f"不支持数据表 {table_name}；可用表：{', '.join(sorted(SUPPORTED_TABLES))}")
    cur.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
        (table_name, column_name),
    )
    column = cur.fetchone()
    if not column:
        raise InvalidRule(f"字段 {table_name}.{column_name} 不存在")
    if column_name == "order_id":
        raise InvalidRule("order_id 是样例主键，请选择需要校验的业务字段")
    return _norm(column)["data_type"].lower()


def create_rule(name, table_name, column_name, rule_type, params=None, session_id=None, dataset_id=None):
    """Validate and persist one rule. An invalid rule never reaches the database."""
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise InvalidRule("规则名称不能为空，且最多 120 个字符")
    if rule_type not in {"NOT_NULL", "ENUM"}:
        raise InvalidRule("规则类型只支持 NOT_NULL 和 ENUM")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise InvalidRule("规则参数必须是对象")
    if rule_type == "NOT_NULL":
        if params:
            raise InvalidRule("非空规则不接受额外参数")
    else:
        values = params.get("allowed_values")
        if set(params) != {"allowed_values"} or not isinstance(values, list) or not 1 <= len(values) <= 100:
            raise InvalidRule("值域规则需要 1 到 100 个 allowed_values")
        if any(not isinstance(v, str) or len(v) > 255 for v in values):
            raise InvalidRule("允许值必须是长度不超过 255 的字符串")
        if len(values) != len(set(values)):
            raise InvalidRule("允许值不能重复")
    from app import datasets
    datasets.ensure_schema()
    if table_name == "uploaded_orders":
        if not isinstance(dataset_id, int) or isinstance(dataset_id, bool) or dataset_id < 1:
            raise InvalidRule("上传订单必须指定有效的 dataset_id")
        datasets.get_dataset(dataset_id)
    elif dataset_id is not None:
        raise InvalidRule("只有 uploaded_orders 可指定 dataset_id")
    with connect() as conn:
        try:
            with conn.cursor() as cur:
                data_type = _validate_target(cur, table_name, column_name)
                if data_type not in STRING_TYPES:
                    raise InvalidRule("当前演示只支持字符串字段")
                cur.execute(
                    "INSERT INTO quality_rules "
                    "(name, table_name, column_name, rule_type, params_json, created_session_id, dataset_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (name.strip(), table_name, column_name, rule_type,
                     json.dumps(params, ensure_ascii=False), session_id, dataset_id),
                )
                rule_id = cur.lastrowid
                cur.execute("SELECT * FROM quality_rules WHERE id = %s", (rule_id,))
                result = _rule(cur.fetchone())
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise


def list_rules(limit=100, before_id=None):
    with connect() as conn:
        with conn.cursor() as cur:
            if before_id is None:
                cur.execute("SELECT * FROM quality_rules ORDER BY id DESC LIMIT %s",
                            (min(max(int(limit), 1), 100),))
            else:
                cur.execute("SELECT * FROM quality_rules WHERE id < %s ORDER BY id DESC LIMIT %s",
                            (int(before_id), min(max(int(limit), 1), 100)))
            return [_rule(row) for row in cur.fetchall()]


def get_rule(rule_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM quality_rules WHERE id = %s", (rule_id,))
            row = cur.fetchone()
    if not row:
        raise MissingResource(f"规则 ID {rule_id} 不存在")
    return _rule(row)


def build_predicates(rule):
    """Build SQL only from validated identifiers and parameter placeholders."""
    table = rule["table_name"]
    column = rule["column_name"]
    if table not in SUPPORTED_TABLES:
        raise InvalidRule("规则引用了不受支持的数据表")
    q_table, q_col = _identifier(table), _identifier(column)
    if rule["rule_type"] == "NOT_NULL":
        return q_table, "0", f"({q_col} IS NULL OR TRIM({q_col}) = '')", []
    if rule["rule_type"] == "ENUM":
        values = rule["params"].get("allowed_values", [])
        if not values:
            raise InvalidRule("已保存的值域规则缺少允许值")
        placeholders = ",".join("CAST(%s AS BINARY)" for _ in values)
        # Byte comparison avoids MySQL's case-insensitive and PAD SPACE collations.
        failed = f"({q_col} IS NOT NULL AND CAST({q_col} AS BINARY) NOT IN ({placeholders}))"
        return q_table, f"({q_col} IS NULL)", failed, values
    raise InvalidRule("已保存的规则类型不受支持")


def _result(row):
    if not row:
        return None
    snapshot = _json(row["rule_snapshot_json"])
    return {
        "execution_id": row["id"],
        "rule_id": row["rule_id"],
        "rule_name": snapshot["name"],
        "rule_snapshot": snapshot,
        "executed_at": row["executed_at"].isoformat(timespec="seconds"),
        "status": row["status"],
        "total_count": row["total_count"],
        "checked_count": row["checked_count"],
        "passed_count": row["passed_count"],
        "failed_count": row["failed_count"],
        "skipped_count": row["skipped_count"],
        "pass_rate": str(row["pass_rate"]) if row["pass_rate"] is not None else None,
        "samples": _json(row["samples_json"]) or [],
        "error": row["error_text"],
    }


def run_rule(rule_id, session_id=None):
    """Run count and sample queries against one consistent MySQL snapshot."""
    rule = get_rule(rule_id)
    table, skip, failed, values = build_predicates(rule)
    column = _identifier(rule["column_name"])
    scope, scope_values = "1=1", []
    if rule["table_name"] == "uploaded_orders":
        if not rule.get("dataset_id"):
            raise InvalidRule("上传订单规则缺少数据集 ID，拒绝跨数据集扫描")
        scope, scope_values = "dataset_id=%s", [rule["dataset_id"]]
    snapshot_json = json.dumps(rule, ensure_ascii=False)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO quality_runs (rule_id, session_id, status, rule_snapshot_json) "
                "VALUES (%s,%s,'RUNNING',%s)",
                (rule_id, session_id, snapshot_json),
            )
            execution_id = cur.lastrowid
        conn.commit()

    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
                cur.execute(
                    f"SELECT COUNT(*) AS total_count, "
                    f"COALESCE(SUM(CASE WHEN {skip} THEN 1 ELSE 0 END),0) AS skipped_count, "
                    f"COALESCE(SUM(CASE WHEN {failed} THEN 1 ELSE 0 END),0) AS failed_count "
                    f"FROM {table} WHERE {scope}",
                    tuple(values + scope_values),
                )
                counts = cur.fetchone()
                total = int(counts["total_count"])
                skipped = int(counts["skipped_count"])
                failures = int(counts["failed_count"])
                checked = total - skipped
                passed = checked - failures
                if min(total, skipped, failures, checked, passed) < 0 or checked != passed + failures:
                    raise RuntimeError("校验统计不一致")
                cur.execute(
                    f"SELECT `order_id`, {column} AS field_value FROM {table} "
                    f"WHERE {failed} AND {scope} ORDER BY `order_id` LIMIT 20",
                    tuple(values + scope_values),
                )
                samples = [
                    {"order_id": row["order_id"], "field_value": row["field_value"]}
                    for row in cur.fetchall()
                ]
                rate = (
                    (Decimal(passed) * 100 / Decimal(checked)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    if checked else None
                )
                cur.execute(
                    "UPDATE quality_runs SET status='SUCCEEDED', total_count=%s, checked_count=%s, "
                    "passed_count=%s, failed_count=%s, skipped_count=%s, pass_rate=%s, "
                    "samples_json=%s WHERE id=%s",
                    (total, checked, passed, failures, skipped, rate,
                     json.dumps(samples, ensure_ascii=False), execution_id),
                )
            conn.commit()
    except Exception as exc:
        # A total database outage cannot be persisted; the HTTP layer reports it.
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE quality_runs SET status='FAILED', error_text=%s WHERE id=%s",
                    (str(exc)[:4000], execution_id),
                )
            conn.commit()
    return get_result(execution_id=execution_id)


def get_result(execution_id=None, rule_id=None, latest=False):
    if execution_id is None and (rule_id is None or not latest):
        raise InvalidRule("请提供执行 ID，或规则 ID 并指定 latest=true")
    with connect() as conn:
        with conn.cursor() as cur:
            if execution_id is not None:
                cur.execute("SELECT * FROM quality_runs WHERE id=%s", (execution_id,))
            else:
                cur.execute("SELECT * FROM quality_runs WHERE rule_id=%s ORDER BY id DESC LIMIT 1", (rule_id,))
            row = cur.fetchone()
    if not row:
        raise MissingResource(f"执行记录不存在：{execution_id if execution_id is not None else f'规则 {rule_id}'}")
    return _result(row)


def list_results(limit=30, before_id=None):
    with connect() as conn:
        with conn.cursor() as cur:
            if before_id is None:
                cur.execute("SELECT * FROM quality_runs ORDER BY id DESC LIMIT %s",
                            (min(max(int(limit), 1), 100),))
            else:
                cur.execute("SELECT * FROM quality_runs WHERE id < %s ORDER BY id DESC LIMIT %s",
                            (int(before_id), min(max(int(limit), 1), 100)))
            return [_result(row) for row in cur.fetchall()]


def recent_session(session_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name FROM quality_rules WHERE created_session_id=%s ORDER BY id DESC LIMIT 5",
                (session_id,),
            )
            rules = cur.fetchall()
            cur.execute(
                "SELECT id, rule_id, status FROM quality_runs WHERE session_id=%s ORDER BY id DESC LIMIT 5",
                (session_id,),
            )
            runs = cur.fetchall()
    return {"recent_rules": rules, "recent_runs": runs}


def recent_task(session_id):
    """Find the last user request that changed rules or executions."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, trace_json FROM chat_messages WHERE session_id=%s AND role='user' "
                "AND trace_json IS NOT NULL ORDER BY id DESC LIMIT 100",
                (session_id,),
            )
            rows = cur.fetchall()
    for row in rows:
        rules, runs = [], []
        for trace in _json(row["trace_json"]) or []:
            data = (trace.get("output") or {}).get("data") or {}
            if not isinstance(data, dict):
                continue
            if trace.get("tool") == "create_quality_rule" and data.get("rule_id"):
                rules.append(data["rule_id"])
            if trace.get("tool") == "run_quality_rule" and data.get("execution_id"):
                runs.append(data["execution_id"])
        if rules or runs:
            return {"task_id": row["id"], "rule_ids": rules, "execution_ids": runs}
    return {"task_id": None, "rule_ids": [], "execution_ids": []}


def session_context(session_id):
    return {**recent_session(session_id), "latest_task": recent_task(session_id)}


def begin_chat(session_id, user_text):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_messages (session_id, role, content, trace_json) "
                "VALUES (%s,'user',%s,'[]')", (session_id, user_text),
            )
            chat_id = cur.lastrowid
        conn.commit()
    return chat_id


def record_chat_progress(chat_id, traces):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE chat_messages SET trace_json=%s WHERE id=%s AND role='user'",
                        (json.dumps(traces, ensure_ascii=False, default=str), chat_id))
        conn.commit()


def finish_chat(chat_id, session_id, reply, traces):
    with connect() as conn:
        with conn.cursor() as cur:
            # The task remains discoverable from the user row, including after
            # a partial failure; keep its trace on both rows for easy recovery.
            cur.execute("UPDATE chat_messages SET trace_json=%s WHERE id=%s AND role='user'",
                        (json.dumps(traces, ensure_ascii=False, default=str), chat_id))
            cur.execute(
                "INSERT INTO chat_messages (session_id, role, content, trace_json) "
                "VALUES (%s,'assistant',%s,%s)",
                (session_id, reply, json.dumps(traces, ensure_ascii=False, default=str)),
            )
        conn.commit()


def manual_action(session_id, description, tool_name, action):
    """Record button actions in the same session context as agent actions."""
    if not session_id:
        return action()
    chat_id = begin_chat(session_id, description)
    try:
        data = action()
        failed = tool_name == "run_quality_rule" and data["status"] != "SUCCEEDED"
        output = {"ok": not failed, "data": data}
        if failed:
            output["error"] = data.get("error") or "规则执行未成功"
        reply = (f"执行 #{data['execution_id']}：{data['status']}" if tool_name == "run_quality_rule"
                 else f"已创建规则 #{data['rule_id']}")
    except Exception as exc:
        output = {"ok": False, "error": str(exc)}
        reply = "页面操作失败：" + str(exc)
        trace = {"tool": tool_name, "status": "error", "summary": reply, "output": output}
        record_chat_progress(chat_id, [trace])
        finish_chat(chat_id, session_id, reply, [trace])
        raise
    trace = {"tool": tool_name, "status": "error" if failed else "ok",
             "summary": reply, "output": output}
    record_chat_progress(chat_id, [trace])
    finish_chat(chat_id, session_id, reply, [trace])
    return data


def save_chat(session_id, user_text, reply, traces):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_messages (session_id, role, content, trace_json) VALUES (%s,'user',%s,NULL)",
                (session_id, user_text),
            )
            cur.execute(
                "INSERT INTO chat_messages (session_id, role, content, trace_json) VALUES (%s,'assistant',%s,%s)",
                (session_id, reply, json.dumps(traces, ensure_ascii=False)),
            )
        conn.commit()


def chat_history(session_id, limit=40):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, role, content, trace_json, created_at FROM "
                "(SELECT * FROM chat_messages WHERE session_id=%s ORDER BY id DESC LIMIT %s) AS recent "
                "ORDER BY id ASC",
                (session_id, min(max(int(limit), 1), 100)),
            )
            rows = cur.fetchall()
            return [
                {"id": row["id"], "role": row["role"], "content": row["content"],
                 "traces": (_json(row["trace_json"]) or []) if (
                     row["role"] == "assistant" or index + 1 == len(rows) or rows[index + 1]["role"] != "assistant"
                 ) else [],
                 "created_at": row["created_at"].isoformat(timespec="seconds")}
                for index, row in enumerate(rows)
            ]

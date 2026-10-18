"""Exercise the failures that previously hid completed work or broke follow-ups."""

import json
from types import SimpleNamespace

import pytest

from app import agent, model_client


@pytest.fixture
def model_environment(monkeypatch):
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MODEL_NAME", "deepseek-flash")
    monkeypatch.setenv("MODEL_API_KEY", "dummy-test-key")
    monkeypatch.setenv("MODEL_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.delenv("MODEL_PROXY_URL", raising=False)


def test_system_http_proxy_wins_over_invalid_socks_fallback(monkeypatch, model_environment):
    monkeypatch.setenv("MODEL_PROXY_MODE", "auto")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:7892")
    model = model_client.build_model()  # constructor only; no model request
    assert model.model_name == "deepseek-flash"


def test_unsupported_proxy_is_actionable(model_environment, monkeypatch):
    monkeypatch.setenv("MODEL_PROXY_MODE", "auto")
    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:7892")
    with pytest.raises(model_client.ModelUnavailable, match="/setup"):
        model_client.build_model()


def _isolate_chat(monkeypatch, context):
    monkeypatch.setattr(agent, "build_model", lambda: object())
    monkeypatch.setattr(agent.quality, "session_context", lambda _session: context)
    monkeypatch.setattr(agent.quality, "chat_history", lambda _session: [])
    monkeypatch.setattr(agent.quality, "begin_chat", lambda _session, _text: 500)
    monkeypatch.setattr(agent.quality, "record_chat_progress", lambda _id, _traces: None)
    agent._seen_sessions.discard("resilience-test")


def test_partial_tool_writes_survive_later_agent_failure(monkeypatch):
    _isolate_chat(monkeypatch, {"recent_rules": [], "recent_runs": [],
                              "latest_task": {"task_id": None, "rule_ids": [], "execution_ids": []}})
    saved = []
    monkeypatch.setattr(agent.quality, "create_rule", lambda *args: {"rule_id": 10})
    monkeypatch.setattr(agent.quality, "run_rule", lambda *args: {
        "execution_id": 20, "status": "FAILED", "error": "simulated SQL failure"})
    monkeypatch.setattr(agent.quality, "finish_chat", lambda *args: saved.append(args))

    class Graph:
        def invoke(self, _input, config):
            tools = Graph.tools
            json.loads(next(t for t in tools if t.name == "create_quality_rule").invoke({
                "name": "客户名非空", "table_name": "demo_orders", "column_name": "customer_name",
                "rule_type": "NOT_NULL", "params": {}}))
            failed = json.loads(next(t for t in tools if t.name == "run_quality_rule").invoke({"rule_id": 10}))
            assert failed["ok"] is False
            raise RuntimeError("model interrupted after tools")

    def make_graph(*, tools, **_kwargs):
        Graph.tools = tools
        return Graph()

    monkeypatch.setattr(agent, "create_deep_agent", make_graph)
    result = agent.chat("resilience-test", "创建并运行")
    assert result["status"] == "failed"
    assert [trace["status"] for trace in result["traces"]] == ["ok", "error"]
    assert saved[0][0] == 500
    assert len(saved[0][3]) == 2


def test_just_now_reads_both_runs_from_combined_task(monkeypatch):
    _isolate_chat(monkeypatch, {"recent_rules": [], "recent_runs": [{"id": 22}],
                              "latest_task": {"task_id": 400, "rule_ids": [11, 12],
                                              "execution_ids": [21, 22]}})
    fetched = []

    def get_result(execution_id, rule_id, latest):
        fetched.append(execution_id)
        return {"execution_id": execution_id, "status": "SUCCEEDED"}

    monkeypatch.setattr(agent.quality, "get_result", get_result)
    monkeypatch.setattr(agent.quality, "finish_chat", lambda *args: None)

    class Graph:
        def invoke(self, payload, config):
            assert "21" in payload["messages"][-1]["content"]
            assert "22" in payload["messages"][-1]["content"]
            return {"messages": [SimpleNamespace(content="两次执行均已查询") ]}

    monkeypatch.setattr(agent, "create_deep_agent", lambda **kwargs: Graph())
    result = agent.chat("resilience-test", "刚才有哪些异常？")
    assert result["status"] == "completed"
    assert fetched == [21, 22]


def _saved_result_trace(**updates):
    data = dict(execution_id=62, rule_id=47, status='SUCCEEDED',
                rule_snapshot={'table_name': 'demo_orders', 'column_name': 'customer_name'},
                total_count=20, checked_count=20, passed_count=17, failed_count=3,
                skipped_count=0, pass_rate='85.00',
                samples=[{'order_id': 1, 'field_value': None},
                         {'order_id': 2, 'field_value': ''},
                         {'order_id': 3, 'field_value': '   '}])
    data.update(updates)
    return {'tool': 'get_quality_result', 'status': 'ok', 'output': {'ok': True, 'data': data}}


def test_compact_reply_preserves_values_and_deduplicates_executions():
    trace = _saved_result_trace()
    reply = agent._compact_result_reply('刚才有哪些异常？', [trace, trace])
    assert reply.count('执行 #62') == 1
    assert '异常 3 条' in reply
    assert '1=NULL' in reply and '2=""（空字符串）' in reply and '3="   "（3 个空格）' in reply
    assert '通过率' not in reply


def test_compact_reply_marks_sample_limit_and_empty_denominator():
    reply = agent._compact_result_reply('查看执行 62 的统计和异常样例', [_saved_result_trace(failed_count=30)])
    assert '异常样例（3/30 条）' in reply
    reply = agent._compact_result_reply('查看执行 62 的结果', [_saved_result_trace(
        total_count=3, checked_count=0, passed_count=0, failed_count=0,
        skipped_count=3, pass_rate=None, samples=[])])
    assert '无可校验数据' in reply and 'None%' not in reply


def test_compact_reply_does_not_hide_failures_or_replace_explanations():
    trace = _saved_result_trace()
    assert agent._compact_result_reply('刚才为什么有异常，怎么修复？', [trace]) is None
    assert agent._compact_result_reply('查看执行 62 的统计', [trace, {'status': 'error'}]) is None
    assert agent._compact_result_reply('查看执行 62 的统计', [_saved_result_trace(status='FAILED')]) is None

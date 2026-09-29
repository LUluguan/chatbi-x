import json

import pytest

from app.agent import ChatAgent, parse_action, single_shot_sql
from app.schema import load_schema


@pytest.fixture
def tables(mini_db):
    return load_schema(mini_db)


def test_parse_action_extracts_json_from_noisy_text():
    act = parse_action('好的，这是结果：\n{"action": "final", "sql": "SELECT 1"}\n以上。')
    assert act == {"action": "final", "sql": "SELECT 1"}


def test_parse_action_returns_none_for_garbage():
    assert parse_action("完全不是 JSON") is None
    assert parse_action('{"action": }') is None


def test_final_directly_executes_sql(mini_db, tables, scripted_provider):
    p = scripted_provider([json.dumps({"action": "final", "sql": "SELECT COUNT(*) AS n FROM users", "summary": "3人"}, ensure_ascii=False)])
    r = ChatAgent(p, tables, mini_db).run("有多少用户")
    assert r.ok
    assert r.rows == [[3]]
    assert r.summary == "3人"
    assert r.error == ""


def test_run_sql_error_triggers_retry_then_final(mini_db, tables, scripted_provider):
    p = scripted_provider([
        json.dumps({"action": "run_sql", "sql": "SELECT nope FROM users"}),
        json.dumps({"action": "run_sql", "sql": "SELECT COUNT(*) AS n FROM users"}),
        json.dumps({"action": "final", "sql": "SELECT COUNT(*) AS n FROM users", "summary": "共3个用户"}, ensure_ascii=False),
    ])
    r = ChatAgent(p, tables, mini_db).run("有多少用户")
    assert r.ok and r.rows == [[3]]
    assert [s["action"] for s in r.steps] == ["run_sql", "run_sql", "final"]
    assert r.steps[0]["ok"] is False and r.steps[1]["ok"] is True


def test_run_sql_success_feedback_echoes_sql_and_allows_refine(mini_db, tables, scripted_provider):
    p = scripted_provider([
        json.dumps({"action": "run_sql", "sql": "SELECT COUNT(*) AS n FROM users"}),
        json.dumps({"action": "final", "sql": "SELECT COUNT(*) AS n FROM users", "summary": "3"}, ensure_ascii=False),
    ])
    r = ChatAgent(p, tables, mini_db).run("有多少用户")
    assert r.ok
    feedback = p.calls[1][-1]["content"]
    # 回显 SQL：便于模型原样定稿而不是重写一个变体
    assert "SELECT COUNT(*) AS n FROM users" in feedback
    # 允许模型在看到结果后继续调整，而不是诱导它把探索性宽查询直接定稿
    assert "恰好" in feedback
    assert "调整" in feedback


def test_final_with_broken_sql_is_not_accepted(mini_db, tables, scripted_provider):
    p = scripted_provider([
        json.dumps({"action": "final", "sql": "SELECT nope FROM users", "summary": "x"}),
        json.dumps({"action": "final", "sql": "SELECT COUNT(*) AS n FROM users", "summary": "3"}, ensure_ascii=False),
    ])
    r = ChatAgent(p, tables, mini_db).run("有多少用户")
    assert r.ok and r.rows == [[3]]
    assert "修正" in p.calls[1][-1]["content"]


def test_get_schema_tool_feeds_table_details_back(mini_db, tables, scripted_provider):
    p = scripted_provider([
        json.dumps({"action": "get_schema", "table": "orders"}),
        json.dumps({"action": "final", "sql": "SELECT COUNT(*) AS n FROM orders", "summary": "3"}, ensure_ascii=False),
    ])
    r = ChatAgent(p, tables, mini_db).run("订单情况")
    assert r.ok
    feedback = p.calls[1][-1]["content"]
    assert "订单表" in feedback  # 中文注释随 get_schema 返回
    assert "created_at" in feedback


def test_invalid_json_output_gets_one_retry(mini_db, tables, scripted_provider):
    p = scripted_provider([
        "我不是 JSON",
        json.dumps({"action": "final", "sql": "SELECT COUNT(*) AS n FROM users", "summary": "3"}, ensure_ascii=False),
    ])
    r = ChatAgent(p, tables, mini_db).run("有多少用户")
    assert r.ok
    assert r.steps[0]["action"] == "invalid"
    assert "只输出一行 JSON" in p.calls[1][-1]["content"]


def test_max_steps_exhausted_reports_failure(mini_db, tables, scripted_provider):
    p = scripted_provider([json.dumps({"action": "run_sql", "sql": "SELECT nope FROM users"})] * 5)
    r = ChatAgent(p, tables, mini_db, max_steps=3).run("有多少用户")
    assert not r.ok
    assert "最大步数" in r.error
    assert len(r.steps) == 3


def test_single_shot_sql_extracts_sql(mini_db, tables, scripted_provider):
    p = scripted_provider([json.dumps({"action": "final", "sql": "SELECT 1"}, ensure_ascii=False)])
    sql = single_shot_sql(p, tables, "任意问题")
    assert sql == "SELECT 1"
    assert "Schema" in p.calls[0][0]["content"]


def test_draft_sql_injected_into_first_user_message(mini_db, tables, scripted_provider):
    draft = "SELECT COUNT(*) AS n FROM users"
    p = scripted_provider([
        json.dumps({"action": "final", "sql": draft, "summary": "3"}, ensure_ascii=False),
    ])
    r = ChatAgent(p, tables, mini_db).run("有多少用户", draft_sql=draft)
    assert r.ok
    first_user = p.calls[0][1]["content"]
    assert draft in first_user
    assert "验证" in first_user


def test_no_draft_keeps_plain_question(mini_db, tables, scripted_provider):
    p = scripted_provider([
        json.dumps({"action": "final", "sql": "SELECT COUNT(*) AS n FROM users", "summary": "3"}, ensure_ascii=False),
    ])
    ChatAgent(p, tables, mini_db).run("有多少用户")
    assert p.calls[0][1]["content"] == "有多少用户"


def test_on_step_callback_receives_steps_as_they_happen(mini_db, tables, scripted_provider):
    p = scripted_provider([
        json.dumps({"action": "run_sql", "sql": "SELECT nope FROM users"}),
        json.dumps({"action": "run_sql", "sql": "SELECT COUNT(*) AS n FROM users"}),
        json.dumps({"action": "final", "sql": "SELECT COUNT(*) AS n FROM users", "summary": "3"}, ensure_ascii=False),
    ])
    seen = []
    r = ChatAgent(p, tables, mini_db).run("有多少用户", on_step=seen.append)
    assert r.ok
    assert [s["action"] for s in seen] == ["run_sql", "run_sql", "final"]
    assert seen == r.steps

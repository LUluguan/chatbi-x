import json

import pytest

from app.config import Settings
from app.mcp_server import TOOLS, make_tools


@pytest.fixture
def tools(tmp_path, mini_db):
    eval_file = tmp_path / "eval.json"
    eval_file.write_text(json.dumps([
        {"question": "有多少个用户", "gold_sql": "SELECT COUNT(*) AS n FROM users"},
    ], ensure_ascii=False), encoding="utf-8")
    s = Settings(db_path=str(mini_db), eval_set_path=str(eval_file))
    return make_tools(s)


def test_tools_registry_declares_four_capabilities():
    assert set(TOOLS) == {"list_tables", "get_schema", "run_sql", "ask"}


def test_make_tools_returns_all_callables(tools):
    assert set(tools) == set(TOOLS)
    assert all(callable(f) for f in tools.values())


def test_list_tables_returns_metadata(tools):
    tables = json.loads(tools["list_tables"]())
    names = [t["name"] for t in tables]
    assert names == ["orders", "users"]
    orders = next(t for t in tables if t["name"] == "orders")
    assert "订单表" in orders["description"]
    assert orders["row_count"] == 3


def test_get_schema_returns_table_details(tools):
    text = tools["get_schema"]("orders")
    assert "订单表" in text
    assert "created_at" in text


def test_get_schema_unknown_table_reports(tools):
    assert "未找到" in tools["get_schema"]("nope")


def test_run_sql_executes_readonly_query(tools):
    r = json.loads(tools["run_sql"]("SELECT COUNT(*) AS n FROM users"))
    assert r["ok"] is True
    assert r["rows"] == [[3]]


def test_run_sql_rejects_write(tools):
    r = json.loads(tools["run_sql"]("DELETE FROM users"))
    assert r["ok"] is False
    assert r["error"]


def test_ask_runs_full_agent(tools):
    r = json.loads(tools["ask"]("请问有多少个用户？"))
    assert r["ok"] is True
    assert r["sql"] == "SELECT COUNT(*) AS n FROM users"
    assert r["rows"] == [[3]]

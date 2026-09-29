import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_settings(tmp_path, mini_db, **kw):
    eval_file = tmp_path / "eval.json"
    eval_file.write_text(json.dumps([
        {"question": "有多少个用户", "gold_sql": "SELECT COUNT(*) AS n FROM users"},
    ], ensure_ascii=False), encoding="utf-8")
    kw.setdefault("llm_provider", "mock")
    return Settings(db_path=str(mini_db), eval_set_path=str(eval_file), **kw)


def test_health_reports_provider_and_tables(tmp_path, mini_db):
    app = create_app(make_settings(tmp_path, mini_db))
    c = TestClient(app)
    r = c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["provider"] == "mock"
    assert body["tables"] == ["orders", "users"]


def test_schema_endpoint_exposes_description(tmp_path, mini_db):
    app = create_app(make_settings(tmp_path, mini_db))
    c = TestClient(app)
    tables = c.get("/api/schema").json()["tables"]
    orders = next(t for t in tables if t["name"] == "orders")
    assert "订单表" in orders["description"]
    assert orders["row_count"] == 3


def test_chat_returns_sql_rows_and_steps(tmp_path, mini_db):
    app = create_app(make_settings(tmp_path, mini_db))
    c = TestClient(app)
    r = c.post("/api/chat", json={"question": "请问有多少个用户？"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["sql"] == "SELECT COUNT(*) AS n FROM users"
    assert body["rows"] == [[3]]
    assert body["columns"] == ["n"]
    assert isinstance(body["steps"], list)
    assert body["elapsed_ms"] >= 0


def test_chat_unknown_question_reports_failure(tmp_path, mini_db):
    app = create_app(make_settings(tmp_path, mini_db))
    c = TestClient(app)
    body = c.post("/api/chat", json={"question": "火星上有多少生命"}).json()
    assert body["ok"] is False
    assert body["error"]


def test_chat_rejects_blank_question(tmp_path, mini_db):
    app = create_app(make_settings(tmp_path, mini_db))
    c = TestClient(app)
    assert c.post("/api/chat", json={"question": ""}).status_code == 422
    body = c.post("/api/chat", json={"question": "   "}).json()
    assert body["ok"] is False


def test_chat_stream_emits_steps_then_result(tmp_path, mini_db):
    app = create_app(make_settings(tmp_path, mini_db))
    c = TestClient(app)
    with c.stream("POST", "/api/chat/stream", json={"question": "请问有多少个用户？"}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())
    assert '"type": "step"' in body
    assert '"type": "result"' in body
    assert "SELECT COUNT(*) AS n FROM users" in body


def test_chat_stream_includes_chart_recommendation(tmp_path, mini_db):
    app = create_app(make_settings(tmp_path, mini_db))
    c = TestClient(app)
    with c.stream("POST", "/api/chat/stream", json={"question": "请问有多少个用户？"}) as resp:
        body = "".join(resp.iter_text())
    assert '"chart"' in body


def test_web_dist_served_when_configured(tmp_path, mini_db):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>chatbi-x</body></html>", encoding="utf-8")
    app = create_app(make_settings(tmp_path, mini_db, web_dist=str(dist)))
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200
    assert "chatbi-x" in r.text
    # API 路由不受静态挂载影响
    assert c.get("/api/health").status_code == 200


def test_web_dist_absent_leaves_api_only(tmp_path, mini_db):
    app = create_app(make_settings(tmp_path, mini_db, web_dist=str(tmp_path / "nope")))
    c = TestClient(app)
    assert c.get("/").status_code == 404
    assert c.get("/api/health").status_code == 200


def test_provider_failure_returns_error_not_500(tmp_path, mini_db):
    s = make_settings(
        tmp_path, mini_db,
        llm_provider="openai_compat",
        llm_base_url="http://127.0.0.1:9/v1",
        llm_api_key="k",
        llm_model="m",
        llm_timeout=1.0,
    )
    app = create_app(s)
    c = TestClient(app)
    r = c.post("/api/chat", json={"question": "有多少个用户"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "LLM" in body["error"]

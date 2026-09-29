import sqlite3

import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def isolate_env_file(monkeypatch):
    """测试永不读取开发者本地 .env：隔离后默认值稳定、环境变量注入仍可用。"""
    cfg = dict(Settings.model_config)
    cfg["env_file"] = None
    monkeypatch.setattr(Settings, "model_config", cfg)


class ScriptedProvider:
    """测试专用：按脚本顺序返回预设响应，并记录每次调用的 messages。"""

    name = "scripted"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, temperature=None):
        self.calls.append(messages)
        return self.responses.pop(0)


@pytest.fixture
def scripted_provider():
    def make(responses):
        return ScriptedProvider(responses)
    return make


@pytest.fixture
def mini_db(tmp_path):
    """小型演示库：2 业务表 + 1 中文注释表（供 linker 做中文-英文桥接）。"""
    db = tmp_path / "mini.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT, city TEXT);
        CREATE TABLE orders(id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, created_at TEXT);
        CREATE TABLE schema_comments(name TEXT PRIMARY KEY, description TEXT);
        INSERT INTO users VALUES (1,'张三','广州'),(2,'李四','深圳'),(3,'王五','广州');
        INSERT INTO orders VALUES (1,1,99.5,'2026-09-01'),(2,2,150.0,'2026-09-02'),(3,1,20.0,'2026-09-03');
        INSERT INTO schema_comments VALUES
         ('users','用户表：姓名与所在城市'),
         ('orders','订单表：用户下单记录，含金额与日期');
        """
    )
    con.commit()
    con.close()
    return str(db)

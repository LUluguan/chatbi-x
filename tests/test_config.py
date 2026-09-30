from app.config import Settings, PROJECT_ROOT


def test_defaults_use_mock_provider_and_demo_db():
    s = Settings()
    assert s.llm_provider == "mock"
    assert s.db_path.endswith("demo_ecom.db")
    assert s.max_agent_steps == 6
    assert s.max_rows == 50
    assert s.sql_timeout_ms == 3000


def test_env_prefix_chatbi_overrides(monkeypatch):
    monkeypatch.setenv("CHATBI_LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("CHATBI_LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("CHATBI_MAX_ROWS", "10")
    s = Settings()
    assert s.llm_provider == "openai_compat"
    assert s.llm_model == "deepseek-chat"
    assert s.max_rows == 10


def test_init_kwargs_beat_env(monkeypatch):
    monkeypatch.setenv("CHATBI_MAX_ROWS", "10")
    s = Settings(max_rows=99)
    assert s.max_rows == 99


def test_cors_origins_parse():
    s = Settings(cors_origins="http://a, http://b")
    assert s.cors_origin_list() == ["http://a", "http://b"]


def test_fk_closure_default_off_and_env_toggle(monkeypatch):
    assert Settings().fk_closure is False
    monkeypatch.setenv("CHATBI_FK_CLOSURE", "true")
    assert Settings().fk_closure is True


def test_project_root_points_at_repo():
    assert (PROJECT_ROOT / "pyproject.toml").exists()

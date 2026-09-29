from pathlib import Path

from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    llm_provider: str = "mock"  # mock | openai_compat
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.0
    llm_timeout: float = 60.0
    llm_max_retries: int = 2
    llm_retry_sleep: float = 1.0
    db_path: str = str(PROJECT_ROOT / "data" / "demo_ecom.db")
    datasets_root: str = str(PROJECT_ROOT / "data" / "bird")
    eval_set_path: str = str(PROJECT_ROOT / "data" / "eval" / "demo_eval.json")
    max_agent_steps: int = 6
    max_rows: int = 50
    sql_timeout_ms: int = 3000
    top_k_tables: int = 4
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    web_dist: str = ""  # 设置为前端构建产物目录时，由 API 直接托管前端（容器部署用）

    model_config = {"env_file": ".env", "env_prefix": "CHATBI_", "extra": "ignore"}

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

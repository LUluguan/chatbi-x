import json
from pathlib import Path

from .mock import MockProvider
from .openai_compat import OpenAICompatProvider, ProviderError

__all__ = ["MockProvider", "OpenAICompatProvider", "ProviderError", "build_provider"]


def load_canned_from_eval_set(path: str) -> dict[str, str]:
    """从评测集 JSON 读取 {question: gold_sql}，供 mock provider 零配置演示。"""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        items = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out = {}
    for item in items if isinstance(items, list) else []:
        q, sql = item.get("question"), item.get("gold_sql") or item.get("SQL")
        if q and sql:
            out[q] = sql
    return out


def build_provider(settings):
    if settings.llm_provider == "mock":
        return MockProvider(load_canned_from_eval_set(settings.eval_set_path))
    if settings.llm_provider == "openai_compat":
        return OpenAICompatProvider(
            settings.llm_base_url, settings.llm_api_key, settings.llm_model,
            temperature=settings.llm_temperature, timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries, retry_sleep=settings.llm_retry_sleep,
        )
    raise ValueError(f"未知 llm_provider: {settings.llm_provider}")

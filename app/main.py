"""ChatBI-X API 服务。

启动: python -m uvicorn app.main:app --port 8000
"""

import json
import queue
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agent import ChatAgent
from .chart import recommend_chart
from .config import Settings
from .linker import rank_tables
from .providers import ProviderError, build_provider
from .schema import load_schema


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)


def _payload(r) -> dict:
    return {
        "ok": r.ok, "sql": r.sql, "summary": r.summary,
        "columns": r.columns, "rows": r.rows,
        "chart": recommend_chart(r.columns, r.rows),
        "steps": r.steps, "error": r.error, "elapsed_ms": r.elapsed_ms,
    }


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings()
    if not Path(s.db_path).exists():
        raise RuntimeError(
            f"数据库不存在: {s.db_path} —— 先运行 python scripts/make_demo_db.py 或设置 CHATBI_DB_PATH"
        )
    provider = build_provider(s)
    all_tables = load_schema(s.db_path)

    def agent_for(question: str) -> ChatAgent:
        # 每个 question 动态做 schema linking，只把最相关的表放进上下文
        linked = rank_tables(all_tables, question, k=s.top_k_tables)
        return ChatAgent(
            provider, linked, s.db_path,
            max_steps=s.max_agent_steps, max_rows=s.max_rows, timeout_ms=s.sql_timeout_ms,
        )

    app = FastAPI(title="ChatBI-X", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list(),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "provider": provider.name, "db": s.db_path,
                "tables": [t.name for t in all_tables]}

    @app.get("/api/schema")
    def schema():
        return {"tables": [
            {"name": t.name, "row_count": t.row_count, "columns": t.columns, "description": t.description}
            for t in all_tables
        ]}

    @app.post("/api/chat")
    def chat(req: ChatRequest):
        question = req.question.strip()
        if not question:
            return {"ok": False, "error": "问题不能为空"}
        try:
            r = agent_for(question).run(question)
        except ProviderError as e:
            return {"ok": False, "error": str(e)}
        return _payload(r)

    @app.post("/api/chat/stream")
    def chat_stream(req: ChatRequest):
        question = req.question.strip()
        if not question:
            return {"ok": False, "error": "问题不能为空"}
        agent = agent_for(question)

        def gen():
            events: queue.Queue = queue.Queue()

            def worker():
                try:
                    r = agent.run(question, on_step=lambda s: events.put(("step", s)))
                    events.put(("result", _payload(r)))
                except ProviderError as e:
                    events.put(("result", {"ok": False, "error": str(e)}))

            threading.Thread(target=worker, daemon=True).start()
            while True:
                kind, payload = events.get()
                yield _sse({"type": kind, **payload})
                if kind == "result":
                    break

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if s.web_dist and Path(s.web_dist).exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=s.web_dist, html=True), name="web")

    return app


app = create_app()

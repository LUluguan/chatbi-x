"""MCP server：把 ChatBI-X 能力暴露为标准 Model Context Protocol 工具。

运行（stdio）: python -m app.mcp_server
Claude Desktop / 任何 MCP 客户端配置示例:
    {"command": "python", "args": ["-m", "app.mcp_server"], "cwd": "<项目根>"}
"""

import json

from . import executor as exe
from .agent import ChatAgent
from .config import Settings
from .linker import rank_tables
from .providers import build_provider
from .schema import load_schema, table_prompt

TOOLS = ["list_tables", "get_schema", "run_sql", "ask"]


def make_tools(settings: Settings | None = None) -> dict:
    """构建纯函数工具集（可独立单测；main() 只做 MCP 注册）。"""
    s = settings or Settings()
    provider = build_provider(s)
    tables = load_schema(s.db_path)

    def list_tables() -> str:
        return json.dumps(
            [{"name": t.name, "row_count": t.row_count, "description": t.description} for t in tables],
            ensure_ascii=False,
        )

    def get_schema(table: str) -> str:
        for t in tables:
            if t.name == table:
                return table_prompt(t)
        return "未找到表 " + table + "，可用表: " + ", ".join(t.name for t in tables)

    def run_sql(sql: str) -> str:
        r = exe.run_sql(s.db_path, sql, s.max_rows, s.sql_timeout_ms)
        return json.dumps(
            {"ok": r.ok, "columns": r.columns, "rows": r.rows[:20],
             "truncated": r.truncated, "error": r.error},
            ensure_ascii=False,
        )

    def ask(question: str) -> str:
        linked = rank_tables(tables, question, k=s.top_k_tables)
        agent = ChatAgent(provider, linked, s.db_path,
                          max_steps=s.max_agent_steps, max_rows=s.max_rows,
                          timeout_ms=s.sql_timeout_ms)
        r = agent.run(question)
        return json.dumps(
            {"ok": r.ok, "sql": r.sql, "summary": r.summary,
             "columns": r.columns, "rows": r.rows[:20], "error": r.error},
            ensure_ascii=False,
        )

    return {"list_tables": list_tables, "get_schema": get_schema, "run_sql": run_sql, "ask": ask}


def main():
    from mcp.server.fastmcp import FastMCP

    tools = make_tools()
    mcp = FastMCP("chatbi-x")

    mcp.tool()(tools["list_tables"])
    mcp.tool()(tools["get_schema"])
    mcp.tool()(tools["run_sql"])
    mcp.tool()(tools["ask"])

    mcp.run()


if __name__ == "__main__":
    main()

"""只读 SQL 执行器：白名单校验 + 只读连接 + 进度守卫超时 + 行数截断。"""

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

_SELECT_RE = re.compile(r"^\s*(with|select)\b", re.IGNORECASE)
_FORBIDDEN_RE = re.compile(r"\b(pragma|attach|detach|vacuum|reindex)\b", re.IGNORECASE)


@dataclass
class ExecutionResult:
    ok: bool = False
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    error: str = ""


def validate_sql(sql: str) -> str | None:
    """返回拒绝原因；合法返回 None。"""
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        return "空 SQL"
    if ";" in s:
        return "不允许多条语句"
    if not _SELECT_RE.match(s):
        return "只允许 SELECT/WITH 查询"
    if _FORBIDDEN_RE.search(s):
        return "包含禁止的命令"
    return None


def run_sql(db_path: str, sql: str, max_rows: int = 50, timeout_ms: int = 3000) -> ExecutionResult:
    reason = validate_sql(sql)
    if reason:
        return ExecutionResult(error=reason)

    s = sql.strip().rstrip(";").strip()
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    deadline = time.monotonic() + timeout_ms / 1000

    def guard():
        if time.monotonic() > deadline:
            raise TimeoutError("SQL 执行超时")

    con.set_progress_handler(guard, 5000)
    try:
        cur = con.execute(s)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [list(r) for r in cur.fetchmany(max_rows + 1)]
        truncated = len(rows) > max_rows
        rows = rows[:max_rows]
        return ExecutionResult(ok=True, columns=cols, rows=rows, row_count=len(rows), truncated=truncated)
    except TimeoutError:
        return ExecutionResult(error="SQL 执行超时")
    except sqlite3.Error as e:
        # progress handler 抛出的超时会被 sqlite3 转成 OperationalError: interrupted
        if "interrupted" in str(e).lower():
            return ExecutionResult(error="SQL 执行超时")
        return ExecutionResult(error=str(e)[:300])
    finally:
        con.close()

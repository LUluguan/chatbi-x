"""自研 Text2SQL Agent：单条 JSON 工具协议 + 执行反馈自校正循环。

协议（provider 每轮只输出一行 JSON）:
  {"action": "get_schema", "table": "..."}   查表结构与样例
  {"action": "run_sql", "sql": "..."}        执行只读 SQL（失败自动反馈重试）
  {"action": "final", "sql": "...", "summary": "..."}  收尾（SQL 会被再次验证）
"""

import json
import re
import time
from dataclasses import dataclass, field

from . import executor as exe
from .linker import few_shot_text
from .schema import schema_prompt, table_prompt

_JSON_RE = re.compile(r"\{.*\}", re.S)

SYSTEM_TMPL = """你是 Text2SQL 数据分析助手，通过工具回答用户的数据库问题。

数据库 Schema:
{schema}

可用工具（每次只输出一行 JSON）:
{{"action": "get_schema", "table": "表名"}}  查看某表结构与样例值
{{"action": "run_sql", "sql": "SELECT ..."}}  执行只读 SQL，返回列名与预览行

规则:
1. SQL 只能是单条 SELECT/WITH 语句。
2. 不确定列名时先 get_schema 确认，再用 run_sql 验证。
3. 结果列必须恰好是问题要的答案（无多余的探索性列）。run_sql 成功后检查:
   若该查询已完整回答问题，立即返回 {{"action": "final", "sql": "此SQL原样", "summary": "一句话中文结论"}}；
   若还需调整（列太多、条件不对、缺聚合/排序），先 run_sql 新查询，验证通过后再 final。

只输出 JSON，不要输出解释、markdown 代码块或多余文字。"""


def parse_action(text: str) -> dict | None:
    m = _JSON_RE.search(text or "")
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


@dataclass
class AgentResult:
    question: str
    ok: bool = False
    sql: str = ""
    summary: str = ""
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    error: str = ""
    elapsed_ms: int = 0


class ChatAgent:
    def __init__(self, provider, tables, db_path: str, max_steps: int = 6,
                 max_rows: int = 50, timeout_ms: int = 3000, few_shots: list[dict] | None = None):
        self.provider = provider
        self.tables = tables
        self.db_path = db_path
        self.max_steps = max_steps
        self.max_rows = max_rows
        self.timeout_ms = timeout_ms
        self.few_shots = few_shots or []

    def _system(self) -> str:
        sys = SYSTEM_TMPL.format(schema=schema_prompt(self.tables))
        if self.few_shots:
            sys += "\n\n" + few_shot_text(self.few_shots)
        return sys

    def _table_text(self, name: str) -> str:
        for t in self.tables:
            if t.name == name:
                return table_prompt(t)
        return "未找到表 " + name + "，可用表: " + ", ".join(t.name for t in self.tables)

    def _preview(self, r: exe.ExecutionResult) -> str:
        head = f"列: {r.columns}；返回 {r.row_count} 行" + ("（已截断）" if r.truncated else "")
        return head + "\n前几行: " + repr(r.rows[:5])

    def run(self, question: str, draft_sql: str = "", on_step=None) -> AgentResult:
        t0 = time.monotonic()
        res = AgentResult(question=question)

        def emit(step: dict):
            res.steps.append(step)
            if on_step:
                try:
                    on_step(step)
                except Exception:
                    pass  # 观察者异常不影响主流程

        first_user = question
        if draft_sql.strip():
            # propose-verify：以 naive 草案为起点，Agent 只负责验证与修正
            first_user += (
                f"\n\n已有初始 SQL 草案（未验证）:\n{draft_sql.strip()}\n"
                "请先 run_sql 验证草案：结果恰好回答问题则直接 final（原样返回该 SQL）；"
                "有错或列不符则修正后 run_sql 再 final。"
            )
        msgs = [{"role": "system", "content": self._system()}, {"role": "user", "content": first_user}]
        executed: exe.ExecutionResult | None = None
        executed_sql = ""

        for _ in range(self.max_steps):
            text = self.provider.chat(msgs)
            act = parse_action(text)
            if not isinstance(act, dict) or not isinstance(act.get("action"), str):
                emit({"action": "invalid", "detail": (text or "")[:120]})
                msgs += [{"role": "assistant", "content": (text or "")[:500]},
                         {"role": "user", "content": "输出不合法，请只输出一行 JSON 工具调用。"}]
                continue

            action = act["action"]
            if action == "get_schema":
                tname = str(act.get("table", ""))
                emit({"action": "get_schema", "detail": tname})
                msgs += [{"role": "assistant", "content": text}, {"role": "user", "content": self._table_text(tname)}]

            elif action == "run_sql":
                sql = str(act.get("sql", ""))
                r = exe.run_sql(self.db_path, sql, self.max_rows, self.timeout_ms)
                emit({"action": "run_sql", "detail": sql[:120], "ok": r.ok})
                if r.ok:
                    executed, executed_sql = r, sql
                    msgs += [{"role": "assistant", "content": text},
                             {"role": "user", "content": (
                                 f"执行成功，结果预览:\n{self._preview(r)}\n"
                                 f"请检查该查询是否恰好回答了问题（结果列就是答案本身，无多余列，行数/排序符合问法）。\n"
                                 f"若是，返回 final，sql 原样用: {sql}\n"
                                 f"若需要调整（列太多、条件不对、缺聚合或排序），先 run_sql 新查询再 final。"
                             )}]
                else:
                    msgs += [{"role": "assistant", "content": text},
                             {"role": "user", "content": f"执行失败: {r.error}\n请修正 SQL 后重新 run_sql。"}]

            elif action == "final":
                sql = str(act.get("sql", ""))
                res.summary = str(act.get("summary", ""))
                if executed is not None and sql.strip() == executed_sql.strip():
                    emit({"action": "final", "detail": sql[:120], "ok": True})
                    res.ok, res.sql, res.columns, res.rows = True, executed_sql, executed.columns, executed.rows
                    break
                r = exe.run_sql(self.db_path, sql, self.max_rows, self.timeout_ms)
                emit({"action": "verify_final", "detail": sql[:120], "ok": r.ok})
                if r.ok:
                    res.ok, res.sql, res.columns, res.rows = True, sql, r.columns, r.rows
                    break
                msgs += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"final 的 SQL 执行失败: {r.error}\n请修正后重新返回 final。"}]

            else:
                msgs += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"未知 action: {action}，请用 get_schema/run_sql/final。"}]
        else:
            if executed is not None:
                res.ok, res.sql, res.columns, res.rows = True, executed_sql, executed.columns, executed.rows
                res.error = "达到最大步数（未收到 final，使用最后成功的查询）"
            else:
                res.error = "达到最大步数，未能得到可执行的 SQL"

        res.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return res


def single_shot_sql(provider, tables, question: str, few_shots: list[dict] | None = None) -> str:
    """朴素基线：一次调用直接要 SQL，无工具循环。用于与 Agent 模式对比评测。"""
    sys = (
        "你是 Text2SQL 引擎。根据下面的数据库 Schema，把用户问题转换为一条 SQLite SELECT 语句。\n"
        '只输出一行 JSON: {"action": "final", "sql": "..."}，不要输出其他内容。\n\n'
        f"Schema:\n{schema_prompt(tables)}"
    )
    if few_shots:
        sys += "\n\n" + few_shot_text(few_shots)
    text = provider.chat([{"role": "system", "content": sys}, {"role": "user", "content": question}])
    act = parse_action(text) or {}
    return str(act.get("sql", ""))

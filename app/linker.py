"""Schema linking：把自然语言问题与表/少样本示例做相关性排序。

中文问题对英文表名没有词面重叠，靠两件事桥接：
1. schema_comments 注释表里的中文业务描述（建库时写入）；
2. 少样本示例的中文问题相似度检索。
"""

import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


def textgrams(text: str) -> Counter:
    text = (text or "").lower()
    grams = _TOKEN_RE.findall(text)
    for run in _CJK_RUN_RE.findall(text):
        grams.extend(run)
        grams.extend(run[i:i + 2] for i in range(len(run) - 1))
    return Counter(grams)


def _sim(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _table_text(t) -> str:
    parts = [t.name, " ".join(c["name"] for c in t.columns), t.description]
    parts.extend(repr(s) for s in t.samples)
    return " ".join(parts)


def rank_tables(tables: list, question: str, k: int = 4) -> list:
    q = textgrams(question)
    return sorted(tables, key=lambda t: _sim(q, textgrams(_table_text(t))), reverse=True)[:k]


def rank_shots(shots: list[dict], question: str, k: int = 2) -> list[dict]:
    q = textgrams(question)
    return sorted(shots, key=lambda s: _sim(q, textgrams(s.get("question", ""))), reverse=True)[:k]


def few_shot_text(shots: list[dict]) -> str:
    if not shots:
        return ""
    lines = ["参考示例:"]
    for s in shots:
        lines.append(f"Q: {s['question']}")
        lines.append(f"SQL: {s['sql']}")
    return "\n".join(lines)


_TABLE_RE = None  # 延迟编译见 tables_in_sql


def tables_in_sql(sql: str) -> set[str]:
    """从 SQL 里提取表名（FROM/JOIN 后的标识符；忽略子查询括号与字符串字面量）。"""
    import re

    masked = re.sub(r"'[^']*'", "''", sql or "")
    found = re.findall(r"(?:\bFROM\b|\bJOIN\b)\s+\"?([a-zA-Z_][a-zA-Z0-9_]*)\"?", masked, re.IGNORECASE)
    # FROM (SELECT ...) 的 "(" 不会匹配标识符，天然被跳过
    return {name.lower() for name in found}


def recall_at_k(gold_tables: set[str], ranked: list[str], k: int) -> float:
    """链接召回率：金标表集合出现在排序结果前 k 位中的比例。"""
    if not gold_tables:
        return 0.0
    top = {t.lower() for t in ranked[:k]}
    return len(gold_tables & top) / len(gold_tables)

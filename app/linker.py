"""Schema linking：把自然语言问题与表/少样本示例做相关性排序。

中文问题对英文表名没有词面重叠，靠两件事桥接：
1. schema_comments 注释表里的中文业务描述（建库时写入）；
2. 少样本示例的中文问题相似度检索。
"""

import re
from collections import Counter, defaultdict
from itertools import combinations

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


def rank_tables(tables: list, question: str, k: int = 4, closure: bool = False) -> list:
    q = textgrams(question)
    ranked = sorted(tables, key=lambda t: _sim(q, textgrams(_table_text(t))), reverse=True)[:k]
    if not closure:
        return ranked
    return join_closure(tables, [t.name for t in ranked])


def _singular(name: str) -> str:
    n = name.lower()
    if n.endswith("ies") and len(n) > 4:
        return n[:-3] + "y"
    if n.endswith(("ses", "xes", "zes")):
        return n[:-2]
    if n.endswith("s") and not n.endswith("ss"):
        return n[:-1]
    return n


def fk_edges(tables: list) -> set[frozenset[str]]:
    """表之间的连接边：优先用库里声明的外键，其次从 `*_id` 列名推断。

    推断时词干必须在候选表里唯一命中才建边——`room_id` 同时像 dorm_rooms 也像
    classrooms，这种歧义宁可放弃，也不要猜一张错的表进 prompt。
    """
    edges: set[frozenset[str]] = set()
    names = {t.name for t in tables}
    for t in tables:
        for target in getattr(t, "fk_targets", ()):
            if target in names and target != t.name:
                edges.add(frozenset((t.name, target)))
    for t in tables:
        for c in t.columns:
            col = c["name"].lower()
            if not col.endswith("_id"):
                continue
            stem = col[:-3]
            if not stem:
                continue
            hits = set()
            for other in tables:
                if other.name == t.name:
                    continue
                n = other.name.lower()
                if (n == stem or n in (stem + "s", stem + "es")
                        or (stem.endswith("y") and n == stem[:-1] + "ies")
                        or _singular(other.name).startswith(stem)):
                    hits.add(other.name)
            if len(hits) == 1:
                edges.add(frozenset((t.name, hits.pop())))
    return edges


def _shortest_path(adj: dict, a: str, b: str) -> list[str] | None:
    if a == b:
        return [a]
    seen, frontier, parents = {a}, [a], {}
    while frontier:
        nxt = []
        for u in frontier:
            for v in adj.get(u, ()):
                if v in seen:
                    continue
                seen.add(v)
                parents[v] = u
                if v == b:
                    path, cur = [b], b
                    while cur != a:
                        cur = parents[cur]
                        path.append(cur)
                    return list(reversed(path))
                nxt.append(v)
        frontier = nxt
    return None


def join_closure(tables: list, selected: list[str], edges=None) -> list:
    """补齐把 selected 连起来所需的桥表，保持种子顺序、不新增无关表。"""
    by_name = {t.name: t for t in tables}
    adj = defaultdict(set)
    for edge in (fk_edges(tables) if edges is None else edges):
        a, b = tuple(edge)
        adj[a].add(b)
        adj[b].add(a)
    picked = [n for n in selected if n in by_name]
    bridges = []
    for a, b in combinations(picked, 2):
        path = _shortest_path(adj, a, b)
        if path:
            bridges.extend(path[1:-1])
    order = picked + [n for n in bridges if n not in picked]
    return [by_name[n] for n in dict.fromkeys(order)]


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

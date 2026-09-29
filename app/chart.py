"""结果集 → 图表类型推荐（启发式，可单测，无重依赖）。

规则优先级：
1. 无数据 / 单值 / 无数值列 → table
2. 日期标签 + 数值 → line（时间趋势）
3. 分类标签 + 单数值，行数 ≤6 且值全为正 → pie（构成占比）
4. 分类标签 + 1~2 个数值 → bar（1 个数值单系列，2 个数值多系列）
"""

import re

_DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def _classify(v) -> str:
    if v is None or isinstance(v, bool):
        return "text"
    if isinstance(v, (int, float)):
        return "number"
    if _DATE_RE.match(str(v).strip()):
        return "date"
    return "text"


def _column_types(columns: list[str], rows: list[list]) -> list[str]:
    types = []
    for i in range(len(columns)):
        seen = {_classify(r[i]) for r in rows if i < len(r) and r[i] is not None}
        # 列内混合时以数值优先（数值列里混一个 NULL 很常见）
        if "number" in seen or "date" in seen:
            seen -= {"text"}
        if not seen:
            seen = {"text"}
        types.append("number" if "number" in seen else ("date" if "date" in seen else "text"))
    return types


def _looks_like_shares(vals: list) -> bool:
    """占比构成的特征：全为正数，且总量像百分比(≈100)或分数(≈1)。"""
    if not (1 <= len(vals) <= 12):
        return False
    if not all(isinstance(v, (int, float)) and v > 0 for v in vals):
        return False
    s = sum(vals)
    return 99.0 <= s <= 101.0 or 0.99 <= s <= 1.01


def recommend_chart(columns: list[str], rows: list[list]) -> dict:
    if not rows:
        return {"type": "table", "reason": "无数据行"}
    if len(columns) < 2:
        return {"type": "table", "reason": "单值结果，表格呈现更清晰"}

    types = _column_types(columns, rows)
    num_idx = [i for i, t in enumerate(types) if t == "number"]
    date_idx = [i for i, t in enumerate(types) if t == "date"]

    if not num_idx:
        return {"type": "table", "reason": "无数值列，无可视化维度"}

    if len(columns) == 2 and len(num_idx) == 1:
        y = columns[num_idx[0]]
        other = 1 - num_idx[0]
        label_t = types[other]
        if label_t == "date":
            return {"type": "line", "x": columns[other], "y": [y], "reason": "日期趋势用折线图"}
        if _looks_like_shares([r[num_idx[0]] for r in rows]):
            return {"type": "pie", "x": columns[other], "y": [y], "reason": "占比构成用饼图"}
        return {"type": "bar", "x": columns[other], "y": [y], "reason": "分类对比用柱状图"}

    if len(num_idx) >= 2 and len(columns) - len(num_idx) == 1:
        label_i = [i for i in range(len(columns)) if i not in num_idx][0]
        return {
            "type": "bar",
            "x": columns[label_i],
            "y": [columns[i] for i in num_idx],
            "reason": "多指标分类对比用分组柱状图",
        }

    return {"type": "table", "reason": "结构复杂，表格呈现更清晰"}

"""执行准确率（execution accuracy）：预测 SQL 与金标 SQL 的结果集对比。"""

from ..executor import ExecutionResult


def _norm_cell(v):
    if isinstance(v, float):
        return round(v, 6)
    return v


def _sort_key(row: tuple) -> list:
    # 类型感知排序键：NULL 与不同类型共存时（BIRD 真实数据）也可排序，
    # 类型名保证只在同类型单元格之间做值比较
    return [(c is None, type(c).__name__, c if c is not None else "") for c in row]


def _norm_rows(rows: list[list]) -> list[tuple]:
    # 排序后比较：行序不敏感、重复行敏感（multiset 语义）
    normalized = [tuple(_norm_cell(c) for c in r) for r in rows]
    return sorted(normalized, key=_sort_key)


def execution_accuracy(pred: ExecutionResult, gold: ExecutionResult) -> float:
    if not (pred.ok and gold.ok):
        return 0.0
    if len(pred.columns) != len(gold.columns):
        return 0.0
    return 1.0 if _norm_rows(pred.rows) == _norm_rows(gold.rows) else 0.0

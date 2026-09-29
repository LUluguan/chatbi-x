"""评测 runner：加载评测集 → 逐题跑预测 → 执行准确率报告（含按难度分组）。

支持 BIRD 风格数据集（question + SQL + db_id + difficulty）与本地格式（question + gold_sql + db_path）。
用法:
    python -m app.eval.runner --dataset data/eval/demo_eval.json --db data/demo_ecom.db --provider mock --mode single_shot
    python -m app.eval.runner --dataset data/bird/dev.json --datasets-root data/bird --limit 50 --provider openai_compat
"""

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import executor as exe
from ..agent import ChatAgent, single_shot_sql
from ..config import Settings
from ..linker import rank_shots, rank_tables
from ..providers import ProviderError, build_provider
from ..schema import load_schema
from .metrics import execution_accuracy


@dataclass
class EvalItem:
    question: str
    gold_sql: str
    db_path: str = ""    # 显式 sqlite 路径（本地格式）
    db_id: str = ""      # BIRD 数据库 id（经 datasets_root 解析，也用于同库 few-shot 过滤）
    difficulty: str = ""
    evidence: str = ""   # BIRD 官方知识提示，随问题注入 prompt


@dataclass
class EvalReport:
    mode: str
    accuracy: float
    total: int
    details: list[dict] = field(default_factory=list)
    by_difficulty: dict[str, dict] = field(default_factory=dict)


def load_dataset(path: str) -> list[EvalItem]:
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for it in items:
        out.append(EvalItem(
            question=it["question"],
            gold_sql=it.get("gold_sql") or it.get("SQL") or "",
            db_path=it.get("db_path") or "",
            db_id=it.get("db_id") or "",
            difficulty=it.get("difficulty") or "",
            evidence=it.get("evidence") or "",
        ))
    return out


def load_shots(path: str) -> list[dict]:
    """加载 few-shot 池（建议用 train 集，避免评测集泄漏）。"""
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for it in items:
        q, sql = it.get("question"), it.get("gold_sql") or it.get("SQL")
        if q and sql:
            entry = {"question": q, "sql": sql}
            if it.get("db_id"):
                entry["db_id"] = it["db_id"]
            out.append(entry)
    return out


def resolve_db(ref: str, default_db: str, datasets_root: str = "") -> str:
    """把 db_id/db_path 解析成实际 sqlite 文件路径。

    支持：空 → 默认库；存在的路径 → 原样；datasets_root 下的 BIRD 布局
    (dev_databases/<id>/<id>.sqlite) 或扁平布局 (<id>/<id>.sqlite)。
    无法解析时明确报错——静默用错库会让评测结果不可信。
    """
    if not ref:
        return default_db
    p = Path(ref)
    if p.exists():
        return str(p)
    if datasets_root:
        for pattern in ("dev_databases/{r}/{r}.sqlite", "{r}/{r}.sqlite"):
            cand = Path(datasets_root) / pattern.format(r=ref)
            if cand.exists():
                return str(cand)
        raise FileNotFoundError(f"在 datasets_root({datasets_root}) 下找不到数据库 {ref}")
    raise FileNotFoundError(f"找不到数据库 {ref}（未提供 --datasets-root 且不是有效路径）")


def run_eval(items: list[EvalItem], provider, default_db: str, mode: str = "single_shot",
             max_rows: int = 50, timeout_ms: int = 3000, top_k_tables: int = 4,
             datasets_root: str = "", shots: list[dict] | None = None) -> EvalReport:
    schema_cache: dict[str, list] = {}

    def tables_for(db: str) -> list:
        if db not in schema_cache:
            schema_cache[db] = load_schema(db)
        return schema_cache[db]

    shots_pool = shots if shots is not None else [
        {"question": it.question, "sql": it.gold_sql} for it in items if it.gold_sql
    ]
    details = []
    diff_stat: dict[str, list[int]] = {}
    hits = 0

    for it in items:
        db = resolve_db(it.db_path or it.db_id, default_db, datasets_root)
        tables = rank_tables(tables_for(db), it.question, k=top_k_tables)
        pool = [s for s in shots_pool if s.get("question") != it.question]
        same_db = [s for s in pool if it.db_id and s.get("db_id") == it.db_id]
        shots_k = rank_shots(same_db or pool, it.question, k=2)
        question = it.question + (f"\n提示: {it.evidence}" if it.evidence else "")

        pred_error = ""
        try:
            if mode == "agent":
                # propose-verify：naive 生成草案，Agent 验证修正
                draft = single_shot_sql(provider, tables, question, few_shots=shots_k)
                r = ChatAgent(provider, tables, db, max_rows=max_rows, timeout_ms=timeout_ms,
                              few_shots=shots_k).run(question, draft_sql=draft)
                pred_sql = r.sql
            else:
                pred_sql = single_shot_sql(provider, tables, question, few_shots=shots_k)
        except ProviderError as e:
            # 单题 provider 故障记录为失败，不炸掉整个评测
            pred_sql, pred_error = "", str(e)

        if pred_sql:
            pred = exe.run_sql(db, pred_sql, max_rows, timeout_ms)
        else:
            pred = exe.ExecutionResult(error=pred_error or "预测为空 SQL")
        gold = exe.run_sql(db, it.gold_sql, max_rows, timeout_ms)
        acc = execution_accuracy(pred, gold)
        hits += acc

        key = it.difficulty or "未标注"
        stat = diff_stat.setdefault(key, [0, 0])
        stat[0] += acc
        stat[1] += 1
        details.append({
            "question": it.question,
            "predicted_sql": pred_sql,
            "acc": acc,
            "ok": pred.ok,
            "error": pred.error,
        })

    total = len(items)
    by_difficulty = {k: {"accuracy": v[0] / v[1], "total": v[1]} for k, v in diff_stat.items()}
    return EvalReport(mode=mode, accuracy=hits / total if total else 0.0,
                      total=total, details=details, by_difficulty=by_difficulty)


def run_compare(items: list[EvalItem], provider, default_db: str, **kw) -> dict:
    """同一评测集跑 single_shot 与 agent 两种模式，返回可序列化对比结果。"""
    rep_single = run_eval(items, provider, default_db, mode="single_shot", **kw)
    rep_agent = run_eval(items, provider, default_db, mode="agent", **kw)
    return {
        "single_shot": asdict(rep_single),
        "agent": asdict(rep_agent),
        "delta": rep_agent.accuracy - rep_single.accuracy,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="ChatBI-X 评测")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--provider", default="mock")
    ap.add_argument("--mode", default="single_shot", choices=["single_shot", "agent"])
    ap.add_argument("--datasets-root", default="")
    ap.add_argument("--shots-file", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="data/eval/last_report.json")
    args = ap.parse_args(argv)

    settings = Settings(llm_provider=args.provider, db_path=args.db,
                        eval_set_path=args.dataset, datasets_root=args.datasets_root)
    provider = build_provider(settings)
    items = load_dataset(args.dataset)
    if args.limit:
        items = items[: args.limit]
    shots = load_shots(args.shots_file) if args.shots_file else None
    report = run_eval(items, provider, args.db, mode=args.mode,
                      datasets_root=args.datasets_root, shots=shots)

    print(f"模式: {report.mode}  题数: {report.total}  执行准确率: {report.accuracy:.2%}")
    for k, v in report.by_difficulty.items():
        print(f"  [{k}] {v['accuracy']:.2%} ({v['total']}题)")
    for d in report.details:
        mark = "PASS" if d["acc"] == 1.0 else "FAIL"
        print(f"  [{mark}] {d['question']}" + (f"  <- {d['error']}" if d["error"] else ""))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写入 {out}")


if __name__ == "__main__":
    main()

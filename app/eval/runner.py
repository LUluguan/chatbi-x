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
from .stats import mcnemar_exact_bilateral, wilson_interval


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


def _categorize(acc: float, pred: "exe.ExecutionResult") -> str:
    if acc == 1.0:
        return "correct"
    if not pred.ok:
        if "最大步数" in pred.error:
            return "max_steps"
        if pred.error == "预测为空 SQL":
            return "empty_sql"
        return "exec_fail"
    return "result_mismatch"


def run_eval(items: list[EvalItem], provider, default_db: str, mode: str = "single_shot",
             max_rows: int = 50, timeout_ms: int = 3000, top_k_tables: int | None = 6,
             datasets_root: str = "", shots: list[dict] | None = None,
             eval_max_rows: int = 100_000) -> EvalReport:
    """eval_max_rows 是判据的比对上限（默认 10 万，视为全量）。

    与 max_rows（Agent 内部预览行数）严格分离：判据若按预览行数截断，
    会拿两边物理顺序的前 N 行比较，长结果集上双向失真。
    """
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
        tables_all = tables_for(db)
        # top_k_tables=None = 关闭 linking（全 schema 进 prompt），用于消融对照
        tables = rank_tables(tables_all, it.question, k=top_k_tables) if top_k_tables else tables_all
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
            pred = exe.run_sql(db, pred_sql, eval_max_rows, timeout_ms)
        else:
            pred = exe.ExecutionResult(error=pred_error or "预测为空 SQL")
        gold = exe.run_sql(db, it.gold_sql, eval_max_rows, timeout_ms)
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
            "truncated": pred.truncated or gold.truncated,
            "category": _categorize(acc, pred),
        })

    total = len(items)
    by_difficulty = {k: {"accuracy": v[0] / v[1], "total": v[1]} for k, v in diff_stat.items()}
    return EvalReport(mode=mode, accuracy=hits / total if total else 0.0,
                      total=total, details=details, by_difficulty=by_difficulty)


def rejudge(report_path: str, dataset_path: str, default_db: str,
            datasets_root: str = "", eval_max_rows: int = 100_000,
            timeout_ms: int = 3000):
    """用当前判据重判已有报告的预测，不重新调用 LLM（判据修正是零成本复测）。

    支持单模式报告（含 details）与 compare 格式（single_shot/agent 两个键）。
    """
    old = json.loads(Path(report_path).read_text(encoding="utf-8"))
    items_by_q = {it.question: it for it in load_dataset(dataset_path)}
    if "details" in old:
        return _rejudge_one(old, items_by_q, default_db, datasets_root, eval_max_rows, timeout_ms)
    return {
        mode: _rejudge_one(old[mode], items_by_q, default_db, datasets_root, eval_max_rows, timeout_ms)
        for mode in ("single_shot", "agent") if mode in old
    }


def _rejudge_one(old: dict, items_by_q: dict, default_db: str,
                 datasets_root: str, eval_max_rows: int, timeout_ms: int) -> EvalReport:
    details = []
    diff_stat: dict[str, list[int]] = {}
    hits = 0
    scored = 0
    for d in old.get("details", []):
        it = items_by_q.get(d.get("question", ""))
        if it is None:
            details.append({**d, "category": "missing_in_dataset"})
            continue
        db = resolve_db(it.db_path or it.db_id, default_db, datasets_root)
        pred_sql = d.get("predicted_sql") or ""
        if pred_sql:
            pred = exe.run_sql(db, pred_sql, eval_max_rows, timeout_ms)
        else:
            pred = exe.ExecutionResult(error="预测为空 SQL")
        gold = exe.run_sql(db, it.gold_sql, eval_max_rows, timeout_ms)
        acc = execution_accuracy(pred, gold)
        hits += acc
        scored += 1
        stat = diff_stat.setdefault(it.difficulty or "未标注", [0, 0])
        stat[0] += acc
        stat[1] += 1
        details.append({
            "question": it.question,
            "predicted_sql": pred_sql,
            "acc": acc,
            "ok": pred.ok,
            "error": pred.error,
            "truncated": pred.truncated or gold.truncated,
            "category": _categorize(acc, pred),
        })
    return EvalReport(
        mode=f"{old.get('mode', '?')} (rejudged)",
        accuracy=hits / scored if scored else 0.0,
        total=scored,
        details=details,
        by_difficulty={k: {"accuracy": v[0] / v[1], "total": v[1]} for k, v in diff_stat.items()},
    )


def run_compare(items: list[EvalItem], provider, default_db: str, **kw) -> dict:
    """同一评测集跑 single_shot 与 agent 两种模式，返回可序列化对比结果。

    附带配对统计：边际准确率的 Wilson 区间可能重叠，但配对 McNemar 才是
    「自校正是否有正收益」的正确判据。
    """
    rep_single = run_eval(items, provider, default_db, mode="single_shot", **kw)
    rep_agent = run_eval(items, provider, default_db, mode="agent", **kw)
    s_by_q = {d["question"]: d for d in rep_single.details}
    a_by_q = {d["question"]: d for d in rep_agent.details}
    only_agent = sum(1 for q in a_by_q if a_by_q[q]["acc"] == 1.0 and s_by_q[q]["acc"] != 1.0)
    only_base = sum(1 for q in s_by_q if s_by_q[q]["acc"] == 1.0 and a_by_q[q]["acc"] != 1.0)

    def _hits(rep: EvalReport) -> int:
        return int(round(sum(d["acc"] for d in rep.details)))

    return {
        "single_shot": asdict(rep_single),
        "agent": asdict(rep_agent),
        "delta": rep_agent.accuracy - rep_single.accuracy,
        "paired": {
            "only_agent_correct": only_agent,
            "only_baseline_correct": only_base,
            "mcnemar_p": mcnemar_exact_bilateral(only_base, only_agent),
            "wilson": {
                "single_shot": list(wilson_interval(_hits(rep_single), rep_single.total)),
                "agent": list(wilson_interval(_hits(rep_agent), rep_agent.total)),
            },
        },
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
    ap.add_argument("--max-rows", type=int, default=100_000,
                    help="判据比对行数上限（默认 10 万，视为全量比对）")
    ap.add_argument("--out", default="data/eval/last_report.json")
    args = ap.parse_args(argv)

    settings = Settings(llm_provider=args.provider, db_path=args.db,
                        eval_set_path=args.dataset, datasets_root=args.datasets_root)
    if args.provider == "openai_compat":
        print("⚠ provider=openai_compat：将调用真实 LLM API，可能产生费用")
    provider = build_provider(settings)
    items = load_dataset(args.dataset)
    if args.limit:
        items = items[: args.limit]
    shots = load_shots(args.shots_file) if args.shots_file else None
    report = run_eval(items, provider, args.db, mode=args.mode,
                      datasets_root=args.datasets_root, shots=shots,
                      eval_max_rows=args.max_rows)

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

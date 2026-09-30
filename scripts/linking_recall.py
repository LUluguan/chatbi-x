"""Linking 召回率测量（零 LLM 成本）。

对给定评测集测量：金标表是否出现在 linking 排序的前 k 位，以及
linking on/off 两种模式下 prompt（schema 部分）的体积对比。

用法: python scripts/linking_recall.py --dataset data/eval/academic_eval.json --db data/bench_academic.db
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.eval.runner import load_dataset, resolve_db  # noqa: E402
from app.linker import rank_tables, recall_at_k, tables_in_sql  # noqa: E402
from app.schema import load_schema, schema_prompt  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--datasets-root", default="")
    args = ap.parse_args()

    items = load_dataset(args.dataset)
    all_tables = None
    recalls = {k: [] for k in (1, 2, 3, 4, 6, 8)}
    on_sizes, off_sizes = [], []
    misses = []

    for it in items:
        db = resolve_db(it.db_path or it.db_id, args.db, args.datasets_root)
        if all_tables is None:
            all_tables = load_schema(db)
        ranked_names = [t.name for t in rank_tables(all_tables, it.question, k=999)]
        gold = tables_in_sql(it.gold_sql)
        for k in recalls:
            recalls[k].append(recall_at_k(gold, ranked_names, k))
        linked = rank_tables(all_tables, it.question, k=4)
        on_sizes.append(len(schema_prompt(linked).encode("utf-8")))
        off_sizes.append(len(schema_prompt(all_tables).encode("utf-8")))
        if recall_at_k(gold, ranked_names, 4) < 1.0:
            misses.append((it.question, sorted(gold), ranked_names[:6]))

    n = len(items)
    print(f"评测集: {args.dataset}（{n} 题，{len(all_tables)} 表）")
    print("召回率（金标表出现在 linking 排序前 k 位）:")
    for k, vals in recalls.items():
        print(f"  Top-{k}: {statistics.mean(vals):.1%}")
    print(f"prompt 体积（schema 部分，字节/题）: linking on ≈ {statistics.mean(on_sizes):.0f}  "
          f"off ≈ {statistics.mean(off_sizes):.0f}  （省 {1 - statistics.mean(on_sizes) / statistics.mean(off_sizes):.0%}）")
    if misses:
        print("\nTop-4 未全召回的题:")
        for q, gold, top6 in misses:
            print(f"  {q}  金标={gold}  前6={top6}")


if __name__ == "__main__":
    main()

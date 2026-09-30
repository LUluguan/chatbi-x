"""用当前判据重判已有评测报告（零 LLM 成本——判据修正后的复测路径）。

用法:
    python -m app.eval.rejudge --report data/eval/compare_report_v3.json \
        --dataset data/bird/dev.json --datasets-root data/bird --db data/demo_ecom.db
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .runner import rejudge


def main(argv=None):
    ap = argparse.ArgumentParser(description="重判已有评测报告")
    ap.add_argument("--report", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--datasets-root", default="")
    ap.add_argument("--max-rows", type=int, default=100_000)
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)

    out = rejudge(args.report, args.dataset, args.db,
                  datasets_root=args.datasets_root, eval_max_rows=args.max_rows)

    if isinstance(out, dict):
        payload = {}
        for mode, rep in out.items():
            cats = {}
            for d in rep.details:
                cats[d.get("category", "?")] = cats.get(d.get("category", "?"), 0) + 1
            print(f"{rep.mode}: 题数 {rep.total}  执行准确率 {rep.accuracy:.2%}  分类={cats}")
            payload[mode] = asdict(rep)
    else:
        print(f"{out.mode}: 题数 {out.total}  执行准确率 {out.accuracy:.2%}")
        payload = asdict(out)

    if args.out:
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print(f"已写入 {args.out}")


if __name__ == "__main__":
    main()

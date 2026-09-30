"""对比 single_shot（朴素基线）与 agent（工具循环+自校正）两种模式的执行准确率。

用法:
    python -m app.eval.compare --dataset data/eval/demo_eval.json --db data/demo_ecom.db --provider mock
    python -m app.eval.compare --dataset data/bird/dev.json --datasets-root data/bird --limit 100 --provider openai_compat
"""

import argparse
import json
from pathlib import Path

from ..config import Settings
from ..providers import build_provider
from .runner import load_dataset, load_shots, run_compare


def main(argv=None):
    ap = argparse.ArgumentParser(description="ChatBI-X 模式对比评测")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--provider", default="mock")
    ap.add_argument("--datasets-root", default="")
    ap.add_argument("--shots-file", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-rows", type=int, default=100_000,
                    help="判据比对行数上限（默认 10 万，视为全量比对）")
    ap.add_argument("--out", default="data/eval/compare_report.json")
    args = ap.parse_args(argv)

    settings = Settings(llm_provider=args.provider, db_path=args.db,
                        eval_set_path=args.dataset, datasets_root=args.datasets_root)
    if args.provider == "openai_compat":
        print("⚠ provider=openai_compat：将调用真实 LLM API，可能产生费用（两种模式共约 3 次 LLM 调用/题）")
    provider = build_provider(settings)
    items = load_dataset(args.dataset)
    if args.limit:
        items = items[: args.limit]
    shots = load_shots(args.shots_file) if args.shots_file else None
    out = run_compare(items, provider, args.db, datasets_root=args.datasets_root,
                      shots=shots, eval_max_rows=args.max_rows)

    s, a = out["single_shot"], out["agent"]
    paired = out["paired"]
    print(f"题数: {s['total']}  模型: {args.provider}")
    print(f"  single_shot (朴素基线)  : {s['accuracy']:.2%}  95%CI [{paired['wilson']['single_shot'][0]:.1%}, {paired['wilson']['single_shot'][1]:.1%}]")
    print(f"  agent (propose-verify)  : {a['accuracy']:.2%}  95%CI [{paired['wilson']['agent'][0]:.1%}, {paired['wilson']['agent'][1]:.1%}]")
    print(f"  配对（McNemar 精确，双侧）: 仅agent对 {paired['only_agent_correct']} vs 仅基线对 {paired['only_baseline_correct']}"
          f"  p = {paired['mcnemar_p']:.4g}")
    for name, rep in (("single_shot", s), ("agent", a)):
        for k, v in rep.get("by_difficulty", {}).items():
            print(f"  [{name}] {k}: {v['accuracy']:.2%} ({v['total']}题)")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写入 {out_path}")


if __name__ == "__main__":
    main()

"""Schema linking 消融：同一评测集，linking on(top-k) vs off(全 schema)，其余全部相同。

用法:
    python scripts/ablation_linking.py --dataset data/eval/academic_eval.json \
        --db data/bench_academic.db --provider openai_compat --k-on 4 --out data/eval/linking_ablation.json
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.eval.runner import load_dataset, run_eval  # noqa: E402
from app.eval.stats import mcnemar_exact_bilateral, wilson_interval  # noqa: E402
from app.providers import build_provider  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--datasets-root", default="")
    ap.add_argument("--provider", default="openai_compat")
    ap.add_argument("--k-on", type=int, default=4)
    ap.add_argument("--mode", default="single_shot", choices=["single_shot", "agent"])
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.provider == "openai_compat":
        print("⚠ 将调用真实 LLM API（约 2 次调用/题 × 2 组），可能产生费用")
    settings = Settings(llm_provider=args.provider, db_path=args.db,
                        eval_set_path=args.dataset, datasets_root=args.datasets_root)
    provider = build_provider(settings)
    items = load_dataset(args.dataset)
    shots = []  # 消融不带 few-shot，避免示例对两组的干扰不均

    print(f"组1 linking ON (top-{args.k_on}) ...", flush=True)
    on = run_eval(items, provider, args.db, mode=args.mode,
                  top_k_tables=args.k_on, shots=shots)
    print(f"组2 linking OFF (全 schema) ...", flush=True)
    off = run_eval(items, provider, args.db, mode=args.mode,
                   top_k_tables=None, shots=shots)

    s_by_q = {d["question"]: d for d in off.details}
    a_by_q = {d["question"]: d for d in on.details}
    only_on = sum(1 for q in a_by_q if a_by_q[q]["acc"] == 1 and s_by_q[q]["acc"] != 1)
    only_off = sum(1 for q in s_by_q if s_by_q[q]["acc"] == 1 and a_by_q[q]["acc"] != 1)

    print(f"\n题数: {on.total}  模式: {args.mode}  模型: {args.provider}")
    print(f"  linking ON  (top-{args.k_on}): {on.accuracy:.2%}  "
          f"95%CI [{wilson_interval(_hits(on), on.total)[0]:.1%}, {wilson_interval(_hits(on), on.total)[1]:.1%}]")
    print(f"  linking OFF (全 schema) : {off.accuracy:.2%}  "
          f"95%CI [{wilson_interval(_hits(off), off.total)[0]:.1%}, {wilson_interval(_hits(off), off.total)[1]:.1%}]")
    print(f"  仅 ON 对 {only_on} vs 仅 OFF 对 {only_off}  McNemar p = "
          f"{mcnemar_exact_bilateral(only_off, only_on):.4g}")
    for name, rep in (("ON", on), ("OFF", off)):
        cats = {}
        for d in rep.details:
            cats[d["category"]] = cats.get(d["category"], 0) + 1
        print(f"  [{name}] 失败分类: { {k: v for k, v in cats.items() if k != 'correct'} }")

    if args.out:
        Path(args.out).write_text(json.dumps({
            "on": asdict(on), "off": asdict(off),
            "paired": {"only_on_correct": only_on, "only_off_correct": only_off,
                       "mcnemar_p": mcnemar_exact_bilateral(only_off, only_on)},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 {args.out}")


def _hits(rep) -> int:
    return int(round(sum(d["acc"] for d in rep.details)))


if __name__ == "__main__":
    main()

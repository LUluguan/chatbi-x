"""SSE 实测：验证 /api/chat/stream 的事件随执行进度递送，而非末尾一次性缓冲。

对真实模型服务运行（事件间隔应达秒级）:
    python scripts/smoke_sse.py --base http://127.0.0.1:8010 --min-spread-ms 300
对 mock 服务运行（事件几乎同刻到达，用 --min-spread-ms 0 只验证事件序列）:
    python scripts/smoke_sse.py --base http://127.0.0.1:8010 --min-spread-ms 0
"""

import argparse
import json
import sys
import time

import httpx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--question", default="销售额最高的商品是哪个？")
    ap.add_argument("--min-spread-ms", type=int, default=300,
                    help="首事件与 result 的最小到达时间差（证明增量递送）")
    args = ap.parse_args()

    t0 = time.perf_counter()
    events = []
    with httpx.Client(timeout=180) as c:
        with c.stream("POST", args.base + "/api/chat/stream",
                      json={"question": args.question}) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line.startswith("data: "):
                    arrival = round((time.perf_counter() - t0) * 1000)
                    events.append((arrival, json.loads(line[6:])))

    print("事件时间线（+ms 为自请求起的到达时刻）:")
    for ms, ev in events:
        detail = ev.get("detail") or ev.get("summary") or ev.get("sql") or ev.get("error") or ""
        print(f"  +{ms:6d}ms  {ev.get('type'):7s} {str(detail)[:70]}")

    ok = bool(events) and events[-1][1].get("type") == "result"
    spread = events[-1][0] - events[0][0] if len(events) >= 2 else 0
    steps_before = sum(1 for _, ev in events[:-1] if ev.get("type") == "step")
    ok = ok and spread >= args.min_spread_ms and steps_before >= 1
    print(f"事件数={len(events)}  step 先行={steps_before}  首末间隔={spread}ms")
    print("SSE_TIMELINE " + ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

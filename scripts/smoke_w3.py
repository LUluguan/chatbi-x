"""W3 冒烟：SSE 流式 + 静态托管 + 图表推荐，对运行中的服务验证。

用法: python scripts/smoke_w3.py http://127.0.0.1:8010
"""

import json
import sys

import httpx


def main(base: str = "http://127.0.0.1:8010"):
    ok = True
    with httpx.Client(base_url=base, timeout=30) as c:
        # 1. 静态托管
        r = c.get("/")
        print(f"静态首页: {r.status_code} 含app挂载点={'id=\"app\"' in r.text}")
        ok &= r.status_code == 200 and 'id="app"' in r.text

        # 2. SSE 流式（真实验证步骤事件与图表推荐）
        with c.stream("POST", "/api/chat/stream", json={"question": "每个城市的用户数量是多少？"}) as resp:
            print(f"stream:  {resp.status_code} {resp.headers.get('content-type')}")
            ok &= resp.status_code == 200 and resp.headers.get("content-type", "").startswith("text/event-stream")
            events = []
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
            kinds = [e.get("type") for e in events]
            print(f"  事件序列: {kinds}")
            ok &= "step" in kinds and "result" in kinds and kinds[-1] == "result"
            result = events[-1]
            print(f"  sql: {result.get('sql')}")
            print(f"  chart: {result.get('chart')}")
            print(f"  rows: {result.get('rows')}")
            ok &= bool(result.get("ok") is True and result.get("rows"))
            ok &= result.get("chart", {}).get("type") == "bar"

        # 3. 线图场景（日期 + 数值 → line）
        with c.stream("POST", "/api/chat/stream", json={"question": "2026年9月22日至9月28日每天的订单数量是多少？"}) as resp:
            events = [json.loads(l[6:]) for l in resp.iter_lines() if l.startswith("data: ")]
            chart = events[-1].get("chart", {})
            print(f"线图场景: type={chart.get('type')}")
            ok &= chart.get("type") == "line"

    print("SMOKE_W3 " + ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010")

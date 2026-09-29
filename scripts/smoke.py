"""对运行中的服务做端到端冒烟检查。

用法: 先启动服务 (python -m uvicorn app.main:app --port 8010)，再运行:
    python scripts/smoke.py http://127.0.0.1:8010
"""

import json
import sys

import httpx


def main(base: str = "http://127.0.0.1:8010"):
    ok = True
    with httpx.Client(base_url=base, timeout=30) as c:
        h = c.get("/api/health")
        print(f"health: {h.status_code} {h.json()}")
        ok &= h.status_code == 200 and h.json()["status"] == "ok"

        s = c.get("/api/schema")
        tables = s.json()["tables"]
        print(f"schema: {s.status_code} tables={[t['name'] for t in tables]}")
        ok &= s.status_code == 200 and len(tables) >= 4

        r = c.post("/api/chat", json={"question": "请问每个城市的用户数量是多少？"})
        b = r.json()
        print(f"chat:   {r.status_code} ok={b['ok']} sql={b['sql']}")
        print(f"        summary={b['summary']}")
        print(f"        columns={b['columns']} rows={b['rows'][:4]}")
        ok &= bool(r.status_code == 200 and b["ok"] and b["rows"])
        if b.get("steps"):
            print(f"        steps={[s2['action'] for s2 in b['steps']]}")

        e = c.post("/api/chat", json={"question": "火星上有多少生命？"})
        be = e.json()
        print(f"chat(unknown): ok={be['ok']} error={be['error'][:40]}")
        ok &= e.status_code == 200 and be["ok"] is False

    print("SMOKE " + ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010")

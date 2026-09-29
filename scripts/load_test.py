"""并发压测：/api/chat/stream 的调度与流式管线开销。

对 mock provider 服务压测（不含 LLM 网络延迟，测的是调度/执行/流式管线本身）：
    CHATBI_LLM_PROVIDER=mock python -m uvicorn app.main:app --port 8010
    python scripts/load_test.py --base http://127.0.0.1:8010 --concurrency 8 --total 40
"""

import argparse
import asyncio
import statistics
import time

import httpx


async def one(client: httpx.AsyncClient, base: str) -> float:
    t0 = time.perf_counter()
    async with client.stream("POST", f"{base}/api/chat/stream",
                             json={"question": "一共有多少个用户？"}) as r:
        got_result = False
        async for line in r.aiter_lines():
            if line.startswith("data: ") and '"result"' in line:
                got_result = True
                break
    if not got_result:
        raise RuntimeError("未收到 result 事件")
    return time.perf_counter() - t0


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--total", type=int, default=40)
    args = ap.parse_args()

    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=60) as client:
        async def bounded():
            async with sem:
                return await one(client, args.base)

        t0 = time.perf_counter()
        latencies = await asyncio.gather(*[bounded() for _ in range(args.total)])
        wall = time.perf_counter() - t0

    latencies.sort()
    n = len(latencies)
    print(f"并发={args.concurrency}  总请求={n}  成功={n}")
    print(f"吞吐      : {n / wall:.1f} req/s")
    print(f"p50/p95/max: {latencies[n // 2] * 1000:.0f}ms / "
          f"{latencies[min(n - 1, int(n * 0.95))] * 1000:.0f}ms / {latencies[-1] * 1000:.0f}ms")
    print(f"均值±标准差: {statistics.mean(latencies) * 1000:.0f}ms ± {statistics.stdev(latencies) * 1000:.0f}ms")


if __name__ == "__main__":
    asyncio.run(main())

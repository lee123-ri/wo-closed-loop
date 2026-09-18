#!/usr/bin/env python3
"""并发压测（只读）—— asyncio + httpx 打后端，出 TPS / 延迟分位 / 错误率。

跑法（不需要装新东西，backend venv 已带 httpx）：
    cd backend
    .venv/bin/python ../scripts/loadtest/loadtest.py --url http://localhost:8000 --token <jwt> -c 50 -d 30

token 用 mint_token.py 造，或浏览器登录后取 localStorage['wo_token']。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections import Counter

import httpx

# 只读端点，压测不写数据、不改状态
ENDPOINTS: list[tuple[str, str]] = [
    ("GET", "/api/work-orders"),
    ("GET", "/api/work-orders?page=1&page_size=50"),
    ("GET", "/api/work-orders/dashboard/summary"),
    ("GET", "/api/dashboard/stats"),
    ("GET", "/api/dashboard/trends"),
]


def percentile(sorted_ms: list[float], p: float) -> float:
    if not sorted_ms:
        return 0.0
    k = (len(sorted_ms) - 1) * p
    lo, hi = int(k), min(len(sorted_ms) - 1, int(k) + 1)
    return (sorted_ms[lo] + sorted_ms[hi]) / 2


async def worker(client: httpx.AsyncClient, sem: asyncio.Semaphore, token: str, deadline: float, results: list):
    headers = {"Authorization": f"Bearer {token}"}
    i = 0
    while time.monotonic() < deadline:
        method, path = ENDPOINTS[i % len(ENDPOINTS)]
        i += 1
        async with sem:
            t0 = time.perf_counter()
            try:
                r = await client.request(method, path, headers=headers)
                results.append((time.perf_counter() - t0, r.status_code))
            except Exception as e:  # 连接/超时/读错误统一记成 error
                results.append((time.perf_counter() - t0, f"error:{type(e).__name__}"))


async def run() -> int:
    ap = argparse.ArgumentParser(description="软工单并发压测（只读）")
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--token", default=None, help="JWT（或环境变量 TOKEN）")
    ap.add_argument("-c", "--concurrency", type=int, default=50, help="并发数")
    ap.add_argument("-d", "--duration", type=int, default=30, help="压测秒数")
    args = ap.parse_args()

    token = args.token or os.environ.get("TOKEN")
    if not token:
        print("缺 token：--token <jwt> 或设环境变量 TOKEN（用 ../scripts/loadtest/mint_token.py 造）", file=sys.stderr)
        return 2

    results: list[tuple[float, object]] = []
    sem = asyncio.Semaphore(args.concurrency)
    limits = httpx.Limits(max_connections=args.concurrency + 10, max_keepalive_connections=args.concurrency)

    print(f"压测 {args.url}，并发 {args.concurrency}，时长 {args.duration}s（只读：{'/'.join(p for _, p in ENDPOINTS[:1])} …）")
    t0 = time.perf_counter()
    async with httpx.AsyncClient(base_url=args.url, limits=limits, timeout=30.0) as client:
        await asyncio.gather(
            *[worker(client, sem, token, t0 + args.duration, results) for _ in range(args.concurrency)]
        )
    wall = time.perf_counter() - t0

    total = len(results)
    if total == 0:
        print("0 请求完成（可能后端没起来或 token 失效）")
        return 1

    ok = [d for d, s in results if s == 200]
    bad = [(d, s) for d, s in results if s != 200]
    err_rate = len(bad) / total
    status_counts = Counter(s for _, s in bad)
    lat_ms = sorted(d * 1000 for d, _ in results)

    print(f"\n===== 结果（{wall:.1f}s，{total} 请求）=====")
    print(f"TPS（吞吐）      : {total / wall:.1f} req/s")
    print(f"成功 200         : {len(ok)} ({len(ok)/total*100:.1f}%)")
    print(f"错误/非 200      : {len(bad)} ({err_rate*100:.2f}%)")
    if status_counts:
        print(f"错误状态分布     : {dict(status_counts)}")
    print(f"延迟 p50/p90/p95/p99 (ms): "
          f"{percentile(lat_ms, .50):.0f} / {percentile(lat_ms, .90):.0f} / "
          f"{percentile(lat_ms, .95):.0f} / {percentile(lat_ms, .99):.0f}")
    print(f"延迟 max (ms)    : {lat_ms[-1]:.0f}")

    # 观测口径：错误率 >1% 或 p95 > 1000ms 视为压不动，需要扩副本或查慢查询
    verdict = "OK：未触到明显瓶颈" if (err_rate <= 0.01 and percentile(lat_ms, .95) <= 1000) else "⚠️ 需关注：扩 replicas 或查慢查询"
    print(f"判定             : {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
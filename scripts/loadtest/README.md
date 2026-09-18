# 并发压测（上线前基线）

平台上线前要回答「并发扛不扛得住」，用这里两个脚本打一批**只读**请求出基线。
只读端点（工单列表 / 汇总 / 看板统计 / 趋势），**不写数据、不改状态**，可放心压。

## 前置

1. 本地跑起后端（`bash run-local.sh`），确保库里有数据、`/health` 返回 200。
2. 造一个测试 JWT。两种方式：

   ```bash
   # 方式 A：复用后端同一把 JWT_SECRET 直接造（最快）
   cd backend && .venv/bin/python ../scripts/loadtest/mint_token.py 1 admin admin
   # 打印出一长串 token，复制备用

   # 方式 B：浏览器登录后，控制台取 localStorage['wo_token']
   ```

## 跑法 A：Python（推荐，零依赖，backend venv 已带 httpx）

```bash
cd backend
.venv/bin/python ../scripts/loadtest/loadtest.py --url http://localhost:8000 --token <jwt> -c 50 -d 30
```

- `-c` 并发数（默认 50），`-d` 持续秒数（默认 30）。
- 逐档加压：`-c 10`、`-c 50`、`-c 100`、`-c 200`，各跑 30s，记录每次的 TPS / p95 / 错误率。

## 跑法 B：k6（打灰度/内网更正式的场景）

```bash
k6 run -e BASE_URL=http://localhost:8000 -e TOKEN=<jwt> scripts/loadtest/k6-loadtest.js
```

内置阈值：p95 < 1000ms、错误率 < 1%，超了 k6 直接报 FAIL。

## 看什么

| 指标 | 观测口径 |
|---|---|
| TPS | 随并发升到某个点不再涨=到达吞吐上限 |
| p95 延迟 | >1000ms 说明单请求慢，查访问日志里的 `[SLOW]` 行 |
| 错误率 | >1% 说明压不动，多半是连接池/线程池打满 |

## 口径提醒（对照架构看数字）

- 后端生产是 **uvicorn `--workers 1` + k8s `replicas=2`**（Dockerfile 硬编码
  workers=1，因为 lifespan 里有 OA 轮询/钉钉 Stream 后台线程，多 worker 会重复起）。
- 业务端点几乎全走**同步 `def`**，FastAPI 丢进默认线程池（约 40 并发/进程），
  2 副本理论承接 ~80 并发同步请求，超过排队。
- 所以压测时：本地只有 1 个进程，`-c 200` 会明显排队属**预期**；生产 2 副本 ≈
  本地 2 倍。上线前拿本地单进程数字 × 副本数估量级，最终以灰度实测为准。

## 压不动怎么办

1. `kubectl scale deploy/wo-backend --replicas=4`（横向扩，成本最低）；
2. 看 `[SLOW]` 访问日志 / ARMS 定位慢查询（大概率是列表页缺索引或 N+1）；
3. 关掉重查询再测（如 /api/dashboard/trends 全量聚合）。
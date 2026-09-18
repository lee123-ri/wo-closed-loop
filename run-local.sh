#!/usr/bin/env bash
# 工单管理平台 —— 本地一键启动
# 用法：bash run-local.sh   （无需 chmod +x）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE=(docker compose)

echo "==> [1/3] 启动依赖 PostgreSQL + Redis"
"${COMPOSE[@]}" -f "$ROOT/docker-compose.yml" up -d db redis

echo "==> [2/3] 等待 PostgreSQL 就绪"
for i in $(seq 1 30); do
  if "${COMPOSE[@]}" -f "$ROOT/docker-compose.yml" exec -T db pg_isready -U postgres >/dev/null 2>&1; then
    echo "       数据库已就绪"
    break
  fi
  sleep 2
done

echo "==> [3/3] 启动后端 (FastAPI @ 8000) + 前端 (Vite @ 5173)"
# 后端：启动时 lifespan 会自动建表 + 灌种子数据
UV="$ROOT/backend/.venv/bin/uvicorn"
if [ -x "$UV" ]; then
  BACK_CMD="$UV"
else
  BACK_CMD=uvicorn
fi

cd "$ROOT/backend"
"$BACK_CMD" app.main:app --reload --host 0.0.0.0 --port 8000 &
BACK_PID=$!

cd "$ROOT/frontend"
npm run dev &
FRONT_PID=$!

trap 'echo; echo "停止中..."; kill $BACK_PID $FRONT_PID 2>/dev/null || true; echo "若进程残留，可手动：pkill -f uvicorn ; pkill -f vite"; exit 0' INT TERM

sleep 3
echo
echo "======================================================"
echo "  前端:      http://localhost:5173"
echo "  后端:      http://localhost:8000   (健康检查 /health)"
echo "  API 文档:  http://localhost:8000/docs"
echo "  按 Ctrl+C 停止前后端"
echo "======================================================"

# macOS 自动用浏览器打开
open "http://localhost:5173" 2>/dev/null || true

wait
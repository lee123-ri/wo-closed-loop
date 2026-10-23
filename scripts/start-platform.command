#!/usr/bin/env bash
# 桌面启动器的项目内版本；PMO mini 只等待新提问，不发送启动提醒。
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/Users/lee/bin:/Users/lee/.local/bin:/Users/lee/.local/node/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

start_pmo_bridge() {
  echo "==> 检查 PMO mini 工单问答接入（不发送提醒）"
  if "$ROOT/backend/.venv/bin/python" "$ROOT/scripts/pmomini_bridge_control.py" ensure --human; then
    echo "    支持私聊或群内 @，仅处理工单和平台相关问题。"
  else
    echo "    PMO mini 接入尚未就绪，平台可继续使用；请检查接入状态"
    return 1
  fi
}

if [ "${1:-}" = "--bridge-only" ]; then
  curl -fsS --max-time 5 http://127.0.0.1:8000/health/ready >/dev/null || exit 1
  start_pmo_bridge
  exit $?
fi

echo "软工单闭环管理平台 · 启动/重启"
for port in 8000 5173; do
  pids=$(lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  if [ -n "$pids" ]; then
    kill $pids 2>/dev/null || true
    sleep 1
    for pid in $pids; do
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    done
  fi
done

cd "$ROOT/backend" || exit 1
nohup "$ROOT/backend/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8000 >/tmp/wo-backend.log 2>&1 &
cd "$ROOT/frontend" || exit 1
nohup npm run dev >/tmp/wo-frontend.log 2>&1 &

ready=false
for attempt in $(seq 1 30); do
  if curl -fsS --max-time 2 http://127.0.0.1:8000/health/ready >/dev/null; then
    ready=true
    break
  fi
  sleep 1
done
if [ "$ready" != true ]; then
  echo "平台后端尚未就绪，未启动 PMO mini 接入。请查看平台运行日志。"
  read -rp "按回车退出..." _
  exit 1
fi
start_pmo_bridge || true
open http://localhost:5173 2>/dev/null || true
echo "平台服务已在后台运行；关闭此窗口或浏览器不会停止服务。"
read -rp "按回车关闭本窗口..." _

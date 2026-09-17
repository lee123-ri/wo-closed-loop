#!/bin/sh
# 后端/Worker/Scheduler 统一入口：导入 dws 凭证后启动主进程。
# 凭证包由 k8s Secret(wo-dws-auth) 挂载到 /secrets/dws-auth.tar.gz。
if command -v dws >/dev/null 2>&1 && [ -f /secrets/dws-auth.tar.gz ]; then
  if dws auth import -i /secrets/dws-auth.tar.gz --force -y >/dev/null 2>&1; then
    echo "[entrypoint] dws 凭证已导入"
  else
    echo "[entrypoint] dws 凭证导入失败：钉盘/AI表格同步不可用（检查凭证包是否过期）"
  fi
elif [ ! -f /secrets/dws-auth.tar.gz ]; then
  echo "[entrypoint] 未挂载 dws 凭证包（/secrets/dws-auth.tar.gz）：钉盘/AI表格同步不可用"
fi
exec "$@"

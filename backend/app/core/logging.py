"""结构化文件日志：标准 logging + 按天滚动，落 backend/logs/ 下 app.log 与 error.log。

用法
----
    from app.core.logging import setup_logging, get_logger
    log = get_logger(__name__)
    log.info("创建工单 code=%s", code)
    log.error("派发措施工单失败: %s", e, exc_info=True)

设计要点
--------
- app.log 收录全部级别（>= log_level）；error.log 只收 ERROR 及以上，方便快速翻错误。
- 按天滚动（midnight），保留 log_retention_days 天，旧文件自动删。
- log_to_stderr=True 时同时打到 stderr（保留现有终端排查习惯；uvicorn 的 access/error 日志仍走它自己的通道，不冲突）。
- 每条日志带请求 ID（[requestid]），由 RequestIDMiddleware 在请求内 set、RequestIDFilter 注入；
  后台线程（轮询器/Celery/钉钉 Stream）无请求上下文时显示 "-"。排查时用 requestid 串起
  访问日志（app.log 一行一条）+ 错误（error.log），是上线后定位问题的关键链路。
- get_logger / setup_logging 幂等：重复调用不会叠加 handler。
"""
from __future__ import annotations

import contextvars
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.core.config import get_settings

_configured = False

# 我们挂到 root 的自定义 handler 标记（幂等判定用，防止环境里二次 import 导致重复）
_MARK = "wo_file_log"

# 请求级 ID：RequestIDMiddleware 在请求生命周期内 set，日志经 RequestIDFilter 注入每条记录。
# 后台线程（轮询器 / Celery / 钉钉 Stream）没有请求上下文，值保持 None → 显示 "-"。
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


class RequestIDFilter(logging.Filter):
    """把当前请求 ID 注入 LogRecord.requestid，供 formatter 使用。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.requestid = request_id_var.get() or "-"
        return True


def _resolve_level(name: str) -> int:
    return getattr(logging, (name or "INFO").upper(), logging.INFO)


class _MarkedFileHandler(TimedRotatingFileHandler):
    """带标识的文件 handler，便于幂等检查时识别「自己人」。"""


def setup_logging() -> None:
    """初始化文件日志（幂等，可重复调用）。须在 get_settings 可用后调用。"""
    global _configured
    if _configured:
        return
    settings = get_settings()
    log_dir = Path(settings.log_dir)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 目录建不出来（如只读），就把文件日志降级为纯终端，不阻断启动
        _configured = True
        return

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(requestid)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _rid_filter = RequestIDFilter()
    level = _resolve_level(settings.log_level)
    backup_count = max(1, settings.log_retention_days)

    root = logging.getLogger()
    root.setLevel(level)

    # 幂等：已挂过我们的文件 handler 就不再重复挂（reload/二次 import 防护）
    already = any(getattr(h, "name", None) == _MARK for h in root.handlers)
    if already:
        _configured = True
        return

    app_handler = _MarkedFileHandler(
        log_dir / "app.log", when="midnight", backupCount=backup_count, encoding="utf-8",
    )
    app_handler.name = _MARK
    app_handler.setFormatter(fmt)
    app_handler.setLevel(level)
    app_handler.addFilter(_rid_filter)
    root.addHandler(app_handler)

    err_handler = _MarkedFileHandler(
        log_dir / "error.log", when="midnight", backupCount=backup_count, encoding="utf-8",
    )
    err_handler.name = _MARK
    err_handler.setFormatter(fmt)
    err_handler.setLevel(logging.ERROR)
    err_handler.addFilter(_rid_filter)
    root.addHandler(err_handler)

    if settings.log_to_stderr:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(fmt)
        stream.setLevel(level)
        stream.addFilter(_rid_filter)
        root.addHandler(stream)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """取命名 logger（root 已挂文件 handler，子 logger 自动继承；未初始化则先初始化）。"""
    if not _configured:
        setup_logging()
    return logging.getLogger(name)
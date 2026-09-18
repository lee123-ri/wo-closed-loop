"""请求级 ASGI 中间件：request_id + 访问日志。

刻意用纯 ASGI 中间件（不用 BaseHTTPMiddleware），避免后者另起任务带来的
contextvar 透传与流式响应问题，也省掉一次额外开销——这是性能改造的一部分。

- RequestIDMiddleware：透传/生成 X-Request-Id，写回响应头，并把 ID 塞进 request_id_var
  供日志携带（见 app.core.logging.RequestIDFilter）。
- AccessLogMiddleware：一行一条访问日志（method path status 耗时 ip uid），
  慢请求（>= access_log_slow_ms）升级 WARNING。探针类请求不打，避免刷屏。
"""
from __future__ import annotations

import time
import uuid

from app.core.config import get_settings
from app.core.logging import get_logger, request_id_var

settings = get_settings()
log = get_logger("access")

# 探针类请求不打访问日志（k8s liveness/readiness 每 ~10s 一次，避免刷屏）
_SKIP_PATHS = {"/health", "/health/ready"}


def _header(scope: dict, name: str) -> str | None:
    for k, v in scope.get("headers", []):
        if k == name.encode("latin-1"):
            return v.decode("latin-1")
    return None


def _scope_client_ip(scope: dict) -> str:
    """与 security_middleware.client_ip 同口径，但作用在裸 ASGI scope 上。"""
    if settings.trust_x_forwarded_for:
        xff = _header(scope, "x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    xri = _header(scope, "x-real-ip")
    if xri:
        return xri.strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


def _extract_uid(scope: dict) -> str:
    """尽力从 JWT 里取用户 id（sub），取不到给 "-"。解析失败绝不影响请求。"""
    auth = _header(scope, "authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        try:
            from app.core.security import decode_token

            payload = decode_token(token)
            if payload and payload.get("sub"):
                return str(payload["sub"])
        except Exception:
            pass
    return "-"


class RequestIDMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = _header(scope, "x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)

        async def send_with_rid(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"x-request-id", rid.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_with_rid)
        finally:
            request_id_var.reset(token)


class AccessLogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") in _SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status: int = 0

        async def send_with_status(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            method = scope.get("method", "")
            path = scope.get("path", "")
            qs = scope.get("query_string", b"")
            query = ("?" + qs.decode("latin-1")) if qs else ""
            ip = _scope_client_ip(scope)
            uid = _extract_uid(scope)
            msg = f"{method} {path}{query} {status} {elapsed_ms:.1f}ms ip={ip} uid={uid}"
            if elapsed_ms >= settings.access_log_slow_ms:
                log.warning("[SLOW] " + msg)
            else:
                log.info(msg)
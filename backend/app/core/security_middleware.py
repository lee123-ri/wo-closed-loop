"""安全中间件：速率限制 + 安全响应头。

- 速率限制：全局 100/min，鉴权类 10/min
- 安全响应头：X-Content-Type-Options, X-Frame-Options, Referrer-Policy, HSTS(生产)
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings

settings = get_settings()

# 限流器存储：优先 Redis（多实例共享计数），连不上则降级内存（单实例）
def _build_limiter() -> Limiter:
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_connect_timeout=1)
        r.ping()
        return Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)
    except Exception:
        # Redis 不可用，内存存储（单实例；生产多实例需 Redis）
        return Limiter(key_func=get_remote_address)

limiter = _build_limiter()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """注入安全响应头"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=()"
        # 生产环境启用 HSTS（需 HTTPS）
        if settings.is_prod:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "请求过于频繁，请稍后再试", "limit": str(exc.detail) if hasattr(exc, "detail") else ""},
    )

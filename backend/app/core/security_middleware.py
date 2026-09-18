"""安全中间件：速率限制（按真实客户端 IP）+ 安全响应头。

- 速率限制：各端点按需 + 限流 key 取真实客户端 IP（见 client_ip，规避 nginx 反代后全员共桶）
- 安全响应头：X-Content-Type-Options, X-Frame-Options, Referrer-Policy, HSTS(生产)
"""
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings

settings = get_settings()


def client_ip(request: Request) -> str:
    """限流 key：按真实客户端 IP 计，而不是代理 IP。

    生产拓扑是 浏览器 → nginx(pod) → uvicorn，若用默认 get_remote_address 会拿到 nginx pod IP，
    全员共用一个限流桶，用户一多就集体 429。
    - nginx 的 `proxy_set_header X-Real-IP $remote_addr` 是「覆盖写」，客户端伪造会被覆盖，可直接采信；
    - `X-Forwarded-For` 用的是 `$proxy_add_x_forwarded_for`「追加」，最左侧可被客户端伪造，
      默认不采信，只有 trust_x_forwarded_for=true（确定前面还有一层 SLB 会重写 XFF 时）才读。
    """
    if settings.trust_x_forwarded_for:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()
    return request.client.host if request.client else "unknown"


# 限流器存储：优先 Redis（多实例共享计数），连不上则降级内存（单实例）
def _build_limiter() -> Limiter:
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_connect_timeout=1)
        r.ping()
        return Limiter(key_func=client_ip, storage_uri=settings.redis_url)
    except Exception:
        # Redis 不可用，内存存储（单实例；生产多实例需 Redis）
        return Limiter(key_func=client_ip)

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

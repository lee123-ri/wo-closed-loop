"""FastAPI 应用入口"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, bot, config, dashboard, dingtalk, imports, pool, workorders
from app.core.config import get_settings
from app.core.security_middleware import (
    SecurityHeadersMiddleware, SlowAPIMiddleware, limiter, rate_limit_exceeded_handler,
)
from slowapi.errors import RateLimitExceeded

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.5.0",
    description="软工单闭环管理系统 API",
)

# 限流
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# 中间件（顺序：外层到内层）
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list if settings.is_prod else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
@limiter.limit("60/minute")
def health(request: Request):
    return {"status": "ok", "env": settings.app_env}


app.include_router(auth.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(workorders.router, prefix="/api")
app.include_router(config.router, prefix="/api")
app.include_router(dingtalk.router, prefix="/api")
app.include_router(bot.router, prefix="/api")
app.include_router(imports.router, prefix="/api")
app.include_router(pool.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

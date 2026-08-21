"""FastAPI 应用入口"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, bot, config, dashboard, dingtalk, imports, pool, workorders
from app.core.config import get_settings
from app.core.security_middleware import (
    SecurityHeadersMiddleware, SlowAPIMiddleware, limiter, rate_limit_exceeded_handler,
)
from slowapi.errors import RateLimitExceeded

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时自动建表 + 检查是否需要灌入种子数据"""
    try:
        from app.core.database import SessionLocal, Base, engine
        # 自动创建缺失的表（无需手动跑 alembic）
        Base.metadata.create_all(bind=engine)
        from app.models import WorkOrder, User
        db = SessionLocal()
        try:
            user_count = db.query(User).count()
            wo_count = db.query(WorkOrder).count()
            if user_count == 0 or wo_count == 0:
                print(f"[startup] 数据库为空（用户{user_count}，工单{wo_count}），自动灌入种子数据...")
                from app.seed import run
                run()
                print("[startup] 种子数据灌入完成")
        finally:
            db.close()
    except Exception as e:
        print(f"[startup] 种子数据检查跳过（可能数据库未就绪）: {e}")
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.5.0",
    description="软工单闭环管理系统 API",
    lifespan=lifespan,
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

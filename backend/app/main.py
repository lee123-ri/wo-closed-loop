"""FastAPI 应用入口"""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin, auth, bot, config, dashboard, dingtalk, external, imports, pool, workorders
from app.api.auth import require_admin, require_auth
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.middleware import AccessLogMiddleware, RequestIDMiddleware
from app.core.security_middleware import (
    SecurityHeadersMiddleware, SlowAPIMiddleware, limiter, rate_limit_exceeded_handler,
)
from slowapi.errors import RateLimitExceeded

settings = get_settings()
setup_logging()  # 文件日志落地（app.log + error.log），须早于任何 logger 使用
log = logging.getLogger("app")


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
            # 生产环境永不自动灌演示数据；开发环境可用 AUTO_SEED=false 关闭
            if settings.auto_seed and not settings.is_prod and (user_count == 0 or wo_count == 0):
                print(f"[startup] 数据库为空（用户{user_count}，工单{wo_count}），自动灌入种子数据...")
                from app.seed import run
                run()
                print("[startup] 种子数据灌入完成")
        finally:
            db.close()
    except Exception as e:
        print(f"[startup] 启动初始化跳过（可能数据库未就绪）: {e}")
    try:
        from app.services import dingtalk_stream
        dingtalk_stream.start_stream()
    except Exception as e:
        print(f"[startup] 钉钉 Stream 接入跳过: {e}")
    try:
        from app.services import oa_poller
        oa_poller.start(10)
    except Exception as e:
        print(f"[startup] OA 自动轮询启动失败: {e}")
    try:
        # 本地开发没起 Celery，用进程内轮询兜底跑「标逾期 → 升级告警」，告警列才不空。
        # 生产（is_prod）由 Celery beat 负责，此处不启用，避免重复扫描。
        if settings.sla_poller_enabled and not settings.is_prod:
            from app.services import sla_poller
            sla_poller.start(settings.sla_poller_interval)
    except Exception as e:
        print(f"[startup] 进程内 SLA 扫描启动失败: {e}")
    try:
        # 异常指标表准实时增量同步 + 年度运营计划初稿（非EAM）轮询导入（只落新增/去重）。
        # 生产由 Celery beat 负责，此处仅本地开发兜底。
        if not settings.is_prod:
            from app.services import sync_poller
            sync_poller.start(settings.anomaly_sync_interval, settings.plan_sync_interval)
    except Exception as e:
        print(f"[startup] 异常指标/计划同步启动失败: {e}")
    try:
        # 主动巡检（静默失效扫描）——本地走进程内轮询，生产由 Celery beat 调 run_sweep
        if not settings.is_prod:
            from app.services import health_sweep
            health_sweep.start()
    except Exception as e:
        print(f"[startup] 主动巡检启动失败: {e}")
    yield
    try:
        from app.services import oa_poller
        await oa_poller.stop()
    except Exception as e:
        print(f"[shutdown] OA 轮询停止失败: {e}")
    try:
        from app.services import sla_poller
        await sla_poller.stop()
    except Exception as e:
        print(f"[shutdown] SLA 扫描停止失败: {e}")
    try:
        from app.services import sync_poller
        await sync_poller.stop()
    except Exception as e:
        print(f"[shutdown] 数据同步轮询停止失败: {e}")
    try:
        from app.services import health_sweep
        await health_sweep.stop()
    except Exception as e:
        print(f"[shutdown] 主动巡检停止失败: {e}")
    try:
        from app.services import dingtalk_stream
        await dingtalk_stream.stop_stream()
    except Exception as e:
        print(f"[shutdown] 钉钉 Stream 停止失败: {e}")


app = FastAPI(
    title=settings.app_name,
    version="0.6.0",
    description="工单管理平台 API",
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
# 请求级中间件：最后 add 的在最外层。目标顺序（外→内）：
# RequestID → AccessLog → CORS → SecurityHeaders → SlowAPI(限流，最贴近应用)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(RequestIDMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底：未捕获异常记 ERROR 并单发告警。

    注意：业务自抛的 HTTPException（422 缺字段 / 409 状态不允许）走 FastAPI 内置 handler，
    不会到这里——那些是可预期、由前端 toast 引导用户自行处理的，不当故障告警。
    这里只兜真正的 500（代码 bug / DB 异常 / 外部调用异常）。
    """
    log.error(
        "未捕获异常 %s %s -> %s: %s",
        request.method, request.url.path, type(exc).__name__, exc,
        exc_info=exc,
    )
    try:
        from app.services.alert_service import send_alert

        send_alert(
            "后端未捕获异常",
            detail=f"端点：{request.method} {request.url.path}\n"
                   f"异常：{type(exc).__name__}: {exc}",
            fix="查 backend/logs/error.log 的 traceback 定位后修复",
            key=f"unhandled:{request.url.path}",
        )
    except Exception:  # 告警自身失败绝不影响响应
        pass
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})


@app.get("/health", tags=["meta"])
@limiter.limit("60/minute")
def health(request: Request):
    return {"status": "ok", "env": settings.app_env}


@app.get("/health/ready", tags=["meta"])
@limiter.limit("60/minute")
def readiness(request: Request):
    """就绪探针：进程存活之外，确认数据库连接可用。"""
    try:
        from sqlalchemy import text
        from app.core.database import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": "unavailable"})
    return {"status": "ready", "database": "ok", "env": settings.app_env}


app.include_router(auth.router, prefix="/api")
# 业务路由统一强制鉴权（router 级 dependencies；各自路由内的豁免端点单独处理）
app.include_router(dashboard.router, prefix="/api", dependencies=[Depends(require_auth)])
app.include_router(workorders.router, prefix="/api", dependencies=[Depends(require_auth)])
app.include_router(config.router, prefix="/api", dependencies=[Depends(require_auth)])
app.include_router(dingtalk.router, prefix="/api", dependencies=[Depends(require_auth)])
# 钉钉服务端回调（OA 审批推送）无用户 JWT，走公开路由，靠验签保护
app.include_router(dingtalk.public_router, prefix="/api")
# bot 是钉钉机器人回调，钉钉服务端推送、无用户 JWT，保持公开（有独立限流）
app.include_router(bot.router, prefix="/api")
# 外部系统/Agent 建单与查询：走 X-API-Key（不走用户 JWT），鉴权在 external.require_api_key 内
app.include_router(external.router, prefix="/api")
app.include_router(imports.router, prefix="/api", dependencies=[Depends(require_auth)])
app.include_router(pool.router, prefix="/api", dependencies=[Depends(require_auth)])
app.include_router(admin.router, prefix="/api", dependencies=[Depends(require_admin)])

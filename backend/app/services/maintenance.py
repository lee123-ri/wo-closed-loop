"""「暂停发单」系统开关：维护期冻结一切「新建/派发工单」入口。

存储：ConfigDefinition(category="system", code="pause_order_issuance") 的 extra.enabled。
DB 持久化、前端按钮即点即生效，免重启；只允许管理员（李沛东）切换，见 config.py 写接口。

被拦截的语义 = 不会有任何新工单进入（含手动建单、外部 API、派发发起 OA、数据池生成、
异常/计划自动导入、措施工单生成、按月计划派发），但不阻断既有工单的 OA 状态回写等只读同步。
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import ConfigDefinition

PAUSE_CATEGORY = "system"
PAUSE_CODE = "pause_order_issuance"
PAUSE_NAME = "暂停发单"

_PAUSE_HTTP_MSG = "系统维护中：已暂停发单，暂不能新建或派发工单，请稍后再试"


def is_paused(db: Session) -> bool:
    """是否处于「暂停发单」状态。未持久化过时默认不暂停。"""
    row = (
        db.query(ConfigDefinition)
        .filter(ConfigDefinition.category == PAUSE_CATEGORY, ConfigDefinition.code == PAUSE_CODE)
        .first()
    )
    return bool((row.extra or {}).get("enabled") if row else False)


def ensure_open(db: Session) -> None:
    """API 建单/派发入口统一拦截：暂停时抛 423，前端据此提示。"""
    if is_paused(db):
        raise HTTPException(status_code=423, detail=_PAUSE_HTTP_MSG)


def state(db: Session) -> dict:
    """返回当前开关状态（读接口用）。"""
    return {"paused": is_paused(db), "code": PAUSE_CODE, "name": PAUSE_NAME}


def set_paused(db: Session, enabled: bool, actor_id: int | None = None) -> dict:
    """开启/关闭「暂停发单」，upsert 持久化并记操作日志。返回 {"paused": bool}。"""
    row = (
        db.query(ConfigDefinition)
        .filter(ConfigDefinition.category == PAUSE_CATEGORY, ConfigDefinition.code == PAUSE_CODE)
        .first()
    )
    if row is None:
        row = ConfigDefinition(category=PAUSE_CATEGORY, code=PAUSE_CODE, name=PAUSE_NAME, extra={})
        db.add(row)
    row.name = PAUSE_NAME
    row.extra = {**(row.extra or {}), "enabled": bool(enabled)}
    db.flush()
    from app.services.audit import log_audit
    log_audit(
        db, actor_id=actor_id,
        action="pause_order_issuance" if enabled else "resume_order_issuance",
        target_type="config", target_id=row.id,
        detail={"enabled": bool(enabled)},
    )
    db.commit()
    return {"paused": bool(enabled)}
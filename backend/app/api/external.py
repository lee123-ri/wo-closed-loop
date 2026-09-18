"""对外 API：给外部系统 / Agent 提供「带 API Key」的建单与查询通道。

与内部 `/work-orders` 的区别：
1. 鉴权：`X-API-Key`（环境变量 `EXTERNAL_API_KEY`），不走钉钉 OAuth / 用户 JWT；
2. 入参：项目 / 责任人 / 审批人 / 工单类型按「名称或编码」传入，后端解析为内部 id；
   ——解析不到直接报错（404/409），不自动新建实体；
3. 幂等：`client_request_id` 去重，网络重试返回首次创建的那条工单，不重复建单；
4. 语义：外部建单默认落「待派发(pending)」，不自动发起钉钉审批，由平台内人工派发
   （dispatch）进入后续 OA 闭环。
"""
import hmac
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import (
    Project, SLADefinition, StatusLog, User, WorkOrder, WorkOrderTypeKB,
)
from app.schemas.external import ExternalWorkOrderCreate
from app.schemas.workorder import WorkOrderOut
from app.api.workorders import _enrich, _next_code
from app.services.audit import log_audit
from app.services.priority_service import normalize_priority
from app.services.roles import resolve_role_user_id
from app.services.maintenance import ensure_open

router = APIRouter(prefix="/external", tags=["external"])
settings = get_settings()


# ── API Key 鉴权 ──────────────────────────────────────

def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """校验 X-API-Key 请求头。未配置（EXTERNAL_API_KEY 为空）视为接口整体禁用。"""
    if not settings.external_api_key:
        raise HTTPException(503, "外部建单接口未启用：服务端未配置 EXTERNAL_API_KEY")
    if not x_api_key:
        raise HTTPException(401, "缺少 X-API-Key 请求头")
    if not hmac.compare_digest(x_api_key, settings.external_api_key):
        raise HTTPException(401, "X-API-Key 无效")


# ── 名称 / 编码解析（找不到即报错，不自动新建） ──────

def _resolve_project(db: Session, code: str | None, name: str | None) -> Project:
    if code:
        c = code.strip()
        p = db.query(Project).filter(Project.code == c).first()
        if not p:
            raise HTTPException(404, f"项目编码不存在：{c}")
        return p
    if name:
        n = name.strip()
        rows = db.query(Project).filter(Project.name == n).all()
        if not rows:
            raise HTTPException(404, f"项目不存在：{n}")
        if len(rows) > 1:
            raise HTTPException(409, f"项目名称存在重复，请改用 project_code：{n}")
        return rows[0]
    raise HTTPException(422, "缺少项目：请提供 project_code 或 project_name")


def _resolve_user_by_name(db: Session, name: str | None, label: str) -> User:
    if not name:
        raise HTTPException(422, f"缺少{label}")
    n = name.strip()
    rows = db.query(User).filter(User.name == n, User.is_active.is_(True)).all()
    if not rows:
        raise HTTPException(404, f"{label}不存在或已禁用：{n}")
    if len(rows) > 1:
        raise HTTPException(409, f"{label}存在同名用户，无法唯一确定：{n}")
    return rows[0]


def _resolve_type_code(db: Session, code: str | None, name: str | None) -> str | None:
    """按「工单类型 code / 名称」解析为统一类型 code（category=work_order_type）。找不到即报错。"""
    from app.models import ConfigDefinition

    if code:
        cd = db.query(ConfigDefinition).filter_by(category="work_order_type", code=code.strip()).first()
        if not cd:
            raise HTTPException(404, f"工单类型编码不存在：{code}")
        return cd.code
    if name:
        cd = db.query(ConfigDefinition).filter(
            ConfigDefinition.category == "work_order_type",
            ConfigDefinition.name == name.strip(),
        ).first()
        if not cd:
            raise HTTPException(404, f"工单类型不存在：{name}")
        return cd.code
    return None


# ── 建单 ──────────────────────────────────────────────

@router.post("/work-orders", response_model=WorkOrderOut)
def create_external_work_order(
    body: ExternalWorkOrderCreate,
    response: Response,
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    ensure_open(db)  # 暂停发单开关：外部 API 建单同样拦截
    # 幂等：同 client_request_id 重复提交，返回首次创建的那条工单（200）
    if body.client_request_id:
        existing = (
            db.query(WorkOrder)
            .filter(WorkOrder.client_request_id == body.client_request_id.strip())
            .first()
        )
        if existing:
            response.status_code = 200
            return _enrich(existing, db)

    project = _resolve_project(db, body.project_code, body.project_name)
    person_id = (_resolve_user_by_name(db, body.person_name, "责任人").id
                 if body.person_name else None)
    type_code = _resolve_type_code(db, body.type_code, body.type_name)
    # 工单类型：type_code/type_name 解析优先，其次显式 source_code，最后兜底「关键会议」
    from app.services.work_order_types import is_anomaly_type, type_approver_name
    from app.models import ConfigDefinition
    final_type = type_code or (body.source_code or "meeting")
    if not db.query(ConfigDefinition).filter_by(category="work_order_type", code=final_type).first():
        raise HTTPException(422, f"工单类型非法：{final_type}（仅限已配置工单类型 code）")

    if body.approver_name:
        approver_id = _resolve_user_by_name(db, body.approver_name, "审批人").id
    else:
        _an = type_approver_name(db, final_type)
        _au = db.query(User).filter(User.name == _an).first() if _an else None
        approver_id = _au.id if _au else None

    # 优先级：显式传入须合法；留空按类型推断（异常类→P1，其余 P2 —— 与内部建单一致）
    if body.priority:
        pri = normalize_priority(body.priority)
        if not pri:
            raise HTTPException(422, f"优先级非法：{body.priority}（仅支持 P1/P2/P3）")
    else:
        pri = "P1" if is_anomaly_type(final_type) else "P2"

    # 截止时间：未填按 SLA 默认天数顺延（与内部建单一致）
    if body.deadline:
        deadline = body.deadline
    else:
        sla = db.query(SLADefinition).filter_by(priority=pri).first()
        deadline = date.today() + timedelta(days=(sla.deadline_days if sla else 7))

    wo = WorkOrder(
        code=_next_code(db),
        client_request_id=body.client_request_id.strip() if body.client_request_id else None,
        title=body.title,
        reason=body.reason,
        action=body.action,
        project_id=project.id,
        person_id=person_id,
        approver_id=approver_id,
        source_code=final_type,
        priority=pri,
        region=body.region,
        planned_start_date=body.planned_start_date,
        deadline=deadline,
        created_date=date.today(),
        status="pending",  # 外部建单落「待派发」，不自动发起钉钉审批
    )
    db.add(wo)
    db.flush()
    db.add(StatusLog(work_order_id=wo.id, from_status=None, to_status="pending", note="外部 API 创建"))
    log_audit(db, actor_id=None, action="external_create", target_type="work_order", target_id=wo.id,
              detail={"code": wo.code, "title": wo.title, "client_request_id": wo.client_request_id,
                      "source_code": wo.source_code})
    try:
        db.commit()
    except IntegrityError:
        # 极端并发下同 client_request_id 同时到达：以先落库的为准
        db.rollback()
        if body.client_request_id:
            existing = (
                db.query(WorkOrder)
                .filter(WorkOrder.client_request_id == body.client_request_id.strip())
                .first()
            )
            if existing:
                response.status_code = 200
                return _enrich(existing, db)
        raise
    db.refresh(wo)
    response.status_code = 201
    return _enrich(wo, db)


# ── 查询 ──────────────────────────────────────────────

@router.get("/work-orders", response_model=WorkOrderOut)
def query_external_work_order(
    code: str | None = None,
    client_request_id: str | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    """按工单编号（code）或调用方请求标识（client_request_id）查询工单现状，二者至少其一。"""
    if not code and not client_request_id:
        raise HTTPException(422, "请提供 code 或 client_request_id 之一")
    if code:
        wo = db.query(WorkOrder).filter(WorkOrder.code == code.strip()).first()
    else:
        wo = (
            db.query(WorkOrder)
            .filter(WorkOrder.client_request_id == client_request_id.strip())
            .first()
        )
    if not wo:
        raise HTTPException(404, "工单不存在")
    return _enrich(wo, db)
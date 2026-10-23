"""Only SELECTs on the platform; never create a login session or business record."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import func, text
from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.models import ConfigDefinition, Project, User, WorkOrder, NotificationLog
try:
    from app.models import WorkOrderFollowupEvent
except ImportError:
    WorkOrderFollowupEvent = None
from app.services.scope import apply_scope_to_query
try:
    from app.services.bot_query_settings import get_bot_query_settings
except ImportError:
    get_bot_query_settings = None
TERMINAL_STATUSES = {"closed", "rejected", "cancelled"}

# Do not log business data as SQL parameters in this separate read-only service.
engine.echo = False
REGIONS = {"华北", "华中", "华东", "华南", "西北", "西南", "东北"}


class QueryBlocked(Exception):
    pass


def query(plan: dict, event: dict, group_projects: dict) -> dict:
    with SessionLocal() as db:
        try:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            db.execute(text("SET LOCAL statement_timeout='5000'"))
            return query_session(db, plan, event, group_projects)
        finally:
            db.rollback()


def query_session(db, plan: dict, event: dict, group_projects: dict) -> dict:
    # Match stable staff ID, never nickname; duplicates are deliberately blocked.
    users = db.query(User).filter(User.dingtalk_id == event["senderStaffId"], User.is_active.is_(True)).limit(2).all()
    if len(users) != 1:
        raise QueryBlocked("提问人的钉钉身份尚未唯一绑定到有效平台账号，请先在平台确认账号绑定。")
    user = users[0]
    q = apply_scope_to_query(db.query(WorkOrder), db, user)
    if event["conversationType"] == "2":
        projects = group_projects.get(event["conversationId"])
        if projects is None:
            existing = get_bot_query_settings().authorizations.get(event["conversationId"]) if get_bot_query_settings else None
            projects = existing.project_ids if existing else None
        if not projects or not all(isinstance(i, int) and not isinstance(i, bool) and i > 0 for i in projects):
            raise QueryBlocked("本群尚未配置可查询的项目范围。可以在群里询问平台操作；具体工单数据请私聊查询，或由管理员配置本群项目范围。")
        q = q.filter(WorkOrder.project_id.in_(projects))
    if plan.get("region"):
        if plan["region"] not in REGIONS:
            raise QueryBlocked("区域未能匹配平台七大区，请补充明确区域。")
        q = q.filter(WorkOrder.region == plan["region"])
    if plan.get("status"):
        if not db.query(ConfigDefinition.id).filter_by(category="status", code=plan["status"]).first():
            raise QueryBlocked("工单状态未能匹配平台配置，请补充准确状态或工单编号。")
        q = q.filter(WorkOrder.status == plan["status"])
    if plan.get("project_code"):
        q = q.join(Project, Project.id == WorkOrder.project_id).filter(Project.code == plan["project_code"])
    code = plan.get("work_order_code")
    if code:
        # Reject fabricated/changed identifiers from the model.
        context_code = event.get("_context", {}).get("work_order_code")
        if code not in event["text"]["content"] and code != context_code:
            raise QueryBlocked("未能确认准确工单编号，请提供完整编号。")
        q = q.filter(WorkOrder.code == code)
    intent = plan["intent"]
    if intent in {"work_order", "escalation"} and not code:
        raise QueryBlocked("请提供需要查询的完整工单编号。")
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if intent == "overdue":
        q = q.filter(WorkOrder.deadline < now.date(), WorkOrder.status.notin_(TERMINAL_STATUSES | {"pending"}))
    total = q.count()
    names = dict(db.query(ConfigDefinition.code, ConfigDefinition.name).filter_by(category="status").all())
    base = get_settings().frontend_base_url.rstrip("/")
    if intent == "stats":
        counts = q.with_entities(WorkOrder.status, func.count(WorkOrder.id)).group_by(WorkOrder.status).order_by(WorkOrder.status).all()
        answer = f"当前授权及筛选范围内共 {total} 张工单。\n" + "\n".join(f"{names.get(s,s)}：{n} 张" for s,n in counts)
    elif intent == "projects":
        rows = q.with_entities(WorkOrder.project_id).distinct().all()
        projects = db.query(Project).filter(Project.id.in_([p for p, in rows])).order_by(Project.code).all()
        page = plan.get("page", 1)
        answer = f"授权范围内存在匹配工单的项目共 {len(projects)} 个。\n" + "\n".join(f"{p.code} · {p.name}" for p in projects[(page-1)*10:page*10])
        answer += f"\n第 {page} 页，每页最多10个；不等于公司全部项目。"
        if page * 10 < len(projects):
            answer += "\n还有后续页，可继续询问下一页。"
    else:
        page = plan.get("page", 1)
        rows = q.order_by(WorkOrder.deadline.asc().nullslast(), WorkOrder.id).offset((page-1)*10).limit(10).all()
        title = "已派发、未结束且截止日早于今天的逾期工单" if intent == "overdue" else "匹配工单"
        answer = f"授权及筛选范围内{title}共 {total} 张。\n"
        for wo in rows:
            person = db.get(User, wo.person_id) if wo.person_id else None
            project = db.get(Project, wo.project_id) if wo.project_id else None
            answer += f"\n[{wo.code}]({base}/work-orders/{wo.id}) · {wo.title}\n{project.name if project else '未关联项目'} · 责任人：{person.name if person else '未配置'} · {names.get(wo.status,wo.status)} · 截止：{wo.deadline or '未配置'}\n"
            if intent == "escalation":
                if WorkOrderFollowupEvent is None:
                    raise QueryBlocked("当前平台版本没有可用的跟催事件明细，请在平台核对跟催记录。")
                counts = db.query(WorkOrderFollowupEvent.status, func.count(WorkOrderFollowupEvent.id)).filter_by(work_order_id=wo.id).group_by(WorkOrderFollowupEvent.status).all()
                notifications = db.query(NotificationLog.status, func.count(NotificationLog.id)).filter_by(work_order_id=wo.id).group_by(NotificationLog.status).all()
                answer += f"跟催运行记录：{dict(counts)}；通知记录：{dict(notifications)}。配置或sent记录不等于实际送达。\n"
        answer += f"\n第 {page} 页，每页最多10张。"
        if page * 10 < total:
            answer += "还有后续页，可继续询问下一页。"
        if total == 0:
            answer += "仅说明授权和筛选范围内未找到，不能据此判断全平台不存在。"
    filters = {k: v for k,v in plan.items() if k in {"region", "status", "project_code", "work_order_code"} and v}
    if filters:
        answer += "\n筛选条件：" + "；".join(f"{k}={v}" for k,v in filters.items())
    answer += f"\n\n查询时点：{now:%Y-%m-%d %H:%M:%S}（北京时间）；依据：[工单平台]({base}/work-orders)。仅限当前会话与提问人的授权范围。"
    return {"answer": answer, "total": total, "filters": filters, "query_time": now.isoformat(), "source": "platform_read_only_transaction"}

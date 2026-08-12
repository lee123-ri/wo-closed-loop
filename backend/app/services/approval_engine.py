"""审批流引擎：按优先级匹配审批流模板、定位当前节点、超时自动升级。"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import ApprovalFlow, WorkOrder, EscalationLog


def get_flow(db: Session, priority: str) -> ApprovalFlow | None:
    """按优先级取启用的审批流模板"""
    return (
        db.query(ApprovalFlow)
        .filter(ApprovalFlow.priority == priority, ApprovalFlow.enabled.is_(True))
        .first()
    )


def current_node(db: Session, wo: WorkOrder) -> dict | None:
    """根据工单状态推算当前审批节点"""
    flow = get_flow(db, wo.priority)
    if not flow:
        return None
    # 状态 → 节点类型映射
    type_map = {
        "pending": "start",
        "approving": "approval",
        "dispatched": "exec",
        "executing": "exec",
        "verifying": "approval",
        "closed": "end",
        "overdue": "exec",
        "rejected": "end",
    }
    target = type_map.get(wo.status)
    if not target:
        return None
    for node in flow.nodes:
        if node.get("type") == target:
            return node
    return flow.nodes[0] if flow.nodes else None


def check_escalation(db: Session, wo: WorkOrder) -> int:
    """检查工单是否需要升级（基于 overdue_days 和 escalation_level）。

    升级阶梯：
      overdue_days >= 1  → L1 预警
      overdue_days >= 3  → L2 升级（抄送审批人）
      overdue_days >= 7  → L3 严重（升级上级）
    返回新 escalation_level（0 表示无需升级）。
    """
    if wo.status != "overdue" or wo.overdue_days <= 0:
        return 0
    days = wo.overdue_days
    if days >= 7:
        new_lvl = 3
    elif days >= 3:
        new_lvl = 2
    else:
        new_lvl = 1
    if new_lvl <= wo.escalation_level:
        return 0
    # 写升级记录
    flow = get_flow(db, wo.priority)
    target = ""
    if flow and flow.escalation:
        target = flow.escalation.get("target", "")
    db.add(EscalationLog(
        work_order_id=wo.id, level=new_lvl,
        triggered_at=datetime.now(timezone.utc), target=target,
    ))
    wo.escalation_level = new_lvl
    db.commit()
    return new_lvl


def run_escalation_scan() -> dict:
    """定时任务：扫描所有逾期工单，触发升级。"""
    db = SessionLocal()
    escalated = 0
    try:
        overdue_wos = db.query(WorkOrder).filter(WorkOrder.status == "overdue").all()
        for wo in overdue_wos:
            # 实时算 overdue_days（若种子未设）
            if wo.overdue_days == 0 and wo.deadline:
                wo.overdue_days = (datetime.now(timezone.utc).date() - wo.deadline).days
                if wo.overdue_days < 0:
                    continue
            if check_escalation(db, wo):
                escalated += 1
    finally:
        db.close()
    return {"scanned": len(overdue_wos), "escalated": escalated}

"""数据重置/清空管理 API：清空演示工单、日志，保留配置。

用于「从头测试」：保留 用户/项目/类型/SLA/审批流/规则 等配置，
只清空 事务性数据（工单 + 状态日志 + 通知日志 + 升级日志 + 附件）。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db
from app.models import Attachment, EscalationLog, NotificationLog, StatusLog, WorkOrder, AgentImportBatch

router = APIRouter(prefix="/admin", tags=["admin"])


@router.delete("/clear-data")
def clear_transactional_data(db: Session = Depends(get_db)):
    """清空事务性数据，保留配置和主数据。

    清空：work_orders, status_log, notification_log, escalation_log, attachments
    保留：users, projects, config_definitions, workorder_type_kb, sla_definitions,
         approval_flows, notification_policies, priority_rules, parsing_rules
    """
    # 按外键依赖顺序删除（含可靠性Agent导入批次，重置后即可重导重测）
    for model in [NotificationLog, EscalationLog, Attachment, StatusLog, WorkOrder, AgentImportBatch]:
        db.query(model).delete()
    db.commit()
    # 重置自增序列（PG）
    db.execute(text("SELECT setval('work_orders_id_seq', 1, false)"))
    db.execute(text("SELECT setval('status_log_id_seq', 1, false)"))
    db.execute(text("SELECT setval('agent_import_batches_id_seq', 1, false)"))
    db.commit()
    return {"cleared": ["work_orders", "status_log", "notification_log", "escalation_log", "attachments", "agent_import_batches"], "kept": ["users", "projects", "config", "rules", "sla", "approval_flows"]}


@router.get("/stats")
def data_stats(db: Session = Depends(get_db)):
    """各表数据量统计"""
    from app.models import (
        ConfigDefinition, WorkOrderTypeKB, PriorityRule, ParsingRule,
        SLADefinition, ApprovalFlow, NotificationPolicy, PersonProjectMap,
        User, Project,
    )
    return {
        "users": db.query(User).count(),
        "projects": db.query(Project).count(),
        "work_orders": db.query(WorkOrder).count(),
        "sources": db.query(ConfigDefinition).filter_by(category="source").count(),
        "statuses": db.query(ConfigDefinition).filter_by(category="status").count(),
        "wo_types": db.query(WorkOrderTypeKB).count(),
        "priority_rules": db.query(PriorityRule).count(),
        "parsing_rules": db.query(ParsingRule).count(),
        "sla": db.query(SLADefinition).count(),
        "approval_flows": db.query(ApprovalFlow).count(),
        "notification_policies": db.query(NotificationPolicy).count(),
        "person_map": db.query(PersonProjectMap).count(),
    }

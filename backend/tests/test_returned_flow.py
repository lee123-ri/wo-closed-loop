"""点2 测试：退回重填(returned) 路由 + 根因回填"""
from datetime import date

from app.api.dingtalk import _current_stage, _sync_oa_results
from app.models import WorkOrder


def _mk_wo(db, code="RT-TEST") -> WorkOrder:
    wo = WorkOrder(
        code=code, title="退单测试", source_code="manual",
        status="verifying", created_date=date.today(),
        project_id=1, person_id=1, approver_id=11,
    )
    db.add(wo)
    db.commit()
    db.refresh(wo)
    return wo


def test_current_stage_returns_accept(db):
    """验收节点(accept)尚未通过时，refuse 应判为退回重填。"""
    wo = _mk_wo(db)
    wo.oa_progress = [
        {"stage": "approve", "role": "pmo", "approved": True},
        {"stage": "execute", "role": "executor", "approved": True},
        {"stage": "accept", "role": "approver", "approved": False},
    ]
    db.commit()
    assert _current_stage(wo) == "accept"


def test_sync_oa_results_backfills_reason(db):
    """闭环时把钉钉表单「根因分析」回填到工单 backfill_reason。"""
    wo = _mk_wo(db, code="RT-TEST-2")
    form_values = [
        {"name": "执行结论", "value": "已处理完成"},
        {"name": "根因分析", "value": "组件连接松动导致"},
    ]
    _sync_oa_results(wo, db, form_values)
    assert wo.conclusion == "已处理完成"
    assert wo.backfill_reason == "组件连接松动导致"
    assert wo.backfill_status == "filled"
    assert wo.backfilled_at is not None
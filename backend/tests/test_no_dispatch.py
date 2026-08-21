"""不发现场关闭测试：软关闭 + 记原因 + AITable 写失败降级（待补偿）

测试直接建工单（唯一 code），绕过预先存在的 `_next_code` 计数型编号 bug，
只验证 close-no-dispatch 端点自身的逻辑。
"""
from datetime import date

import pytest
from fastapi import HTTPException

from app.api.workorders import close_no_dispatch
from app.models import WorkOrder
from app.schemas.workorder import CloseNoDispatchRequest


def _mk_wo(db, n: int, source_code: str = "alert") -> WorkOrder:
    wo = WorkOrder(
        code=f"SELF-NOD-{n}",
        title="异常指标工单",
        action="排查异常",
        source_code=source_code,
        priority="P1",
        status="approving",
        created_date=date.today(),
        project_id=1, person_id=1, approver_id=11,
    )
    db.add(wo)
    db.commit()
    db.refresh(wo)
    return wo


def test_close_no_dispatch_persists_locally(db, monkeypatch):
    """AITable 写失败（权限未授予/未建表）→ 本地软关闭 + 标记待补偿"""
    monkeypatch.setattr("app.services.aitable.write_no_dispatch_record", lambda data: False)
    wo = _mk_wo(db, 1)

    out = close_no_dispatch(
        wo.id,
        CloseNoDispatchRequest(reason="非设备问题，无需现场处置", operator_name="PMO张三"),
        db,
    )
    assert out.status == "closed"
    assert out.closed_without_dispatch is True
    assert out.no_dispatch_reason == "非设备问题，无需现场处置"
    assert out.no_dispatch_synced is False  # 写失败 → 待补偿

    model = db.get(WorkOrder, wo.id)
    assert model.status == "closed"
    assert model.conclusion == "非设备问题，无需现场处置"


def test_close_no_dispatch_writes_aitable_when_ok(db, monkeypatch):
    """AITable 写成功 → no_dispatch_synced=True"""
    captured = {}
    monkeypatch.setattr("app.services.aitable.write_no_dispatch_record",
                        lambda data: captured.update(data) or True)
    wo = _mk_wo(db, 2)

    out = close_no_dispatch(wo.id, CloseNoDispatchRequest(reason="无需派发现场"), db)
    assert out.no_dispatch_synced is True
    assert captured["工单编号"] == wo.code
    assert captured["关闭原因"] == "无需派发现场"
    assert captured["判断来源"] == "pmo_manual"  # Agent 未判 no_action_needed


def test_close_no_dispatch_rejects_non_alert(db, monkeypatch):
    monkeypatch.setattr("app.services.aitable.write_no_dispatch_record", lambda data: True)
    wo = _mk_wo(db, 3, source_code="manual")
    with pytest.raises(HTTPException) as exc:
        close_no_dispatch(wo.id, CloseNoDispatchRequest(reason="x"), db)
    assert exc.value.status_code == 400


def test_close_no_dispatch_requires_reason(db, monkeypatch):
    monkeypatch.setattr("app.services.aitable.write_no_dispatch_record", lambda data: True)
    wo = _mk_wo(db, 4)
    with pytest.raises(HTTPException) as exc:
        close_no_dispatch(wo.id, CloseNoDispatchRequest(reason="   "), db)
    assert exc.value.status_code == 422


def test_close_no_dispatch_blocks_reclose(db, monkeypatch):
    monkeypatch.setattr("app.services.aitable.write_no_dispatch_record", lambda data: True)
    wo = _mk_wo(db, 5)
    close_no_dispatch(wo.id, CloseNoDispatchRequest(reason="第一次关闭"), db)
    with pytest.raises(HTTPException) as exc:
        close_no_dispatch(wo.id, CloseNoDispatchRequest(reason="重复关闭"), db)
    assert exc.value.status_code == 409
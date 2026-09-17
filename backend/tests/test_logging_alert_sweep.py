"""日志 / 告警 / 巡检 单元测试。"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import pytest

from app.core.logging import get_logger, setup_logging


# ── 日志 ──

def test_setup_logging_idempotent():
    """setup_logging 幂等：多次调用不重复挂文件 handler。"""
    setup_logging()
    root = logging.getLogger()
    before = sum(1 for h in root.handlers if getattr(h, "name", None) == "wo_file_log")
    setup_logging()
    setup_logging()
    after = sum(1 for h in root.handlers if getattr(h, "name", None) == "wo_file_log")
    assert after == before
    assert after >= 1


def test_get_logger_returns_logger():
    assert isinstance(get_logger("t.logging_alert_sweep"), logging.Logger)


# ── 告警 ──

from app.services import alert_service


@pytest.fixture
def _reset_alert_state(monkeypatch):
    alert_service._last_sent.clear()
    from app.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "alert_enabled", True)
    monkeypatch.setattr(s, "alert_notify_userid", "u_lee")
    monkeypatch.setattr(s, "dingtalk_fallback_userid", "")
    monkeypatch.setattr(s, "alert_debounce_seconds", 300)


def test_alert_disabled_returns_false(monkeypatch, _reset_alert_state):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "alert_enabled", False)
    assert alert_service.send_alert("x") is False


def test_alert_no_userid_skips(monkeypatch, _reset_alert_state):
    from app.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "alert_notify_userid", "")
    monkeypatch.setattr(s, "dingtalk_fallback_userid", "")
    assert alert_service.send_alert("x") is False


def test_alert_debounce_dedup(monkeypatch, _reset_alert_state):
    from app.services import dingtalk as dt
    calls: list[tuple] = []
    monkeypatch.setattr(dt, "send_work_notification", lambda *a, **k: calls.append(a) or True)
    assert alert_service.send_alert("故障A", key="same") is True
    assert alert_service.send_alert("故障A", key="same") is False  # 防抖窗口内去重
    assert len(calls) == 1


# ── 巡检 ──

from app.services import health_sweep


def test_sweep_detects_missing_oa_fields(db):
    from app.models import WorkOrder
    wo = WorkOrder(
        code="RW-SWEEP-MISSING-1", title="缺字段待派发", source_code="manual",
        created_date=date.today(),
        status="pending", priority="P2",
        person_id=None, approver_id=None, planned_start_date=None, deadline=None,
    )
    db.add(wo)
    db.flush()
    problems = health_sweep._scan_missing_oa_fields(db)
    assert any(p["kind"] == "missing_oa_fields" for p in problems)


def test_sweep_skips_when_all_fields_present(db):
    """补齐现存 pending 的缺字段后巡检应扫不出问题（隔离 seed 里 pending 工单缺 planned_start_date 的干扰）。"""
    from app.models import WorkOrder
    for wo in db.query(WorkOrder).filter(WorkOrder.status == "pending").all():
        if not wo.planned_start_date:
            wo.planned_start_date = date.today()
        if not wo.deadline:
            wo.deadline = date.today()
    db.flush()
    assert health_sweep._scan_missing_oa_fields(db) == []


def test_sweep_detects_sync_stall(monkeypatch):
    from app.services import sync_poller
    stale = datetime.now() - timedelta(hours=3)
    monkeypatch.setattr(sync_poller, "sync_health", lambda: {"anomaly_last_ok": stale, "plan_last_ok": None})
    problems = health_sweep._scan_sync_stall()
    assert any(p["kind"] == "sync_stall" for p in problems)

"""异常指标大类相关的回归：规则配置 API + 生成工单按类别默认责任人 + 每日同步编排冒烟。

（需本地 PG + fastapi，本机跑：cd backend && python -m pytest tests/test_anomaly_flow.py -q）
"""
from app.models import DataPoolItem, User, WorkOrder
from app.services.pool_service import generate_from_pool


# ── 规则配置 API ──────────────────────────────────────

def test_categories_seeded_with_default_person(client_auth):
    r = client_auth.get("/api/config/anomaly-categories")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 8
    assert {c["code"] for c in items} == {
        "power_gen", "curtailment", "dual_rule", "reliability",
        "info_quality", "contract", "cost", "satisfaction",
    }
    for c in items:
        expected = "徐林杰" if c["code"] == "dual_rule" else "金惠良"
        assert (c["extra"] or {}).get("default_person_name") == expected


def test_update_category_default_person_persists(client_auth):
    items = client_auth.get("/api/config/anomaly-categories").json()
    target = next(c for c in items if c["code"] == "power_gen")

    r2 = client_auth.patch(f"/api/config/anomaly-categories/{target['id']}", json={"default_person_name": "王小宁"})
    assert r2.status_code == 200
    assert r2.json()["extra"]["default_person_name"] == "王小宁"

    # 再查一次确认已持久化
    again = next(c for c in client_auth.get("/api/config/anomaly-categories").json() if c["code"] == "power_gen")
    assert again["extra"]["default_person_name"] == "王小宁"


def test_update_unknown_category_404(client_auth):
    r = client_auth.patch("/api/config/anomaly-categories/999999", json={"default_person_name": "X"})
    assert r.status_code == 404


# ── 生成工单按类别默认责任人 ───────────────────────────

def _add_pool_item(db, ref, metric_type, person_name=None, title="测试"):
    item = DataPoolItem(
        pool_type="anomaly", source_system="anomaly", source_ref=ref,
        title=title, project_name=None, person_name=person_name,
        description="测试异常", status="pending", metric_type=metric_type,
    )
    db.add(item)
    db.flush()
    return item


def test_generate_uses_category_default_person(db):
    item = _add_pool_item(db, "t-ref-1", metric_type="power_gen")
    out = generate_from_pool(db, [item.id])
    assert out["generated"] == 1
    wo = db.get(WorkOrder, out["work_order_ids"][0])
    assert db.get(User, wo.person_id).name == "金惠良"
    assert wo.metric_type == "power_gen"


def test_generate_falls_back_to_person_name_when_no_metric(db):
    item = _add_pool_item(db, "t-ref-2", metric_type=None, person_name="王小宁")
    out = generate_from_pool(db, [item.id])
    assert out["generated"] == 1
    wo = db.get(WorkOrder, out["work_order_ids"][0])
    assert db.get(User, wo.person_id).name == "王小宁"
    assert wo.metric_type is None


# ── 每日同步编排冒烟（mock 掉 dws，无真实钉钉/钉盘调用） ──

def test_daily_sync_smoke(monkeypatch):
    import app.services.aitable as aitable
    from app.services.aitable import run_anomaly_daily_sync

    monkeypatch.setattr(aitable, "_get_records", lambda *a, **k: [])
    result = run_anomaly_daily_sync()
    assert result["synced"] == 0
    assert "generated" in result
    assert isinstance(result["errors"], list)


# ── 异常年份过滤：只进 7 月及以后 ──

def test_keep_month_july_onward():
    from app.services.aitable import _keep_month
    assert _keep_month("7月") and _keep_month("8月") and _keep_month("12月")
    assert _keep_month(" 7月 ")
    assert not _keep_month("6月") and not _keep_month("1月")
    assert not _keep_month("")
    assert not _keep_month("25年分析")
    assert not _keep_month("上半年")


def test_daily_sync_gated_before_start_date(monkeypatch):
    import app.services.aitable as aitable
    from app.services.aitable import run_anomaly_daily_sync
    from app.core.config import get_settings
    from datetime import date, timedelta

    s = get_settings()
    monkeypatch.setattr(aitable, "sync_anomaly_to_pool", lambda *a, **k: {"synced": 0, "errors": []})
    # 双细则直导同样 mock 掉：须避免真 dws 拉取并 commit 真实 SXZ 行污染后续用例
    monkeypatch.setattr(aitable, "sync_dual_rule_to_workorders", lambda *a, **k: {"synced": 0, "errors": []})

    # 未到起跑日 → 直接 skip，不触达同步/生成
    monkeypatch.setattr(s, "anomaly_sync_start_date", date.today() + timedelta(days=2))
    r = run_anomaly_daily_sync()
    assert r.get("skipped") is True

    # 已到起跑日 → 正常跑
    monkeypatch.setattr(s, "anomaly_sync_start_date", date.today() - timedelta(days=1))
    r2 = run_anomaly_daily_sync()
    assert r2.get("skipped") is not True
    assert "synced" in r2


# ── 字段映射迁移（2026-09-11 上游改表）：整改人/PMO/原因分类 ──

def test_sync_anomaly_maps_new_fields(monkeypatch):
    """上游改表后：整改人改读 filterUp 字段，PMO/原因分类落 raw_data，person_name 不再是 PMO。"""
    import app.services.aitable as aitable
    from app.services.aitable import sync_anomaly_to_pool
    from app.core.database import SessionLocal

    fake = [{
        "recordId": "rec-new-fields-1",
        "cells": {
            "06h8ukzbt5k6lit2wupf2": {"id": "p1", "name": "协合师宗"},
            "dudwqcjgwobfozvuhgu7l": {"id": "m1", "name": "损失电量-风机故障损失电量超对标值"},
            "6xwktuomtdhlqqd3iqh3q": {"id": "mon8", "name": "8月"},
            "rmnmea3m114npk2s537em": {"id": "r1", "name": "西南区域中心"},
            "v6mn5bqeigdt6xmm4a45b": {"refFieldType": "member", "value": [{"id": "u1", "name": "王小宁"}]},
            "1kgnhr6fqota0ct19aqn6": {"id": "pmo1", "name": "席鹏程"},
            "xyflaonxfsr57nfnt5df4": {"refFieldType": "multipleSelect", "value": [[{"id": "c1", "name": "不可抗力"}]]},
        },
    }]
    monkeypatch.setattr(aitable, "_get_records", lambda *a, **k: fake)

    out = sync_anomaly_to_pool(full=True)
    assert out["synced"] == 1

    s = SessionLocal()
    try:
        item = s.query(DataPoolItem).filter_by(
            source_system="anomaly", source_ref="rec-new-fields-1").first()
        assert item is not None
        assert item.person_name == "王小宁"           # 整改人（filterUp 抽出姓名），不再是 PMO
        assert item.metric_type == "power_gen"         # 损失电量 → 电量大类
        assert item.raw_data["pmo"] == "席鹏程"
        assert item.raw_data["reason_category"] == "不可抗力"
    finally:
        # sync 用自己的 session 提交，不进 fixture 的 savepoint，需手动清理避免污染后续用例
        s.query(DataPoolItem).filter_by(source_system="anomaly", source_ref="rec-new-fields-1").delete()
        s.commit()
        s.close()


# ── 双细则异常直导工单（2026-09-11 上游拆子表） ──

def test_sync_dual_rule_to_workorders(monkeypatch):
    """双细则异常表 → 直接生成工单：责任人=大类默认(徐林杰)、优先级 P0→P1、按 SXZ 编号幂等。"""
    import app.services.aitable as aitable
    from app.services.aitable import sync_dual_rule_to_workorders
    from app.core.database import SessionLocal

    # 预置双细则大类默认责任人「徐林杰」进测试库（真实库里是钉钉同步来的 executor 用户）
    s0 = SessionLocal()
    try:
        if not s0.query(User).filter_by(name="徐林杰").first():
            s0.add(User(name="徐林杰", role="executor", is_active=True))
            s0.commit()
    finally:
        s0.close()

    fake = [{
        "recordId": "rec-dr-1",
        "cells": {
            "n2dmwW8": "SXZ-20260910-01",
            "5o83YsJ": "SXZ-20260910-01 协合四马桥 AVC投运率",
            "GR6wzxe": "协合四马桥",
            "JSvIxyO": "华南区域中心",
            "H6Z7qCc": {"id": "x", "name": "AVC投运率"},
            "OMe1zkx": "0",
            "Jx1SwAb": "100%",
            "CjJ3IAZ": {"id": "r", "name": "red"},
            "MfzDKTp": {"id": "p", "name": "P0"},
            "c9ouglA": {"refFieldType": "user",
                        "value": [[{"name": "王小宁", "uid": "1"}], [{"name": "王小宁", "uid": "1"}]]},
            "MeQwTQU": "原因：xx；措施：yy",
            "jFO4J0Y": "2026-09-10T00:00:00+08:00",
        },
    }]
    monkeypatch.setattr(aitable, "_get_records", lambda *a, **k: fake)

    out = sync_dual_rule_to_workorders(full=True)
    assert out["synced"] == 1

    s = SessionLocal()
    try:
        wo = s.query(WorkOrder).filter_by(client_request_id="sxz-SXZ-20260910-01").first()
        assert wo is not None
        assert wo.metric_type == "dual_rule"
        assert wo.status == "judging"                # 自带回填 → 已回填
        assert wo.alert_phase == "confirming"         # 进入 alert 五阶段①分析确认
        assert wo.source_code == "alert"
        assert wo.priority == "P1"                 # 双细则 P0 → 平台最高 P1
        assert wo.region == "华南"
        assert s.get(User, wo.person_id).name == "徐林杰"   # 责任人=大类默认徐林杰，不是表里王小宁
        assert "填报责任人 王小宁" in (wo.action or "")   # 表里填报责任人降级进摘要，不丢
        assert wo.title == "SXZ-20260910-01 协合四马桥 AVC投运率"

        # 幂等：再同步一次，SXZ 编号已存在 → 跳过
        out2 = sync_dual_rule_to_workorders(full=False)
        assert out2["synced"] == 0
    finally:
        s.query(WorkOrder).filter_by(client_request_id="sxz-SXZ-20260910-01").delete()
        s.query(User).filter_by(name="徐林杰").delete()
        s.commit()
        s.close()

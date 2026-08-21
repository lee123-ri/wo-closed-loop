"""可靠性Agent出参导入测试：泰康师宗 9 张工单 → 草稿工单 + 留空提示 + 批次去重"""
import json
from pathlib import Path

GOLDEN = Path(__file__).resolve().parents[2] / "docs" / "reliability-agent" / "黄金样本-泰康师宗9工单.json"


def _batch():
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return {"project": data["project"], "trigger": data["trigger"], "workorders": data["workorders"]}


def test_import_creates_9_drafts(client, db):
    body = _batch()
    resp = client.post("/api/import/agent-workorders", json=body)
    assert resp.status_code == 200, resp.text
    out = resp.json()

    assert out["total"] == 9
    assert out["created"] == 9
    assert out["skipped_duplicate"] == 0
    assert out["batch_key"] == "泰康师宗|FLE50|2026-04 ~ 2026-05"

    results = out["results"]
    created = [r for r in results if r["status"] == "created"]
    assert len(created) == 9
    for r in created:
        assert r["code"].startswith("RW-")
        assert any("责任人" in u for u in r["unmapped"]), f"{r['code']} 未标责任人留空: {r}"

    from app.models import WorkOrder, AgentImportBatch
    codes = [r["code"] for r in created]
    rows = db.query(WorkOrder).filter(WorkOrder.code.in_(codes)).all()
    assert len(rows) == 9
    for wo in rows:
        assert wo.status == "pending"
        assert wo.source_code == "alert"
        assert wo.priority == "P1"
        assert wo.person_id is None  # 责任人留空待人工补填
        assert wo.project_id is not None

    # 批次记录已落库
    batch = db.query(AgentImportBatch).filter(AgentImportBatch.batch_key == out["batch_key"]).first()
    assert batch is not None
    assert batch.work_order_codes == codes


def test_import_batch_dedup_same_project_indicator(client, db):
    """同一个项目同一个指标：即使工单标题改成别的，也因批次去重整批跳过。"""
    body = _batch()
    client.post("/api/import/agent-workorders", json=body)

    # 改掉所有标题（模拟 Agent 重跑、措辞不同），但项目+指标+周期不变
    for i, wo in enumerate(body["workorders"]):
        wo["workorder_id"] = f"rerun-{i}"
        wo["title"] = f"（重跑）{wo['title']}"

    resp = client.post("/api/import/agent-workorders", json=body)
    out = resp.json()
    assert out["created"] == 0
    assert out["already_imported"] is True
    assert out["skipped_duplicate"] == 9


def test_import_action_merges_target_metric(client, db):
    body = _batch()
    body["workorders"] = body["workorders"][:1]  # 只导 F15 那张
    resp = client.post("/api/import/agent-workorders", json=body)
    out = resp.json()
    assert out["created"] == 1
    from app.models import WorkOrder
    wo = db.query(WorkOrder).filter(WorkOrder.code == out["results"][0]["code"]).first()
    assert "【目标】" in wo.action  # M 目标值已并入行动要求
    assert wo.title.startswith("泰康师宗·3#集电线F15风机")


HTML_FIXTURE = Path(__file__).resolve().parents[2] / "docs" / "reliability-agent" / "样例-泰康师宗复盘HTML.html"


def test_import_html_parses_9_workorders(client, db):
    """荣的复盘 HTML → 解析出 9 张工单 → 生成 9 个草稿。"""
    html = HTML_FIXTURE.read_text(encoding="utf-8")
    resp = client.post("/api/import/agent-html", json={"html": html})
    assert resp.status_code == 200, resp.text
    out = resp.json()

    assert out["parsed_count"] == 9
    assert out["created"] == 9
    assert out["project"] == "泰康师宗"
    assert out["trigger"]["indicator"] == "FLE50"
    assert out["trigger"]["period"] == "4~5月"

    from app.models import WorkOrder
    codes = [r["code"] for r in out["results"] if r["status"] == "created"]
    rows = db.query(WorkOrder).filter(WorkOrder.code.in_(codes)).all()
    assert len(rows) == 9
    for wo in rows:
        assert wo.status == "pending"
        assert wo.source_code == "alert"


def test_import_html_batch_dedup(client, db):
    """同一个 HTML 重复导入 → 批次去重整批跳过。"""
    html = HTML_FIXTURE.read_text(encoding="utf-8")
    client.post("/api/import/agent-html", json={"html": html})
    out = client.post("/api/import/agent-html", json={"html": html}).json()
    assert out["already_imported"] is True
    assert out["created"] == 0
    assert out["skipped_duplicate"] == 9


def test_reset_workorder_to_pending(client, db):
    """重置：已派发工单 → 待派发(未发起)，并清空 OA 单号，便于重新测试。"""
    resp = client.post("/api/work-orders", json={
        "title": "重置流转测试", "reason": "测", "action": "做",
        "project_id": 1, "person_id": 1, "approver_id": 2,
        "source_code": "alert", "priority": "P1", "deadline": "2026-08-30",
    })
    assert resp.status_code in (200, 201), resp.text
    wo_id = resp.json()["id"]

    # 发起审批 → dispatched
    client.post(f"/api/work-orders/{wo_id}/transition", params={"action": "dispatch"})
    # 重置 → pending
    r = client.post(f"/api/work-orders/{wo_id}/transition", params={"action": "reset"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["oa_id"] is None
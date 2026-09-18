"""可靠性Agent出参导入测试（判断流契约）：
9 条措施 → 1 张宿主工单（judging）+ 9 条措施任务草稿 + 留空提示 + 批次去重。

契约来源：app/api/imports.py `_import_agent_batch`（commit 5482e92 判断Agent闭环设计）。
"""
import json
from pathlib import Path

import pytest

from app.models import AgentImportBatch, Project, WorkOrder

GOLDEN = Path(__file__).resolve().parents[2] / "docs" / "reliability-agent" / "黄金样本-泰康师宗9工单.json"
HTML_FIXTURE = Path(__file__).resolve().parents[2] / "docs" / "reliability-agent" / "样例-泰康师宗复盘HTML.html"


def _batch():
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return {"project": data["project"], "trigger": data["trigger"], "workorders": data["workorders"]}


@pytest.fixture
def tk_project(db):
    """黄金样本的项目「泰康师宗」不在种子数据里，测试内自建，保证项目匹配路径被覆盖。"""
    p = Project(code="TKSZ", name="泰康师宗")
    db.add(p)
    db.flush()
    return p


def test_import_creates_host_wo_with_9_tasks(client_auth, db, tk_project):
    """9 条措施 → 1 张宿主工单（judging，带 9 条措施任务），责任人留空待人工补选。"""
    resp = client_auth.post("/api/import/agent-workorders", json=_batch())
    assert resp.status_code == 200, resp.text
    out = resp.json()

    assert out["total"] == 9
    assert out["created"] == 1  # 判断流：1 张宿主工单
    assert out["skipped_duplicate"] == 0
    assert out["batch_key"] == "泰康师宗|FLE50|2026-04 ~ 2026-05"

    r = out["results"][0]
    assert r["status"] == "created"
    assert r["task_count"] == 9
    assert r["code"].startswith("RW-")
    # 黄金样本的措施都带责任人姓名 → 姓名以文本保留在措施任务里（判断时再绑用户），
    # 因此不会有「责任人留空」提示；项目已由 tk_project 夹具匹配
    assert not any("责任人" in u for u in r["unmapped"]), f"责任人姓名已给，不应留空: {r}"
    assert not any("项目" in u for u in r["unmapped"])

    wo = db.query(WorkOrder).filter(WorkOrder.code == r["code"]).first()
    assert wo is not None
    assert wo.status == "judging"
    assert wo.judgment_status == "judging"
    assert wo.source_code == "reliability"
    assert wo.priority == "P1"
    assert wo.project_id == tk_project.id
    assert len(wo.triggered_wo_tasks or []) == 9
    assert any(t.get("person_name") for t in wo.triggered_wo_tasks), "责任人姓名应保留在措施任务中"

    # 批次记录已落库
    batch = db.query(AgentImportBatch).filter(AgentImportBatch.batch_key == out["batch_key"]).first()
    assert batch is not None
    assert batch.work_order_codes == [r["code"]]


def test_import_batch_dedup_same_project_indicator(client_auth, db, tk_project):
    """同一个项目同一个指标：即使工单标题改成别的，也因批次去重整批跳过。"""
    body = _batch()
    first = client_auth.post("/api/import/agent-workorders", json=body)
    assert first.status_code == 200, first.text

    # 改掉所有标题（模拟 Agent 重跑、措辞不同），但项目+指标+周期不变
    for i, wo in enumerate(body["workorders"]):
        wo["workorder_id"] = f"rerun-{i}"
        wo["title"] = f"（重跑）{wo['title']}"

    resp = client_auth.post("/api/import/agent-workorders", json=body)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["already_imported"] is True
    assert out["created"] == 0
    assert out["skipped_duplicate"] == 9


def test_import_action_merges_target_metric(client_auth, db, tk_project):
    """target_metric 并入措施任务的行动要求（【目标】）；宿主标题为指标异常处置。"""
    body = _batch()
    body["workorders"] = body["workorders"][:1]  # 只导 F15 那张
    body["trigger"]["period"] = "2026-06"        # 独立批次，避免与其他用例的批次键耦合
    resp = client_auth.post("/api/import/agent-workorders", json=body)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["created"] == 1

    wo = db.query(WorkOrder).filter(WorkOrder.code == out["results"][0]["code"]).first()
    assert wo.title.startswith("【指标异常处置】")
    assert len(wo.triggered_wo_tasks) == 1
    assert "【目标】" in wo.triggered_wo_tasks[0]["action"]  # M 目标值已并入措施行动要求


def test_import_html_parses_9_workorders(client_auth, db, tk_project):
    """复盘 HTML → 解析出 9 条措施 → 1 张宿主工单 + 9 条措施任务。"""
    html = HTML_FIXTURE.read_text(encoding="utf-8")
    resp = client_auth.post("/api/import/agent-html", json={"html": html})
    assert resp.status_code == 200, resp.text
    out = resp.json()

    assert out["parsed_count"] == 9
    assert out["created"] == 1
    assert out["project"] == "泰康师宗"
    assert out["trigger"]["indicator"] == "FLE50"
    assert out["results"][0]["task_count"] == 9

    wo = db.query(WorkOrder).filter(WorkOrder.code == out["results"][0]["code"]).first()
    assert wo.status == "judging"
    assert wo.source_code == "reliability"


def test_import_html_batch_dedup(client_auth, db, tk_project):
    """同一个 HTML 重复导入 → 批次去重整批跳过。"""
    html = HTML_FIXTURE.read_text(encoding="utf-8")
    first = client_auth.post("/api/import/agent-html", json={"html": html})
    assert first.status_code == 200, first.text
    out = client_auth.post("/api/import/agent-html", json={"html": html}).json()
    assert out["already_imported"] is True
    assert out["created"] == 0
    assert out["skipped_duplicate"] == 9


def test_reset_workorder_to_pending(client_auth, db):
    """重置：已派发工单 → 待派发(未发起)，并清空 OA 单号，便于重新测试。"""
    resp = client_auth.post("/api/work-orders", json={
        "title": "重置流转测试", "reason": "测", "action": "做",
        "project_id": 1, "person_id": 1, "approver_id": 2, "type_id": 1,
        "source_code": "meeting", "priority": "P1",
        "deadline": "2026-08-30", "planned_start_date": "2026-08-25",
    })
    assert resp.status_code in (200, 201), resp.text
    wo_id = resp.json()["id"]

    # 发起审批 → dispatched（必填字段已齐）
    d = client_auth.post(f"/api/work-orders/{wo_id}/transition", params={"action": "dispatch"})
    assert d.status_code == 200, d.text
    # 重置 → pending
    r = client_auth.post(f"/api/work-orders/{wo_id}/transition", params={"action": "reset"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["oa_id"] is None

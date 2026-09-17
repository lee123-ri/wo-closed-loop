"""项目筛选下拉回归：只列列表里真实出现过的项目，不列无工单的「死项目」。

背景（2026-09-15）：主列表「项目」筛选栏原先取自 /config/projects/all（全部项目表），
导致下拉里出现「有项目但没有任何工单」的无效选项；现已改为由列表接口按当前
列表范围（区域 + 行级范围 + 是否闭环）去重返回 `project_options`。
"""

from app.models import Project, WorkOrder


def _active_project_ids(db, *, closed_only: bool = False, region: str | None = None):
    """与后端 _project_options 同口径：非闭环(或闭环)工单去重后的项目 id 集合。"""
    q = (
        db.query(WorkOrder.project_id)
        .join(Project, WorkOrder.project_id == Project.id)
        .filter(WorkOrder.project_id.isnot(None))
    )
    if closed_only:
        q = q.filter(WorkOrder.status == "closed")
    else:
        q = q.filter(WorkOrder.status != "closed")
    if region:
        q = q.filter(WorkOrder.region == region)
    return {pid for (pid,) in q.distinct().all()}


def test_project_options_only_projects_in_list(db, client_auth):
    """project_options 应恰好等于主列表里出现的项目集合，且与分页无关。"""
    expect = _active_project_ids(db)
    # page_size=1 时 options 仍应是全量——证明它不随当前页收缩
    r = client_auth.get("/api/work-orders", params={"page_size": 1})
    assert r.status_code == 200
    data = r.json()
    assert "project_options" in data
    opt_ids = {o["id"] for o in data["project_options"]}
    assert opt_ids == expect, "项目下拉应恰好等于主列表里真实出现的项目集合"


def test_project_options_respect_region(db, client_auth):
    """选了区域后，project_options 只含该区域工单里出现过的项目。"""
    region = "华北"
    expect = _active_project_ids(db, region=region)
    r = client_auth.get("/api/work-orders", params={"page_size": 1, "region": region})
    assert r.status_code == 200
    opt_ids = {o["id"] for o in r.json().get("project_options", [])}
    assert opt_ids == expect, "区域筛选下项目下拉应只含该区域工单里出现的项目"


def test_closed_list_project_options(db, client_auth):
    """闭环记录列表的 project_options 应恰好等于已闭环工单里出现的项目集合。"""
    expect = _active_project_ids(db, closed_only=True)
    r = client_auth.get("/api/work-orders/closed/list", params={"page_size": 1})
    assert r.status_code == 200
    data = r.json()
    assert "project_options" in data
    opt_ids = {o["id"] for o in data["project_options"]}
    assert opt_ids == expect
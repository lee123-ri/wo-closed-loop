"""回归测试（2026-09-03）：项目编码规则 / 用户搜索 / 操作日志接通。

对应三个现场问题：
1. 项目管理页编码杂乱（名称截断码 vs PRJ-xxxx）→ 规则统一为 PRJ-#### 系统自动分配、不可改；
2. 用户管理 1500 人无搜索 → /auth/users 支持 q 参数（姓名/钉钉ID 模糊）；
3. 操作日志页长期为空 → 读接口字段修正 + 关键操作写入审计日志。
"""
import re

from app.models import Project, User

PRJ_RE = re.compile(r"^PRJ-\d{4,}$")


# ── 1. 项目编码规则 ─────────────────────────────────────

def test_create_project_auto_assigns_sequential_code(client_auth):
    """新增项目不传 code，系统自动分配 PRJ-#### 且连号递增。"""
    c1 = client_auth.post("/api/config/projects", json={"name": "回归测试电场甲"}).json()["code"]
    c2 = client_auth.post("/api/config/projects", json={"name": "回归测试电场乙"}).json()["code"]
    assert PRJ_RE.match(c1), c1
    assert PRJ_RE.match(c2), c2
    assert int(c2[4:]) == int(c1[4:]) + 1


def test_create_project_ignores_client_supplied_code(client_auth):
    """客户端塞 code 一律忽略，仍走自动分配（防绕过规则）。"""
    r = client_auth.post("/api/config/projects", json={"name": "回归测试电场丙", "code": "HACK-1"})
    assert r.status_code == 201, r.text
    assert PRJ_RE.match(r.json()["code"])


def test_project_code_immutable_on_edit(client_auth, db):
    """编辑只能改名称/类型/区域，编码不可变。"""
    body = client_auth.post("/api/config/projects", json={"name": "回归测试电场丁"}).json()
    client_auth.patch(f"/api/config/projects/{body['id']}",
                      json={"name": "回归测试电场丁改", "code": "PRJ-9999"})
    assert db.get(Project, body["id"]).code == body["code"]


def test_next_project_code_continues_from_max(db):
    """编号从库内最大 PRJ 序号 +1，不回收、不与存量撞。"""
    from app.services.project_codes import next_project_code
    db.add(Project(code="PRJ-0042", name="编号回归"))
    db.commit()
    assert next_project_code(db) == "PRJ-0043"


def test_plan_code_normalization_only_touches_bad_codes():
    """历史杂码归一计划：合规码不动，杂码按 id 顺序续编。"""
    from app.services.project_codes import plan_code_normalization
    pairs = [(1, "PRJ-0001"), (2, "三一东丰"), (3, "三一平台村、-1"), (4, "PRJ-0002")]
    plan = plan_code_normalization(pairs)
    assert set(plan) == {2, 3}
    assert list(plan.values()) == ["PRJ-0003", "PRJ-0004"]


# ── 2. 用户搜索 ─────────────────────────────────────────

def test_user_search_filters_by_name(client_auth, db):
    """q 参数按姓名模糊过滤，total 同步为过滤后总数；不传 q 返回全量。"""
    db.add(User(name="回归搜索张三", role="executor", is_active=True))
    db.commit()
    body = client_auth.get("/api/auth/users", params={"q": "回归搜索"}).json()
    assert body["total"] == 1, body
    assert body["items"][0]["name"] == "回归搜索张三"
    assert client_auth.get("/api/auth/users").json()["total"] > 1


# ── 3. 操作日志 ─────────────────────────────────────────

def _hits(logs, target, target_id, action):
    return [l for l in logs["items"]
            if l["target"] == target and l["target_id"] == target_id and l["action"] == action]


def test_audit_written_on_project_create(client_auth):
    """新增项目写入审计日志，operator 为可读人名。"""
    pid = client_auth.post("/api/config/projects", json={"name": "审计回归电场"}).json()["id"]
    logs = client_auth.get("/api/config/audit-logs").json()
    hit = _hits(logs, "project", pid, "create")
    assert hit, logs["items"][:5]
    assert hit[0]["operator"], "operator 应为操作人姓名而非空"


def test_audit_written_on_role_change(client_auth, db):
    """改角色写入审计日志。"""
    u = db.query(User).filter(User.role == "executor").first()
    client_auth.patch(f"/api/auth/users/{u.id}/role", json={"role": "approver"})
    logs = client_auth.get("/api/config/audit-logs").json()
    assert _hits(logs, "user", u.id, "update_role")


def test_audit_written_on_workorder_lifecycle(client_auth):
    """工单创建/流转写入审计日志。"""
    wo = client_auth.post("/api/work-orders", json={
        "title": "审计回归工单", "action": "排查", "reason": "审计回归",
        "source_code": "meeting", "priority": "P2", "project_id": 1, "person_id": 1,
        "approver_id": 11, "type_id": 1, "planned_start_date": "2026-09-03",
    }).json()
    client_auth.post(f"/api/work-orders/{wo['id']}/transition", params={"action": "reset"})
    logs = client_auth.get("/api/config/audit-logs").json()
    assert _hits(logs, "work_order", wo["id"], "create")
    assert _hits(logs, "work_order", wo["id"], "transition")

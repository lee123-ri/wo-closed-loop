"""表格模板导入（POST /api/import/table）回归：项目名解析 + 未匹配拦截。

历史 bug：模板「项目」列按 Project.name 精确匹配，后缀漂移（如「瓜州二期风电场2025」）
导致 project_id 落空、列表「无项目名」，且静默不报。修复后按 clean_project_name 规范匹配
（可容纳尾部字母代号/年份后缀）+ 编码兜底；项目必填，未匹配显式报错并跳过该行。
"""
import io

from app.models import Project, User, WorkOrder

HEADERS = ["标题", "项目", "责任人", "截止日期", "类型", "描述", "行动要求"]


def _csv(headers, rows):
    lines = [",".join(headers)] + [",".join(r) for r in rows]
    return io.BytesIO("\n".join(lines).encode("utf-8-sig"))


def _as_import_owner(db):
    """将种子管理员临时绑定为历史导入唯一授权人。"""
    from app.api.auth import settings
    admin = db.query(User).filter_by(role="admin").first()
    admin.dingtalk_id = "owner-user-id"
    db.commit()
    settings.bulk_import_owner_dingtalk_id = "owner-user-id"


def _post(client_auth, db, rows):
    _as_import_owner(db)
    f = _csv(HEADERS, rows)
    return client_auth.post("/api/import/table", files={"file": ("t.csv", f, "text/csv")})


def _last_wo(db):
    return db.query(WorkOrder).order_by(WorkOrder.id.desc()).first()


def test_table_import_matches_suffixed_project_name(client_auth, db):
    """项目列带年份后缀也能匹配到规范名（历史 bug：精确匹配失败 → 无项目名）。"""
    p = db.query(Project).filter(Project.name == "瓜州二期风电场").first()
    assert p is not None
    r = _post(client_auth, db, [["更换#1风机齿轮箱油封", "瓜州二期风电场2025", "高志强",
                             "2026-09-20", "检修工单", "渗油", "更换"]])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1, body
    assert _last_wo(db).project_id == p.id


def test_table_import_matches_project_by_code(client_auth, db):
    """项目列填 PRJ-xxxx 编码也能解析。"""
    p = db.query(Project).filter(Project.name == "通辽永兴风电场").first()
    assert p is not None and p.code
    r = _post(client_auth, db, [["变桨排查", p.code, "王小宁", "2026-09-20", "检修工单", "异常", "排查"]])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1, body
    assert _last_wo(db).project_id == p.id


def test_table_import_unknown_project_skipped(client_auth, db):
    """项目名解析不到 → 显式报错并跳过该行（不再静默落空）。"""
    r = _post(client_auth, db, [["某任务", "不存在的项目XYZ", "", "2026-09-20", "", "", ""]])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 0, body
    assert body["errors"] and any("未匹配" in e for e in body["errors"])


def test_table_import_missing_project_skipped(client_auth, db):
    """项目列为空 → 显式报错并跳过（与手动建单「项目必填」口径一致）。"""
    r = _post(client_auth, db, [["某任务", "", "", "2026-09-20", "", "", ""]])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 0, body
    assert body["errors"] and any("缺少项目" in e for e in body["errors"])


# ── 预览/确认录入（POST /api/import/table/preview + /confirm）─────────────────

def _preview(client_auth, db, rows):
    _as_import_owner(db)
    f = _csv(HEADERS, rows)
    return client_auth.post("/api/import/table/preview", files={"file": ("t.csv", f, "text/csv")})


def _confirm(client_auth, db, raw_rows):
    _as_import_owner(db)
    return client_auth.post("/api/import/table/confirm", json={"rows": raw_rows})


def test_table_preview_does_not_persist(client_auth, db):
    """preview 只解析不落库；ok/err 口径与 _import_rows 一致。"""
    before = db.query(WorkOrder).count()
    r = _preview(client_auth, db, [
        ["更换#1风机齿轮箱油封", "瓜州二期风电场", "高志强", "2026-09-20", "检修工单", "渗油", "更换"],
        ["某任务", "不存在的项目XYZ", "", "2026-09-20", "", "", ""],
    ])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2, body
    assert body["ok_count"] == 1, body
    assert body["err_count"] == 1, body
    ok_rows = [x for x in body["rows"] if x["ok"]]
    bad_rows = [x for x in body["rows"] if not x["ok"]]
    assert len(ok_rows) == 1 and ok_rows[0]["project_label"]
    assert len(bad_rows) == 1 and "未匹配" in bad_rows[0]["error"]
    # 未落库
    assert db.query(WorkOrder).count() == before


def test_table_confirm_persists_selected_rows(client_auth, db):
    """confirm 只落库勾选的行（raw 原样回传，复用 _import_rows）。"""
    before = db.query(WorkOrder).count()
    pv = _preview(client_auth, db, [
        ["更换#1风机齿轮箱油封", "瓜州二期风电场", "高志强", "2026-09-20", "检修工单", "渗油", "更换"],
        ["变桨排查", "通辽永兴风电场", "王小宁", "2026-09-20", "检修工单", "异常", "排查"],
    ])
    ok_rows = [x for x in pv.json()["rows"] if x["ok"]]
    assert len(ok_rows) == 2
    r = _confirm(client_auth, db, [x["raw"] for x in ok_rows])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2, body
    assert db.query(WorkOrder).count() == before + 2


def test_table_import_is_admin_only(client, db):
    """正式批量导入口只允许管理员；普通已登录人员也不能绕过前端。"""
    from app.core.security import create_access_token
    executor = db.query(User).filter_by(role="executor").first()
    token = create_access_token(str(executor.id), extra={"name": executor.name, "role": executor.role})
    r = client.post("/api/import/table/confirm", json={"rows": []}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403

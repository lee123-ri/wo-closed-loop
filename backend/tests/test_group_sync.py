"""钉钉群成员同步测试"""
from app.api.dingtalk import sync_group_members
from app.models import Project, User, PersonProjectMap


def test_sync_creates_mapping(db):
    """同步群成员后，项目下应有对应人员映射"""
    before = db.query(PersonProjectMap).filter_by(project_id=1).count()
    result = sync_group_members(project_id=1, group_id="cid-test-sync", db=db)
    assert result["synced"] >= 1
    after = db.query(PersonProjectMap).filter_by(project_id=1).count()
    assert after >= before  # 合并不删
    # 群 ID 应写入项目
    proj = db.get(Project, 1)
    assert proj.dingtalk_group_id == "cid-test-sync"


def test_sync_idempotent(db):
    """重复同步不重复创建映射"""
    sync_group_members(project_id=1, group_id="cid-idem", db=db)
    n1 = db.query(PersonProjectMap).filter_by(project_id=1).count()
    sync_group_members(project_id=1, group_id="cid-idem", db=db)
    n2 = db.query(PersonProjectMap).filter_by(project_id=1).count()
    assert n2 == n1  # 幂等


def test_sync_unknown_project(db):
    """项目不存在应 404"""
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        sync_group_members(project_id=99999, group_id="x", db=db)
    assert exc.value.status_code == 404


def test_sync_no_group_id(db):
    """项目无群 ID 且未传 group_id 应 400"""
    import pytest
    from fastapi import HTTPException
    proj = db.get(Project, 2)
    proj.dingtalk_group_id = None
    db.commit()
    with pytest.raises(HTTPException) as exc:
        sync_group_members(project_id=2, group_id=None, db=db)
    assert exc.value.status_code == 400

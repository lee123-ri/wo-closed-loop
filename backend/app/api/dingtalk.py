"""钉钉回调接口：

1. OA 审批状态回调：钉钉审批通过/驳回后回调本接口，更新工单状态
2. 事件订阅：钉钉开放平台事件回调（@机器人消息等）

回调验签用 dingtalk callback 的 aes 解密（此处简化，生产需配 aes_key）。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Project, User, PersonProjectMap, WorkOrder, StatusLog

router = APIRouter(prefix="/dingtalk", tags=["dingtalk"])
settings = get_settings()


@router.post("/sync-group-members")
def sync_group_members(project_id: int, group_id: str | None = None, db: Session = Depends(get_db)):
    """从钉钉群同步成员到项目的人员映射。

    1. 取项目关联的 dingtalk_group_id（或用传入的 group_id）
    2. 调钉钉获取群成员
    3. 每个成员：匹配/创建 User，写 PersonProjectMap（合并，不删旧的）
    """
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(404, "项目不存在")
    cid = group_id or proj.dingtalk_group_id
    if not cid:
        raise HTTPException(400, "未提供群 ID，且项目未关联钉钉群")
    # 记录群 ID 到项目
    if proj.dingtalk_group_id != cid:
        proj.dingtalk_group_id = cid
        db.commit()

    from app.services import dingtalk
    members = dingtalk.get_group_members(cid)
    if not members:
        raise HTTPException(502, "未能获取群成员（检查群ID或钉钉凭证）")

    synced = 0
    created = 0
    existing_map = {m.user_id: m for m in db.query(PersonProjectMap).filter_by(project_id=project_id).all()}
    for mem in members:
        # 匹配/创建用户
        u = None
        if mem.get("dingtalk_id"):
            u = db.query(User).filter(User.dingtalk_id == mem["dingtalk_id"]).first()
        if not u and mem.get("name"):
            u = db.query(User).filter(User.name == mem["name"]).first()
            if u and mem.get("dingtalk_id"):
                u.dingtalk_id = mem["dingtalk_id"]
        if not u:
            u = User(name=mem.get("name") or "未知", dingtalk_id=mem.get("dingtalk_id"),
                     role="executor", is_active=True)
            db.add(u); db.flush()
            created += 1
        # 写映射（幂等）
        if u.id not in existing_map:
            m = PersonProjectMap(project_id=project_id, user_id=u.id, is_default=False)
            db.add(m)
            existing_map[u.id] = m
        synced += 1
    db.commit()
    return {"project_id": project_id, "group_id": cid, "synced": synced, "created": created,
            "members": [{"name": m["name"], "dingtalk_id": m["dingtalk_id"]} for m in members]}


@router.post("/oa/callback")
async def oa_callback(request: Request, db: Session = Depends(get_db)):
    """钉钉 OA 审批节点流转回调（多节点审批流）。

    审批流设计为 3 节点：
      节点1 审批人（确认派发）  → agree → 工单 dispatched
      节点2 执行人（执行+附件） → agree → 工单 verifying（待审批人确认）
      节点3 审批人（确认执行）  → agree → 工单 closed
    任意节点 refuse → 工单 rejected

    钉钉回调 payload 含 processInstanceId / result / activityName(节点名) / formComponentValues。
    回调类型：钉钉「审批任务流转」事件，每个节点完成都回调。
    """
    body = await request.json()
    # 兼容：钉钉回调可能包一层 eventType
    if "processInstanceId" not in body:
        body = body.get("data", body)

    # 从表单字段找工单编号
    code = None
    for fv in body.get("formComponentValues", []):
        if fv.get("name") == "工单编号":
            code = fv.get("value")
            break
    if not code:
        return {"success": False, "msg": "未找到工单编号"}

    wo = db.query(WorkOrder).filter(WorkOrder.code == code).first()
    if not wo:
        return {"success": False, "msg": "工单不存在"}

    result = body.get("result", "agree")
    activity = body.get("activityName", "")  # 当前节点名
    wo.oa_id = body.get("processInstanceId", wo.oa_id)

    if result == "refuse":
        # 任意节点驳回 → rejected
        db.add(StatusLog(work_order_id=wo.id, from_status=wo.status, to_status="rejected",
                         note=f"钉钉OA节点「{activity}」驳回"))
        wo.status = "rejected"
        db.commit()
        return {"success": True, "status": "rejected"}

    # agree：3 节点对应 3 次推进（审批人→执行人→审批人确认）
    next_map = {
        "approving": ("executing", "节点1审批通过·开始执行"),
        "executing": ("verifying", "节点2执行人提交·待确认"),
        "verifying": ("closed", "节点3审批人确认·闭环"),
    }
    if wo.status in next_map:
        to, note = next_map[wo.status]
        db.add(StatusLog(work_order_id=wo.id, from_status=wo.status, to_status=to,
                         note=f"钉钉OA「{activity}」{note}"))
        wo.status = to
        from datetime import date as _date
        if to == "closed":
            wo.completed_date = _date.today()
            if not wo.conclusion:
                wo.conclusion = "钉钉OA审批通过·闭环"
            # 闭环时拉取执行人上传的附件
            _sync_attachments(wo, db)
    db.commit()
    return {"success": True, "status": wo.status}


def _sync_attachments(wo: WorkOrder, db: Session):
    """从钉钉审批单表单拉取执行附件，转存 attachments 表。无凭证时跳过。"""
    try:
        from app.services import dingtalk
        from app.models import Attachment
        info = dingtalk.query_oa_approval(wo.oa_id)
        if not info:
            return
        for fv in (info.get("formComponentValues") or []):
            if fv.get("name") in ("执行附件", "附件") and fv.get("value"):
                # value 可能是附件 URL 或 JSON 数组
                files = fv["value"] if isinstance(fv["value"], list) else [{"url": fv["value"], "name": "执行附件"}]
                for f in files:
                    oss_key = f.get("url", "")  # 真实场景：下载转存 OSS 后替换为 key
                    exists = db.query(Attachment).filter_by(work_order_id=wo.id, oss_key=oss_key).first()
                    if not exists:
                        db.add(Attachment(
                            work_order_id=wo.id, filename=f.get("name", "执行附件"),
                            oss_key=oss_key, size=0,
                        ))
    except Exception as e:
        print(f"[dingtalk] 附件同步跳过: {e}")


@router.get("/status")
def dingtalk_status():
    """凭证配置状态（不返回真实值，只返回是否已配置）"""
    return {
        "app_key": bool(settings.dingtalk_app_key),
        "app_secret": bool(settings.dingtalk_app_secret),
        "agent": bool(settings.dingtalk_agent_id),
        "oa_template": bool(settings.dingtalk_oa_template_id),
        "corp": bool(settings.dingtalk_corp_id),
    }


@router.get("/oa/check")
def oa_status_check(code: str, db: Session = Depends(get_db)):
    """主动查询某工单的 OA 审批状态（轮询兜底，回调失败时用）"""
    wo = db.query(WorkOrder).filter(WorkOrder.code == code).first()
    if not wo or not wo.oa_id:
        return {"status": "no_oa"}
    try:
        from app.services import dingtalk
        info = dingtalk.query_oa_approval(wo.oa_id)
        if info:
            return {"status": info.get("status"), "raw": info}
    except Exception as e:
        return {"status": "error", "msg": str(e)}
    return {"status": "unknown"}

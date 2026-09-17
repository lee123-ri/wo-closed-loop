"""钉钉回调接口：

1. OA 审批状态回调：钉钉审批通过/驳回后回调本接口，更新工单状态
2. 事件订阅：钉钉开放平台事件回调（@机器人消息等）
3. GET /oa/callback：钉钉 URL 校验（echostr 解密）
"""
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Project, User, PersonProjectMap, WorkOrder, StatusLog

router = APIRouter(prefix="/dingtalk", tags=["dingtalk"])
# 公开路由：钉钉服务端推送的回调端点（无用户 JWT，靠验签保护），不挂鉴权
public_router = APIRouter(prefix="/dingtalk", tags=["dingtalk"])
settings = get_settings()
logger = logging.getLogger(__name__)


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


@public_router.get("/oa/callback")
async def oa_callback_verify(
    signature: str = Query(..., alias="signature"),
    timestamp: str = Query(..., alias="timestamp"),
    nonce: str = Query(..., alias="nonce"),
    echostr: str = Query(..., alias="echostr"),
):
    """钉钉回调 URL 校验（GET）。

    钉钉在注册回调 URL 时发送 GET 请求验证有效性：
    校验签名 → 用 AES Key 解密 echostr → 原样返回解密后的明文。
    注意：必须返回纯文本明文，不能再加密；否则钉钉校验不通过。
    """
    from fastapi.responses import PlainTextResponse
    if not settings.dingtalk_callback_token or not settings.dingtalk_callback_aes_key:
        logger.warning("回调 URL 校验跳过：未配置 dingtalk_callback_token/aes_key")
        return PlainTextResponse(echostr)  # 未配置时原样返回（仅开发环境，钉钉会拒绝）
    from app.services.dingtalk_callback_crypto import DingCallbackCrypto
    crypto = DingCallbackCrypto(
        settings.dingtalk_callback_token,
        settings.dingtalk_callback_aes_key,
        settings.dingtalk_corp_id,
    )
    # 验签
    expected = crypto.get_signature(timestamp, nonce, echostr)
    if signature != expected:
        raise HTTPException(400, "签名校验失败")
    # 解密 echostr，返回明文
    decrypted = crypto.decrypt_msg(echostr)
    return PlainTextResponse(decrypted)


@public_router.post("/oa/callback")
async def oa_callback(
    request: Request,
    db: Session = Depends(get_db),
    signature: str = Query("", alias="signature"),
    timestamp: str = Query("", alias="timestamp"),
    nonce: str = Query("", alias="nonce"),
):
    """钉钉 OA 审批节点流转回调（多节点审批流）。

    审批流设计为 3 节点：
      节点1 审批人（确认派发）  → agree → 工单 dispatched
      节点2 执行人（执行+附件） → agree → 工单 verifying（待审批人确认）
      节点3 审批人（确认执行）  → agree → 工单 closed
    任意节点 refuse → 工单 rejected

    钉钉回调 payload 含 processInstanceId / result / activityName(节点名) / formComponentValues。
    回调类型：钉钉「审批任务流转」事件，每个节点完成都回调。
    """
    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8")

    # 解密（若已配置事件订阅加解密）。crypto 同时用于结尾的加密成功回执。
    crypto = None
    if settings.dingtalk_callback_token and settings.dingtalk_callback_aes_key:
        from app.services.dingtalk_callback_crypto import DingCallbackCrypto
        crypto = DingCallbackCrypto(
            settings.dingtalk_callback_token,
            settings.dingtalk_callback_aes_key,
            settings.dingtalk_corp_id,
        )
        try:
            encrypted_body = json.loads(raw_text)
            encrypt = encrypted_body.get("encrypt", "")
            if encrypt:
                if not signature:
                    raise HTTPException(400, "缺少签名参数")
                expected = crypto.get_signature(timestamp, nonce, encrypt)
                if signature != expected:
                    raise HTTPException(400, "签名校验失败")
                body = json.loads(crypto.decrypt_msg(encrypt))
            else:
                body = encrypted_body
        except Exception as e:
            logger.error(f"回调解密失败: {e}")
            raise HTTPException(400, f"回调解密失败: {e}")
    else:
        body = json.loads(raw_text)

    def respond(result: dict):
        """钉钉事件订阅要求返回加密的 "success" 回执，否则会重推。"""
        if crypto:
            return crypto.get_encrypted_map("success")
        return result

    from app.services.oa_event import apply_oa_event
    result = apply_oa_event(body, db, event_type=body.get("EventType", ""))
    return respond(result)


@router.get("/status")
def dingtalk_status():
    """凭证配置状态（不返回真实值，只返回是否已配置）"""
    return {
        "app_key": bool(settings.dingtalk_app_key),
        "app_secret": bool(settings.dingtalk_app_secret),
        "agent": bool(settings.dingtalk_agent_id),
        "oa_template": bool(settings.dingtalk_oa_template_id),
        "corp": bool(settings.dingtalk_corp_id),
        "callback_token": bool(settings.dingtalk_callback_token),
        "callback_aes_key": bool(settings.dingtalk_callback_aes_key),
    }


@router.post("/oa/sync/{wo_id}")
def oa_sync_work_order(wo_id: int, db: Session = Depends(get_db)):
    """手动按工单拉取钉钉审批最新状态/内容/附件（轮询兜底，回调不稳定时用）。"""
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "工单不存在")
    if not wo.oa_id:
        return {"success": False, "msg": "该工单未发起 OA 审批（无 oa_id）"}
    from app.services.oa_event import apply_oa_event
    return apply_oa_event({"processInstanceId": wo.oa_id}, db, event_type="手动同步")


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
            return {"status": info.get("status"), "result": info.get("result"), "raw": info}
    except Exception as e:
        return {"status": "error", "msg": str(e)}
    return {"status": "unknown"}

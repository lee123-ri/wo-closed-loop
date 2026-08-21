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


@router.get("/oa/callback")
async def oa_callback_verify(
    signature: str = Query(..., alias="signature"),
    timestamp: str = Query(..., alias="timestamp"),
    nonce: str = Query(..., alias="nonce"),
    echostr: str = Query(..., alias="echostr"),
):
    """钉钉回调 URL 校验（GET）。

    钉钉在注册回调 URL 时发送 GET 请求验证有效性。
    解密 echostr 后重新加密返回，钉钉比对一致即校验通过。
    """
    if not settings.dingtalk_callback_token or not settings.dingtalk_callback_aes_key:
        logger.warning("回调 URL 校验跳过：未配置 dingtalk_callback_token/aes_key")
        return echostr  # 未配置时原样返回（仅开发环境，钉钉会拒绝）
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
    # 解密 echostr，再加密返回
    decrypted = crypto.decrypt_msg(echostr)
    encrypted_map = crypto.get_encrypted_map(decrypted)
    return encrypted_map


@router.post("/oa/callback")
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
    验收节点(accept) refuse → 工单 returned（退回责任人重填）；其余节点 refuse → rejected

    钉钉回调 payload 含 processInstanceId / result / activityName(节点名) / formComponentValues。
    回调类型：钉钉「审批任务流转」事件，每个节点完成都回调。
    """
    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8")

    # 如果配置了验签，先解密
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
                decrypted = crypto.decrypt_msg(encrypt)
                body = json.loads(decrypted)
            else:
                body = encrypted_body
        except Exception as e:
            logger.error(f"回调解密失败: {e}")
            raise HTTPException(400, f"回调解密失败: {e}")
    else:
        body = json.loads(raw_text)

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
        # 验收节点(accept)驳回 → 退回重填(returned)；其余节点驳回 → rejected
        stage = _current_stage(wo)
        if stage == "accept":
            to_status, note = "returned", f"验收节点「{activity}」驳回·退回责任人重填"
        else:
            to_status, note = "rejected", f"钉钉OA节点「{activity}」驳回"
        db.add(StatusLog(work_order_id=wo.id, from_status=wo.status, to_status=to_status, note=note))
        wo.status = to_status
        db.commit()
        return {"success": True, "status": to_status}

    # agree：按 oa_progress 逐节点推进（角色审批链 → 具体人），再算目标状态
    to = _advance_oa_progress(wo)
    if to and to != wo.status:
        db.add(StatusLog(work_order_id=wo.id, from_status=wo.status, to_status=to,
                         note=f"钉钉OA「{activity}」{_status_note(to)}"))
        wo.status = to
        from datetime import date as _date
        if to == "closed":
            wo.completed_date = _date.today()
            # 回写钉钉表单「执行结论/执行附件」到工单（表单改动同步）
            _sync_oa_results(wo, db, body.get("formComponentValues") or [])
            if not wo.conclusion:
                wo.conclusion = "钉钉OA审批通过·闭环"
    db.commit()
    return {"success": True, "status": wo.status}


def _current_stage(wo: WorkOrder) -> str | None:
    """当前所在审批阶段：oa_progress 中首个未 approved 节点的 stage。"""
    if not wo.oa_progress:
        return None
    for p in wo.oa_progress:
        if not p.get("approved"):
            return p.get("stage")
    return None


def _advance_oa_progress(wo: WorkOrder) -> str | None:
    """同意一步：标记首个未通过节点为已批，返回目标状态。

    有 oa_progress 时按角色审批链推进；无（旧工单/未发起）则回落到朴素 next_map。
    深拷贝列表再回写，触发 SQLAlchemy JSONB 变更检测。
    """
    if wo.oa_progress:
        progress = [dict(p) for p in wo.oa_progress]
        for p in progress:
            if not p.get("approved"):
                p["approved"] = True
                break
        wo.oa_progress = progress
        return _compute_status(progress)
    return {
        "approving": "executing",
        "executing": "verifying",
        "verifying": "closed",
    }.get(wo.status)


def _compute_status(progress: list[dict]) -> str:
    """按审批进度算状态：approve 全过→dispatched；execute 过→verifying；
    accept 过（或 P3 无 accept 阶段）→closed；否则 approving。"""
    approve_done = all(p.get("approved") for p in progress if p.get("stage") == "approve")
    execute_done = any(p.get("approved") for p in progress if p.get("stage") == "execute")
    has_accept = any(p.get("stage") == "accept" for p in progress)
    accept_done = any(p.get("approved") for p in progress if p.get("stage") == "accept")
    if accept_done or (execute_done and not has_accept):
        return "closed"
    if execute_done:
        return "verifying"
    if approve_done:
        return "dispatched"
    return "approving"


def _status_note(to: str) -> str:
    return {
        "dispatched": "审批通过·已派发",
        "verifying": "执行人提交·待验收",
        "closed": "审批人确认·闭环",
        "executing": "审批通过·开始执行",
    }.get(to, "状态推进")


def _sync_oa_results(wo: WorkOrder, db: Session, form_values: list | None = None):
    """闭环时回写钉钉表单内容：执行结论 → conclusion，执行附件 → attachments。

    form_values 优先用回调 body 里的 formComponentValues；未取到结论/附件时
    再查钉钉实例兜底（回调 body 有时只含当前节点字段）。
    """
    from app.services import dingtalk
    from app.models import Attachment

    def extract(fvs):
        conclusion = None
        files = []
        reason = None
        for fv in (fvs or []):
            name = fv.get("name") or ""
            value = fv.get("value")
            if not value:
                continue
            if name == "执行结论":
                if isinstance(value, list):
                    value = "\n".join(
                        (v.get("text", "") if isinstance(v, dict) else str(v)) for v in value
                    )
                conclusion = str(value).strip()
            elif name == "根因分析":
                if isinstance(value, list):
                    value = "\n".join(
                        (v.get("text", "") if isinstance(v, dict) else str(v)) for v in value
                    )
                reason = str(value).strip()
            elif name in ("执行佐证", "执行附件", "附件"):
                if not isinstance(value, list):
                    value = [{"url": value, "name": "执行附件"}]
                files = value
        return conclusion, files, reason

    conclusion, files, reason = extract(form_values)
    if not conclusion and not files and not reason:
        try:
            info = dingtalk.query_oa_approval(wo.oa_id)
            c2, f2, r2 = extract((info or {}).get("formComponentValues"))
            if not conclusion:
                conclusion = c2
            if not files:
                files = f2
            if not reason:
                reason = r2
        except Exception as e:
            print(f"[dingtalk] 查询 OA 实例兜底跳过: {e}")

    if conclusion:
        wo.conclusion = conclusion
    if reason:
        # 责任人回填的根因 → backfill_reason（对应工单回填字段）
        wo.backfill_reason = reason
        wo.backfill_status = "filled"
        if not wo.backfilled_at:
            from datetime import datetime
            wo.backfilled_at = datetime.now()
    for f in files or []:
        oss_key = (f.get("url") or "") if isinstance(f, dict) else str(f)
        fname = (f.get("name") or "执行附件") if isinstance(f, dict) else "执行附件"
        exists = db.query(Attachment).filter_by(work_order_id=wo.id, oss_key=oss_key).first()
        if not exists and oss_key:
            db.add(Attachment(
                work_order_id=wo.id, filename=fname, oss_key=oss_key, size=0,
            ))


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

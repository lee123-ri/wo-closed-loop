"""OA 审批事件处理核心逻辑（HTTP 回调与 Stream 模式共用）。

两者拿到的事件体都是同一套钉钉审批事件（含 processInstanceId / result / activityName），
处理链路完全一致：反查工单 → 以钉钉实例实际状态为准 → 推进平台状态机 → 闭环时拉附件。

HTTP 回调版本见 api/dingtalk.py 的 POST /oa/callback（多了加解密回执）；
Stream 版本见 dingtalk_stream.py（长连接收事件，无加解密、无回执）。
"""
import json
import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models import Attachment, StatusLog, WorkOrder

logger = logging.getLogger(__name__)


def apply_oa_event(body: dict, db: Session, event_type: str = "") -> dict:
    """处理一条钉钉审批事件，同步工单状态。返回 {"success", "status", ...}。

    body 需含 processInstanceId（钉钉审批事件体，bpms_instance_change / bpms_task_change）。
    event_type 仅用于 StatusLog 备注标注（HTTP 回调传 body.EventType，Stream 传 headers.event_type）。
    """
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            body = {}

    # 兼容：事件体可能包一层 data
    if "processInstanceId" not in body and isinstance(body, dict) and "data" in body:
        body = body["data"]

    # 关键：钉钉「审批实例/任务流转」事件体里没有表单字段，只有 processInstanceId。
    # 所以不能靠「工单编号」字段反查，必须用实例 ID 匹配 wo.oa_id。
    pid = body.get("processInstanceId") or body.get("process_instance_id")
    if not pid:
        return {"success": False, "msg": "缺少 processInstanceId"}

    wo = db.query(WorkOrder).filter(WorkOrder.oa_id == pid).first()
    if not wo:
        # 兜底：非常规事件体可能携带 formComponentValues，按「工单编号」再找一次
        code = None
        for fv in body.get("formComponentValues", []) or []:
            if fv.get("name") == "工单编号":
                code = fv.get("value")
                break
        wo = db.query(WorkOrder).filter(WorkOrder.code == code).first() if code else None
    if not wo:
        return {"success": False, "msg": "工单不存在（未按 processInstanceId 匹配到）"}

    if wo.oa_id != pid:
        wo.oa_id = pid

    result = body.get("result")  # agree/refuse；start 类事件无 result
    activity = body.get("activityName") or body.get("taskName") or ""

    # 以钉钉实例实际状态为准（查询带上最新 status/result/tasks），回调 body 只作触发器。
    # 平台状态一律从钉钉实例推导 —— 钉钉审批流是唯一状态源。
    from app.services.dingtalk import query_oa_approval
    info = query_oa_approval(pid)
    oa_status = info.get("status") if info else None
    if info and info.get("result"):
        result = info.get("result")

    def _apply(to_status: str, note: str, close: bool = False) -> str:
        if wo.status != to_status:
            db.add(StatusLog(work_order_id=wo.id, from_status=wo.status, to_status=to_status,
                             note=f"钉钉OA「{activity or event_type or '审批'}」{note}"))
        wo.status = to_status
        if close:
            wo.completed_date = date.today()
            if not wo.conclusion:
                wo.conclusion = "钉钉OA审批通过·闭环"
            # 若闭环的是措施工单，回写关联异常主单进度（2/11 / 全闭环置待复核）
            from app.services.pool_service import _notify_measure_closed
            _notify_measure_closed(db, wo)
        db.commit()
        return to_status

    status = wo.status
    # 1) 任意节点驳回 / 实例被撤销终止 → rejected
    if result == "refuse" or oa_status in ("TERMINATED", "CANCELED"):
        status = _apply("rejected", "驳回" if result == "refuse" else "已撤销/终止")
    # 2) 实例已归档且通过 → closed（仅当钉钉实例 COMPLETED 才闭环，避免过早闭环）
    elif oa_status == "COMPLETED":
        status = _apply("closed", "审批通过·闭环", close=True)
    # 3) 审批进行中（RUNNING/NEW）：按「已通过的审批节点数」反推平台状态。
    #    实际模板为 2 个审批节点：责任人(执行/提交佐证) → 审批人(确认闭环)。
    #      1 节点通过 = 责任人已提交佐证 → verifying；2 节点通过 = 实例 COMPLETED（由上面的分支闭环）。
    #    dispatched / executing 只存在于手动流，OA 不驱动。
    #    只依赖钉钉实例现状，不依赖事件到达次数 → 天然幂等（重推/重复轮询不会重复推进）。
    else:
        approved = _approved_node_count(info)
        if approved is not None:
            target = _status_for_approved_nodes(approved)
            if target and target != wo.status:
                status = _apply(target, f"审批已通过 {approved} 个节点")
        elif result == "agree":
            # 兜底：查询结果拿不到任务列表时，才按「责任人已提交佐证」前进一步
            forward = {
                "approving": ("verifying", "责任人已提交佐证·待验收"),
            }
            if wo.status in forward:
                to, note = forward[wo.status]
                status = _apply(to, note)
            elif activity:
                db.add(StatusLog(work_order_id=wo.id, from_status=wo.status, to_status=wo.status,
                                 note=f"钉钉OA节点「{activity}」通过"))
                db.commit()

    # 每次事件都回写表单内容 + 附件（钉钉端改的内容/传的附件要同步回平台）
    if info:
        _sync_form_back(wo, db, info)
        db.commit()

    return {"success": True, "status": status}


def _approved_node_count(info: dict | None) -> int | None:
    """钉钉实例「已通过（agree）的审批节点数」。字段名兼容新/旧网关大小写；拿不到任务列表时返回 None。"""
    if not isinstance(info, dict):
        return None
    tasks = info.get("tasks") or info.get("Tasks")
    if not isinstance(tasks, list):
        return None
    n = 0
    for t in tasks:
        if not isinstance(t, dict):
            continue
        r = str(t.get("task_result") or t.get("taskResult") or "").strip().lower()
        if r in ("agree", "agreed"):
            n += 1
    return n


def _status_for_approved_nodes(approved: int) -> str | None:
    """2 节点审批流（责任人执行→审批人确认闭环）已通过节点数 → 平台状态。

    1 节点通过 = 责任人已提交佐证 → verifying（待验收）。
    0 个通过保持 approving；≥2 已由 COMPLETED 分支处理，返回 None。
    """
    return {1: "verifying"}.get(approved)


def _sync_form_back(wo: WorkOrder, db: Session, info: dict):
    """把钉钉审批单上改动的表单内容 + 附件回写到工单。"""
    try:
        from app.services.dingtalk import query_oa_approval  # noqa: F401（info 由调用方传入）
        fvs = info.get("form_component_values") or []
        by_name = {fv.get("name"): fv.get("value") for fv in fvs if isinstance(fv, dict)}
        # 内容回写（执行人/审批人可能在钉钉里改了这些字段）
        for name, attr in (("触发原因", "reason"), ("行动要求", "action"), ("执行结论", "conclusion")):
            v = by_name.get(name)
            if v is not None and str(v).strip() and str(getattr(wo, attr) or "").strip() != str(v).strip():
                setattr(wo, attr, str(v).strip())
        # 附件回写：字段名含「佐证/附件」的都按附件解析（模板命名可能不同）
        for name, v in by_name.items():
            if not v or not isinstance(name, str) or not ("佐证" in name or "附件" in name):
                continue
            files = v if isinstance(v, list) else []
            if isinstance(v, str):
                try:
                    parsed = json.loads(v)
                    files = parsed if isinstance(parsed, list) else []
                except Exception:
                    files = [{"url": v, "name": name}]
            print(f"[dingtalk] 发现附件字段「{name}」，解析出 {len(files)} 个文件", flush=True)
            for f in files:
                if not isinstance(f, dict):
                    continue
                sid = str(f.get("spaceId") or "")
                fid = str(f.get("fileId") or "")
                oss_key = f"{sid}:{fid}" if sid and fid else str(f.get("url") or sid or fid or "")
                if not oss_key:
                    continue
                exists = db.query(Attachment).filter_by(work_order_id=wo.id, oss_key=oss_key).first()
                if not exists:
                    db.add(Attachment(
                        work_order_id=wo.id,
                        filename=str(f.get("name") or f.get("fileName") or name),
                        oss_key=oss_key, size=0,
                    ))
    except Exception as e:
        print(f"[dingtalk] 表单/附件回写跳过: {e}")
"""通知触发入口。

实际投递统一委托给 ``notification_rules``，可配置渠道仅机器人私聊和群聊。
本文件中的旧分组格式函数仅保留给历史展示/测试，不再作为生产投递策略。
"""
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import NotificationPolicy, NotificationLog, WorkOrder, User
from app.services import dingtalk

settings = get_settings()


def _detail_url(wo_id: int) -> str:
    """拼工单详情跳转链接（钉钉卡片「查看工单」按钮用绝对地址）。"""
    base = (settings.frontend_base_url or "").rstrip("/")
    return f"{base}/work-orders/{wo_id}" if base else ""


def trigger_notify(wo_id: int, event: str) -> None:
    """流转/派发后的通知入口（懒加载 Celery task 避免循环导入；异常吞掉只打日志）。"""
    try:
        from app.tasks import send_notification_task
        send_notification_task.delay(wo_id, event)
    except Exception as e:
        print(f"[notify] 触发通知跳过: {e}")


def trigger_dispatch_group(wo_ids: list[int]) -> None:
    """派发后按每张工单触发已启用的统一通知规则。"""
    if not wo_ids:
        return
    try:
        from app.tasks import send_notification_task
        for wo_id in wo_ids:
            send_notification_task.delay(wo_id, "dispatch")
    except Exception as e:
        print(f"[notify] 群发触发跳过: {e}")


def trigger_measure_dispatch(host_id: int, measure_ids: list[int]) -> None:
    """措施派发后按统一规则触发；没有启用规则就不投递。"""
    if not measure_ids:
        return
    try:
        from app.tasks import send_notification_task
        for wo_id in measure_ids:
            send_notification_task.delay(wo_id, "dispatch")
    except Exception as e:
        print(f"[notify] 措施通报触发跳过: {e}")


def build_dispatch_group_markdown(db: Session, wo_ids: list[int]) -> list[str]:
    """【旧版，保留给测试】按责任人把一批工单分组，返回每组一条 markdown。"""
    if not wo_ids:
        return []
    wos = db.query(WorkOrder).filter(WorkOrder.id.in_(wo_ids)).all()
    groups: dict[int, list[WorkOrder]] = {}
    for wo in wos:
        groups.setdefault(wo.person_id or 0, []).append(wo)
    chunks: list[str] = []
    for person_id, items in groups.items():
        person = db.get(User, person_id) if person_id else None
        head = f"**{person.name}**" if person else "**未指派责任人**"
        lines = [f"📌 新工单待处理 · {len(items)} 条", "", head, ""]
        for wo in items:
            url = _detail_url(wo.id)
            lines.append(f"- [{wo.code} {wo.title or '未命名'}]({url})")
        chunks.append("\n".join(lines))
    return chunks


# ── 群 @ 提醒（自定义 webhook 机器人，markdown + at.atUserIds）──────────

def _mmdd(d) -> str:
    return d.strftime("%m-%d") if d else "—"


def _short_title(title: str) -> str:
    """去掉 SXZ-xxxx 编号前缀，只留场站+异常名（用户嫌编号长且没用）。"""
    t = (title or "").strip()
    if t.startswith("SXZ-"):
        _, _, rest = t.partition(" ")
        if rest:
            return rest.strip()
    return t


def _fallback_at() -> str | None:
    return settings.dingtalk_fallback_userid or None


def _at_of(user: User | None) -> str | None:
    return user.dingtalk_id if (user and user.dingtalk_id) else None


def _send_group(text: str, at_userids: list[str] | None) -> bool:
    """发群 markdown 并红点 @（自定义 webhook 机器人 at.atUserIds）。"""
    return dingtalk.send_robot_group(
        settings.dingtalk_robot_webhook, settings.dingtalk_robot_secret,
        "工单提醒", text, at_userids=at_userids or None,
    )


def _row_link(wo: WorkOrder) -> str:
    disp = _short_title(wo.title) or "未命名"
    return f"- [{disp}｜{wo.priority or '—'}｜截止 {_mmdd(wo.deadline)}]({_detail_url(wo.id)})"


def _anomaly_text(header: str, at_line: str, items: list[WorkOrder]) -> str:
    return "\n".join([header, "", at_line, ""] + [_row_link(wo) for wo in items])


def notify_anomaly_new(wo_ids: list[int]) -> dict:
    """场景1：异常工单抓到平台 → 按责任人分组 @；找不到责任人 @兜底(刘冰)。"""
    if not wo_ids:
        return {"sent_groups": 0, "failed": 0}
    db = SessionLocal()
    try:
        wos = db.query(WorkOrder).filter(WorkOrder.id.in_(wo_ids)).all()
        by_person: dict[int, list[WorkOrder]] = {}
        orphan: list[WorkOrder] = []
        for wo in wos:
            (by_person.setdefault(wo.person_id, []).append(wo)
             if wo.person_id else orphan.append(wo))
        sent = failed = 0
        for pid, items in by_person.items():
            person = db.get(User, pid)
            at = _at_of(person)
            text = _anomaly_text(
                f"📌 新增异常工单 · {len(items)} 条待处理",
                f"@{person.name}" if person else "@责任人", items)
            if _send_group(text, [at] if at else None):
                sent += 1
            else:
                failed += 1
        if orphan:
            text = _anomaly_text(
                f"📌 新增异常工单 · {len(orphan)} 条待处理（未匹配责任人）",
                "@刘冰 请指派", orphan)
            if _send_group(text, [_fallback_at()] if _fallback_at() else None):
                sent += 1
            else:
                failed += 1
        return {"sent_groups": sent, "failed": failed, "total_wo": len(wos)}
    finally:
        db.close()


def notify_measure_dispatch(host_id: int, measure_ids: list[int]) -> dict:
    """场景2：措施工单派发 → 通报（首行点完成人=异常工单责任人），@各措施执行人。"""
    if not measure_ids:
        return {"sent_groups": 0, "failed": 0}
    db = SessionLocal()
    try:
        host = db.get(WorkOrder, host_id)
        measures = db.query(WorkOrder).filter(WorkOrder.id.in_(measure_ids)).all()
        if not measures:
            return {"sent_groups": 0, "failed": 0}
        owner = db.get(User, host.person_id) if (host and host.person_id) else None
        owner_name = owner.name if owner else "—"
        host_title = _short_title(host.title) if host else "异常工单"
        at_ids: list[str] = []
        lines = [f"✅ 处置完成 · {owner_name} 已处理「{host_title}」，派发 {len(measures)} 条措施工单", ""]
        for m in measures:
            exe = db.get(User, m.person_id) if m.person_id else None
            if _at_of(exe):
                at_ids.append(_at_of(exe))
            disp = _short_title(m.title) or "未命名"
            exe_name = exe.name if exe else "—"
            lines.append(f"- [{disp}｜{exe_name}｜截止 {_mmdd(m.deadline)}]({_detail_url(m.id)})")
        ok = _send_group("\n".join(lines), at_ids or None)
        return {"sent_groups": int(ok), "failed": int(not ok), "total_wo": len(measures)}
    finally:
        db.close()


def send_dispatch_group(wo_ids: list[int]) -> dict:
    """普通「派发」合并发群：按责任人分组 @；无责任人 @兜底(刘冰)。"""
    if not wo_ids:
        return {"sent_groups": 0, "failed": 0}
    db = SessionLocal()
    try:
        wos = db.query(WorkOrder).filter(WorkOrder.id.in_(wo_ids)).all()
        by_person: dict[int, list[WorkOrder]] = {}
        orphan: list[WorkOrder] = []
        for wo in wos:
            (by_person.setdefault(wo.person_id, []).append(wo)
             if wo.person_id else orphan.append(wo))
        sent = failed = 0
        for pid, items in by_person.items():
            person = db.get(User, pid)
            at = _at_of(person)
            text = _anomaly_text(
                f"📌 新工单待处理 · {len(items)} 条",
                f"@{person.name}" if person else "@责任人", items)
            if _send_group(text, [at] if at else None):
                sent += 1
            else:
                failed += 1
        if orphan:
            text = _anomaly_text(
                f"📌 新工单待处理 · {len(orphan)} 条（未匹配责任人）",
                "@刘冰 请指派", orphan)
            if _send_group(text, [_fallback_at()] if _fallback_at() else None):
                sent += 1
            else:
                failed += 1
        return {"sent_groups": sent, "failed": failed, "total_wo": len(wos)}
    finally:
        db.close()


def resolve_channels(db: Session, priority: str, event: str) -> list[str]:
    """查通知策略，返回通道列表"""
    p = (
        db.query(NotificationPolicy)
        .filter(
            NotificationPolicy.priority == priority,
            NotificationPolicy.event == event,
            NotificationPolicy.enabled.is_(True),
        )
        .first()
    )
    if not p or not p.channels:
        return []
    return list(p.channels)


def build_message(wo: WorkOrder, event: str, db: Session) -> tuple[str, str]:
    """构造通知标题和正文"""
    title_map = {
        "dispatch": f"📌 新工单待处理 · {wo.code}",
        "unread": f"⏰ 工单 24h 未读提醒 · {wo.code}",
        "sla_warn": f"⚠️ 工单 SLA 即将到期 · {wo.code}",
        "sla_breach": f"🚨 工单 SLA 已违约 · {wo.code}",
        "sla_breach_72h": f"🚨🚨 工单违约超 72h · {wo.code}",
    }
    title = title_map.get(event, f"工单通知 · {wo.code}")
    person = db.get(User, wo.person_id) if wo.person_id else None
    approver = db.get(User, wo.approver_id) if wo.approver_id else None
    body = (
        f"**标题**：{wo.title}\n\n"
        f"**责任人**：{person.name if person else '—'}\n"
        f"**审批人**：{approver.name if approver else '—'}\n"
        f"**优先级**：{wo.priority}\n"
        f"**截止**：{wo.deadline}\n"
        f"**状态**：{wo.status}\n"
    )
    if (wo.escalation_level or 0) > 0:
        body += f"**升级级别**：L{wo.escalation_level}\n"
    if event == "sla_breach" and wo.overdue_days:
        body += f"\n⚠️ 已超期 {wo.overdue_days} 天\n"
    return title, body


def send_notification(wo_id: int, event: str) -> dict:
    """同步投递已启用规则（也可被 Celery 调用）。"""
    db = SessionLocal()
    try:
        wo = db.get(WorkOrder, wo_id)
        if not wo:
            return {"error": "work order not found"}
        from app.services.notification_rules import dispatch
        result = dispatch(db, wo, event, dry_run=False)
        db.commit()
        return result
    finally:
        db.close()

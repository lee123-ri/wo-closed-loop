"""错误告警：把关键故障推给负责人（钉钉工作通知单发、一对一）。

原则
----
- 告警是「尽力而为」：发不出去（钉钉/网络故障）只落日志，绝不因告警本身再抛错把主流程带崩。
- 防抖：同一 key 在 ALERT_DEBOUNCE_SECONDS 内只发一次，避免同类错误短时间轰炸。
- 通道：send_work_notification（复用 AppKey/Secret/AgentId，与 OA 同网关），
  目标 userId = ALERT_NOTIFY_USERID（空则回落 DINGTALK_FALLBACK_USERID）。

消息约定
--------
每条告警带：summary（一句话结论）、detail（端点/工单/摘要/根因）、fix（一行「怎么办」），
收到即知道去哪修，不必再翻代码。
"""
from __future__ import annotations

import threading
import time

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)
settings = get_settings()

# 进程内防抖表：key -> 上次发送时间戳（单调时钟）
_last_sent: dict[str, float] = {}
_lock = threading.Lock()


def _target_userid() -> str:
    return (
        (settings.alert_notify_userid or "").strip()
        or (settings.dingtalk_fallback_userid or "").strip()
    )


def send_alert(
    summary: str,
    *,
    detail: str = "",
    fix: str = "",
    level: str = "error",
    key: str | None = None,
) -> bool:
    """发送错误告警（钉钉工作通知单发）。返回是否真的发出（被开关/防抖/未配置拦下时返回 False）。"""
    if not settings.alert_enabled:
        return False

    userid = _target_userid()
    if not userid:
        log.warning("[alert] 未配置告警接收人（ALERT_NOTIFY_USERID / DINGTALK_FALLBACK_USERID），跳过告警")
        return False

    k = key or summary
    now = time.monotonic()
    with _lock:
        last = _last_sent.get(k)
        if last is not None and now - last < max(0, settings.alert_debounce_seconds):
            log.info("[alert] 同类告警在防抖窗口内，跳过重复发送: %s", k)
            return False
        _last_sent[k] = now
        # 防抖表无限增长防护：超 1000 条清理已过窗口的老记录
        if len(_last_sent) > 1000:
            cutoff = now - max(0, settings.alert_debounce_seconds) - 60
            for stale in [x for x, t in _last_sent.items() if t < cutoff]:
                _last_sent.pop(stale, None)

    icon = {"error": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(level, "🔔")
    title = f"{icon} 工单告警：{summary[:40]}"
    body_lines = [f"**{summary}**", ""]
    if detail:
        body_lines.append(str(detail))
    if fix:
        body_lines.append("")
        body_lines.append(f"🧰 怎么修：{fix}")
    try:
        from app.services import dingtalk

        ok = dingtalk.send_work_notification(userid, title, "\n\n".join(body_lines))
        if ok:
            log.info("[alert] 已单发告警给 %s：%s", userid, summary)
        else:
            log.error("[alert] 告警单发失败（钉钉侧返回失败）：%s", summary)
        return bool(ok)
    except Exception as e:  # 告警通道自身异常绝不能把主业务带崩
        log.error("[alert] 告警发送异常: %s", e, exc_info=True)
        return False
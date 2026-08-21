"""判断Agent 调用服务

调用技术团队提供的判断Agent HTTP API，审核回填的根因分析和应对措施。
支持降级：Agent不可达/超时 → 跳过判断，按PMO原输入生成工单。
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ── 降级原因常量 ──────────────────────────────────────

DEGRADE_TIMEOUT = "timeout"
DEGRADE_UNREACHABLE = "unreachable"
DEGRADE_PARSE_ERROR = "parse_error"
DEGRADE_SERVER_ERROR = "server_error"
DEGRADE_DISABLED = "disabled"


def _build_payload(wo: Any, pool_item: Any | None) -> dict:
    """构建发给判断Agent的请求体"""
    payload: dict[str, Any] = {
        "work_order_id": wo.code,
        "station_name": _get_project_name(wo),
        "anomaly": None,
        "backfill": {
            "reason": wo.backfill_reason,
            "action": wo.backfill_action,
        },
        "proposed_work_order": {
            "title": getattr(wo, "triggered_wo_title", None),
            "deadline": str(wo.triggered_wo_deadline) if getattr(wo, "triggered_wo_deadline", None) else None,
            "person_name": getattr(wo, "triggered_wo_person_name", None),
            "priority": wo.priority,
        },
    }
    if pool_item:
        payload["anomaly"] = {
            "metric_type": pool_item.metric_type,
            "metric_value": pool_item.metric_value,
            "threshold": pool_item.threshold,
            "deviation_pct": pool_item.deviation_pct,
            "period": str(wo.created_date)[:7] if wo.created_date else None,
        }
    if pool_item and pool_item.raw_data:
        payload["raw_data"] = pool_item.raw_data
    return payload


def _get_project_name(wo: Any) -> str | None:
    """从工单关联获取项目名"""
    try:
        from app.core.database import SessionLocal
        from app.models import Project
        db = SessionLocal()
        proj = db.get(Project, wo.project_id) if wo.project_id else None
        db.close()
        return proj.name if proj else None
    except Exception:
        return None


def call_judgment_agent(wo: Any, pool_item: Any | None = None) -> dict:
    """同步调用判断Agent，返回判定结果。

    Returns:
        {
            "verdict": "approved_suggested" | "approved_as_is" | "rejected" | "no_action_needed" | "degraded",
            "confidence": float,
            "reasoning": str,
            "suggestions": dict | None,
            "reject_reason": str | None,
            "risk_level": str | None,
        }
    """
    settings = get_settings()

    if not settings.judgment_enabled:
        return _degraded_result("判断Agent已关闭", DEGRADE_DISABLED)

    payload = _build_payload(wo, pool_item)
    url = f"{settings.judgment_agent_url.rstrip('/')}/judge"
    timeout = settings.judgment_timeout

    try:
        headers = {"Content-Type": "application/json"}
        if settings.judgment_agent_token:
            headers["Authorization"] = f"Bearer {settings.judgment_agent_token}"

        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=headers)

        if resp.status_code == 200:
            data = resp.json()
            return _validate_response(data)

        logger.warning(f"[judgment] Agent返回非200: {resp.status_code} {resp.text[:200]}")
        return _degraded_result(f"Agent返回{resp.status_code}", DEGRADE_SERVER_ERROR)

    except httpx.TimeoutException:
        logger.warning(f"[judgment] Agent超时({timeout}s)，降级")
        return _degraded_result(f"Agent超时({timeout}s)", DEGRADE_TIMEOUT)
    except httpx.ConnectError as e:
        logger.warning(f"[judgment] Agent不可达: {e}")
        return _degraded_result(f"Agent不可达: {e}", DEGRADE_UNREACHABLE)
    except Exception as e:
        logger.warning(f"[judgment] 调用异常: {e}")
        return _degraded_result(str(e), DEGRADE_SERVER_ERROR)


def _validate_response(data: dict) -> dict:
    """校验Agent返回格式，不合法则降级"""
    verdict = data.get("verdict", "")
    valid_verdicts = {"approved_suggested", "approved_as_is", "rejected", "no_action_needed"}
    if verdict not in valid_verdicts:
        logger.warning(f"[judgment] 非法verdict: {verdict}")
        return _degraded_result(f"非法verdict: {verdict}", DEGRADE_PARSE_ERROR)

    return {
        "verdict": verdict,
        "confidence": float(data.get("confidence", 0.0)),
        "reasoning": str(data.get("reasoning", "")),
        "suggestions": data.get("suggestions") if verdict == "approved_suggested" else None,
        "reject_reason": data.get("reject_reason") if verdict == "rejected" else None,
        "risk_level": data.get("risk_level"),
    }


def _degraded_result(reason: str, degrade_reason: str) -> dict:
    return {
        "verdict": "degraded",
        "confidence": 0.0,
        "reasoning": f"判断Agent不可用({reason})，降级为原样创建工单B",
        "suggestions": None,
        "reject_reason": None,
        "risk_level": None,
        "_degrade_reason": degrade_reason,
    }


def record_degradation(wo_id: int, reason: str, original_error: str | None = None):
    """记录降级日志"""
    try:
        from app.core.database import SessionLocal
        from app.models.judgment import JudgmentDegradationLog
        db = SessionLocal()
        db.add(JudgmentDegradationLog(
            work_order_id=wo_id,
            reason=reason,
            original_error=original_error,
        ))
        db.commit()
        db.close()
    except Exception as e:
        logger.error(f"[judgment] 写降级日志失败: {e}")


def apply_judgment_to_wo(wo: Any, judgment: dict):
    """将判断结果写入工单对象"""
    wo.judgment_status = judgment["verdict"]
    wo.judgment_result = judgment
    wo.judgment_completed_at = datetime.now(timezone.utc)
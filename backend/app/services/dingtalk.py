"""钉钉开放平台 SDK 封装。

所有调用都从 settings 取 key，真实 key 在 .env 填入即可，代码无需改动。
未配置 key 时方法返回占位结果，不报错（便于本地开发）。
"""
import time
import hashlib
import hmac
import base64
import urllib.parse
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import User
import redis

settings = get_settings()

# access_token 缓存（10 分钟有效期，提前 5 分钟刷新）
_TOKEN_KEY = "dingtalk:access_token"
_API = "https://api.dingtalk.com"


def _redis():
    try:
        r = redis.from_url(settings.redis_url, socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None


def _configured() -> bool:
    return bool(settings.dingtalk_app_key and settings.dingtalk_app_secret)


def get_access_token() -> str | None:
    """获取企业 access_token，带 Redis 缓存"""
    if not _configured():
        return None
    r = _redis()
    if r:
        cached = r.get(_TOKEN_KEY)
        if cached:
            return cached.decode() if isinstance(cached, bytes) else cached
    try:
        resp = httpx.post(
            f"{_API}/v1.0/oauth2/accessToken",
            json={"appKey": settings.dingtalk_app_key, "appSecret": settings.dingtalk_app_secret},
            timeout=10,
        )
        resp.raise_for_status()
        token = resp.json().get("accessToken")
        if token and r:
            r.setex(_TOKEN_KEY, 7000, token)  # 缓存 ~116 分钟
        return token
    except Exception as e:
        print(f"[dingtalk] get_access_token failed: {e}")
        return None


def _headers(token: str | None) -> dict:
    return {"x-acs-dingtalk-access-token": token or "", "Content-Type": "application/json"}


def create_oa_approval(wo: Any, token: str | None = None) -> str | None:
    """发起钉钉 OA 审批。返回钉钉审批实例 ID。

    需在钉钉后台配置审批模板（DINGTALK_OA_TEMPLATE_ID），字段映射：
      标题->title, 原因->reason, 行动->action, 责任人->person, 截止->deadline
    """
    if not _configured() or not settings.dingtalk_oa_template_id:
        print("[dingtalk] OA 模板未配置，跳过发起审批")
        return None
    token = token or get_access_token()
    approver = wo.approver_name or ""
    # 查审批人的钉钉 userId（此处简化，真实场景需通讯录接口映射）
    payload = {
        "processCode": settings.dingtalk_oa_template_id,
        "originatorUserId": "",  # 提交人 userId（需映射）
        "deptId": 0,
        "formComponentValues": [
            {"name": "工单编号", "value": getattr(wo, "code", "")},
            {"name": "标题", "value": getattr(wo, "title", "")},
            {"name": "触发原因", "value": getattr(wo, "reason", "") or ""},
            {"name": "行动要求", "value": getattr(wo, "action", "") or ""},
            {"name": "责任人", "value": getattr(wo, "person_name", "") or ""},
            {"name": "审批人", "value": approver},
            {"name": "截止日期", "value": str(getattr(wo, "deadline", "") or "")},
        ],
    }
    try:
        resp = httpx.post(f"{_API}/v1.0/workflow/processes", headers=_headers(token), json=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("result", {}).get("processInstanceId")
        print(f"[dingtalk] create OA failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[dingtalk] create OA exception: {e}")
    return None


def query_oa_approval(process_instance_id: str, token: str | None = None) -> dict | None:
    """查询 OA 审批单状态"""
    if not _configured() or not process_instance_id:
        return None
    token = token or get_access_token()
    try:
        resp = httpx.get(
            f"{_API}/v1.0/workflow/processInstances/{process_instance_id}",
            headers=_headers(token),
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[dingtalk] query OA exception: {e}")
    return None


def send_work_notification(user_id: str, title: str, content: str, action_url: str = "") -> bool:
    """发送工作通知（消息卡片）。user_id 为钉钉 userId"""
    if not _configured():
        print(f"[dingtalk-mock] 工作通知 -> {user_id}: {title}")
        return False
    token = get_access_token()
    msg = {
        "msgtype": "action_card",
        "action_card": {
            "title": title,
            "text": f"## {title}\n\n{content}",
            "btn_orientation": "0",
            "btn_json": [{"title": "查看工单", "action_url": action_url}] if action_url else [],
        },
    }
    try:
        resp = httpx.post(
            f"{_API}/v1.0/robot/oToMessages/batchSend",
            headers=_headers(token),
            json={"robotCode": settings.dingtalk_agent_id, "userIds": [user_id], "msg": msg},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[dingtalk] work notify exception: {e}")
        return False


def send_robot_group(webhook: str, secret: str, title: str, text: str, at_userids: list[str] | None = None) -> bool:
    """群机器人发消息（加签安全设置）"""
    if not webhook:
        print(f"[dingtalk-mock] 群消息: {title}")
        return False
    timestamp = str(round(time.time() * 1000))
    sign = _sign(secret, timestamp) if secret else ""
    body = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
        "at": {"atUserIds": at_userids or [], "isAtAll": False},
    }
    url = f"{webhook}&timestamp={timestamp}&sign={sign}" if sign else webhook
    try:
        resp = httpx.post(url, json=body, timeout=10)
        return resp.status_code == 200 and resp.json().get("errcode") == 0
    except Exception as e:
        print(f"[dingtalk] robot group exception: {e}")
        return False


def send_phone_ding(user_id: str, content: str) -> bool:
    """电话 DING（需开通权限）。简化：调用工作通知代替"""
    return send_work_notification(user_id, "电话DING", content)


def get_group_members(conversation_id: str, token: str | None = None) -> list[dict]:
    """获取钉钉群成员列表。

    返回 [{"name": "王小宁", "dingtalk_id": "xxx", "union_id": "..."}]
    无 key 时返回 mock 数据。
    """
    if not _configured() or not conversation_id:
        return _mock_group_members()
    token = token or get_access_token()
    members: list[dict] = []
    cursor = 0
    has_more = True
    try:
        while has_more:
            resp = httpx.get(
                f"{_API}/v1.0/robot/groupConversations/{conversation_id}/members",
                headers=_headers(token),
                params={"maxResults": 100, "nextToken": cursor},
                timeout=10,
            )
            if resp.status_code != 200:
                print(f"[dingtalk] get group members failed: {resp.status_code}")
                break
            data = resp.json()
            for m in data.get("memberList", []):
                members.append({
                    "name": m.get("nick") or m.get("name") or "",
                    "dingtalk_id": m.get("staffId") or "",
                    "union_id": m.get("unionId") or "",
                })
            has_more = data.get("hasMore", False)
            cursor = data.get("nextToken", 0)
            if not has_more:
                break
    except Exception as e:
        print(f"[dingtalk] group members exception: {e}")
    return members


def _mock_group_members() -> list[dict]:
    """无凭证时的占位成员（验证链路用）"""
    return [
        {"name": "王小宁", "dingtalk_id": "mock-001", "union_id": ""},
        {"name": "于鸿飞", "dingtalk_id": "mock-002", "union_id": ""},
        {"name": "高志强", "dingtalk_id": "mock-003", "union_id": ""},
    ]


def _sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode("utf-8")

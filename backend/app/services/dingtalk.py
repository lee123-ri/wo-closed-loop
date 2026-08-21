"""钉钉开放平台 SDK 封装。

所有调用都从 settings 取 key，真实 key 在 .env 填入即可，代码无需改动。
未配置 key 时方法返回占位结果，不报错（便于本地开发）。

OA审批使用 oapi.dingtalk.com 旧版网关（已通过测试验证可用）。
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
_OAPI = "https://oapi.dingtalk.com"


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
    """获取企业 access_token（使用旧版 oapi 网关），带 Redis 缓存"""
    if not _configured():
        return None
    r = _redis()
    if r:
        cached = r.get(_TOKEN_KEY)
        if cached:
            return cached.decode() if isinstance(cached, bytes) else cached
    try:
        resp = httpx.get(
            f"{_OAPI}/gettoken",
            params={"appkey": settings.dingtalk_app_key, "appsecret": settings.dingtalk_app_secret},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") == 0:
            token = data.get("access_token")
            if token and r:
                r.setex(_TOKEN_KEY, 7000, token)  # 缓存 ~116 分钟
            return token
        else:
            print(f"[dingtalk] gettoken failed: errcode={data.get('errcode')} msg={data.get('errmsg')}")
            return None
    except Exception as e:
        print(f"[dingtalk] get_access_token failed: {e}")
        return None


def _headers(token: str | None) -> dict:
    """旧版 oapi 不需要特殊 header，token 通过 URL 参数传递"""
    return {"Content-Type": "application/json"}


def create_oa_approval(wo: Any, chain: list[dict] | None = None, token: str | None = None) -> str | None:
    """发起钉钉 OA 审批。返回钉钉审批实例 ID。

    使用旧版 oapi 网关（已通过测试验证）。
    chain 为 roles.resolve_oa_chain 解析出的角色审批链；据此填钉钉模板审批节点的
    具体审批人（approvers），使平台角色审批流与钉钉 OA 节点对齐。
    模板字段：工单编号、项目名称、工单类型、触发原因、行动要求、
              责任人、截止时间、执行佐证、执行结论、审批人
    """
    if not _configured() or not settings.dingtalk_oa_template_id:
        print("[dingtalk] OA 模板未配置，跳过发起审批")
        return None
    token = token or get_access_token()
    if not token:
        print("[dingtalk] no access_token, skip OA")
        return None

    # OA 模板中工单类型的可选值（必须与钉钉管理后台「软工单闭环审批」模板的下拉选项一致，
    # 若模板下拉尚未同步为这 11 类，请先在钉钉后台更新模板选项）
    _OA_TYPE_OPTIONS = {
        "客户满意度/客户投诉", "履约指标异常", "应签未签", "考核扣款", "项目风险",
        "绩效考核", "成本管理", "专项服务", "重点工作督办", "设备预警工单", "其他",
    }

    # 获取关联数据
    project_name = ""
    type_name = ""
    try:
        db = SessionLocal()
        from app.models import Project, WorkOrderTypeKB
        proj = db.query(Project).filter(Project.id == wo.project_id).first()
        if proj:
            project_name = proj.name or ""
        typ = db.query(WorkOrderTypeKB).filter(WorkOrderTypeKB.id == wo.type_id).first()
        if typ:
            raw = typ.name or ""
            # 如果工单类型不在 OA 模板选项里，fallback 到"其他"避免钉钉校验失败
            type_name = raw if raw in _OA_TYPE_OPTIONS else "其他"
        db.close()
    except Exception as e:
        print(f"[dingtalk] lookup project/type failed: {e}")

    # 获取发起人 userId（映射 person_id → dingtalk_id）
    originator_user_id = _lookup_dingtalk_id(wo, "person_id")

    # 构建审批表单数据（字段名必须与钉钉OA模板中的字段名完全一致）
    form_component_values = [
        {"name": "工单编号", "value": getattr(wo, "code", "")},
        {"name": "项目名称", "value": project_name},
        {"name": "工单类型", "value": type_name},
        {"name": "触发原因", "value": getattr(wo, "reason", "") or ""},
        {"name": "行动要求", "value": getattr(wo, "action", "") or ""},
        {"name": "责任人", "value": _lookup_dingtalk_id(wo, "person_id", as_list=True)},
        {"name": "审批人", "value": _lookup_dingtalk_id(wo, "approver_id", as_list=True)},
        {"name": "截止时间", "value": str(getattr(wo, "deadline", "") or "")},
    ]

    # 使用旧版 oapi 网关发起审批（新网关 /v1.0/workflow/processes 404）
    payload = {
        "process_code": settings.dingtalk_oa_template_id,
        "originator_user_id": originator_user_id,
        "dept_id": 1,
        "app_v2": True,
        "form_component_values": form_component_values,
    }
    # 按角色链填审批节点审批人（单模板 3 节点：审批→执行→验收确认）
    approvers = _build_approvers(chain) if chain else None
    if approvers:
        payload["approvers"] = approvers

    try:
        resp = httpx.post(
            f"{_OAPI}/topapi/processinstance/create?access_token={token}",
            json=payload,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("errcode") == 0:
                return data.get("process_instance_id") or data.get("instanceId")
            print(f"[dingtalk] create OA failed: errcode={data.get('errcode')} msg={data.get('errmsg')}")
        else:
            print(f"[dingtalk] create OA HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[dingtalk] create OA exception: {e}")
    return None


def _build_approvers(chain: list[dict]) -> list[dict]:
    """把角色链按阶段分组到单模板的 3 个审批节点：approve→execute→accept。

    每个模板审批节点都是「发起人自选审批人」；approve 阶段可能含多人
    （P1 的 PMO+负责人，模板节点设「依次审批」即依次通过）。
    P3 无 accept 阶段 → 执行人自确认闭环。
    """
    approve = [c["dingtalk_id"] for c in chain if c.get("stage") == "approve"]
    execute = [c["dingtalk_id"] for c in chain if c.get("stage") == "execute"]
    accept = [c["dingtalk_id"] for c in chain if c.get("stage") == "accept"]
    if not accept:
        accept = execute
    approvers: list[dict] = []
    for uids in (approve, execute, accept):
        if uids:
            approvers.append({"actionType": "add", "userIds": uids})
    return approvers


def terminate_oa_approval(process_instance_id: str, token: str | None = None) -> bool:
    """终止钉钉 OA 审批单（平台侧驳回/闭环/重置时反向同步用，best-effort）。

    旧版网关 topapi/processinstance/terminate；失败仅打日志不抛异常。
    """
    if not _configured() or not process_instance_id:
        return False
    token = token or get_access_token()
    if not token:
        return False
    try:
        resp = httpx.post(
            f"{_OAPI}/topapi/processinstance/terminate?access_token={token}",
            json={"process_instance_id": process_instance_id},
            timeout=10,
        )
        if resp.status_code == 200 and resp.json().get("errcode") == 0:
            return True
        print(f"[dingtalk] terminate OA failed: {resp.text[:200]}")
    except Exception as e:
        print(f"[dingtalk] terminate OA exception: {e}")
    return False


def _lookup_dingtalk_id(wo: Any, attr: str, as_list: bool = False) -> str | list:
    """从数据库查询用户的钉钉 userId，代替旧的 _staff_value（用名字不靠谱）"""
    user_id = getattr(wo, attr, None)
    if not user_id:
        return [] if as_list else ""
    try:
        db = SessionLocal()
        user = db.query(User).filter(User.id == user_id).first()
        db.close()
        if user and user.dingtalk_id:
            return [user.dingtalk_id] if as_list else user.dingtalk_id
        if user:
            return [user.name or ""] if as_list else (user.name or "")
    except Exception:
        pass
    return [] if as_list else ""


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

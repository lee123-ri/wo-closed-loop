"""钉钉开放平台 SDK 封装。

所有调用都从 settings 取 key，真实 key 在 .env 填入即可，代码无需改动。
未配置 key 时方法返回占位结果，不报错（便于本地开发）。

OA审批使用 oapi.dingtalk.com 旧版网关（已通过测试验证可用）。
"""
import json
import re
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


def oa_configured() -> bool:
    """是否已完整配置钉钉 OA（有 key/secret + OA 模板），用于判断发起失败是否要报错。"""
    return _configured() and bool(settings.dingtalk_oa_template_id)


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


_NEW_TOKEN_KEY = "dingtalk:new_access_token"


def get_new_access_token() -> str | None:
    """新版网关 OAuth2 accessToken（api.dingtalk.com 的 v1.0 接口用），带 Redis 缓存。"""
    if not _configured():
        return None
    r = _redis()
    if r:
        cached = r.get(_NEW_TOKEN_KEY)
        if cached:
            return cached.decode() if isinstance(cached, bytes) else cached
    try:
        resp = httpx.post(
            f"{_API}/v1.0/oauth2/accessToken",
            json={"appKey": settings.dingtalk_app_key, "appSecret": settings.dingtalk_app_secret},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("accessToken")
        if token and r:
            r.setex(_NEW_TOKEN_KEY, int(data.get("expireIn", 7200)) - 300, token)
        return token
    except Exception as e:
        print(f"[dingtalk] get_new_access_token failed: {e}")
        return None


def get_approval_file_download(process_instance_id: str, file_id: str) -> str | None:
    """审批附件下载（新版 workflow 专用接口，内部处理审批空间授权，不依赖 unionId 空间 ACL）。

    POST /v1.0/workflow/processInstances/spaces/files/urls/download，body {processInstanceId, fileId}，
    返回 result.downloadUri（带签名临时 OSS 地址）。走新版权限，已有 Workflow.Form.Read 即可。
    旧 oapi topapi/processinstance/file/download 查的是已下线的 qyapi_aflow_att_auth_code，弃用。
    """
    token = get_new_access_token()
    if not token or not process_instance_id or not file_id:
        return None
    try:
        resp = httpx.post(
            f"{_API}/v1.0/workflow/processInstances/spaces/files/urls/download",
            headers={"x-acs-dingtalk-access-token": token, "Content-Type": "application/json"},
            json={"processInstanceId": process_instance_id, "fileId": file_id},
            timeout=10,
        )
        data = resp.json() if resp.status_code == 200 else {}
        result = data.get("result") or {}
        url = (result.get("downloadUri") or result.get("download_uri")
               or data.get("downloadUri") or data.get("url"))
        if not url:
            print(f"[dingtalk] workflow urls/download failed: HTTP {resp.status_code} body={resp.text[:200]}")
        return url
    except Exception as e:
        print(f"[dingtalk] approval file download exception: {e}")
        return None


def _headers(token: str | None) -> dict:
    """旧版 oapi 不需要特殊 header，token 通过 URL 参数传递"""
    return {"Content-Type": "application/json"}


def create_oa_approval(wo: Any, token: str | None = None) -> str | None:
    """发起钉钉 OA 审批。返回钉钉审批实例 ID。

    使用旧版 oapi 网关（已通过测试验证）。
    模板字段：工单编号、项目名称、工单类型、触发原因、行动要求、
              责任人、截止时间、计划开始时间、执行佐证、执行结论、审批人、
              任务目标交付物（年度计划类必填，须在钉钉模板里加同名控件）
    """
    if not _configured() or not settings.dingtalk_oa_template_id:
        print("[dingtalk] OA 模板未配置，跳过发起审批")
        return None
    token = token or get_access_token()
    if not token:
        print("[dingtalk] no access_token, skip OA")
        return None

    # 获取关联数据
    project_name = ""
    type_name = ""
    try:
        db = SessionLocal()
        from app.models import Project, ConfigDefinition
        proj = db.query(Project).filter(Project.id == wo.project_id).first()
        if proj:
            project_name = proj.name or ""
        # 工单类型名从统一类型配置取（source_code = 工单类型 code）
        sc = getattr(wo, "source_code", None)
        if sc:
            cd = db.query(ConfigDefinition).filter_by(category="work_order_type", code=sc).first()
            if cd:
                type_name = cd.name or ""
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
        {"name": "任务目标交付物", "value": getattr(wo, "task_deliverable", "") or ""},
        {"name": "责任人", "value": _lookup_dingtalk_id(wo, "person_id", as_list=True)},
        {"name": "审批人", "value": _lookup_dingtalk_id(wo, "approver_id", as_list=True)},
        {"name": "计划开始时间", "value": str(getattr(wo, "planned_start_date", "") or "")},
        {"name": "截止时间", "value": str(getattr(wo, "deadline", "") or "")},
    ]

    print(f"[dingtalk] create OA originator={originator_user_id!r} deadline={getattr(wo, 'deadline', None)!r} form_values={form_component_values!r}")

    # 使用旧版 oapi 网关发起审批（新网关 /v1.0/workflow/processes 404）
    payload = {
        "process_code": settings.dingtalk_oa_template_id,
        "originator_user_id": originator_user_id,
        "dept_id": 1,
        "app_v2": True,
        "form_component_values": form_component_values,
    }

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


# 新格式钉钉 userId：数字-字母数字-(字母数字) ，如 20240411221612722-892A-F34744006
_USERID_RE = re.compile(r"^\d+-[A-Za-z0-9]+-[A-Za-z0-9]*$")


def resolve_userid(did: str | None, token: str | None = None) -> str:
    """把 dingtalk_id 统一成 OA 发起审批接口需要的 userId（新格式）。

    users.dingtalk_id 字段被多处写入，可能存三种值：
    - 新格式 userId（如 20240411221612722-892A-F34744006）→ 直接用
    - union_id（OAuth 登录写入，如 O19HojbsuvkV94oQkXiiprQiEiE）→ topapi/user/getbyunionid 反查
    - 旧 staffId（纯数字，如 032314392348730642）→ topapi/v2/user/get 反查充值新 userId

    转换失败时原样返回（交给钉钉报错，便于日志定位）。
    """
    if not did:
        return ""
    did = did.strip()
    if _USERID_RE.match(did):
        return did
    t = token or get_access_token()
    if not t:
        return did
    try:
        if did.isdigit():
            # 旧 staffId → userId
            resp = httpx.post(
                f"{_OAPI}/topapi/v2/user/get?access_token={t}",
                json={"userid": did}, timeout=10,
            )
            data = resp.json()
            uid = (data.get("result") or {}).get("userid")
        else:
            # union_id → userId
            resp = httpx.post(
                f"{_OAPI}/topapi/user/getbyunionid?access_token={t}",
                json={"unionid": did}, timeout=10,
            )
            data = resp.json()
            uid = (data.get("result") or {}).get("userid")
        if uid:
            print(f"[dingtalk] resolve userid {did[:8]}... -> {uid}")
            return uid
        print(f"[dingtalk] resolve userid failed: src={did[:8]}... err={data.get('errcode')} {data.get('errmsg')}")
    except Exception as e:
        print(f"[dingtalk] resolve userid({did[:8]}...) exception: {e}")
    return did


def _lookup_dingtalk_id(wo: Any, attr: str, as_list: bool = False) -> str | list:
    """从数据库查询用户的钉钉 userId（已归一化为新格式 userId），代替旧的 _staff_value（用名字不靠谱）"""
    user_id = getattr(wo, attr, None)
    if not user_id:
        return [] if as_list else ""
    try:
        db = SessionLocal()
        user = db.query(User).filter(User.id == user_id).first()
        db.close()
        if user and user.dingtalk_id:
            did = resolve_userid(user.dingtalk_id)
            return [did] if as_list else did
        if user:
            return [user.name or ""] if as_list else (user.name or "")
    except Exception:
        pass
    return [] if as_list else ""


def oa_required_missing(wo: Any) -> list:
    """返回发起 OA 审批前缺失的必填字段中文名（与 OA 模板必填项一致）。

    无缺失返回空列表。用于「发起审批」前置拦截：缺失时阻止发起、让用户手动补齐，
    而不是在表单里塞默认值糊弄。
    """
    missing = []
    if not getattr(wo, "project_id", None):
        missing.append("项目")
    if not (getattr(wo, "source_code", None) or "").strip():
        missing.append("工单类型")
    if not getattr(wo, "person_id", None):
        missing.append("责任人")
    if not getattr(wo, "approver_id", None):
        missing.append("审批人")
    if not getattr(wo, "planned_start_date", None):
        missing.append("计划开始时间")
    if not getattr(wo, "deadline", None):
        missing.append("截止时间")
    if not (getattr(wo, "reason", None) or "").strip():
        missing.append("触发原因")
    if not (getattr(wo, "action", None) or "").strip():
        missing.append("行动要求")
    return missing


def plan_completeness_missing(wo: Any) -> list:
    """运营计划工单（工单类型 code=plan）进列表前的必填完整性校验。

    必填 = OA 发起必填（oa_required_missing）+ 「任务目标交付物」。其他类型不强制。
    返回缺失字段中文名列表，空列表表示完整。用于「导入建单门禁」与「月度自动派发前再校验」，
    缺项时不建单/不发起 OA（不塞默认值糊弄）。
    """
    missing = oa_required_missing(wo)
    if not (getattr(wo, "task_deliverable", None) or "").strip():
        missing.append("任务目标交付物")
    return missing


def query_oa_approval(process_instance_id: str, token: str | None = None) -> dict | None:
    """查询 OA 审批单状态（旧版 oapi 网关，与发起审批同网关同 token）。

    返回规范化的 process_instance 字典，关键字段：
      process_instance_id / title / status / result / form_component_values
    其中 status ∈ {NEW, RUNNING, TERMINATED, COMPLETED, CANCELED}；
          result ∈ {agree, refuse, redirect}。
    注意：不要用新网关 api.dingtalk.com/v1.0/workflow/processInstances ——
          那需要 OAuth2 accessToken，而本服务持有的是 oapi gettoken 的企业 token。
    """
    if not _configured() or not process_instance_id:
        return None
    token = token or get_access_token()
    if not token:
        return None
    try:
        resp = httpx.post(
            f"{_OAPI}/topapi/processinstance/get?access_token={token}",
            json={"process_instance_id": process_instance_id},
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"[dingtalk] query OA HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        data = resp.json()
        if data.get("errcode") != 0:
            print(f"[dingtalk] query OA failed: errcode={data.get('errcode')} msg={data.get('errmsg')}")
            return None
        return data.get("process_instance")
    except Exception as e:
        print(f"[dingtalk] query OA exception: {e}")
    return None


def work_notify_configured() -> bool:
    """工作通知是否就绪：有 AppKey/AppSecret + AgentId。"""
    return _configured() and bool(settings.dingtalk_agent_id)


def send_work_notification(user_id: str, title: str, content: str, action_url: str = "") -> bool:
    """发送工作通知（企业内部应用，进钉钉「工作通知」）。user_id 为钉钉 userId(staffId)。

    走旧 oapi 网关 topapi/message/corpconversation/asyncsend_v2，企业 access_token（与 OA 审批同网关同 token）。
    """
    if not work_notify_configured():
        print("[dingtalk] 工作通知未配置（缺 AppKey/Secret/AgentId），跳过")
        return False
    token = get_access_token()
    if not token:
        print("[dingtalk] 无 access_token，跳过工作通知")
        return False
    try:
        agent_id = int(settings.dingtalk_agent_id)
    except (TypeError, ValueError):
        print(f"[dingtalk] AgentId 非法（应为数字）：{settings.dingtalk_agent_id!r}")
        return False
    action_card = {
        "title": title,
        "markdown": f"## {title}\n\n{content}",
    }
    if action_url:
        action_card["btn_orientation"] = "0"
        action_card["btn_json_list"] = [{"title": "查看工单", "action_url": action_url}]
    msg = {"msgtype": "action_card", "action_card": action_card}
    try:
        resp = httpx.post(
            f"{_OAPI}/topapi/message/corpconversation/asyncsend_v2?access_token={token}",
            json={"agent_id": agent_id, "userid_list": user_id, "msg": msg},
            timeout=10,
        )
        data = resp.json()
        if data.get("errcode") == 0:
            return True
        print(f"[dingtalk] 工作通知发送失败: errcode={data.get('errcode')} msg={data.get('errmsg')}")
        return False
    except Exception as e:
        print(f"[dingtalk] work notify exception: {e}")
        return False


def send_group_markdown(text: str, title: str = "") -> bool:
    """企业内部机器人发群 markdown（合并多条工单链接用）。走新网关 groupMessages/send。

    robotCode + openConversationId + msgKey(sampleMarkdown) + msgParam(title/text)。
    成功返回 True（HTTP 200 且无 code 字段，响应带 processQueryKey）。
    """
    robot_code = settings.dingtalk_robot_code
    conv_id = settings.dingtalk_notify_group_id
    if not (robot_code and conv_id):
        print("[dingtalk] 群机器人未配置（缺 DINGTALK_ROBOT_CODE/notify_group_id），跳过")
        return False
    token = get_new_access_token()
    if not token:
        print("[dingtalk] 无 OAuth2 access_token，跳过群发")
        return False
    body = {
        "robotCode": robot_code,
        "openConversationId": conv_id,
        "msgKey": "sampleMarkdown",
        "msgParam": json.dumps({"title": title or "工单派发提醒", "text": text}, ensure_ascii=False),
    }
    try:
        resp = httpx.post(
            f"{_API}/v1.0/robot/groupMessages/send",
            headers={"x-acs-dingtalk-access-token": token, "Content-Type": "application/json"},
            json=body, timeout=10,
        )
        data = resp.json() if resp.status_code == 200 else {}
        if resp.status_code == 200 and not data.get("code"):
            return True
        print(f"[dingtalk] 群发失败: HTTP {resp.status_code} {data}")
        return False
    except Exception as e:
        print(f"[dingtalk] group notify exception: {e}")
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

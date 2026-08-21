"""鉴权 API：钉钉 OAuth 登录 + JWT"""
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, decode_token, verify_password
from app.core.security_middleware import limiter
from app.core.config import get_settings
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
security = HTTPBearer(auto_error=False)


# ── 钉钉 OAuth 登录 ──────────────────────────────────

@router.get("/dingtalk/url")
def get_dingtalk_login_url(redirect_path: str = "/"):
    """生成钉钉 OAuth 授权 URL"""
    if not settings.dingtalk_app_key:
        raise HTTPException(400, "未配置钉钉应用")
    params = {
        "redirect_uri": f"{settings.dingtalk_callback_url}?redirect_path={redirect_path}",
        "response_type": "code",
        "client_id": settings.dingtalk_app_key,
        "scope": "openid",
        "state": "login",
        "prompt": "consent",
    }
    return {"url": f"https://login.dingtalk.com/oauth2/auth?{urlencode(params)}"}


@router.get("/dingtalk/callback")
def dingtalk_callback(code: str = Query(...), redirect_path: str = Query("/"), db: Session = Depends(get_db)):
    """钉钉 OAuth 回调：用 code 换 token → 获取用户信息 → 签发 JWT"""
    if not settings.dingtalk_app_key:
        raise HTTPException(400, "未配置钉钉应用")

    # 1. 用 code 换 accessToken
    try:
        resp = httpx.post(
            "https://api.dingtalk.com/v1.0/oauth2/userAccessToken",
            json={
                "clientId": settings.dingtalk_app_key,
                "clientSecret": settings.dingtalk_app_secret,
                "code": code,
                "grantType": "authorization_code",
            },
            timeout=10,
        )
        resp.raise_for_status()
        token_data = resp.json()
        access_token = token_data.get("accessToken")
        union_id = token_data.get("unionId")
        if not access_token or not union_id:
            raise HTTPException(400, f"钉钉授权失败: {token_data}")
    except Exception as e:
        raise HTTPException(400, f"钉钉授权失败: {e}")

    # 2. 获取用户信息
    try:
        resp = httpx.get(
            f"https://api.dingtalk.com/v1.0/contact/users/me",
            headers={"x-acs-dingtalk-access-token": access_token},
            timeout=10,
        )
        resp.raise_for_status()
        user_info = resp.json()
        dingtalk_name = user_info.get("nick") or user_info.get("name") or ""
        dingtalk_mobile = user_info.get("mobile") or ""
    except Exception as e:
        raise HTTPException(400, f"获取用户信息失败: {e}")

    # 3. 查找或创建用户
    user = db.query(User).filter(User.dingtalk_id == union_id).first()
    if not user:
        # 新用户，默认 executor 角色
        user = User(
            name=dingtalk_name or f"钉钉用户_{union_id[:8]}",
            dingtalk_id=union_id,
            phone=dingtalk_mobile,
            role="executor",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # 更新用户信息
        if dingtalk_name and user.name != dingtalk_name:
            user.name = dingtalk_name
        if dingtalk_mobile and user.phone != dingtalk_mobile:
            user.phone = dingtalk_mobile
        db.commit()

    # 4. 签发 JWT
    token = create_access_token(
        str(user.id),
        extra={"name": user.name, "role": user.role, "dingtalk_id": union_id},
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "name": user.name, "role": user.role, "phone": user.phone},
        "redirect_path": redirect_path,
    }


# ── 获取当前用户 ──────────────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User | None:
    """从 JWT 中提取当前用户（可选鉴权，不强制）"""
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return db.get(User, int(user_id))


def require_auth(user: User | None = Depends(get_current_user)) -> User:
    """强制鉴权：未登录返回 401"""
    if not user:
        raise HTTPException(401, "请先登录")
    if not user.is_active:
        raise HTTPException(403, "用户已禁用")
    return user


def require_admin(user: User = Depends(require_auth)) -> User:
    """管理员权限"""
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


def require_approver(user: User = Depends(require_auth)) -> User:
    """审批人及以上权限"""
    if user.role not in ("admin", "approver"):
        raise HTTPException(403, "需要审批人及以上权限")
    return user


# ── 开发环境登录（跳过钉钉 OAuth）─────────────────────

from pydantic import BaseModel

class DevLoginBody(BaseModel):
    user_id: int
    name: str
    role: str


@router.post("/dev-login")
def dev_login(body: DevLoginBody, db: Session = Depends(get_db)):
    """开发环境：直接签发 token，不经过钉钉"""
    if settings.app_env == "production":
        raise HTTPException(403, "生产环境不允许开发登录")
    user = db.get(User, body.user_id)
    if not user:
        user = User(id=body.user_id, name=body.name, role=body.role, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    token = create_access_token(
        str(user.id),
        extra={"name": user.name, "role": user.role},
    )
    return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "name": user.name, "role": user.role}}

@router.get("/me")
def get_me(user: User = Depends(require_auth)):
    return {"id": user.id, "name": user.name, "role": user.role, "phone": user.phone, "dingtalk_id": user.dingtalk_id}


# ── 权限配置（前端可配置）─────────────────────────────

@router.get("/permissions")
def get_permissions():
    """返回角色权限映射表，前端据此过滤菜单和功能"""
    return {
        "roles": ["admin", "approver", "executor", "readonly"],
        "menu_groups": {
            "工作台": {
                "管理看板": {"roles": ["admin", "approver"]},
                "我的工单": {"roles": ["admin", "approver", "executor"]},
            },
            "工单管理": {
                "工单列表": {"roles": ["admin", "approver"]},
                "新建工单": {"roles": ["admin", "approver"]},
                "闭环记录": {"roles": ["admin", "approver", "executor"]},
            },
            "基础数据": {
                "项目管理": {"roles": ["admin", "approver"]},
                "用户管理": {"roles": ["admin"]},
                "数据池": {"roles": ["admin", "approver"]},
                "SOP知识库": {"roles": ["admin", "approver", "executor"]},
            },
            "系统设置": {
                "规则配置": {"roles": ["admin"]},
                "操作日志": {"roles": ["admin"]},
                "钉钉集成": {"roles": ["admin", "approver"]},
            },
        },
        "actions": {
            "create_wo": {"roles": ["admin", "approver"]},
            "import_excel": {"roles": ["admin", "approver"]},
            "generate_wo": {"roles": ["admin", "approver"]},
            "backfill_wo": {"roles": ["admin", "approver", "executor"]},
            "close_wo": {"roles": ["admin", "approver"]},
            "manage_users": {"roles": ["admin"]},
            "pool_import": {"roles": ["admin", "approver"]},
        },
    }


# ── 用户管理（管理员）─────────────────────────────────

class UpdateRoleBody(BaseModel):
    role: str


@router.get("/users")
def list_users(page: int = 1, page_size: int = 50, db: Session = Depends(get_db), _: User = Depends(require_auth)):
    users = db.query(User).order_by(User.role, User.name).offset((page-1)*page_size).limit(page_size).all()
    total = db.query(User).count()
    return {
        "items": [{"id": u.id, "name": u.name, "role": u.role, "phone": u.phone,
                    "dingtalk_id": u.dingtalk_id, "is_active": u.is_active} for u in users],
        "total": total, "page": page, "page_size": page_size,
    }


@router.patch("/users/{user_id}/role")
def update_user_role(user_id: int, body: UpdateRoleBody, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if body.role not in ("admin", "approver", "executor", "readonly"):
        raise HTTPException(400, "无效角色")
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    u.role = body.role
    db.commit()
    return {"id": u.id, "name": u.name, "role": u.role}


@router.patch("/users/{user_id}/toggle-active")
def toggle_user_active(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    u.is_active = not u.is_active
    db.commit()
    return {"id": u.id, "name": u.name, "is_active": u.is_active}

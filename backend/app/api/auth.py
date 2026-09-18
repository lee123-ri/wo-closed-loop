"""鉴权 API：钉钉 OAuth 登录 + JWT"""
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, decode_token
from app.core.security_middleware import limiter
from app.core.config import get_settings
from app.models import BusinessRole, BusinessRoleAssignment, ConfigDefinition, User

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
security = HTTPBearer(auto_error=False)


# ── 钉钉 OAuth 登录 ──────────────────────────────────
# 流程：前端跳 login.dingtalk.com/oauth2/auth → 用户授权 → 钉钉回跳前端登录页
# （settings.dingtalk_login_redirect_uri，带 authCode）→ 前端拿 code 调本回调换 JWT。
# 登录策略：不自动建号；仅匹配已有启用用户；login_admin_only=True 时仅管理员可登录。

@router.get("/dingtalk/url")
def get_dingtalk_login_url(redirect_path: str = "/"):
    """生成钉钉 OAuth 授权 URL"""
    if not settings.dingtalk_app_key:
        raise HTTPException(400, "未配置钉钉应用")
    params = {
        # redirect_uri 必须与钉钉后台登记的 URL 逐字符一致，故不带查询串；回跳去向走 state 带回
        "redirect_uri": settings.dingtalk_login_redirect_uri,
        "response_type": "code",
        "client_id": settings.dingtalk_app_key,
        "scope": "openid",
        "state": redirect_path,
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
        if not access_token:
            raise HTTPException(400, f"钉钉授权失败: {token_data}")
    except Exception as e:
        raise HTTPException(400, f"钉钉授权失败: {e}")

    # 2. 获取用户信息（unionId 只在这个接口返回，换 token 接口不给）
    try:
        resp = httpx.get(
            "https://api.dingtalk.com/v1.0/contact/users/me",
            headers={"x-acs-dingtalk-access-token": access_token},
            timeout=10,
        )
        resp.raise_for_status()
        user_info = resp.json()
        union_id = user_info.get("unionId") or ""
        dingtalk_name = user_info.get("nick") or user_info.get("name") or ""
        dingtalk_mobile = user_info.get("mobile") or ""
        if not union_id:
            raise HTTPException(400, f"用户信息缺 unionId: {user_info}")
    except Exception as e:
        raise HTTPException(400, f"获取用户信息失败: {e}")

    # 3. 查找用户：不自动建号。已绑定的按钉钉 ID 查（union_id 或 userId）；未绑定的首次登录按姓名/手机号匹配。
    from app.services.dingtalk import resolve_userid
    dingtalk_userid = resolve_userid(union_id)
    user = db.query(User).filter(User.dingtalk_id == union_id).first()
    if not user and dingtalk_userid != union_id:
        user = db.query(User).filter(User.dingtalk_id == dingtalk_userid).first()
    if not user:
        conds = [User.is_active.is_(True)]
        or_conds = []
        if dingtalk_name:
            or_conds.append(User.name == dingtalk_name)
        if dingtalk_mobile:
            or_conds.append(User.phone == dingtalk_mobile)
        if or_conds:
            user = db.query(User).filter(or_(*or_conds), *conds).first()
        if not user:
            raise HTTPException(403, "未授权用户：本平台仅对已登记人员开放")
        # 首次登录绑定钉钉身份（存 userId 而非 union_id，OA 发起审批只认 userId）
        user.dingtalk_id = dingtalk_userid or union_id
        if dingtalk_mobile and not user.phone:
            user.phone = dingtalk_mobile
        db.commit()
    elif user.dingtalk_id == union_id and dingtalk_userid != union_id:
        # 库里的 dingtalk_id 是历史 union_id（会致 OA 发起审批 820003），就地修正为 userId
        user.dingtalk_id = dingtalk_userid
        db.commit()

    if not user.is_active:
        raise HTTPException(403, "用户已禁用")
    if settings.login_admin_only and user.role != "admin":
        raise HTTPException(403, "当前仅管理员可登录本平台")

    # 4. 签发 JWT
    token = create_access_token(
        str(user.id),
        extra={"name": user.name, "role": user.role, "dingtalk_id": dingtalk_userid or union_id},
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


def require_bulk_import_owner(user: User = Depends(require_auth)) -> User:
    """历史批量导入是运维后门：仅允许配置的单一钉钉身份。"""
    owner_id = settings.bulk_import_owner_dingtalk_id.strip()
    if not owner_id or user.dingtalk_id != owner_id:
        raise HTTPException(403, "历史批量导入仅对指定运维账号开放")
    return user


def require_approver(user: User = Depends(require_auth)) -> User:
    """审批人及以上权限"""
    if user.role not in ("admin", "approver"):
        raise HTTPException(403, "需要审批人及以上权限")
    return user


# ── 开发环境登录（跳过钉钉 OAuth）─────────────────────

from pydantic import BaseModel, Field

class DevLoginBody(BaseModel):
    user_id: int
    name: str
    role: str


# ── 姓名登录（钉钉 OAuth 之外的简化入口）─────────────
# 注意：姓名登录无口令校验，属内网信任模式；公网暴露时请以钉钉 OAuth 为主入口。

class NameLoginBody(BaseModel):
    name: str


@router.post("/name")
@limiter.limit("30/minute")
def name_login(request: Request, body: NameLoginBody, db: Session = Depends(get_db)):
    """输入姓名登录：默认关闭（无口令信任模式）；仅 name_login_enabled=True 时可用。"""
    if not settings.name_login_enabled:
        raise HTTPException(403, "姓名登录已停用，请使用钉钉账号登录")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "请输入姓名")
    candidates = db.query(User).filter(User.name == name, User.is_active.is_(True)).all()
    if len(candidates) > 1:
        raise HTTPException(409, "存在同名用户，请联系管理员处理")
    if not candidates:
        raise HTTPException(401, "未找到该用户，请核对姓名")
    user = candidates[0]
    token = create_access_token(
        str(user.id),
        extra={"name": user.name, "role": user.role},
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "name": user.name, "role": user.role, "phone": user.phone},
    }


@router.post("/dev-login")
def dev_login(body: DevLoginBody, db: Session = Depends(get_db)):
    """开发环境：直接签发 token，不经过钉钉。默认关闭；生产环境恒关。"""
    if settings.is_prod or not settings.dev_login_enabled:
        raise HTTPException(403, "开发登录未开放")
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


# ── 系统身份 × 菜单权限（可持久化）─────────────────────

# “只读”是菜单权限级别，不是用户身份。用户只保留三类系统身份；每个菜单项
# 按身份配置无权限 / 只读 / 读写。admin 仍保留服务端兜底权限，避免误配锁死系统。
SYSTEM_ROLES = ("admin", "approver", "executor")
MENU_ACCESS_LEVELS = frozenset(("none", "read", "write"))
DEFAULT_PERMISSIONS = {
    "roles": list(SYSTEM_ROLES),
    "menu_groups": {
        "工作台": {
            "管理看板": {"access": {"admin": "write", "approver": "read", "executor": "none"}},
            "我的工单": {"access": {"admin": "write", "approver": "write", "executor": "write"}},
        },
        "工单管理": {
            "工单列表": {"access": {"admin": "write", "approver": "write", "executor": "none"}},
            "新建工单": {"access": {"admin": "write", "approver": "write", "executor": "none"}},
            "闭环记录": {"access": {"admin": "write", "approver": "write", "executor": "write"}},
        },
        "基础数据": {
            "项目管理": {"access": {"admin": "write", "approver": "read", "executor": "none"}},
            "用户管理": {"access": {"admin": "write", "approver": "none", "executor": "none"}},
            "数据池": {"access": {"admin": "write", "approver": "write", "executor": "none"}},
            "SOP知识库": {"access": {"admin": "write", "approver": "read", "executor": "read"}},
        },
        "系统设置": {
            "规则配置": {"access": {"admin": "write", "approver": "none", "executor": "none"}},
            "操作日志": {"access": {"admin": "read", "approver": "none", "executor": "none"}},
            "钉钉集成": {"access": {"admin": "write", "approver": "read", "executor": "none"}},
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


def _normalise_menu_permission(conf: object) -> dict:
    """将旧 roles 数组平滑转换成当前的 access 映射。"""
    raw = conf if isinstance(conf, dict) else {}
    raw_access = raw.get("access") if isinstance(raw.get("access"), dict) else None
    if raw_access is None:
        # 历史配置只有“能否看见”；迁移后保守地视为只读，管理员始终可写。
        legacy_roles = set(raw.get("roles") or []) if isinstance(raw.get("roles"), list) else set()
        raw_access = {role: ("write" if role == "admin" else "read") if role in legacy_roles else "none" for role in SYSTEM_ROLES}
    return {"access": {role: raw_access.get(role, "none") if raw_access.get(role) in MENU_ACCESS_LEVELS else "none" for role in SYSTEM_ROLES}}


def _permissions_from_row(row: ConfigDefinition | None) -> dict:
    """还原系统身份到菜单权限，并兼容旧 roles 数组。"""
    extra = (row.extra or {}) if row else {}
    menu_groups = {group: {title: _normalise_menu_permission(conf) for title, conf in items.items()}
                   for group, items in DEFAULT_PERMISSIONS["menu_groups"].items()}
    for group, items in (extra.get("menu_groups") or {}).items():
        if isinstance(items, dict):
            target = menu_groups.setdefault(group, {})
            for title, conf in items.items():
                target[title] = _normalise_menu_permission(conf)
    actions = {name: dict(conf) for name, conf in DEFAULT_PERMISSIONS["actions"].items()}
    if isinstance(extra.get("actions"), dict):
        actions.update(extra["actions"])
    return {
        "roles": list(DEFAULT_PERMISSIONS["roles"]),
        "menu_groups": menu_groups,
        "actions": actions,
    }


def _permissions_row(db: Session) -> ConfigDefinition | None:
    return (
        db.query(ConfigDefinition)
        .filter(ConfigDefinition.category == "permission", ConfigDefinition.code == "menu")
        .first()
    )


@router.get("/permissions")
def get_permissions(db: Session = Depends(get_db)):
    """返回角色权限映射表，前端据此过滤菜单和功能"""
    return _permissions_from_row(_permissions_row(db))


class PermissionsBody(BaseModel):
    menu_groups: dict
    actions: dict | None = None


@router.put("/permissions")
def update_permissions(body: PermissionsBody, db: Session = Depends(get_db),
                       user: User = Depends(require_admin)):
    """保存每个系统身份对每个菜单项的无权限/只读/读写级别。"""
    for gname, items in (body.menu_groups or {}).items():
        if not isinstance(items, dict):
            raise HTTPException(400, f"菜单权限格式错误：{gname}")
        for title, conf in items.items():
            access = conf.get("access") if isinstance(conf, dict) else None
            if not isinstance(access, dict) or set(access) - set(SYSTEM_ROLES) or any(level not in MENU_ACCESS_LEVELS for level in access.values()):
                raise HTTPException(400, f"无效菜单权限：{gname} / {title}")

    row = _permissions_row(db)
    actions = body.actions if body.actions is not None else _permissions_from_row(row)["actions"]
    extra = {
        "menu_groups": {
            group: {title: _normalise_menu_permission(conf) for title, conf in items.items()}
            for group, items in body.menu_groups.items()
        },
        "actions": actions,
    }
    if row is None:
        row = ConfigDefinition(category="permission", code="menu", name="菜单权限配置", extra=extra)
        db.add(row)
    else:
        row.extra = extra
    db.flush()
    from app.services.audit import log_audit
    log_audit(db, actor_id=user.id, action="update_permissions", target_type="config",
              target_id=row.id, detail={"groups": sorted(body.menu_groups.keys())})
    db.commit()
    return _permissions_from_row(row)


# ── 用户管理（管理员）─────────────────────────────────

class UpdateRoleBody(BaseModel):
    role: str


class UpdateUserProfileBody(BaseModel):
    """管理员在本平台维护的组织资料；钉钉 ID 保持为外部同步事实。"""
    department: str | None = Field(default=None, max_length=128)


class UpdateBusinessRolesBody(BaseModel):
    """整体覆盖用户的业务岗位，避免前端维护多条分配记录。"""
    role_codes: list[str] = Field(default_factory=list, max_length=20)


def _business_roles_for_users(db: Session, user_ids: list[int]) -> dict[int, list[dict]]:
    """用户列表的内部实现：一次查询聚合业务岗位，调用方无需处理分配表。"""
    result = {user_id: [] for user_id in user_ids}
    if not user_ids:
        return result
    rows = (
        db.query(BusinessRoleAssignment, BusinessRole)
        .join(BusinessRole, BusinessRole.id == BusinessRoleAssignment.business_role_id)
        .filter(BusinessRoleAssignment.user_id.in_(user_ids))
        .order_by(BusinessRole.name)
        .all()
    )
    for assignment, role in rows:
        result[assignment.user_id].append({"code": role.code, "name": role.name})
    return result


def _user_out(user: User, business_roles: list[dict]) -> dict:
    # 不把“无岗位”留成数据权限空洞：默认项目人员，只看本人相关工单。
    if not business_roles:
        business_roles = [{"code": "project_member", "name": "项目人员", "is_default": True}]
    return {
        "id": user.id, "name": user.name, "role": user.role, "phone": user.phone,
        "dingtalk_id": user.dingtalk_id, "department": user.department,
        "department_id": user.department_id, "is_active": user.is_active,
        "business_roles": business_roles,
    }


@router.get("/users")
def list_users(page: int = 1, page_size: int = 50, q: str | None = None,
               db: Session = Depends(get_db), _: User = Depends(require_auth)):
    query = db.query(User)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(User.name.ilike(like), User.dingtalk_id.ilike(like)))
    total = query.count()
    users = query.order_by(User.role, User.name).offset((page-1)*page_size).limit(page_size).all()
    roles_by_user = _business_roles_for_users(db, [u.id for u in users])
    return {
        "items": [_user_out(u, roles_by_user[u.id]) for u in users],
        "total": total, "page": page, "page_size": page_size,
    }


@router.patch("/users/{user_id}/role")
def update_user_role(user_id: int, body: UpdateRoleBody, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if body.role not in SYSTEM_ROLES:
        raise HTTPException(400, "无效角色")
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    old_role = u.role
    u.role = body.role
    from app.services.audit import log_audit
    log_audit(db, actor_id=user.id, action="update_role", target_type="user", target_id=u.id,
              detail={"name": u.name, "from": old_role, "to": body.role})
    db.commit()
    return {"id": u.id, "name": u.name, "role": u.role}


@router.patch("/users/{user_id}/profile")
def update_user_profile(user_id: int, body: UpdateUserProfileBody, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """部门先由钉钉带入；管理员可根据实际组织归属修正显示和业务分配。"""
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    department = body.department.strip() if body.department else None
    old_department = u.department
    u.department = department
    from app.services.audit import log_audit
    log_audit(db, actor_id=actor.id, action="update_user_department", target_type="user", target_id=u.id,
              detail={"name": u.name, "from": old_department, "to": department})
    db.commit()
    return _user_out(u, _business_roles_for_users(db, [u.id])[u.id])


@router.get("/business-roles")
def list_business_roles(db: Session = Depends(get_db), _: User = Depends(require_auth)):
    """返回业务岗位选项；权限角色与菜单权限不在此处重复配置。"""
    return [
        {"code": row.code, "name": row.name, "is_active": row.is_active, "is_system": row.is_system}
        for row in db.query(BusinessRole).order_by(BusinessRole.name).all()
    ]


@router.put("/users/{user_id}/business-roles")
def replace_user_business_roles(user_id: int, body: UpdateBusinessRolesBody, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """以岗位编码数组整体覆盖，隐藏分配记录、项目群候选等历史复杂度。"""
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    role_codes = list(dict.fromkeys(body.role_codes))
    roles = db.query(BusinessRole).filter(BusinessRole.code.in_(role_codes), BusinessRole.is_active.is_(True)).all() if role_codes else []
    found = {role.code for role in roles}
    missing = [code for code in role_codes if code not in found]
    if missing:
        raise HTTPException(400, f"业务岗位不存在或已停用：{', '.join(missing)}")
    db.query(BusinessRoleAssignment).filter(BusinessRoleAssignment.user_id == u.id).delete(synchronize_session=False)
    for role in roles:
        db.add(BusinessRoleAssignment(user_id=u.id, business_role_id=role.id, scope_type="global", source="manual", is_confirmed=True))
    from app.services.audit import log_audit
    log_audit(db, actor_id=actor.id, action="replace_business_roles", target_type="user", target_id=u.id,
              detail={"name": u.name, "role_codes": role_codes})
    db.commit()
    return _user_out(u, _business_roles_for_users(db, [u.id])[u.id])


@router.patch("/users/{user_id}/toggle-active")
def toggle_user_active(user_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    u.is_active = not u.is_active
    from app.services.audit import log_audit
    log_audit(db, actor_id=user.id, action="toggle_active", target_type="user", target_id=u.id,
              detail={"name": u.name, "is_active": u.is_active})
    db.commit()
    return {"id": u.id, "name": u.name, "is_active": u.is_active}

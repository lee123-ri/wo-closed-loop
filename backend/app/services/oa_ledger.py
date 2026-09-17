# -*- coding: utf-8 -*-
"""公司 OA（泛微 oa.xh-service.com）运维「项目台账」抓取 —— Playwright 浏览器登录 + 表格提取。

取数方式对齐 annual-ops-plan 项目的 oa_login / oa_fetch（同一套 OA 网页台账）：
  1. 账号密码登录统一认证平台（默认短信登录 → 切「密码登录」→ 填表 → 点登录 → 等跳转）
  2. 打开运维项目台账搜索页 customid=97，逐页读取表格
  3. 按「项目状态 ∈ 执行中/待执行」过滤「项目简称」，upsert 进本地 projects 表

凭据与地址走 env：
  OA_BASE_URL（默认 https://oa.xh-service.com）
  OA_USERNAME / OA_PASSWORD（沿用年度运营计划机器人的 OA 账号）
  PROJECT_LEDGER_CUSTOMID（默认 97）
  PROJECT_LEDGER_ACTIVE_STATUSES（默认 执行中,待执行，逗号分隔）
  PROJECT_LEDGER_MAX_PAGES（默认 100）

Playwright 为可选依赖：未装 / 未配凭据时返回明确 error，不静默吞、不抛异常，
好让项目管理页「从 OA 同步项目」按钮给出可读反馈。
"""
from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Project
from app.services.region_map import normalize_region
from app.services.project_names import clean_project_name

# 凭据/地址/口径统一从 Settings（.env → pydantic-settings）读，勿直接用 os.environ
# ——pydantic-settings 不会把 .env 写回 os.environ，读 os.environ 会恒空。
_settings = get_settings()
OA_BASE_URL = _settings.oa_base_url.rstrip("/")
LEDGER_CUSTOMID = _settings.project_ledger_customid
# 台账状态列里要收录的取值（用户拍板：执行中 / 待执行）
ACTIVE_STATUSES = [
    s.strip()
    for s in _settings.project_ledger_active_statuses.split(",")
    if s.strip()
]
MAX_PAGES = int(_settings.project_ledger_max_pages or 100)

_PLAYWRIGHT_AVAILABLE = False
_PLAYWRIGHTS: dict[int, Any] = {}
try:
    from playwright.sync_api import sync_playwright  # type: ignore
    _PLAYWRIGHT_AVAILABLE = True
except Exception:  # ImportError 等，Playwright 未装
    _PLAYWRIGHT_AVAILABLE = False


def _creds() -> tuple[str, str]:
    return _settings.oa_username.strip(), _settings.oa_password.strip()


# ============================================================================
# 登录（对齐 annual-ops-plan oa_login.login_oa）
# ============================================================================

def _login():
    """返回已登录 BrowserContext；不可用/失败返回 None，并把原因写进 _LOGIN_ERR。"""
    global _LOGIN_ERR
    if not _PLAYWRIGHT_AVAILABLE:
        _LOGIN_ERR = "Playwright 未安装（pip install playwright && playwright install chromium）"
        return None
    username, password = _creds()
    if not username or not password:
        _LOGIN_ERR = "未配置 OA 账号密码（OA_USERNAME / OA_PASSWORD）"
        return None

    pw = None
    browser = None
    context = None
    try:
        pw = sync_playwright().start()
        launch_options: dict[str, Any] = {
            "headless": True,
            "args": ["--no-sandbox", "--disable-setuid-sandbox"],
        }
        chromium_path = os.environ.get("CHROMIUM_EXECUTABLE_PATH", "")
        if chromium_path and os.path.isfile(chromium_path):
            launch_options["executable_path"] = chromium_path

        browser = pw.chromium.launch(**launch_options)
        context = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
        page = context.new_page()

        page.goto(f"{OA_BASE_URL}/login/Login.jsp", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)

        # 统一认证默认短信登录 → 切密码登录
        _activate_password_login(page)
        _fill_login_form(page, username, password)
        _click_login_button(page)

        # 等统一认证 → CAS → OA 首页跳转
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            body = ""
            try:
                body = page.locator("body").inner_text(timeout=1500)
            except Exception:
                pass
            if any(m in body for m in ("用户名或密码错误", "账号或密码错误", "登录名或密码错误", "密码输入错误", "认证失败", "账号已锁定")):
                raise RuntimeError("OA 账号或密码错误")
            if _is_logged_in(page):
                _LOGIN_ERR = ""
                _PLAYWRIGHTS[id(context)] = pw
                return context
            page.wait_for_timeout(500)
        raise RuntimeError(f"OA 登录跳转超时，最后页面: {page.url[:200]}")
    except Exception as e:
        _LOGIN_ERR = f"OA 登录失败: {e}"
        for obj in (context, browser):
            try:
                obj.close()
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass
        return None


_LOGIN_ERR = ""


def _close(ctx) -> None:
    if ctx is None:
        return
    browser = ctx.browser
    pw = _PLAYWRIGHTS.pop(id(ctx), None)
    try:
        ctx.close()
    except Exception:
        pass
    try:
        browser.close()
    except Exception:
        pass
    if pw is not None:
        try:
            pw.stop()
        except Exception:
            pass


def _is_logged_in(page) -> bool:
    current = urlparse(page.url)
    expected = urlparse(OA_BASE_URL)
    if current.hostname != expected.hostname:
        return False
    path = current.path.lower()
    if "/login" in path or path.endswith("/login.jsp"):
        return False
    if path.startswith("/wui/"):
        return True
    try:
        title = page.title()
    except Exception:
        return False
    return bool(title) and "登录" not in title and "不存在" not in title


def _activate_password_login(page) -> None:
    """默认短信登录，切到账号密码模式；以真实可编辑密码框为准。"""
    selectors = ['text="密码登录"', 'button:has-text("密码登录")', 'a:has-text("密码登录")', '.el-tabs__item:has-text("密码登录")']
    for _ in range(20):
        try:
            pwd = page.locator('input[type="password"]:visible').first
            if pwd.is_visible(timeout=100) and pwd.is_editable(timeout=100):
                return
        except Exception:
            pass
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=100):
                    loc.click()
                    page.wait_for_timeout(350)
                    return
            except Exception:
                continue
        page.wait_for_timeout(350)
    raise RuntimeError("未找到 OA 密码登录入口")


def _fill_login_form(page, username: str, password: str) -> None:
    username_selectors = [
        'input[placeholder*="用户名/邮箱"]', 'input[placeholder*="用户名"]',
        'input[placeholder*="账号"]', 'input[placeholder*="工号"]',
        'input[name="username"]', 'input[name="user"]', 'input[name="loginname"]',
        'input[name="account"]', 'input[placeholder*="手机"]', 'input[type="text"]:not([readonly])',
    ]
    password_selectors = [
        'input[name="password"]', 'input[name="passwd"]', 'input[name="pwd"]',
        'input[type="password"]', 'input[placeholder*="密码"]',
    ]
    filled = False
    for sel in username_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000) and el.is_editable(timeout=2000):
                el.fill(username)
                filled = True
                break
        except Exception:
            continue
    if not filled:
        raise RuntimeError("未找到可编辑的 OA 用户名输入框")
    for sel in password_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000) and el.is_editable(timeout=2000):
                el.fill(password)
                return
        except Exception:
            continue
    raise RuntimeError("未找到可编辑的 OA 密码输入框")


def _click_login_button(page) -> None:
    selectors = [
        'button[type="submit"]', 'input[type="submit"]', 'button:has-text("登录")',
        'button:has-text("登 录")', 'button:has-text("Sign in")', 'a:has-text("登录")',
        '.login-btn', '#loginBtn',
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000) and el.is_enabled(timeout=2000):
                el.click()
                return
        except Exception:
            continue
    page.keyboard.press("Enter")


# ============================================================================
# 台账抓取（对齐 annual-ops-plan oa_fetch._search_in_ledger）
# ============================================================================

def _ledger_url(customid: str) -> str:
    return f"{OA_BASE_URL}/spa/cube/index.html#/main/cube/search?customid={customid}"


def _fetch_ledger(ctx, customid: str, max_pages: int):
    """打开台账搜索页（不搜关键词=全部记录），逐页读取表头+行。返回 (headers, rows)。

    泛微 cube 表格翻页是**异步渲染**：点「下一页」后 activePage 立刻变，但表格内容要等
    后端数据回来才换。所以不能固定 sleep 后读——必须轮询等「内容真的变了」再读；点了下一页
    而内容不再变化（末页/无新页）即停，避免超读重读尾页，也避免把加载中的中间态误判成末页。
    """
    page = ctx.new_page()
    try:
        page.goto(_ledger_url(customid), wait_until="networkidle", timeout=60000)

        headers: list = []
        all_rows: list = []
        prev_sig: str | None = None
        complete = False  # 是否在「内容不再变化/末页」处干净停下（而非翻满 max_pages 被截断）
        for _pageno in range(1, max_pages + 1):
            # 首页等出现非空行；翻页后等内容与上一页不同（异步渲染，轮询而非固定 sleep）
            rows, hs = _wait_for_content(page, prev_sig)
            if hs:
                headers = hs
            if not rows:
                complete = True
                break
            sig = repr(rows)
            if sig == prev_sig:
                complete = True
                break  # 点了「下一页」但内容没再变 → 已到末页
            prev_sig = sig
            all_rows.extend(rows)
            _goto_next_page(page)  # 点下一页；是否真翻过去由下一轮 _wait_for_content 判定
        return headers, all_rows, complete
    finally:
        try:
            page.close()
        except Exception:
            pass


def _wait_for_content(page, prev_sig, timeout_s: float = 15.0):
    """轮询等表格内容就位：首页(prev_sig=None)等出现非空行；翻页后等内容与 prev_sig 不同。

    超时仍无变化则返回当前读到的行——调用方据 sig 是否变化判定是否末页。
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        rows, hs = _rows_and_headers(page)
        if rows and (prev_sig is None or repr(rows) != prev_sig):
            return rows, hs
        page.wait_for_timeout(400)
    rows, hs = _rows_and_headers(page)
    return rows, hs


def _rows_and_headers(page):
    """优先按 ant-design 表格选择器，退化为通用 table 选择器。"""
    data = page.evaluate(
        """() => {
            const ths = Array.from(document.querySelectorAll('.ant-table-thead th')).map(c => c.innerText.trim());
            const rows = Array.from(document.querySelectorAll('.ant-table-tbody tr.ant-table-row'))
                .map(r => Array.from(r.querySelectorAll('td')).map(c => c.innerText.trim()));
            return { headers: ths, rows: rows };
        }"""
    )
    if data.get("rows"):
        return data.get("rows", []), data.get("headers", [])
    # 通用 table 兜底
    tables = page.evaluate(
        """() => Array.from(document.querySelectorAll('table')).map(t => ({
            headers: Array.from(t.querySelectorAll('thead th')).map(c => c.innerText.trim()),
            rows: Array.from(t.querySelectorAll('tbody tr')).map(r =>
                Array.from(r.querySelectorAll('td')).map(c => c.innerText.trim()))
        }))"""
    )
    for t in tables:
        if t.get("rows"):
            return t.get("rows", []), t.get("headers", [])
    return [], []


def _goto_next_page(page) -> bool:
    try:
        return bool(page.evaluate(
            """() => {
                const el = document.querySelector('.ant-pagination-next:not(.ant-pagination-disabled) a')
                        || document.querySelector('.ant-pagination-next:not(.ant-pagination-disabled) button');
                if (el) { el.click(); return true; }
                return false;
            }"""
        ))
    except Exception:
        return False


def _row_to_dict(row: list, headers: list) -> dict:
    return {headers[i]: row[i] for i in range(min(len(headers), len(row))) if headers[i]}


def _find_cell(row: dict, *keys: str) -> str:
    """按表头名含关键词取单元格（优先精确包含）。"""
    for key in keys:
        for k, v in row.items():
            if key in k and v:
                return str(v).strip()
    return ""


def _clean_name(name: str) -> str:
    """项目名清洗：口径统一走 app.services.project_names.clean_project_name（单一来源，防漂移）。"""
    return clean_project_name(name)


# ============================================================================
# 同步入口
# ============================================================================

def sync_project_ledger() -> dict:
    """登录 OA → 抓运维项目台账(customid=97) → 以 OA 台账为准同步 projects。

    口径（用户拍板 2026-09-10）：
    - 只收「项目状态 ∈ 执行中/待执行」且名称是中文场站名（纯字母/数字=脏数据，过滤）的项目；
    - 按名称幂等 upsert（已存在回填区域/启用，不重复建）；
    - 同步末尾把**不在名单里的既有项目停用**（is_active=False，非删除、可逆），
      让项目列表/下拉 = OA 台账口径；工单仍引用这些 project_id、不受影响。
    - 防误停用：本批没筛出任何有效项目（抓空/失败/全被过滤）时不碰存量，只回传 error。
    """
    if not _PLAYWRIGHT_AVAILABLE:
        return {"ok": False, "synced": 0, "updated": 0, "skipped": 0, "disabled": 0, "total": 0,
                "active_statuses": ACTIVE_STATUSES,
                "errors": ["Playwright 未安装（pip install playwright && playwright install chromium）"]}
    u, p = _creds()
    if not u or not p:
        return {"ok": False, "synced": 0, "updated": 0, "skipped": 0, "disabled": 0, "total": 0,
                "active_statuses": ACTIVE_STATUSES,
                "errors": ["未配置 OA 账号密码（OA_USERNAME / OA_PASSWORD）"]}

    ctx = _login()
    if ctx is None:
        return {"ok": False, "synced": 0, "updated": 0, "skipped": 0, "disabled": 0, "total": 0,
                "active_statuses": ACTIVE_STATUSES, "errors": [_LOGIN_ERR]}

    try:
        headers, rows, complete = _fetch_ledger(ctx, LEDGER_CUSTOMID, MAX_PAGES)
    except Exception as e:
        return {"ok": False, "synced": 0, "updated": 0, "skipped": 0, "disabled": 0, "total": 0,
                "active_statuses": ACTIVE_STATUSES, "errors": [f"OA 台账抓取失败: {e}"]}
    finally:
        _close(ctx)

    from app.services.project_codes import next_project_code
    db = SessionLocal()
    synced = skipped = updated = disabled = 0
    errors: list = []
    seen_names: set = set()
    try:
        for row in rows:
            d = _row_to_dict(row, headers)
            raw_name = _find_cell(d, "项目简称", "项目名称")
            status = _find_cell(d, "项目状态", "状态")
            region = normalize_region(_find_cell(d, "交付单元", "区域"))
            name = _clean_name(raw_name)
            if len(name) < 2:
                # 清洗后不足 2 个中文字：纯字母/数字/编号的脏数据，跳过不进项目表
                skipped += 1
                continue
            if status not in ACTIVE_STATUSES:
                skipped += 1
                continue
            if name in seen_names:
                skipped += 1
                continue
            seen_names.add(name)
            existing = db.query(Project).filter(Project.name == name).first()
            if existing:
                if region and existing.region != region:
                    existing.region = region
                    updated += 1
                if not existing.is_active:
                    existing.is_active = True
                    updated += 1
                continue
            db.add(Project(code=next_project_code(db), name=name, region=region))
            db.flush()
            synced += 1

        # 以 OA 台账为准：停用不在「执行中/待执行」名单里的既有项目。
        # 双保险防误停用：① 真的筛出了有效名单 ② 抓取「干净读完」（内容不再变化=末页），
        # 而非翻满 max_pages 被截断——否则宁可不动存量、只报 error。
        if seen_names and complete:
            for proj in db.query(Project).filter(Project.is_active.is_(True)).all():
                if proj.name not in seen_names:
                    proj.is_active = False
                    disabled += 1
        elif not seen_names:
            errors.append(
                f"从 {len(rows)} 行台账中未筛出任何有效「执行中/待执行」项目，未动存量（可能状态/名称列名不符）"
            )
        else:
            errors.append(
                f"台账抓取可能未读完（翻到 max_pages={MAX_PAGES} 仍被截断），已跳过停用、未动存量，请调大 PROJECT_LEDGER_MAX_PAGES 后重试"
            )
        db.commit()
    except Exception as e:
        db.rollback()
        errors.append(str(e))
    finally:
        db.close()
    return {"ok": True, "synced": synced, "updated": updated, "skipped": skipped,
            "disabled": disabled, "total": len(rows), "active_statuses": ACTIVE_STATUSES,
            "errors": errors}
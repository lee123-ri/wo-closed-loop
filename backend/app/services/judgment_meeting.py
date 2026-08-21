"""试运营判定会自动建会服务。

对齐贾总版《试运营判定会议自动创建》机制：
- 项目录入入场日期 + 产品系列 → 计算判定日 → D1 即创建钉钉日历日程
- 参会人：固定 金惠良/刘冰/贾兴威 + 动态 项目负责人/区域PMO/区域生产副总
- 日程：判定日 10:00-11:00，富文本议程 + 一页纸SOP（判定会议模板）
- 判定日前 1 天（D-1）向区域群发提醒

调用方式与 aitable 同步一致：subprocess 调 `dws` CLI（用户 Token 已认证）。
"""
import json
import subprocess
from datetime import date, datetime, timedelta
from typing import Any

# ── 常量（对齐贾总版 skill 配置）────────────────────────
# Aitable 项目清单表 hhNYedT（PMO / VP / 项目名）
AITABLE_BASE = "wva2dxOW4Y6GgZ4yukXOlvAEVbkz3BRL"
AITABLE_TABLE = "hhNYedT"
F_PROJECT = "FMnI15B"     # 项目名
F_PMO = "L7UtzCX"         # 区域PMO
F_VP = "QaSwDr1"          # 区域生产副总

# 0映射表（场站第一负责人 = 项目负责人）
MAP_BASE = "1zknDm0WRaNwg5KkI0BwAMRy8BQEx5rG"
MAP_TABLE = "Dzp793M"
F_OWNER = "IFHB40F"       # 场站第一负责人

# 固定参会人（会议组织人 金惠良）
FIXED_ATTENDEES = ["金惠良", "刘冰", "贾兴威"]

# 产品系列 → 判定天数（试运营总天数）
SERIES_DAYS = {
    "HS100": 20, "HS200": 20,
    "HS300": 25, "HS400": 25,
    "HS500": 40, "500PRO": 40,
}

# 区域 → 新入场项目管理群 openConversationId（D-1 提醒用）
REGION_GROUPS = {
    "华北": "cidKS3sDmNjD8UuAhpHtJRsMw==",
    "华东": "cidIT5gaz05lF5c83eSL79DWA==",
    "西北": "cidBEbZIYbrhcfuk1Ek7a65Mg==",
    "华南": "cidFkPXMgWRrUmtvpHaHls9LQ==",
    "东北": "cidjvjoL62+ICGGQY2LqRLFnw==",
    "西南": "cida7OxNtXrwpCwXiV9dFr8Pw==",
    "华中": "cidFwX9rxqkykUiEaqzfUbWaA==",
}

# 判定会议日程标题与富文本描述（模板见 新入场项目日报/knowledge/判定会议模板.md）
MEETING_TITLE_TMPL = "{name}试运营判定会议"


def _agenda_html(name: str) -> str:
    return (
        f"<h2>{name} 试运营判定会议</h2>"
        "<h3>会议组织：金惠良（交付管理部）</h3><hr/>"
        "<h3>会议议程</h3>"
        "<ol>"
        "<li>项目负责人汇报试运营期整体情况（对接/计划执行/设备体检）</li>"
        "<li>四大核心维度评估：合同指标达成率、成本偏差控制、客户满意度、年度运营计划</li>"
        "<li>风险定级及遗留问题清单确认</li>"
        "<li>PMO出具判定结论：通过转入正式运营 / 延长试运营（最长15天）</li>"
        "<li>后续工作安排</li>"
        "</ol>"
        "<p><strong>备注：区域生产副总如无法出席，可委托授权人参加。如与会人员有误，请相关人员自行修正。</strong></p><hr/>"
        "<h3>📋 试运营期管理流程（一页纸SOP）</h3>"
        "<p><strong>⏱ 试运营期按产品系列分档：</strong></p>"
        "<table border=\"1\">"
        "<tr><th>产品系列</th><th>总天数</th><th>磨合期</th><th>观测期</th><th>调整期</th><th>判定日</th></tr>"
        "<tr><td>HS100/HS200</td><td>20天</td><td>D1-5</td><td>D6-15</td><td>D16-19</td><td>D20</td></tr>"
        "<tr><td>HS300/HS400</td><td>25天</td><td>D1-7</td><td>D8-18</td><td>D19-24</td><td>D25</td></tr>"
        "<tr><td>HS500/500Pro</td><td>40天</td><td>D1-10</td><td>D11-30</td><td>D31-39</td><td>D40</td></tr>"
        "</table>"
        "<h4>四阶段标准化管理</h4><ol>"
        "<li><b>磨合期</b> → 客户现场负责人对接、项目数据接入公司数字化系统、启动会暨交底会、交付执行计划编制落实</li>"
        "<li><b>观测期</b> → 全负荷测试、每日标准化动作+日报、客户沟通</li>"
        "<li><b>调整期</b> → 问题集中攻坚、纠偏措施制定与验证</li>"
        "<li><b>判定转正式</b> → 提交总结报告、PMO评审出具判定结论</li>"
        "</ol>"
        "<h4>达标判定四要素</h4><ul>"
        "<li>✅ 未触发合同考核指标（发电量/可利用率/PR值）</li>"
        "<li>✅ 成本偏差 ≤1万元</li>"
        "<li>✅ 客户无投诉（口头/书面）</li>"
        "<li>🔴 年度运营计划经区域、事业部会审通过（红线项）</li>"
        "</ul>"
        "<h4>🔴 红线规定（强制执行）</h4>"
        "<p>项目转正式运营前，必须提交项目年度运营计划并经区域、事业部会审通过后方可进入正式运营期。</p>"
        "<h4>判定结论</h4>"
        "<p>通过 → PMO签发《转正常运营通知书》<br/>不通过 → 延长试运营期（最长15天）</p>"
    )


# ── dws CLI 封装（与 aitable.py 一致）────────────────────

def _dws(*args: str) -> dict:
    cmd = ["dws", *args, "--format", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    output = result.stdout.strip()
    if not output:
        raise RuntimeError(f"dws stdout empty, stderr: {result.stderr[:200]}")
    return json.loads(output)


def age_in_days(series: str | None) -> int | None:
    """产品系列 → 试运营判定天数（HS100/200=20，HS300/400=25，HS500/500Pro=40）"""
    if not series:
        return None
    key = series.strip().upper()
    if key.startswith("HS100") or key.startswith("HS200"):
        return 20
    if key.startswith("HS300") or key.startswith("HS400"):
        return 25
    if key.startswith("HS500") or "500" in key:
        return 40
    return SERIES_DAYS.get(key)


def compute_judgment_date(entry: date, series: str | None) -> date | None:
    """判定日 = 入场日期 + 判定天数 - 1"""
    days = age_in_days(series)
    if days is None:
        return None
    return entry + timedelta(days=days - 1)


def resolve_user_id_by_name(name: str) -> str | None:
    """姓名 → 钉钉 userId（dws aisearch person）"""
    name = (name or "").strip()
    if not name:
        return None
    try:
        data = _dws("aisearch", "person", "--keyword", name, "--dimension", "name")
        people = data.get("result", data)
        if isinstance(people, list) and people:
            return people[0].get("userId") or people[0].get("openDingTalkId")
    except Exception as e:
        print(f"[judgment-meeting] 解析参会人 {name} 失败: {e}")
    return None


def _cell(cells: dict, fid: str) -> str:
    v = cells.get(fid)
    if v is None:
        return ""
    if isinstance(v, dict):
        return v.get("name", "")
    if isinstance(v, list) and v:
        return v[0].get("name", "") if isinstance(v[0], dict) else str(v[0])
    return str(v)


def _query_aitable(base: str, table: str) -> list[dict]:
    data = _dws("aitable", "record", "query", "--base-id", base,
                "--table-id", table, "--all", "--page-limit", "0")
    result = data.get("data", data.get("result", data))
    return result.get("records", [])


def _match_project_record(project_name: str, table: str, base: str) -> dict | None:
    """按项目名在 Aitable 表里匹配一条记录"""
    for r in _query_aitable(base, table):
        cells = r.get("cells", {})
        if _cell(cells, F_PROJECT) == project_name:
            return r
    return None


def resolve_dynamic_attendees(project_name: str) -> list[str]:
    """动态 3 人（项目负责人 / 区域PMO / 区域生产副总）的姓名列表。

    实时拉 Aitable（对齐贾总版）：
    - 项目负责人 = 0映射表「场站第一负责人」字段 IFHB40F
    - 区域PMO = 新入场项目清单表 hhNYedT 字段 L7UtzCX
    - 区域生产副总 = hhNYedT 字段 QaSwDr1
    多来源按记录各自独立匹配，缺哪个跳过哪个。
    """
    names: list[str] = []

    # 项目负责人（0映射表）
    try:
        for r in _query_aitable(MAP_BASE, MAP_TABLE):
            cells = r.get("cells", {})
            if _cell(cells, "xOTtpZc") == project_name or _cell(cells, "TMaSENb") == project_name:
                owner = _cell(cells, F_OWNER)
                if owner:
                    names.append(owner)
                break
    except Exception as e:
        print(f"[judgment-meeting] 查询项目负责人失败: {e}")

    # 区域PMO / 区域生产副总（新入场项目清单表 hhNYedT）
    try:
        rec = _match_project_record(project_name, AITABLE_TABLE, AITABLE_BASE)
        if rec:
            cells = rec.get("cells", {})
            pmo = _cell(cells, F_PMO)
            vp = _cell(cells, F_VP)
            for n in (pmo, vp):
                # 同名/含「、」多人时逐段解析
                if not n:
                    continue
                for seg in n.replace("、", ",").split(","):
                    seg = seg.strip()
                    if seg and seg not in names and seg not in FIXED_ATTENDEES:
                        names.append(seg)
    except Exception as e:
        print(f"[judgment-meeting] 查询 PMO/VP 失败: {e}")

    return names


def build_meeting_args(project_name: str, entry: date, series: str | None) -> dict | None:
    """组装 dws calendar event create 的参数（不含调用）"""
    jd = compute_judgment_date(entry, series)
    if jd is None:
        return None
    start = f"{jd.isoformat()}T10:00:00+08:00"
    end = f"{jd.isoformat()}T11:00:00+08:00"

    user_ids: list[str] = []
    for name in FIXED_ATTENDEES:
        uid = resolve_user_id_by_name(name)
        if uid:
            user_ids.append(uid)

    for name in resolve_dynamic_attendees(project_name):
        uid = resolve_user_id_by_name(name)
        if uid and uid not in user_ids:
            user_ids.append(uid)

    return {
        "title": MEETING_TITLE_TMPL.format(name=project_name),
        "start": start,
        "end": end,
        "judgment_date": jd,
        "attendees": user_ids,
        "rich_text_desc": _agenda_html(project_name),
    }


def _create_event(args: dict) -> str | None:
    """调用 dws calendar event create，返回 eventId"""
    cmd = ["calendar", "event", "create",
           "--title", args["title"],
           "--start", args["start"],
           "--end", args["end"],
           "--rich-text-desc", args["rich_text_desc"]]
    if args.get("attendees"):
        cmd += ["--attendees", ",".join(args["attendees"])]
    data = _dws(*cmd)
    inner = data.get("result", data)
    if isinstance(inner, dict):
        return inner.get("eventId") or inner.get("id")
    return data.get("eventId") or data.get("id")


def create_or_update_judgment_meeting(project: Any, db: Any) -> dict:
    """项目入场日期/系列确定后，自动创建（或改期）判定会日程。同步执行，失败不抛出。"""
    if not project.entry_date or not project.product_series:
        return {"skipped": True, "reason": "缺入场日期或产品系列"}
    new_jd = compute_judgment_date(project.entry_date, project.product_series)
    if new_jd is None:
        return {"skipped": True, "reason": f"未知产品系列 {project.product_series}"}

    # 幂等：判定日未变且已建过 → 跳过
    if project.judgment_event_id and project.judgment_date == new_jd:
        return {"skipped": True, "reason": "判定会日程已存在且未变", "event_id": project.judgment_event_id}

    args = build_meeting_args(project.name, project.entry_date, project.product_series)
    if args is None:
        return {"skipped": True, "reason": "无法组装日程参数"}

    try:
        event_id = _create_event(args)
        project.judgment_date = new_jd
        project.judgment_event_id = event_id or project.judgment_event_id
        project.judgment_status = "created" if event_id else "failed"
        project.judgment_error = None if event_id else "dws 未返回 eventId"
        db.commit()
        return {"ok": bool(event_id), "event_id": event_id, "attendees": len(args["attendees"])}
    except Exception as e:
        project.judgment_status = "failed"
        project.judgment_error = str(e)[:500]
        db.commit()
        return {"ok": False, "error": str(e)}


def send_d1_reminder(project: Any) -> dict:
    """判定日前 1 天（D-1）向区域群发提醒"""
    if not project.judgment_date:
        return {"skipped": True, "reason": "无判定日"}
    if (project.judgment_date - date.today()).days != 1:
        return {"skipped": True, "reason": "非 D-1"}

    group = (REGION_GROUPS.get(project.region or "") or "")
    text = (
        f"📢 判定会提醒\n\n"
        f"项目「{project.name}」将于明天（{project.judgment_date.isoformat()}）上午 10:00 进行试运营判定会议，"
        f"请项目负责人与区域 PMO/生产副总提前准备试运营总结报告与年度运营计划。"
    )
    if not group:
        return {"skipped": True, "reason": "区域群未配置"}
    try:
        # 群消息发送不接受 --format json，走裸 subprocess（对齐贾总版 dws chat）
        cmd = ["dws", "chat", "message", "send", "--group", group, "--text", text, "--ai-tag=false", "-y"]
        subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
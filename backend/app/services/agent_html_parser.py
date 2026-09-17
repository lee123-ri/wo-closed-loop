"""可靠性Agent《指标异常处置SOP》复盘 HTML → 出参 JSON 解析器。

解析荣的 Agent 生成的「…指标异常处置模拟与复盘.html」，
把里面的 SMART 工单（<div class='order'> 块）抽成 workorder 出参契约（对齐 workorder.schema.json）。

结构假设（荣的 Agent 生成，规整）：
  <div class='order'>
    <h3><span class='pill'>分型</span>工单标题</h3>
    <div class='smarts'>
      <b>S 具体任务</b><span>…</span>
      <b>M 目标值</b><span>…</span>
      <b>A 完成标志</b><span>…</span>
      <b>R 责任方</b><span>执行＝X；监管＝Y</span>
      <b>T 时限</b><span>…</span>
      <b>依据事件</b><span>…</span>
    </div>
  </div>
仅用标准库（html.unescape + re），不依赖 bs4/lxml。
"""
from __future__ import annotations

import re
from html import unescape

# pill 首段 → 可靠性归因分型（workorder.schema.json 的 subtype 枚举）
_PILL_SUBTYPE = {
    "超时": "超时型",
    "高频": "高频型",
    "共性": "共性缺陷型",
    "紧急": "紧急确认类",
}

_FIELD_KEY = {
    "S 具体任务": "S",
    "M 目标值": "M",
    "A 完成标志": "A",
    "R 责任方": "R",
    "T 时限": "T",
    "依据事件": "evidence",
}


def _strip(s: str) -> str:
    """去标签 + unescape + 去首尾空白/多余空行。"""
    s = re.sub(r"<[^>]+>", "", s or "")
    s = unescape(s)
    s = re.sub(r"[ \t　]+", " ", s)  # 压空白
    s = re.sub(r"\s*\n\s*", "\n", s)
    return s.strip()


def _slug(s: str) -> str:
    """标题 → 稳定 idempotency key（保留中英文数字，其余转连字符）。"""
    return re.sub(r"[^\w一-鿿]+", "-", s).strip("-")[:120]


def _parse_deadline_days(t_text: str) -> int:
    """从 T 时限抽取截止天数：取「N日」最大值；即时/立即 → 0；默认 7。"""
    days = [int(d) for d in re.findall(r"(\d+)\s*日", t_text or "")]
    if days:
        return max(days)
    if "即时" in (t_text or "") or "立即" in (t_text or ""):
        return 0
    return 7


def _parse_roles(r_text: str) -> tuple[dict | None, dict | None]:
    """R 责任方 → (责任人, 审批人)。格式：执行＝X（…）；监管＝Y（…）。"""
    responsible = approver = None
    for part in (r_text or "").split("；"):
        if "执行" in part:
            m = re.search(r"执行[=＝]\s*(.+?)(?:[（(]|$)", part)
            if m:
                responsible = {"name": _strip(m.group(1)), "role": "执行方"}
        elif "监管" in part:
            m = re.search(r"监管[=＝]\s*(.+?)(?:[（(]|$)", part)
            if m:
                approver = {"name": _strip(m.group(1)), "role": "监管方"}
    return responsible, approver


def _parse_evidence(text: str, title: str) -> dict:
    """依据事件 → evidence 单条（date/device/fault/detail/eam_ref）。"""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", text or "")
    parts = [p for p in (title or "").split("·") if p]
    device = parts[1] if len(parts) >= 2 else ""
    fault = "·".join(parts[2:]) if len(parts) >= 3 else ""
    return {
        "date": m.group(1) if m else "",
        "device": device,
        "fault": fault,
        "detail": (text or "").strip(),
        "eam_ref": (text or "").strip(),
    }


def parse_agent_html(html_text: str, oa_type: str = "设备预警工单") -> dict:
    """解析复盘 HTML → 出参批次 dict（project + trigger + workorders）。"""
    # 项目：h1 「泰康师宗 FLE50 指标异常处置模拟与复盘」第一个词
    project = ""
    mh = re.search(r"<h1[^>]*>(.*?)</h1>", html_text or "", re.S)
    if mh:
        project = _strip(mh.group(1)).split("·")[0].split(" ")[0].split("/")[0].strip()
    if not project:
        # 兜底：取第一个 order 标题前缀
        mo = re.search(r"<div class=['\"]?order[^>]*>.*?<h3[^>]*>(.*?)</h3>", html_text or "", re.S)
        if mo:
            title = _strip(mo.group(1))
            project = title.split("·")[0].strip()

    # 指标 + 周期：从「第一部分」note 抽，如「4~5月 FLE50 = 9.70 / 14.03，超阈值5」
    indicator = "FLE50" if re.search(r"\bFLE50\b", html_text or "") else "可靠性"
    period = ""
    mp = re.search(r"(\d+)\s*~\s*(\d+)\s*月", html_text or "")
    if mp:
        period = f"{mp.group(1)}~{mp.group(2)}月"

    # 切出每个工单块
    blocks = re.split(r"<div class=['\"]?order[^>]*>", html_text or "")[1:]
    workorders = []
    for blk in blocks:
        mh3 = re.search(r"<h3[^>]*>(.*?)</h3>", blk, re.S)
        if not mh3:
            continue
        # pill + title
        pill = ""
        mpill = re.search(r"<span class=['\"]pill['\"]>(.*?)</span>", mh3.group(1), re.S)
        if mpill:
            pill = _strip(mpill.group(1))
        title = _strip(re.sub(r"<span class=['\"]pill['\"]>.*?</span>", "", mh3.group(1), flags=re.S))

        # S/M/A/R/T/依据事件
        fields: dict[str, str] = {}
        for label, val in re.findall(r"<b>([^<]+)</b>\s*<span[^>]*>(.*?)</span>", blk, re.S):
            key = _FIELD_KEY.get(_strip(label))
            if key:
                fields[key] = _strip(val)

        responsible, approver = _parse_roles(fields.get("R", ""))

        workorders.append({
            "workorder_id": _slug(title),
            "title": title,
            "subtype": next((v for k, v in _PILL_SUBTYPE.items() if pill.startswith(k)), "超时型"),
            "oa_type": oa_type,
            "reason": fields.get("evidence", ""),
            "action": fields.get("S", ""),
            "target_metric": fields.get("M", ""),
            "responsible": responsible,
            "approver": approver,
            "deadline_days": _parse_deadline_days(fields.get("T", "")),
            "deadline_basis": fields.get("T", ""),
            "completion_criteria": fields.get("A", ""),
            "evidence": [_parse_evidence(fields.get("evidence", ""), title)],
            "smart": {
                "S": fields.get("S", ""),
                "M": fields.get("M", ""),
                "A": fields.get("A", ""),
                "R": fields.get("R", ""),
                "T": fields.get("T", ""),
            },
        })

    return {
        "project": project,
        "trigger": {"indicator": indicator, "period": period, "value": None, "threshold": 5},
        "workorders": workorders,
    }
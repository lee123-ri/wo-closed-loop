"""LLM 解析服务：调通义千问（百炼）从听记文本提取工单结构化数据。

无 DASHSCOPE_API_KEY 时自动降级到正则解析（parsing_rules 评分）。
"""
import json
import re
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import ParsingRule, PriorityRule, User
from app.services.priority_service import match_priority

settings = get_settings()

_SYSTEM_PROMPT = """[STAGE:workorder-extract] 你是新能源电站运维工单分析助手。
从用户提供的听记内容中提取所有需要跟进的事项，输出为 JSON 数组。
对每个工单返回字段：title(标题), type(纠偏|客户沟通|关系维护|隐患整改|非标任务|其他),
priority(P1|P2|P3), person(责任人姓名), project(项目名称), deadline(YYYY-MM-DD), reason(触发原因), action(行动要求)。

优先级判定：P1=涉及安全/扣款/停运；P2=投诉/告警/会议决议/隐患；P3=计划/例行/培训/汇报。
若信息缺失，字段留空字符串。严格只返回 JSON 数组，不要解释文字。"""


def parse_with_llm(text: str) -> list[dict]:
    """调通义千问解析"""
    if not settings.dashscope_api_key:
        return []
    try:
        resp = httpx.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        # 兼容 {workorders: [...]} 或直接 [...]
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    return v
        if isinstance(data, list):
            return data
    except Exception as e:
        print(f"[llm] 解析失败，降级正则: {e}")
    return []


def parse_with_regex(text: str) -> list[dict]:
    """正则评分解析（fallback 或无 LLM 时主路径）

    按行切分候选条目，用 parsing_rules 评分，≥阈值的为工单候选。
    """
    db = SessionLocal()
    try:
        rules = (
            db.query(ParsingRule)
            .filter(ParsingRule.enabled.is_(True))
            .order_by(ParsingRule.sort_order)
            .all()
        )
    finally:
        db.close()

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    candidates: list[dict] = []
    current: dict | None = None
    for line in lines:
        m = re.match(r"^(\d+)[\.、\)]\s*(.+)", line) or re.match(r"^[-•]\s*(.+)", line)
        if m:
            if current:
                candidates.append(current)
            current = {"text": m.group(2) or m.group(1), "score": 0, "reasons": []}
        elif current:
            current["text"] += " " + line
    if current:
        candidates.append(current)

    if not candidates:
        candidates = [{"text": l, "score": 0, "reasons": []} for l in lines if len(l) > 10]

    THRESHOLD = 5
    out: list[dict] = []
    for c in candidates:
        for rule in rules:
            try:
                if re.search(rule.pattern, c["text"], re.IGNORECASE):
                    c["score"] += rule.weight
                    c["reasons"].append(rule.name)
            except re.error:
                continue
        if c["score"] >= THRESHOLD:
            out.append(_enrich_candidate(c, db))
        else:
            out.append({**_enrich_candidate(c, db), "low_confidence": True, "score": c["score"], "reasons": c["reasons"]})
    return out


def _enrich_candidate(c: dict, db) -> dict:
    """从候选文本提取 person/project/priority/deadline"""
    text = c["text"]
    db2 = SessionLocal()
    # 匹配责任人
    person = None
    users = db2.query(User).filter(User.role == "executor").all()
    for u in users:
        if u.name in text:
            person = u.name
            break
    # 匹配项目
    project = None
    from app.models import Project
    for p in db2.query(Project).all():
        if p.name[:4] in text or p.name in text:
            project = p.name
            break
    db2.close()
    priority = match_priority(db, text, "")
    return {
        "title": text[:60],
        "person": person,
        "project": project,
        "priority": priority,
        "raw": text,
        "score": c.get("score", 0),
        "reasons": c.get("reasons", []),
    }


def parse_minutes(text: str) -> dict:
    """主入口：先试 LLM，失败/无 key 降级正则"""
    if settings.dashscope_api_key:
        items = parse_with_llm(text)
        if items:
            return {"engine": "llm", "items": items, "count": len(items)}
    items = parse_with_regex(text)
    return {"engine": "regex", "items": items, "count": len(items)}

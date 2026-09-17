"""项目编码规则（2026-09-03 定稿）：统一 `PRJ-<四位流水>`，系统自动分配、创建后不可改。

历史问题：手工新增自由填码、aitable 同步用「名称截断」凑码（出现「三一东丰」
「三一平台村、-1」这类杂码），与 PRJ-xxxx 并存，编码列失去可读秩序。
规则收编后所有建项入口（手工新增 / aitable 同步 / seed）都走 next_project_code。
"""
import re

from sqlalchemy.orm import Session

from app.models import Project

PROJECT_CODE_RE = re.compile(r"^PRJ-(\d{4,})$")


def _seq(code: str) -> int | None:
    m = PROJECT_CODE_RE.match(code)
    return int(m.group(1)) if m else None


def next_project_code(db: Session) -> str:
    """按库内最大 PRJ 序号 +1 生成新编码（只增不回收，避免历史引用混淆）。"""
    codes = [c for (c,) in db.query(Project.code).filter(Project.code.like("PRJ-%")).all()]
    nxt = max((s for s in map(_seq, codes) if s is not None), default=0) + 1
    return f"PRJ-{nxt:04d}"


def plan_code_normalization(pairs: list[tuple[int, str]]) -> dict[int, str]:
    """历史杂码归一计划：不合规编码按 id 顺序续编，合规码原样保留。

    pairs: [(project_id, code)]，返回 {project_id: new_code}。
    """
    nxt = max((s for s in map(_seq, (c for _, c in pairs)) if s is not None), default=0) + 1
    plan: dict[int, str] = {}
    for pid, code in sorted(pairs, key=lambda p: p[0]):
        if _seq(code) is None:
            plan[pid] = f"PRJ-{nxt:04d}"
            nxt += 1
    return plan
